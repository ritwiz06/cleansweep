from __future__ import annotations

import ast
import io
import itertools
import keyword
import tokenize
from pathlib import Path

from cleansweep.core.models import CodeUnit

from .graph import is_test_file, iter_py_files

SHINGLE = 5
MIN_STATEMENTS = 4


def _normalized_tokens(source: str) -> list[str]:
    out = []
    try:
        for tok in tokenize.generate_tokens(io.StringIO(source).readline):
            if tok.type == tokenize.NAME:
                out.append(tok.string if keyword.iskeyword(tok.string) else "ID")
            elif tok.type == tokenize.STRING:
                out.append("STR")
            elif tok.type == tokenize.NUMBER:
                out.append("NUM")
            elif tok.type == tokenize.OP:
                out.append(tok.string)
    except (tokenize.TokenError, IndentationError):
        pass
    return out


def _body_source(node: ast.FunctionDef, lines: list[str]) -> str:
    body = node.body
    if (
        body
        and isinstance(body[0], ast.Expr)
        and isinstance(getattr(body[0], "value", None), ast.Constant)
    ):
        body = body[1:]  # drop the docstring
    if not body:
        return ""
    import textwrap

    return textwrap.dedent("\n".join(lines[body[0].lineno - 1 : body[-1].end_lineno]))


def _functions(repo_dir: str):
    root = Path(repo_dir)
    for path in iter_py_files(root):
        if is_test_file(path):
            continue
        text = (root / path).read_text(encoding="utf-8", errors="replace")
        try:
            tree = ast.parse(text)
        except SyntaxError:
            continue
        lines = text.splitlines()
        for node, qual in _walk_defs(tree):
            n_stmts = sum(isinstance(s, ast.stmt) for s in ast.walk(node)) - 1
            if n_stmts < MIN_STATEMENTS:
                continue
            src = _body_source(node, lines)
            unit = CodeUnit(path, "function", qual, node.lineno, node.end_lineno)
            yield unit, src


def _walk_defs(tree: ast.Module):
    for node in tree.body:
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            yield node, node.name
        elif isinstance(node, ast.ClassDef):
            for sub in node.body:
                if isinstance(sub, ast.FunctionDef | ast.AsyncFunctionDef):
                    yield sub, f"{node.name}.{sub.name}"


def _shingles(tokens: list[str]) -> set[tuple]:
    if len(tokens) < SHINGLE:
        return {tuple(tokens)} if tokens else set()
    return {tuple(tokens[i : i + SHINGLE]) for i in range(len(tokens) - SHINGLE + 1)}


def find_duplicates(
    repo_dir: str, threshold: float = 0.8, only: set[str] | None = None
) -> list[tuple[CodeUnit, CodeUnit, float]]:
    """Pairs of functions whose normalized token shingles have Jaccard >= threshold.

    Exact comparison. With `only` (unit keys), each of those functions is compared with every
    other function (k x n) instead of all pairs, which keeps big repos fast.
    """
    funcs = [(u, src, _shingles(_normalized_tokens(src))) for u, src in _functions(repo_dir)]
    if only is None:
        candidates = itertools.combinations(funcs, 2)
    else:
        mine = [f for f in funcs if f[0].key in only]
        candidates = (
            (a, b) for a in mine for b in funcs if b[0].key not in only or a[0].key < b[0].key
        )
    pairs = []
    for (ua, _, sa), (ub, _, sb) in candidates:
        if not sa or not sb or ua.key == ub.key:
            continue
        sim = len(sa & sb) / len(sa | sb)
        if sim >= threshold:
            pairs.append((ua, ub, round(sim, 4)))
    return sorted(pairs, key=lambda p: -p[2])


def body_text(repo_dir: str, unit: CodeUnit) -> str:
    """Docstring-free body of a function, used to tell exact from near duplicates."""
    for u, src in _functions(repo_dir):
        if u.key == unit.key:
            return src
    return ""
