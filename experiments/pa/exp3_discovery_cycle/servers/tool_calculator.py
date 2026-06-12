"""
Local MCP stdio tool — calculator.

Listed in the experiment's local_tools.json: loaded by LocalResourcePool as
resource_id "local-calculator" and spawned per call by the PA's MCPClient
(pa_direct). No GA involved.
"""
import ast
import operator

from fastmcp import FastMCP

mcp = FastMCP("calculator")

_OPS = {
    ast.Add:  operator.add,
    ast.Sub:  operator.sub,
    ast.Mult: operator.mul,
    ast.Div:  operator.truediv,
}


def _eval(node: ast.expr) -> float:
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
        return node.value
    if isinstance(node, ast.BinOp) and type(node.op) in _OPS:
        return _OPS[type(node.op)](_eval(node.left), _eval(node.right))
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub):
        return -_eval(node.operand)
    raise ValueError(f"unsupported expression node: {ast.dump(node)}")


@mcp.tool
def calculate(expression: str) -> dict:
    """Evaluate a basic arithmetic expression (+ - * /)."""
    value = _eval(ast.parse(expression, mode="eval").body)
    return {"expression": expression, "result": value}


if __name__ == "__main__":
    mcp.run(show_banner=False)
