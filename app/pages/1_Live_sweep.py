"""Live sweep: run CleanSweep step by step, or replay a saved run, and watch each stage."""

import itertools
import sys
import tempfile
import threading
import time
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from app.live_runner import (  # noqa: E402
    LIVE_DIR,
    STAGE_LABELS,
    STAGES,
    TOY_REPO,
    fold,
    list_runs,
    read_events,
    replay,
    run_live,
)
from app.loaders import compare_reports, judge_decision, load_report, outcome_score  # noqa: E402
from cleansweep.core.models import METHODS  # noqa: E402

RESULT_COLORS = {
    "kept": "#2e7d32",
    "repaired": "#1565c0",
    "split in half": "#ef6c00",
    "rolled back": "#c62828",
    "skipped": "#757575",
}
LANE_STYLE = {
    "safe": "background-color: #e8f5e9; color: #1b1b1b",
    "suggest": "background-color: #fff3e0; color: #1b1b1b",
}
CSS = """
<style>
.cs-stage {padding: 6px 4px; border-radius: 6px; text-align: center; font-size: 0.85rem;
           border: 1px solid #ccc; color: #555; background: #f4f4f4;}
.cs-stage.done {background: #2e7d32; color: white; border-color: #2e7d32;}
.cs-stage.running {background: #fff3e0; color: #e65100; border-color: #ef6c00; font-weight: 600;}
.cs-stage.skipped {background: #fafafa; color: #aaa; border-style: dashed;}
.cs-spin {display: inline-block; width: 0.8em; height: 0.8em; margin-right: 0.35em;
          border: 2px solid #ef6c00; border-right-color: transparent; border-radius: 50%;
          animation: cs-rot 0.8s linear infinite; vertical-align: -0.1em;}
@keyframes cs-rot {to {transform: rotate(360deg);}}
.cs-badge {display: inline-block; padding: 1px 8px; border-radius: 10px; color: white;
           font-size: 0.8rem; font-weight: 600;}
</style>
"""

st.set_page_config(page_title="CleanSweep · Live sweep", layout="wide")
st.markdown(CSS, unsafe_allow_html=True)
st.title("Live sweep")


def target_options() -> dict[str, str]:
    options = {"Toy repo": str(TOY_REPO)}
    prepared = Path(tempfile.gettempdir()) / "cleansweep-demo" / "shop_app"
    if prepared.is_dir():
        options["Prepared demo (demo/prepare_demo.sh)"] = str(prepared)
    for folder in sorted((ROOT / "demo").glob("*")):
        if folder.is_dir() and not folder.name.endswith("_hidden") and any(folder.rglob("*.py")):
            options[f"Demo: {folder.name}"] = str(folder)
    options["Other path..."] = ""
    return options


with st.sidebar:
    st.header("Run")
    options = target_options()
    label = st.selectbox("Target", list(options))
    target = options[label] or st.text_input("Path to a Python project")
    method = st.selectbox("Method", METHODS)
    judge_mode = st.radio("Judge mode", ["off", "gatekeeper", "advisory"], index=1)
    run_clicked = st.button("Run", type="primary", disabled=not target)

    st.header("Replay")
    runs = list_runs()
    picked = st.selectbox("Saved run", runs, format_func=lambda p: p.name) if runs else None
    speed = st.slider("Speed", 1, 50, 10, format="%dx")
    replay_clicked = st.button("Replay", disabled=picked is None)


def stage_bar(state: dict, clock: float) -> None:
    cols = st.columns(len(STAGES))
    for col, stage in zip(cols, STAGES, strict=True):
        status = state["stages"].get(stage, "pending")
        text = STAGE_LABELS[stage]
        if status == "running":
            elapsed = max(clock - state["current_since"], 0)
            text = f"<span class='cs-spin'></span>{text} {elapsed:.0f} s"
        elif status == "done" and stage != "done":
            text = f"{text} · {state['stage_seconds'].get(stage, 0):.0f} s"
        col.markdown(f"<div class='cs-stage {status}'>{text}</div>", unsafe_allow_html=True)
    if state["current"] == "plan":
        calls = state["llm"]
        finished = [c for c in calls if c["seconds"] is not None]
        if calls:
            st.markdown(
                f"<span class='cs-spin'></span>LLM judge working: request {len(calls)}, "
                f"{len(finished)} done, {clock - state['current_since']:.0f} s in this stage",
                unsafe_allow_html=True,
            )
        else:
            st.markdown("<span class='cs-spin'></span>Running detectors", unsafe_allow_html=True)


