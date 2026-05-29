# poc_resolver — Resolver roadmap

Demonstrates the **Resolver** stage of the PA pipeline end to end, with all of
its steps visible: local pool, UCB gateway ranking, broadcast, the operator
policy filter, and the final per-subtask assignment.

See [docs/resolver.md](../../docs/resolver.md) for the full explanation.

## run_huggingface.py

Uses the **Hugging Face** MCP resource from
[docs/mcp-resources.md](../../docs/mcp-resources.md) (`mcp_http` · `bearer` ·
token in `HF_TOKEN`) as the resource a Gateway Agent returns. The GA transport
is stubbed — the real HTTP/retrieval path is covered by `poc_mcp_client` — so
this runs with **no Ollama and no real token**, focusing purely on the
Resolver's decisions.

```bash
python pocs/poc_resolver/run_huggingface.py
```

Two scenarios, same policy (`allow_paid=false`):

| scenario | `HF_TOKEN` | outcome |
|----------|-----------|---------|
| A | unset | Step 4 discards the resource (`set HF_TOKEN …`), fail-fast → subtask unresolved → `ResolverError` |
| B | set | resource passes → assigned to the subtask |

In both, the UCB reward for the gateway is recorded at resolution
(match + speed) and is **not** penalized when the policy discards the resource —
the restriction is the operator's, not the gateway's.

## Seeing the same roadmap from the CLI

With Ollama running and a Gateway Agent connected that exposes a `models`-tagged
resource, the full pipeline (Intent → Decomposer → Resolver) prints the same
Resolver steps:

```bash
axon pa intent test -q "find trending text-generation models on Hugging Face"
```
