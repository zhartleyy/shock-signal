#!/usr/bin/env python3
"""
Catalyst daily brief generator.

Save in your repo as: scripts/generate_brief.py

Calls the Claude API (with web search) to research today's market-moving
events, gets back structured JSON, validates it, and renders index.html
from a fixed template. If anything fails, the script exits non-zero and
nothing is written — the site keeps the previous day's brief.

Requires: pip install anthropic
Env var:  ANTHROPIC_API_KEY
"""

import html
import json
import os
import re
import sys
from datetime import datetime
from zoneinfo import ZoneInfo

import anthropic

MODEL = "claude-sonnet-5"
OUTPUT_FILE = "index.html"

# ---------------------------------------------------------------------------
# 1. Research prompt
# ---------------------------------------------------------------------------

PROMPT = """You are the research engine behind "Catalyst", a daily supply-and-demand
market intelligence brief. Today's date: {date}.

Use web search to scan the last 24-48 hours of global news for events creating
supply or demand shocks: geopolitical, financial/monetary, regulatory/trade,
climatic, and technological. Trace each event through its causal chain to
specific publicly traded companies.

Then output ONLY a JSON object (no prose before or after) with this exact shape:

{{
  "headline_stat": {{"value": "$86", "label": "Brent / bbl"}},
  "themes": [
    {{"icon": "🕊️", "title": "Theme Name", "desc": "1-2 sentence summary with concrete figures."}}
  ],
  "doubles": [
    {{"ticker": "DAL", "company": "Delta Air Lines",
      "desc": "2-3 sentences on why this stock benefits from 2+ separate signals.",
      "chips": ["Catalyst One", "Catalyst Two"]}}
  ],
  "signals": [
    {{"theme": "Theme Name",
      "sector": "Energy / Geopolitical",
      "title": "Headline-style signal title",
      "mech": "↑ Supply Normalization",
      "summary": "3-4 sentence explanation of the event, the causal chain, and concrete numbers.",
      "winners": [{{"ticker": "DAL", "company": "Delta Air Lines", "thesis": "One-line thesis", "cv": 9}}],
      "losers":  [{{"ticker": "OXY", "company": "Occidental Petroleum", "thesis": "One-line thesis", "cv": 8}}]}}
  ]
}}

Rules:
- 8 to 12 signals, 4 to 6 themes, 3 to 6 double beneficiaries.
- Every signal's "theme" must EXACTLY match the "title" of one theme.
- "cv" is a conviction score 1-10: 8-10 = direct causal link, large revenue
  exposure, likely underpriced; 5-7 = clear mechanism but partially priced in
  or second-order; 1-4 = speculative or longer-horizon.
- Each winners/losers list has 2-4 rows. Theses are one line, no ticker repeats
  within a table.
- "mech" is a short mechanism label, optionally prefixed ↑ or ↓
  (e.g. "↑ Demand Surge", "↓ Supply Deficit", "Rate Constraint", "Mixed Signal").
- "headline_stat" is one market number that anchors the day (an index level,
  commodity price, yield, etc.).
- Double beneficiaries must appear in at least 2 different signals' tables.
- Use real, current facts from your searches. Include concrete figures.
- Do NOT include citation tags, <cite> markup, or source references inside any
  JSON string — plain prose only.
- Output raw JSON only. No markdown fences, no commentary."""

# ---------------------------------------------------------------------------
# 2. Fixed page template (CSS/head identical to the existing site)
# ---------------------------------------------------------------------------

