#!/usr/bin/env python3
"""
repo_growth.py — Visualise how a Git repository has grown over time.

This module is the analysis core (commit traversal, line counts, churn,
distributions) plus the HTML generators. It has no GUI dependency — launch
the app with:
    python main.py

Pick a repository folder, choose a detail level, click Generate. The chart
is saved inside the repo at <repo>/Repo Growth/<repo>_growth_<date>.html.

Detail levels (target data points): Rough ~100, Standard ~300, Detailed ~900,
Full = every commit (no sampling; slow on large repos). The newest commit is
always included so the right edge of every chart reflects current state.

Requirements:
    pip install gitpython
"""

import base64
import json
import os
import re
import subprocess
import sys
import threading
import time
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


class AnalysisCancelled(Exception):
    """Raised when analyse_repo's cancel_event is set mid-run."""


# How long the analysis may go quiet before the heartbeat says what it is
# stuck on (seconds).
HEARTBEAT_SECS = 15


class _Heartbeat:
    """Reports when the analysis has been quiet for a while.

    A single blob read can block for minutes (cloud-placeholder hydration,
    slow disk) and the loops can't report progress while blocked — so a
    watchdog thread announces what the analysis is stuck on instead of
    leaving the progress log frozen with no explanation.
    """

    def __init__(self, progress, interval=HEARTBEAT_SECS):
        self._progress = progress
        self._interval = interval
        self._label = "starting"
        self._last = time.monotonic()
        self._stop = threading.Event()
        threading.Thread(target=self._watch, daemon=True).start()

    def note(self, label):
        """Record what the analysis is working on right now."""
        self._label = label
        self._last = time.monotonic()

    def stop(self):
        self._stop.set()

    def _watch(self):
        while not self._stop.wait(self._interval):
            quiet = time.monotonic() - self._last
            if quiet >= self._interval:
                try:
                    self._progress(
                        f"  still working on {self._label} ({quiet:.0f}s with no "
                        "progress) — git data may be downloading from cloud storage"
                    )
                except Exception:
                    pass


# Windows flags OneDrive "Files On-Demand" placeholders with this attribute;
# reading such a file blocks while its content downloads.
_FILE_ATTRIBUTE_RECALL_ON_DATA_ACCESS = 0x400000


def cloud_placeholder_count(repo_path):
    """Number of files under .git/objects that are cloud-only placeholders.

    OneDrive/SharePoint Files On-Demand dehydrates synced files; each git
    object read then blocks on a network download, and an analysis touching
    thousands of them can stall for a very long time (seen in practice with a
    repo synced across machines via SharePoint). Returns 0 on platforms
    without the attribute or when the path can't be scanned.
    """
    objects_dir = os.path.join(repo_path, ".git", "objects")
    count = 0
    try:
        for root, _dirs, files in os.walk(objects_dir):
            for name in files:
                try:
                    st = os.stat(os.path.join(root, name), follow_symlinks=False)
                except OSError:
                    continue
                if getattr(st, "st_file_attributes", 0) & _FILE_ATTRIBUTE_RECALL_ON_DATA_ACCESS:
                    count += 1
    except OSError:
        pass
    return count


def normalise_exclude_dirs(names):
    """Clean a folder list into a frozenset of bare folder names.

    Accepts either an iterable or the raw comma/newline-separated string the
    GUI and CLI collect, so "tests/, spec" and ["tests", "spec"] mean the same
    thing.
    """
    if not names:
        return frozenset()
    if isinstance(names, str):
        names = re.split(r"[,\n]", names)
    return frozenset(
        cleaned for cleaned in (n.strip().strip("/\\").strip() for n in names) if cleaned
    )


def _is_excluded(path, exclude_dirs):
    """True when any *folder* in `path` is one of `exclude_dirs`.

    Git tree paths are always '/'-separated with the file name last, so
    dropping the last component means a file named "tests" survives while
    anything inside a folder named "tests" — at any depth — doesn't.
    """
    if not exclude_dirs:
        return False
    return any(part in exclude_dirs for part in path.split("/")[:-1])


def _exclude_pathspec(exclude_dirs):
    """Git pathspec args that drop `exclude_dirs` at any depth, or [] for none.

    Churn is measured by git itself, so it filters via pathspec rather than by
    matching paths in Python: --numstat renders renames as "dir/{old => new}.py",
    and re-parsing that back into paths is easy to get subtly wrong. A leading
    "**/" matches in all directories, root included, so this agrees with
    _is_excluded.
    """
    if not exclude_dirs:
        return []
    return ["--"] + [f":(glob,exclude)**/{name}/**" for name in sorted(exclude_dirs)]


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


