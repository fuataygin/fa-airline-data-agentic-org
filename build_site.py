"""
build_site.py
---------------
Generates a static, GitHub Pages-ready showcase site from the REAL output
of your last `python main.py` run — the actual research brief, design
spec, GTM package, executive summary, and the actual ranked FleetGap
table FORGE's code produced live.

Why this exists instead of a "live" page that calls Gemini in the browser:
GitHub Pages only serves static files (no Python), and the Gemini API key
is a secret — putting it in JavaScript on an unauthenticated public page
means anyone who opens dev tools can copy it and spend your API credits.
This script sidesteps that entirely: it runs *locally*, where your real
.env key already lives, reads the genuine outputs your pipeline already
produced, and bakes them into plain HTML that has no key, no backend, and
nothing secret in it at all — safe to publish to a fully public URL.

Usage:
    python main.py          # produces real outputs/ + products/bers_engine.py
    python build_site.py    # turns those real outputs into docs/index.html

Then enable GitHub Pages pointing at the /docs folder (see README.md).
"""

from __future__ import annotations

import datetime as dt
import os
from pathlib import Path

import pandas as pd

try:
    import markdown as md_lib
except ImportError as exc:  # pragma: no cover
    raise SystemExit(
        "Missing dependency 'markdown'. Run: pip install -r requirements.txt"
    ) from exc

REPO_ROOT = Path(__file__).resolve().parent
OUTPUTS_DIR = REPO_ROOT / "outputs"
DOCS_DIR = REPO_ROOT / "docs"

AGENT_FILES = [
    ("01_research_brief.md", "ARIA", "Researcher", "Opportunity"),
    ("02_design_spec.md", "NOVA", "Designer", "Design Specification"),
    ("03_maker_note_and_raw_output.md", "FORGE", "Maker", "Build Note"),
    ("04_gtm_package.md", "ECHO", "Communicator", "Go-To-Market Package"),
    ("05_executive_summary.md", "ATLAS", "Manager", "Executive Summary"),
]

CSV_PATH = None  # resolved dynamically at build time — see _find_ranked_csv()

CF_WORKER_URL = os.environ.get("CF_WORKER_URL", "").strip()

# Tested in isolation (Node.js, including CSV-quoting and airline-name
# collision edge cases) before being embedded here — see cloudflare-worker/
# for the proxy this calls and its README for setup.
WIDGET_JS = r"""
function faadParseCsv(text) {
  const rows = [];
  let row = [];
  let field = "";
  let inQuotes = false;
  for (let i = 0; i < text.length; i++) {
    const c = text[i];
    if (inQuotes) {
      if (c === '"') {
        if (text[i + 1] === '"') {
          field += '"';
          i++;
        } else {
          inQuotes = false;
        }
      } else {
        field += c;
      }
    } else if (c === '"') {
      inQuotes = true;
    } else if (c === ",") {
      row.push(field);
      field = "";
    } else if (c === "\n" || c === "\r") {
      if (c === "\r" && text[i + 1] === "\n") i++;
      row.push(field);
      rows.push(row);
      row = [];
      field = "";
    } else {
      field += c;
    }
  }
  if (field.length > 0 || row.length > 0) {
    row.push(field);
    rows.push(row);
  }
  if (rows.length === 0) return [];
  const headers = rows[0].map((h) => h.trim().toLowerCase());
  return rows.slice(1).filter((r) => r.length === headers.length).map((r) => {
    const obj = {};
    headers.forEach((h, idx) => (obj[h] = r[idx]));
    return obj;
  });
}

async function faadFetchTab(workerUrl, tab) {
  const resp = await fetch(`${workerUrl}?tab=${encodeURIComponent(tab)}`);
  if (!resp.ok) throw new Error(`Worker returned ${resp.status} for tab '${tab}'`);
  const text = await resp.text();
  return faadParseCsv(text);
}

function faadMatchIncidents(incRows, airlineName, tPrev, t) {
  if (!airlineName) return { count: 0, boeing: 0 };
  const norm = airlineName.toLowerCase().trim();
  if (!norm) return { count: 0, boeing: 0 };
  let count = 0;
  let boeing = 0;
  incRows.forEach((r) => {
    const y = parseInt(r["year"], 10);
    if (y < tPrev || y > t) return;
    const rowName = (r["airline"] || "").toLowerCase().trim();
    if (!rowName) return;
    const isMatch = rowName === norm || rowName.includes(norm) || norm.includes(rowName);
    if (!isMatch) return;
    count += 1;
    if (r["is_boeing"] === "1" || r["is_boeing"] === "True" || r["is_boeing"] === "true") {
      boeing += 1;
    }
  });
  return { count, boeing };
}

function faadComputeRiskTable(finRows, incRows) {
  const byYear = {};
  finRows.forEach((r) => {
    const y = parseInt(r["year"], 10);
    if (!byYear[y]) byYear[y] = [];
    byYear[y].push(r);
  });
  const years = Object.keys(byYear).map(Number).sort((a, b) => a - b);
  if (years.length < 2) return { rows: [], t: null, tPrev: null };
  const t = years[years.length - 1];
  const tPrev = years[years.length - 2];

  const prevByCode = {};
  byYear[tPrev].forEach((r) => (prevByCode[r["iata_code"]] = r));

  const results = [];
  byYear[t].forEach((row) => {
    const code = row["iata_code"];
    const prev = prevByCode[code];
    if (!prev) return;

    const fleetT = parseFloat(row["fleet_size_est"]);
    const fleetPrev = parseFloat(prev["fleet_size_est"]);
    let fleetGrowthPct = null;
    if (fleetPrev > 0 && !isNaN(fleetT) && !isNaN(fleetPrev)) {
      fleetGrowthPct = ((fleetT - fleetPrev) / fleetPrev) * 100;
    }

    const marginT = parseFloat(row["operating_margin_pct"]);
    const marginPrev = parseFloat(prev["operating_margin_pct"]);
    let marginDeltaBps = 0;
    if (!isNaN(marginT) && !isNaN(marginPrev)) {
      const scale = Math.abs(marginT) <= 1 ? 10000 : 100;
      marginDeltaBps = (marginT - marginPrev) * scale;
    }

    const name = row["airline_name"] || code;
    const inc = faadMatchIncidents(incRows, name, tPrev, t);

    const fgs = fleetGrowthPct === null || fleetPrev <= 0 ? 0 : Math.max(0, 1 - fleetT / fleetPrev);
    const oss = inc.count > 0 ? inc.boeing / inc.count : 0;
    const score = Math.min(100, (fgs * 0.5 + oss * 0.5) * 100);

    results.push({
      code,
      name,
      fleetGrowthPct,
      marginDeltaBps,
      incidents: inc.count,
      boeingIncidents: inc.boeing,
      score,
    });
  });

  results.sort((a, b) => b.score - a.score);
  return { rows: results, t, tPrev };
}
""".strip()