PAGE_HEAD = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Catalyst — Daily Intelligence Brief</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800;900&family=JetBrains+Mono:wght@400;500;600;700&display=swap" rel="stylesheet">
<style>
  :root{
    --bg:#09090b;
    --surface:#131316;
    --surface-2:#1a1a1f;
    --border:#27272a;
    --border-2:#3f3f46;
    --text:#fafafa;
    --text-2:#a1a1aa;
    --muted:#71717a;
    --accent:#f59e0b;
    --accent-2:#fbbf24;
    --green:#22c55e;
    --orange:#f97316;
    --blue:#3b82f6;
    --red:#ef4444;
    --radius:16px;
  }
  *{margin:0;padding:0;box-sizing:border-box}
  html{scroll-behavior:smooth}
  body{
    font-family:'Inter',system-ui,-apple-system,sans-serif;
    background:var(--bg);
    color:var(--text);
    line-height:1.6;
    -webkit-font-smoothing:antialiased;
    overflow-x:hidden;
  }
  .mono{font-family:'JetBrains Mono',monospace}
  a{color:inherit;text-decoration:none}
  .wrap{max-width:1180px;margin:0 auto;padding:0 24px}
  nav{
    position:sticky;top:0;z-index:100;
    background:rgba(9,9,11,.72);
    backdrop-filter:blur(16px) saturate(160%);
    -webkit-backdrop-filter:blur(16px) saturate(160%);
    border-bottom:1px solid var(--border);
  }
  .nav-inner{display:flex;align-items:center;justify-content:space-between;height:64px}
  .brand{display:flex;align-items:center;gap:10px;font-weight:800;font-size:1.15rem;letter-spacing:-.01em}
  .brand .logo{
    color:var(--accent);font-size:1.35rem;
    filter:drop-shadow(0 0 8px rgba(245,158,11,.55));
  }
  .brand b{color:var(--accent)}
  .nav-meta{font-size:.8rem;color:var(--muted);font-weight:500}
  .nav-meta .dot{color:var(--accent);margin:0 8px}
  header{position:relative;padding:90px 0 70px;text-align:center;overflow:hidden}
  header::before{
    content:"";position:absolute;top:-180px;left:50%;transform:translateX(-50%);
    width:760px;height:560px;
    background:radial-gradient(ellipse at center,rgba(245,158,11,.20),rgba(245,158,11,.06) 42%,transparent 70%);
    pointer-events:none;z-index:0;
  }
  header .wrap{position:relative;z-index:1}
  .eyebrow{
    display:inline-block;font-family:'JetBrains Mono',monospace;
    font-size:.72rem;letter-spacing:.22em;text-transform:uppercase;
    color:var(--accent);border:1px solid rgba(245,158,11,.35);
    background:rgba(245,158,11,.07);padding:7px 16px;border-radius:999px;margin-bottom:26px;
  }
  h1{font-size:clamp(2.3rem,6vw,4rem);font-weight:900;letter-spacing:-.03em;line-height:1.05}
  h1 .accent{
    background:linear-gradient(120deg,var(--accent),var(--accent-2));
    -webkit-background-clip:text;background-clip:text;color:transparent;
  }
  .lede{max-width:620px;margin:22px auto 0;color:var(--text-2);font-size:1.08rem}
  .stats{display:flex;justify-content:center;gap:14px;flex-wrap:wrap;margin-top:38px}
  .stat{
    background:var(--surface);border:1px solid var(--border);border-radius:14px;
    padding:16px 26px;min-width:128px;
  }
  .stat .num{font-family:'JetBrains Mono',monospace;font-size:1.7rem;font-weight:700;color:var(--accent)}
  .stat .lbl{font-size:.72rem;letter-spacing:.08em;text-transform:uppercase;color:var(--muted);margin-top:2px}
  .disclaimer{
    display:flex;gap:12px;align-items:flex-start;
    max-width:900px;margin:8px auto 0;
    background:var(--surface);border:1px solid var(--border);border-left:3px solid var(--accent);
    border-radius:12px;padding:14px 18px;color:var(--text-2);font-size:.84rem;
  }
  .disclaimer .i{color:var(--accent);font-style:normal;font-weight:700}
  section{padding:54px 0}
  .sec-head{display:flex;align-items:baseline;gap:14px;margin-bottom:28px;flex-wrap:wrap}
  .sec-head h2{font-size:1.7rem;font-weight:800;letter-spacing:-.02em}
  .sec-tag{
    font-family:'JetBrains Mono',monospace;font-size:.72rem;letter-spacing:.12em;text-transform:uppercase;
    color:var(--accent);background:rgba(245,158,11,.08);border:1px solid rgba(245,158,11,.28);
    padding:4px 12px;border-radius:999px;
  }
  .legend{display:grid;grid-template-columns:repeat(3,1fr);gap:16px}
  .leg{background:var(--surface);border:1px solid var(--border);border-radius:var(--radius);padding:22px}
  .leg .badge{
    display:inline-flex;align-items:center;justify-content:center;
    font-family:'JetBrains Mono',monospace;font-weight:700;font-size:.95rem;
    padding:6px 12px;border-radius:8px;margin-bottom:12px;
  }
  .b-green{background:rgba(34,197,94,.13);color:var(--green);border:1px solid rgba(34,197,94,.4)}
  .b-orange{background:rgba(249,115,22,.13);color:var(--orange);border:1px solid rgba(249,115,22,.4)}
  .b-blue{background:rgba(59,130,246,.13);color:var(--blue);border:1px solid rgba(59,130,246,.4)}
  .leg h3{font-size:1rem;margin-bottom:6px}
  .leg p{font-size:.86rem;color:var(--text-2)}
  .macro{display:grid;grid-template-columns:repeat(auto-fit,minmax(210px,1fr));gap:16px}
  .force{
    background:linear-gradient(180deg,var(--surface),var(--surface-2));
    border:1px solid var(--border);border-radius:var(--radius);padding:22px;
    transition:border-color .2s,transform .2s;
  }
  .force:hover{border-color:rgba(245,158,11,.4);transform:translateY(-3px)}
  .force .ic{font-size:1.7rem;margin-bottom:12px;display:block}
  .force h3{font-size:1.05rem;margin-bottom:8px}
  .force p{font-size:.84rem;color:var(--text-2)}
  .force .count{
    display:inline-block;margin-top:14px;font-family:'JetBrains Mono',monospace;font-size:.72rem;
    color:var(--accent);background:rgba(245,158,11,.08);border:1px solid rgba(245,158,11,.25);
    padding:3px 10px;border-radius:999px;
  }
  .dbl{display:grid;grid-template-columns:repeat(auto-fit,minmax(280px,1fr));gap:16px}
  .ben{background:var(--surface);border:1px solid var(--border);border-radius:var(--radius);padding:22px;transition:border-color .2s}
  .ben:hover{border-color:rgba(34,197,94,.4)}
  .ben-top{display:flex;align-items:center;gap:10px;margin-bottom:10px}
  .ben-tick{font-family:'JetBrains Mono',monospace;font-weight:700;color:var(--green);font-size:1.05rem}
  .ben-x{font-family:'JetBrains Mono',monospace;font-size:.68rem;color:var(--accent);background:rgba(245,158,11,.1);border:1px solid rgba(245,158,11,.3);padding:2px 8px;border-radius:6px;margin-left:auto}
  .ben h3{font-size:1.02rem;margin-bottom:8px}
  .ben p{font-size:.85rem;color:var(--text-2);margin-bottom:14px}
  .chips{display:flex;gap:8px;flex-wrap:wrap}
  .chip{font-size:.7rem;font-family:'JetBrains Mono',monospace;color:var(--text-2);background:var(--surface-2);border:1px solid var(--border-2);padding:3px 10px;border-radius:999px}
  .signals{display:flex;flex-direction:column;gap:22px}
  .card{background:var(--surface);border:1px solid var(--border);border-radius:var(--radius);overflow:hidden;transition:border-color .2s}
  .card:hover{border-color:var(--border-2)}
  .card-head{padding:22px 24px 18px;border-bottom:1px solid var(--border)}
  .tags{display:flex;gap:8px;flex-wrap:wrap;margin-bottom:12px}
  .tag{font-family:'JetBrains Mono',monospace;font-size:.68rem;letter-spacing:.06em;text-transform:uppercase;padding:3px 10px;border-radius:6px}
  .tag-theme{color:var(--accent);background:rgba(245,158,11,.1);border:1px solid rgba(245,158,11,.3)}
  .tag-sector{color:var(--text-2);background:var(--surface-2);border:1px solid var(--border-2)}
  .card-head h3{font-size:1.22rem;font-weight:700;letter-spacing:-.01em;line-height:1.3}
  .card-body{padding:20px 24px 24px}
  .chain{display:flex;align-items:center;gap:12px;flex-wrap:wrap;margin-bottom:18px}
  .chain .mech{
    font-family:'JetBrains Mono',monospace;font-size:.74rem;font-weight:600;
    padding:5px 12px;border-radius:7px;white-space:nowrap;
    background:rgba(245,158,11,.1);color:var(--accent);border:1px solid rgba(245,158,11,.3);
  }
  .chain p{font-size:.9rem;color:var(--text-2);flex:1;min-width:240px}
  .tables{display:grid;grid-template-columns:1fr 1fr;gap:18px}
  .tbl-wrap h4{font-size:.78rem;letter-spacing:.08em;text-transform:uppercase;margin-bottom:10px;display:flex;align-items:center;gap:7px}
  .win h4{color:var(--green)}
  .lose h4{color:var(--red)}
  table{width:100%;border-collapse:collapse;font-size:.82rem}
  th{text-align:left;font-family:'JetBrains Mono',monospace;font-size:.66rem;letter-spacing:.06em;text-transform:uppercase;color:var(--muted);padding:6px 8px;border-bottom:1px solid var(--border)}
  td{padding:9px 8px;border-bottom:1px solid var(--border);vertical-align:top;color:var(--text-2)}
  tr:last-child td{border-bottom:none}
  .tick{font-family:'JetBrains Mono',monospace;font-weight:700;color:var(--text)}
  .co{color:var(--text);font-weight:500}
  .cv{
    font-family:'JetBrains Mono',monospace;font-weight:700;font-size:.78rem;
    display:inline-flex;align-items:center;justify-content:center;
    width:30px;height:26px;border-radius:8px;
  }
  .cv-h{background:rgba(34,197,94,.14);color:var(--green);border:1px solid rgba(34,197,94,.4)}
  .cv-m{background:rgba(249,115,22,.14);color:var(--orange);border:1px solid rgba(249,115,22,.4)}
  .cv-l{background:rgba(59,130,246,.14);color:var(--blue);border:1px solid rgba(59,130,246,.4)}
  .steps{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:16px}
  .step{background:var(--surface);border:1px solid var(--border);border-radius:var(--radius);padding:24px;position:relative}
  .step .n{font-family:'JetBrains Mono',monospace;font-size:.72rem;color:var(--accent);letter-spacing:.1em}
  .step .ic{font-size:1.6rem;margin:10px 0 12px;display:block}
  .step h3{font-size:1.05rem;margin-bottom:8px}
  .step p{font-size:.85rem;color:var(--text-2)}
  footer{border-top:1px solid var(--border);padding:42px 0;text-align:center;margin-top:20px}
  footer .brand{justify-content:center;margin-bottom:10px}
  footer p{color:var(--muted);font-size:.84rem;margin-bottom:4px}
  footer .nia{font-family:'JetBrains Mono',monospace;font-size:.7rem;letter-spacing:.18em;color:var(--red);margin-top:14px;opacity:.8}
  @media(max-width:768px){
    .legend{grid-template-columns:1fr}
    .tables{grid-template-columns:1fr}
    .nav-meta{display:none}
    section{padding:40px 0}
    header{padding:64px 0 50px}
  }
  @media(max-width:480px){
    .wrap{padding:0 16px}
    .stat{min-width:104px;padding:13px 18px}
    .stat .num{font-size:1.4rem}
    h1{font-size:2rem}
    .card-head,.card-body{padding-left:16px;padding-right:16px}
    th,td{padding:7px 5px;font-size:.76rem}
    .sec-head h2{font-size:1.35rem}
  }
