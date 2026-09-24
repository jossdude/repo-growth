"""CustomTkinter GUI for repo_growth — pick a repo, choose detail level, generate."""

import ctypes
import json
import os
import pathlib
import queue
import re
import subprocess
import sys
import threading
import time
import webbrowser
import tkinter as tk
from datetime import datetime
from tkinter import filedialog, messagebox, font as tkfont

import customtkinter as ctk

import gui_art
import updater
from repo_growth import (
    ASSETS_DIR,
    DATE_FORMAT,
    DETAIL_TARGETS,
    SAMPLE_WEIGHT,
    AnalysisCancelled,
    _resolve_rev,
    analyse_repo,
    animated_output_path,
    cloud_placeholder_count,
    count_commits,
    default_output_path,
    generate_animated_html,
    generate_html,
    preset_range,
    range_slug,
    resolve_range,
)
from version import __version__

# Above this many commits, the Full detail level prompts for confirmation
# because analysing every commit can take minutes on a large history.
FULL_WARN_THRESHOLD = 2000

# How long after launch the silent update check runs. Long enough that the
# window is up and interactive first.
STARTUP_CHECK_DELAY_MS = 2500


def _settings_path():
    base = os.environ.get("APPDATA") or os.path.expanduser("~")
    return os.path.join(base, "RepoGrowth", "settings.json")


def _load_settings():
    """Last-used GUI choices, or {} on first run / unreadable file."""
    try:
        with open(_settings_path(), "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _save_settings(data):
    """Best-effort persist — a failed save must never break a run."""
    path = _settings_path()
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
    except Exception:
        pass


# Every colour is a (light, dark) pair, the form CustomTkinter takes, so the
# window follows the OS appearance without any code of ours. The same tokens
# are used by both HTML templates.
PALETTE = {
    "bg":           ("#f5f5f7", "#000000"),
    "card":         ("#ffffff", "#1c1c1e"),
    "text":         ("#1d1d1f", "#f5f5f7"),
    "secondary":    ("#6e6e73", "#a1a1a6"),
    "tertiary":     ("#86868b", "#8e8e93"),
    "hairline":     ("#e5e5ea", "#2c2c2e"),
    "fill":         ("#e8e8ed", "#2c2c2e"),
    "fill_hover":   ("#dcdce1", "#3a3a3c"),
    "field":        ("#ffffff", "#2c2c2e"),
    "field_border": ("#d2d2d7", "#3a3a3c"),
    # The selected segment of a segmented control, raised off the fill.
    "segment":      ("#ffffff", "#636366"),
    "accent":       ("#08865a", "#32d583"),
    "accent_hover": ("#06744d", "#5ddf9c"),
    "on_accent":    ("#ffffff", "#04150d"),
    # The log's well inside the progress panel.
    "well":         ("#f5f5f7", "#000000"),
}

# Chart palette slots 1-3, for the output previews — the same fixed order the
# templates use, so the thumbnails look like the pages they stand for.
CHART_BLUE   = ("#007aff", "#0a84ff")
CHART_ORANGE = ("#ff9500", "#ff9f0a")
CHART_PURPLE = ("#af52de", "#bf5af2")

# While the progress panel is up, everything behind it is recoloured toward
# black by these factors (light, dark) — Tk has no translucent overlay.
DIM = (0.72, 0.5)


def _dim_hex(colour, factor):
    r, g, b = (int(colour[i:i + 2], 16) for i in (1, 3, 5))
    return "#%02x%02x%02x" % (int(r * factor), int(g * factor), int(b * factor))


# Font preferences, system UI first so the window reads as native: SF Pro on
# macOS, Segoe UI Variable on Windows 11. Geist (bundled for the HTML pages)
# is used when installed; Tk can't load a font file itself, so it can't be the
# guaranteed fallback here the way it is in the pages.
TEXT_CANDIDATES = [
    "SF Pro Text", ".AppleSystemUIFont", "Segoe UI Variable Text", "Segoe UI",
    "Geist", "Inter", "Cantarell", "Ubuntu", "DejaVu Sans", "Helvetica", "Arial",
]
DISPLAY_CANDIDATES = [
    "SF Pro Display", ".AppleSystemUIFont", "Segoe UI Variable Display", "Segoe UI",
    "Geist", "Inter", "Cantarell", "Ubuntu", "DejaVu Sans", "Helvetica", "Arial",
]
# Tk only knows normal and bold, so semibold means picking a family that is
# semibold by name, and falling back to bold.
SEMIBOLD_CANDIDATES = [
    "Segoe UI Variable Text Semibold", "Segoe UI Semibold",
]
MONO_CANDIDATES = [
    "SF Mono", "Menlo", "Cascadia Mono", "Consolas", "Geist Mono",
    "DejaVu Sans Mono", "Courier New",
]


# The mark as an icon file, for the window title bar, its dialogs and the
# taskbar. Tk can't render SVG, so assets/logo.ico and assets/logo.png are
# rasterised from assets/logo.svg by tools/make_icons.py and committed.
ICON_ICO = os.path.join(ASSETS_DIR, "logo.ico")
ICON_PNG = os.path.join(ASSETS_DIR, "logo.png")

# Matches the macOS bundle identifier in repo_growth.spec.
APP_ID = "com.repogrowth.app"


def _claim_taskbar_identity():
    """Make Windows treat us as our own app rather than as its host process.

    Without an explicit AppUserModelID the shell groups the window under the
    icon of whatever launched it — pythonw.exe from a source checkout — so the
    taskbar button showed a different graphic to the title bar. Must run before
    the window exists, and is a no-op everywhere but Windows.
    """
    if sys.platform != "win32":
        return
    try:
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_ID)
    except Exception:
        pass  # an unrecognised shell just means the old grouping — not fatal


def _apply_icon(window, default=True):
    """Put the mark on the title bar, the taskbar and every dialog.

    Windows wants a real .ico; `default=` makes it the icon for Toplevels too.
    Elsewhere Tk takes a PhotoImage, and iconphoto's `default` flag does the
    same job.
    """
    if sys.platform == "win32" and os.path.exists(ICON_ICO):
        try:
            if default:
                window.iconbitmap(default=ICON_ICO)
            else:
                window.iconbitmap(ICON_ICO)
            return
        except tk.TclError:
            pass
    if os.path.exists(ICON_PNG):
        try:
            image = tk.PhotoImage(file=ICON_PNG)
            window.iconphoto(default, image)
            window._icon_image = image  # Tk keeps no reference of its own
        except tk.TclError:
            pass


