"""PromptSeal command-line interface."""

from __future__ import annotations

import json
import os
import sys
import time
import webbrowser
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import typer
import httpx
from rich.console import Console
from rich.table import Table

from promptseal import assertions, driftwatch as driftwatch_mod
from promptseal import record as record_mod
from promptseal import report as report_mod
from promptseal import report_html, server as server_mod, storage
from promptseal._version import __version__
from promptseal.config import find_config, load_config
from promptseal.diff import DiffReport, diff_runs
from promptseal.init_templates import INIT_CASES, INIT_YAML
from promptseal.models import Run
from promptseal.providers import ProviderError, get_provider
from promptseal.runner import CaseFilter, execute, execute_matrix, load_suites

# Windows consoles (and CI logs) often default to a legacy code page (cp1252);
# force UTF-8 so the seal and table glyphs never crash the CLI.
for _stream in (sys.stdout, sys.stderr):
    if _stream is not None and hasattr(_stream, "reconfigure"):
        try:
            _stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:  # noqa: BLE001 — never let output config kill the CLI
            pass

app = typer.Typer(
    name="promptseal",
    help="🦭 Regression testing for prompts, agents, and models.",
    no_args_is_help=True,
    add_completion=False,
    pretty_exceptions_show_locals=False,
)
console = Console()


def _version_callback(value: Optional[bool]) -> None:
    if value:
        console.print(f"promptseal {__version__} 🦭")
        raise typer.Exit()


@app.callback()
def _root(
    version: Optional[bool] = typer.Option(
        None,
        "--version",
        "-V",
        callback=_version_callback,
        is_eager=True,
        help="Show the PromptSeal version and exit.",
    ),
) -> None:
    """Load third-party assertion plugins (entry-point group promptseal.assertions)."""
    assertions.load_plugins()


def _config():
    path = find_config()
    if path is None:
        console.print("[red]No promptseal.yaml found. Run `promptseal init` first.[/]")
        raise typer.Exit(1)
    return load_config(path)


def _check_repeat_args(repeat: Optional[int], flaky_rate: Optional[float]) -> None:
    if repeat is not None and repeat < 1:
        raise typer.BadParameter("--repeat must be >= 1")
    if flaky_rate is not None and not 0.0 < flaky_rate <= 1.0:
        raise typer.BadParameter("--flaky-pass-rate must be in (0, 1]")


def _check_concurrency(value: Optional[int]) -> None:
    if value is not None and value < 1:
        raise typer.BadParameter("--concurrency must be >= 1")


@app.command()
def version() -> None:
    """Show the PromptSeal version."""
    console.print(f"promptseal {__version__} 🦭")


@app.command()
def init(
    force: bool = typer.Option(False, "--force", help="Overwrite existing files."),
    provider: Optional[str] = typer.Option(
        None, "--provider", "-p", help="Default provider spec written into the scaffold (e.g. ollama:llama3.1:8b)"
    ),
    suite: Optional[str] = typer.Option(
        None, "--suite", help="Suite name written into the scaffold"
    ),
) -> None:
    """Create promptseal.yaml and a starter case suite."""
    yaml_text = INIT_YAML
    if provider:
        if ":" not in provider:
            raise typer.BadParameter("--provider must look like 'name:model', e.g. openai:gpt-4o")
        yaml_text = yaml_text.replace("provider: mock:echo", f"provider: {provider}")
    if suite:
        yaml_text = yaml_text.replace("suite: my-app", f"suite: {suite}")
    created = []
    for rel, content in (("promptseal.yaml", yaml_text), (Path("cases") / "smoke.yaml", INIT_CASES)):
        path = Path(rel)
        if path.exists() and not force:
            console.print(f"[yellow]{rel} already exists — skipping.[/]")
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        created.append(str(path))
    console.print("[green]🦭 Initialized PromptSeal.[/]")
    for rel in created:
        console.print(f"   created [cyan]{rel}[/]")
    console.print("\nNext steps:")
    console.print("  [bold]promptseal run[/]  — run the suite (mock:echo, no API key needed)")
    console.print("  [bold]promptseal run --save-baseline[/]  — seal the current behavior")
    console.print("  [bold]promptseal ci[/]  — compare against baseline (CI mode)")