def count_lines_and_files(commit, cache=None, on_error=None, exclude_dirs=()):
    if cache is None:
        cache = {}
    total_lines = 0
    total_files = 0
    ext_lines = defaultdict(int)
    try:
        for blob in commit.tree.traverse():
            if blob.type == "blob":
                if _is_excluded(blob.path, exclude_dirs):
                    continue
                total_files += 1
                lines = _blob_lines(blob, cache)
                if lines is None:
                    continue
                total_lines += lines
                ext = os.path.splitext(blob.name)[1].lower()
                if ext in COMMON_EXTENSIONS:
                    ext_lines[ext] += lines
    except Exception as e:
        # A failed tree walk truncates this data point; tell the caller so
        # the dip in the chart is explainable instead of invisible.
        if on_error is not None:
            try:
                on_error(f"tree walk failed at {commit.hexsha[:7]} ({e}); "
                         "line/file counts for this point may be low")
            except Exception:
                pass
    return total_lines, total_files, dict(ext_lines)


def file_sizes_for_commit(commit, cache, exclude_dirs=()):
    """[(path, lines), ...] for the non-binary files in a commit's tree.

    Used once, on the newest commit, to surface the largest file and the
    median file size. Runs on a warm cache so it's essentially free.
    """
    out = []
    try:
        for blob in commit.tree.traverse():
            if blob.type == "blob":
                if _is_excluded(blob.path, exclude_dirs):
                    continue
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


def get_churn(repo, commits, progress=print, on_pair=None, cancel_event=None,
              exclude_dirs=()):
    """Lines added/removed between consecutive (possibly sampled) commits.

    All pairs are diffed by a single `git diff-tree -r --numstat --stdin`
    process instead of one `git diff` process per pair — on a Full run over
    thousands of commits that saves thousands of process launches.

    `on_pair(i, total)` (optional) is called after every pair with the
    1-based pair index and the total number of pairs — used by callers that
    want determinate progress. Setting `cancel_event` aborts the loop with
    AnalysisCancelled.
    """
    if len(commits) < 2:
        return []
    try:
        return _churn_diff_tree(repo, commits, progress, on_pair, cancel_event,
                                exclude_dirs)
    except AnalysisCancelled:
        raise
    except Exception as e:
        progress(f"  batched churn failed ({e}); falling back to per-pair diffs")
        return _churn_per_pair(repo, commits, progress, on_pair, cancel_event,
                               exclude_dirs)


def _churn_entry(curr_commit, added, removed):
    date_str = datetime.fromtimestamp(curr_commit.committed_date).strftime("%Y-%m-%d")
    return {"date": date_str, "added": added, "removed": removed}


def _report_pair(i, total, progress, on_pair):
    if on_pair is not None:
        try: on_pair(i, total)
        except Exception: pass
    if i % 50 == 0:
        progress(f"  churn [{i}/{total}]")


def _churn_diff_tree(repo, commits, progress, on_pair, cancel_event, exclude_dirs=()):
    """Diff every consecutive pair with one `git diff-tree --stdin` process.

    Each input line is `<commit> <parent>` (full SHAs — diff-tree ignores
    abbreviated ones); git echoes the commit id, then numstat lines, in feed
    order, so blocks map back to pairs positionally.
    """
    n = len(commits)
    total_pairs = n - 1
    pairs = "".join(f"{commits[i].hexsha} {commits[i - 1].hexsha}\n" for i in range(1, n))
    proc = subprocess.Popen(
        # -M: detect renames like porcelain `git diff` does (diff-tree is
        # plumbing and leaves them off, which would count every renamed file
        # as a full delete + add).
        [git.Git.GIT_PYTHON_GIT_EXECUTABLE, "diff-tree", "-r", "-M", "--numstat", "--stdin"]
        + _exclude_pathspec(exclude_dirs),
        cwd=repo.working_dir or repo.git_dir,
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
        text=True, encoding="utf-8", errors="replace",
    )

    # Feed stdin from a thread: writing every pair before reading any output
    # can deadlock once the pipe buffers fill on a long history.
    def _feed():
        try:
            proc.stdin.write(pairs)
            proc.stdin.close()
        except OSError:
            pass

    threading.Thread(target=_feed, daemon=True).start()

    churn = []
    added = removed = 0
    pair_no = 0  # 1-based once the first block header arrives
    header = re.compile(r"^[0-9a-f]{40,64}$")
    try:
        for line in proc.stdout:
            if cancel_event is not None and cancel_event.is_set():
                proc.kill()
                raise AnalysisCancelled("analysis cancelled")
            line = line.rstrip("\n")
            if header.match(line):
                if pair_no:
                    churn.append(_churn_entry(commits[pair_no], added, removed))
                    _report_pair(pair_no, total_pairs, progress, on_pair)
                added = removed = 0
                pair_no += 1
                continue
            parts = line.split("\t")
            if len(parts) >= 2:
                a, r = parts[0], parts[1]
                if a.isdigit():
                    added += int(a)
                if r.isdigit():
                    removed += int(r)
        if pair_no:
            churn.append(_churn_entry(commits[pair_no], added, removed))
            _report_pair(pair_no, total_pairs, progress, on_pair)
    finally:
        try:
            proc.stdout.close()
        except OSError:
            pass
        proc.wait()

    if len(churn) != total_pairs:
        raise RuntimeError(f"expected {total_pairs} diff blocks, got {len(churn)}")
    return churn


