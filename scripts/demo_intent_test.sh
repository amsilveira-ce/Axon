#!/usr/bin/env bash
#
# scripts/demo_intent_test.sh
#
# Sobe a infra que o Principal Agent precisa e roda o pipeline COMPLETO,
# etapa por etapa, via `axon pa intent test`:
#
#   IntentExtraction → Decomposer (+DAG) → Resolver → Executor
#
# Uso:
#   ./scripts/demo_intent_test.sh
#   ./scripts/demo_intent_test.sh "do a deep research on arXiv about graph neural networks"
#
# A query padrão usa `web_search` (tool LOCAL), então o Resolver resolve no pool
# local e o Executor chama a tool stdio direto — só o Ollama é obrigatório aqui.
# Mesmo assim subimos os Gateway Agents configurados, para queries que precisem
# deles (ex.: deep_research → arxiv via ga_proxy).

set -euo pipefail

QUERY="${1:-search the web for the latest news about AI}"
OLLAMA_URL="${OLLAMA_HOST:-http://localhost:11434}"

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

PY="$ROOT/.venv/bin/python"
if [ -x "$ROOT/.venv/bin/axon" ]; then
  AXON="$ROOT/.venv/bin/axon"
else
  AXON="$PY -m axon.cli.main"
fi

STARTED_PIDS=()

cleanup() {
  if [ "${#STARTED_PIDS[@]}" -gt 0 ]; then
    echo
    echo "→ encerrando servers que este script subiu..."
    for pid in "${STARTED_PIDS[@]}"; do
      kill "$pid" 2>/dev/null || true
    done
  fi
}
trap cleanup EXIT INT TERM

hr() { printf '─%.0s' {1..70}; echo; }

# ── 0. pré-requisitos ─────────────────────────────────────────────────────────
[ -f axon.config.json ] || {
  echo "✗ axon.config.json não encontrado — rode 'axon init' primeiro."
  exit 1
}

# ── 1. Ollama (obrigatório: IntentExtractor + Decomposer usam o LLM) ──────────
if ! curl -sf "$OLLAMA_URL/api/tags" >/dev/null 2>&1; then
  echo "✗ Ollama não respondeu em $OLLAMA_URL"
  echo "  inicie:  ollama serve"
  echo "  modelo:  ollama pull deepseek-r1:14b"
  exit 1
fi
echo "✓ Ollama ok ($OLLAMA_URL)"

# ── 2. sobe os Gateway Agents que o PA conhece (idempotente) ──────────────────
wait_health() {
  local port="$1" tries=40
  until curl -sf "http://127.0.0.1:$port/health" >/dev/null 2>&1; do
    tries=$((tries - 1))
    [ "$tries" -le 0 ] && return 1
    sleep 0.5
  done
  return 0
}

start_ga() {
  local ctx="$1" port="$2"
  if curl -sf "http://127.0.0.1:$port/health" >/dev/null 2>&1; then
    echo "✓ GA '$ctx' já está no ar (porta $port)"
    return 0
  fi
  echo "→ subindo GA '$ctx' na porta $port  (log: /tmp/axon-ga-$ctx.log)"
  AXON_GA_CONTEXT="$ctx" $AXON ga serve --context "$ctx" >"/tmp/axon-ga-$ctx.log" 2>&1 &
  STARTED_PIDS+=("$!")
  if wait_health "$port"; then
    echo "✓ GA '$ctx' saudável"
  else
    echo "▲ GA '$ctx' não respondeu a tempo — seguindo (veja /tmp/axon-ga-$ctx.log)"
  fi
}

# lê (contexto, porta) da config e sobe cada um
while read -r ctx port; do
  [ -n "$ctx" ] && start_ga "$ctx" "$port"
done < <("$PY" -c "from axon.config import read_config; [print(k, v.port) for k, v in read_config().gateways.items()]")

# ── 3. roda o pipeline completo, etapa por etapa ──────────────────────────────
echo
hr
echo "  axon pa intent test --query \"$QUERY\""
hr
$AXON pa intent test --query "$QUERY"

echo
echo "✓ pronto. Para revisar a run persistida:  axon pa inspect"
