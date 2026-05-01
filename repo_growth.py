#!/usr/bin/env python3
"""
repo_growth.py — Visualise how a Git repository has grown over time.

Run the script to launch the Tk GUI:
    python repo_growth.py

Pick a repository folder, choose a detail level, click Generate. The chart
is saved inside the repo at <repo>/Repo Growth/<repo>_growth_<date>.html.

Detail levels (target data points): Rough ~100, Standard ~300, Detailed ~1500.
The newest commit is always included so the right edge of every chart
reflects current state.

Requirements:
    pip install gitpython
"""

import json
import os
import re
import sys
from collections import defaultdict
from datetime import datetime, timedelta

try:
    import git
except ImportError:
    print("Error: gitpython is required. Install it with:")
    print("  pip install gitpython")
    sys.exit(1)


COMMON_EXTENSIONS = {
    ".js", ".jsx", ".ts", ".tsx", ".py", ".php", ".css", ".scss",
    ".html", ".json", ".xml", ".md", ".txt", ".sh", ".sql",
    ".vue", ".svelte", ".rb", ".go", ".java", ".c", ".cpp", ".h"
}


def count_lines_and_files(commit):
    total_lines = 0
    total_files = 0
    ext_lines = defaultdict(int)
    try:
        for blob in commit.tree.traverse():
            if blob.type == "blob":
                total_files += 1
                try:
                    data = blob.data_stream.read()
                    if b"\x00" in data[:8000]:
                        continue
                    lines = data.count(b"\n") + (1 if data and not data.endswith(b"\n") else 0)
                    total_lines += lines
                    ext = os.path.splitext(blob.name)[1].lower()
                    if ext in COMMON_EXTENSIONS:
                        ext_lines[ext] += lines
                except Exception:
                    pass
    except Exception:
        pass
    return total_lines, total_files, dict(ext_lines)


def get_week_key(ts):
    dt = datetime.fromtimestamp(ts)
    monday = dt - timedelta(days=dt.weekday())
    return monday.strftime("%Y-%m-%d")


def get_commit_frequency_weekly(all_commits):
    weekly = defaultdict(int)
    for commit in all_commits:
        week = get_week_key(commit.committed_date)
        weekly[week] += 1
    return dict(sorted(weekly.items()))


def get_churn(repo, commits, progress=print):
    """Lines added/removed between consecutive (possibly sampled) commits.

    Uses `git diff --numstat`, which is much faster than building patches
    and parsing +/- lines in Python.
    """
    churn = []
    n = len(commits)
    for i in range(1, n):
        prev, curr = commits[i - 1], commits[i]
        added = removed = 0
        try:
            out = repo.git.diff(prev.hexsha, curr.hexsha, "--numstat")
            for line in out.splitlines():
                parts = line.split("\t")
                if len(parts) >= 2:
                    a, r = parts[0], parts[1]
                    if a.isdigit():
                        added += int(a)
                    if r.isdigit():
                        removed += int(r)
        except Exception:
            pass
        date_str = datetime.fromtimestamp(curr.committed_date).strftime("%Y-%m-%d")
        churn.append({"date": date_str, "added": added, "removed": removed})
        if i % 50 == 0:
            progress(f"  churn [{i}/{n - 1}]")
    return churn


REPO_GROWTH_DIRNAME = "Repo Growth"


def default_output_path(repo_path):
    """Date-stamped default path inside the repo's "Repo Growth" folder.

    Successive runs on different days produce different filenames; same-day
    reruns on the same repo overwrite (use --output to keep both).
    """
    repo_name = os.path.basename(os.path.abspath(repo_path)) or "repo"
    today = datetime.now().strftime("%Y-%m-%d")
    safe = re.sub(r"[^\w\-.]", "_", repo_name).strip("_") or "repo"
    return os.path.join(repo_path, REPO_GROWTH_DIRNAME, f"{safe}_growth_{today}.html")