def _pick_family(root, candidates, fallback):
    available = set(tkfont.families(root))
    for fam in candidates:
        if fam in available:
            return fam
    return fallback


class _Fonts:
    """The type scale, loosely after macOS: 13px body, 11-12px captions."""

    def __init__(self, root):
        text = _pick_family(root, TEXT_CANDIDATES, "TkDefaultFont")
        display = _pick_family(root, DISPLAY_CANDIDATES, text)
        semibold = _pick_family(root, SEMIBOLD_CANDIDATES, None)
        mono = _pick_family(root, MONO_CANDIDATES, "TkFixedFont")

        def strong(size):
            if semibold:
                return ctk.CTkFont(semibold, size)
            return ctk.CTkFont(text, size, "bold")

        self.title    = ctk.CTkFont(display, 26, "bold")
        self.heading  = ctk.CTkFont(display, 17, "bold")
        self.body     = ctk.CTkFont(text, 13)
        self.strong   = strong(13)
        self.small    = ctk.CTkFont(text, 12)
        self.section  = strong(12)
        self.caption  = ctk.CTkFont(text, 11)
        self.button   = strong(13)
        self.segment  = ctk.CTkFont(text, 12)
        self.mono     = ctk.CTkFont(mono, 11)


class _Theme:
    """Remembers which palette token each widget colour came from.

    That's what lets the form dim behind the progress panel: every registered
    colour is re-resolved to a darker variant, then back again.
    """

    def __init__(self):
        self.dimmed = False
        self._paint = {}    # widget -> [dims, {option: token}]
        self._images = {}   # label -> ((normal, dimmed), dims)

    def color(self, token, dims=True):
        pair = PALETTE[token]
        if self.dimmed and dims:
            return tuple(_dim_hex(c, f) for c, f in zip(pair, DIM))
        return pair

    def paint(self, widget, dims=True, **tokens):
        entry = self._paint.setdefault(widget, [dims, {}])
        entry[0] = dims
        entry[1].update(tokens)
        widget.configure(**{opt: self.color(tok, dims) for opt, tok in tokens.items()})
        return widget

    def image(self, label, art, dims=True):
        self._images[label] = (art, dims)
        label.configure(image=art[1] if (self.dimmed and dims) else art[0])

    def set_dimmed(self, on):
        self.dimmed = on
        for widget, (dims, tokens) in self._paint.items():
            if dims:
                widget.configure(**{opt: self.color(tok) for opt, tok in tokens.items()})
        for label, (art, dims) in self._images.items():
            if dims:
                label.configure(image=art[1] if on else art[0])


def _art(light, dark, size):
    """(normal, dimmed) CTkImages from a light- and a dark-theme drawing."""
    normal = ctk.CTkImage(light_image=light, dark_image=dark, size=size)
    dimmed = ctk.CTkImage(
        light_image=gui_art.dim(light, DIM[0]),
        dark_image=gui_art.dim(dark, DIM[1]),
        size=size,
    )
    return normal, dimmed


def _repo_summary(path):
    """(commit count, branch name) for the footer, or None if unreadable.

    Counts the same branch analyse_repo will chart, so the number matches.
    """
    try:
        import git
        with git.Repo(path) as repo:
            rev, name = _resolve_rev(repo)
            return int(repo.git.rev_list("--count", rev)), name
    except Exception:
        return None


