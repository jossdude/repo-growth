#!/usr/bin/env python3
"""
repo_growth.py — Visualise how a Git repository has grown over time.

Run the script to launch the Tk GUI:
    python repo_growth.py

Pick a repository folder, choose a detail level, click Generate. The chart
is saved inside the repo at <repo>/Repo Growth/<repo>_growth_<date>.html.

Detail levels (target data points): Rough ~100, Standard ~300, Detailed ~900.
The newest commit is always included so the right edge of every chart
reflects current state.

Requirements:
    pip install gitpython
"""

import json
import os
import re
import sys
from collections import Counter, defaultdict
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

DOW_NAMES = ["Monday", "Tuesday", "Wednesday", "Thursday",
             "Friday", "Saturday", "Sunday"]

# Hours considered "after hours" for the night-owl index.
NIGHT_HOURS = (22, 23, 0, 1, 2, 3, 4, 5)


def _blob_lines(blob, cache):
    """Non-binary line count for a blob, or None if binary/unreadable.

    Cached by the blob's content SHA. Git blobs are content-addressed, so
    identical file content across many commits shares one SHA — and most files
    don't change between sampled commits. Counting each distinct blob once
    instead of once per commit is the single biggest speed-up on large repos.
    """
    key = blob.binsha
    if key in cache:
        return cache[key]
    try:
        data = blob.data_stream.read()
    except Exception:
        cache[key] = None
        return None
    if b"\x00" in data[:8000]:
        cache[key] = None
        return None
    lines = data.count(b"\n") + (1 if data and not data.endswith(b"\n") else 0)
    cache[key] = lines
    return lines


def count_lines_and_files(commit, cache=None):
    if cache is None:
        cache = {}
    total_lines = 0
    total_files = 0
    ext_lines = defaultdict(int)
    try:
        for blob in commit.tree.traverse():
            if blob.type == "blob":
                total_files += 1
                lines = _blob_lines(blob, cache)
                if lines is None:
                    continue
                total_lines += lines
                ext = os.path.splitext(blob.name)[1].lower()
                if ext in COMMON_EXTENSIONS:
                    ext_lines[ext] += lines
    except Exception:
        pass
    return total_lines, total_files, dict(ext_lines)


def file_sizes_for_commit(commit, cache):
    """[(path, lines), ...] for the non-binary files in a commit's tree.

    Used once, on the newest commit, to surface the largest file and the
    median file size. Runs on a warm cache so it's essentially free.
    """
    out = []
    try:
        for blob in commit.tree.traverse():
            if blob.type == "blob":
                lines = _blob_lines(blob, cache)
                if lines is not None:
                    out.append((blob.path, lines))
    except Exception:
        pass
    return out


def _author_name(commit):
    try:
        return commit.author.name or "Unknown"
    except Exception:
        return "Unknown"


def _streak_and_gap(week_keys):
    """Longest run of consecutive active weeks, and longest gap (in empty
    weeks) between active weeks, from a set of 'YYYY-MM-DD' Monday keys."""
    dates = sorted(datetime.strptime(w, "%Y-%m-%d") for w in week_keys)
    if not dates:
        return 0, 0
    longest_streak = current = 1
    longest_gap = 0
    for i in range(1, len(dates)):
        gap = (dates[i] - dates[i - 1]).days // 7
        if gap == 1:
            current += 1
            longest_streak = max(longest_streak, current)
        else:
            current = 1
            longest_gap = max(longest_gap, gap - 1)
    return longest_streak, longest_gap


def _milestones(data_points):
    """First date each round line-count threshold was crossed (oldest first)."""
    out = []
    for t in (1_000, 10_000, 100_000, 1_000_000):
        for d in data_points:
            if d["lines"] >= t:
                out.append({"threshold": t, "date": d["date"]})
                break
    return out


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


def get_churn(repo, commits, progress=print, on_pair=None):
    """Lines added/removed between consecutive (possibly sampled) commits.

    Uses `git diff --numstat`, which is much faster than building patches
    and parsing +/- lines in Python.

    `on_pair(i, total)` (optional) is called after every diff with the
    1-based pair index and the total number of pairs — used by callers that
    want determinate progress.
    """
    churn = []
    n = len(commits)
    total_pairs = max(0, n - 1)
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
        if on_pair is not None:
            try: on_pair(i, total_pairs)
            except Exception: pass
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


def animated_output_path(static_path):
    """Derive the animated-output path from a static one by inserting
    "_animated" before the extension. Keeps both files in the same folder."""
    base, ext = os.path.splitext(static_path)
    return f"{base}_animated{ext}"


