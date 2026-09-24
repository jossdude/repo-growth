"""Screenshot the GUI in its three states — ready, running, done.

    python tools/screenshot_gui.py light OUT_DIR [REPO]
    python tools/screenshot_gui.py dark  OUT_DIR [REPO]

Writes OUT_DIR/gui-<mode>-ready.png, -running.png and -done.png. REPO
defaults to this checkout. The window really runs: the settings file points
at REPO and Generate is pressed. The analysis is slowed down (and its result
computed up front) only so the running state can be caught mid-way.

Windows only (window bounds come from DWM), and needs Pillow for ImageGrab.
Settings are read from a throwaway APPDATA, so your own are left alone.
"""

import ctypes
import json
import os
import sys
import tempfile
import threading
import time
from ctypes import wintypes

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)


def _window_rect(hwnd):
    """The window's visible bounds, title bar included, without the shadow."""
    rect = wintypes.RECT()
    DWMWA_EXTENDED_FRAME_BOUNDS = 9
    ctypes.windll.dwmapi.DwmGetWindowAttribute(
        wintypes.HWND(hwnd), DWMWA_EXTENDED_FRAME_BOUNDS,
        ctypes.byref(rect), ctypes.sizeof(rect))
    return rect.left, rect.top, rect.right, rect.bottom


def main():
    mode, out_dir = sys.argv[1], sys.argv[2]
    repo = sys.argv[3] if len(sys.argv) > 3 else ROOT
    os.makedirs(out_dir, exist_ok=True)

    appdata = tempfile.mkdtemp()
    os.environ["APPDATA"] = appdata
    os.makedirs(os.path.join(appdata, "RepoGrowth"))
    with open(os.path.join(appdata, "RepoGrowth", "settings.json"), "w") as f:
        json.dump({"repo": repo, "detail": "Standard", "static": True, "animated": True,
                   "check_updates": False}, f)

    import customtkinter as ctk
    from PIL import ImageGrab
    import gui
    import repo_growth

    real = repo_growth.analyse_repo(repo, progress=lambda _m: None)
    release = threading.Event()

    def slow_analyse(repo_path, progress=print, progress_pct=None, **_kw):
        n = len(real["data"])
        progress(f"Opening repo at: {repo_path}")
        progress(f"Branch: {real['branch']}")
        progress(f"Total commits: {real['total_commits']}")
        progress(f"Processing all {n} commits")
        for i in range(n):
            if release.is_set():
                break
            progress_pct(repo_growth.SAMPLE_WEIGHT * (i + 1) / n)
            if (i + 1) % 10 == 0:
                d = real["data"][i]
                progress(f"  [{i+1}/{n}] {100*(i+1)/n:.0f}%  {d['date']} — {d['lines']:,} lines, {d['files']} files")
            time.sleep(0.25)
        release.wait()
        progress("Calculating churn...")
        progress_pct(1.0)
        return real

    gui.analyse_repo = slow_analyse
    # A checkout inside OneDrive would otherwise stop at the placeholder dialog.
    gui.cloud_placeholder_count = lambda _p: 0
    # A git worktree has a .git file rather than a folder, which the
    # "doesn't look like a Git repository" check asks about.
    gui.messagebox.askyesno = lambda *_a, **_k: True

    root = gui.build_gui()
    ctk.set_appearance_mode(mode)
    root.geometry("+80+40")
    root.attributes("-topmost", True)

    def shot(name):
        root.update()
        hwnd = ctypes.windll.user32.GetParent(root.winfo_id())
        img = ImageGrab.grab(_window_rect(hwnd), all_screens=True)
        path = os.path.join(out_dir, f"gui-{mode}-{name}.png")
        img.save(path)
        print("wrote", path)

    def step_ready():
        shot("ready")
        root.event_generate("<Control-g>")
        root.after(3200, step_running)

    def step_running():
        shot("running")
        release.set()
        root.after(2500, step_done)

    def step_done():
        shot("done")
        root.destroy()

    root.after(1800, step_ready)
    root.mainloop()


if __name__ == "__main__":
    main()
