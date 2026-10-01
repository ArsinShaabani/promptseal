"""Terminal (rich) and markdown reporting."""

from __future__ import annotations

from rich.console import Console
from rich.table import Table

from promptseal.diff import DiffReport
from promptseal.models import Run

console = Console()

_STATUS_STYLE = {"pass": "bold green", "fail": "bold red", "error": "bold yellow"}


def print_run(run: Run) -> None:
    meta = run.meta
    console.print()
    console.print(
        f"🦭 [bold]PromptSeal run[/bold] [dim]{meta.run_id}[/dim] — "
        f"[cyan]{meta.provider}:{meta.model}[/cyan] · suite [magenta]{meta.suite}[/magenta]"
    )
    s = run.summary
    rate = f"{s.pass_rate * 100:.0f}%"
    style = "green" if s.pass_rate == 1.0 else ("yellow" if s.pass_rate >= 0.5 else "red")
    console.print(
        f"   pass rate: [{style} bold]{rate}[/] ({s.passed}/{s.total}) · "
        f"failed [red]{s.failed}[/] · errors [yellow]{s.errors}[/] · "
        f"latency [blue]{s.total_latency_ms}ms[/] · "
        f"cost {'$%.4f' % s.total_cost_usd if s.total_cost_usd is not None else 'n/a'} · "
        f"in {s.duration_s}s"
    )
    console.print()

    table = Table(show_header=True, header_style="bold", expand=False)
    table.add_column("Case", style="cyan", no_wrap=True)
    table.add_column("Status", justify="center")
    table.add_column("Latency", justify="right")
    table.add_column("Checks", overflow="fold")

    for r in run.results:
        status_style = _STATUS_STYLE.get(r.status, "white")
        status_text = f"[{status_style}]{r.status.upper()}[/]"
        if r.attempts is not None and r.attempts > 1:
            status_text += f" [dim]({r.passed_attempts or 0}/{r.attempts})[/]"
        if r.status == "error":
            checks = (r.error or "unknown error")[:120]
        else:
            parts = []
            for a in r.assertion_results:
                mark = "[green]✔[/]" if a.passed else "[red]✘[/]"
                piece = f"{mark} {a.type}"
                if not a.passed and a.detail:
                    piece += f" [dim]({a.detail})[/]"
                parts.append(piece)
            checks = "\n".join(parts) if parts else "[dim]smoke (no asserts)[/]"
        table.add_row(r.case_id, status_text, f"{r.latency_ms}ms", checks)
    console.print(table)

    if s.pass_rate == 1.0:
        console.print("\n[green bold]All cases passed. You're sealed. 🦭[/]\n")
    else:
        console.print("\n[red bold]Some cases failed — check the details above.[/]\n")


def print_diff(diff: DiffReport) -> None:
    console.print()
    console.print(
        f"🦭 [bold]Diff[/bold]  baseline [dim]{diff.baseline_run_id}[/dim]  →  "
        f"candidate [dim]{diff.candidate_run_id}[/dim]"
    )
    console.print(
        f"   pass rate: {diff.baseline_pass_rate * 100:.0f}% → "
        f"{diff.candidate_pass_rate * 100:.0f}%"
    )
    console.print()

    table = Table(show_header=True, header_style="bold", expand=False)
    table.add_column("Case", style="cyan", no_wrap=True)
    table.add_column("Baseline", justify="center")
    table.add_column("Candidate", justify="center")
    table.add_column("Note", overflow="fold")

    for case_id, base, cand in diff.regressions:
        table.add_row(case_id, f"[green]{base.status}[/]", f"[red bold]{cand.status}[/]", "regression")
    for case_id, base, cand in diff.improvements:
        table.add_row(case_id, f"[red]{base.status}[/]", f"[green bold]{cand.status}[/]", "improvement")
    for case_id in diff.new_cases:
        table.add_row(case_id, "[dim]—[/]", "new", "")
    for case_id in diff.missing_cases:
        table.add_row(case_id, "removed", "[dim]—[/]", "")
    for case_id in diff.stable_pass:
        table.add_row(case_id, "[green]pass[/]", "[green]pass[/]", "")
    for case_id in diff.stable_fail:
        table.add_row(case_id, "[red]fail[/]", "[red]fail[/]", "")

    console.print(table)
    if diff.verdict == "pass":
        console.print("\n[green bold]Verdict: PASS — no regressions detected. 🦭[/]\n")
    else:
        console.print(f"\n[red bold]Verdict: REGRESSION — {len(diff.regressions)} case(s) got worse.[/]\n")