def _run_single(
    config,
    provider_spec: str,
    cases_dir: Optional[Path],
    save_baseline: bool = False,
    html: bool = False,
    json_out: bool = False,
    fail_on_failure: bool = True,
    repeat: Optional[int] = None,
    flaky_pass_rate: Optional[float] = None,
    case_filter: Optional[CaseFilter] = None,
    fail_fast: bool = False,
    concurrency: Optional[int] = None,
) -> Run:
    run_result = execute(
        config,
        provider_spec=provider_spec,
        cases_dir=cases_dir,
        repeat=repeat,
        flaky_pass_rate=flaky_pass_rate,
        case_filter=case_filter,
        fail_fast=fail_fast,
        concurrency=concurrency,
    )
    if json_out:
        typer.echo(run_result.model_dump_json(indent=2))
    else:
        report_mod.print_run(run_result)
        run_path = storage.runs_dir() / f"{run_result.meta.run_id}.json"
        console.print(f"   saved: [dim]{run_path}[/dim]")
        if html:
            out = Path("promptseal-report.html")
            out.write_text(report_html.render_html(run_result), encoding="utf-8")
            console.print(f"   report: [cyan]{out.resolve()}[/cyan]")
        if save_baseline:
            # Embed the full run so baseline.json is self-contained (CI-friendly).
            storage.save_baseline(run_result.meta.run_id, run=run_result)
            storage.append_audit(
                "seal",
                run_id=run_result.meta.run_id,
                provider=f"{run_result.meta.provider}:{run_result.meta.model}",
                suite=run_result.meta.suite,
            )
            console.print(f"   [green]baseline sealed:[/] {run_result.meta.run_id}")
    if fail_on_failure and run_result.summary.pass_rate < 1.0:
        raise typer.Exit(1)
    return run_result


