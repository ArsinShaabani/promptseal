"""Run persistence: git-friendly JSON files under .promptseal/runs/."""

from __future__ import annotations

import json
from pathlib import Path

from promptseal.models import Run

BASE_DIRNAME = ".promptseal"
RUNS_DIRNAME = "runs"
BASELINE_FILENAME = "baseline.json"


def base_dir(root: Path | None = None) -> Path:
    return (root or Path.cwd()) / BASE_DIRNAME


def runs_dir(root: Path | None = None) -> Path:
    return base_dir(root) / RUNS_DIRNAME


def save_run(run: Run, root: Path | None = None) -> Path:
    directory = runs_dir(root)
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{run.meta.run_id}.json"
    path.write_text(run.model_dump_json(indent=2), encoding="utf-8")
    return path


def load_run(path: Path) -> Run:
    return Run.model_validate_json(path.read_text(encoding="utf-8"))


def list_runs(root: Path | None = None) -> list[Run]:
    directory = runs_dir(root)
    if not directory.exists():
        return []
    runs = []
    for path in sorted(directory.glob("*.json")):
        try:
            runs.append(load_run(path))
        except Exception:  # noqa: BLE001 — skip corrupt files
            continue
    runs.sort(key=lambda r: r.meta.created_at, reverse=True)
    return runs


def save_baseline(run_id: str, root: Path | None = None) -> Path:
    path = base_dir(root) / BASELINE_FILENAME
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"run_id": run_id}), encoding="utf-8")
    return path


def load_baseline(root: Path | None = None) -> str | None:
    path = base_dir(root) / BASELINE_FILENAME
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8")).get("run_id")
    except json.JSONDecodeError:
        return None


def resolve_run(ref: str, root: Path | None = None) -> tuple[Run, Path]:
    """Resolve 'latest', 'baseline', a run_id (or prefix), or a path to a run file."""
    p = Path(ref)
    if p.suffix == ".json" and p.exists():
        return load_run(p), p

    directory = runs_dir(root)
    if ref == "latest":
        runs = list_runs(root)
        if not runs:
            raise FileNotFoundError("no runs found — run `promptseal run` first")
        run = runs[0]
        return run, directory / f"{run.meta.run_id}.json"

    if ref == "baseline":
        run_id = load_baseline(root)
        if not run_id:
            raise FileNotFoundError(
                "no baseline saved — create one with: promptseal run --save-baseline"
            )
        path = directory / f"{run_id}.json"
        return load_run(path), path

    path = directory / f"{ref}.json"
    if path.exists():
        return load_run(path), path
    matches = [r for r in list_runs(root) if r.meta.run_id.startswith(ref)]
    if len(matches) == 1:
        run = matches[0]
        return run, directory / f"{run.meta.run_id}.json"
    raise FileNotFoundError(f"cannot resolve run reference: {ref!r}")
