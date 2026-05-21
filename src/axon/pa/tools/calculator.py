"""
pa/tools/calculator.py — Eval seguro de expressões matemáticas.

Usa ast.parse + NodeVisitor para permitir apenas operações seguras —
sem acesso a builtins, imports ou chamadas de função arbitrárias.
"""

from __future__ import annotations

import ast
import math
import operator


_SAFE_OPS = {
    ast.Add:      operator.add,
    ast.Sub:      operator.sub,
    ast.Mult:     operator.mul,
    ast.Div:      operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod:      operator.mod,
    ast.Pow:      operator.pow,
    ast.USub:     operator.neg,
    ast.UAdd:     operator.pos,
}

_SAFE_FUNCS = {
    "abs":   abs,
    "round": round,
    "sqrt":  math.sqrt,
    "ceil":  math.ceil,
    "floor": math.floor,
    "log":   math.log,
    "sin":   math.sin,
    "cos":   math.cos,
    "tan":   math.tan,
    "pi":    math.pi,
    "e":     math.e,
}


class _SafeEval(ast.NodeVisitor):
    def visit_Expression(self, node):
        return self.visit(node.body)

    def visit_Constant(self, node):
        if isinstance(node.value, (int, float)):
            return node.value
        raise ValueError(f"Unsupported constant type: {type(node.value)}")

    def visit_BinOp(self, node):
        op = _SAFE_OPS.get(type(node.op))
        if op is None:
            raise ValueError(f"Unsupported operator: {type(node.op).__name__}")
        return op(self.visit(node.left), self.visit(node.right))

    def visit_UnaryOp(self, node):
        op = _SAFE_OPS.get(type(node.op))
        if op is None:
            raise ValueError(f"Unsupported unary operator: {type(node.op).__name__}")
        return op(self.visit(node.operand))

    def visit_Call(self, node):
        if not isinstance(node.func, ast.Name):
            raise ValueError("Only simple function calls are allowed")
        name = node.func.id
        func = _SAFE_FUNCS.get(name)
        if func is None:
            raise ValueError(f"Function not allowed: {name}")
        args = [self.visit(a) for a in node.args]
        return func(*args)

    def visit_Name(self, node):
        val = _SAFE_FUNCS.get(node.id)
        if val is None:
            raise ValueError(f"Name not allowed: {node.id}")
        return val

    def generic_visit(self, node):
        raise ValueError(f"Unsupported node type: {type(node).__name__}")


def safe_eval(expression: str) -> float:
    """
    Avalia uma expressão matemática de forma segura.

    Suporta: +, -, *, /, //, %, **, abs, round, sqrt, ceil, floor,
             log, sin, cos, tan, pi, e

    Returns:
        float — resultado da expressão

    Raises:
        ValueError: expressão inválida ou não permitida
    """
    try:
        tree = ast.parse(expression.strip(), mode="eval")
    except SyntaxError as exc:
        raise ValueError(f"Invalid expression: {exc}") from exc

    return float(_SafeEval().visit(tree))