def pick_sample_step(n, target=300):
    """Step size so list[::step] yields ~`target` items.

    Small repos (≤ target commits) → step 1 (every commit).
    Larger repos → step = n // target, evenly spaced across history.
    """
    if n <= target:
        return 1
    return max(1, n // target)


DETAIL_TARGETS = {"Rough": 100, "Standard": 300, "Detailed": 1500}


def analyse_repo(repo_path, branch=None, progress=print, target_points=300):
    progress(f"Opening repo at: {repo_path}")
    repo = git.Repo(repo_path)

    if branch is None:
        try:
            rev = repo.active_branch.name
            display_branch = rev
        except (TypeError, ValueError):
            rev = "HEAD"
            display_branch = f"HEAD ({repo.head.commit.hexsha[:7]})"
    else:
        rev = branch
        display_branch = branch
    progress(f"Branch: {display_branch}")

    try:
        all_commits = list(repo.iter_commits(rev))
    except git.GitCommandError as e:
        progress(f"Couldn't read '{rev}' ({e}); falling back to HEAD")
        all_commits = list(repo.iter_commits("HEAD"))
    total = len(all_commits)
    progress(f"Total commits: {total}")

    commit_frequency = get_commit_frequency_weekly(all_commits)
    most_active_week = max(commit_frequency, key=commit_frequency.get) if commit_frequency else "—"
    most_active_count = commit_frequency.get(most_active_week, 0)

    all_commits.reverse()  # oldest first

    step = pick_sample_step(total, target=target_points)
    indices = list(range(0, total, step))
    if total and indices[-1] != total - 1:
        indices.append(total - 1)  # always include the newest commit
    sampled = [all_commits[i] for i in indices]

    if step > 1:
        progress(f"Sampling every {step} commits -> {len(sampled)} data points (target ~{target_points})")
    else:
        progress(f"Processing every commit ({total} <= target {target_points})")

    data_points = []
    biggest_jump = {"delta": 0, "date": "", "message": ""}

    for idx, commit in enumerate(sampled):
        date_str = datetime.fromtimestamp(commit.committed_date).strftime("%Y-%m-%d")
        lines, files, ext_lines = count_lines_and_files(commit)
        avg_file_size = round(lines / files, 1) if files > 0 else 0
        msg = commit.message.split("\n")[0][:60]

        data_points.append({
            "date": date_str,
            "lines": lines,
            "files": files,
            "avg_file_size": avg_file_size,
            "ext_lines": ext_lines,
            "hash": commit.hexsha[:7],
            "message": msg,
        })

        if idx > 0:
            delta = abs(lines - data_points[idx - 1]["lines"])
            if delta > biggest_jump["delta"]:
                biggest_jump = {"delta": delta, "date": date_str, "message": msg}

        if (idx + 1) % 10 == 0 or (idx + 1) == len(sampled):
            pct = (idx + 1) / len(sampled) * 100
            progress(f"  [{idx+1}/{len(sampled)}] {pct:.0f}%  {date_str} — {lines:,} lines, {files} files")

    progress("Calculating churn...")
    churn = get_churn(repo, sampled, progress=progress)

    final_exts = data_points[-1]["ext_lines"] if data_points else {}
    top_exts = sorted(final_exts, key=lambda e: final_exts[e], reverse=True)[:6]

    first = data_points[0] if data_points else {}
    last  = data_points[-1] if data_points else {}

    return {
        "repo_name": os.path.basename(os.path.abspath(repo_path)),
        "branch": display_branch,
        "total_commits": total,
        "data": data_points,
        "top_exts": top_exts,
        "commit_frequency": commit_frequency,
        "churn": churn,
        "stats": {
            "lines_now":        last.get("lines", 0),
            "files_now":        last.get("files", 0),
            "lines_start":      first.get("lines", 0),
            "net_change":       last.get("lines", 0) - first.get("lines", 0),
            "avg_file_size":    last.get("avg_file_size", 0),
            "total_commits":    total,
            "active_weeks":     len(commit_frequency),
            "most_active_week": most_active_week,
            "most_active_count":most_active_count,
            "biggest_jump":     biggest_jump,
        }
    }


def generate_html(analysis, output_path, progress=print):
    data_json     = json.dumps(analysis["data"])
    freq_json     = json.dumps(analysis["commit_frequency"])
    top_exts_json = json.dumps(analysis["top_exts"])
    churn_json    = json.dumps(analysis["churn"])
    stats_json    = json.dumps(analysis["stats"])
    repo_name     = analysis["repo_name"]
    branch        = analysis["branch"]
    total_commits = analysis["total_commits"]

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{repo_name} — Repo Growth</title>
<style>
  @import url('https://fonts.googleapis.com/css2?family=Syne:wght@400;700;800&family=JetBrains+Mono:wght@400;500&display=swap');

  :root {{
    --bg: #0d0f14;
    --surface: #141720;
    --border: #1e2230;
    --accent: #00e5a0;
    --accent2: #0090ff;
    --accent3: #ff6b6b;
    --accent4: #ffd93d;
    --text: #e8eaf0;
    --muted: #5a6070;
  }}

  * {{ box-sizing: border-box; margin: 0; padding: 0; }}

  body {{
    background: var(--bg);
    color: var(--text);
    font-family: 'Syne', sans-serif;
    min-height: 100vh;
    padding: 40px 32px;
  }}

  .header {{ margin-bottom: 36px; }}
  .header h1 {{
    font-size: clamp(26px, 4vw, 46px);
    font-weight: 800;
    letter-spacing: -1px;
    line-height: 1;
  }}
  .header h1 span {{ color: var(--accent); }}
  .header p {{
    margin-top: 8px;
    font-family: 'JetBrains Mono', monospace;
    font-size: 13px;
    color: var(--muted);
  }}

  .stats-grid {{
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(160px, 1fr));
    gap: 12px;
    margin-bottom: 28px;
  }}

  .stat {{
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: 10px;
    padding: 14px 18px;
  }}
  .stat-value {{
    font-size: 20px;
    font-weight: 700;
    color: var(--accent);
    font-family: 'JetBrains Mono', monospace;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }}
  .stat-value.neg {{ color: var(--accent3); }}
  .stat-label {{
    font-size: 11px;
    color: var(--muted);
    text-transform: uppercase;
    letter-spacing: 1px;
    margin-top: 4px;
  }}
  .stat-sub {{
    font-size: 10px;
    color: #3a4050;
    font-family: 'JetBrains Mono', monospace;
    margin-top: 3px;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }}

  .charts {{
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 20px;
    margin-bottom: 20px;
  }}
  .chart-full {{ grid-column: 1 / -1; }}
  .chart-wrap {{
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: 16px;
    padding: 24px 28px 20px;
  }}
  .chart-title {{
    font-size: 12px;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: 1.5px;
    color: var(--muted);
    margin-bottom: 14px;
  }}
  canvas {{ display: block; width: 100%; }}

  .tooltip {{
    position: fixed;
    background: #0a0c10;
    border: 1px solid var(--accent);
    border-radius: 8px;
    padding: 10px 14px;
    font-family: 'JetBrains Mono', monospace;
    font-size: 12px;
    pointer-events: none;
    opacity: 0;
    transition: opacity 0.1s;
    z-index: 100;
    max-width: 280px;
    line-height: 1.7;
  }}
  .tooltip.visible {{ opacity: 1; }}
  .t-date {{ color: var(--accent); font-weight: 500; }}
  .t-main {{ color: var(--text); font-size: 15px; font-weight: 700; }}
  .t-sub  {{ color: var(--muted); font-size: 11px; margin-top: 2px; word-break: break-word; }}
  .t-hash {{ color: var(--accent2); font-size: 11px; }}
  .t-add  {{ color: var(--accent); font-size: 11px; }}
  .t-rem  {{ color: var(--accent3); font-size: 11px; }}

  .legend {{
    display: flex;
    flex-wrap: wrap;
    gap: 12px;
    margin-top: 14px;
  }}
  .legend-item {{
    display: flex;
    align-items: center;
    gap: 6px;
    font-family: 'JetBrains Mono', monospace;
    font-size: 11px;
    color: var(--muted);
  }}
  .legend-dot {{ width: 10px; height: 10px; border-radius: 2px; flex-shrink: 0; }}

  .footer {{
    margin-top: 16px;
    font-family: 'JetBrains Mono', monospace;
    font-size: 11px;
    color: var(--muted);
    text-align: right;
  }}

  @media (max-width: 700px) {{
    .charts {{ grid-template-columns: 1fr; }}
    .chart-full {{ grid-column: 1; }}
    body {{ padding: 20px 16px; }}
  }}