def _ellipsize_path(path, limit=46):
    """Shorten a long path from the middle, keeping the drive and the tail."""
    if len(path) <= limit:
        return path
    head = path[: limit // 3]
    tail = path[-(limit - len(head) - 1):]
    return head + "…" + tail


def _about_left(seconds):
    if seconds < 5:
        return "a few seconds left"
    if seconds < 60:
        n = int(round(seconds / 5) * 5) if seconds > 15 else int(round(seconds))
        return f"about {n} seconds left"
    if seconds < 90:
        return "about a minute left"
    return f"about {int(round(seconds / 60))} minutes left"


def _took(seconds):
    if seconds < 1:
        return "Done in under a second"
    if seconds < 60:
        n = int(round(seconds))
        return f"Done in {n} second{'s' if n != 1 else ''}"
    m, s = divmod(int(round(seconds)), 60)
    return f"Done in {m} min {s} s" if s else f"Done in {m} min"


def _reveal(path):
    """Show a file selected in Explorer / Finder, or open its folder."""
    try:
        if sys.platform == "win32":
            subprocess.Popen(["explorer", "/select,", os.path.normpath(path)])
        elif sys.platform == "darwin":
            subprocess.Popen(["open", "-R", path])
        else:
            subprocess.Popen(["xdg-open", os.path.dirname(path)])
    except Exception:
        pass


def _open_file(path):
    """Open a generated page in the default browser.

    Hands the file itself to the OS rather than building a file:/// URL by
    hand: a folder name containing '#' or '%' turned that URL into a
    different, missing file, and the open failed without a word.
    """
    path = os.path.abspath(path)
    if sys.platform == "win32":
        os.startfile(path)
    elif sys.platform == "darwin":
        subprocess.Popen(["open", path])
    elif not webbrowser.open(pathlib.Path(path).as_uri()):
        subprocess.Popen(["xdg-open", path])


def _place_near(win, parent, dx=90, dy=90):
    win.geometry(f"+{parent.winfo_rootx() + dx}+{parent.winfo_rooty() + dy}")


def launch_gui():
    build_gui().mainloop()


def build_gui():
    """Create the main window, ready for mainloop()."""
    # A portable self-update leaves the previous build renamed beside us.
    updater.cleanup_old_build()

    # Before the window exists — the taskbar reads it when the button is made.
    _claim_taskbar_identity()

    ctk.set_appearance_mode("system")

    root = ctk.CTk(fg_color=PALETTE["bg"])
    root.title("Repo Growth")
    root.geometry("760x812")
    root.minsize(680, 800)
    _apply_icon(root)

    fonts = _Fonts(root)
    theme = _Theme()

    settings = _load_settings()
    detail = settings.get("detail", "Standard")
    repo_var     = tk.StringVar(value=settings.get("repo", ""))
    detail_var   = tk.StringVar(value=detail if detail in DETAIL_TARGETS else "Standard")
    exclude_var  = tk.StringVar(value=settings.get("exclude", ""))
    since_var    = tk.StringVar(value=settings.get("since", ""))
    until_var    = tk.StringVar(value=settings.get("until", ""))
    static_var   = tk.BooleanVar(value=bool(settings.get("static", True)))
    animated_var = tk.BooleanVar(value=bool(settings.get("animated", True)))
    updates_var  = tk.BooleanVar(value=bool(settings.get("check_updates", True)))

    def save_settings():
        _save_settings({
            "repo":          repo_var.get().strip(),
            "detail":        detail_var.get(),
            "static":        static_var.get(),
            "animated":      animated_var.get(),
            "exclude":       exclude_var.get().strip(),
            "since":         since_var.get().strip(),
            "until":         until_var.get().strip(),
            "check_updates": updates_var.get(),
        })

    # Paths to the most recently generated files, used by the Open buttons.
    last_output = {"static": "", "animated": ""}

    # The running analysis' cancel event, or None when idle; plus what the
    # progress panel needs to turn raw progress into "commit X of Y".
    current_run = {"cancel": None, "start": 0.0, "total": None, "phase": "sample", "pct": 0.0}

    # "ready", "running" or "done" — which face the footer shows.
    ui_state = {"mode": "ready"}

    # The in-flight update check or download. Worker threads only ever put
    # messages on `msgs`; every Tk call below happens on the main thread.
    update_run = {"busy": False, "cancel": None, "window": None, "bar": None}

    msgs = queue.Queue()

    def log(msg):
        msgs.put(("log", str(msg)))

    def report_pct(v):
        msgs.put(("pct", float(v)))

    # ------------------------------------------------------------ building blocks

    def label(parent, text="", font=None, token="text", **kw):
        widget = ctk.CTkLabel(parent, text=text, font=font or fonts.body,
                              fg_color="transparent", anchor="w", justify="left", **kw)
        return theme.paint(widget, text_color=token)

    def card(parent):
        return theme.paint(ctk.CTkFrame(parent, corner_radius=12, border_width=0), fg_color="card")

    def hairline(parent):
        return theme.paint(ctk.CTkFrame(parent, height=1, corner_radius=0), fg_color="hairline")

    def pill(parent, text, command, primary, dims=True, width=0):
        button = ctk.CTkButton(parent, text=text, command=command, height=32,
                               width=width or 0, corner_radius=16, border_width=0,
                               font=fonts.button)
        if primary:
            return theme.paint(button, dims, fg_color="accent", hover_color="accent_hover",
                               text_color="on_accent", text_color_disabled="on_accent")
        return theme.paint(button, dims, fg_color="fill", hover_color="fill_hover",
                           text_color="text", text_color_disabled="tertiary")

    def link(parent, text, command, dims=True):
        widget = ctk.CTkLabel(parent, text=text, font=fonts.small, fg_color="transparent",
                              cursor="hand2")
        widget.bind("<Button-1>", lambda _e: command())
        return theme.paint(widget, dims, text_color="accent")

    def field(parent, var, width=140):
        entry = ctk.CTkEntry(parent, textvariable=var, width=width, height=30,
                             corner_radius=8, border_width=1, font=fonts.body)
        theme.paint(entry, fg_color="field", border_color="field_border", text_color="text")
        focus_ring(entry, entry)
        return entry

    def focus_ring(entry, framed):
        """Accent border while the field has focus, like a native text field."""
        entry.bind("<FocusIn>", lambda _e: framed.configure(border_color=theme.color("accent")), add="+")
        entry.bind("<FocusOut>", lambda _e: framed.configure(border_color=theme.color("field_border")), add="+")

    def segmented(parent, values, variable, command=None):
        seg = ctk.CTkSegmentedButton(parent, values=values, variable=variable, command=command,
                                     height=28, corner_radius=8, border_width=2,
                                     font=fonts.segment, dynamic_resizing=False)
        return theme.paint(seg, fg_color="fill", selected_color="segment",
                           selected_hover_color="segment", unselected_color="fill",
                           unselected_hover_color="fill_hover", text_color="text",
                           text_color_disabled="tertiary")

    def section(parent, title):
        label(parent, title, fonts.section, "secondary").pack(fill="x", padx=14, pady=(14, 4))
        c = card(parent)
        c.pack(fill="x")
        return c

    def row(parent, title, sub=None, divider=False):
        """One label-left, control-right row of a grouped card; returns the control side."""
        if divider:
            hairline(parent).pack(fill="x", padx=16)
        r = ctk.CTkFrame(parent, fg_color="transparent")
        r.pack(fill="x", padx=16, pady=9)
        r.grid_columnconfigure(0, minsize=150)
        r.grid_columnconfigure(1, weight=1)
        side = ctk.CTkFrame(r, fg_color="transparent")
        side.grid(row=0, column=0, sticky="w")
        label(side, title, fonts.body).pack(anchor="w")
        if sub:
            label(side, sub, fonts.caption, "tertiary").pack(anchor="w")
        control = ctk.CTkFrame(r, fg_color="transparent")
        control.grid(row=0, column=1, sticky="ew")
        return control

    # ------------------------------------------------------------ actions

    def pick_repo():
        if ui_state["mode"] == "running":
            return
        path = filedialog.askdirectory(title="Choose a Git repository")
        if path:
            repo_var.set(os.path.normpath(path))

    PERIODS = [("All time", None), ("Last month", "month"), ("Last week", "week"),
               ("Last day", "day"), ("Custom", "custom")]
    period_var = tk.StringVar(value="All time")

    def set_range(preset):
        """Fill the date fields from a quick range, or clear them for all time."""
        if preset is None:
            since_var.set("")
            until_var.set("")
            return
        since, until = preset_range(preset)
        since_var.set(f"{since:{DATE_FORMAT}}")
        until_var.set(f"{until:{DATE_FORMAT}}")

    def on_period(choice):
        preset = dict(PERIODS)[choice]
        if preset == "custom":
            since_entry.focus_set()
        else:
            set_range(preset)

    def sync_period(*_):
        """Select whichever period the date fields currently describe.

        Typing a date by hand switches to Custom, so the control never claims
        a window the run won't actually use.
        """
        current = (since_var.get().strip(), until_var.get().strip())
        match = "Custom"
        for name, preset in PERIODS:
            if preset is None:
                if current == ("", ""):
                    match = name
            elif preset != "custom":
                since, until = preset_range(preset)
                if current == (f"{since:{DATE_FORMAT}}", f"{until:{DATE_FORMAT}}"):
                    match = name
        if period_var.get() != match:
            period_var.set(match)

    since_var.trace_add("write", sync_period)
    until_var.trace_add("write", sync_period)

    def open_path(key):
        path = last_output.get(key, "")
        if not path:
            return
        if not os.path.exists(path):
            messagebox.showerror(
                "Repo Growth",
                f"Couldn't find the report. It may have been moved or deleted:\n\n{path}")
            return
        try:
            _open_file(path)
        except Exception as e:
            messagebox.showerror("Repo Growth", f"Couldn't open the report:\n\n{path}\n\n{e}")

    def write_log(text):
        stamp = datetime.now().strftime("%H:%M:%S")
        log_box.configure(state="normal")
        for line in text.rstrip("\n").split("\n"):
            log_box.insert("end", f"{stamp}  {line}\n")
        log_box.see("end")
        log_box.configure(state="disabled")

    def run():
        if current_run["cancel"] is not None:
            return  # already analysing — the accelerator can fire while busy
        repo_path = repo_var.get().strip()
        if not repo_path or not os.path.isdir(repo_path):
            messagebox.showerror("Repo Growth", "Choose a valid repository folder first.")
            return
        if not static_var.get() and not animated_var.get():
            messagebox.showerror(
                "Repo Growth",
                "Pick at least one output: Static dashboard or Animated story.",
            )
            return
        try:
            since, until = resolve_range(since_var.get(), until_var.get())
        except ValueError as e:
            messagebox.showerror("Repo Growth", str(e))
            return
        out_static   = default_output_path(repo_path, range_slug(since, until))
        out_animated = animated_output_path(out_static)
        want_static   = static_var.get()
        want_animated = animated_var.get()
        target = DETAIL_TARGETS.get(detail_var.get(), 300)
        if not os.path.isdir(os.path.join(repo_path, ".git")):
            if not messagebox.askyesno(
                "Repo Growth",
                "That folder doesn't look like a Git repository (no .git directory). Continue anyway?",
            ):
                return

        # Full analyses every commit; on a large history that can take minutes,
        # so confirm before starting. (count_commits returns None if it can't
        # read the repo — in that case just proceed and let the run surface it.)
        if target == float("inf"):
            n = count_commits(repo_path)
            if n is not None and n > FULL_WARN_THRESHOLD:
                if not messagebox.askyesno(
                    "Repo Growth",
                    "Full detail analyses every commit, which may take several "
                    "minutes on a repository this large. Continue?",
                ):
                    return

        # Cloud-only git objects (OneDrive Files On-Demand) each force a
        # network download when read; the run can stall for a long time.
        # Warn before starting so the stall isn't a mystery.
        placeholders = cloud_placeholder_count(repo_path)
        if placeholders:
            if not messagebox.askyesno(
                "Repo Growth",
                f"{placeholders:,} git object files in this repository are cloud-only "
                "placeholders (OneDrive/SharePoint Files On-Demand). The analysis may "
                "pause while each one downloads.\n\n"
                "Tip: right-click the repository folder and choose \"Always keep on "
                "this device\" to stop this recurring.\n\nContinue anyway?",
            ):
                return

        exclude = exclude_var.get().strip()

        save_settings()

        cancel_event = threading.Event()
        current_run.update(cancel=cancel_event, start=time.monotonic(),
                           total=None, phase="sample", pct=0.0)
        last_output.update(static="", animated="")
        show_running(os.path.basename(os.path.abspath(repo_path)))

        def worker():
            try:
                analysis = analyse_repo(
                    repo_path, progress=log, target_points=target,
                    progress_pct=report_pct, cancel_event=cancel_event,
                    exclude_dirs=exclude, since=since, until=until,
                )
                produced = {"static": "", "animated": ""}
                if want_static:
                    generate_html(analysis, out_static, progress=log)
                    produced["static"] = out_static
                if want_animated:
                    generate_animated_html(analysis, out_animated, progress=log)
                    produced["animated"] = out_animated
                msgs.put(("done", produced))
            except AnalysisCancelled:
                msgs.put(("cancelled", None))
            except Exception as e:
                msgs.put(("error", str(e)))

        threading.Thread(target=worker, daemon=True).start()

    def cancel_run():
        cancel_event = current_run.get("cancel")
        if cancel_event is not None and not cancel_event.is_set():
            cancel_event.set()
            cancel_btn.configure(state="disabled")
            step_label.configure(text="Cancelling — finishing the current step…")
            write_log("Cancelling — waiting for the current step to finish...")
        sync_menus()

    # What sync_menus last wrote, so it can skip writes that change nothing.
    # entryconfigure redraws an open menu on Windows, and poll() calls this
    # ten times a second — writing unconditionally makes the File menu flicker
    # for as long as it's held open.
    menu_state = {}

    def sync_menus():
        """Mirror what the window currently offers onto the File menu."""
        running = current_run["cancel"] is not None
        cancelling = running and current_run["cancel"].is_set()
        for entry_label, enabled in (
            ("Generate",               not running),
            ("Cancel Analysis",        running and not cancelling),
            ("Open Static Dashboard",  bool(last_output["static"])),
            ("Open Animated Story",    bool(last_output["animated"])),
        ):
            state = "normal" if enabled else "disabled"
            if menu_state.get(entry_label) != state:
                menu_state[entry_label] = state
                file_menu.entryconfigure(entry_label, state=state)

    # ------------------------------------------------------------ progress text

    def note_log(msg):
        """Pick the progress panel's facts out of the analysis log."""
        m = (re.search(r"-> ([\d,]+) data points", msg)
             or re.search(r"Processing all ([\d,]+) commits", msg))
        if m:
            current_run["total"] = int(m.group(1).replace(",", ""))
        elif msg.startswith("Calculating churn"):
            current_run["phase"] = "churn"
        elif msg.startswith("Chart saved to"):
            current_run["phase"] = "write"

    def step_text():
        pct = current_run["pct"]
        elapsed = time.monotonic() - current_run["start"]
        eta = ""
        if 0.02 <= pct < 1.0 and elapsed >= 1.0:
            eta = _about_left(elapsed * (1.0 - pct) / pct)
        total, phase = current_run["total"], current_run["phase"]
        if phase == "sample" and total:
            done = min(total, max(1, round(pct / SAMPLE_WEIGHT * total)))
            head = f"Commit {done:,} of {total:,}"
        elif phase == "churn":
            head = "Comparing commits"
        elif phase == "write" or pct >= 1.0:
            head = "Writing the pages"
        else:
            head = "Reading the history"
        return f"{head} · {eta}" if eta else head

    def show_pct(pct):
        current_run["pct"] = pct
        progress.set(pct)
        pct_label.configure(text=f"{int(pct * 100)}%")
        if not current_run["cancel"] or not current_run["cancel"].is_set():
            step_label.configure(text=step_text())

    # ------------------------------------------------------------ the three states

    inputs = []   # everything the user can change, disabled while running

    def set_inputs(state):
        for widget in inputs:
            widget.configure(state=state)

    def show_running(repo_name):
        ui_state["mode"] = "running"
        log_box.configure(state="normal")
        log_box.delete("1.0", "end")
        log_box.configure(state="disabled")
        if len(repo_name) > 30:
            repo_name = repo_name[:29] + "…"
        title_label.configure(text=f"Analysing {repo_name}")
        step_label.configure(text="Reading the history")
        progress.set(0)
        pct_label.configure(text="0%")
        cancel_btn.configure(state="normal")
        set_inputs("disabled")
        generate_btn.configure(state="disabled")
        theme.set_dimmed(True)
        panel.place(relx=0.5, rely=0.47, anchor="center")
        panel.lift()
        sync_menus()

    def hide_running():
        panel.place_forget()
        theme.set_dimmed(False)
        set_inputs("normal")
        generate_btn.configure(state="normal")
        current_run["cancel"] = None

    def show_ready(*_):
        if ui_state["mode"] == "running":
            return
        ui_state["mode"] = "ready"
        tick.pack_forget()
        done_links.pack_forget()
        status_sub.pack(side="left")
        status_title.configure(text="Ready")
        for b in (open_story_btn, open_dash_btn):
            b.pack_forget()
        generate_btn.pack(side="right")
        refresh_summary()

    def show_done(seconds):
        ui_state["mode"] = "done"
        tick.pack(side="left", padx=(0, 10), before=status_texts)
        status_title.configure(text=_took(seconds))
        status_sub.pack_forget()
        done_links.pack(side="left")
        generate_btn.pack_forget()
        # The dashboard is the primary result; with only one output, that one
        # takes the primary style.
        dash, story = last_output["static"], last_output["animated"]
        theme.paint(open_story_btn, **(_PRIMARY if not dash else _SECONDARY))
        if dash:
            open_dash_btn.pack(side="right")
        if story:
            open_story_btn.pack(side="right", padx=(0, 8) if dash else 0)

    _PRIMARY = dict(fg_color="accent", hover_color="accent_hover",
                    text_color="on_accent", text_color_disabled="on_accent")
    _SECONDARY = dict(fg_color="fill", hover_color="fill_hover",
                      text_color="text", text_color_disabled="tertiary")

    def show_in_folder():
        path = last_output["static"] or last_output["animated"]
        if path and os.path.exists(path):
            _reveal(path)

    # Footer status line — refreshed off the UI thread, since counting commits
    # on a large repo can take a moment. The token drops stale answers.
    summary = {"token": 0}

    def refresh_summary(*_):
        summary["token"] += 1
        token = summary["token"]
        root.after(300, lambda: start_summary(token))

    def start_summary(token):
        if token != summary["token"] or ui_state["mode"] != "ready":
            return
        path = repo_var.get().strip()
        if not path:
            status_sub.configure(text="Choose a repository to begin")
            return
        if not os.path.isdir(path):
            status_sub.configure(text="That folder doesn't exist")
            return
        saves = _ellipsize_path(os.path.join(path, "Repo Growth") + os.sep)
        status_sub.configure(text=f"Saves to {saves}")

        def worker():
            msgs.put(("summary", (token, saves, _repo_summary(path))))

        threading.Thread(target=worker, daemon=True).start()

    def on_summary(token, saves, info):
        if token != summary["token"] or ui_state["mode"] != "ready":
            return
        if info is None:
            status_sub.configure(text=f"Saves to {saves} · not a Git repository?")
            return
        count, branch = info
        status_sub.configure(
            text=f"Saves to {saves} · {count:,} commit{'s' if count != 1 else ''} on {branch}")

    # ------------------------------------------------------------ updates

    def check_for_updates(manual=True):
        """Ask GitHub what the latest release is, off the UI thread."""
        if update_run["busy"]:
            if manual:
                messagebox.showinfo("Repo Growth", "An update check is already running.")
            return
        update_run["busy"] = True
        if manual:
            write_log("Checking for updates...")

        def worker():
            try:
                msgs.put(("update_found", (updater.fetch_latest(), manual)))
            except Exception as e:
                msgs.put(("update_failed", (str(e), manual)))

        threading.Thread(target=worker, daemon=True).start()

    def on_update_found(info, manual):
        update_run["busy"] = False
        if not updater.is_newer(info["version"]):
            if manual:
                messagebox.showinfo(
                    "Repo Growth",
                    f"You're up to date — {__version__} is the latest version.",
                )
            return

        headline = (
            f"Repo Growth {info['version']} is available.\n"
            f"You have {__version__}."
        )
        mode = updater.update_mode()
        asset = info["assets"].get(updater.asset_name(mode) or "")

        # macOS bundles, source checkouts, and releases missing our asset all
        # fall back to the download page.
        if asset is None:
            if messagebox.askyesno("Repo Growth", headline + "\n\nOpen the download page?"):
                webbrowser.open(info["page"])
            return

        if current_run["cancel"] is not None:
            messagebox.showinfo(
                "Repo Growth",
                headline + "\n\nInstalling restarts the app, so finish or cancel "
                "the current analysis first, then check again.",
            )
            return

        if messagebox.askyesno(
            "Repo Growth",
            headline + "\n\nDownload and install it now? Repo Growth will restart.",
        ):
            start_download(asset, mode)

    def dialog(title):
        """A themed Toplevel with our icon rather than CustomTkinter's."""
        win = ctk.CTkToplevel(root)
        win.title(title)
        win.resizable(False, False)
        win.transient(root)
        theme.paint(win, False, fg_color="bg")
        # CTkToplevel sets its own icon shortly after opening unless one has
        # been set explicitly.
        _apply_icon(win, default=False)
        return win

    def grab(win):
        """grab_set once the window is actually mapped — before that it fails."""
        def attempt():
            try:
                win.grab_set()
            except tk.TclError:
                win.after(50, attempt)
        win.after(10, attempt)

    def start_download(asset, mode):
        cancel = threading.Event()

        win = dialog("Updating Repo Growth")
        _place_near(win, root, 110, 150)
        win.protocol("WM_DELETE_WINDOW", cancel.set)

        body = ctk.CTkFrame(win, fg_color="transparent")
        body.pack(fill="both", expand=True, padx=26, pady=22)
        label(body, f"Downloading {asset.get('name', 'update')}…", fonts.strong).pack(anchor="w")
        label(body, "Repo Growth will restart once it's installed.", fonts.small, "secondary") \
            .pack(anchor="w", pady=(2, 0))
        bar = ctk.CTkProgressBar(body, width=360, height=4, corner_radius=2)
        theme.paint(bar, False, fg_color="fill", progress_color="accent")
        bar.set(0)
        bar.pack(fill="x", pady=(16, 16))
        pill(body, "Cancel", cancel.set, primary=False, dims=False, width=88).pack(anchor="e")
        grab(win)

        update_run.update(busy=True, cancel=cancel, window=win, bar=bar)

        def worker():
            try:
                path = updater.download_asset(
                    asset,
                    progress=lambda f: msgs.put(("update_pct", f)),
                    cancel_event=cancel,
                )
                msgs.put(("update_ready", (path, mode)))
            except Exception as e:
                # A cancel raises too; that isn't worth an error dialog.
                msgs.put(("update_failed", (None, False) if cancel.is_set() else (str(e), True)))

        threading.Thread(target=worker, daemon=True).start()

    def close_update_window():
        win = update_run.get("window")
        if win is not None:
            try:
                win.grab_release()
                win.destroy()
            except tk.TclError:
                pass
        update_run.update(busy=False, cancel=None, window=None, bar=None)

    def on_update_ready(path, mode):
        close_update_window()
        try:
            updater.apply_update(path, mode)
        except Exception as e:
            messagebox.showerror("Repo Growth", str(e))
            return
        # Quit hard and now: the installer is waiting to replace our files,
        # and in portable mode the new build is already starting up.
        root.destroy()
        os._exit(0)

    def on_update_failed(message, manual):
        close_update_window()
        if message and manual:
            messagebox.showerror("Repo Growth", message)
        elif message:
            write_log(f"Update check failed: {message}")

    def show_about():
        win = dialog("About Repo Growth")
        _place_near(win, root)

        body = ctk.CTkFrame(win, fg_color="transparent")
        body.pack(fill="both", expand=True, padx=30, pady=26)

        mark = ctk.CTkLabel(body, text="", image=logo_small[0])
        mark.pack(anchor="w")
        label(body, "Repo Growth", fonts.heading).pack(anchor="w", pady=(12, 0))
        label(body, f"Version {__version__}", fonts.small, "secondary").pack(anchor="w", pady=(0, 14))
        label(
            body,
            "See how a Git repository has grown over time.\n"
            "Everything runs on this computer — the pages it writes\n"
            "make no network requests at all.",
            fonts.body,
        ).pack(anchor="w")
        link(body, updater.PROJECT_PAGE, lambda: webbrowser.open(updater.PROJECT_PAGE), dims=False) \
            .pack(anchor="w", pady=(12, 22))

        buttons = ctk.CTkFrame(body, fg_color="transparent")
        buttons.pack(anchor="e")
        pill(buttons, "Check for Updates", lambda: (win.destroy(), check_for_updates(True)),
             primary=False, dims=False).pack(side="left", padx=(0, 8))
        pill(buttons, "Close", win.destroy, primary=True, dims=False, width=80).pack(side="left")

    def poll():
        try:
            while True:
                kind, payload = msgs.get_nowait()
                if kind == "log":
                    write_log(payload)
                    note_log(payload)
                elif kind == "pct":
                    show_pct(payload)
                elif kind == "done":
                    seconds = time.monotonic() - current_run["start"]
                    show_pct(1.0)
                    last_output["static"]   = payload.get("static", "")
                    last_output["animated"] = payload.get("animated", "")
                    parts = [p for p in (last_output["static"], last_output["animated"]) if p]
                    write_log("Done — saved to:\n  " + "\n  ".join(parts))
                    hide_running()
                    show_done(seconds)
                elif kind == "cancelled":
                    write_log("Cancelled.")
                    hide_running()
                    show_ready()
                    status_title.configure(text="Cancelled")
                elif kind == "error":
                    write_log(f"ERROR: {payload}")
                    hide_running()
                    show_ready()
                    status_title.configure(text="Something went wrong")
                    messagebox.showerror("Repo Growth", payload)
                elif kind == "summary":
                    on_summary(*payload)
                elif kind == "update_found":
                    on_update_found(*payload)
                elif kind == "update_pct":
                    bar = update_run.get("bar")
                    if bar is not None:
                        bar.set(payload)
                elif kind == "update_ready":
                    on_update_ready(*payload)
                elif kind == "update_failed":
                    on_update_failed(*payload)
        except queue.Empty:
            pass
        # The ETA ticks down between progress callbacks too.
        if current_run["cancel"] is not None and not current_run["cancel"].is_set():
            step_label.configure(text=step_text())
        sync_menus()
        root.after(100, poll)

    # ------------------------------------------------------------ artwork

    def tile_art(size):
        img = gui_art.mark_tile(size)
        return _art(img, gui_art.mark_tile(size, border=False), (size, size))

    logo_large = tile_art(56)
    logo_small = tile_art(40)
    folder = _art(gui_art.folder_icon(16, PALETTE["secondary"][0]),
                  gui_art.folder_icon(16, PALETTE["secondary"][1]), (16, 16))
    checks = {
        on: _art(gui_art.check_circle(20, on, PALETTE["accent"][0], PALETTE["field_border"][0],
                                      PALETTE["on_accent"][0]),
                 gui_art.check_circle(20, on, PALETTE["accent"][1], PALETTE["field_border"][1],
                                      PALETTE["on_accent"][1]), (20, 20))
        for on in (True, False)
    }
    done_tick = _art(gui_art.tick_badge(22, PALETTE["accent"][0], PALETTE["on_accent"][0]),
                     gui_art.tick_badge(22, PALETTE["accent"][1], PALETTE["on_accent"][1]), (22, 22))
    PREVIEW = (92, 60)
    previews = {
        "static": _art(
            gui_art.dashboard_preview(*PREVIEW, False, CHART_BLUE[0], CHART_ORANGE[0], CHART_PURPLE[0]),
            gui_art.dashboard_preview(*PREVIEW, True, CHART_BLUE[1], CHART_ORANGE[1], CHART_PURPLE[1]),
            PREVIEW),
        # The story itself is always dark, so its preview is too.
        "animated": _art(gui_art.story_preview(*PREVIEW, CHART_BLUE[1]),
                         gui_art.story_preview(*PREVIEW, CHART_BLUE[1]), PREVIEW),
    }

    # ------------------------------------------------------------ footer
    # Packed before the form so it keeps its place when the window is short.

    footer = theme.paint(ctk.CTkFrame(root, corner_radius=0, height=68), fg_color="card")
    footer.pack(side="bottom", fill="x")
    footer.pack_propagate(False)
    hairline(root).pack(side="bottom", fill="x")

    status = ctk.CTkFrame(footer, fg_color="transparent")
    status.pack(side="left", padx=(28, 0))
    tick = ctk.CTkLabel(status, text="")
    theme.image(tick, done_tick)
    status_texts = ctk.CTkFrame(status, fg_color="transparent")
    status_texts.pack(side="left")
    status_title = label(status_texts, "Ready", fonts.strong)
    status_title.pack(anchor="w")
    status_line = ctk.CTkFrame(status_texts, fg_color="transparent")
    status_line.pack(anchor="w")
    status_sub = label(status_line, "", fonts.small, "secondary")
    status_sub.pack(side="left")
    done_links = ctk.CTkFrame(status_line, fg_color="transparent")
    link(done_links, "Show in folder", show_in_folder).pack(side="left")
    label(done_links, "  ·  ", fonts.small, "tertiary").pack(side="left")
    link(done_links, "Generate again", run).pack(side="left")

    actions = ctk.CTkFrame(footer, fg_color="transparent")
    actions.pack(side="right", padx=(0, 28))
    generate_btn = pill(actions, "Generate", run, primary=True, width=112)
    generate_btn.pack(side="right")
    open_dash_btn = pill(actions, "Open Dashboard", lambda: open_path("static"), primary=True)
    open_story_btn = pill(actions, "Open Story", lambda: open_path("animated"), primary=False)

    # ------------------------------------------------------------ form

    body = ctk.CTkFrame(root, fg_color="transparent")
    body.pack(fill="both", expand=True, padx=28, pady=(22, 16))

    header = ctk.CTkFrame(body, fg_color="transparent")
    header.pack(fill="x")
    logo = ctk.CTkLabel(header, text="")
    theme.image(logo, logo_large)
    logo.pack(side="left", padx=(0, 16))
    header_text = ctk.CTkFrame(header, fg_color="transparent")
    header_text.pack(side="left", fill="x")
    label(header_text, "Repo Growth", fonts.title).pack(anchor="w")
    label(header_text, "See how a Git repository has grown over time. Runs entirely on this computer.",
          fonts.body, "secondary").pack(anchor="w")

    # Source
    src = section(body, "Source")
    ctl = row(src, "Repository")
    ctl.grid_columnconfigure(0, weight=1)
    path_box = theme.paint(ctk.CTkFrame(ctl, corner_radius=8, border_width=1, height=30),
                           fg_color="field", border_color="field_border")
    path_box.grid(row=0, column=0, sticky="ew")
    folder_label = ctk.CTkLabel(path_box, text="", width=16)
    theme.image(folder_label, folder)
    folder_label.pack(side="left", padx=(9, 0))
    repo_entry = ctk.CTkEntry(path_box, textvariable=repo_var, height=26, border_width=0,
                              corner_radius=6, font=fonts.body)
    theme.paint(repo_entry, fg_color="field", text_color="text")
    repo_entry.pack(side="left", fill="x", expand=True, padx=(2, 3), pady=2)
    focus_ring(repo_entry, path_box)
    choose_btn = pill(ctl, "Choose…", pick_repo, primary=False, width=88)
    choose_btn.configure(height=30, corner_radius=15)
    choose_btn.grid(row=0, column=1, padx=(8, 0))

    ctl = row(src, "Exclude folders", "Comma-separated, any depth", divider=True)
    exclude_entry = field(ctl, exclude_var)
    exclude_entry.pack(fill="x")

    # Range
    rng = section(body, "Range")
    ctl = row(rng, "Period")
    period_seg = segmented(ctl, [name for name, _ in PERIODS], period_var, on_period)
    period_seg.pack(fill="x")
    ctl = row(rng, "Custom dates", "Either side can be left open", divider=True)
    since_entry = field(ctl, since_var, width=118)
    since_entry.pack(side="left")
    label(ctl, "to", fonts.body, "secondary").pack(side="left", padx=10)
    until_entry = field(ctl, until_var, width=118)
    until_entry.pack(side="left")
    label(ctl, "YYYY-MM-DD", fonts.caption, "tertiary").pack(side="left", padx=(12, 0))
    sync_period()

    # Analysis
    ana = section(body, "Analysis")
    ctl = row(ana, "Detail")
    detail_seg = segmented(ctl, list(DETAIL_TARGETS.keys()), detail_var,
                           lambda _v: update_detail_caption())
    detail_seg.pack(fill="x")
    detail_caption = label(ctl, "", fonts.caption, "secondary")
    detail_caption.pack(anchor="w", pady=(6, 0))

    def update_detail_caption(*_):
        level = detail_var.get()
        target = DETAIL_TARGETS.get(level, 300)
        text = {
            "Rough":    f"About {target:,} points · fastest",
            "Standard": f"About {target:,} points · balanced",
            "Detailed": f"About {target:,} points · finer curves, slower",
        }.get(level, "Every commit · slowest on a long history")
        detail_caption.configure(text=text)

    detail_var.trace_add("write", update_detail_caption)
    update_detail_caption()

    # Create
    label(body, "Create", fonts.section, "secondary").pack(fill="x", padx=14, pady=(14, 4))
    tiles_row = ctk.CTkFrame(body, fg_color="transparent")
    tiles_row.pack(fill="x")
    tiles_row.grid_columnconfigure((0, 1), weight=1, uniform="tiles")

    def output_tile(column, key, var, title, sub):
        tile = theme.paint(ctk.CTkFrame(tiles_row, corner_radius=12, border_width=2),
                           fg_color="card", border_color="hairline")
        tile.grid(row=0, column=column, sticky="ew", padx=(0, 6) if column == 0 else (6, 0))
        tile.grid_columnconfigure(1, weight=1)
        preview = ctk.CTkLabel(tile, text="")
        theme.image(preview, previews[key])
        preview.grid(row=0, column=0, rowspan=2, padx=(12, 12), pady=12)
        label(tile, title, fonts.strong).grid(row=0, column=1, sticky="sw", pady=(0, 0))
        label(tile, sub, fonts.small, "secondary").grid(row=1, column=1, sticky="nw")
        check = ctk.CTkLabel(tile, text="")
        check.grid(row=0, column=2, rowspan=2, sticky="ne", padx=12, pady=12)

        def refresh(*_):
            on = var.get()
            theme.image(check, checks[on])
            theme.paint(tile, border_color="accent" if on else "hairline")

        def toggle(_e=None):
            if ui_state["mode"] != "running":
                var.set(not var.get())

        def bind_all(widget):
            widget.bind("<Button-1>", toggle)
            try:
                widget.configure(cursor="hand2")
            except (tk.TclError, ValueError):
                pass
            for child in widget.winfo_children():
                bind_all(child)

        bind_all(tile)
        var.trace_add("write", refresh)
        refresh()

    output_tile(0, "static", static_var, "Dashboard", "Every chart on one page")
    output_tile(1, "animated", animated_var, "Story", "Scroll-through replay")

    inputs.extend([repo_entry, choose_btn, exclude_entry, period_seg,
                   since_entry, until_entry, detail_seg])

    # ------------------------------------------------------------ progress panel
    # Placed over the dimmed form while a run is going. Its colours are
    # registered with dims=False so it stays bright.

    panel = theme.paint(ctk.CTkFrame(root, corner_radius=14, border_width=1), False,
                        fg_color="card", border_color="hairline")
    inner = ctk.CTkFrame(panel, fg_color="transparent")
    inner.pack(fill="both", expand=True, padx=26, pady=24)
    # Holds the panel at a steady width; CustomTkinter won't take one in place().
    ctk.CTkFrame(inner, width=408, height=0, fg_color="transparent").pack()
    head = ctk.CTkFrame(inner, fg_color="transparent")
    head.pack(fill="x")
    ctk.CTkLabel(head, text="", image=logo_small[0]).pack(side="left", padx=(0, 14))
    head_text = ctk.CTkFrame(head, fg_color="transparent")
    head_text.pack(side="left", fill="x", expand=True)
    title_label = theme.paint(ctk.CTkLabel(head_text, text="", font=fonts.heading, anchor="w",
                                           fg_color="transparent"), False, text_color="text")
    title_label.pack(anchor="w", fill="x")
    step_label = theme.paint(ctk.CTkLabel(head_text, text="", font=fonts.small, anchor="w",
                                          fg_color="transparent"), False, text_color="secondary")
    step_label.pack(anchor="w", fill="x")

    bar_row = ctk.CTkFrame(inner, fg_color="transparent")
    bar_row.pack(fill="x", pady=(18, 0))
    pct_label = theme.paint(ctk.CTkLabel(bar_row, text="0%", font=fonts.small, width=40, anchor="e",
                                         fg_color="transparent"), False, text_color="secondary")
    pct_label.pack(side="right")
    progress = theme.paint(ctk.CTkProgressBar(bar_row, height=4, corner_radius=2), False,
                           fg_color="fill", progress_color="accent")
    progress.set(0)
    progress.pack(side="left", fill="x", expand=True, padx=(0, 10))

    foot = ctk.CTkFrame(inner, fg_color="transparent")
    foot.pack(fill="x", pady=(16, 0))
    details_open = {"on": False}

    def toggle_details():
        details_open["on"] = not details_open["on"]
        details_btn.configure(text=("⌄  Details" if details_open["on"] else "›  Details"))
        if details_open["on"]:
            log_box.pack(fill="x", pady=(12, 0))
        else:
            log_box.pack_forget()

    details_btn = theme.paint(
        ctk.CTkButton(foot, text="›  Details", command=toggle_details, width=0, height=28,
                      corner_radius=8, border_width=0, font=fonts.small, anchor="w"),
        False, fg_color="card", hover_color="fill", text_color="secondary")
    details_btn.pack(side="left")
    cancel_btn = pill(foot, "Cancel", cancel_run, primary=False, dims=False, width=88)
    cancel_btn.pack(side="right")
    log_box = theme.paint(
        ctk.CTkTextbox(inner, height=150, corner_radius=8, border_width=0, font=fonts.mono,
                       wrap="word", state="disabled"),
        False, fg_color="well", text_color="secondary")

    # ------------------------------------------------------------ menus
    # Built last so sync_menus has everything it mirrors. Native menus follow
    # the OS look on their own, so they get no colours of ours.

    menubar = tk.Menu(root, tearoff=0)

    file_menu = tk.Menu(menubar, tearoff=0)
    file_menu.add_command(label="Choose Repository…", accelerator="Ctrl+O", command=pick_repo)
    file_menu.add_separator()
    file_menu.add_command(label="Generate", accelerator="Ctrl+G", command=run)
    file_menu.add_command(label="Cancel Analysis", command=cancel_run, state="disabled")
    file_menu.add_separator()
    file_menu.add_command(label="Open Static Dashboard", state="disabled",
                          command=lambda: open_path("static"))
    file_menu.add_command(label="Open Animated Story", state="disabled",
                          command=lambda: open_path("animated"))
    file_menu.add_separator()
    file_menu.add_command(label="Exit", accelerator="Alt+F4", command=root.destroy)
    menubar.add_cascade(label="File", menu=file_menu)

    help_menu = tk.Menu(menubar, tearoff=0)
    help_menu.add_command(label="Check for Updates…", command=lambda: check_for_updates(True))
    help_menu.add_checkbutton(label="Check for updates at startup",
                              variable=updates_var, command=save_settings)
    help_menu.add_separator()
    help_menu.add_command(label="Project on GitHub",
                          command=lambda: webbrowser.open(updater.PROJECT_PAGE))
    help_menu.add_command(label="About Repo Growth", command=show_about)
    menubar.add_cascade(label="Help", menu=help_menu)

    tk.Tk.configure(root, menu=menubar)
    root.bind("<Control-o>", lambda _e: pick_repo())
    root.bind("<Control-g>", lambda _e: run())

    # Any change to the form after a run puts the footer back to Generate;
    # the finished files stay reachable from the File menu.
    for var in (repo_var, exclude_var, since_var, until_var, detail_var, static_var, animated_var):
        var.trace_add("write", show_ready)
    show_ready()

    # A checkout updates with `git pull`, so only built copies check on launch.
    if updates_var.get() and updater.update_mode() != "source":
        root.after(STARTUP_CHECK_DELAY_MS, lambda: check_for_updates(manual=False))

    poll()
    return root


if __name__ == "__main__":
    launch_gui()
