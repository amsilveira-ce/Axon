# Resource resolution (the Resolver)

Between the **Planner** and the **Executor** sits the **Resolver**. The Planner
produces a `Plan` of subtasks, each declaring a `capability_required` (for
example `web_search` or `pdf_report`). The Resolver's job is to bind every
subtask to a concrete resource that can run it — a local tool, a cached resource,
or one discovered live from a Gateway Agent — and record that binding so the
Executor can run the plan without discovering anything itself.

```
Planner → Plan (subtasks, each with capability_required)
    ↓
Resolver
    1. local pool      already have a resource? use it (zero network)
    2. Gateway Agent   otherwise ask connected GAs (UCB1 ranking)
    3. policy filter   discard paid/over-cost resources (operator policy)
    4. token           discard resources whose auth token isn't configured
    ↓
state.resource_assignments  { subtask_id → ResolverResult }
```

It reads `state.plan.subtasks` and `state.resource_pool`; it writes
`state.resource_assignments` and may grow `state.resource_pool` with newly
discovered resources.

## What the Resolver produces

Each resolved subtask gets a `ResolverResult` in
`state.resource_assignments[subtask_id]`:

| field | meaning |
|-------|---------|
| `manifest` | the chosen `ResourceManifest` — ready for the Executor |
| `alternatives` | other manifests the GA returned, kept as fallbacks |
| `ga_url` | which gateway it came from (`""` for local) |
| `match_score` | retrieval quality reported by the GA (0..1) |
| `latency_ms` | how fast that GA answered |

`ga_url` is the discriminator the Executor uses later: an **empty `ga_url`** means
the resource came from the local pool and the gateway-affinity bandit must not be
touched for it; a **non-empty `ga_url`** means the resource was discovered through
a GA and its execution outcome feeds back into that GA's score.

## Step 1 — the local pool

Before any network call, the Resolver looks for a manifest in
`state.resource_pool` whose `capability_tags` cover the subtask's
`capability_required`. The pool is pre-populated at PA startup from two sources:

- **local tools** (`LocalResourcePool`) — see [Local tools](local-tools.md)
- **the resource cache** (`{data_dir}/pa/resource_cache.json`) — resources
  discovered through a GA on *previous* runs

When a candidate is found, the subtask is assigned with `ga_url=""` and **no GA is
contacted**. If several candidates match, the one with the best track record wins
(`success_count` high, `failure_count` low).

### Cache hit means zero broadcast

This is the expected behaviour on the *second* run of a similar flow: every
resource is already in the cache, so resolution is entirely local. To make that
hold across separate runs, the Resolver **persists** each resource it discovers
in Step 2 to the resource cache (`cache.put(manifest)`). The next run starts with
those manifests already in its pool.

```
run 1   capability not in pool → 1 broadcast → discovers tavily → writes cache
run 2   startup loads cache → capability already in pool → 0 broadcasts
```

## Step 2 — Gateway discovery

A subtask whose capability is not covered locally becomes a `PendingCapability`
and is sent to the connected Gateway Agents (`config.pa.gateways`).

### Choosing which GA to ask — UCB1 affinity

The Resolver does not blindly fan out to every gateway forever. It keeps a small
**multi-armed bandit** (`GAAffinityStore`, persisted in
`{data_dir}/pa/ga_affinity.json`) that learns, per `(gateway, capability)`, which
GA tends to return the best resource fastest. Gateways are ranked by their
**UCB1** score:

```
score(ga, cap) = reward_mean + √(2 · ln N / n)
```

where `n` is how many times this GA was queried for this capability and `N` the
total across all GAs. A GA never tried for a capability scores **+∞**, so it is
always explored first.

### Broadcast vs direct routing

- **Nothing known yet** (every candidate scores ∞) → **broadcast**: query all
  gateways, record a partial reward for each that answers, keep the best match.
- **A leader has emerged** → query the leader directly and fall back to the next
  ranked GA only if it returns nothing usable.

A gateway that is unreachable (connection refused, timeout) is logged and skipped
— it does not become a "tested" arm, so it stays at ∞ and is retried next time.

### The two-phase reward

Each query produces a reward in `[0,1]` combining three signals, in two phases:

| phase | when | signals | weight |
|-------|------|---------|--------|
| `update_partial` | at resolution | match quality + answer speed | `W_MATCH=0.5`, `W_SPEED=0.3` |
| `update_final` | after execution | did the chosen resource run successfully? | `W_EXEC=0.2` |

`update_partial` is recorded the moment a GA answers — it measures the gateway's
**retrieval quality**, independent of whether the operator's policy later allows
using the result. `update_final` is the Executor's job (see *Current status*).

### What comes back

The GA returns a list ranked by `match_score`. The Resolver keeps the best as
`ResolverResult.manifest` and the rest as `alternatives`, then appends the chosen
manifest to `state.resource_pool` and persists it to the resource cache.

## Step 3 — operator policy (paid / cost)

A GA returning a resource does not mean the PA is *allowed* to use it. The
Resolver first applies the operator's `ResourcePolicyConfig` (from
`axon.config.json`, under `pa.resource_policy`) — the **economic** rules:

| check | discarded when |
|-------|----------------|
| paid | `manifest.policy.is_paid` and `allow_paid = false` |
| cost | `cost_per_call > max_cost_per_call` |

A discarded resource is dropped silently from the candidate list — if the best
match is filtered out, a cheaper/free alternative can still win; if all are
filtered, the Resolver tries the next gateway.