</style>
</head>
<body>
"""

STATIC_LEGEND = """
<!-- LEGEND -->
<section id="legend">
  <div class="wrap">
    <div class="sec-head"><h2>Conviction Legend</h2><span class="sec-tag">Scoring Guide</span></div>
    <div class="legend">
      <div class="leg">
        <span class="badge b-green mono">8–10</span>
        <h3>High Conviction</h3>
        <p>Direct causal link, significant revenue exposure, likely underpriced by the market. Imminent impact.</p>
      </div>
      <div class="leg">
        <span class="badge b-orange mono">5–7</span>
        <h3>Moderate Conviction</h3>
        <p>Clear mechanism but partial pricing in, some macro uncertainty, or a second-order effect.</p>
      </div>
      <div class="leg">
        <span class="badge b-blue mono">1–4</span>
        <h3>Conditional</h3>
        <p>Speculative or longer-horizon thesis. Likely already priced in, or depends on uncertain follow-through.</p>
      </div>
    </div>
  </div>
</section>
"""

STATIC_HOW = """
<!-- HOW IT WORKS -->
<section id="how">
  <div class="wrap">
    <div class="sec-head"><h2>How Catalyst Works</h2><span class="sec-tag">Methodology</span></div>
    <div class="steps">
      <div class="step">
        <span class="n mono">STEP 01</span>
        <span class="ic">🔍</span>
        <h3>Scan</h3>
        <p>Every morning, Catalyst scans global news for events creating supply or demand shocks — geopolitical, financial, regulatory, climatic and technological.</p>
      </div>
      <div class="step">
        <span class="n mono">STEP 02</span>
        <span class="ic">🔗</span>
        <h3>Trace</h3>
        <p>Each event is traced through its causal chain: what becomes scarcer or more abundant, and which companies sit directly in the path of that change?</p>
      </div>
      <div class="step">
        <span class="n mono">STEP 03</span>
        <span class="ic">🎯</span>
        <h3>Score</h3>
        <p>A conviction score (1–10) is assigned on directness of the causal link, revenue exposure, and how much of the effect is already priced into the stock.</p>
      </div>
      <div class="step">
        <span class="n mono">STEP 04</span>
        <span class="ic">📬</span>
        <h3>Deliver</h3>
        <p>The full brief is published each morning with winners, losers, macro themes and double beneficiaries — ready before markets open.</p>
      </div>
    </div>
  </div>