def _churn_per_pair(repo, commits, progress, on_pair, cancel_event, exclude_dirs=()):
    """One `git diff --numstat` process per pair — slow, but a safe fallback."""
    churn = []
    pathspec = _exclude_pathspec(exclude_dirs)
    n = len(commits)
    for i in range(1, n):
        if cancel_event is not None and cancel_event.is_set():
            raise AnalysisCancelled("analysis cancelled")
        prev, curr = commits[i - 1], commits[i]
        added = removed = 0
        try:
            out = repo.git.diff(prev.hexsha, curr.hexsha, "--numstat", *pathspec)
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
        churn.append(_churn_entry(curr, added, removed))
        _report_pair(i, n - 1, progress, on_pair)
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


# "Full" has an infinite target so pick_sample_step always returns 1 — every
# commit is analysed, no sampling, however large the history.
DETAIL_TARGETS = {"Rough": 100, "Standard": 300, "Detailed": 900, "Full": float("inf")}


def count_commits(repo_path):
    """Commits reachable from HEAD, or None if it can't be read.

    `git rev-list --count HEAD` is a single fast call (no tree walking), so the
    GUI can use it to decide whether to warn before a Full (every-commit) run
    on a large repo without noticeably delaying the click.
    """
    try:
        with git.Repo(repo_path) as repo:
            return int(repo.git.rev_list("--count", "HEAD"))
    except Exception:
        return None


DEFAULT_BRANCH = "main"


def _resolve_rev(repo):
    """(rev_to_chart, name_to_display) — always `main` where the repo has it.

    There's deliberately no branch option: Repo Growth charts main, so the
    result doesn't depend on what happens to be checked out. Repos without a
    main branch (older ones on master, detached HEAD) still have to produce a
    chart, so they fall back to the checkout rather than failing.
    """
    try:
        if any(h.name == DEFAULT_BRANCH for h in repo.heads):
            return DEFAULT_BRANCH, DEFAULT_BRANCH
    except Exception:
        pass  # unreadable refs — fall through to the checked-out branch
    try:
        name = repo.active_branch.name
        return name, name
    except (TypeError, ValueError):
        return "HEAD", f"HEAD ({repo.head.commit.hexsha[:7]})"


def analyse_repo(repo_path, progress=print, target_points=300,
                 progress_pct=None, cancel_event=None, exclude_dirs=()):
    """Analyse the repo and return the chart-ready dict.

    `cancel_event` (a threading.Event) may be set from another thread to
    abort; the analysis then raises AnalysisCancelled at the next commit or
    churn pair boundary.

    `exclude_dirs` names folders to leave out of every chart (see
    normalise_exclude_dirs).
    """
    progress(f"Opening repo at: {repo_path}")

    # OneDrive/SharePoint Files On-Demand can leave git objects as cloud-only
    # placeholders; every read then blocks on a download and the run can look
    # frozen. Say so up front — the stall is otherwise invisible.
    placeholders = cloud_placeholder_count(repo_path)
    if placeholders:
        progress(f"warning: {placeholders:,} git object files are cloud-only placeholders "
                 "(OneDrive Files On-Demand) — the run may pause while they download")

    exclude_dirs = normalise_exclude_dirs(exclude_dirs)
    if exclude_dirs:
        progress("Excluding folders: " + ", ".join(sorted(exclude_dirs)))

    repo = git.Repo(repo_path)
    heartbeat = _Heartbeat(progress)
    try:
        return _analyse(repo, repo_path, progress, target_points,
                        progress_pct, cancel_event, heartbeat, exclude_dirs)
    finally:
        heartbeat.stop()
        # Stop GitPython's persistent cat-file children so .git isn't left
        # with open handles (blocks OneDrive sync and file deletion on Windows).
        repo.close()