## Step 4 — token resolution (auth)

A resource that passed policy still has to be *callable*. For any resource whose
`auth.scheme` is not `none` (and not `oauth`, which is interactive), the Resolver
resolves the token through the [TokenResolver](mcp-resources.md#architecture)
convention — a secret in `AXON_SECRET_<NAME>` or the resource's explicit
`env_var`:

```
auth.scheme = bearer, env_var = None
  → infer AXON_SECRET_HEALTH_SEARCH
  → token present  → resource is callable, keep it
  → token missing  → discard, log "set AXON_SECRET_HEALTH_SEARCH para habilitar"

auth.scheme = none
  → nothing to resolve, keep it
```

This is **fail-fast**: a resource you cannot authenticate to is dropped *here*,
at resolution, with an explicit diagnostic — not deep inside the Executor at run
time. There is no flag to disable it; an unusable resource is never added to the
pool.

> The token is **only verified**, never stored on the manifest. Manifests are
> persisted to `resource_cache.json` and to run traces, so writing the secret
> there would leak it. The Executor re-resolves the token from the environment at
> call time (the same path `MCPClient` already uses).

### The shared evaluator

Both checks live in `pa/policy.py`: `policy_violations()` (Step 3) and
`token_status()` (Step 4). `evaluate(manifest, policy)` runs both and is what the
CLI calls to render eligibility. The Resolver runs them as two distinct steps but
reaches the same verdict — **what the operator sees as "ready" in
`axon pa gateway resources` is exactly what the Resolver will accept.**

### UCB is not penalized

The bandit reward is recorded *before* Steps 3 and 4 run. A gateway that returns
an excellent match still earns its retrieval reward even if policy blocks the
resource or its token is missing — those are the operator's/environment's
concern, not a failure of the gateway's retrieval.

## The operator workflow

The policy filter is only useful if the operator can see what is available and
tune the policy. Three commands close that loop.

### 1. Connect a gateway — `axon pa gateway add`

```
axon pa gateway add http://ga-corp.example.com/
```

Runs three steps:

1. `GET /ga/card` — fetch the gateway card, check its `trust_level`.
2. `POST /pa/connect` — announce the PA to the GA (a `PACard`); the GA records
   the connection in `{data_dir}/ga/{context}/connections.json`.
3. `GET /ga/resources` — list the GA's resources and print an **eligibility
   table** evaluated against the current policy.

```
RECURSOS
resource             pricing       auth        status
health_search        gratuito      no-auth     ✓ pronto
healthcare-agent-1   gratuito      bearer ✗    ✗ set AXON_SECRET_HEALTHCARE_AGENT_1 …
resend               pago $0.0010  api_key ✗   ✗ recurso pago … · set AXON_SECRET_RESEND …
notion               pago          api_key ✓   ✗ recurso pago desabilitado
lab-search           gratuito      no-auth     ✓ pronto
2/6 prontos — configure os tokens ausentes e revise política
```

### 2. Inspect eligibility — `axon pa gateway resources`

Lists resources across all connected gateways with the same status. Filters:

| command | shows |
|---------|-------|
| `axon pa gateway resources` | everything, grouped by gateway |
| `… --filter eligible` | only resources ready to use |
| `… --filter auth-missing` | only resources needing a token (and which var) |
| `… --filter paid` | only paid resources — decide whether to allow them |
| `… --context ga-corp` | restrict to one gateway |

### 3. Set policy — `axon pa policy`

```
axon pa policy                              # show current policy
axon pa policy set --allow-paid true
axon pa policy set --max-cost-per-call 0.01
axon pa policy set --require-auth-setup true
axon pa policy set --match-threshold 0.75   # minimum GA match to accept
```

`match_threshold` feeds the Resolver's acceptance bar: a GA result scoring below
it leaves the capability pending.

A typical loop: connect a GA → `gateway resources` to see gaps → export the
missing `AXON_SECRET_*` tokens → `policy set --allow-paid true` if paid resources
are wanted → `gateway resources --filter eligible` to confirm.

## Where state lives

| file | written by | holds |
|------|-----------|-------|
| `{data_dir}/pa/resource_cache.json` | Resolver (Step 2) | manifests discovered via GA — pre-populates the pool next run; LRU-bounded by `pa.cache.max_size` |
| `{data_dir}/pa/ga_affinity.json` | Resolver (Step 2) | UCB1 reward table per `(gateway, capability)` |
| `{data_dir}/ga/{context}/connections.json` | GA (`POST /pa/connect`) | PAs that connected to this gateway |

## Current status

Steps 1–4 are implemented and wired into `PrincipalAgent.run()`. Resource
declarations (`is_paid`, `cost_per_call`) are captured at registration via
`axon add mcp --paid --cost-per-call` and travel registry → `/ga/resources` and
`/ga/resources/search` → manifest, so the policy filter and the eligibility table
reflect real pricing; auth is resolved live in Step 4.

The **Executor** is not built yet. Its hook is the final piece of the reward
loop: after running each subtask it calls `update_final(ga_url, capability,
execution_success)` on the affinity store, closing the two-phase reward for GA-
discovered resources (those with a non-empty `ga_url`). Until then, gateway
scores reflect retrieval quality (match + speed) but not execution success.

See also: [Architecture](architecture.md) · [Third-party MCP resources](mcp-resources.md) · [Local tools](local-tools.md) · [Configuration](configuration.md).
