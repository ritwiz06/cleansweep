"""Line-level slop detectors (v2): unused local variables, debug leftovers, commented-out code,
TODO/FIXME notes and simple redundant checks.

Each item carries its edit as a zero-context diff (action "edit_lines"), applied by finding the
exact old lines nearest their position, so earlier edits that moved them do not matter. Only
edits that keep behavior are in the safe lane; the checks after each edit still test them."""

from __future__ import annotations

import ast
import difflib
import io
import json
import re
import tokenize
from pathlib import Path

from cleansweep.analysis.graph import is_test_file, iter_py_files
from cleansweep.core.models import CleanupItem, CodeUnit

from .detectors import _tool, make_item

DEBUG_MARK = re.compile(r"^\s*(debug|dbg|xxx|>>>|here\b|---)", re.IGNORECASE)
TODO = re.compile(r"#\s*(TODO|FIXME|XXX|HACK)\b", re.IGNORECASE)
CODE_HINT = re.compile(
    r"(=|\(|\)|:\s*$|^\s*(import|from|return|def|class|for|while|if|elif|else|try|except|raise|print)\b)"
)
SKIP_COMMENT = re.compile(
    r"^#\s*(!|-\*-|type:|noqa|pragma|pylint|fmt:|isort|mypy|ruff)", re.IGNORECASE
)
CLI_NAMES = ("cli", "main", "__main__", "commands", "command", "scripts", "manage", "run")
LINE_CATEGORIES = [
    "unused_variable",
    "debug_leftover",
    "commented_code",
    "todo_note",
    "redundant_check",
]


def _lines(repo_dir: str, path: str) -> list[str] | None:
    try:
        lines = (Path(repo_dir) / path).read_text(encoding="utf-8").splitlines(keepends=True)
    except (OSError, UnicodeDecodeError):
        return None
    if lines and not lines[-1].endswith("\n"):
        lines[-1] += "\n"
    return lines


def _unified(path: str, before: list[str], after: list[str]) -> str:
    """A zero-context diff: the edit_lines action finds the old lines near their position."""
    diff = difflib.unified_diff(before, after, fromfile=f"a/{path}", tofile=f"b/{path}", n=0)
    return "".join(diff)


def _item(
    path: str,
    start: int,
    end: int,
    category: str,
    lane: str,
    reason: str,
    patch: str,
    evidence: list[str],
    source: str,
) -> CleanupItem:
    unit = CodeUnit(path, "lines", f"L{start}-{end}", start, end)
    return make_item(unit, category, "edit_lines", lane, reason, evidence, [source], patch=patch)


def _parents(tree: ast.AST) -> dict[ast.AST, ast.AST]:
    return {child: node for node in ast.walk(tree) for child in ast.iter_child_nodes(node)}


def _remove_stmt(lines: list[str], node: ast.stmt, parent: ast.AST | None) -> list[str]:
    """The file without a statement; an emptied block gets `pass`."""
    start, end = node.lineno - 1, node.end_lineno
    new = lines[:start] + lines[end:]
    for field in ("body", "orelse", "finalbody"):
        block = getattr(parent, field, None)
        if isinstance(block, list) and block == [node]:
            indent = re.match(r"\s*", lines[start]).group(0)
            new = lines[:start] + [f"{indent}pass\n"] + lines[end:]
    return new


def _py_files(repo_dir: str, paths: list[str] | None) -> list[str]:
    files = paths if paths is not None else iter_py_files(repo_dir)
    return [p for p in files if p.endswith(".py") and not is_test_file(p)]


def detect_unused_variables(repo_dir: str, paths: list[str] | None = None) -> list[CleanupItem]:
    """ruff F841: a local assigned and never used. The value is kept when it is a call."""
    files = _py_files(repo_dir, paths)
    if not files:
        return []
    out = _tool(
        [
            "ruff",
            "check",
            "--isolated",
            "--select",
            "F841",
            "--output-format",
            "json",
            "--exit-zero",
            *files,
        ],
        repo_dir,
    )
    if out is None or not out[1].strip():
        return []
    items = []
    root = Path(repo_dir).resolve()
    for r in json.loads(out[1]):
        if r.get("code") != "F841":
            continue  # ruff also reports syntax errors
        path = Path(r["filename"]).resolve().relative_to(root).as_posix()
        lines = _lines(repo_dir, path)
        row = r["location"]["row"]
        if lines is None or row > len(lines):
            continue
        name = (re.search(r"`([^`]+)`", r["message"]) or [None, "?"])[1]
        new = _drop_assignment(lines, row, name)
        if new is None:
            continue
        reason = f"The local variable {name} is assigned in {path} but never used."
        items.append(
            _item(
                path,
                row,
                row,
                "unused_variable",
                "safe",
                reason,
                _unified(path, lines, new),
                [f"ruff F841 at line {row}"],
                "ruff",
            )
        )
    return items