</style>
</head>
<body>

<div class="header">
  <h1><span>{repo_name}</span> growth</h1>
  <p>branch: {branch} &nbsp;·&nbsp; {total_commits:,} commits</p>
</div>

<div class="stats-grid" id="statsGrid"></div>

<div class="charts">
  <div class="chart-wrap chart-full">
    <div class="chart-title">Lines of Code — by Commit Number</div>
    <canvas id="linesByCommitChart"></canvas>
  </div>
  <div class="chart-wrap chart-full">
    <div class="chart-title">Lines of Code — by Date</div>
    <canvas id="linesByDateChart"></canvas>
  </div>
  <div class="chart-wrap">
    <div class="chart-title">Total Files over Time</div>
    <canvas id="filesChart"></canvas>
  </div>
  <div class="chart-wrap">
    <div class="chart-title">Average File Size (lines) over Time</div>
    <canvas id="avgSizeChart"></canvas>
  </div>
  <div class="chart-wrap">
    <div class="chart-title">Commits per Week</div>
    <canvas id="freqChart"></canvas>
  </div>
  <div class="chart-wrap">
    <div class="chart-title">Churn — Lines Added vs Removed</div>
    <canvas id="churnChart"></canvas>
  </div>
  <div class="chart-wrap chart-full">
    <div class="chart-title">Lines by File Type over Time</div>
    <canvas id="extChart"></canvas>
    <div class="legend" id="extLegend"></div>
  </div>
</div>