@app.command()
def run(
    providers: Optional[list[str]] = typer.Option(
        None, "--provider", "-p",
        help="Provider spec, e.g. -p openai:gpt-4o. Repeat the flag to compare models side-by-side.",
    ),
    cases_dir: Optional[Path] = typer.Option(None, "--cases", help="Cases directory override"),
    save_baseline: bool = typer.Option(False, "--save-baseline", help="Mark this run as the baseline"),
    html: bool = typer.Option(False, "--html", help="Also write an HTML report"),
    json_out: bool = typer.Option(False, "--json", help="Machine-readable JSON output"),
    repeat: Optional[int] = typer.Option(
        None, "--repeat", help="Run each case N times (flaky detection); overrides config"
    ),
    flaky_rate: Optional[float] = typer.Option(
        None, "--flaky-pass-rate", help="Fraction of attempts that must pass, 0<r<=1; overrides config"
    ),
    tags: Optional[str] = typer.Option(
        None, "--tags", help="Only run cases carrying ANY of these tags (comma-separated)"
    ),
    exclude_tags: Optional[str] = typer.Option(
        None, "--exclude-tags", help="Skip cases carrying ANY of these tags (comma-separated)"
    ),
    only: Optional[str] = typer.Option(
        None, "--case", help="Only run these case IDs (comma-separated) — great for debugging one case"
    ),
    skip: Optional[str] = typer.Option(
        None, "--skip-case", help="Skip these case IDs (comma-separated)"
    ),
    fail_fast: bool = typer.Option(
        False, "--fail-fast", help="Stop at the first failing case (ignored with --concurrency > 1)"
    ),
    concurrency: Optional[int] = typer.Option(
        None, "--concurrency", help="Run cases in N parallel threads (default: config defaults.concurrency)"
    ),
    list_only: bool = typer.Option(
        False, "--list", help="List the matching cases and exit — no provider calls, no API key needed"
    ),
) -> None:
    """Run the eval suite against one provider — or compare several in a matrix."""
    config = _config()
    _check_repeat_args(repeat, flaky_rate)
    _check_concurrency(concurrency)
    case_filter = CaseFilter.parse(tags, exclude_tags, only, skip)

    if list_only:
        try:
            cases_path = cases_dir or (Path.cwd() / config.cases_dir)
            entries = [(s.name, c) for s in load_suites(cases_path) for c in s.cases]
        except (FileNotFoundError, ValueError) as exc:
            console.print(f"[red]{exc}[/]")
            raise typer.Exit(1)
        matched = [(sn, c) for sn, c in entries if case_filter.matches(c)]
        table = Table(show_header=True, header_style="bold")
        table.add_column("Case", style="cyan", no_wrap=True)
        table.add_column("Suite")
        table.add_column("Tags")
        table.add_column("Checks", justify="right")
        for sn, c in matched:
            table.add_row(c.id, sn, ", ".join(c.tags) or "—", str(len(c.asserts)))
        console.print(table)
        console.print(f"[green]{len(matched)}[/] of {len(entries)} case(s) match. No provider was called.")
        return

    specs = list(providers) if providers else [config.default_provider]
    try:
        if len(specs) == 1:
            _run_single(
                config,
                specs[0],
                cases_dir,
                save_baseline,
                html,
                json_out,
                repeat=repeat,
                flaky_pass_rate=flaky_rate,
                case_filter=case_filter,
                fail_fast=fail_fast,
                concurrency=concurrency,
            )
            return

        runs = execute_matrix(
            config, specs, cases_dir=cases_dir, repeat=repeat, flaky_pass_rate=flaky_rate,
            case_filter=case_filter, fail_fast=fail_fast, concurrency=concurrency,
        )
        if json_out:
            typer.echo(json.dumps([json.loads(r.model_dump_json()) for r in runs], indent=2))
        else:
            report_mod.print_matrix(runs)
            for r in runs:
                console.print(f"   saved: [dim]{storage.runs_dir() / (r.meta.run_id + '.json')}[/dim]")
        if html:
            out = Path("promptseal-matrix.html")
            stamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
            out.write_text(report_html.render_matrix_html(runs, generated_at=stamp), encoding="utf-8")
            console.print(f"   report: [cyan]{out.resolve()}[/cyan]")
        if save_baseline:
            # In matrix mode the first listed provider is treated as the reference model.
            storage.save_baseline(runs[0].meta.run_id, run=runs[0])
            storage.append_audit(
                "seal",
                run_id=runs[0].meta.run_id,
                provider=f"{runs[0].meta.provider}:{runs[0].meta.model}",
                suite=runs[0].meta.suite,
            )
            console.print(f"   [green]baseline sealed:[/] {runs[0].meta.run_id}")
    except typer.Exit:
        raise
    except Exception as exc:  # noqa: BLE001
        console.print(f"[red]Run failed: {exc}[/]")
        raise typer.Exit(1)


@app.command()
def seal(
    provider: Optional[str] = typer.Option(None, "--provider", "-p", help="Provider spec override"),
    cases_dir: Optional[Path] = typer.Option(None, "--cases", help="Cases directory override"),
    html: bool = typer.Option(False, "--html", help="Also write an HTML report"),
) -> None:
    """Run the suite and 🔒 seal the result as your baseline."""
    config = _config()
    try:
        _run_single(
            config,
            provider or config.default_provider,
            cases_dir,
            save_baseline=True,
            html=html,
            json_out=False,
            fail_on_failure=False,
        )
    except typer.Exit:
        raise
    except Exception as exc:  # noqa: BLE001
        console.print(f"[red]Run failed: {exc}[/]")
        raise typer.Exit(1)
    console.print("[green]Behavior sealed. From now on, `promptseal ci` guards it.[/]")


