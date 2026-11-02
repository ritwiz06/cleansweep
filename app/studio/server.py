"""Studio's web server: a JSON API over runs, results and case studies, plus the built frontend.

Start it with `cleansweep studio`; the API is under /api and everything else is the React app.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import threading
import time
import webbrowser
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from starlette.middleware.trustedhost import TrustedHostMiddleware

from . import data, files, jobs, runs
from .files import ROOT, Forbidden

FRONTEND = Path(__file__).resolve().parent / "frontend"
DIST = FRONTEND / "dist"
DEFAULT_RUNS = ROOT / "results" / "raw" / "studio"
IMAGES = {".png": "image/png", ".svg": "image/svg+xml", ".jpg": "image/jpeg"}
TEXT = {".md", ".txt", ".diff", ".json", ".csv", ".log", ".patch"}
POLL = 0.3
HEARTBEAT = 10.0


def create_app(
    runs_dir: str | Path = DEFAULT_RUNS,
    dist: str | Path = DIST,
    hosts: tuple[str, ...] = ("127.0.0.1", "localhost"),
    results: str | Path = ROOT / "results",
) -> FastAPI:
    """The Studio app over one runs folder (where Studio's own runs go), for local hosts only."""
    runs_dir = Path(runs_dir).expanduser().resolve()
    dist = Path(dist)
    roots = {**files.default_roots(runs_dir), "results": Path(results)}
    manager = jobs.JobManager(runs_dir)
    app = FastAPI(title="CleanSweep Studio", docs_url=None, redoc_url=None)
    # other host names (DNS rebinding) are refused; no CORS, so other sites cannot call the API
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=list(hosts))
    app.state.jobs = manager

    @app.exception_handler(Forbidden)
    def forbidden(request: Request, exc: Forbidden):
        return JSONResponse({"detail": str(exc)}, status_code=403)

    @app.exception_handler(FileNotFoundError)
    def missing(request: Request, exc: FileNotFoundError):
        return JSONResponse({"detail": str(exc) or "not found"}, status_code=404)

    def folder(root: str, path: str) -> Path:
        found = files.resolve(roots, root, path)
        if not found.is_dir():
            raise FileNotFoundError(f"no run folder {root}/{path}")
        return found

    @app.get("/api/health")
    def health() -> dict:
        return {"ok": True, "runs": str(runs_dir), "watch": jobs.watch_available()}

    @app.get("/api/runs")
    def list_runs() -> list[dict]:
        rows = runs.list_runs(roots)
        for row in rows:
            row["live"] = manager.running(roots[row["root"]] / row["path"])
        return rows

    @app.get("/api/run")
    def run_detail(root: str, path: str) -> dict:
        found = folder(root, path)
        out = runs.detail(root, path, found)
        out["live"] = manager.running(found)
        job = manager.job_for(found)
        if job is not None:
            # before the first event the folder is empty; the job knows what it will hold
            out["kind"] = {"clean": "v2", "sweep": "v1", "watch": "watch"}[job.kind]
        return out

    @app.get("/api/run/events")
    def run_events(root: str, path: str) -> list[dict]:
        return files.events(folder(root, path) / "events.jsonl")

    @app.get("/api/run/stream")
    def run_stream(root: str, path: str, after: int = Query(0, ge=0)):
        found = folder(root, path)
        return StreamingResponse(
            _stream(found, after, manager),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    @app.get("/api/run/diff")
    def run_diff(root: str, path: str) -> dict:
        return {"text": runs.final_diff(folder(root, path))}

    @app.get("/api/run/artifact")
    def run_artifact(root: str, path: str, id: str) -> dict:
        return runs.artifact(folder(root, path), id)

    @app.get("/api/run/score")
    def run_score(root: str, path: str) -> dict:
        found = folder(root, path)
        target = runs.summary(root, path, found).get("target") or ""
        return {
            "score": data.sweep_score(found, target),
            "toy_runs": data.toy_runs(roots["results"]),
        }

    @app.get("/api/reports")
    def list_reports() -> list[dict]:
        return runs.find_reports(roots)

    @app.get("/api/report")
    def read_report(root: str, path: str) -> dict:
        return runs.report_file(files.resolve(roots, root, path))

    @app.get("/api/file")
    def read_file(root: str, path: str) -> dict:
        found = files.resolve(roots, root, path)
        if found.suffix not in TEXT or not found.is_file():
            raise FileNotFoundError(f"no text file {root}/{path}")
        return files.read_text(found)

    @app.get("/api/image")
    def image(root: str, path: str):
        found = files.resolve(roots, root, path)
        if found.suffix not in IMAGES or not found.is_file():
            raise FileNotFoundError(f"no image {root}/{path}")
        return FileResponse(found, media_type=IMAGES[found.suffix])

    @app.get("/api/table")
    def read_table(root: str, path: str) -> dict:
        found = files.resolve(roots, root, path)
        if found.suffix != ".csv":
            raise FileNotFoundError(f"no table {root}/{path}")
        return data.table(data.read_csv(found)) or {"columns": [], "rows": []}

    @app.get("/api/results")
    def results_index() -> dict:
        return data.results_index(roots["results"])

    @app.get("/api/cases")
    def cases() -> list[dict]:
        return data.case_list(roots["results"])

    @app.get("/api/cases/{name}")
    def case(name: str) -> dict:
        return data.case_detail(roots["results"], name)

    @app.get("/api/cases/{name}/diff")
    def case_diff(name: str) -> dict:
        found = files.resolve(roots, "results", f"raw/case_studies/{name}/final.diff")
        return files.read_text(found) if found.is_file() else {"text": ""}

    @app.get("/api/watch")
    def watch(root: str, path: str) -> dict:
        return data.watch_log(folder(root, path))

    @app.get("/api/watch-replay")
    def watch_replay() -> dict:
        path = roots["results"] / "summary" / "v2" / "watch_replay.csv"
        return {"table": data.table(data.read_csv(path))}

    @app.get("/api/parity/scheduler")
    def parity_scheduler(repo: str | None = None) -> dict:
        return data.scheduler(roots["results"], repo)

    @app.get("/api/parity/baselines")
    def parity_baselines() -> dict:
        return data.baselines(roots["results"])

    @app.get("/api/parity/data")
    def parity_data() -> dict:
        return data.data_page(roots["results"])

    @app.get("/api/parity/guard")
    def parity_guard() -> dict:
        return data.guard(roots["results"])

    @app.get("/api/targets")
    def targets() -> dict:
        from cleansweep.core.models import METHODS

        return {
            "targets": jobs.targets(),
            "methods": METHODS,
            "modes": list(jobs.MODES),
            "judge_modes": list(jobs.JUDGE_MODES),
            "watch": jobs.watch_available(),
        }

    @app.get("/api/jobs")
    def list_jobs() -> list[dict]:
        return manager.list()

    @app.post("/api/jobs")
    async def start_job(request: Request) -> dict:
        # a JSON body needs a CORS preflight, which this server never grants to other sites
        if not request.headers.get("content-type", "").startswith("application/json"):
            raise HTTPException(415, "send application/json")
        try:
            spec = await request.json()
        except ValueError:
            raise HTTPException(400, "send a JSON object") from None
        if not isinstance(spec, dict):
            raise HTTPException(400, "send a JSON object")
        try:
            job = manager.start(spec)
        except jobs.JobError as exc:
            raise HTTPException(400, str(exc)) from None
        return job.info(runs_dir)

    @app.post("/api/jobs/{job_id}/stop")
    def stop_job(job_id: str) -> dict:
        job = manager.stop(job_id)
        if job is None:
            raise HTTPException(404, f"no job {job_id}")
        return job.info(runs_dir)

    @app.get("/api/jobs/{job_id}/log")
    def job_log(job_id: str) -> dict:
        job = manager.get(job_id)
        if job is None or not job.log.is_file():
            raise HTTPException(404, f"no log for job {job_id}")
        return files.read_text(job.log, limit=200_000)

    @app.get("/api/{rest:path}")
    def unknown_api(rest: str):
        raise HTTPException(404, f"no API route /api/{rest}")

    @app.get("/{rest:path}")
    def frontend(rest: str):
        index = dist / "index.html"
        if not index.is_file():
            return JSONResponse(
                {"detail": "the frontend is not built; run: " + " && ".join(BUILD_HINT)},
                status_code=503,
            )
        target = (dist / rest).resolve()
        if rest and target.is_file() and target.is_relative_to(dist.resolve()):
            return FileResponse(target)
        return FileResponse(index)

    return app


def _finished(event: dict) -> bool:
    if event.get("v") == 2:
        return event.get("kind") == "run_end"
    return event.get("kind") == "error" or (
        event.get("kind") == "stage_done" and event.get("stage") == "done"
    )


def _stream(folder: Path, after: int, manager: jobs.JobManager):
    """Server-sent events: the events from index `after`, then each new one as it is written."""
    path = folder / "events.jsonl"
    offset, index, buffer = 0, 0, ""
    last_beat = time.time()
    while True:
        chunk = ""
        if path.is_file():
            with path.open(encoding="utf-8", errors="replace") as f:
                f.seek(offset)
                chunk = f.read()
                offset = f.tell()
        if chunk:
            buffer += chunk
            *lines, buffer = buffer.split("\n")
            for line in lines:
                if not line.strip():
                    continue
                try:
                    event = files.clean(json.loads(line))
                except ValueError:
                    continue
                if index >= after:
                    yield f"id: {index}\ndata: {json.dumps(event)}\n\n"
                index += 1
                if _finished(event) and not manager.running(folder):
                    yield "event: end\ndata: {}\n\n"
                    return
        elif not manager.running(folder):
            yield "event: end\ndata: {}\n\n"
            return
        if time.time() - last_beat > HEARTBEAT:
            last_beat = time.time()
            yield ": keep-alive\n\n"
        time.sleep(POLL)


BUILD_HINT = [f"cd {FRONTEND}", "npm ci", "npm run build"]


def build_frontend() -> bool:
    """Build the frontend with npm when dist/ is missing; False (with the commands) without npm."""
    if (DIST / "index.html").is_file():
        return True
    npm = shutil.which("npm")
    if npm is None:
        print("The Studio frontend is not built and npm is not installed. Build it with:")
        print("  " + "\n  ".join(BUILD_HINT))
        return False
    print("Building the Studio frontend (npm ci, npm run build) ...")
    for args in (["ci"], ["run", "build"]):
        if subprocess.run([npm, *args], cwd=FRONTEND).returncode != 0:
            print("The frontend build failed; run these by hand:\n  " + "\n  ".join(BUILD_HINT))
            return False
    return True


def serve(port: int = 8765, runs_dir: str | Path | None = None, open_browser: bool = True) -> int:
    """`cleansweep studio`: build the frontend if needed, then serve on localhost."""
    import uvicorn

    build_frontend()
    app = create_app(runs_dir or DEFAULT_RUNS)
    url = f"http://127.0.0.1:{port}/"
    print(f"CleanSweep Studio: {url}  (runs folder: {app.state.jobs.runs})")
    if open_browser:
        threading.Timer(1.0, webbrowser.open, args=(url,)).start()
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning")
    return 0
