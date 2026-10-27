"""Find review comments that ask the agent to remove code: a keyword filter, then an LLM check."""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path

import pandas as pd

log = logging.getLogger(__name__)

PROMPT = (Path(__file__).parent / "prompts" / "removal.txt").read_text()
KEYWORDS = re.compile(
    r"\b(?:remove|removing|delete|deleting|drop (?:this|it|the)|get rid of|unused|not used|"
    r"no longer (?:used|needed)|dead code|not needed|unnecessary|redundant|duplicat\w*|leftover|"
    r"left over|debug(?:ging)? (?:print|code|log)|clean ?up|why is this (?:here|needed)|"
    r"don'?t need|isn'?t needed|is this needed|not required)\b",
    re.IGNORECASE,
)
CATEGORIES = {
    "leftover_file",
    "dead_code",
    "duplicate",
    "wrapper",
    "unused_import",
    "unused_dependency",
    "other",
}


def keyword_match(comments: pd.DataFrame) -> pd.DataFrame:
    """Comments whose body mentions removal in any of the KEYWORDS forms."""
    if "body" not in comments:
        return comments.iloc[0:0]
    return comments[comments["body"].fillna("").str.contains(KEYWORDS)].copy()


def find_removal_requests(
    comments: pd.DataFrame,
    llm=None,
    batch: int = 20,
    max_requests: int = 50,
    extra_body: dict | None = None,
) -> pd.DataFrame:
    """Keyword candidates, checked by the LLM in batches (at most max_requests requests).

    Returns the checked candidates with columns removal (bool), category and target; without
    an LLM, the keyword candidates with removal=None (unchecked)."""
    cand = keyword_match(comments)
    cand["removal"], cand["category"], cand["target"] = None, None, None
    if llm is None or cand.empty:
        return cand
    checked = cand.iloc[: batch * max_requests].copy()
    for start in range(0, len(checked), batch):
        chunk = checked.iloc[start : start + batch]
        payload = [
            {"id": str(row.id), "file": row.path, "comment": str(row.body)[:800]}
            for row in chunk.itertuples()
        ]
        try:
            messages = [
                {"role": "user", "content": PROMPT.format(comments=json.dumps(payload, indent=1))}
            ]
            if extra_body:
                reply = llm.chat_json(messages, extra_body=extra_body)
            else:
                reply = llm.chat_json(messages)
        except Exception as exc:  # one failed request leaves its comments unchecked
            log.warning(
                "removal check failed for comments %d-%d: %s", start, start + len(chunk), exc
            )
            continue
        rows = reply.get("comments", []) if isinstance(reply, dict) else reply
        by_id = {str(r.get("id")): r for r in rows if isinstance(r, dict)}
        for idx, row in zip(chunk.index, chunk.itertuples(), strict=True):
            r = by_id.get(str(row.id))
            if r is None:
                continue
            removal = bool(r.get("removal"))
            category = r.get("category") if r.get("category") in CATEGORIES else None
            checked.loc[idx, ["removal", "category", "target"]] = [
                removal,
                category if removal else None,
                r.get("target") if removal else None,
            ]
    return checked