def plan_frame(state: dict) -> pd.DataFrame:
    rows = []
    for item in state["items"]:
        decision, confidence = judge_decision(item["evidence"])
        if item["category"] == "format" and decision == "-":
            decision = "skipped (format)"
        rows.append(
            {
                "lane": item["lane"],
                "category": item["category"],
                "unit": item["unit"]["path"]
                + (f"::{item['unit']['name']}" if item["unit"]["name"] else ""),
                "status": state["statuses"].get(item["item_id"], ""),
                "judge": decision,
                "confidence": confidence,
                "safe_score": state["scores"].get(item["item_id"], item.get("safe_score")),
                "reason": item["reason"],
                "evidence": "; ".join(e for e in item["evidence"] if not e.startswith("llm judge")),
            }
        )
    return pd.DataFrame(rows)


def show_plan(state: dict, frame: int) -> None:
    st.subheader("Reviewer plan")
    frame = plan_frame(state)
    if frame.empty:
        st.caption("Waiting for the Reviewer...")
        return
    styled = frame.style.apply(lambda row: [LANE_STYLE.get(row["lane"], "")] * len(row), axis=1)
    styled = styled.format({"confidence": "{:.2f}", "safe_score": "{:.2f}"}, na_rep="")
    st.dataframe(styled, hide_index=True, width="stretch", height=430, key=f"plan-{frame}")


def show_guard(state: dict, frame: int) -> None:
    st.subheader("Guard")
    a, b, c, d = st.columns(4)
    a.metric("Kept", state["kept"])
    b.metric("Rolled back", state["rolled_back"])
    c.metric("Test runs", state["test_runs"])
    d.metric("Lines removed", state["lines_removed"])
    safe_total = sum(
        1 for i in state["items"] if i["lane"] == "safe" and i["action"] != "report_only"
    )
    if safe_total:
        meter = go.Figure(
            go.Bar(
                x=[state["kept"], max(len(state["items"]) - state["kept"], 0)],
                y=["cleaned", "still open"],
                orientation="h",
                marker_color=["#2e7d32", "#bdbdbd"],
            )
        )
        meter.update_layout(
            title="Slop meter (items)", height=150, margin={"t": 30, "b": 5, "l": 5, "r": 5}
        )
        st.plotly_chart(meter, width="stretch", key=f"meter-{frame}")
    units = {i["item_id"]: i for i in state["items"]}
    for card in reversed(state["batches"]):
        with st.container(border=True):
            result = card.get("result")
            if result is None:
                badge = "<span class='cs-spin'></span>checking"
            else:
                color = RESULT_COLORS.get(result, "#757575")
                badge = f"<span class='cs-badge' style='background:{color}'>{result}</span>"
            seconds = f" · {card['seconds']} s" if card.get("seconds") is not None else ""
            st.markdown(
                f"**Check {card['n']}** · {len(card['items'])} item(s){seconds} &nbsp; {badge}",
                unsafe_allow_html=True,
            )
            st.markdown(
                "\n".join(
                    f"- `{u}` ({units.get(i, {}).get('category', '?')})"
                    for i, u in zip(card["items"], card["units"], strict=True)
                )
            )
            if result is not None:
                tests = card.get("tests")
                checks = "compile, import, "
                checks += (
                    f"tests ({tests['passed']} passed, {tests['failed']} failed)"
                    if tests
                    else "stopped before the tests"
                    if not card.get("ok")
                    else "tests"
                )
                if card.get("ast_equal") is not None:
                    checks += f", AST unchanged: {'yes' if card['ast_equal'] else 'no'}"
                st.caption(f"Checks: {checks} · test runs so far: {card.get('test_runs')}")