def _drop_assignment(lines: list[str], row: int, name: str) -> list[str] | None:
    text = lines[row - 1]
    m = re.match(rf"(\s*except\b.*?)\s+as\s+{re.escape(name)}\s*:", text)
    if m:
        return (
            lines[: row - 1]
            + [text[: m.end(1)] + text[m.end(1) :].replace(f" as {name}", "", 1)]
            + lines[row:]
        )
    try:
        tree = ast.parse("".join(lines))
    except SyntaxError:
        return None
    parents = _parents(tree)
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign | ast.AnnAssign) and node.lineno == row:
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            if len(targets) != 1 or not isinstance(targets[0], ast.Name) or targets[0].id != name:
                return None
            value = node.value
            if value is not None and isinstance(
                value, ast.Call | ast.Await | ast.Yield | ast.YieldFrom
            ):
                indent = re.match(r"\s*", lines[row - 1]).group(0)
                segment = ast.get_source_segment("".join(lines), value)
                if segment is None:
                    return None
                body = [
                    f"{indent}{ln}" if i else ln
                    for i, ln in enumerate(segment.splitlines(keepends=True))
                ]
                kept = f"{indent}{''.join(body)}".rstrip("\n") + "\n"
                return lines[: node.lineno - 1] + [kept] + lines[node.end_lineno :]
            return _remove_stmt(lines, node, parents.get(node))
    return None


def _call_name(node: ast.AST) -> str:
    if isinstance(node, ast.Call):
        f = node.func
        if isinstance(f, ast.Name):
            return f.id
        if isinstance(f, ast.Attribute) and isinstance(f.value, ast.Name):
            return f"{f.value.id}.{f.attr}"
    return ""


def _is_cli_module(path: str, text: str) -> bool:
    stem = Path(path).stem
    return (
        stem in CLI_NAMES
        or "__main__" in text
        or Path(path).parts[0] in ("scripts", "bin", "examples")
    )


def _self_documenting(values: list[ast.expr]) -> bool:
    """True for f"{x=}": Python stores it as the text "x=" followed by the field x."""
    for text, field in zip(values, values[1:], strict=False):
        if (
            isinstance(text, ast.Constant)
            and isinstance(text.value, str)
            and isinstance(field, ast.FormattedValue)
        ):
            source = ast.unparse(field.value)
            if re.sub(r"\s", "", text.value).endswith(re.sub(r"\s", "", source) + "="):
                return True
    return False


def _debug_print(node: ast.Call) -> bool:
    if not node.args:
        return False
    first = node.args[0]
    if isinstance(first, ast.Constant) and isinstance(first.value, str):
        return bool(DEBUG_MARK.match(first.value))
    if isinstance(first, ast.JoinedStr):
        lead = first.values[0] if first.values else None
        lead_text = (
            lead.value if isinstance(lead, ast.Constant) and isinstance(lead.value, str) else ""
        )
        return bool(DEBUG_MARK.match(lead_text)) or _self_documenting(first.values)
    return False


def detect_debug_leftovers(repo_dir: str, paths: list[str] | None = None) -> list[CleanupItem]:
    """breakpoint(), pdb/ipdb.set_trace() and debug prints: safe; other prints in library
    modules: suggested only (they may be intended output)."""
    items = []
    for path in _py_files(repo_dir, paths):
        lines = _lines(repo_dir, path)
        if lines is None:
            continue
        text = "".join(lines)
        try:
            tree = ast.parse(text)
        except SyntaxError:
            continue
        parents = _parents(tree)
        cli = _is_cli_module(path, text)
        for node in ast.walk(tree):
            if not (isinstance(node, ast.Expr) and isinstance(node.value, ast.Call)):
                continue
            name = _call_name(node.value)
            if name in ("breakpoint", "pdb.set_trace", "ipdb.set_trace", "pudb.set_trace"):
                lane, why = "safe", f"A debugger call ({name}) was left in the code."
            elif name == "print" and _debug_print(node.value):
                lane, why = "safe", "A debug print was left in the code."
            elif name == "print" and not cli:
                lane, why = (
                    "suggest",
                    "A print in library code; it may be leftover debugging or intended output.",
                )
            else:
                continue
            new = _remove_stmt(lines, node, parents.get(node))
            start, end = node.lineno, node.end_lineno
            items.append(
                _item(
                    path,
                    start,
                    end,
                    "debug_leftover",
                    lane,
                    why,
                    _unified(path, lines, new),
                    [f"{name} at line {start}"],
                    "ast",
                )
            )
    return items


