import json
import shutil

import pytest
from fastapi.testclient import TestClient

from app.studio.files import ROOT
from app.studio.server import create_app
from tests.app.studio.conftest import REPLAY_RUN
from tests.conftest import FIXTURES


def test_health_and_unknown_routes(client):
    assert client.get("/api/health").json()["ok"] is True
    assert client.get("/api/nothing").status_code == 404


def test_runs_list_the_shipped_recordings_by_kind(client):
    rows = {(r["root"], r["name"]): r for r in client.get("/api/runs").json()}
    v2 = rows[("replay", REPLAY_RUN)]
    assert v2["kind"] == "v2" and v2["verdict"] == "everything runs" and v2["finished"]
    demo = rows[("replay", "20261102_demo_feature_agentic")]
    assert demo["outcome"] == {"kept": 5, "rolled_back": 1, "lines_removed": 47}
    assert rows[("replay", "20261030_demo_feature_advisory_v1")]["kind"] == "v1"
    assert rows[("results", "watch_a")]["kind"] == "watch"
    assert rows[("results", "clean-001")]["path"] == "raw/watch_a/clean-001"


def test_every_shipped_v2_recording_replays(client):
    names = [
        REPLAY_RUN,
        "20261102_demo_feature_agentic",
        "20261101_manager_conflict_step_back",
        "20261101_skill_seekers_case_study",
    ]
    for name in names:
        query = {"root": "replay", "path": name}
        agentic = client.get("/api/run", params=query).json()["report"]["stats"]["agentic"]
        assert agentic["verdict"] == "everything runs", name
        events = client.get("/api/run/events", params=query).json()
        assert events[0]["kind"] == "run_start" and events[-1]["kind"] == "run_end", name
        if name.startswith("20261101_manager"):
            assert agentic["back_steps"] == {"FINAL_VERIFY->EXECUTE": 1}


def test_run_detail_events_and_artifacts(client):
    query = {"root": "replay", "path": REPLAY_RUN}
    run = client.get("/api/run", params=query).json()
    assert run["report"]["stats"]["agentic"]["verdict"] == "everything runs"
    assert "blueprint.md" in run["docs"] and run["has_cache"] and not run["live"]
    events = client.get("/api/run/events", params=query).json()
    assert events[0]["kind"] == "run_start" and events[-1]["kind"] == "run_end"
    art = next(a for e in events for a in e["artifacts"] if a.startswith("art:diff:"))
    got = client.get("/api/run/artifact", params={**query, "id": art}).json()
    assert got["kind"] == "diff" and got["text"].startswith("diff --git")
    bad = client.get("/api/run/artifact", params={**query, "id": "../report.json"})
    assert bad.status_code == 403
    gone = client.get("/api/run/artifact", params={**query, "id": "art:diff:00000000"})
    assert gone.status_code == 404
    assert "diff --git" in client.get("/api/run/diff", params=query).json()["text"]


def test_project_files_when_the_run_saved_them(client, tmp_path):
    recording = {"root": "replay", "path": REPLAY_RUN}
    assert client.get("/api/run/files", params=recording).json() == {
        "files": [],
        "complete": False,
    }
    run = tmp_path / "runs" / "r1"
    run.mkdir()
    listing = [{"path": "a.py", "lines": 3}, {"path": "logo.png", "lines": None}]
    (run / "project_files.json").write_text(json.dumps({"files": listing}))
    got = client.get("/api/run/files", params={"root": "runs", "path": "r1"}).json()
    assert got == {"files": listing, "complete": True}


def test_stream_sends_the_events_after_an_index_then_ends(client):
    query = {"root": "replay", "path": REPLAY_RUN}
    events = client.get("/api/run/events", params=query).json()
    with client.stream("GET", "/api/run/stream", params={**query, "after": 5}) as response:
        body = "".join(response.iter_text())
    sent = [json.loads(line[6:]) for line in body.splitlines() if line.startswith('data: {"')]
    assert sent == events[5:] and body.rstrip().endswith("event: end\ndata: {}")


@pytest.mark.parametrize(
    "root,path",
    [
        ("results", "../README.md"),
        ("results", "raw/../../pyproject.toml"),
        ("replay", "/etc/hosts"),
        ("home", "x"),
        ("runs", ".env"),
        ("runs", "run/.env"),
        ("runs", "run/../.env"),
        ("runs", "prod.env"),
    ],
)
def test_paths_outside_the_roots_and_env_files_are_refused(client, root, path):
    for route in ("/api/file", "/api/image", "/api/table", "/api/run", "/api/run/events"):
        response = client.get(route, params={"root": root, "path": path})
        assert response.status_code == 403, (route, path)


