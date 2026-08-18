"""Tk GUI for repo_growth — pick a repo, choose detail level, generate."""

import ctypes
import json
import os
import queue
import sys
import threading
import webbrowser
import tkinter as tk
from tkinter import filedialog, ttk, messagebox, font as tkfont

import updater
from repo_growth import (
    ASSETS_DIR,
    DETAIL_TARGETS,
    AnalysisCancelled,
    analyse_repo,
    animated_output_path,
    cloud_placeholder_count,
    count_commits,
    default_output_path,
    generate_animated_html,
    generate_html,
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


BG           = "#0d0f14"
SURFACE      = "#141720"
SURFACE_HI   = "#1a1e28"
BORDER       = "#1e2230"
ACCENT       = "#00e5a0"
ACCENT_HOVER = "#22f0b0"
ACCENT_DOWN  = "#00b785"
TEXT         = "#e8eaf0"
MUTED        = "#5a6070"
MARK_AXIS    = "#2a3242"   # the logo's chart axis — sits between BORDER and MUTED

# Greyed-out menu entries. MUTED manages only 2.9:1 against the menu's
# SURFACE background — dim enough to read as disabled, too dim to read. This
# sits at 4.8:1: still visibly inactive next to TEXT's 14:1, but legible.
MENU_DISABLED = "#7b8394"

# Font preferences. The static HTML template uses Syne (display sans) and
# JetBrains Mono. We try those first, then fall back through likely-installed
# Windows alternatives. To get an exact match, install the two Google Fonts
# locally — the GUI will pick them up automatically.
SANS_CANDIDATES = ["Syne", "Segoe UI Variable Display", "Segoe UI", "Arial"]
MONO_CANDIDATES = ["JetBrains Mono", "Cascadia Mono", "Cascadia Code", "Consolas", "Courier New"]


# The logo mark, defined on the same 32x32 grid as assets/logo.svg: a
# lines-of-code curve rising off a muted axis. Tk can't render SVG, so we
# redraw it on a Canvas from the same coordinates — keep the two in step if
# either changes.
_MARK_AXIS_PTS    = [(6, 4.5), (6, 26), (27.5, 26)]
_MARK_CURVE_PTS   = [(9.5, 21.2), (14.8, 16.2), (19.2, 18.4), (25, 9.2)]
_MARK_CURVE_WIDTH = 2.6


def _make_mark(parent, size=34):
    """Canvas widget holding the Repo Growth mark, drawn at `size` pixels."""
    s = size / 32.0
    canvas = tk.Canvas(
        parent, width=size, height=size,
        bg=BG, highlightthickness=0, bd=0,
    )

    def scaled(points):
        return [c * s for pt in points for c in pt]

    canvas.create_line(
        *scaled(_MARK_AXIS_PTS),
        fill=MARK_AXIS, width=max(1, 2.4 * s),
        capstyle=tk.ROUND, joinstyle=tk.ROUND,
    )
    canvas.create_line(
        *scaled(_MARK_CURVE_PTS),
        fill=ACCENT, width=max(1, _MARK_CURVE_WIDTH * s),
        capstyle=tk.ROUND, joinstyle=tk.ROUND,
    )
    return canvas


# The same mark as an icon file, for the window title bar, its dialogs and the
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


def _apply_icon(root):
    """Put the mark on the title bar, the taskbar and every dialog.

    Windows wants a real .ico; `default=` makes it the icon for Toplevels too,
    so the About and update windows get it without repeating this. Elsewhere Tk
    takes a PhotoImage, and iconphoto's `default` flag does the same job.
    """
    if sys.platform == "win32" and os.path.exists(ICON_ICO):
        try:
            root.iconbitmap(default=ICON_ICO)
            return
        except tk.TclError:
            pass
    if os.path.exists(ICON_PNG):
        try:
            image = tk.PhotoImage(file=ICON_PNG)
            root.iconphoto(True, image)
            root._icon_image = image  # Tk keeps no reference of its own
        except tk.TclError:
            pass


def _pick_family(root, candidates):
    available = set(tkfont.families(root))
    for fam in candidates:
        if fam in available:
            return fam
    return candidates[-1]


def _configure_styles(root, sans, mono):
    fonts = {
        "base":      (sans, 10),
        "small":     (sans, 9),
        "bold":      (sans, 10, "bold"),
        "header":    (sans, 26, "bold"),
        "mono":      (mono, 10),
        "mono_sub":  (mono, 9),
        "tracked":   (mono, 9, "bold"),     # used for small uppercase section labels
    }

    style = ttk.Style(root)
    style.theme_use("clam")

    style.configure("TFrame", background=BG)

    style.configure("TLabel",            background=BG, foreground=TEXT,   font=fonts["base"])
    style.configure("Subtle.TLabel",     background=BG, foreground=MUTED,  font=fonts["small"])

    # Two-tone header: "Repo" in accent green, " Growth" in text colour.
    style.configure("Title.TLabel",       background=BG, foreground=TEXT,   font=fonts["header"])
    style.configure("TitleAccent.TLabel", background=BG, foreground=ACCENT, font=fonts["header"])

    # Matches the .chart-title style from template.html — small, uppercase,
    # mono, tracked, muted. We fake letter-spacing by uppercasing the text.
    style.configure("Tracked.TLabel",    background=BG, foreground=MUTED,  font=fonts["tracked"])

    # Mono small muted — matches the web subtitle "branch: ... · ... commits".
    style.configure("MonoSub.TLabel",    background=BG, foreground=MUTED,  font=fonts["mono_sub"])

    # Clickable URL in the About box.
    style.configure("Link.TLabel",       background=BG, foreground=ACCENT, font=fonts["mono_sub"])

    style.configure("TEntry",
        fieldbackground=SURFACE, foreground=TEXT,
        bordercolor=BORDER, lightcolor=BORDER, darkcolor=BORDER,
        insertcolor=TEXT, padding=7,
    )
    style.map("TEntry",
        bordercolor=[("focus", ACCENT)],
        lightcolor=[("focus", ACCENT)],
        darkcolor=[("focus", ACCENT)],
    )

    style.configure("TCombobox",
        fieldbackground=SURFACE, background=SURFACE, foreground=TEXT,
        bordercolor=BORDER, lightcolor=BORDER, darkcolor=BORDER,
        arrowcolor=TEXT, padding=5,
        selectbackground=SURFACE, selectforeground=TEXT,
    )
    style.map("TCombobox",
        fieldbackground=[("readonly", SURFACE)],
        bordercolor=[("focus", ACCENT)],
    )
    root.option_add("*TCombobox*Listbox.background", SURFACE)
    root.option_add("*TCombobox*Listbox.foreground", TEXT)
    root.option_add("*TCombobox*Listbox.selectBackground", ACCENT)
    root.option_add("*TCombobox*Listbox.selectForeground", "#0d0f14")
    root.option_add("*TCombobox*Listbox.borderWidth", 0)
    root.option_add("*TCombobox*Listbox.font", fonts["base"])

    style.configure("TButton",
        background=SURFACE, foreground=TEXT,
        bordercolor=BORDER, lightcolor=BORDER, darkcolor=BORDER,
        padding=(14, 7), font=fonts["base"], borderwidth=1,
    )
    style.map("TButton",
        background=[("active", SURFACE_HI), ("pressed", SURFACE_HI), ("disabled", SURFACE)],
        foreground=[("disabled", MUTED)],
        bordercolor=[("active", ACCENT), ("focus", ACCENT)],
    )

    style.configure("Accent.TButton",
        background=ACCENT, foreground="#0d0f14",
        bordercolor=ACCENT, lightcolor=ACCENT, darkcolor=ACCENT,
        padding=(22, 9), font=fonts["bold"], borderwidth=0,
    )
    style.map("Accent.TButton",
        background=[("active", ACCENT_HOVER), ("pressed", ACCENT_DOWN), ("disabled", BORDER)],
        foreground=[("disabled", MUTED)],
    )

    style.configure("TCheckbutton",
        background=BG, foreground=TEXT, font=fonts["base"],
        indicatorcolor=SURFACE, indicatorrelief="flat",
        focuscolor=BG, padding=(0, 2),
    )
    style.map("TCheckbutton",
        background=[("active", BG)],
        foreground=[("disabled", MUTED)],
        indicatorcolor=[("selected", ACCENT), ("pressed", ACCENT_DOWN), ("!selected", SURFACE)],
    )

    style.configure("Horizontal.TProgressbar",
        background=ACCENT, troughcolor=SURFACE, bordercolor=SURFACE,
        lightcolor=ACCENT, darkcolor=ACCENT, borderwidth=0, thickness=4,
    )

    style.configure("Vertical.TScrollbar",
        background=SURFACE, troughcolor=BG,
        bordercolor=BG, lightcolor=SURFACE, darkcolor=SURFACE,
        arrowcolor=MUTED, borderwidth=0, gripcount=0,
    )
    style.map("Vertical.TScrollbar",
        background=[("active", BORDER), ("pressed", BORDER)],
        arrowcolor=[("active", TEXT)],
    )

    return fonts


def _menu(parent, fonts):
    """A dropdown menu in the app's palette.

    The menu *bar* strip is drawn by the window manager and largely ignores
    these colours; the dropdowns that hang off it honour them.
    """
    return tk.Menu(
        parent, tearoff=0,
        bg=SURFACE, fg=TEXT,
        activebackground=ACCENT, activeforeground=BG,
        disabledforeground=MENU_DISABLED,
        selectcolor=ACCENT,
        borderwidth=0, activeborderwidth=0,
        font=fonts["base"],
    )


def _place_near(win, parent, dx=90, dy=90):
    win.geometry(f"+{parent.winfo_rootx() + dx}+{parent.winfo_rooty() + dy}")


def launch_gui():
    # A portable self-update leaves the previous build renamed beside us.
    updater.cleanup_old_build()

    # Before the window exists — the taskbar reads it when the button is made.
    _claim_taskbar_identity()

    root = tk.Tk()
    root.title("Repo Growth")
    root.geometry("780x640")
    root.minsize(620, 520)
    root.configure(bg=BG)
    _apply_icon(root)

    sans = _pick_family(root, SANS_CANDIDATES)
    mono = _pick_family(root, MONO_CANDIDATES)
    fonts = _configure_styles(root, sans, mono)

    settings = _load_settings()
    detail = settings.get("detail", "Standard")
    repo_var     = tk.StringVar(value=settings.get("repo", ""))
    detail_var   = tk.StringVar(value=detail if detail in DETAIL_TARGETS else "Standard")
    exclude_var  = tk.StringVar(value=settings.get("exclude", ""))
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
            "check_updates": updates_var.get(),
        })

    # Paths to the most recently generated files, used by the two Open buttons.
    last_output = {"static": "", "animated": ""}

    # The running analysis' cancel event, or None when idle.
    current_run = {"cancel": None}

    # The in-flight update check or download. Worker threads only ever put
    # messages on `msgs`; every Tk call below happens on the main thread.
    update_run = {"busy": False, "cancel": None, "window": None, "bar": None}

    msgs = queue.Queue()

    def log(msg):
        msgs.put(("log", str(msg)))

    def report_pct(v):
        msgs.put(("pct", float(v)))

    def pick_repo():
        path = filedialog.askdirectory(title="Choose a Git repository")
        if path:
            repo_var.set(path)

    def open_path(key):
        path = last_output.get(key, "")
        if path and os.path.exists(path):
            webbrowser.open(f"file:///{os.path.abspath(path).replace(os.sep, '/')}")

    def write_log(text):
        log_text.configure(state="normal")
        log_text.insert("end", text)
        log_text.see("end")
        log_text.configure(state="disabled")

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
        out_static   = default_output_path(repo_path)
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

        log_text.configure(state="normal")
        log_text.delete("1.0", "end")
        log_text.configure(state="disabled")
        run_btn.configure(state="disabled")
        cancel_btn.configure(state="normal")
        open_static_btn.configure(state="disabled")
        open_animated_btn.configure(state="disabled")
        progress_bar.configure(value=0)

        cancel_event = threading.Event()
        current_run["cancel"] = cancel_event

        def worker():
            try:
                analysis = analyse_repo(
                    repo_path, progress=log, target_points=target,
                    progress_pct=report_pct, cancel_event=cancel_event,
                    exclude_dirs=exclude,
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
            write_log("Cancelling — waiting for the current step to finish...\n")
        sync_menus()

    # What sync_menus last wrote, so it can skip writes that change nothing.
    # entryconfigure redraws an open menu on Windows, and poll() calls this
    # ten times a second — writing unconditionally makes the File menu flicker
    # for as long as it's held open.
    menu_state = {}

    def sync_menus():
        """Mirror the toolbar buttons' enabled state onto the File menu."""
        for label, widget in (
            ("Generate",               run_btn),
            ("Cancel Analysis",        cancel_btn),
            ("Open Static Dashboard",  open_static_btn),
            ("Open Animated Story",    open_animated_btn),
        ):
            state = str(widget["state"])
            if menu_state.get(label) != state:
                menu_state[label] = state
                file_menu.entryconfigure(label, state=state)

    # ------------------------------------------------------------ updates

    def check_for_updates(manual=True):
        """Ask GitHub what the latest release is, off the UI thread."""
        if update_run["busy"]:
            if manual:
                messagebox.showinfo("Repo Growth", "An update check is already running.")
            return
        update_run["busy"] = True
        if manual:
            write_log("Checking for updates...\n")

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

    def start_download(asset, mode):
        cancel = threading.Event()

        win = tk.Toplevel(root)
        win.title("Updating Repo Growth")
        win.configure(bg=BG)
        win.resizable(False, False)
        win.transient(root)
        _place_near(win, root, 110, 150)
        win.protocol("WM_DELETE_WINDOW", cancel.set)

        body = ttk.Frame(win, padding=(26, 22))
        body.pack(fill="both", expand=True)
        ttk.Label(body, text=f"Downloading {asset.get('name', 'update')}…").pack(anchor="w")
        ttk.Label(
            body, text="Repo Growth will restart once it's installed.",
            style="Subtle.TLabel",
        ).pack(anchor="w", pady=(4, 0))
        bar = ttk.Progressbar(body, mode="determinate", maximum=100, length=360)
        bar.pack(fill="x", pady=(16, 14))
        ttk.Button(body, text="Cancel", command=cancel.set).pack(anchor="e")
        win.grab_set()

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
            write_log(f"Update check failed: {message}\n")

    def show_about():
        win = tk.Toplevel(root)
        win.title("About Repo Growth")
        win.configure(bg=BG)
        win.resizable(False, False)
        win.transient(root)
        _place_near(win, root)

        body = ttk.Frame(win, padding=(30, 26))
        body.pack(fill="both", expand=True)

        name_row = ttk.Frame(body)
        name_row.pack(anchor="w")
        ttk.Label(name_row, text="Repo",    style="TitleAccent.TLabel").pack(side="left")
        ttk.Label(name_row, text=" Growth", style="Title.TLabel").pack(side="left")

        ttk.Label(body, text=f"version {__version__}", style="MonoSub.TLabel") \
            .pack(anchor="w", pady=(6, 18))
        ttk.Label(
            body,
            text="Visualise how a git repository has grown over time.\n"
                 "Everything runs on your machine — the charts it writes\n"
                 "make no network requests at all.",
        ).pack(anchor="w")

        link = ttk.Label(body, text=updater.PROJECT_PAGE, style="Link.TLabel", cursor="hand2")
        link.pack(anchor="w", pady=(14, 22))
        link.bind("<Button-1>", lambda _e: webbrowser.open(updater.PROJECT_PAGE))

        buttons = ttk.Frame(body)
        buttons.pack(anchor="e")
        ttk.Button(
            buttons, text="Check for Updates",
            command=lambda: (win.destroy(), check_for_updates(True)),
        ).pack(side="left", padx=(0, 8))
        ttk.Button(buttons, text="Close", style="Accent.TButton", command=win.destroy) \
            .pack(side="left")

    def poll():
        try:
            while True:
                kind, payload = msgs.get_nowait()
                if kind == "log":
                    write_log(payload + "\n")
                elif kind == "pct":
                    progress_bar.configure(value=payload * 100)
                elif kind == "done":
                    progress_bar.configure(value=100)
                    run_btn.configure(state="normal")
                    cancel_btn.configure(state="disabled")
                    current_run["cancel"] = None
                    last_output["static"]   = payload.get("static", "")
                    last_output["animated"] = payload.get("animated", "")
                    open_static_btn.configure(
                        state=("normal" if last_output["static"] else "disabled")
                    )
                    open_animated_btn.configure(
                        state=("normal" if last_output["animated"] else "disabled")
                    )
                    parts = [p for p in (last_output["static"], last_output["animated"]) if p]
                    write_log("\nDone — saved to:\n  " + "\n  ".join(parts) + "\n")
                elif kind == "cancelled":
                    progress_bar.configure(value=0)
                    run_btn.configure(state="normal")
                    cancel_btn.configure(state="disabled")
                    current_run["cancel"] = None
                    write_log("\nCancelled.\n")
                elif kind == "error":
                    progress_bar.configure(value=0)
                    run_btn.configure(state="normal")
                    cancel_btn.configure(state="disabled")
                    current_run["cancel"] = None
                    write_log(f"\nERROR: {payload}\n")
                    messagebox.showerror("Repo Growth", payload)
                elif kind == "update_found":
                    on_update_found(*payload)
                elif kind == "update_pct":
                    bar = update_run.get("bar")
                    if bar is not None:
                        bar.configure(value=payload * 100)
                elif kind == "update_ready":
                    on_update_ready(*payload)
                elif kind == "update_failed":
                    on_update_failed(*payload)
        except queue.Empty:
            pass
        sync_menus()
        root.after(100, poll)

    outer = ttk.Frame(root, padding=(28, 24, 28, 20))
    outer.pack(fill="both", expand=True)
    outer.columnconfigure(0, weight=1)

    title_row = ttk.Frame(outer)
    title_row.grid(row=0, column=0, sticky="w")
    _make_mark(title_row, 40).pack(side="left", padx=(0, 13))
    ttk.Label(title_row, text="Repo",   style="TitleAccent.TLabel").pack(side="left")
    ttk.Label(title_row, text=" Growth", style="Title.TLabel").pack(side="left")
    ttk.Label(
        outer,
        text="visualise how a git repository has grown over time  ·  local repos only"
             f"  ·  v{__version__}",
        style="MonoSub.TLabel",
    ).grid(row=1, column=0, sticky="w", pady=(8, 24))

    form = ttk.Frame(outer)
    form.grid(row=2, column=0, sticky="ew")
    form.columnconfigure(1, weight=1)

    r = 0
    ttk.Label(form, text="REPOSITORY", style="Tracked.TLabel").grid(row=r, column=0, sticky="w", padx=(0, 14), pady=(0, 4))
    repo_entry = ttk.Entry(form, textvariable=repo_var)
    repo_entry.grid(row=r, column=1, sticky="ew", pady=(0, 4))
    ttk.Button(form, text="Browse…", command=pick_repo).grid(row=r, column=2, padx=(8, 0), pady=(0, 4))
    r += 1
    ttk.Label(form, text="the local git repository you want to chart", style="Subtle.TLabel") \
        .grid(row=r, column=1, sticky="w", pady=(0, 16))
    r += 1

    ttk.Label(form, text="EXCLUDE FOLDERS", style="Tracked.TLabel").grid(row=r, column=0, sticky="w", padx=(0, 14), pady=(0, 4))
    exclude_entry = ttk.Entry(form, textvariable=exclude_var)
    exclude_entry.grid(row=r, column=1, sticky="ew", pady=(0, 4))
    r += 1
    ttk.Label(form, text="comma-separated folder names to leave out, at any depth  ·  e.g. tests, fixtures  ·  blank charts everything", style="Subtle.TLabel") \
        .grid(row=r, column=1, sticky="w", pady=(0, 16))
    r += 1

    ttk.Label(form, text="DETAIL LEVEL", style="Tracked.TLabel").grid(row=r, column=0, sticky="w", padx=(0, 14), pady=(0, 4))
    detail_combo = ttk.Combobox(
        form, textvariable=detail_var,
        values=list(DETAIL_TARGETS.keys()), state="readonly",
    )
    detail_combo.grid(row=r, column=1, sticky="ew", pady=(0, 4))
    r += 1
    ttk.Label(
        form,
        text=f"target data points  ·  rough ~{DETAIL_TARGETS['Rough']}  ·  standard ~{DETAIL_TARGETS['Standard']}  ·  detailed ~{DETAIL_TARGETS['Detailed']}  ·  full = every commit",
        style="Subtle.TLabel",
    ).grid(row=r, column=1, sticky="w", pady=(0, 16))
    r += 1

    ttk.Label(form, text="OUTPUTS", style="Tracked.TLabel").grid(row=r, column=0, sticky="w", padx=(0, 14), pady=(0, 4))
    outputs_frame = ttk.Frame(form)
    outputs_frame.grid(row=r, column=1, sticky="w", pady=(0, 4))
    ttk.Checkbutton(outputs_frame, text="Static dashboard", variable=static_var).pack(side="left", padx=(0, 18))
    ttk.Checkbutton(outputs_frame, text="Animated story",   variable=animated_var).pack(side="left")
    r += 1
    ttk.Label(
        form,
        text="saved to  <repo>/Repo Growth/  with a date-stamped filename",
        style="Subtle.TLabel",
    ).grid(row=r, column=1, sticky="w", pady=(0, 22))

    actions = ttk.Frame(outer)
    actions.grid(row=3, column=0, sticky="ew", pady=(0, 14))
    run_btn = ttk.Button(actions, text="Generate", style="Accent.TButton", command=run)
    run_btn.pack(side="left")
    cancel_btn = ttk.Button(actions, text="Cancel", command=cancel_run, state="disabled")
    cancel_btn.pack(side="left", padx=(10, 0))
    open_static_btn = ttk.Button(
        actions, text="Open Static",
        command=lambda: open_path("static"), state="disabled",
    )
    open_static_btn.pack(side="left", padx=(10, 0))
    open_animated_btn = ttk.Button(
        actions, text="Open Animated",
        command=lambda: open_path("animated"), state="disabled",
    )
    open_animated_btn.pack(side="left", padx=(8, 0))

    progress_bar = ttk.Progressbar(outer, mode="determinate", maximum=100, value=0)
    progress_bar.grid(row=4, column=0, sticky="ew", pady=(0, 14))

    log_frame = ttk.Frame(outer)
    log_frame.grid(row=5, column=0, sticky="nsew")
    log_frame.columnconfigure(0, weight=1)
    log_frame.rowconfigure(0, weight=1)
    outer.rowconfigure(5, weight=1)

    log_text = tk.Text(
        log_frame,
        wrap="word", state="disabled", font=fonts["mono"],
        bg=SURFACE, fg=TEXT, insertbackground=TEXT,
        selectbackground=BORDER, selectforeground=TEXT,
        relief="flat", borderwidth=0,
        highlightthickness=1, highlightbackground=BORDER, highlightcolor=BORDER,
        padx=12, pady=10,
    )
    log_scroll = ttk.Scrollbar(log_frame, command=log_text.yview)
    log_text.configure(yscrollcommand=log_scroll.set)
    log_text.grid(row=0, column=0, sticky="nsew")
    log_scroll.grid(row=0, column=1, sticky="ns")

    # Built last so its commands can reference the buttons they mirror.
    menubar = _menu(root, fonts)

    file_menu = _menu(menubar, fonts)
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

    help_menu = _menu(menubar, fonts)
    help_menu.add_command(label="Check for Updates…", command=lambda: check_for_updates(True))
    help_menu.add_checkbutton(label="Check for updates at startup",
                              variable=updates_var, command=save_settings)
    help_menu.add_separator()
    help_menu.add_command(label="Project on GitHub",
                          command=lambda: webbrowser.open(updater.PROJECT_PAGE))
    help_menu.add_command(label="About Repo Growth", command=show_about)
    menubar.add_cascade(label="Help", menu=help_menu)

    root.configure(menu=menubar)
    root.bind("<Control-o>", lambda _e: pick_repo())
    root.bind("<Control-g>", lambda _e: run())

    # A checkout updates with `git pull`, so only built copies check on launch.
    if updates_var.get() and updater.update_mode() != "source":
        root.after(STARTUP_CHECK_DELAY_MS, lambda: check_for_updates(manual=False))

    poll()
    root.mainloop()


if __name__ == "__main__":
    launch_gui()