<div class="tooltip" id="tooltip"></div>
<div class="footer">generated by repo_growth.py &nbsp;·&nbsp; {total_commits:,} commits analysed</div>

<script>
const RAW   = {data_json};
const FREQ  = {freq_json};
const EXTS  = {top_exts_json};
const CHURN = {churn_json};
const STATS = {stats_json};

// Filter out early near-empty commits so Y axes start from first real content
const _sorted = RAW.slice().sort((a,b) => a.date.localeCompare(b.date));
const _maxLines = Math.max(..._sorted.map(d=>d.lines));
const DATA = _sorted.filter(d => d.lines > _maxLines * 0.02);

const EXT_COLORS = ['#00e5a0','#0090ff','#ff6b6b','#ffd93d','#c77dff','#ff9f43'];

const tooltip = document.getElementById('tooltip');
function showTip(e, html) {{
  tooltip.innerHTML = html;
  tooltip.classList.add('visible');
  tooltip.style.left = Math.min(e.clientX + 16, window.innerWidth - 290) + 'px';
  tooltip.style.top  = (e.clientY - 10) + 'px';
}}
function hideTip() {{ tooltip.classList.remove('visible'); }}

// Stats
const sg = document.getElementById('statsGrid');
const net = STATS.net_change;
const netStr = (net >= 0 ? '+' : '') + net.toLocaleString();
const netClass = net >= 0 ? '' : 'neg';
[
  [STATS.lines_now.toLocaleString(),                    'Lines now',          ''],
  [STATS.files_now.toLocaleString(),                    'Files now',          ''],
  [`<span class="${{netClass}}">${{netStr}}</span>`,        'Net line change',    ''],
  [STATS.avg_file_size + ' lines',                      'Avg file size',      'currently'],
  [STATS.total_commits.toLocaleString(),                'Total commits',      ''],
  [STATS.active_weeks + ' weeks',                       'Active weeks',       ''],
  [STATS.most_active_count + ' commits',                'Busiest week',       STATS.most_active_week],
  ['+' + STATS.biggest_jump.delta.toLocaleString(),     'Biggest jump',       STATS.biggest_jump.date + ' · ' + (STATS.biggest_jump.message||'').slice(0,30)],
].forEach(([val, label, sub]) => {{
  sg.innerHTML += `<div class="stat">
    <div class="stat-value">${{val}}</div>
    <div class="stat-label">${{label}}</div>
    ${{sub ? `<div class="stat-sub" title="${{sub}}">${{sub}}</div>` : ''}}
  </div>`;
}});

function setupCanvas(canvas, W, H) {{
  const dpr = window.devicePixelRatio || 1;
  canvas.style.width = W + 'px'; canvas.style.height = H + 'px';
  canvas.width = W * dpr; canvas.height = H * dpr;
  const ctx = canvas.getContext('2d');
  ctx.scale(dpr, dpr);
  return ctx;
}}

function drawGrid(ctx, PAD, CW, CH, minY, maxY, steps) {{
  for (let i = 0; i <= steps; i++) {{
    const v = minY + (maxY - minY) / steps * i;
    const y = PAD.top + CH - ((v - minY) / (maxY - minY)) * CH;
    ctx.strokeStyle = '#1a1e28'; ctx.lineWidth = 1;
    ctx.beginPath(); ctx.moveTo(PAD.left, y); ctx.lineTo(PAD.left + CW, y); ctx.stroke();
    ctx.fillStyle = '#5a6070'; ctx.font = '11px JetBrains Mono,monospace'; ctx.textAlign = 'right';
    ctx.fillText(Math.round(v).toLocaleString(), PAD.left - 8, y + 4);
  }}
}}

function drawXLabels(ctx, n, H, PAD, CW, labelFn) {{
  const step = Math.max(1, Math.floor(n / 7));
  ctx.fillStyle = '#5a6070'; ctx.textAlign = 'center'; ctx.font = '11px JetBrains Mono,monospace';
  for (let i = 0; i < n; i += step) ctx.fillText(labelFn(i), PAD.left + (i/(n-1||1))*CW, H - PAD.bottom + 18);
}}

function smoothLine(ctx, pts) {{
  ctx.beginPath(); ctx.moveTo(pts[0].x, pts[0].y);
  for (let i = 1; i < pts.length; i++) {{
    const cpx = (pts[i-1].x + pts[i].x) / 2;
    ctx.bezierCurveTo(cpx, pts[i-1].y, cpx, pts[i].y, pts[i].x, pts[i].y);
  }}
}}