def pick_sample_step(n, target=300):
    """Step size so list[::step] yields ~`target` items.

    Small repos (≤ target commits) → step 1 (every commit).
    Larger repos → step = n // target, evenly spaced across history.
    """
    if n <= target:
        return 1
    return max(1, n // target)


DETAIL_TARGETS = {"Rough": 100, "Standard": 300, "Detailed": 900}


def analyse_repo(repo_path, branch=None, progress=print, target_points=300, progress_pct=None):
    # Sampling traverses every blob in every sampled commit; churn just runs
    # `git diff --numstat` between pairs. Sampling dominates total runtime
    # on every real-world repo I've measured, so we weight it more heavily.
    SAMPLE_WEIGHT = 0.7
    CHURN_WEIGHT  = 1.0 - SAMPLE_WEIGHT

    def _pct(v):
        if progress_pct is None:
            return
        try:
            progress_pct(max(0.0, min(1.0, v)))
        except Exception:
            pass

    _pct(0.0)
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

    # One pass over the full history for author / day / hour distributions —
    # cheap (no tree walk) and gives stats the sampled series can't.
    author_counts = Counter()
    dow_hist = [0] * 7
    hour_hist = [0] * 24
    for c in all_commits:  # oldest first
        author_counts[_author_name(c)] += 1
        dt = datetime.fromtimestamp(c.committed_date)
        dow_hist[dt.weekday()] += 1
        hour_hist[dt.hour] += 1

    # Cumulative unique-author count at each sampled commit, counting every
    # commit in between so the contributor curve doesn't skip people.
    seen_authors = set()
    cursor = 0
    authors_at_sample = []
    for gi in indices:
        while cursor <= gi:
            seen_authors.add(_author_name(all_commits[cursor]))
            cursor += 1
        authors_at_sample.append(len(seen_authors))

    cache = {}  # blob SHA -> line count, shared across every sampled commit

    data_points = []
    biggest_addition = {"delta": 0, "date": "", "message": ""}
    biggest_removal  = {"delta": 0, "date": "", "message": ""}

    for idx, commit in enumerate(sampled):
        date_str = datetime.fromtimestamp(commit.committed_date).strftime("%Y-%m-%d")
        lines, files, ext_lines = count_lines_and_files(commit, cache)
        avg_file_size = round(lines / files, 1) if files > 0 else 0
        msg = commit.message.split("\n")[0][:60]

        data_points.append({
            "date": date_str,
            "lines": lines,
            "files": files,
            "avg_file_size": avg_file_size,
            "ext_lines": ext_lines,
            "authors": authors_at_sample[idx] if idx < len(authors_at_sample) else 0,
            "hash": commit.hexsha[:7],
            "message": msg,
        })

        if idx > 0:
            delta = lines - data_points[idx - 1]["lines"]
            if delta > biggest_addition["delta"]:
                biggest_addition = {"delta": delta, "date": date_str, "message": msg}
            if -delta > biggest_removal["delta"]:
                biggest_removal = {"delta": -delta, "date": date_str, "message": msg}

        if len(sampled):
            _pct(SAMPLE_WEIGHT * ((idx + 1) / len(sampled)))
        if (idx + 1) % 10 == 0 or (idx + 1) == len(sampled):
            pct = (idx + 1) / len(sampled) * 100
            progress(f"  [{idx+1}/{len(sampled)}] {pct:.0f}%  {date_str} — {lines:,} lines, {files} files")

    progress("Calculating churn...")
    churn = get_churn(
        repo, sampled, progress=progress,
        on_pair=lambda i, n: _pct(SAMPLE_WEIGHT + CHURN_WEIGHT * (i / n)) if n else None,
    )
    _pct(1.0)

    final_exts = data_points[-1]["ext_lines"] if data_points else {}
    top_exts = sorted(final_exts, key=lambda e: final_exts[e], reverse=True)[:6]

    first = data_points[0] if data_points else {}
    last  = data_points[-1] if data_points else {}
    lines_now = last.get("lines", 0)

    # Largest / median file in the newest commit (cache is warm → cheap).
    largest_file = {"name": "—", "lines": 0}
    median_file_size = 0
    if sampled:
        file_sizes = file_sizes_for_commit(sampled[-1], cache)
        if file_sizes:
            name, flines = max(file_sizes, key=lambda t: t[1])
            largest_file = {"name": name, "lines": flines}
            sizes = sorted(s for _, s in file_sizes)
            median_file_size = sizes[len(sizes) // 2]

    # Peak (the repo may have shrunk, so "peak" can differ from "now").
    peak_lines = max((d["lines"] for d in data_points), default=0)
    peak_date = next((d["date"] for d in data_points if d["lines"] == peak_lines),
                     last.get("date", ""))

    # Age + average growth rate.
    first_date = first.get("date", "")
    last_date  = last.get("date", "")
    age_days = 0
    if first_date and last_date:
        age_days = (datetime.strptime(last_date, "%Y-%m-%d")
                    - datetime.strptime(first_date, "%Y-%m-%d")).days
    growth_per_day = round((lines_now - first.get("lines", 0)) / age_days, 1) if age_days > 0 else 0

    # Code survival: how much of what was written across sampled spans is still
    # present. Approximate — sampling collapses intermediate churn — but a fair
    # signal of write-then-delete vs. steady accretion.
    total_added   = sum(c["added"] for c in churn)
    total_removed = sum(c["removed"] for c in churn)
    survival_rate = round(100 * lines_now / total_added, 1) if total_added else 0

    # Dominant file type as a share of the codebase.
    dominant_ext, dominant_ext_pct = "—", 0
    if final_exts and lines_now:
        dominant_ext = max(final_exts, key=lambda e: final_exts[e])
        dominant_ext_pct = round(100 * final_exts[dominant_ext] / lines_now, 1)

    # Contributors.
    author_count = len(author_counts)
    top_author, top_author_commits = (author_counts.most_common(1)[0]
                                      if author_counts else ("—", 0))
    top_author_pct = round(100 * top_author_commits / total, 1) if total else 0

    # When the work happens.
    busiest_day = DOW_NAMES[dow_hist.index(max(dow_hist))] if total else "—"
    weekend_pct = round(100 * (dow_hist[5] + dow_hist[6]) / total, 1) if total else 0
    night = sum(hour_hist[h] for h in NIGHT_HOURS)
    night_owl_pct = round(100 * night / total, 1) if total else 0

    longest_streak_weeks, longest_gap_weeks = _streak_and_gap(commit_frequency.keys())
    avg_commits_per_active_week = round(total / len(commit_frequency), 1) if commit_frequency else 0

    return {
        "repo_name": os.path.basename(os.path.abspath(repo_path)),
        "branch": display_branch,
        "total_commits": total,
        "data": data_points,
        "top_exts": top_exts,
        "commit_frequency": commit_frequency,
        "churn": churn,
        "stats": {
            "lines_now":        lines_now,
            "files_now":        last.get("files", 0),
            "lines_start":      first.get("lines", 0),
            "net_change":       lines_now - first.get("lines", 0),
            "avg_file_size":    last.get("avg_file_size", 0),
            "total_commits":    total,
            "active_weeks":     len(commit_frequency),
            "most_active_week": most_active_week,
            "most_active_count":most_active_count,
            "biggest_addition": biggest_addition,
            "biggest_removal":  biggest_removal,
            "peak_lines":       peak_lines,
            "peak_date":        peak_date,
            "first_date":       first_date,
            "last_date":        last_date,
            "age_days":         age_days,
            "growth_per_day":   growth_per_day,
            "total_added":      total_added,
            "total_removed":    total_removed,
            "survival_rate":    survival_rate,
            "milestones":       _milestones(data_points),
            "dominant_ext":     dominant_ext,
            "dominant_ext_pct": dominant_ext_pct,
            "avg_commits_per_active_week": avg_commits_per_active_week,
            "author_count":     author_count,
            "top_author":       top_author,
            "top_author_pct":   top_author_pct,
            "top_author_commits": top_author_commits,
            "busiest_day":      busiest_day,
            "weekend_pct":      weekend_pct,
            "night_owl_pct":    night_owl_pct,
            "dow_hist":         dow_hist,
            "hour_hist":        hour_hist,
            "longest_streak_weeks": longest_streak_weeks,
            "longest_gap_weeks":    longest_gap_weeks,
            "largest_file":     largest_file,
            "median_file_size": median_file_size,
        }
    }


def _render_template(template_name, analysis):
    template_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), template_name)
    with open(template_path, "r", encoding="utf-8") as f:
        template = f.read()

    return (template
        .replace("{{REPO_NAME}}",     analysis["repo_name"])
        .replace("{{BRANCH}}",        analysis["branch"])
        .replace("{{TOTAL_COMMITS}}", f"{analysis['total_commits']:,}")
        .replace("{{DATA_JSON}}",     json.dumps(analysis["data"]))
        .replace("{{FREQ_JSON}}",     json.dumps(analysis["commit_frequency"]))
        .replace("{{TOP_EXTS_JSON}}", json.dumps(analysis["top_exts"]))
        .replace("{{CHURN_JSON}}",    json.dumps(analysis["churn"]))
        .replace("{{STATS_JSON}}",    json.dumps(analysis["stats"]))
    )


def _write_html(html, output_path, progress):
    parent = os.path.dirname(output_path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(html)
    progress(f"Chart saved to: {output_path}")


def generate_html(analysis, output_path, progress=print):
    _write_html(_render_template("template.html", analysis), output_path, progress)


def generate_animated_html(analysis, output_path, progress=print):
    _write_html(_render_template("template_animated.html", analysis), output_path, progress)

if __name__ == "__main__":
    from gui import launch_gui
    launch_gui()
