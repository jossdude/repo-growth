<img src="assets/logo.svg" alt="" width="64" height="64">

# repo-growth

[![Latest release](https://img.shields.io/github/v/release/jossdude/repo-growth?color=08865a&label=download)](https://github.com/jossdude/repo-growth/releases/latest)
[![Downloads](https://img.shields.io/github/downloads/jossdude/repo-growth/total?color=08865a)](https://github.com/jossdude/repo-growth/releases)
[![License](https://img.shields.io/github/license/jossdude/repo-growth?color=08865a)](LICENSE)
![Platforms](https://img.shields.io/badge/platform-Windows%20%7C%20macOS%20%7C%20Linux-08865a)

Visualise how a Git repository has grown over time. Generates self-contained, interactive HTML — your choice of a **static dashboard**, an **animated scroll-through story**, or both.

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/images/screenshot-dark.png">
  <img src="docs/images/screenshot.png" alt="The Repo Growth desktop app">
</picture>

*Point it at a local repo, pick a period and a detail level, choose what to create, and click Generate. The window follows your system's light or dark setting.*

The **dashboard** opens with the repo's headline numbers — lines of code, files, commits, contributors — over a full-width lines-of-code chart you can switch between **by date** and **by commit**. Below that it charts total files, average file size, churn (added/removed), commits per week, contributors over time, commits by day of week and hour of day, and a breakdown by file type — a 100%-stacked area showing how the mix shifted over time, paired with a donut of the hovered commit (with an "other" band so the bands account for the real total). Every chart carries a one-line takeaway in plain English ("Tuesday is the busiest day"), and an **At a glance** list holds ~20 summary stats: peak lines, repo age, average growth/day, code-survival rate, dominant file type, contributor count, busiest week/day, night-owl share, longest active streak and gap, largest/median file, biggest single addition and cleanup, and more.

The dashboard is light by default and switches to a dark theme with your system setting.

The **story** replays that history as you scroll — chapter by chapter through lines, files, file types, churn and contributors — each chart drawing itself in behind a glowing playhead while a big number counts up, with milestone pills ("25,000 lines") appearing as the line crosses them. A chapter list on the right jumps between chapters, a **play** button auto-scrolls the whole thing, and the finale sums it up in six big stats.

Works on local clones — including private repos. The analysis runs entirely on your machine, and the generated pages embed their own fonts, so an open chart makes **no network requests** at all. Share or archive a single HTML file that renders identically offline.

## Download

Prefer not to install Python? Grab a ready-to-run build from the [Releases page](../../releases):

- **Windows (installer)** — `RepoGrowth-Setup.exe` — installs for the current user only, so there's no admin prompt. Adds a Start Menu entry (and optionally a desktop shortcut) and a normal uninstall entry in Apps & features.
- **Windows (portable)** — `RepoGrowth-windows.exe` — a single file, nothing installed. Run it from anywhere.
- **macOS** — `RepoGrowth-macos.zip` (unzip to get `RepoGrowth.app`; see the note below)
- **Linux** — `RepoGrowth-linux` (`chmod +x RepoGrowth-linux`, then run it)

These bundle Python and all dependencies, so there's nothing to install — **except Git**, which Repo Growth still calls to read repositories, so it must be installed and on your `PATH`.

> **Windows first launch:** the builds are unsigned, so SmartScreen shows a "Windows protected your PC" warning. Click **More info** → **Run anyway**.

> **macOS first launch:** the app is unsigned, so macOS blocks it the first time. Right-click `RepoGrowth.app` → **Open** → **Open**, or run `xattr -dr com.apple.quarantine RepoGrowth.app`. After that it opens normally.

### Updating

**Help → Check for Updates…** compares your version against the latest release and offers to install it. Repo Growth also checks quietly in the background a couple of seconds after launch, and only speaks up when there's something newer — untick **Help → Check for updates at startup** to stop that.

How the update installs depends on which build you're running:

| Build | What happens |
| --- | --- |
| Windows, installed | Downloads `RepoGrowth-Setup.exe` and runs it silently; the app closes and reopens on the new version. |
| Windows / Linux, portable | Downloads the new program, renames the running one aside, moves the new one into place and restarts. The old copy is deleted on the next launch. |
| macOS | Check only — it tells you what's available and opens the Releases page. |
| Running from source | Not applicable; `git pull`. |

Downloads come from the GitHub Releases API and are refused if the URL or any redirect leaves `github.com`. The portable swap needs write access to the folder the program sits in, so a portable copy in `C:\Program Files` can't update itself — use the installer, or keep the portable build somewhere you own.

## Install

```bash
pip install -r requirements.txt
```

Requires Python 3.8+ and `git` on your `PATH`. The GUI is built with
[CustomTkinter](https://github.com/TomSchimansky/CustomTkinter) and Pillow (both
in `requirements.txt`) on top of Tkinter, which ships with Python on Windows and
macOS; on some Linux distributions it's a separate package (e.g.
`sudo apt install python3-tk`).

## Usage

```bash
python main.py
```

The window opens. **File** holds the same actions as the buttons — Choose Repository (`Ctrl+O`), Generate (`Ctrl+G`), Cancel, and opening either result — and **Help** covers About and updates.

Under **Source**, choose a repository folder and optionally list folders to **Exclude** (comma-separated, matched at any depth — e.g. `tests` to leave test code out of every chart). Under **Range**, pick a **Period**; under **Analysis**, a **Detail** level. Under **Create**, click the **Dashboard** and/or **Story** tiles to choose what to generate (a green outline and tick mark each one that's on), then click **Generate**. The footer shows where the files will be saved and how many commits the branch has.

While it runs, a panel over the form shows which commit it's on, roughly how long is left and a progress bar; **Details** expands the timestamped log, and **Cancel** stops the run at the next commit boundary. When it's done, the footer says how long it took and offers **Open Story**, **Open Dashboard** and **Show in folder**. Your last-used repo and options are remembered between sessions.

**Period** defaults to **All time**, which charts the whole history. **Last day** / **Last week** / **Last month** fill in the **Custom dates** for you; to chart any other window, type the dates (`YYYY-MM-DD`, both inclusive) and the period switches to **Custom**. Leaving one date blank leaves that end open — a start date with no end means "everything since".

Everything in the report then describes that window alone: growth is measured from the first commit inside it, not from the repo's first commit, and the commit count, contributor and churn figures follow the same window.

Files are saved inside the target repo at `<repo>/Repo Growth/<repo>_growth_<YYYY-MM-DD>.html` (the animated one gets an `_animated` suffix). A date range adds its own tag to the filename, so an all-time chart and a last-week chart made on the same day don't overwrite each other. The folder is created automatically.

> Tip: add `Repo Growth/` to that repo's `.gitignore` to keep generated charts out of version control.

### Command line

Pass a repository path to skip the GUI — handy for scripts and scheduled runs:

```bash
python main.py --version                           # version + how this copy updates
python main.py path/to/repo                        # both outputs, Standard detail
python main.py path/to/repo --detail Full --exclude tests
python main.py path/to/repo --no-animated --output charts/growth.html
python main.py path/to/repo --last week                 # just the last 7 days
python main.py path/to/repo --since 2025-01-01 --until 2025-06-30
```

`--detail` accepts `Rough`, `Standard`, `Detailed` or `Full`; `--exclude` takes comma-separated folder names to leave out of every chart, matched at any depth (`--exclude tests,fixtures`); `--output` overrides the static HTML path (the animated file sits next to it with an `_animated` suffix).

`--since` / `--until` (`YYYY-MM-DD`, both inclusive, either one optional) restrict the chart to a date window, and `--last day|week|month` is a shorthand for a window ending today — `month` meaning the last 30 days. A window that contains no commits stops the run with a message rather than producing an empty chart.

Charts always follow **`main`**. Repositories without a `main` branch fall back to whatever is checked out, so older `master` repos still work.

## Detail levels

The script samples commits evenly across history and always includes the newest commit, so the right-hand edge reflects current state.

| Level    | Target points | Notes                                                   |
|----------|--------------:|---------------------------------------------------------|
| Rough    | ~100          | Fastest. Coarse line for very large repos.              |
| Standard | ~300          | Balanced default.                                       |
| Detailed | ~900          | Near-every-commit on small/medium repos; slow on huge.  |
| Full     | every commit  | No sampling at all. Slowest; can take minutes on large repos (the GUI warns first). |

## How it works

For each sampled commit, the script walks the tree and counts non-binary lines and file types. Identical file blobs are counted once and cached by content hash, so unchanged files between samples are nearly free — the main speed-up on large repos. Churn between consecutive sampled commits comes from a single `git diff-tree --numstat --stdin` process fed every pair at once (with rename detection, matching `git diff`), and a single pass over the full history yields the contributor, day-of-week and hour-of-day distributions. Everything is bundled into a single HTML file with vanilla-canvas charts — no JS dependencies, works offline.

If nothing completes for a while, a heartbeat line reports which commit the analysis is stuck on — the usual culprit is git data being downloaded from cloud storage (see Troubleshooting).

## Build a standalone program

The [Releases](../../releases) builds are produced with [PyInstaller](https://pyinstaller.org). To build one yourself:

```bash
pip install -r requirements-dev.txt
pyinstaller repo_growth.spec
```

The result lands in `dist/` — `RepoGrowth.exe` on Windows, `RepoGrowth` on Linux, `RepoGrowth.app` on macOS. PyInstaller only builds for the OS it runs on, so the GitHub Actions workflow ([`.github/workflows/build.yml`](.github/workflows/build.yml)) builds all three when a `v*` tag is pushed and attaches them to the Release.

### Windows installer

`RepoGrowth-Setup.exe` is built from [`installer/repo_growth.iss`](installer/repo_growth.iss) with [Inno Setup 6](https://jrsoftware.org/isinfo.php) (`winget install --id JRSoftware.InnoSetup`). After the PyInstaller build above, from PowerShell:

```bash
& "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe" /DAppVersion=0.2.0 installer\repo_growth.iss
```

That's the per-user winget location; Chocolatey installs to `C:\Program Files (x86)\Inno Setup 6` instead, which is why CI resolves the path with [`.github/find-iscc.sh`](.github/find-iscc.sh) rather than hardcoding it. From Git Bash, prefix the command with `MSYS_NO_PATHCONV=1` or `/DAppVersion=…` gets rewritten into a file path.

The installer lands in `installer/Output/`. CI compiles the script on any pull request that touches it, so a syntax error surfaces before a release rather than during one.

### Versioning

[`version.py`](version.py) is the single source of truth, and the build workflow rewrites it from the tag being built — so a downloaded build always reports the tag it came from, and the updater compares like with like. Keep the checked-in value in step with the tag you're about to push.

## Project layout

```
main.py                          entry point — GUI by default, headless CLI with args
gui.py                           desktop GUI (CustomTkinter); imports the analysis functions
gui_art.py                       the GUI's logo tile, icons and output previews, drawn with Pillow
repo_growth.py                   analysis core + HTML generators (no GUI dependency)
updater.py                       release check + in-place update (no GUI dependency)
version.py                       the version string, stamped from the tag at build time
templates/
  template.html                  static dashboard (HTML + CSS + JS)
  template_animated.html         scroll-driven animated story
  fonts/                         bundled woff2 fonts (embedded at generation time)
assets/
  logo.svg                       the mark — source of truth for the artwork
  logo.ico, logo.png             the same mark as window, taskbar and exe icons
tools/make_icons.py              redraws those two from the mark (needs Pillow)
tools/screenshot_gui.py          captures the GUI in its ready/running/done states (Windows)
repo_growth.spec                 PyInstaller build recipe (standalone program)
installer/repo_growth.iss        Inno Setup recipe (Windows per-user installer)
.github/workflows/build.yml      CI: build + publish binaries on a v* tag
requirements.txt
requirements-dev.txt             build/test tooling (PyInstaller, pytest, Pillow)
LICENSE
```

- `repo_growth.py` — commit traversal, line counts, churn, contributor/time distributions, sampling, plus `generate_html` and `generate_animated_html`, which fill in the templates.
- The templates use placeholders like `{{DATA_JSON}}` that are filled in at generation time. Edit them directly to tweak styling or chart logic — no Python brace-escaping needed.
- `templates/fonts/` holds the Geist and Geist Mono woff2 files; the generator base64-encodes them into each page so the output is a single self-contained, offline file (see [Self-hosted fonts](#self-hosted-fonts)).

## Troubleshooting

- **`ModuleNotFoundError: No module named 'tkinter'`** — install your platform's Tk package (`sudo apt install python3-tk` on Debian/Ubuntu). Tkinter is bundled with the standard Python installers on Windows and macOS.
- **`Error: gitpython is required`** — run `pip install -r requirements.txt`.
- **"That folder doesn't look like a Git repository"** — point Repo Growth at the root of a clone (the folder containing `.git`), not a subfolder.
- **"No commits in … - widen the date range and try again"** — the date range excludes every commit on `main`. Check the dates, remember both bounds are inclusive, or clear the range to chart the whole history.
- **Detailed level is slow on a huge repo** — that's expected; it samples near every commit. Use Standard or Rough for very large histories.
- **"Couldn't replace the running program"** — the portable build can only update itself if it can write to its own folder. Move it somewhere you own (Desktop, Documents) or switch to `RepoGrowth-Setup.exe`, which installs per-user.
- **The run stalls partway through on a OneDrive/SharePoint-synced repo** — "Files On-Demand" can leave git objects as cloud-only placeholders (commits synced from another machine arrive dehydrated), and every read then waits on a download. Repo Growth counts these before starting and warns you; the durable fix is right-clicking the repo folder and choosing **Always keep on this device**.

## Limitations

- Stats are computed from **sampled** commits (see Detail levels), so churn and code-survival figures are close approximations, not exact per-commit totals. The newest commit is always included.
- Binary files are detected heuristically (a NUL byte in the first 8 KB) and excluded from line counts.
- The stacked file-type breakdown tracks a fixed set of common source extensions; everything else is grouped into an "other" band.

## Self-hosted fonts

The pages use the system UI font first — SF Pro on Apple devices, Segoe UI
Variable on Windows — and fall back to [Geist and Geist Mono](https://github.com/vercel/geist-font),
bundled under `templates/fonts/` and embedded into each generated page as base64.
Nothing is fetched from a font CDN, so pages render the same with no internet
connection. Both Geist fonts are licensed under the SIL Open Font License 1.1 —
see [`templates/fonts/OFL.txt`](templates/fonts/OFL.txt).

## License

[MIT](LICENSE) © Joss Redfern. The bundled fonts are licensed separately under the
SIL Open Font License 1.1 — see [NOTICE](NOTICE).
