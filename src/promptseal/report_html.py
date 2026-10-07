"""Self-contained HTML report (no external assets, works offline)."""

from __future__ import annotations

from jinja2 import Template

from promptseal.diff import DiffReport
from promptseal.models import Run

_CSS = """
  :root { color-scheme: dark; }
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body { font-family: -apple-system, 'Segoe UI', Roboto, sans-serif;
         background: #0b1020; color: #e6e9f2; padding: 32px; }
  .wrap { max-width: 960px; margin: 0 auto; }
  h1 { font-size: 26px; display: flex; align-items: center; gap: 10px; }
  .sub { color: #8b93a7; margin-top: 6px; font-size: 14px; }
  .cards { display: flex; gap: 16px; margin: 28px 0; flex-wrap: wrap; }
  .card { background: #121a30; border: 1px solid #1f2a4a; border-radius: 14px;
          padding: 18px 22px; min-width: 150px; flex: 1; }
  .card .v { font-size: 26px; font-weight: 700; margin-top: 6px; }
  .card .k { color: #8b93a7; font-size: 12px; text-transform: uppercase; letter-spacing: 1px; }
  .donut { width: 92px; height: 92px; border-radius: 50%;
           background: conic-gradient({{ donut_color }} {{ donut_deg }}deg, #26304f 0deg);
           display: flex; align-items: center; justify-content: center; }
  .donut .in { width: 68px; height: 68px; border-radius: 50%; background: #121a30;
               display: flex; align-items: center; justify-content: center;
               font-weight: 700; font-size: 15px; }
  table { width: 100%; border-collapse: collapse; margin-top: 14px; font-size: 14px; }
  th { text-align: left; color: #8b93a7; font-weight: 600; padding: 10px;
       border-bottom: 1px solid #1f2a4a; font-size: 12px; text-transform: uppercase; }
  td { padding: 10px; border-bottom: 1px solid #17203c; vertical-align: top; }
  tr:hover td { background: #101a33; }
  .chip { display: inline-block; padding: 2px 10px; border-radius: 999px;
          font-size: 12px; font-weight: 700; }
  .pass { background: #10361f; color: #4ade80; }
  .fail { background: #3b1220; color: #f87171; }
  .error { background: #3a2b10; color: #fbbf24; }
  .reg { background: #3b1220; color: #f87171; }
  .imp { background: #10361f; color: #4ade80; }
  details { margin-top: 6px; }
  summary { cursor: pointer; color: #7aa2f7; font-size: 13px; }
  pre { background: #0d1428; border: 1px solid #1f2a4a; border-radius: 10px;
        padding: 12px; margin-top: 8px; white-space: pre-wrap; font-size: 12.5px;
        color: #cbd5f5; }
  .muted { color: #8b93a7; }
  .verdict { margin-top: 26px; padding: 16px 20px; border-radius: 14px; font-weight: 700; }
  .v-pass { background: #10361f; color: #4ade80; border: 1px solid #1d5c35; }
  .v-reg { background: #3b1220; color: #f87171; border: 1px solid #7f1d3a; }
  footer { margin-top: 40px; color: #5b6478; font-size: 12.5px; text-align: center; }
"""

_TEMPLATE = Template(
    autoescape=True,
    source="""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>PromptSeal report — {{ run.meta.run_id }}</title>
<style>{{ css }}</style>
</head>
<body>
<div class="wrap">
  <h1>🦭 PromptSeal</h1>
  <div class="sub">
    run <b>{{ run.meta.run_id }}</b> ·
    <span class="muted">{{ run.meta.provider }}:{{ run.meta.model }}</span> ·
    suite <b>{{ run.meta.suite }}</b> ·
    <span class="muted">{{ run.meta.created_at }}</span>
  </div>

  <div class="cards">
    <div class="card" style="display:flex; gap:18px; align-items:center;">
      <div class="donut"><div class="in">{{ "%.0f"|format(run.summary.pass_rate * 100) }}%</div></div>
      <div><div class="k">pass rate</div>
        <div class="v">{{ run.summary.passed }}/{{ run.summary.total }}</div></div>
    </div>
    <div class="card"><div class="k">failed</div>
      <div class="v" style="color:#f87171;">{{ run.summary.failed }}</div></div>
    <div class="card"><div class="k">errors</div>
      <div class="v" style="color:#fbbf24;">{{ run.summary.errors }}</div></div>
    <div class="card"><div class="k">latency</div>
      <div class="v">{{ run.summary.total_latency_ms }}<span style="font-size:14px">ms</span></div></div>
    <div class="card"><div class="k">cost</div>
      <div class="v">{% if run.summary.total_cost_usd is not none %}${{ "%.4f"|format(run.summary.total_cost_usd) }}{% else %}<span style="font-size:16px">n/a</span>{% endif %}</div></div>
  </div>
"""
)