def test_env_is_never_served(tmp_path, results):
    runs = tmp_path / "runs"
    (runs / "run").mkdir(parents=True)
    secret = "sk-" + "studio" * 5
    for name in (".env", "run/.env", "run/prod.env"):
        (runs / name).write_text(f"VOYAGER_API_KEY={secret}\n")
    (runs / "run" / "note.txt").symlink_to(runs / ".env")
    (runs / "run" / "events.jsonl").write_text(json.dumps({"kind": "log", "t": 0, "m": secret}))
    app = create_app(runs, dist=tmp_path / "dist", hosts=("testserver",), results=results)
    with TestClient(app) as c:
        bodies = [
            c.get("/api/file", params={"root": "runs", "path": p}).text
            for p in (".env", "run/.env", "run/prod.env", "run/note.txt", "run/../.env")
        ]
        bodies.append(c.get("/api/runs").text)
        bodies.append(c.get("/api/run/events", params={"root": "runs", "path": "run"}).text)
    assert all(secret not in b for b in bodies)


def test_text_tables_and_images(client):
    md = client.get("/api/file", params={"root": "results", "path": "summary/v1/main_table.md"})
    assert md.status_code == 200 and md.json()["text"]
    table = client.get(
        "/api/table", params={"root": "results", "path": "summary/v1/main_table.csv"}
    )
    assert table.json()["columns"] and table.json()["rows"]
    figure = client.get(
        "/api/image", params={"root": "replay", "path": REPLAY_RUN + "/report.json"}
    )
    assert figure.status_code == 404
    index = client.get("/api/results").json()
    assert "main_table.csv" in index["v1"]["tables"] and "eval_table.csv" in index["v2"]["tables"]


def test_saved_sweep_reports_are_listed_and_shown(client, results):
    saved = results / "raw" / "quickstart" / "report.json"
    saved.parent.mkdir()
    shutil.copy(FIXTURES / "sample_report.json", saved)
    (saved.parent / "timing.json").write_text("{}")
    found = {(r["root"], r["path"]): r for r in client.get("/api/reports").json()}
    assert found[("results", "raw/quickstart/report.json")]["method"] == "cleansweep"
    assert ("replay", "20261030_demo_feature_advisory_v1/report.json") in found
    assert ("results", "raw/quickstart/timing.json") not in found
    query = {"root": "results", "path": "raw/quickstart/report.json"}
    report = client.get("/api/report", params=query).json()
    assert len(report["items"]) == 16 and report["results"][-1]["status"] == "rolled_back"
    query["path"] = "raw/quickstart/timing.json"
    assert client.get("/api/report", params=query).status_code == 404
    query["path"] = "../README.md"
    assert client.get("/api/report", params=query).status_code == 403


def test_case_studies_carry_the_reviewer_label(client):
    rows = client.get("/api/cases").json()
    assert rows[0]["name"] == "proj_a" and rows[0]["accepted"] == 1 and rows[0]["rejected"] == 1
    case = client.get("/api/cases/proj_a").json()
    assert case["review"]["label"] == "LLM-reviewer acceptance (independent model, blinded)"
    assert [r["llm_decision"] for r in case["review"]["rows"]] == ["accept", "reject"]
    assert "workspace" not in case["summary"] and "CLEANUP_REPORT.md" in case["docs"]
    assert "-def old" in client.get("/api/cases/proj_a/diff").json()["text"]
    assert client.get("/api/cases/missing").status_code == 404
    assert client.get("/api/cases/..%2F..%2Fsummary").status_code in (403, 404)


def test_a_run_shows_its_rows_from_a_review_sheet_kept_apart(client, results):
    cases = results / "raw" / "case_studies"
    run, sheet = cases / "proj_b-safe", cases / "proj_b"
    shutil.copytree(cases / "proj_a", run)
    sheet.mkdir()
    for name in ("review_rows.json", "llm_review.json", "review_sheet.md"):
        (run / name).rename(sheet / name)
    meta = json.loads((sheet / "review_rows.json").read_text())
    meta.update(safe="proj_b-safe", thorough="proj_b-thorough")
    meta["rows"][0]["run"] = meta["rows"][1]["run"] = "proj_b-safe"
    meta["rows"].append({**meta["rows"][0], "n": 3, "run": "proj_b-thorough"})
    (sheet / "review_rows.json").write_text(json.dumps(meta))
    row = next(r for r in client.get("/api/cases").json() if r["name"] == "proj_b-safe")
    assert row["has_review"] and (row["accepted"], row["rejected"]) == (1, 1)
    case = client.get("/api/cases/proj_b-safe").json()
    assert [r["llm_decision"] for r in case["review"]["rows"]] == ["accept", "reject"]
    assert case["review"]["model"] and "review_sheet.md" in case["docs"]