def show_bottom(state: dict, target_path: str, frame: int) -> None:
    st.divider()
    left, right = st.columns(2)
    with left:
        st.subheader("Diffs")
        units = {i["item_id"]: i for i in state["items"]}
        shown = [r for r in state["results"] if r.get("diff")]
        if not shown:
            st.caption("Diffs appear when the Guard finishes.")
        for r in shown:
            item = units.get(r["item_id"], {})
            key = item.get("unit", {})
            name = key.get("path", "?") + (f"::{key['name']}" if key.get("name") else "")
            with st.expander(f"{r['status']} · {item.get('category', '?')} · {name}"):
                st.code(r["diff"], language="diff")
    with right:
        st.subheader("Hidden checks")
        hidden = state["hidden"]
        if hidden is None:
            st.caption("Runs after the Guard.")
        elif not hidden.get("available"):
            st.info("No hidden checks for this target.")
        elif hidden.get("applied") is False:
            st.warning("The cleanup diff did not apply to a fresh copy, so nothing was checked.")
        else:
            changed = hidden.get("behavior_changed")
            before = set(hidden["hidden_before"]["failed_ids"])
            after = set(hidden["hidden_after"]["failed_ids"])
            flipped = sorted(before ^ after)
            if changed:
                st.error("Behavior changed: yes")
                st.markdown("\n".join(f"- `{t}`" for t in flipped) or "- (error count changed)")
            else:
                st.success("Behavior changed: no")
            if hidden.get("visible_new_failures"):
                st.warning(f"Visible tests broken: {', '.join(hidden['visible_new_failures'])}")
        expected = Path(target_path.rstrip("/") + "_expected.json")
        if state["report"] and expected.exists():
            score = outcome_score(load_report(state["report"]), expected)
            st.subheader("Outcome vs. answer key")
            st.metric("Outcome accuracy", f"{score['hits']}/{score['total']}")
            st.dataframe(score["table"], hide_index=True, width="stretch", key=f"score-{frame}")
    if state["logs"]:
        with st.expander(f"Run log ({len(state['logs'])} lines)"):
            st.code("\n".join(f"{e['level']} {e['logger']}: {e['message']}" for e in state["logs"]))
    st.subheader("Toy repo runs so far")
    compare = compare_reports(ROOT / "results" / "raw" / "toy")
    if compare.empty:
        st.caption("No saved runs in results/raw/toy/.")
    else:
        st.dataframe(compare, hide_index=True, width="stretch", key=f"compare-{frame}")


# Every redraw in one script run needs fresh element keys, or Streamlit sees duplicates.
FRAMES = itertools.count()


def render(root, state: dict, clock: float) -> None:
    frame = next(FRAMES)
    with root.container():
        run = state["run"]
        if run:
            st.caption(
                f"{run['run_id']} · {Path(run['target']).name} · method {run['method']} · "
                f"judge {run['judge_mode']} · model {run.get('model') or 'none'}"
            )
        stage_bar(state, clock)
        if state["error"]:
            st.error(state["error"])
        left, right = st.columns([3, 2])
        with left:
            show_plan(state, frame)
        with right:
            show_guard(state, frame)
        show_bottom(state, run.get("target", ""), frame)


root = st.empty()
if run_clicked:
    run_id = f"{time.strftime('%Y%m%d-%H%M%S')}_{Path(target).name}_{method}_{judge_mode}"
    events_path = LIVE_DIR / run_id / "events.jsonl"
    failure: dict = {}

    def work() -> None:
        try:
            run_live(target, None, method, judge_mode, run_id)
        except Exception as exc:  # the runner already logged it; keep the page alive
            failure["error"] = exc

    worker = threading.Thread(target=work, daemon=True)
    started = time.time()
    worker.start()
    while worker.is_alive():
        render(root, fold(read_events(events_path)), time.time() - started)
        time.sleep(0.5)
    render(root, fold(read_events(events_path)), time.time() - started)
    st.session_state["shown"] = str(events_path)
elif replay_clicked and picked is not None:
    events = read_events(picked / "events.jsonl")
    for clock, n in replay(events, speed=speed, tick=0.25):
        render(root, fold(events[:n]), clock)
    st.session_state["shown"] = str(picked / "events.jsonl")
elif "shown" in st.session_state:
    events = read_events(st.session_state["shown"])
    render(root, fold(events), events[-1]["t"] if events else 0)
else:
    root.info("Pick a target and press Run, or choose a saved run and press Replay.")
