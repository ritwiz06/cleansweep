from __future__ import annotations

import ast
import json
import re
from pathlib import Path

import pandas as pd

from cleansweep.core.models import FEATURE_COLUMNS, CommitEvent

from .graph import CodeGraph, is_test_file
from .minhash import find_duplicates
from .scope import agent_scope

NAME_PATTERNS = {
    r"_old\b|old_": 1.0,
    r"_v\d+\b": 1.0,
    r"backup|\.bak": 1.0,
    r"scratch": 1.0,
    r"reproduce": 0.9,
    r"debug": 0.8,
    r"\btmp|temp_": 0.7,
    r"copy": 0.6,
}
BRANCHES = (
    ast.If,
    ast.For,
    ast.While,
    ast.Try,
    ast.With,
    ast.BoolOp,
    ast.IfExp,
    ast.comprehension,
    ast.ExceptHandler,
)


def name_pattern_score(text: str) -> float:
    text = text.lower()
    return max((w for pat, w in NAME_PATTERNS.items() if re.search(pat, text)), default=0.0)


def is_wrapper_node(node: ast.AST) -> bool:
    """A function whose whole body is `return f(<its own params, in order>)`."""
    if not isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
        return False
    body = [
        s for s in node.body if not (isinstance(s, ast.Expr) and isinstance(s.value, ast.Constant))
    ]
    if len(body) != 1 or not isinstance(body[0], ast.Return):
        return False
    call = body[0].value
    if not isinstance(call, ast.Call) or call.keywords:
        return False
    params = [a.arg for a in node.args.args if a.arg not in ("self", "cls")]
    args = [a.id for a in call.args if isinstance(a, ast.Name)]
    return len(args) == len(call.args) and args == params


def _coverage_index(coverage_json: str | None) -> dict[str, dict[int, set[str]]]:
    if not coverage_json or not Path(coverage_json).exists():
        return {}
    data = json.loads(Path(coverage_json).read_text())
    out: dict[str, dict[int, set[str]]] = {}
    for fname, info in data.get("files", {}).items():
        ctx = info.get("contexts", {})
        out[fname.replace("\\", "/")] = {int(k): {c for c in v if c} for k, v in ctx.items()}
    return out


def extract_features(
    repo_dir: str,
    graph: CodeGraph,
    coverage_json: str | None = None,
    history: list[CommitEvent] | None = None,
    units: set[str] | None = None,
) -> pd.DataFrame:
    """One row per code unit with FEATURE_COLUMNS; -1 marks values we could not compute.

    In a repo with an "agent patch" commit, written_by_agent is filled in and duplicate
    similarity is computed only for the agent's functions (k x n). With `units`, only those
    unit keys get rows, and duplicate similarity is computed for them (k x n)."""
    scope = agent_scope(repo_dir, graph)
    dup_sim: dict[str, float] = {}
    only = scope.units if scope is not None else None
    if units is not None:  # rows (and k x n duplicates) for these unit keys only
        only = set(units)
    for a, b, sim in find_duplicates(repo_dir, threshold=0.5, only=only):
        for u in (a, b):
            dup_sim[u.key] = max(dup_sim.get(u.key, 0.0), sim)
    cov = _coverage_index(coverage_json)
    rows = {}
    for unit in graph.units():
        if unit.kind not in ("file", "function", "class"):
            continue
        if units is not None and unit.key not in units:
            continue
        mod = graph.modules.get(unit.path)
        node = mod.defs.get(unit.name) if (mod and unit.name) else None
        callers = graph.callers(unit.key)
        row = dict.fromkeys(FEATURE_COLUMNS, -1)
        row.update(
            {
                "kind_file": int(unit.kind == "file"),
                "kind_function": int(unit.kind == "function"),
                "kind_class": int(unit.kind == "class"),
                "n_refs_static": len(callers),
                "n_callers": len({graph.file_of(c) if "::" not in c else c for c in callers}),
                "reachable_from_entry": int(graph.is_reachable(unit.key)),
                "imported_by_tests": int(any(is_test_file(c.split("::")[0]) for c in callers)),
                "loc": (unit.end_line or 0) - (unit.start_line or 0) + 1 if unit.end_line else -1,
                "cyclomatic": 1 + sum(isinstance(n, BRANCHES) for n in ast.walk(node))
                if node
                else -1,
                "n_params": len(node.args.args) if isinstance(node, ast.FunctionDef) else -1,
                "is_wrapper": int(is_wrapper_node(node)) if node else 0,
                "name_pattern_score": name_pattern_score(unit.key),
                "max_dup_similarity": dup_sim.get(unit.key, 0.0),
                "dynamic_risk": int(graph.dynamic_risk(unit.key)),
                "is_test_file": int(is_test_file(unit.path)),
                "written_by_agent": int(scope.covers(unit)) if scope is not None else -1,
            }
        )
        lines = cov.get(unit.path)
        if lines is not None and unit.start_line and unit.end_line:
            span = range(unit.start_line, unit.end_line + 1)
            hit = [ln for ln in span if lines.get(ln)]
            row["covered_lines_frac"] = round(len(hit) / len(span), 4)
            row["times_executed"] = len(set().union(*(lines[ln] for ln in hit))) if hit else 0
        rows[unit.key] = row
    df = pd.DataFrame.from_dict(rows, orient="index", columns=FEATURE_COLUMNS)
    return df.fillna(-1)
