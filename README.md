# repo-growth

Visualise how a Git repository has grown over time. Generates self-contained, interactive HTML — your choice of a **static dashboard**, an **animated scroll-through story**, or both.

The **static dashboard** charts lines of code (by commit number and by date), total files, average file size, churn (added/removed), commits per week, contributors over time, commits by day of week and hour of day, and a stacked breakdown by file type (with an "other" band so the bands sum to the real total). Above the charts sits a grid of ~20 summary stats: peak lines, repo age, average growth/day, code-survival rate, dominant file type, contributor count, busiest week/day, night-owl share, longest active streak and gap, largest/median file, biggest single addition and cleanup, and more.

The **animated story** replays that history as you scroll — chapter by chapter through lines, files, file types, churn and contributors — with milestone callouts (1k/10k/100k…) flashing in as the line crosses them, a **▶ play** button that auto-scrolls the whole thing, and a count-up stat summary at the end.

Works on local clones — including private repos. Nothing leaves your machine.

## Install

```bash
pip install -r requirements.txt
```

Requires Python 3.8+ and `git` on your `PATH`.

## Usage

```bash
python repo_growth.py
```

The Tk GUI opens. Pick a repository folder, optionally enter a branch, choose a **Detail level**, tick which **Outputs** you want (**Static dashboard** and/or **Animated story**), then click **Generate**. Progress streams to the log panel; **Open Static** / **Open Animated** launch each result when it's done.

Files are saved inside the target repo at `<repo>/Repo Growth/<repo>_growth_<YYYY-MM-DD>.html` (the animated one gets an `_animated` suffix). The folder is created automatically.

> Tip: add `Repo Growth/` to that repo's `.gitignore` to keep generated charts out of version control.

## Detail levels

The script samples commits evenly across history and always includes the newest commit, so the right-hand edge reflects current state.

| Level    | Target points | Notes                                                   |
|----------|--------------:|---------------------------------------------------------|
| Rough    | ~100          | Fastest. Coarse line for very large repos.              |
| Standard | ~300          | Balanced default.                                       |
| Detailed | ~900          | Near-every-commit on small/medium repos; slow on huge.  |

## How it works

For each sampled commit, the script walks the tree and counts non-binary lines and file types. Identical file blobs are counted once and cached by content hash, so unchanged files between samples are nearly free — the main speed-up on large repos. Churn between consecutive sampled commits comes from `git diff --numstat`, and a single pass over the full history yields the contributor, day-of-week and hour-of-day distributions. Everything is bundled into a single HTML file with vanilla-canvas charts — no JS dependencies, works offline.

## Project layout

- `repo_growth.py` — analysis core (commit traversal, line counts, churn, contributor/time distributions, sampling) plus `generate_html` and `generate_animated_html`, which fill in the templates.
- `gui.py` — Tk GUI; imports the analysis functions from `repo_growth`.
- `template.html` — the static dashboard (HTML + CSS + JS). Placeholders like `{{DATA_JSON}}` are filled in at generation time.
- `template_animated.html` — the scroll-driven animated story; same data, same placeholders.

Edit the templates directly to tweak styling or chart logic — no Python brace-escaping needed.