function drawLineChart(canvas, values, color, dataRef, labelFn, H, byDate) {{
  H = H || 260;
  const W = canvas.parentElement.clientWidth - 56;
  const ctx = setupCanvas(canvas, W, H);
  const PAD = {{top:16, right:16, bottom:44, left:88}};
  const CW = W - PAD.left - PAD.right, CH = H - PAD.top - PAD.bottom;
  const n = values.length;
  if (n < 2) return;

  const minVal = Math.min(...values), maxVal = Math.max(...values);
  const pad = (maxVal - minVal) * 0.1 || 1;
  const minY = Math.max(0, minVal - pad), maxY = maxVal + pad;

  let xp;
  if (byDate) {{
    const times = dataRef.map(d => new Date(d.date).getTime());
    const tMin = times[0], tMax = times[n-1];
    const tSpan = (tMax - tMin) || 1;
    xp = i => PAD.left + ((times[i] - tMin) / tSpan) * CW;
  }} else {{
    xp = i => PAD.left + (i / (n-1)) * CW;
  }}
  const yp = v => PAD.top + CH - ((v - minY) / (maxY - minY)) * CH;

  drawGrid(ctx, PAD, CW, CH, minY, maxY, 4);
  if (byDate) {{
    const times = dataRef.map(d => new Date(d.date).getTime());
    const tMin = times[0], tMax = times[n-1];
    ctx.fillStyle = '#5a6070'; ctx.textAlign = 'center'; ctx.font = '11px JetBrains Mono,monospace';
    for (let i = 0; i <= 7; i++) {{
      const t = tMin + (tMax - tMin) * (i / 7);
      const x = PAD.left + (i / 7) * CW;
      const dt = new Date(t);
      ctx.fillText(`${{dt.getFullYear()}}-${{String(dt.getMonth()+1).padStart(2,'0')}}`, x, H - PAD.bottom + 18);
    }}
  }} else {{
    drawXLabels(ctx, n, H, PAD, CW, i => dataRef[i].date.slice(0,7));
  }}

  const pts = values.map((v,i) => ({{x:xp(i), y:yp(v)}}));

  smoothLine(ctx, pts);
  ctx.lineTo(xp(n-1), PAD.top+CH); ctx.lineTo(xp(0), PAD.top+CH); ctx.closePath();
  const g = ctx.createLinearGradient(0,PAD.top,0,PAD.top+CH);
  g.addColorStop(0, color+'30'); g.addColorStop(1, color+'00');
  ctx.fillStyle = g; ctx.fill();

  smoothLine(ctx, pts);
  ctx.strokeStyle = color; ctx.lineWidth = 2; ctx.stroke();

  canvas._pts = values.map((v,i) => ({{x:xp(i), y:yp(v), v, d:dataRef[i]}}));
  canvas.onmousemove = e => {{
    const mx = e.clientX - canvas.getBoundingClientRect().left;
    let cl = null, md = Infinity;
    canvas._pts.forEach(p => {{ const d = Math.abs(p.x-mx); if(d<md){{md=d;cl=p;}} }});
    if (cl && md < 50) showTip(e, labelFn(cl)); else hideTip();
  }};
  canvas.onmouseleave = hideTip;
}}

function drawBarChart(canvas, labels, values, color) {{
  const W = canvas.parentElement.clientWidth - 56, H = 260;
  const ctx = setupCanvas(canvas, W, H);
  const PAD = {{top:16, right:16, bottom:44, left:52}};
  const CW = W - PAD.left - PAD.right, CH = H - PAD.top - PAD.bottom;
  const n = values.length;
  const maxY = Math.max(...values) * 1.1 || 1;
  const yp = v => PAD.top + CH - (v/maxY)*CH;

  drawGrid(ctx, PAD, CW, CH, 0, maxY, 4);

  const barW = Math.max(2, CW/n*0.7);
  const rects = [];
  values.forEach((v,i) => {{
    const x = PAD.left + (i+0.5)/n*CW - barW/2;
    const bh = (v/maxY)*CH, y = PAD.top+CH-bh;
    ctx.fillStyle = color + '99';
    ctx.beginPath();
    if (ctx.roundRect) ctx.roundRect(x,y,barW,bh,2); else ctx.rect(x,y,barW,bh);
    ctx.fill();
    rects.push({{x, w:barW, v, label:labels[i]}});
  }});

  const step = Math.max(1, Math.floor(n/10));
  ctx.fillStyle='#5a6070'; ctx.textAlign='center'; ctx.font='11px JetBrains Mono,monospace';
  for (let i=0;i<n;i+=step) ctx.fillText(labels[i], PAD.left+(i+0.5)/n*CW, H-PAD.bottom+18);

  canvas.onmousemove = e => {{
    const mx = e.clientX - canvas.getBoundingClientRect().left;
    const hit = rects.find(r => mx>=r.x && mx<=r.x+r.w);
    if (hit) showTip(e, `<div class="t-date">${{hit.label}}</div><div class="t-main">${{hit.v}} commits</div>`);
    else hideTip();
  }};
  canvas.onmouseleave = hideTip;
}}