def _comments(text: str) -> list[tuple[int, int, str]]:
    """(line, column, text) of comments that stand on their own line."""
    out = []
    try:
        for tok in tokenize.generate_tokens(io.StringIO(text).readline):
            if tok.type == tokenize.COMMENT and not tok.line[: tok.start[1]].strip():
                out.append((tok.start[0], tok.start[1], tok.string))
    except (tokenize.TokenError, IndentationError, SyntaxError):
        return []
    return out


CODE_NODES = (
    ast.Call,
    ast.Assign,
    ast.AugAssign,
    ast.Return,
    ast.Import,
    ast.ImportFrom,
    ast.FunctionDef,
    ast.ClassDef,
    ast.If,
    ast.For,
    ast.While,
    ast.With,
    ast.Try,
)
MAX_BLOCK = 40


def _parses_as_code(block: list[str]) -> bool:
    body = [re.sub(r"^#\s?", "", c) for c in block]
    if not all(b.strip() for b in body) or not any(CODE_HINT.search(b) for b in body):
        return False
    indented = "if True:\n" + "\n".join("    " + b for b in body)
    for source in ("\n".join(body), indented):
        try:
            tree = ast.parse(source)
        except SyntaxError:
            continue
        # a lone name or constant is a word, not code
        return any(isinstance(n, CODE_NODES) for n in ast.walk(tree))
    return False


def code_runs(block: list[str]) -> list[tuple[int, int]]:
    """(start, end) index ranges of the longest runs of comment lines that parse as code."""
    runs, i = [], 0
    block = block[:MAX_BLOCK]
    while i < len(block):
        for j in range(len(block), i, -1):
            if _parses_as_code(block[i:j]):
                runs.append((i, j))
                i = j
                break
        else:
            i += 1
    return runs


def detect_commented_code(repo_dir: str, paths: list[str] | None = None) -> list[CleanupItem]:
    """Runs of comment lines that parse as Python statements (prose around them stays)."""
    items = []
    for path in _py_files(repo_dir, paths):
        lines = _lines(repo_dir, path)
        if lines is None:
            continue
        comments = [
            c
            for c in _comments("".join(lines))
            if not SKIP_COMMENT.match(c[2]) and not TODO.search(c[2])
        ]
        blocks: list[list[tuple[int, int, str]]] = []
        for c in comments:
            if blocks and c[0] == blocks[-1][-1][0] + 1 and c[1] == blocks[-1][-1][1]:
                blocks[-1].append(c)
            else:
                blocks.append([c])
        for block in blocks:
            if block[0][0] <= 3 and any(
                "copyright" in c[2].lower() or "license" in c[2].lower() for c in block
            ):
                continue
            for a, b in code_runs([c[2] for c in block]):
                start, end = block[a][0], block[b - 1][0]
                new = lines[: start - 1] + lines[end:]
                why = f"{end - start + 1} lines of commented-out code."
                patch = _unified(path, lines, new)
                evidence = [f"comment lines {start}-{end} parse as Python"]
                items.append(
                    _item(
                        path, start, end, "commented_code", "safe", why, patch, evidence, "tokenize"
                    )
                )
    return items


def detect_todo_notes(repo_dir: str, paths: list[str] | None = None) -> list[CleanupItem]:
    """TODO/FIXME/XXX/HACK comments on their own line: always suggestions (a person decides)."""
    items = []
    for path in _py_files(repo_dir, paths):
        lines = _lines(repo_dir, path)
        if lines is None:
            continue
        for row, _, text in _comments("".join(lines)):
            if TODO.search(text):
                new = lines[: row - 1] + lines[row:]
                why = f"A leftover note: {text.strip()[:80]}"
                items.append(
                    _item(
                        path,
                        row,
                        row,
                        "todo_note",
                        "suggest",
                        why,
                        _unified(path, lines, new),
                        [f"comment at line {row}"],
                        "tokenize",
                    )
                )
    return items


def _bool_return(stmts: list[ast.stmt]) -> bool | None:
    if (
        len(stmts) == 1
        and isinstance(stmts[0], ast.Return)
        and isinstance(stmts[0].value, ast.Constant)
        and isinstance(stmts[0].value.value, bool)
    ):
        return stmts[0].value.value
    return None