</section>
"""

# ---------------------------------------------------------------------------
# 3. Rendering
# ---------------------------------------------------------------------------

def esc(s):
    # Strip citation tags the model sometimes embeds in searched text,
    # then escape for HTML.
    s = re.sub(r"</?cite[^>]*>", "", str(s))
    return html.escape(s, quote=False)


def cv_class(cv):
    return "cv-h" if cv >= 8 else ("cv-m" if cv >= 5 else "cv-l")


def render_table(rows):
    out = ["<table>", "<tr><th>Ticker</th><th>Company</th><th>Thesis</th><th>CV</th></tr>"]
    for r in rows:
        out.append(
            f'<tr><td class="tick">{esc(r["ticker"])}</td>'
            f'<td class="co">{esc(r["company"])}</td>'
            f'<td>{esc(r["thesis"])}</td>'
            f'<td><span class="cv {cv_class(r["cv"])}">{int(r["cv"])}</span></td></tr>'
        )
    out.append("</table>")
    return "\n".join(out)


def render(data, date_str):
    n_sig, n_thm, n_dbl = len(data["signals"]), len(data["themes"]), len(data["doubles"])
    hs = data["headline_stat"]

    parts = [PAGE_HEAD]

    parts.append(f"""
<nav>
  <div class="wrap nav-inner">
    <a href="#" class="brand"><span class="logo">⚛</span> Cata<b>lyst</b></a>
    <div class="nav-meta">{date_str} <span class="dot">·</span> Daily Brief</div>
  </div>