function drawChurnChart(canvas, churn) {{
  const W = canvas.parentElement.clientWidth - 56, H = 260;
  const ctx = setupCanvas(canvas, W, H);
  const PAD = {{top:16, right:16, bottom:44, left:68}};
  const CW = W - PAD.left - PAD.right, CH = H - PAD.top - PAD.bottom;
  const n = churn.length;
  if (!n) return;

  const maxY = Math.max(...churn.map(c => Math.max(c.added, c.removed))) * 1.1 || 1;
  drawGrid(ctx, PAD, CW, CH, 0, maxY, 4);

  const slotW = CW / n;
  const barW  = Math.max(1, slotW * 0.35);
  const rects = [];

  churn.forEach((c,i) => {{
    const cx = PAD.left + (i+0.5)*slotW;
    const ah = (c.added/maxY)*CH;
    ctx.fillStyle='#00e5a055';
    ctx.beginPath();
    if(ctx.roundRect) ctx.roundRect(cx-barW-1, PAD.top+CH-ah, barW, ah, 1); else ctx.rect(cx-barW-1, PAD.top+CH-ah, barW, ah);
    ctx.fill();
    const rh = (c.removed/maxY)*CH;
    ctx.fillStyle='#ff6b6b55';
    ctx.beginPath();
    if(ctx.roundRect) ctx.roundRect(cx+1, PAD.top+CH-rh, barW, rh, 1); else ctx.rect(cx+1, PAD.top+CH-rh, barW, rh);
    ctx.fill();
    rects.push({{cx, slotW, c, i}});
  }});

  const step = Math.max(1, Math.floor(n/8));
  ctx.fillStyle='#5a6070'; ctx.textAlign='center'; ctx.font='11px JetBrains Mono,monospace';
  for (let i=0;i<n;i+=step) ctx.fillText(churn[i].date.slice(0,7), PAD.left+(i+0.5)*slotW, H-PAD.bottom+18);

  ctx.fillStyle='#00e5a0'; ctx.fillRect(PAD.left, H-8, 10, 6);
  ctx.fillStyle='#5a6070'; ctx.textAlign='left'; ctx.font='11px JetBrains Mono,monospace';
  ctx.fillText('added', PAD.left+14, H-3);
  ctx.fillStyle='#ff6b6b'; ctx.fillRect(PAD.left+80, H-8, 10, 6);
  ctx.fillStyle='#5a6070'; ctx.fillText('removed', PAD.left+94, H-3);

  canvas.onmousemove = e => {{
    const mx = e.clientX - canvas.getBoundingClientRect().left;
    const idx = Math.floor((mx - PAD.left) / slotW);
    if (idx >= 0 && idx < n) {{
      const c = churn[idx];
      showTip(e, `<div class="t-date">${{c.date}}</div><div class="t-add">+${{c.added.toLocaleString()}} added</div><div class="t-rem">−${{c.removed.toLocaleString()}} removed</div>`);
    }} else hideTip();
  }};
  canvas.onmouseleave = hideTip;
}}

