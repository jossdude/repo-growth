"""Tk GUI for repo_growth — pick a repo, choose detail level, generate."""

import os
import queue
import threading
import webbrowser
import tkinter as tk
from tkinter import filedialog, ttk, scrolledtext, messagebox

from repo_growth import (
    DETAIL_TARGETS,
    analyse_repo,
    default_output_path,
    generate_html,
)


def launch_gui():
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
