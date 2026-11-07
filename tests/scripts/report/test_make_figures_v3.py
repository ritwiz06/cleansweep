import csv
import importlib.util
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[3] / "scripts" / "report" / "make_figures_v3.py"


def load():
    spec = importlib.util.spec_from_file_location("make_figures_v3", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _csv(path: Path, rows: list[dict]) -> None:
    with path.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def test_every_figure_builds_from_its_table_and_missing_tables_are_skipped(tmp_path, monkeypatch):
    figures = load()
    monkeypatch.setattr(figures, "SUMMARY", tmp_path)
    monkeypatch.setattr(figures, "FIGURES", tmp_path / "fig")
    assert figures.safety_yield() is None  # no table yet
    wrong = "wrong_all_tiers (incl. LLM-judged readings)"
    _csv(
        tmp_path / "curve.csv",
        [
            {"method": "agentic", "lines_removed": 300, wrong: 2, "wrong_confirmed": 1},
            {"method": "aider", "lines_removed": 900, wrong: 9, "wrong_confirmed": 4},
        ],
    )
    _csv(
        tmp_path / "injection.csv",
        [
            {"method": "agentic", "recall": 0.8, "recall_ci_low": 0.7, "recall_ci_high": 0.9},
        ],
    )
    _csv(
        tmp_path / "audit.csv",
        [
            {
                "set": "real v3",
                "method": "agentic",
                "kept_code_edits": 20,
                "share_confirmed": 0.05,
                "share_all_tiers": 0.1,
            },
        ],
    )
    _csv(
        tmp_path / "real.csv",
        [
            {
                "method": "agentic",
                "finished": 15,
                "heldout_changed_projects (finished)": 1,
                "visible_broken_projects (finished)": 0,
            },
        ],
    )
    _csv(
        tmp_path / "autonomy_runs.csv",
        [
            {"pass": 1, "completed": "True", "failure": "", "environment": ""},
            {"pass": 1, "completed": "False", "failure": "crash", "environment": ""},
            {
                "pass": 2,
                "completed": "False",
                "failure": "other stop",
                "environment": "needs a GPU",
            },
        ],
    )
    _csv(tmp_path / "cost.csv", [{"set": "REAL", "method": "agentic", "llm_requests_mean": 120}])
    made = [
        f()
        for f in (
            figures.safety_yield,
            figures.injection_recall,
            figures.audit_tiers,
            figures.heldout,
            figures.autonomy,
            figures.cost,
        )
    ]
    assert all(p is not None and p.exists() and p.stat().st_size > 1000 for p in made)


def test_autonomy_counts_whole_runs_and_needs_a_legend_only_for_two_passes(tmp_path, monkeypatch):
    figures = load()
    monkeypatch.setattr(figures, "SUMMARY", tmp_path)
    kept = []
    monkeypatch.setattr(figures, "save", lambda fig, name: kept.append(fig) or tmp_path / name)
    stop = {"completed": "False", "failure": "other stop", "environment": ""}
    _csv(tmp_path / "autonomy_runs.csv", [{"pass": 1, **stop}] * 3)
    figures.autonomy()
    ax = kept[-1].axes[0]
    assert ax.get_legend() is None and ax.get_title(loc="left").endswith("(pass 1)")
    assert all(t == int(t) for t in ax.get_xticks())
    _csv(tmp_path / "autonomy_runs.csv", [{"pass": 1, **stop}, {"pass": 2, **stop}])
    figures.autonomy()
    assert kept[-1].axes[0].get_legend() is not None