function drawStackedChart(canvas, data, exts, colors) {{
  const W = canvas.parentElement.clientWidth - 56, H = 280;
  const ctx = setupCanvas(canvas, W, H);
  const PAD = {{top:16, right:16, bottom:44, left:88}};
  const CW = W - PAD.left - PAD.right, CH = H - PAD.top - PAD.bottom;
  const n = data.length;
  if (n < 2 || !exts.length) return;

  const stacks = data.map(d => {{
    let cum = 0;
    return exts.map(ext => {{ cum += (d.ext_lines&&d.ext_lines[ext])||0; return cum; }});
  }});

  const maxY = Math.max(...stacks.map(s=>s[s.length-1]))*1.1||1;
  const xp = i => PAD.left + (i/(n-1))*CW;
  const yp = v => PAD.top + CH - (v/maxY)*CH;

  drawGrid(ctx, PAD, CW, CH, 0, maxY, 4);
  drawXLabels(ctx, n, H, PAD, CW, i => data[i].date.slice(0,7));

  for (let ei = exts.length-1; ei >= 0; ei--) {{
    const top = stacks.map((s,i) => ({{x:xp(i), y:yp(s[ei])}}));
    smoothLine(ctx, top);
    if (ei === 0) {{
      ctx.lineTo(xp(n-1), PAD.top+CH); ctx.lineTo(xp(0), PAD.top+CH);
    }} else {{
      const bot = stacks.map((s,i) => ({{x:xp(i), y:yp(s[ei-1])}})).reverse();
      bot.forEach((p,j) => {{
        if (j===0) ctx.lineTo(p.x, p.y);
        else {{ const prev=bot[j-1]; const cpx=(prev.x+p.x)/2; ctx.bezierCurveTo(cpx,prev.y,cpx,p.y,p.x,p.y); }}
      }});
    }}
    ctx.closePath(); ctx.fillStyle=colors[ei]+'bb'; ctx.fill();
  }}

  const legendEl = document.getElementById('extLegend');
  legendEl.innerHTML = '';
  exts.forEach((ext,i) => {{
    const v = (data[data.length-1].ext_lines&&data[data.length-1].ext_lines[ext])||0;
    legendEl.innerHTML += `<div class="legend-item"><div class="legend-dot" style="background:${{colors[i]}}"></div>${{ext}} (${{v.toLocaleString()}})</div>`;
  }});

  canvas.onmousemove = e => {{
    const mx = e.clientX - canvas.getBoundingClientRect().left;
    const idx = Math.round((mx-PAD.left)/CW*(n-1));
    if (idx<0||idx>=n) {{ hideTip(); return; }}
    const d = data[idx];
    let html = `<div class="t-date">${{d.date}}</div>`;
    exts.forEach((ext,i) => {{
      const v=(d.ext_lines&&d.ext_lines[ext])||0;
      html += `<div style="color:${{colors[i]}};font-size:11px">${{ext}}: ${{v.toLocaleString()}}</div>`;
    }});
    showTip(e, html);
  }};
  canvas.onmouseleave = hideTip;
}}

function drawAll() {{
  drawLineChart(document.getElementById('linesByCommitChart'), DATA.map(d=>d.lines), '#00e5a0', DATA, p=>`<div class="t-date">${{p.d.date}}</div><div class="t-main">${{p.v.toLocaleString()}} lines</div><div class="t-hash">${{p.d.hash}}</div><div class="t-sub">${{p.d.message}}</div>`, 300);
  drawLineChart(document.getElementById('linesByDateChart'),   DATA.map(d=>d.lines), '#ff9f43', DATA, p=>`<div class="t-date">${{p.d.date}}</div><div class="t-main">${{p.v.toLocaleString()}} lines</div><div class="t-hash">${{p.d.hash}}</div><div class="t-sub">${{p.d.message}}</div>`, 300, true);
  drawLineChart(document.getElementById('filesChart'),   DATA.map(d=>d.files),         '#0090ff', DATA, p=>`<div class="t-date">${{p.d.date}}</div><div class="t-main">${{p.v.toLocaleString()}} files</div><div class="t-hash">${{p.d.hash}}</div><div class="t-sub">${{p.d.message}}</div>`);
  drawLineChart(document.getElementById('avgSizeChart'), DATA.map(d=>d.avg_file_size), '#c77dff', DATA, p=>`<div class="t-date">${{p.d.date}}</div><div class="t-main">${{p.v}} lines/file</div><div class="t-hash">${{p.d.hash}}</div><div class="t-sub">${{p.d.message}}</div>`);
  drawBarChart(document.getElementById('freqChart'), Object.keys(FREQ), Object.values(FREQ), '#ffd93d');
  drawChurnChart(document.getElementById('churnChart'), CHURN);
  drawStackedChart(document.getElementById('extChart'), DATA, EXTS, EXT_COLORS.slice(0, EXTS.length));
}}

