"""Small AST mutations, to measure how strong the Guard's checks are.

Five operators: flip a comparison, swap + and -, add 1 to an int constant, swap and/or, and
return None. Only the text of the mutated node is replaced, so the rest of the file keeps its
exact formatting (and stays valid on the target project's own Python version).
"""

from __future__ import annotations

import ast
import random
from dataclasses import dataclass

OPERATORS = ["flip_comparison", "swap_add_sub", "int_plus_one", "swap_and_or", "return_none"]
FLIP = {
    ast.Lt: ast.GtE,
    ast.GtE: ast.Lt,
    ast.Gt: ast.LtE,
    ast.LtE: ast.Gt,
    ast.Eq: ast.NotEq,
    ast.NotEq: ast.Eq,
    ast.Is: ast.IsNot,
    ast.IsNot: ast.Is,
    ast.In: ast.NotIn,
    ast.NotIn: ast.In,
}


@dataclass
class Mutant:
    operator: str
    path: str
    qualname: str
    line: int
    source: str  # the whole file with the mutation

    @property
    def key(self) -> str:
        return f"{self.path}::{self.qualname}"


def find_function(tree: ast.Module, qualname: str):
    body, node = tree.body, None
    for part in qualname.split("."):
        node = next(
            (
                n
                for n in body
                if isinstance(n, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef)
                and n.name == part
            ),
            None,
        )
        if node is None:
            return None
        body = node.body
    return node if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef) else None


def sites(func: ast.AST) -> list[tuple[str, ast.AST]]:
    """Every place in a function where an operator applies, as (operator, node)."""
    found = []
    for node in ast.walk(func):
        if isinstance(node, ast.Compare) and type(node.ops[0]) in FLIP:
            found.append(("flip_comparison", node))
        elif isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add | ast.Sub):
            found.append(("swap_add_sub", node))
        elif (
            isinstance(node, ast.Constant)
            and isinstance(node.value, int)
            and not isinstance(node.value, bool)
        ):
            found.append(("int_plus_one", node))
        elif isinstance(node, ast.BoolOp):
            found.append(("swap_and_or", node))
        elif isinstance(node, ast.Return) and node.value is not None:
            if not (isinstance(node.value, ast.Constant) and node.value.value is None):
                found.append(("return_none", node.value))
    return found


def _mutated(operator: str, node: ast.AST) -> ast.AST:
    import copy

    new = copy.deepcopy(node)
    if operator == "flip_comparison":
        new.ops[0] = FLIP[type(new.ops[0])]()
    elif operator == "swap_add_sub":
        new.op = ast.Sub() if isinstance(new.op, ast.Add) else ast.Add()
    elif operator == "int_plus_one":
        new.value = new.value + 1
    elif operator == "swap_and_or":
        new.op = ast.Or() if isinstance(new.op, ast.And) else ast.And()
    elif operator == "return_none":
        new = ast.Constant(None)
    return new


def replace_node(text: str, node: ast.AST, new_text: str) -> str:
    """The file text with exactly the node's source range replaced."""
    lines = text.splitlines(keepends=True)
    start = sum(len(line) for line in lines[: node.lineno - 1]) + _byte_to_char(
        lines[node.lineno - 1], node.col_offset
    )
    end = sum(len(line) for line in lines[: node.end_lineno - 1]) + _byte_to_char(
        lines[node.end_lineno - 1], node.end_col_offset
    )
    return text[:start] + new_text + text[end:]


def _byte_to_char(line: str, offset: int) -> int:
    # ast offsets are UTF-8 byte offsets
    return len(line.encode("utf-8")[:offset].decode("utf-8", errors="ignore"))


def mutants(text: str, path: str, qualname: str) -> list[Mutant]:
    """All single mutants of one function, in source order."""
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return []
    func = find_function(tree, qualname)
    if func is None:
        return []
    out = []
    for operator, node in sites(func):
        new_text = ast.unparse(_mutated(operator, node))
        if operator in ("swap_add_sub", "swap_and_or", "flip_comparison"):
            new_text = f"({new_text})"  # keep precedence where the node sits
        source = replace_node(text, node, new_text)
        try:
            if ast.dump(ast.parse(source)) == ast.dump(tree):
                continue
        except SyntaxError:
            continue
        out.append(Mutant(operator, path, qualname, node.lineno, source))
    return out


def sample(candidates: list[Mutant], limit: int, seed: int = 0) -> list[Mutant]:
    """Up to `limit` mutants, spread over operators and functions, reproducibly."""
    rng = random.Random(seed)
    pool = list(candidates)
    rng.shuffle(pool)
    pool.sort(key=lambda m: OPERATORS.index(m.operator))  # stable: shuffled within operator
    by_op: dict[str, list[Mutant]] = {}
    for m in pool:
        by_op.setdefault(m.operator, []).append(m)
    picked = []
    while len(picked) < limit and any(by_op.values()):
        for op in OPERATORS:
            if by_op.get(op) and len(picked) < limit:
                picked.append(by_op[op].pop(0))
    return picked
