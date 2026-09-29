"""PromptSeal command-line interface."""

from __future__ import annotations

import os
import webbrowser
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.table import Table

from promptseal import report as report_mod
from promptseal import report_html, storage
from promptseal._version import __version__
from promptseal.config import find_config, load_config
from promptseal.diff import diff_runs
from promptseal.init_templates import INIT_CASES, INIT_YAML
from promptseal.runner import execute

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


@app.command()
def run(
    provider: Optional[str] = typer.Option(None, "--provider", "-p", help="Provider spec, e.g. openai:gpt-4o"),
    cases_dir: Optional[Path] = typer.Option(None, "--cases", help="Cases directory override"),
    save_baseline: bool = typer.Option(False, "--save-baseline", help="Mark this run as the baseline"),
    html: bool = typer.Option(False, "--html", help="Also write a self-contained HTML report"),
) -> None:
    """Run the eval suite against a provider."""
    config = _config()
    try:
        run_result = execute(config, provider_spec=provider, cases_dir=cases_dir)
    except Exception as exc:  # noqa: BLE001
        console.print(f"[red]Run failed: {exc}[/]")
        raise typer.Exit(1)
    report_mod.print_run(run_result)
    run_path = storage.runs_dir() / f"{run_result.meta.run_id}.json"
    console.print(f"   saved: [dim]{run_path}[/dim]")
    if html:
        out = Path("promptseal-report.html")
        out.write_text(report_html.render_html(run_result), encoding="utf-8")
        console.print(f"   report: [cyan]{out.resolve()}[/cyan]")
    if save_baseline:
        storage.save_baseline(run_result.meta.run_id)
        console.print(f"   [green]baseline sealed:[/] {run_result.meta.run_id}")
    if run_result.summary.pass_rate < 1.0:
        raise typer.Exit(1)


@app.command()
def diff(
    base: str = typer.Argument("baseline", help="Baseline run ref (baseline | latest | run_id | path)"),
    cand: str = typer.Argument("latest", help="Candidate run ref"),
) -> None:
    """Compare two runs and show regressions/improvements."""
    try:
        base_run, _ = storage.resolve_run(base)
        cand_run, _ = storage.resolve_run(cand)
    except FileNotFoundError as exc:
        console.print(f"[red]{exc}[/]")
        raise typer.Exit(1)
    report_mod.print_diff(diff_runs(base_run, cand_run))


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
) -> None:
    """CI mode: run, diff against baseline, write step summary, exit 1 on regression."""
    config = _config()
    try:
        run_result = execute(config, provider_spec=provider)
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