@app.command()
def record(
    upstream: Optional[str] = typer.Option(
        None, "--upstream", "-u",
        help="Real provider base URL to forward to (e.g. https://api.openai.com/v1).",
    ),
    port: int = typer.Option(8819, "--port", help="Local port for the recorder proxy"),
    capture_dir: Optional[Path] = typer.Option(None, "--capture-dir", help="Where captures are stored"),
    no_redact: bool = typer.Option(False, "--no-redact", help="Disable PII redaction (not recommended)"),
    to_cases: bool = typer.Option(False, "--to-cases", help="Convert existing captures into a draft suite"),
    out: Path = typer.Option(Path("cases") / "recorded.yaml", "--out", help="Output YAML for --to-cases"),
    suite: str = typer.Option("recorded", "--suite", help="Suite name for --to-cases"),
    max_cases: int = typer.Option(50, "--max", help="Max cases generated by --to-cases"),
    max_latency_s: Optional[float] = typer.Option(None, "--max-latency", help="Add a max_latency_s assertion"),
) -> None:
    """Record real chat traffic through a local proxy — or convert captures to cases.

    Without --to-cases: starts the recorder proxy. Point your app's
    OPENAI_BASE_URL at http://127.0.0.1:8819/v1 and use it as usual; every
    request/response pair is captured locally. Press Ctrl+C to stop.
    """
    root = Path.cwd()
    cdir = capture_dir or (root / ".promptseal" / "captures")

    if to_cases:
        if not cdir.exists() or not list(cdir.glob("*.jsonl")):
            console.print(f"[red]No captures found in {cdir}. Run `promptseal record` first.[/]")
            raise typer.Exit(1)
        suite_dict = record_mod.captures_to_cases(
            cdir, suite=suite, max_cases=max_cases, max_latency_s=max_latency_s
        )
        count = len(suite_dict["cases"])
        if count == 0:
            console.print("[yellow]Captures contained no usable user prompts.[/]")
            raise typer.Exit(1)
        path = record_mod.write_cases_yaml(suite_dict, root / out)
        console.print(f"🦭 [green]{count} draft case(s) written to[/] [cyan]{path}[/cyan]")
        console.print("Review them, add stronger assertions (llm_judge, not_contains, ...), then:")
        console.print("   [bold]promptseal seal[/] — seal current behavior as baseline")
        return

    if not upstream:
        config = _config()
        spec = config.default_provider
        if spec.startswith(("mock:",)):
            console.print("[red]--upstream is required when your default provider is a mock.[/]")
            raise typer.Exit(1)
        pconf = config.provider(spec.split(":", 1)[0])
        upstream = pconf.base_url or None
        if not upstream:
            console.print("[red]Could not infer upstream from config; pass --upstream explicitly.[/]")
            raise typer.Exit(1)

    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    capture_path = cdir / f"capture-{stamp}.jsonl"
    proxy = record_mod.RecordProxy(
        upstream=upstream,
        capture_path=capture_path,
        port=port,
        redact_pii=not no_redact,
        timeout_s=60.0,
    ).start()

    console.print("🦭 [bold]PromptSeal recorder is running.[/]")
    console.print(f"   proxy:  [cyan]{proxy.base_url}/v1[/cyan]  →  upstream [dim]{upstream}[/dim]")
    console.print(f"   capture: [dim]{capture_path}[/dim]  (redaction {'ON' if not no_redact else 'OFF'})")
    console.print("\nPoint your app at the proxy:")
    console.print(f"   [bold]OPENAI_BASE_URL={proxy.base_url}/v1[/bold]")
    console.print("\nEvery request will be forwarded and captured. Press [bold]Ctrl+C[/] to stop.")
    try:
        while True:
            time.sleep(0.5)
    except KeyboardInterrupt:
        pass
    finally:
        proxy.shutdown()
    console.print(f"\n[green]Captured [bold]{proxy.captured_count}[/] request(s).[/]")
    console.print("Now convert them into eval cases:")
    console.print("   [bold]promptseal record --to-cases[/]")



def _diff_to_dict(diff: DiffReport) -> dict:
    return {
        "baseline": diff.baseline_run_id,
        "candidate": diff.candidate_run_id,
        "baseline_pass_rate": diff.baseline_pass_rate,
        "candidate_pass_rate": diff.candidate_pass_rate,
        "verdict": diff.verdict,
        "regressions": [cid for cid, _, _ in diff.regressions],
        "improvements": [cid for cid, _, _ in diff.improvements],
        "stable_pass": diff.stable_pass,
        "stable_fail": diff.stable_fail,
        "new_cases": diff.new_cases,
        "missing_cases": diff.missing_cases,
    }