def test_watch_folder_and_replay_table(client):
    log = client.get("/api/watch", params={"root": "results", "path": "raw/watch_a"}).json()
    assert [e["decision"] for e in log["entries"]] == ["clean", "wait"]
    assert log["runs"] == ["clean-001"] and log["state"]["cleans"] == 1
    assert client.get("/api/watch-replay").json()["table"] is None


def test_parity_pages_with_small_results(client):
    scheduler = client.get("/api/parity/scheduler").json()
    assert scheduler["means"]["rows"] and scheduler["repo"] in scheduler["repos"]
    assert client.get("/api/parity/baselines").json()["main"]["rows"]
    guard = client.get("/api/parity/guard").json()
    assert guard["strength"]["rows"] and guard["figure"] is None
    data = client.get("/api/parity/data").json()
    assert data["funnel"] is None and data["rules"] is None


def test_parity_pages_on_the_committed_results(tmp_path):
    app = create_app(tmp_path / "runs", dist=tmp_path / "dist", hosts=("testserver",))
    with TestClient(app) as c:
        data = c.get("/api/parity/data").json()
        assert len(data["rules"]["rows"]) == 10 and data["funnel"]["rows"]
        scheduler = c.get("/api/parity/scheduler").json()
        assert scheduler["curves"]["rows"]
        assert scheduler["figure"] == "figures/v1/scheduler_tradeoff.png"
        image = c.get("/api/image", params={"root": "results", "path": scheduler["figure"]})
        assert image.headers["content-type"] == "image/png"


def test_v1_score_reads_the_answer_key(client):
    query = {"root": "replay", "path": "20261030_demo_feature_advisory_v1"}
    score = client.get("/api/run/score", params=query).json()["score"]
    assert score["hits"] == 7 and score["total"] == 7


def test_jobs_refuse_bad_requests(client):
    assert client.post("/api/jobs", content="kind=clean").status_code == 415
    for spec in (
        {"kind": "deploy"},
        {"kind": "clean", "target": "relative/path"},
        {"kind": "clean", "target": "toy", "mode": "fast"},
        {"kind": "clean", "target": "toy", "budget": "coffee=2"},
        {"kind": "sweep", "target": "toy", "method": "magic"},
        {"kind": "clean", "target": "toy", "model": "a b; rm"},
        {"kind": "watch", "target": "toy"},
    ):
        assert client.post("/api/jobs", json=spec).status_code == 400, spec
    assert client.post("/api/jobs/none/stop").status_code == 404
    assert client.get("/api/jobs").json() == []


def test_other_hosts_are_refused(tmp_path, results):
    app = create_app(tmp_path / "runs", dist=tmp_path / "dist", results=results)
    with TestClient(app) as c:
        assert c.get("/api/health").status_code == 400
        assert c.get("/api/health", headers={"host": "127.0.0.1:8765"}).status_code == 200


def test_frontend_is_served_with_a_fallback_to_index(client, tmp_path):
    assert client.get("/").status_code == 503
    dist = tmp_path / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text("<html>studio</html>")
    (dist / "assets" / "app.js").write_text("console.log(1)")
    assert client.get("/").text == "<html>studio</html>"
    assert client.get("/replay/anything").text == "<html>studio</html>"
    assert client.get("/assets/app.js").text == "console.log(1)"
    assert "[build-system]" not in client.get("/../pyproject.toml").text


@pytest.mark.slow
def test_a_clean_job_runs_offline_and_streams_its_events(client):
    job = client.post("/api/jobs", json={"kind": "clean", "target": "toy", "no_llm": True}).json()
    assert job["status"] == "running" and job["root"] == "runs"
    with client.stream("GET", "/api/run/stream", params={"root": "runs", "path": job["path"]}) as r:
        body = "".join(r.iter_text())
    lines = [line for line in body.splitlines() if line.startswith('data: {"')]
    kinds = [json.loads(line[6:])["kind"] for line in lines]
    assert kinds[0] == "run_start" and kinds[-1] == "run_end"
    assert client.get("/api/jobs").json()[0]["status"] == "done"


def test_shipped_v2_recording_is_small_and_self_contained():
    folder = ROOT / "demo" / "replay" / REPLAY_RUN
    assert sum(p.stat().st_size for p in folder.rglob("*") if p.is_file()) < 400_000
    assert not (folder / "workspace").exists() and (folder / "cache").is_dir()
