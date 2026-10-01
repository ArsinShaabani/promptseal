"""driftwatch — local drift dashboard over your saved run history.

A static, self-contained HTML page (inline SVG, no JS, no CDN): pass-rate trends
per provider:model across every run in `.promptseal/runs/`, plus cost & latency.
"""

from __future__ import annotations

import html
import math
from typing import Any

from promptseal.models import Run

_CSS = """
  :root { color-scheme: dark; }
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body { font-family: -apple-system, 'Segoe UI', Roboto, sans-serif;
         background: #0b1020; color: #e6e9f2; padding: 32px; }
  .wrap { max-width: 980px; margin: 0 auto; }
  h1 { font-size: 26px; } .sub { color: #8b93a7; margin-top: 6px; font-size: 14px; }
  .cards { display: flex; gap: 16px; margin: 24px 0; flex-wrap: wrap; }
  .card { background: #121a30; border: 1px solid #1f2a4a; border-radius: 14px;
          padding: 16px 20px; min-width: 150px; flex: 1; }
  .card .v { font-size: 24px; font-weight: 700; margin-top: 6px; }
  .card .k { color: #8b93a7; font-size: 12px; text-transform: uppercase; letter-spacing: 1px; }
  .prov { background: #121a30; border: 1px solid #1f2a4a; border-radius: 14px;
          padding: 20px 22px; margin: 18px 0; }
  .prov h2 { font-size: 16px; margin-bottom: 4px; }
  .stat { color: #8b93a7; font-size: 13px; margin-bottom: 10px; }
  svg.spark { width: 100%; height: 150px; display: block; }
  svg.spark .line { fill: none; stroke: #4ade80; stroke-width: 2.5; }
  svg.spark .dot { fill: #4ade80; }
  svg.spark .axis { stroke: #26304f; stroke-width: 1; }
  svg.spark .dashed { stroke-dasharray: 4 4; }
  svg.spark text { fill: #8b93a7; font-size: 11px; }
  table { width: 100%; border-collapse: collapse; margin-top: 12px; font-size: 13px; }
  th { text-align: left; color: #8b93a7; font-weight: 600; padding: 8px 10px;
       border-bottom: 1px solid #1f2a4a; font-size: 11px; text-transform: uppercase; }
  td { padding: 8px 10px; border-bottom: 1px solid #17203c; }
  tr:hover td { background: #101a33; }
  footer { margin-top: 36px; color: #5b6478; font-size: 12.5px; text-align: center; }
"""


def _sparkline(values: list[float], width: int = 760, height: int = 150) -> str:
    """Minimal inline SVG trend line (pass-rate 0..1 over consecutive runs)."""
    pad = 34
    n = len(values)
    pts: list[tuple[float, float]] = []
    for i, v in enumerate(values):
        x = pad + i * (width - 2 * pad) / (n - 1) if n > 1 else width / 2
        y = height - pad - max(0.0, min(1.0, v)) * (height - 2 * pad)
        pts.append((round(x, 1), round(y, 1)))
    dots = "".join(f'<circle cx="{x}" cy="{y}" r="3.4" class="dot"/>' for x, y in pts)
    line = ""
    if n > 1:
        poly = " ".join(f"{x},{y}" for x, y in pts)
        line = f'<polyline points="{poly}" class="line"/>'
    grid = (
        f'<line x1="{pad}" y1="{height - pad}" x2="{width - pad}" '
        f'y2="{height - pad}" class="axis"/>'
        f'<line x1="{pad}" y1="{height / 2:.0f}" x2="{width - pad}" '
        f'y2="{height / 2:.0f}" class="axis dashed"/>'
        f'<text x="4" y="{height / 2 + 4:.0f}">50%</text>'
        f'<text x="4" y="{pad + 4}">100%</text>'
    )
    return f'<svg viewBox="0 0 {width} {height}" class="spark" preserveAspectRatio="none">{grid}{line}{dots}</svg>'


def _prov_section(key: str, runs: list[Run]) -> str:
    rates = [r.summary.pass_rate for r in runs]
    costs = [r.summary.total_cost_usd for r in runs if r.summary.total_cost_usd is not None]
    avg_lat = sum(r.summary.total_latency_ms for r in runs) / len(runs)
    cost_str = f"${sum(costs):.4f}" if costs else "n/a"
    rows = "".join(
        f"<tr><td>{html.escape(r.meta.created_at[:19].replace('T', ' '))}</td>"
        f"<td>{html.escape(r.meta.suite)}</td>"
        f"<td>{r.summary.pass_rate * 100:.0f}%</td>"
        f"<td>{r.summary.total_latency_ms}ms</td>"
        f"<td>{'$%.4f' % r.summary.total_cost_usd if r.summary.total_cost_usd is not None else 'n/a'}</td>"
        f"<td>{html.escape(r.meta.run_id)}</td></tr>"
        for r in runs
    )
    return (
        f'<div class="prov"><h2>🦭 {html.escape(key)}</h2>'
        f'<div class="stat">last {rates[-1] * 100:.0f}% · {len(runs)} run(s) · '
        f"avg latency {avg_lat:.0f}ms · total cost {cost_str}</div>"
        f"{_sparkline(rates)}"
        "<table><tr><th>Created</th><th>Suite</th><th>Pass</th><th>Latency</th>"
        f"<th>Cost</th><th>Run</th></tr>{rows}</table></div>"
    )


