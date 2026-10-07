"""Run persistence: git-friendly JSON files under .promptseal/ (or $PROMPTSEAL_HOME)."""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from promptseal.models import Run

BASE_DIRNAME = ".promptseal"
RUNS_DIRNAME = "runs"
BASELINE_FILENAME = "baseline.json"
AUDIT_FILENAME = "audit.log"


def base_dir(root: Path | None = None) -> Path:
    """Storage root: $PROMPTSEAL_HOME when set (shared/monorepo baselines),
    otherwise <root or cwd>/.promptseal."""
    home = os.environ.get("PROMPTSEAL_HOME")
    if home:
        return Path(home).expanduser()
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
    runs.sort(key=lambda r: (r.meta.created_at, r.meta.run_id), reverse=True)
    return runs


def save_baseline(run_id: str, root: Path | None = None, run: Run | None = None) -> Path:
    """Save the baseline pointer.

    When `run` is given, a full snapshot of the run is embedded so baseline.json is
    self-contained: CI can resolve the baseline without .promptseal/runs/ ever being
    committed. baseline.json itself is git-whitelisted (see .gitignore).
    """
    path = base_dir(root) / BASELINE_FILENAME
    path.parent.mkdir(parents=True, exist_ok=True)
    payload: dict = {"run_id": run_id}
    if run is not None:
        payload["run"] = json.loads(run.model_dump_json())
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return path


def load_baseline(root: Path | None = None) -> str | None:
    path = base_dir(root) / BASELINE_FILENAME
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8")).get("run_id")
    except json.JSONDecodeError:
        return None


def load_baseline_run(root: Path | None = None) -> Run | None:
    """Return the run snapshot embedded in baseline.json, if present."""
    path = base_dir(root) / BASELINE_FILENAME
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None
    raw = data.get("run") if isinstance(data, dict) else None
    if not isinstance(raw, dict):
        return None
    try:
        return Run.model_validate(raw)
    except Exception:  # noqa: BLE001 — a corrupt snapshot behaves like "no snapshot"
        return None


def read_audit(root: Path | None = None, limit: int = 50) -> list[dict[str, Any]]:
    """Read the audit log, newest first, skipping corrupt lines."""
    path = base_dir(root) / AUDIT_FILENAME
    if not path.exists():
        return []
    out: list[dict[str, Any]] = []
    for line in reversed(path.read_text(encoding="utf-8").splitlines()):
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
        if len(out) >= limit:
            break
    return out


def append_audit(event: str, root: Path | None = None, **details: Any) -> None:
    """Append an event to the append-only audit log (.promptseal/audit.log, JSONL)."""
    path = base_dir(root) / AUDIT_FILENAME
    path.parent.mkdir(parents=True, exist_ok=True)
    entry: dict[str, Any] = {
        "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "event": event,
    }
    entry.update(details)
    with open(path, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(entry, ensure_ascii=False) + "\n")


def unique_run_id(run_id: str, root: Path | None = None) -> str:
    """Return run_id suffixed -2/-3/... if a run file with that id already exists.

    Run ids embed second granularity, so two same-second runs (same provider)
    would otherwise silently overwrite each other's JSON files.
    """
    base = run_id
    n = 2
    while (runs_dir(root) / f"{run_id}.json").exists():
        run_id = f"{base}-{n}"
        n += 1
    return run_id


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
        baseline_path = base_dir(root) / BASELINE_FILENAME
        run_id = load_baseline(root)
        embedded = load_baseline_run(root)
        # Prefer the embedded snapshot: baseline.json is git-whitelisted, so CI can
        # resolve the baseline even when .promptseal/runs/ was never committed.
        if embedded is not None:
            return embedded, baseline_path
        if run_id:
            path = directory / f"{run_id}.json"
            if path.exists():
                return load_run(path), path
            raise FileNotFoundError(
                "baseline saved but its run file is missing — re-seal with `promptseal seal`"
            )
        raise FileNotFoundError(
            "no baseline saved — create one with: promptseal run --save-baseline"
        )

    path = directory / f"{ref}.json"
    if path.exists():
        return load_run(path), path
    matches = [r for r in list_runs(root) if r.meta.run_id.startswith(ref)]
    if len(matches) == 1:
        run = matches[0]
        return run, directory / f"{run.meta.run_id}.json"
    raise FileNotFoundError(f"cannot resolve run reference: {ref!r}")
