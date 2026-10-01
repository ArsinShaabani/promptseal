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
from rich.console import Console
from rich.table import Table

from promptseal import record as record_mod
from promptseal import report as report_mod
from promptseal import report_html, storage
from promptseal._version import __version__
from promptseal.config import find_config, load_config
from promptseal.diff import DiffReport, diff_runs
from promptseal.init_templates import INIT_CASES, INIT_YAML
from promptseal.models import Run
from promptseal.runner import execute, execute_matrix

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


@app.command()
def version() -> None:
    """Show the PromptSeal version."""
    console.print(f"promptseal {__version__} 🦭")


@app.command()
def init(force: bool = typer.Option(False, "--force", help="Overwrite existing files.")) -> None:
    """Create promptseal.yaml and a starter case suite."""
    created = []
    for rel, content in (("promptseal.yaml", INIT_YAML), (Path("cases") / "smoke.yaml", INIT_CASES)):
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
) -> Run:
    run_result = execute(
        config,
        provider_spec=provider_spec,
        cases_dir=cases_dir,
        repeat=repeat,
        flaky_pass_rate=flaky_pass_rate,
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
) -> None:
    """Run the eval suite against one provider — or compare several in a matrix."""
    config = _config()
    _check_repeat_args(repeat, flaky_rate)
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
            )
            return

        runs = execute_matrix(
            config, specs, cases_dir=cases_dir, repeat=repeat, flaky_pass_rate=flaky_rate
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
) -> None:
    """Compare two runs and show regressions/improvements."""
    try:
        base_run, _ = storage.resolve_run(base)
        cand_run, _ = storage.resolve_run(cand)
    except FileNotFoundError as exc:
        console.print(f"[red]{exc}[/]")
        raise typer.Exit(1)
    report = diff_runs(base_run, cand_run)
    if json_out:
        typer.echo(json.dumps(_diff_to_dict(report), indent=2))
    else:
        report_mod.print_diff(report)


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
def runs() -> None:
    """List saved runs."""
    all_runs = storage.list_runs()
    if not all_runs:
        console.print("[yellow]No runs yet — try `promptseal run`.[/]")
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
) -> None:
    """CI mode: run, diff against baseline, write step summary, exit 1 on regression."""
    config = _config()
    _check_repeat_args(repeat, flaky_rate)
    if min_pass_rate is not None:
        config.ci.min_pass_rate = min_pass_rate
    try:
        run_result = execute(config, provider_spec=provider, repeat=repeat, flaky_pass_rate=flaky_rate)
    except Exception as exc:  # noqa: BLE001
        console.print(f"[red]Run failed: {exc}[/]")
        raise typer.Exit(2)
    try:
        base_run, _ = storage.resolve_run("baseline")
    except FileNotFoundError as exc:
        console.print(f"[red]{exc}[/]")
        raise typer.Exit(2)

    diff = diff_runs(base_run, run_result)
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
    if failed:
        raise typer.Exit(1)
    console.print("[green]🦭 Sealed. No regressions detected.[/]")


if __name__ == "__main__":
    app()