def _percentile(values: list[float], pct: float) -> float:
    """Nearest-rank percentile (pct in 0..1)."""
    if not values:
        return 0.0
    ordered = sorted(values)
    idx = min(len(ordered) - 1, max(0, math.ceil(pct * len(ordered)) - 1))
    return ordered[idx]


def per_case_stats(runs: list[Run]) -> list[dict[str, Any]]:
    """Per-case cost/latency percentiles across all runs (cost observability).

    Returns one row per case_id with sample count, cost p50/p95/max, latency
    p50/p95, and the cheapest provider observed for that case.
    """
    by_case: dict[str, list[tuple[float, float, str]]] = {}
    for run in runs:
        for res in run.results:
            if res.cost_usd is None and res.latency_ms == 0:
                continue
            cost = res.cost_usd if res.cost_usd is not None else 0.0
            by_case.setdefault(res.case_id, []).append(
                (cost, float(res.latency_ms), f"{run.meta.provider}:{run.meta.model}")
            )
    stats: list[dict[str, Any]] = []
    for case_id in sorted(by_case):
        entries = by_case[case_id]
        costs = [e[0] for e in entries]
        lats = [e[1] for e in entries]
        cheapest = min(entries, key=lambda e: e[0])
        stats.append(
            {
                "case_id": case_id,
                "samples": len(entries),
                "cost_p50": _percentile(costs, 0.50),
                "cost_p95": _percentile(costs, 0.95),
                "cost_max": max(costs),
                "latency_p50": _percentile(lats, 0.50),
                "latency_p95": _percentile(lats, 0.95),
                "cheapest_provider": cheapest[2],
                "cheapest_cost": cheapest[0],
            }
        )
    return stats


def _stats_section(runs: list[Run]) -> str:
    stats = per_case_stats(runs)
    if not stats:
        return ""
    rows = "".join(
        f"<tr><td>{html.escape(s['case_id'])}</td><td>{s['samples']}</td>"
        f"<td>${s['cost_p50']:.4f}</td><td>${s['cost_p95']:.4f}</td>"
        f"<td>${s['cost_max']:.4f}</td><td>{s['latency_p50']:.0f}ms</td>"
        f"<td>{s['latency_p95']:.0f}ms</td><td>{html.escape(s['cheapest_provider'])}</td></tr>"
        for s in stats
    )
    return (
        '<div class="prov"><h2>💰 Cost & latency by case — percentiles across providers</h2>'
        "<table><tr><th>Case</th><th>Samples</th><th>p50 cost</th><th>p95 cost</th>"
        "<th>max cost</th><th>p50 latency</th><th>p95 latency</th><th>cheapest</th></tr>"
        f"{rows}</table></div>"
    )


def render_html(runs: list[Run], generated_at: str = "") -> str:
    groups: dict[str, list[Run]] = {}
    for r in sorted(runs, key=lambda r: r.meta.created_at):
        groups.setdefault(f"{r.meta.provider}:{r.meta.model}", []).append(r)
    sections = "".join(_prov_section(k, rs) for k, rs in groups.items())
    newest = max(r.meta.created_at for r in runs)[:19].replace("T", " ")
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>PromptSeal driftwatch</title>
<style>{_CSS}</style>
</head>
<body>
<div class="wrap">
  <h1>🦭 PromptSeal — driftwatch</h1>
  <div class="sub">{len(runs)} runs · {len(groups)} provider(s) · newest {html.escape(newest)} · {html.escape(generated_at)}</div>
  <div class="cards">
    <div class="card"><div class="k">runs</div><div class="v">{len(runs)}</div></div>
    <div class="card"><div class="k">providers</div><div class="v">{len(groups)}</div></div>
    <div class="card"><div class="k">suites</div><div class="v">{len({r.meta.suite for r in runs})}</div></div>
  </div>
  {sections}
  {_stats_section(runs)}
  <footer>Generated by PromptSeal 🦭 — local-first drift watching, no server involved.</footer>
</div>
</body>
</html>
"""