</nav>

<header>
  <div class="wrap">
    <span class="eyebrow">Daily Intelligence Brief</span>
    <h1>Supply &amp; Demand <span class="accent">Signal Report</span></h1>
    <p class="lede">Global events parsed into market-moving catalysts. Causal chains traced to specific stocks. Updated every morning.</p>
    <div class="stats">
      <div class="stat"><div class="num mono">{n_sig}</div><div class="lbl">Signals</div></div>
      <div class="stat"><div class="num mono">{n_thm}</div><div class="lbl">Macro Themes</div></div>
      <div class="stat"><div class="num mono">{n_dbl}</div><div class="lbl">Double Plays</div></div>
      <div class="stat"><div class="num mono">{esc(hs["value"])}</div><div class="lbl">{esc(hs["label"])}</div></div>
    </div>
  </div>
</header>

<div class="wrap">
  <div class="disclaimer">
    <span class="i">ℹ</span>
    <span>This report is for informational purposes only and does not constitute investment advice, a solicitation, or a recommendation to buy or sell any security. All analysis reflects publicly available information. Past catalyst patterns do not guarantee future performance. Consult a licensed financial advisor before making investment decisions.</span>
  </div>
</div>
""")

    parts.append(STATIC_LEGEND)

    # Macro themes (signal counts computed from the signals list)
    theme_counts = {}
    for s in data["signals"]:
        theme_counts[s["theme"]] = theme_counts.get(s["theme"], 0) + 1

    forces = []
    for t in data["themes"]:
        c = theme_counts.get(t["title"], 0)
        label = f"{c} signal" if c == 1 else f"{c} signals"
        forces.append(f"""      <div class="force">
        <span class="ic">{esc(t["icon"])}</span>
        <h3>{esc(t["title"])}</h3>
        <p>{esc(t["desc"])}</p>
        <span class="count mono">{label}</span>
      </div>""")

    parts.append(f"""
