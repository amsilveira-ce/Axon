# Resource Resolution

The **Resolver** is the bridge between planning and execution. After the Planner
produces a list of subtasks — each one declaring a capability it needs, like
`web_search` or `pdf_report` — the Resolver's job is to answer one question for
every subtask: *which concrete resource will run this?*

That binding happens before the Executor touches anything. By the time execution
starts, every subtask either has a verified, policy-approved resource assigned to
it, or it has been explicitly marked as skipped or failed. The Executor never
discovers resources on its own.

## Overview

```
Planner → Plan
          └── subtask A  (capability_required: web_search)
          └── subtask B  (capability_required: pdf_report)
                │
                ▼
           RESOLVER
         ┌─────────────────────────────────────────────────┐
         │  Step 1  local pool     zero-network fast path  │
         │  Step 2  Gateway Agent  UCB1-ranked discovery   │
         │  Step 3  policy filter  economic rules          │
         │  Step 4  token check    auth fail-fast          │
         └─────────────────────────────────────────────────┘
                │
                ▼
   state.resource_assignments
   { subtask_id → ResolverResult }
                │
                ▼
           EXECUTOR
```

The Resolver reads `state.plan.subtasks` and `state.resource_pool`. It writes
`state.resource_assignments` and may grow `state.resource_pool` with newly
discovered resources that are then cached for future runs.

> **Note:** Steps 3 and 4 — policy and token — are independent of each other but
> both must pass. A free, properly-credentialed resource that exceeds
> `max_cost_per_call` is rejected just as firmly as a resource with a missing
> token.

---

## What the Resolver produces

Each resolved subtask gets a `ResolverResult` stored in
`state.resource_assignments[subtask_id]`:

| Field | Type | Meaning |
|-------|------|---------|
| `manifest` | `ResourceManifest` | The chosen resource, ready for the Executor to call |
| `alternatives` | `list[ResourceManifest]` | Other candidates returned by the GA, kept as fallbacks |
| `ga_url` | `str` | Which gateway the resource came from; `""` if it came from the local pool |
| `match_score` | `float` (0–1) | Retrieval quality reported by the GA |
| `latency_ms` | `int` | How long that GA took to answer |

The `ga_url` field is the key discriminator for what happens after execution. An
**empty `ga_url`** means the resource is local — the gateway-affinity bandit is
not involved. A **non-empty `ga_url`** means a Gateway Agent found it, and the
execution outcome will feed back into that gateway's score.

---

## Step 1: Local pool lookup

Before making any network call, the Resolver checks `state.resource_pool` for a
manifest whose `capability_tags` already cover the required capability. The pool
is pre-populated at PA startup from two sources:

- **Local tools** (`LocalResourcePool`) — tools registered directly on this PA.
  See [Local tools](local-tools.md).
- **Resource cache** (`{data_dir}/pa/resource_cache.json`) — manifests discovered
  through a Gateway Agent on previous runs, persisted to disk so they survive
  restarts.

When a matching manifest is found locally, the subtask is assigned with
`ga_url=""` and **no Gateway Agent is contacted**. If multiple candidates match,
the one with the strongest track record wins: highest `success_count` and lowest
`failure_count`.

### Warm cache = zero network

On a second run of a similar flow, the cache is already populated from the first
run. Every capability resolves locally, with no broadcasts at all:

```
run 1   web_search not in pool
          → broadcast to gateways
          → discovers Tavily manifest
          → writes manifest to resource_cache.json

run 2   startup loads resource_cache.json
          → web_search already in pool
          → 0 network calls, assigned instantly
```

> **Tip:** If you want to force fresh discovery (for example, after adding a new
> gateway), delete `{data_dir}/pa/resource_cache.json` before running. The next
> run will broadcast and repopulate the cache from scratch.

---

## Step 2: Gateway Agent discovery

A subtask whose capability is not covered locally becomes a `PendingCapability`
and is sent to one or more connected Gateway Agents configured in
`config.pa.gateways`.