def _find_ranked_csv() -> Path | None:
    """FORGE names its own product each run (fleetgap_risk_summary.csv,
    fleetshock_index.csv, etc.), so we can't hardcode a filename here.
    Pick the most recently modified CSV in outputs/ instead."""
    candidates = sorted(
        OUTPUTS_DIR.glob("*.csv"), key=lambda p: p.stat().st_mtime, reverse=True
    )
    return candidates[0] if candidates else None


def _require_outputs() -> None:
    missing = [name for name, *_ in AGENT_FILES if not (OUTPUTS_DIR / name).exists()]
    if missing:
        raise SystemExit(
            "Can't build the site — these real output files are missing:\n  "
            + "\n  ".join(missing)
            + "\n\nRun `python main.py` first so there's a real pipeline run "
            "to publish. This script only ever publishes genuine output, "
            "never placeholder text."
        )


def _maker_note_only(raw_markdown: str) -> str:
    """FORGE's file is a short note followed by a large fenced code block.
    The landing page shows the note + a link to the real code on GitHub,
    not the whole script inline."""
    return raw_markdown.split("```")[0].strip()


def _md_to_html(text: str) -> str:
    return md_lib.markdown(text, extensions=["fenced_code", "tables"])


def _ranked_table_html() -> tuple[str, dict]:
    csv_path = _find_ranked_csv()
    if csv_path is None:
        return (
            "<p><em>No ranked table found yet — run "
            "<code>python -m products.bers_engine</code> to generate one "
            "in outputs/.</em></p>",
            {},
        )
    df = pd.read_csv(csv_path)
    score_col = next((c for c in df.columns if "score" in c.lower()), None)
    name_col = next((c for c in df.columns if "name" in c.lower()), df.columns[0])
    stats = {
        "carrier_count": len(df),
        "source_file": csv_path.name,
        "avg_score": round(pd.to_numeric(df[score_col], errors="coerce").mean(), 1) if score_col else None,
        "top_carrier": df.iloc[0].get(name_col, "") if len(df) else "",
    }
    table_html = df.to_html(index=False, classes="ranked-table", border=0, escape=True)
    return table_html, stats