def detect_redundant_checks(repo_dir: str, paths: list[str] | None = None) -> list[CleanupItem]:
    """`if c: return True else: return False` -> `return bool(c)` (and the negation); a boolean
    test with the same operand twice. Comparisons with True/False are suggested only, since
    `x == True` is not the same as `x` for non-bool values."""
    items = []
    for path in _py_files(repo_dir, paths):
        lines = _lines(repo_dir, path)
        if lines is None:
            continue
        text = "".join(lines)
        try:
            tree = ast.parse(text)
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            body = getattr(node, "body", None)
            if not isinstance(body, list):
                continue
            for i, stmt in enumerate(body):
                if not isinstance(stmt, ast.If):
                    continue
                then = _bool_return(stmt.body)
                other = _bool_return(stmt.orelse) if stmt.orelse else None
                nxt = None
                if not stmt.orelse and i + 1 < len(body):
                    nxt = _bool_return([body[i + 1]])
                if (
                    then is None
                    or (other if stmt.orelse else nxt) is None
                    or (other if stmt.orelse else nxt) == then
                ):
                    continue
                cond = ast.get_source_segment(text, stmt.test)
                if cond is None or "\n" in cond:
                    continue
                end = stmt.end_lineno if stmt.orelse else body[i + 1].end_lineno
                indent = re.match(r"\s*", lines[stmt.lineno - 1]).group(0)
                expr = f"bool({cond})" if then else f"not ({cond})"
                new = lines[: stmt.lineno - 1] + [f"{indent}return {expr}\n"] + lines[end:]
                why = f"`if {cond}: return {then} ... return {not then}` is `return {expr}`."
                items.append(
                    _item(
                        path,
                        stmt.lineno,
                        end,
                        "redundant_check",
                        "safe",
                        why,
                        _unified(path, lines, new),
                        [f"if at line {stmt.lineno}"],
                        "ast",
                    )
                )
        for node in ast.walk(tree):
            if isinstance(node, ast.BoolOp) and len(node.values) == 2:
                a, b = (ast.dump(v) for v in node.values)
                simple = all(
                    isinstance(v, ast.Name | ast.Attribute | ast.Compare) for v in node.values
                )
                if a == b and simple and node.lineno == node.end_lineno:
                    seg = ast.get_source_segment(text, node)
                    one = ast.get_source_segment(text, node.values[0])
                    row = node.lineno
                    if seg and one and seg in lines[row - 1]:
                        new = lines[: row - 1] + [lines[row - 1].replace(seg, one, 1)] + lines[row:]
                        why = f"`{seg}` tests the same thing twice."
                        items.append(
                            _item(
                                path,
                                row,
                                row,
                                "redundant_check",
                                "safe",
                                why,
                                _unified(path, lines, new),
                                [f"line {row}"],
                                "ast",
                            )
                        )
            if (
                isinstance(node, ast.Compare)
                and len(node.ops) == 1
                and isinstance(node.ops[0], ast.Eq | ast.Is)
            ):
                right = node.comparators[0]
                if (
                    isinstance(right, ast.Constant)
                    and isinstance(right.value, bool)
                    and node.lineno == node.end_lineno
                ):
                    seg = ast.get_source_segment(text, node)
                    left = ast.get_source_segment(text, node.left)
                    row = node.lineno
                    if seg and left and seg in lines[row - 1]:
                        simpler = left if right.value else f"not {left}"
                        new = (
                            lines[: row - 1]
                            + [lines[row - 1].replace(seg, simpler, 1)]
                            + lines[row:]
                        )
                        why = f"`{seg}` could be `{simpler}` if {left} is always a bool."
                        items.append(
                            _item(
                                path,
                                row,
                                row,
                                "redundant_check",
                                "suggest",
                                why,
                                _unified(path, lines, new),
                                [f"line {row}"],
                                "ast",
                            )
                        )
    return items


def run_line_detectors(repo_dir: str, paths: list[str] | None = None) -> list[CleanupItem]:
    """All five line-level detectors."""
    found = []
    for detect in (
        detect_unused_variables,
        detect_debug_leftovers,
        detect_commented_code,
        detect_todo_notes,
        detect_redundant_checks,
    ):
        found += detect(repo_dir, paths)
    seen, out = set(), []
    for item in found:
        if item.item_id not in seen:
            seen.add(item.item_id)
            out.append(item)
    return out