def print_matrix(runs: list) -> None:
    """Side-by-side comparison of the same suite across several providers."""
    if not runs:
        return
    labels = []
    for r in runs:
        cost = f"${r.summary.total_cost_usd:.4f}" if r.summary.total_cost_usd is not None else "n/a"
        labels.append(f"{r.meta.provider}:{r.meta.model}\n{r.summary.pass_rate * 100:.0f}% · {cost} · {r.summary.total_latency_ms}ms")

    case_ids: list[str] = []
    for r in runs:
        for res in r.results:
            if res.case_id not in case_ids:
                case_ids.append(res.case_id)

    table = Table(show_header=True, header_style="bold", expand=False)
    table.add_column("Case", style="cyan", no_wrap=True)
    for label in labels:
        table.add_column(label, justify="center")

    glyph = {"pass": "[green]✔[/]", "fail": "[red]✘[/]", "error": "[yellow]E[/]"}
    by_run = [{res.case_id: res.status for res in r.results} for r in runs]
    for cid in case_ids:
        row = [cid] + [glyph.get(by_run[i].get(cid, "?"), "?") for i in range(len(runs))]
        table.add_row(*row)

    table.add_section()
    best = max(
        runs,
        key=lambda r: (
            r.summary.pass_rate,
            -(r.summary.total_cost_usd or 0.0),
            -r.summary.total_latency_ms,
        ),
    )
    rates = []
    for i, r in enumerate(runs):
        marker = " 🏆" if r is best else ""
        rates.append(f"[bold]{r.summary.pass_rate * 100:.0f}%{marker}[/]")
    table.add_row("[bold]pass rate[/]", *rates)
    console.print(table)
    console.print(
        f"\n[bold green]🏆 Recommended:[/] [cyan]{best.meta.provider}:{best.meta.model}[/cyan] "
        f"({best.summary.pass_rate * 100:.0f}% pass, "
        f"{'$%.4f' % best.summary.total_cost_usd if best.summary.total_cost_usd is not None else 'cost n/a'})\n"
    )


def matrix_markdown(runs: list) -> str:
    """GitHub step-summary friendly model comparison table."""
    lines = ["## 🦭 PromptSeal model comparison", "", "| Model | Pass rate | Failed | Errors | Latency | Cost |", "|---|---|---|---|---|---|"]
    for r in runs:
        s = r.summary
        cost = f"${s.total_cost_usd:.4f}" if s.total_cost_usd is not None else "n/a"
        lines.append(
            f"| `{r.meta.provider}:{r.meta.model}` | **{s.pass_rate * 100:.0f}%** ({s.passed}/{s.total}) | {s.failed} | {s.errors} | {s.total_latency_ms}ms | {cost} |"
        )
    lines.append("")
    lines.append("<sub>Generated by PromptSeal 🦭</sub>")
    return "\n".join(lines)


def summary_markdown(run: Run, diff: DiffReport | None = None) -> str:
    """GitHub Actions step-summary friendly markdown."""
    s = run.summary
    lines = [
        "## 🦭 PromptSeal report",
        "",
        "| Metric | Value |",
        "|---|---|",
        f"| Provider | `{run.meta.provider}:{run.meta.model}` |",
        f"| Pass rate | **{s.pass_rate * 100:.0f}%** ({s.passed}/{s.total}) |",
        f"| Latency | {s.total_latency_ms} ms |",
        f"| Cost | {'$%.4f' % s.total_cost_usd if s.total_cost_usd is not None else 'n/a'} |",
        "",
    ]
    if diff is not None:
        verdict = "✅ PASS" if diff.verdict == "pass" else "❌ REGRESSION"
        lines += [
            f"**Verdict vs baseline:** {verdict} "
            f"({len(diff.regressions)} regressions, {len(diff.improvements)} improvements)",
            "",
            "| Case | Baseline | Candidate |",
            "|---|---|---|",
        ]
        for case_id, base, cand in diff.regressions:
            lines.append(f"| ❌ {case_id} | {base.status} | **{cand.status}** |")
        for case_id, base, cand in diff.improvements:
            lines.append(f"| ✅ {case_id} | {base.status} | **{cand.status}** |")
    lines.append("")
    lines.append("<sub>Generated by PromptSeal 🦭</sub>")
    return "\n".join(lines)