### The UCB1 affinity bandit

The Resolver does not fan out blindly to every gateway on every request. It
maintains a small **multi-armed bandit** — the `GAAffinityStore`, persisted in
`{data_dir}/pa/ga_affinity.json` — that learns, per `(gateway, capability)` pair,
which gateway tends to return the best resource fastest.

Think of it like a recommendation system that gets smarter with each request: it
tries unknown gateways eagerly at first, then gradually routes more traffic to
whichever one consistently delivers quality results.

Gateways are ranked by their **UCB1** score:

```
score(ga, cap) = reward_mean + √(2 · ln N / n)
```

Where:
- `n` = number of times this gateway has been queried for this capability
- `N` = total queries across all gateways for this capability
- `reward_mean` = average reward earned so far (see [two-phase reward](#the-two-phase-reward) below)

A gateway that has **never been tried** for a capability scores **+∞**, so it is
always explored before any gateway with a finite score. This guarantees every
gateway gets at least one chance.

### Broadcast vs. direct routing

The Resolver adapts its routing strategy based on how much it already knows:

| Situation | Strategy |
|-----------|----------|
| No gateway has been tried yet (all score ∞) | **Broadcast** — query all gateways in parallel, record a partial reward for each that answers, keep the best match |
| A clear leader has emerged | **Direct** — query the top-ranked gateway; fall back to the next-ranked only if it returns nothing usable |

> **Note:** A gateway that is unreachable — connection refused or timeout — is
> logged and skipped. It does **not** become a "tested" arm, so it retains its ∞
> score and will be retried on the next request.

### The two-phase reward

Bandit learning requires feedback. The Resolver records rewards in two phases so
that gateway scores reflect both *retrieval quality* and *execution success*:

| Phase | Triggered by | Signals measured | Weights |
|-------|-------------|-----------------|---------|
| `update_partial` | Gateway answers (at resolution time) | Match quality + answer speed | `W_MATCH=0.5`, `W_SPEED=0.3` |
| `update_final` | Subtask completes (at execution time) | Did the resource actually succeed? | `W_EXEC=0.2` |

`update_partial` is recorded the moment a GA answers, regardless of whether Steps
3 or 4 later discard the result. This is intentional: whether a resource is
allowed by policy or has a token configured is the operator's responsibility, not
a reflection of how well the gateway does retrieval.

`update_final` is triggered by the Executor after the subtask runs. The affinity
store is shared in-memory between the Resolver and the Executor, so both phases
accumulate on the same entry.

> **Tip:** Because `update_final` carries `W_EXEC=0.2`, a gateway that
> consistently returns plausible-looking resources that fail at execution time
> will gradually lose ranking to one whose resources actually work.

### What the gateway returns

The GA returns a ranked list of manifests. The Resolver keeps the top result as
`ResolverResult.manifest` and the rest as `alternatives`. The chosen manifest is
appended to `state.resource_pool` and persisted to the resource cache so it is
available locally on the next run.

---

## Step 3: Operator policy (paid / cost)

A Gateway Agent returning a resource does not mean the PA is allowed to use it.
The Resolver applies the operator's `ResourcePolicyConfig` — configured in
`axon.config.json` under `pa.resource_policy` — before accepting any discovery
result.

These are the **economic** rules:

| Check | Resource is discarded when… |
|-------|-----------------------------|
| Paid | `manifest.policy.is_paid` is true **and** `allow_paid = false` |
| Cost cap | `cost_per_call` exceeds `max_cost_per_call` |

When the best-ranked candidate is filtered out, the next alternative is
considered. If all candidates from a gateway are filtered, the Resolver moves on
to the next gateway. Policy filtering is transparent to the bandit: the gateway
still earned its `update_partial` reward for retrieval quality.

> **Warning:** Resource pricing (`is_paid`, `cost_per_call`) is captured at
> registration time via `axon add mcp --paid --cost-per-call` and travels through
> the registry into every `/ga/resources` response. The policy filter and the
> eligibility table shown by `axon pa gateway resources` reflect the same data —
> what you see in the CLI is exactly what the Resolver will accept or reject.

---

## Step 4: Token resolution (auth)

A resource that passes the policy check still has to be *callable*. For any
resource whose `auth.scheme` is not `none` (OAuth is handled interactively and is
not resolved here), the Resolver looks up a token through the
[TokenResolver](mcp-resources.md#architecture) convention.

The resolution order is:

1. If the manifest has an explicit `env_var`, use that environment variable.
2. Otherwise, infer the variable name as `AXON_SECRET_<RESOURCE_NAME_UPPERCASED>`.

```
auth.scheme = bearer, env_var = None
  → look up AXON_SECRET_HEALTH_SEARCH

  token found   → resource is callable → keep it
  token missing → discard resource
                → log: "set AXON_SECRET_HEALTH_SEARCH to enable this resource"

auth.scheme = none
  → no token needed → keep it
```

This is a **fail-fast** design: a resource you cannot authenticate to is dropped
at resolution time with an explicit diagnostic. It will never reach the Executor.
There is no flag to override this behavior.

> **Warning:** Tokens are **verified at resolution time but never stored on the
> manifest.** Manifests are persisted to `resource_cache.json` and included in
> run traces — writing secrets there would leak them. The Executor re-resolves the
> token from the environment at call time, following the same path used by
> `MCPClient`.

### One evaluator, consistent results

Both checks live in `pa/policy.py`:

- `policy_violations()` — runs Step 3
- `token_status()` — runs Step 4
- `evaluate(manifest, policy)` — runs both and is what the CLI calls to render
  eligibility

The Resolver runs them as two distinct steps, but the verdict is the same one the
CLI surfaces. **What the operator sees as "ready" in `axon pa gateway resources`
is exactly what the Resolver will accept.**

> **Note:** The bandit reward (`update_partial`) is recorded *before* Steps 3 and
> 4 run. A gateway that returns an excellent match still earns its retrieval
> reward even if the operator's policy or a missing token prevents using the
> result. Those are operational constraints, not retrieval failures.

---

## When nothing resolves: fallback strategies

If every gateway was queried and none returned an eligible resource for a
capability, the subtask is left unresolved. What happens next depends on two
things: whether the subtask is optional, and what the operator's
`fallback_strategy` is.

**Optional subtasks** (`is_optional = true`) are always marked `SKIPPED`,
regardless of policy. The plan was explicitly designed to run without them.

**Required subtasks** follow `pa.resource_policy.fallback_strategy`:

| `fallback_strategy` | What the Resolver does |
|---------------------|------------------------|
| `skip` | Marks the subtask `SKIPPED`; the plan continues and the Executor ignores it |
| `fail` | Records a `Failure` in `AgentState`, marks the subtask `FAILED`, and raises — the run halts |
| `ask_user` | Returns a `ClarificationNeeded` to the user (e.g., *"I couldn't find a resource for `health_search`. Do you have access to a system that provides this?"*) |

`ask_user` reuses the same clarification channel as the IntentExtractor, so an
unresolvable capability surfaces as a question to the user rather than a hard
crash. The default strategy is `ask_user`. A Resolver configured without an
explicit policy falls back to `fail`.

> **Note:** At most three clarification questions are raised at once, per the
> `ClarificationNeeded` contract. If more than three subtasks are unresolved, the
> extras are described in the clarification context so the user can address them
> in the same response.

---

## Operator workflow

The policy filter only matters if you can see what is available and tune it.
Three CLI commands give you that visibility.

### Step 1: Connect a gateway

```bash
axon pa gateway add http://ga-corp.example.com/
```

This runs three steps under the hood:

1. `GET /ga/card` — fetches the gateway card and checks its `trust_level`.
2. `POST /pa/connect` — announces this PA to the gateway (sends a `PACard`); the
   GA records the connection in `{data_dir}/ga/{context}/connections.json`.
3. `GET /ga/resources` — lists the gateway's resources and prints an eligibility
   table evaluated against the current policy.

**Expected output:**

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

The summary line tells you immediately how many resources are ready and why the
rest are blocked.

### Step 2: Inspect eligibility

```bash
axon pa gateway resources
```

Lists resources across all connected gateways with the same status columns. Use
filters to focus on what needs attention:

| Command | Shows |
|---------|-------|
| `axon pa gateway resources` | Everything, grouped by gateway |
| `… --filter eligible` | Only resources ready to use right now |
| `… --filter auth-missing` | Resources that need a token, with the exact variable name |
| `… --filter paid` | Paid resources — useful when deciding whether to enable them |
| `… --context ga-corp` | Restricts output to one specific gateway |

### Step 3: Tune policy

```bash
axon pa policy                               # show current policy
axon pa policy set --allow-paid true
axon pa policy set --max-cost-per-call 0.01
axon pa policy set --require-auth-setup true
axon pa policy set --match-threshold 0.75    # minimum GA match score to accept
```

`match_threshold` sets the Resolver's acceptance bar: a GA result whose
`match_score` falls below this value leaves the capability pending and triggers
fallback logic.

**A typical operator loop:**

```
1. axon pa gateway add <url>
       → see which resources are blocked and why

2. export AXON_SECRET_HEALTHCARE_AGENT_1=<token>
       → unblock auth-missing resources

3. axon pa policy set --allow-paid true
       → unblock paid resources if acceptable

4. axon pa gateway resources --filter eligible
       → confirm the Resolver will now accept these resources
```

---

## Where state lives

| File | Written by | Contains |
|------|-----------|----------|
| `{data_dir}/pa/resource_cache.json` | Resolver (Step 2) | Manifests discovered via GA; pre-populates the local pool on next startup. LRU-bounded by `pa.cache.max_size` |
| `{data_dir}/pa/ga_affinity.json` | Resolver (Step 2) | UCB1 reward table per `(gateway, capability)` pair |
| `{data_dir}/ga/{context}/connections.json` | GA (`POST /pa/connect`) | PAs that have connected to this gateway |

---

## Current implementation status

Steps 1–4 are fully implemented and wired into `PrincipalAgent.run()`.

Resource declarations (`is_paid`, `cost_per_call`) are captured at registration
via `axon add mcp --paid --cost-per-call` and flow through the registry into every
`/ga/resources` and `/ga/resources/search` response. The policy filter and the
eligibility table both read the same data.

The **Executor** is built and integrated. It walks the resolved plan and, for each
subtask:

- Gates on budget, dependency readiness, and the result cache
- Resolves ReWOO parameters (`{{artifact:name}}`)
- Calls the resource by `callable_by`:
  - `ga_proxy` → proxied through the GA's `/invoke` endpoint
  - `pa_direct` → called directly via the A2A or MCP clients, with fallback to
    `alternatives` on failure
- Records a `Fact` (success) or `Failure` in `AgentState`
- Calls `update_final(ga_url, capability, execution_success)` for GA-discovered
  resources — closing the two-phase reward loop so bandit scores reflect real
  execution outcomes, not just retrieval quality

Each run is persisted to
`{data_dir}/pa/traces/{session_id}/{request_id}.json` and can be inspected with:

```bash
axon pa inspect --session <session_id>
```

The trace includes the objective, the full plan with per-subtask status, all
recorded facts and failures, and budget usage.

---

## See also

- [Architecture](architecture.md) — how the Planner, Resolver, and Executor fit
  into the overall Principal Agent design
- [Third-party MCP resources](mcp-resources.md) — the `ResourceManifest` schema,
  `TokenResolver`, and how resources are registered
- [Local tools](local-tools.md) — how the `LocalResourcePool` is populated at
  startup
- [Configuration](configuration.md) — `pa.resource_policy`, gateway config, and
  cache settings