def _analyse(repo, repo_path, progress, target_points, progress_pct,
             cancel_event, heartbeat, exclude_dirs):
    # Sampling traverses every blob in every sampled commit; churn diffs all
    # pairs in a single git process. Sampling dominates total runtime on
    # every real-world repo I've measured, so we weight it more heavily.
    SAMPLE_WEIGHT = 0.7
    CHURN_WEIGHT  = 1.0 - SAMPLE_WEIGHT

    def _pct(v):
        if progress_pct is None:
            return
        try:
            progress_pct(max(0.0, min(1.0, v)))
        except Exception:
            pass

    def _check_cancel():
        if cancel_event is not None and cancel_event.is_set():
            raise AnalysisCancelled("analysis cancelled")

    _pct(0.0)

    rev, display_branch = _resolve_rev(repo)
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
        progress(f"Processing all {total} commits")

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
        _check_cancel()
        date_str = datetime.fromtimestamp(commit.committed_date).strftime("%Y-%m-%d")
        heartbeat.note(f"commit {commit.hexsha[:7]} ({date_str})")
        lines, files, ext_lines = count_lines_and_files(
            commit, cache, on_error=lambda msg: progress(f"  warning: {msg}"),
            exclude_dirs=exclude_dirs)
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
    heartbeat.note("churn")

    def _churn_pair(i, n):
        heartbeat.note(f"churn pair {i}/{n}")
        if n:
            _pct(SAMPLE_WEIGHT + CHURN_WEIGHT * (i / n))

    churn = get_churn(repo, sampled, progress=progress, on_pair=_churn_pair,
                      cancel_event=cancel_event, exclude_dirs=exclude_dirs)
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
        file_sizes = file_sizes_for_commit(sampled[-1], cache, exclude_dirs)
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
    # Everything ever written = what the first sample already had plus lines
    # added since; without the first term, a repo that keeps its initial code
    # reports survival above 100%.
    total_written = first.get("lines", 0) + total_added
    survival_rate = round(100 * lines_now / total_written, 1) if total_written else 0

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


def _resource_base():
    """Directory holding bundled data files (templates/ and its fonts/).

    When frozen by PyInstaller, bundled data lives in the temp extraction dir
    exposed as sys._MEIPASS. From source that attribute is absent, so we fall
    back to this file's directory and behave exactly as before.
    """
    return getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))


BASE_DIR = _resource_base()
TEMPLATES_DIR = os.path.join(BASE_DIR, "templates")
FONTS_DIR = os.path.join(TEMPLATES_DIR, "fonts")

# (family, font-weight range, woff2 filename). These are variable fonts, so one
# file per family covers every weight the templates use. Bundled under the SIL
# Open Font License — see templates/fonts/OFL.txt.
_BUNDLED_FONTS = [
    ("Syne",           "400 800", "Syne.woff2"),
    ("JetBrains Mono", "100 800", "JetBrainsMono.woff2"),
]

_font_faces_cache = None


def _font_faces_css():
    """@font-face rules with each woff2 embedded as a base64 data URI.

    Inlining the fonts keeps every generated page a single self-contained file
    that renders identically offline — no request to Google Fonts. Computed
    once and cached. If the font files are missing, returns "" and the page
    falls back to system sans/monospace.
    """
    global _font_faces_cache
    if _font_faces_cache is not None:
        return _font_faces_cache
    rules = []
    for family, weight, filename in _BUNDLED_FONTS:
        try:
            with open(os.path.join(FONTS_DIR, filename), "rb") as f:
                b64 = base64.b64encode(f.read()).decode("ascii")
        except OSError:
            continue
        rules.append(
            "@font-face{font-family:'%s';font-style:normal;font-weight:%s;"
            "font-display:swap;"
            "src:url(data:font/woff2;base64,%s) format('woff2')}"
            % (family, weight, b64)
        )
    _font_faces_cache = "\n  ".join(rules)
    return _font_faces_cache


def _render_template(template_name, analysis):
    template_path = os.path.join(TEMPLATES_DIR, template_name)
    with open(template_path, "r", encoding="utf-8") as f:
        template = f.read()

    return (template
        .replace("{{FONT_FACES}}",    _font_faces_css())
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