@app.command()
def diff(
    base: str = typer.Argument("baseline", help="Baseline run ref (baseline | latest | run_id | path)"),
    cand: str = typer.Argument("latest", help="Candidate run ref"),
    json_out: bool = typer.Option(False, "--json", help="Machine-readable JSON output"),
    fail_on_regression: bool = typer.Option(
        False, "--fail-on-regression", help="Exit 1 when the verdict is regression (for scripting)"
    ),
) -> None:
    """Compare two runs and show regressions/improvements."""
    try:
        base_run, _ = storage.resolve_run(base)
        cand_run, _ = storage.resolve_run(cand)
    except FileNotFoundError as exc:
        console.print(f"[red]{exc}[/]")
        raise typer.Exit(1)
    report = diff_runs(base_run, cand_run)
    storage.append_audit(
        "diff",
        baseline=report.baseline_run_id,
        candidate=report.candidate_run_id,
        verdict=report.verdict,
        regressions=len(report.regressions),
        improvements=len(report.improvements),
    )
    if json_out:
        typer.echo(json.dumps(_diff_to_dict(report), indent=2))
    else:
        report_mod.print_diff(report)
    if fail_on_regression and report.verdict != "pass":
        raise typer.Exit(1)


@app.command()
def report(
    run_ref: str = typer.Argument("latest", help="Run ref to render"),
    out: Path = typer.Option(Path("promptseal-report.html"), "--out", help="Output HTML path"),
    open_browser: bool = typer.Option(False, "--open", help="Open the report in a browser"),
) -> None:
    """Generate a self-contained HTML report for a run."""
    try:
        run_result, _ = storage.resolve_run(run_ref)
    except FileNotFoundError as exc:
        console.print(f"[red]{exc}[/]")
        raise typer.Exit(1)
    out.write_text(report_html.render_html(run_result), encoding="utf-8")
    console.print(f"🦭 report written: [cyan]{out.resolve()}[/cyan]")
    if open_browser:
        webbrowser.open(out.resolve().as_uri())


@app.command()
def runs(
    json_out: bool = typer.Option(False, "--json", help="Machine-readable JSON list"),
) -> None:
    """List saved runs."""
    all_runs = storage.list_runs()
    if not all_runs:
        console.print("[yellow]No runs yet — try `promptseal run`.[/]")
        return
    baseline_id = storage.load_baseline()
    if json_out:
        typer.echo(
            json.dumps(
                [
                    {
                        "run_id": r.meta.run_id,
                        "created_at": r.meta.created_at,
                        "provider": r.meta.provider,
                        "model": r.meta.model,
                        "suite": r.meta.suite,
                        "pass_rate": r.summary.pass_rate,
                        "total": r.summary.total,
                        "is_baseline": r.meta.run_id == baseline_id,
                    }
                    for r in all_runs
                ],
                indent=2,
            )
        )
        return
    table = Table(show_header=True, header_style="bold")
    table.add_column("Run ID", style="cyan")
    table.add_column("Provider")
    table.add_column("Suite")
    table.add_column("Pass rate", justify="right")
    table.add_column("Created")
    baseline_id = storage.load_baseline()
    for r in all_runs:
        mark = " [green]← baseline[/]" if r.meta.run_id == baseline_id else ""
        table.add_row(
            r.meta.run_id + mark,
            f"{r.meta.provider}:{r.meta.model}",
            r.meta.suite,
            f"{r.summary.pass_rate * 100:.0f}%",
            r.meta.created_at[:19].replace("T", " "),
        )
    console.print(table)


@app.command()
def driftwatch(
    out: Path = typer.Option(Path("promptseal-drift.html"), "--out", help="Output HTML path"),
    open_browser: bool = typer.Option(False, "--open", help="Open the dashboard in a browser"),
) -> None:
    """Local drift dashboard: pass-rate/cost/latency trends over all saved runs."""
    runs = storage.list_runs()
    if not runs:
        console.print("[red]No runs found — run `promptseal run` first.[/]")
        raise typer.Exit(1)
    stamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
    out.write_text(driftwatch_mod.render_html(runs, generated_at=stamp), encoding="utf-8")
    console.print(f"🦭 drift dashboard: [cyan]{out.resolve()}[/cyan] ({len(runs)} runs)")
    if open_browser:
        webbrowser.open(out.resolve().as_uri())