_BODY_REST = """
  {% if diff %}
  <div class="verdict {{ 'v-pass' if diff.verdict == 'pass' else 'v-reg' }}">
    {% if diff.verdict == 'pass' %}✅ PASS vs baseline — no regressions.
    {% else %}❌ REGRESSION vs baseline — {{ diff.regressions|length }} case(s) got worse.{% endif %}
    <span style="font-weight:400; margin-inline-start:8px;">
      pass rate {{ "%.0f"|format(diff.baseline_pass_rate * 100) }}% →
      {{ "%.0f"|format(diff.candidate_pass_rate * 100) }}%</span>
  </div>
  {% endif %}

  <table>
    <tr><th>Case</th><th>Status</th><th>Latency</th><th>Checks</th></tr>
    {% for r in run.results %}
    <tr>
      <td><b>{{ r.case_id }}</b></td>
      <td><span class="chip {{ r.status }}">{{ r.status|upper }}</span></td>
      <td class="muted">{{ r.latency_ms }}ms</td>
      <td>
        {% if r.status == 'error' %}<span class="muted">{{ r.error }}</span>
        {% elif r.assertion_results %}
          {% for a in r.assertion_results %}
            <span class="chip {{ 'pass' if a.passed else 'fail' }}">{{ a.type }}</span>
            {% if not a.passed and a.detail %}<div class="muted" style="font-size:12px">{{ a.detail }}</div>{% endif %}
          {% endfor %}
        {% else %}<span class="muted">smoke (no asserts)</span>{% endif %}
        {% if r.output %}
        <details><summary>output</summary><pre>{{ r.output[:2000] }}</pre></details>
        {% endif %}
      </td>
    </tr>
    {% endfor %}
  </table>

  <footer>Generated by PromptSeal 🦭 — regression testing for prompts, agents, and models.</footer>
</div>
</body>
</html>
"""


def render_html(run: Run, diff: DiffReport | None = None) -> str:
    donut_deg = int(run.summary.pass_rate * 360)
    donut_color = (
        "#4ade80" if run.summary.pass_rate >= 0.999 else (
            "#fbbf24" if run.summary.pass_rate >= 0.5 else "#f87171"
        )
    )
    html = _TEMPLATE.render(run=run, diff=diff, css=_CSS, donut_deg=donut_deg, donut_color=donut_color)
    return html + _BODY_REST


_MATRIX_TEMPLATE = Template(
    autoescape=True,
    source="""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>PromptSeal matrix — {{ runs_count }} models</title>
<style>{{ css }}</style>
</head>
<body>
<div class="wrap">
  <h1>🦭 PromptSeal — model comparison</h1>
  <div class="sub">{{ runs_count }} models scored on the same suite · {{ generated_at }}</div>

  <div class="cards">
    {% for r in runs %}
    <div class="card">
      <div class="k">{{ r.meta.provider }}:{{ r.meta.model }}</div>
      <div class="v" style="color:{{ '#4ade80' if r.summary.pass_rate >= 0.999 else ('#fbbf24' if r.summary.pass_rate >= 0.5 else '#f87171') }};">{{ "%.0f"|format(r.summary.pass_rate * 100) }}%</div>
      <div class="muted" style="font-size:12px">
        {{ r.summary.passed }}/{{ r.summary.total }} passed ·
        {{ r.summary.total_latency_ms }}ms ·
        {% if r.summary.total_cost_usd is not none %}${{ "%.4f"|format(r.summary.total_cost_usd) }}{% else %}cost n/a{% endif %}
      </div>
    </div>
    {% endfor %}
  </div>

  <div class="verdict v-pass">🏆 Recommended:
    <span style="color:#e6e9f2">{{ best.meta.provider }}:{{ best.meta.model }}</span>
    <span style="font-weight:400">— highest pass rate, then cheapest & fastest</span>
  </div>

  <table>
    <tr><th>Case</th>{% for r in runs %}<th>{{ r.meta.provider }}:{{ r.meta.model }}</th>{% endfor %}</tr>
    {% for cid in case_ids %}
    <tr>
      <td><b>{{ cid }}</b></td>
      {% for st in rows[cid] %}
        <td>{% if st == 'pass' %}<span class="chip pass">✔</span>
            {% elif st == 'fail' %}<span class="chip fail">✘</span>
            {% elif st == 'error' %}<span class="chip error">E</span>
            {% else %}<span class="muted">—</span>{% endif %}</td>
      {% endfor %}
    </tr>
    {% endfor %}
  </table>

  <footer>Generated by PromptSeal 🦭 — seal it before you ship it.</footer>
</div>
</body>
</html>
"""
)


def render_matrix_html(runs: list, generated_at: str = "") -> str:
    case_ids: list[str] = []
    for r in runs:
        for res in r.results:
            if res.case_id not in case_ids:
                case_ids.append(res.case_id)
    statuses = [{res.case_id: res.status for res in r.results} for r in runs]
    rows = {cid: [statuses[i].get(cid, "?") for i in range(len(runs))] for cid in case_ids}
    best = max(
        runs,
        key=lambda r: (
            r.summary.pass_rate,
            -(r.summary.total_cost_usd or 0.0),
            -r.summary.total_latency_ms,
        ),
    )
    return _MATRIX_TEMPLATE.render(
        runs=runs,
        runs_count=len(runs),
        case_ids=case_ids,
        rows=rows,
        best=best,
        css=_CSS,
        generated_at=generated_at,
    )


