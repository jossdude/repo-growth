# repo-growth

Visualise how a Git repository has grown over time. Generates a self-contained, interactive HTML chart showing lines of code (by commit number and by date), total files, churn (added/removed), commits per week, average file size, and a stacked breakdown by file type.

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

The Tk GUI opens. Pick a repository folder, optionally enter a branch, choose a **Detail level**, click **Generate**. Progress streams to the log panel. **Open in browser** launches the result when it's done.

The chart is saved inside the target repo at `<repo>/Repo Growth/<repo>_growth_<YYYY-MM-DD>.html` (the folder is created automatically). Use **Save as…** to put it somewhere else.

> Tip: add `Repo Growth/` to that repo's `.gitignore` to keep generated charts out of version control.

## Detail levels

The script samples commits evenly across history and always includes the newest commit, so the right-hand edge reflects current state.

| Level    | Target points | Notes                                                   |
|----------|--------------:|---------------------------------------------------------|
| Rough    | ~100          | Fastest. Coarse line for very large repos.              |
| Standard | ~300          | Balanced default.                                       |
| Detailed | ~1500         | Near-every-commit on small/medium repos; slow on huge.  |

## How it works

For each sampled commit, the script walks the tree and counts non-binary lines and file types. Churn between consecutive sampled commits comes from `git diff --numstat`. Everything is bundled into a single HTML file with vanilla-canvas charts — no JS dependencies, works offline.

## Project layout

- `repo_growth.py` — analysis core (commit traversal, line counts, churn, sampling) and `generate_html`, which substitutes the template.
- `gui.py` — Tk GUI; imports the analysis functions from `repo_growth`.
- `template.html` — the chart page (HTML + CSS + JS). Placeholders like `{{DATA_JSON}}` are filled in by `generate_html`.

Edit `template.html` directly to tweak styling or chart logic — no Python brace-escaping needed.