<!-- MACRO THEMES -->
<section id="macro">
  <div class="wrap">
    <div class="sec-head"><h2>Macro Themes</h2><span class="sec-tag">{n_thm} Forces</span></div>
    <div class="macro">
{chr(10).join(forces)}
    </div>
  </div>
</section>
""")

    # Double beneficiaries
    bens = []
    for d in data["doubles"]:
        chips = "".join(f'<span class="chip">{esc(c)}</span>' for c in d["chips"])
        bens.append(f"""      <div class="ben">
        <div class="ben-top"><span class="ben-tick mono">{esc(d["ticker"])}</span><span class="ben-x mono">2× catalyst</span></div>
        <h3>{esc(d["company"])}</h3>
        <p>{esc(d["desc"])}</p>
        <div class="chips">{chips}</div>
      </div>""")

    parts.append(f"""
<!-- DOUBLE BENEFICIARIES -->
<section id="double">
  <div class="wrap">
    <div class="sec-head"><h2>Double Beneficiaries</h2><span class="sec-tag">2+ Signals</span></div>
    <div class="dbl">
{chr(10).join(bens)}
    </div>
  </div>
</section>
""")

    # Individual signals
    cards = []
    for i, s in enumerate(data["signals"], 1):
        cards.append(f"""      <!-- SIGNAL {i} -->
      <div class="card">
        <div class="card-head">
          <div class="tags"><span class="tag tag-theme">{esc(s["theme"])}</span><span class="tag tag-sector">{esc(s["sector"])}</span></div>
          <h3>{esc(s["title"])}</h3>
        </div>
        <div class="card-body">
          <div class="chain">
            <span class="mech">{esc(s["mech"])}</span>
            <p>{esc(s["summary"])}</p>
          </div>
          <div class="tables">
            <div class="tbl-wrap win">
              <h4>▲ Winners</h4>
              {render_table(s["winners"])}
            </div>
            <div class="tbl-wrap lose">
              <h4>▼ Losers</h4>
              {render_table(s["losers"])}
            </div>
          </div>
        </div>
      </div>
""")

    parts.append(f"""
<!-- INDIVIDUAL SIGNALS -->
<section id="signals">
  <div class="wrap">
    <div class="sec-head"><h2>Individual Signals</h2><span class="sec-tag">{n_sig} Signals</span></div>
    <div class="signals">

{chr(10).join(cards)}
    </div>
  </div>
</section>
""")

    parts.append(STATIC_HOW)

    parts.append(f"""
<footer>
  <div class="wrap">
    <div class="brand"><span class="logo">⚛</span> Cata<b>lyst</b></div>
    <p>Supply &amp; demand intelligence for public markets</p>
    <p>Daily Intelligence Brief · {date_str}</p>
    <p class="nia">NOT INVESTMENT ADVICE</p>
  </div>
</footer>

</body>
</html>
""")

    return "".join(parts)


# ---------------------------------------------------------------------------
# 4. Validation
# ---------------------------------------------------------------------------

def validate(data):
    for key in ("headline_stat", "themes", "doubles", "signals"):
        if key not in data:
            raise ValueError(f"missing key: {key}")
    if not (isinstance(data["headline_stat"], dict)
            and "value" in data["headline_stat"] and "label" in data["headline_stat"]):
        raise ValueError("bad headline_stat")
    if not (4 <= len(data["themes"]) <= 8):
        raise ValueError(f"expected 4-8 themes, got {len(data['themes'])}")
    if not (6 <= len(data["signals"]) <= 14):
        raise ValueError(f"expected 6-14 signals, got {len(data['signals'])}")
    if not (2 <= len(data["doubles"]) <= 8):
        raise ValueError(f"expected 2-8 doubles, got {len(data['doubles'])}")
    titles = {t["title"] for t in data["themes"]}
    for t in data["themes"]:
        for k in ("icon", "title", "desc"):
            if not t.get(k):
                raise ValueError(f"theme missing {k}")
    for d in data["doubles"]:
        for k in ("ticker", "company", "desc", "chips"):
            if not d.get(k):
                raise ValueError(f"double missing {k}")
    for s in data["signals"]:
        for k in ("theme", "sector", "title", "mech", "summary", "winners", "losers"):
            if not s.get(k):
                raise ValueError(f"signal missing {k}: {s.get('title', '?')}")
        if s["theme"] not in titles:
            raise ValueError(f"signal theme '{s['theme']}' matches no theme title")
        for side in ("winners", "losers"):
            for r in s[side]:
                for k in ("ticker", "company", "thesis", "cv"):
                    if k not in r or r[k] in ("", None):
                        raise ValueError(f"row missing {k} in '{s['title']}'")
                if not (1 <= int(r["cv"]) <= 10):
                    raise ValueError(f"cv out of range in '{s['title']}'")


# ---------------------------------------------------------------------------
# 5. Main
# ---------------------------------------------------------------------------

def extract_json(text):
    """Pull the outermost JSON object out of the model's response."""
    text = re.sub(r"^```(?:json)?|```$", "", text.strip(), flags=re.MULTILINE).strip()
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end == -1:
        raise ValueError("no JSON object found in model response")
    return json.loads(text[start:end + 1])