@app.command()
def doctor() -> None:
    """Self-check: config, providers, judge, assertion registry, storage."""
    failures = 0
    rows: list[tuple[str, str, str]] = []

    def record(name: str, ok: bool, detail: str = "", warn: bool = False) -> None:
        nonlocal failures
        if not ok and not warn:
            failures += 1
        rows.append((name, "✔" if ok else ("⚠" if warn else "✘"), detail))

    record("promptseal", True, f"v{__version__}")
    path = find_config()
    if path:
        record("config", True, str(path))
        cfg = load_config(path)
    else:
        record("config", False, "promptseal.yaml not found — defaults in use", warn=True)
        cfg = load_config()
    try:
        provider = get_provider(cfg.default_provider, cfg)
        record("default provider", True, f"{provider.name}:{provider.model} resolvable")
    except ProviderError as exc:
        record("default provider", False, str(exc))
    if cfg.judge.provider:
        try:
            judge = get_provider(cfg.judge.provider, cfg)
            record("judge provider", True, f"{judge.name}:{judge.model}")
        except ProviderError as exc:
            record("judge provider", False, str(exc))
    else:
        record("judge provider", True, "not set — defaults to the run provider")
    plugins = assertions.load_plugins()
    registry_detail = f"{len(assertions.available_checks())} checks registered"
    if plugins:
        registry_detail += f" · plugins: {', '.join(plugins)}"
    record("assertion registry", True, registry_detail)
    try:
        storage.runs_dir().mkdir(parents=True, exist_ok=True)
        record("storage", True, str(storage.runs_dir()))
    except OSError as exc:
        record("storage", False, str(exc))

    table = Table(show_header=True, header_style="bold")
    table.add_column("Check", style="cyan")
    table.add_column("Status", justify="center")
    table.add_column("Detail", overflow="fold")
    colors = {"✔": "green", "⚠": "yellow", "✘": "red"}
    for name, status, detail in rows:
        table.add_row(name, f"[{colors[status]}]{status}[/]", detail)
    console.print(table)
    if failures:
        console.print(f"[red]🦭 {failures} problem(s) found.[/]")
        raise typer.Exit(1)
    console.print("[green]🦭 All checks passed.[/]")


@app.command()
def audit(
    limit: int = typer.Option(20, "--limit", "-n", help="Show the last N events"),
) -> None:
    """Show the local audit log (seal / diff / ci events, newest last)."""
    events = storage.read_audit(limit=limit)
    if not events:
        console.print("[yellow]Audit log is empty — seal or run `ci` first.[/]")
        return
    table = Table(show_header=True, header_style="bold")
    table.add_column("Time", style="cyan")
    table.add_column("Event", justify="center")
    table.add_column("Details", overflow="fold")
    for event in reversed(events):  # chronological order in the table
        details = {k: v for k, v in event.items() if k not in ("ts", "event")}
        table.add_row(
            str(event.get("ts", "?")),
            str(event.get("event", "?")),
            json.dumps(details, ensure_ascii=False)[:200],
        )
    console.print(table)


@app.command()
def server(
    port: int = typer.Option(8800, "--port", help="Local port (binds to 127.0.0.1 only)"),
    root: Path = typer.Option(Path.cwd(), "--root", help="Project root containing .promptseal/"),
) -> None:
    """Serve a read-only local dashboard + JSON API over your run history."""
    srv = server_mod.PromptSealServer(root=root, port=port).start()
    console.print("🦭 [bold]PromptSeal server is running (read-only).[/]")
    console.print(f"   dashboard:  [cyan]{srv.base_url}/[/cyan]")
    console.print(f"   api:        [cyan]{srv.base_url}/api/runs[/cyan] · /api/stats · /api/health")
    console.print(f"   root:       [dim]{srv.root}[/dim]")
    console.print("\nPress [bold]Ctrl+C[/] to stop.")
    try:
        while True:
            time.sleep(0.5)
    except KeyboardInterrupt:
        pass
    finally:
        srv.shutdown()


