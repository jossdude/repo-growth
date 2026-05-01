"""Tk GUI for repo_growth — pick a repo, choose detail level, generate."""

import os
import queue
import threading
import webbrowser
import tkinter as tk
from tkinter import filedialog, ttk, messagebox

from repo_growth import (
    DETAIL_TARGETS,
    analyse_repo,
    default_output_path,
    generate_html,
)


BG           = "#0d0f14"
SURFACE      = "#141720"
SURFACE_HI   = "#1a1e28"
BORDER       = "#1e2230"
ACCENT       = "#00e5a0"
ACCENT_HOVER = "#22f0b0"
ACCENT_DOWN  = "#00b785"
TEXT         = "#e8eaf0"
MUTED        = "#5a6070"

FONT_BASE   = ("Segoe UI", 10)
FONT_SMALL  = ("Segoe UI", 9)
FONT_LABEL  = ("Segoe UI", 10)
FONT_BOLD   = ("Segoe UI", 10, "bold")
FONT_HEADER = ("Segoe UI", 22, "bold")
FONT_MONO   = ("Consolas", 10)


def _configure_styles(root):
    style = ttk.Style(root)
    style.theme_use("clam")

    style.configure("TFrame", background=BG)

    style.configure("TLabel",        background=BG, foreground=TEXT,  font=FONT_LABEL)
    style.configure("Header.TLabel", background=BG, foreground=TEXT,  font=FONT_HEADER)
    style.configure("Subtle.TLabel", background=BG, foreground=MUTED, font=FONT_SMALL)

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
    root.option_add("*TCombobox*Listbox.font", FONT_BASE)

    style.configure("TButton",
        background=SURFACE, foreground=TEXT,
        bordercolor=BORDER, lightcolor=BORDER, darkcolor=BORDER,
        padding=(14, 7), font=FONT_BASE, borderwidth=1,
    )
    style.map("TButton",
        background=[("active", SURFACE_HI), ("pressed", SURFACE_HI), ("disabled", SURFACE)],
        foreground=[("disabled", MUTED)],
        bordercolor=[("active", ACCENT), ("focus", ACCENT)],
    )

    style.configure("Accent.TButton",
        background=ACCENT, foreground="#0d0f14",
        bordercolor=ACCENT, lightcolor=ACCENT, darkcolor=ACCENT,
        padding=(22, 9), font=FONT_BOLD, borderwidth=0,
    )
    style.map("Accent.TButton",
        background=[("active", ACCENT_HOVER), ("pressed", ACCENT_DOWN), ("disabled", BORDER)],
        foreground=[("disabled", MUTED)],
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


def launch_gui():
    root = tk.Tk()
    root.title("Repo Growth")
    root.geometry("780x680")
    root.minsize(620, 540)
    root.configure(bg=BG)

    _configure_styles(root)

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
                    write_log(f"\nDone — saved to {payload}\n")
                elif kind == "error":
                    progress_bar.stop()
                    run_btn.configure(state="normal")
                    write_log(f"\nERROR: {payload}\n")
                    messagebox.showerror("Repo Growth", payload)
        except queue.Empty:
            pass
        root.after(100, poll)

    outer = ttk.Frame(root, padding=(28, 24, 28, 20))
    outer.pack(fill="both", expand=True)
    outer.columnconfigure(0, weight=1)

    ttk.Label(outer, text="Repo Growth", style="Header.TLabel").grid(row=0, column=0, sticky="w")
    ttk.Label(
        outer,
        text="Visualise how a Git repository has grown over time. Local repos only — nothing leaves your machine.",
        style="Subtle.TLabel",
    ).grid(row=1, column=0, sticky="w", pady=(4, 22))

    form = ttk.Frame(outer)
    form.grid(row=2, column=0, sticky="ew")
    form.columnconfigure(1, weight=1)

    r = 0
    ttk.Label(form, text="Repository").grid(row=r, column=0, sticky="w", padx=(0, 14), pady=(0, 4))
    ttk.Entry(form, textvariable=repo_var).grid(row=r, column=1, sticky="ew", pady=(0, 4))
    ttk.Button(form, text="Browse…", command=pick_repo).grid(row=r, column=2, padx=(8, 0), pady=(0, 4))
    r += 1
    ttk.Label(form, text="The local Git repository you want to chart.", style="Subtle.TLabel") \
        .grid(row=r, column=1, sticky="w", pady=(0, 16))
    r += 1

    ttk.Label(form, text="Output HTML").grid(row=r, column=0, sticky="w", padx=(0, 14), pady=(0, 4))
    ttk.Entry(form, textvariable=output_var).grid(row=r, column=1, sticky="ew", pady=(0, 4))
    ttk.Button(form, text="Save as…", command=pick_output).grid(row=r, column=2, padx=(8, 0), pady=(0, 4))
    r += 1
    ttk.Label(
        form,
        text="Optional — defaults to  <repo>/Repo Growth/<repo>_growth_<date>.html",
        style="Subtle.TLabel",
    ).grid(row=r, column=1, sticky="w", pady=(0, 16))
    r += 1

    ttk.Label(form, text="Branch").grid(row=r, column=0, sticky="w", padx=(0, 14), pady=(0, 4))
    ttk.Entry(form, textvariable=branch_var).grid(row=r, column=1, sticky="ew", pady=(0, 4))
    r += 1
    ttk.Label(form, text="Optional — defaults to the active branch.", style="Subtle.TLabel") \
        .grid(row=r, column=1, sticky="w", pady=(0, 16))
    r += 1

    ttk.Label(form, text="Detail level").grid(row=r, column=0, sticky="w", padx=(0, 14), pady=(0, 4))
    detail_combo = ttk.Combobox(
        form, textvariable=detail_var,
        values=list(DETAIL_TARGETS.keys()), state="readonly",
    )
    detail_combo.grid(row=r, column=1, sticky="ew", pady=(0, 4))
    r += 1
    ttk.Label(
        form,
        text=f"Target data points  ·  Rough ~{DETAIL_TARGETS['Rough']}  ·  Standard ~{DETAIL_TARGETS['Standard']}  ·  Detailed ~{DETAIL_TARGETS['Detailed']}",
        style="Subtle.TLabel",
    ).grid(row=r, column=1, sticky="w", pady=(0, 22))

    actions = ttk.Frame(outer)
    actions.grid(row=3, column=0, sticky="ew", pady=(0, 14))
    run_btn = ttk.Button(actions, text="Generate", style="Accent.TButton", command=run)
    run_btn.pack(side="left")
    open_btn = ttk.Button(actions, text="Open in browser", command=open_output, state="disabled")
    open_btn.pack(side="left", padx=(10, 0))

    progress_bar = ttk.Progressbar(outer, mode="indeterminate")
    progress_bar.grid(row=4, column=0, sticky="ew", pady=(0, 14))

    log_frame = ttk.Frame(outer)
    log_frame.grid(row=5, column=0, sticky="nsew")
    log_frame.columnconfigure(0, weight=1)
    log_frame.rowconfigure(0, weight=1)
    outer.rowconfigure(5, weight=1)

    log_text = tk.Text(
        log_frame,
        wrap="word", state="disabled", font=FONT_MONO,
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

    poll()
    root.mainloop()


if __name__ == "__main__":
    launch_gui()
