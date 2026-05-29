#!/usr/bin/env bash
# scripts/serve_local_tools.sh
# Sobe o MCP server das tools locais do PA (calculate, web_search, read_file,
# get_datetime) via Streamable HTTP, para inspeção/registro.
#
# Uso:
#   bash scripts/serve_local_tools.sh [porta]    # porta padrão: 9000
#
# Depois, em outro terminal:
#   axon add mcp local-tools --http http://127.0.0.1:9000/mcp/ --tag math --tag web_search
#
# (Internamente o PA usa essas tools via stdio: "python -m axon.pa.tools.server".
#  Este script é só para deixá-las no ar como um endpoint conectável.)

set -euo pipefail

PORT="${1:-9000}"
HOST="127.0.0.1"

echo ""
echo "  ▲ Axon — local tools MCP server"
echo "    url:   http://${HOST}:${PORT}/mcp/"
echo "    tools: calculate, web_search, read_file, get_datetime"
echo "    (Ctrl+C para parar)"
echo ""

exec python -c "from axon.pa.tools.server import mcp; mcp.run(transport='http', host='${HOST}', port=${PORT})"