def call_model(client, messages):
    return client.messages.create(
        model=MODEL,
        max_tokens=16000,
        tools=[{"type": "web_search_20250305", "name": "web_search", "max_uses": 10}],
        messages=messages,
    )


def main():
    if not os.environ.get("ANTHROPIC_API_KEY"):
        sys.exit("ANTHROPIC_API_KEY is not set")

    now = datetime.now(ZoneInfo("America/New_York"))
    date_str = now.strftime("%B %-d, %Y")

    client = anthropic.Anthropic()
    print(f"Generating brief for {date_str} ...")

    messages = [{"role": "user", "content": PROMPT.format(date=date_str)}]
    data = None
    for attempt in range(1, 4):
        resp = call_model(client, messages)
        # Web search can pause long turns (stop_reason "pause_turn");
        # keep continuing the same turn until the model actually finishes.
        hops = 0
        while resp.stop_reason == "pause_turn" and hops < 8:
            messages.append({"role": "assistant", "content": resp.content})
            resp = call_model(client, messages)
            hops += 1

        text = "".join(b.text for b in resp.content if b.type == "text")
        try:
            data = extract_json(text)
            break
        except (ValueError, json.JSONDecodeError) as e:
            print(f"Attempt {attempt}: no valid JSON ({e}); asking model to re-emit.")
            messages.append({"role": "assistant", "content": resp.content})
            messages.append({"role": "user", "content":
                "Now output ONLY the raw JSON object described earlier — no prose, "
                "no markdown fences, starting with '{' and ending with '}'."})

    if data is None:
        sys.exit("Failed to get valid JSON from the model after 3 attempts.")

    validate(data)

    page = render(data, date_str)
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        f.write(page)
    print(f"Wrote {OUTPUT_FILE}: {len(data['signals'])} signals, "
          f"{len(data['themes'])} themes, {len(data['doubles'])} doubles.")


def _friendly_exit(e):
    """Turn common API failures into a one-line message instead of a traceback."""
    msg = str(e)
    low = msg.lower()
    if "credit balance is too low" in low or "insufficient" in low:
        sys.exit(
            "ANTHROPIC BILLING: out of API credits. Add credits at "
            "https://console.anthropic.com/settings/billing and re-run this workflow."
        )
    if "authentication" in low or "invalid x-api-key" in low or "401" in msg:
        sys.exit(
            "ANTHROPIC AUTH: the ANTHROPIC_API_KEY secret is missing, revoked, or wrong. "
            "Update the repo secret and re-run this workflow."
        )
    if "rate limit" in low or "429" in msg:
        sys.exit("ANTHROPIC RATE LIMIT: too many requests right now. Re-run this workflow later.")
    if "not_found" in low and "model" in low:
        sys.exit(f"ANTHROPIC MODEL: '{MODEL}' is not available to this account. {msg}")
    sys.exit(f"ANTHROPIC API ERROR: {msg}")


if __name__ == "__main__":
    try:
        main()
    except anthropic.APIStatusError as e:
        _friendly_exit(e)
    except anthropic.APIConnectionError as e:
        sys.exit(f"NETWORK: could not reach the Anthropic API ({e}).")