drawAll();
window.addEventListener('resize', drawAll);
</script>
</body>
</html>
"""

    parent = os.path.dirname(output_path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(html)
    progress(f"Chart saved to: {output_path}")


def launch_gui():
    import threading
    import queue
    import webbrowser
    import tkinter as tk
    from tkinter import filedialog, ttk, scrolledtext, messagebox

    root = tk.Tk()
    root.title("Repo Growth")
    root.geometry("680x540")
    root.minsize(540, 420)

    repo_var   = tk.StringVar()
    output_var = tk.StringVar(value="")
    branch_var = tk.StringVar()
    detail_var = tk.StringVar(value="Standard")

    msgs = queue.Queue()

    def log(msg):
        msgs.put(("log", str(msg)))

    def pick_repo():
        path = filedialog.askdirectory(title="Choose a Git repository")
        if path:
            repo_var.set(path)
            output_var.set(default_output_path(path))

    def pick_output():
        path = filedialog.asksaveasfilename(
            title="Save chart as…",
            defaultextension=".html",
            filetypes=[("HTML", "*.html"), ("All files", "*.*")],
            initialfile="repo_growth.html",
        )
        if path:
            output_var.set(path)

    def open_output():
        path = output_var.get()
        if os.path.exists(path):
            webbrowser.open(f"file:///{os.path.abspath(path).replace(os.sep, '/')}")

    def write_log(text):
        log_text.configure(state="normal")
        log_text.insert("end", text)
        log_text.see("end")
        log_text.configure(state="disabled")

    def run():
        repo_path = repo_var.get().strip()
        if not repo_path or not os.path.isdir(repo_path):
            messagebox.showerror("Repo Growth", "Choose a valid repository folder first.")
            return
        out    = output_var.get().strip() or default_output_path(repo_path)
        branch = branch_var.get().strip() or None
        target = DETAIL_TARGETS.get(detail_var.get(), 300)
        if not os.path.isdir(os.path.join(repo_path, ".git")):
            if not messagebox.askyesno(
                "Repo Growth",
                "That folder doesn't look like a Git repository (no .git directory). Continue anyway?",
            ):
                return

        log_text.configure(state="normal")
        log_text.delete("1.0", "end")
        log_text.configure(state="disabled")
        run_btn.configure(state="disabled")
        open_btn.configure(state="disabled")
        progress_bar.start(10)

        def worker():
            try:
                analysis = analyse_repo(repo_path, branch=branch, progress=log, target_points=target)
                generate_html(analysis, out, progress=log)
                msgs.put(("done", out))
            except Exception as e:
                msgs.put(("error", str(e)))

        threading.Thread(target=worker, daemon=True).start()

    def poll():
        try:
            while True:
                kind, payload = msgs.get_nowait()
                if kind == "log":
                    write_log(payload + "\n")
                elif kind == "done":
                    progress_bar.stop()
                    run_btn.configure(state="normal")
                    open_btn.configure(state="normal")
                    write_log(f"\n✓ Done. {payload}\n")
                elif kind == "error":
                    progress_bar.stop()
                    run_btn.configure(state="normal")
                    write_log(f"\nERROR: {payload}\n")
                    messagebox.showerror("Repo Growth", payload)
        except queue.Empty:
            pass
        root.after(100, poll)

    pad = {"padx": 10, "pady": 6}
    frm = ttk.Frame(root, padding=12)
    frm.pack(fill="both", expand=True)
    frm.columnconfigure(1, weight=1)

    ttk.Label(frm, text="Repository:").grid(row=0, column=0, sticky="w", **pad)
    ttk.Entry(frm, textvariable=repo_var).grid(row=0, column=1, sticky="ew", **pad)
    ttk.Button(frm, text="Browse…", command=pick_repo).grid(row=0, column=2, **pad)

    ttk.Label(frm, text="Output HTML:").grid(row=1, column=0, sticky="w", **pad)
    ttk.Entry(frm, textvariable=output_var).grid(row=1, column=1, sticky="ew", **pad)
    ttk.Button(frm, text="Save as…", command=pick_output).grid(row=1, column=2, **pad)

    ttk.Label(frm, text="Branch (optional):").grid(row=2, column=0, sticky="w", **pad)
    ttk.Entry(frm, textvariable=branch_var).grid(row=2, column=1, sticky="ew", **pad)

    ttk.Label(frm, text="Detail level:").grid(row=3, column=0, sticky="w", **pad)
    detail_combo = ttk.Combobox(
        frm, textvariable=detail_var,
        values=list(DETAIL_TARGETS.keys()),
        state="readonly",
    )
    detail_combo.grid(row=3, column=1, sticky="ew", **pad)
    ttk.Label(
        frm,
        text=f"  ~{DETAIL_TARGETS['Rough']} / {DETAIL_TARGETS['Standard']} / {DETAIL_TARGETS['Detailed']} pts",
        foreground="#777",
    ).grid(row=3, column=2, sticky="w", **pad)

    btn_row = ttk.Frame(frm)
    btn_row.grid(row=4, column=0, columnspan=3, sticky="ew", pady=(8, 4), padx=10)
    run_btn = ttk.Button(btn_row, text="Generate", command=run)
    run_btn.pack(side="left")
    open_btn = ttk.Button(btn_row, text="Open in browser", command=open_output, state="disabled")
    open_btn.pack(side="left", padx=(8, 0))

    progress_bar = ttk.Progressbar(frm, mode="indeterminate")
    progress_bar.grid(row=5, column=0, columnspan=3, sticky="ew", pady=(4, 8), padx=10)

    log_text = scrolledtext.ScrolledText(
        frm, height=18, state="disabled", wrap="word", font=("Consolas", 9)
    )
    log_text.grid(row=6, column=0, columnspan=3, sticky="nsew", padx=10, pady=(0, 10))
    frm.rowconfigure(6, weight=1)

    poll()
    root.mainloop()


if __name__ == "__main__":
    launch_gui()