def build() -> Path:
    _require_outputs()
    DOCS_DIR.mkdir(exist_ok=True)

    generated_at = dt.datetime.now().strftime("%Y-%m-%d %H:%M")

    agent_sections = []
    for filename, codename, role, label in AGENT_FILES:
        raw = (OUTPUTS_DIR / filename).read_text(encoding="utf-8")
        if filename.startswith("03_"):
            raw = _maker_note_only(raw)
        html_body = _md_to_html(raw)
        agent_sections.append(
            f"""
            <section class="agent-card" id="{codename.lower()}">
              <div class="agent-header">
                <span class="agent-name">{codename}</span>
                <span class="agent-role">{role}</span>
              </div>
              <h3>{label}</h3>
              <div class="agent-body">{html_body}</div>
            </section>
            """
        )

    table_html, stats = _ranked_table_html()

    stat_line = ""
    if stats.get("avg_score") is not None:
        stat_line = (
            f'<p class="stat-line">{stats["carrier_count"]} carriers ranked · '
            f'average risk score <strong>{stats["avg_score"]}</strong> · '
            f'top-ranked: <strong>{stats["top_carrier"]}</strong></p>'
        )

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>FA Airline Data — Agentic Organisation</title>
<style>
  :root {{
    --bg: #0b0d12;
    --panel: #12151c;
    --border: #232833;
    --text: #e6e9ef;
    --muted: #8b93a7;
    --accent: #4fb0ff;
  }}
  * {{ box-sizing: border-box; }}
  body {{
    margin: 0;
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Helvetica, Arial, sans-serif;
    background: var(--bg);
    color: var(--text);
    line-height: 1.55;
  }}
  header {{
    padding: 48px 24px 32px;
    text-align: center;
    border-bottom: 1px solid var(--border);
  }}
  header h1 {{ margin: 0 0 8px; font-size: 1.9rem; }}
  header p {{ color: var(--muted); max-width: 640px; margin: 8px auto; }}
  .badge {{
    display: inline-block;
    margin-top: 14px;
    padding: 6px 14px;
    border-radius: 999px;
    background: rgba(79,176,255,0.12);
    border: 1px solid rgba(79,176,255,0.35);
    color: var(--accent);
    font-size: 0.82rem;
  }}
  .pipeline-strip {{
    display: flex;
    flex-wrap: wrap;
    justify-content: center;
    gap: 8px;
    margin: 24px auto 0;
    max-width: 900px;
    font-size: 0.85rem;
    color: var(--muted);
  }}
  .pipeline-strip span.node {{
    padding: 6px 12px;
    border: 1px solid var(--border);
    border-radius: 8px;
    background: var(--panel);
  }}
  main {{ max-width: 900px; margin: 0 auto; padding: 32px 24px 80px; }}
  .agent-card {{
    background: var(--panel);
    border: 1px solid var(--border);
    border-radius: 12px;
    padding: 24px 28px;
    margin-bottom: 20px;
  }}
  .agent-header {{ display: flex; align-items: baseline; gap: 10px; margin-bottom: 4px; }}
  .agent-name {{ font-weight: 700; color: var(--accent); letter-spacing: 0.02em; }}
  .agent-role {{ color: var(--muted); font-size: 0.85rem; }}
  .agent-card h3 {{ margin: 6px 0 14px; font-size: 1.1rem; }}
  .agent-body h1, .agent-body h2 {{ font-size: 1.05rem; margin: 18px 0 6px; }}
  .agent-body p {{ color: #cfd4e0; }}
  .agent-body code {{ background: #1a1f29; padding: 1px 6px; border-radius: 4px; }}
  .table-section {{ margin-top: 40px; }}
  .stat-line {{ color: var(--muted); font-size: 0.9rem; margin-bottom: 14px; }}
  table.ranked-table {{
    width: 100%;
    border-collapse: collapse;
    font-size: 0.85rem;
    background: var(--panel);
    border: 1px solid var(--border);
    border-radius: 8px;
    overflow: hidden;
  }}
  table.ranked-table th, table.ranked-table td {{
    padding: 8px 12px;
    text-align: left;
    border-bottom: 1px solid var(--border);
  }}
  table.ranked-table th {{ color: var(--muted); font-weight: 600; }}
  footer {{
    text-align: center;
    color: var(--muted);
    font-size: 0.8rem;
    padding: 24px;
    border-top: 1px solid var(--border);
  }}
  footer a {{ color: var(--accent); text-decoration: none; }}
  a {{ color: var(--accent); }}
</style>
</head>
<body>
<header>
  <h1>FA Airline Data — Agentic Organisation</h1>
  <p>Five Gemini-powered agents — ARIA, NOVA, FORGE, ECHO, ATLAS — researched, designed,
     built, and launched a real aviation-analytics product, live, against a public dataset.
     This page shows their <strong>actual, unedited output</strong> from a real run.</p>
  <span class="badge">Real pipeline run · generated {generated_at}</span>
  <div class="pipeline-strip">
    <span class="node">ARIA (Researcher)</span>→
    <span class="node">NOVA (Designer)</span>→
    <span class="node">FORGE (Maker)</span>→
    <span class="node">ECHO (Communicator)</span>→
    <span class="node">ATLAS (Manager)</span>
  </div>
</header>
<main>
  {''.join(agent_sections)}

  <section class="table-section">
    <h2>FORGE's agent-built product — live ranked output</h2>
    {stat_line}
    <p style="color:var(--muted); font-size:0.85rem;">
      This table is FORGE's generated product actually executed against the
      live FA Airline Data Google Sheet — not a mockup.
    </p>
    {table_html}
  </section>

  <section class="table-section" id="live-widget-section">
    <h2>Live in your browser</h2>
    <p style="color:var(--muted); font-size:0.85rem;">
      Unlike the table above (a snapshot from one real pipeline run), this
      section re-fetches the public FA Airline Data sheet directly in
      <strong>your</strong> browser, right now, and recomputes a simplified
      risk score client-side — a second, independent live connection,
      separate from the agents' own Gemini-powered run.
    </p>
    <div id="live-widget-status" style="color:var(--muted); font-size:0.85rem; margin:10px 0;">
      {"Loading live data…" if CF_WORKER_URL else "Live widget not configured — see cloudflare-worker/README.md to enable it."}
    </div>
    <div id="live-widget-table"></div>
    <button id="live-widget-refresh" style="display:none; margin-top:12px; background:var(--panel); color:var(--accent); border:1px solid var(--border); border-radius:8px; padding:8px 16px; cursor:pointer;">
      Refresh live data
    </button>
  </section>
</main>
<footer>
  Full source, agent prompts, and the live data connection:
  <a href="https://github.com/fuataygin/fa-airline-data-agentic-org">github.com/fuataygin/fa-airline-data-agentic-org</a>
</footer>
<script>
const FAAD_WORKER_URL = {repr(CF_WORKER_URL)};

{WIDGET_JS}

async function faadRunLiveWidget() {{
  const statusEl = document.getElementById("live-widget-status");
  const tableEl = document.getElementById("live-widget-table");
  const refreshBtn = document.getElementById("live-widget-refresh");
  if (!FAAD_WORKER_URL) return;

  statusEl.textContent = "Fetching live data from the FA Airline Data sheet…";
  tableEl.innerHTML = "";
  refreshBtn.style.display = "none";

  try {{
    const [finRows, incRows] = await Promise.all([
      faadFetchTab(FAAD_WORKER_URL, "airline_financials"),
      faadFetchTab(FAAD_WORKER_URL, "aviation_incidents"),
    ]);
    const {{ rows, t, tPrev }} = faadComputeRiskTable(finRows, incRows);
    if (!rows.length) {{
      statusEl.textContent = "Live fetch succeeded but no comparable rows were found.";
      return;
    }}
    const top = rows.slice(0, 10);
    const now = new Date().toLocaleTimeString();
    statusEl.textContent = `Live as of ${{now}} — comparing ${{t}} vs ${{tPrev}}, top 10 of ${{rows.length}} carriers by simplified score.`;

    let html = '<table class="ranked-table"><tr><th>Code</th><th>Airline</th><th>Fleet growth</th><th>Margin delta</th><th>Incidents</th><th>Boeing-linked</th><th>Score</th></tr>';
    top.forEach((r) => {{
      const growth = r.fleetGrowthPct === null ? "N/A" : `${{r.fleetGrowthPct.toFixed(1)}}%`;
      html += `<tr><td>${{r.code}}</td><td>${{r.name}}</td><td>${{growth}}</td><td>${{Math.round(r.marginDeltaBps)}} bps</td><td>${{r.incidents}}</td><td>${{r.boeingIncidents}}</td><td>${{r.score.toFixed(1)}}</td></tr>`;
    }});
    html += "</table>";
    tableEl.innerHTML = html;
    refreshBtn.style.display = "inline-block";
  }} catch (err) {{
    statusEl.textContent = "Live fetch failed: " + err.message + ". The Cloudflare Worker may be unreachable or misconfigured.";
  }}
}}

if (FAAD_WORKER_URL) {{
  faadRunLiveWidget();
  document.getElementById("live-widget-refresh").addEventListener("click", faadRunLiveWidget);
}}
</script>
</body>
</html>"""

    out_path = DOCS_DIR / "index.html"
    out_path.write_text(html, encoding="utf-8")
    return out_path


if __name__ == "__main__":
    path = build()
    print(f"Built static showcase site -> {path}")
    print("Next: git add docs/ && git commit -m 'Publish site' && git push")
    print("Then enable GitHub Pages (Settings -> Pages -> Branch: main, Folder: /docs)")
