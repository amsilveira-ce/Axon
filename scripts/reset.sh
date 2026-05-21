# scripts/reset.sh
# Zera toda a configuração do Axon e começa do zero.
# Uso: bash scripts/reset.sh [--yes]

set -euo pipefail

# ── cores ─────────────────────────────────────────────────────────────────────
RED='\033[0;31m'
YELLOW='\033[1;33m'
GREEN='\033[0;32m'
DIM='\033[2m'
RESET='\033[0m'

# ── flags ─────────────────────────────────────────────────────────────────────
YES=false
for arg in "$@"; do
  [[ "$arg" == "--yes" || "$arg" == "-y" ]] && YES=true
done

# ── confirmação ───────────────────────────────────────────────────────────────
echo ""
echo -e "  ${YELLOW}▲  Axon reset${RESET}"
echo ""
echo -e "  ${DIM}This will permanently delete:${RESET}"
echo -e "  ${DIM}  axon.config.json${RESET}"
echo -e "  ${DIM}  .axon/  (registry, tokens, sessions, memory, traces)${RESET}"
echo ""

if [[ "$YES" != true ]]; then
  read -r -p "  Continue? [y/N] " confirm
  echo ""
  if [[ ! "$confirm" =~ ^[Yy]$ ]]; then
    echo -e "  ${DIM}Aborted.${RESET}"
    echo ""
    exit 0
  fi
fi

removed=0

if [[ -f "axon.config.json" ]]; then
  rm axon.config.json
  echo -e "  ${DIM}✓ axon.config.json removed${RESET}"
  ((removed++))
fi

if [[ -d ".axon" ]]; then
  rm -rf .axon
  echo -e "  ${DIM}✓ .axon/ removed${RESET}"
  ((removed++))
fi

if [[ $removed -eq 0 ]]; then
  echo -e "  ${DIM}Nothing to remove — already clean.${RESET}"
  echo ""
  exit 0
fi

echo ""
echo -e "  ${DIM}Re-initializing...${RESET}"
echo ""

axon init --defaults

echo ""
echo -e "  ${GREEN}◆  Reset complete — ready to go.${RESET}"
echo ""