@app.command()
def ci(
    provider: Optional[str] = typer.Option(None, "--provider", "-p", help="Provider override"),
    min_pass_rate: Optional[float] = typer.Option(
        None, "--min-pass-rate", help="Override ci.min_pass_rate from config"
    ),
    repeat: Optional[int] = typer.Option(
        None, "--repeat", help="Run each case N times (flaky detection); overrides config"
    ),
    flaky_rate: Optional[float] = typer.Option(
        None, "--flaky-pass-rate", help="Fraction of attempts that must pass, 0<r<=1; overrides config"
    ),
    tags: Optional[str] = typer.Option(
        None, "--tags", help="Only run cases carrying ANY of these tags (comma-separated)"
    ),
    exclude_tags: Optional[str] = typer.Option(
        None, "--exclude-tags", help="Skip cases carrying ANY of these tags (comma-separated)"
    ),
    only: Optional[str] = typer.Option(
        None, "--case", help="Only run these case IDs (comma-separated)"
    ),
    skip: Optional[str] = typer.Option(
        None, "--skip-case", help="Skip these case IDs (comma-separated)"
    ),
    fail_fast: bool = typer.Option(
        False, "--fail-fast", help="Stop at the first failing case (ignored with --concurrency > 1)"
    ),
    concurrency: Optional[int] = typer.Option(
        None, "--concurrency", help="Run cases in N parallel threads (default: config defaults.concurrency)"
    ),
) -> None:
    """CI mode: run, diff against baseline, write step summary, exit 1 on regression."""
    config = _config()
    _check_repeat_args(repeat, flaky_rate)
    _check_concurrency(concurrency)
    case_filter = CaseFilter.parse(tags, exclude_tags, only, skip)
    if min_pass_rate is not None:
        config.ci.min_pass_rate = min_pass_rate
    try:
        run_result = execute(
            config,
            provider_spec=provider,
            repeat=repeat,
            flaky_pass_rate=flaky_rate,
            case_filter=case_filter,
            fail_fast=fail_fast,
            concurrency=concurrency,
        )
    except Exception as exc:  # noqa: BLE001
        console.print(f"[red]Run failed: {exc}[/]")
        raise typer.Exit(2)
    try:
        base_run, _ = storage.resolve_run("baseline")
    except FileNotFoundError as exc:
        console.print(f"[red]{exc}[/]")
        raise typer.Exit(2)

    diff = diff_runs(
        base_run,
        run_result,
        only_ids={r.case_id for r in run_result.results} if (tags or exclude_tags or only or skip) else None,
    )
    console.print(report_mod.summary_markdown(run_result, diff))

    summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary_path:
        with open(summary_path, "a", encoding="utf-8") as fh:
            fh.write(report_mod.summary_markdown(run_result, diff))
        console.print("   [dim]GitHub step summary written.[/]")

    failed = False
    if config.ci.fail_on_regression and diff.has_regressions:
        console.print(f"[red]Regressions detected: {len(diff.regressions)}[/]")
        failed = True
    if run_result.summary.pass_rate < config.ci.min_pass_rate:
        console.print(
            f"[red]Pass rate {run_result.summary.pass_rate:.0%} "
            f"< required {config.ci.min_pass_rate:.0%}[/]"
        )
        failed = True

    storage.append_audit(
        "ci",
        suite=config.suite,
        run_id=run_result.meta.run_id,
        verdict=diff.verdict,
        pass_rate=round(run_result.summary.pass_rate, 4),
        regressions=len(diff.regressions),
        failed=failed,
    )

    webhook = config.ci.alert_webhook
    if webhook:
        payload = {
            "event": "promptseal_ci",
            "suite": config.suite,
            "provider": f"{run_result.meta.provider}:{run_result.meta.model}",
            "run_id": run_result.meta.run_id,
            "pass_rate": round(run_result.summary.pass_rate, 4),
            "verdict": diff.verdict,
            "regressions": len(diff.regressions),
            "improvements": len(diff.improvements),
            "failed": failed,
        }
        try:
            response = httpx.post(webhook, json=payload, timeout=10.0)
            response.raise_for_status()
            console.print("   [dim]webhook alert sent.[/]")
        except Exception as exc:  # noqa: BLE001 — alerting must never break the gate
            console.print(f"[yellow]webhook alert failed: {exc}[/]")

    if failed:
        raise typer.Exit(1)
    console.print("[green]🦭 Sealed. No regressions detected.[/]")


if __name__ == "__main__":
    app()


