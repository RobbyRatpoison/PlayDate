"""
uninstall.py — PlayDate GUI Uninstaller
Uses only tkinter (ships with Python — no pip install needed).
Run with: python uninstall.py
"""

import os
import sys
import subprocess
import threading
import platform
import shutil
import tkinter as tk
from tkinter import ttk, messagebox

# ── Resolve paths ─────────────────────────────────────────────────────────────
INSTALL_DIR  = os.path.dirname(os.path.abspath(__file__))
VENV_DIR     = os.path.join(INSTALL_DIR, ".venv")
LAUNCHER_SH  = os.path.join(INSTALL_DIR, "playdate-launch.sh")
LAUNCHER_BAT = os.path.join(INSTALL_DIR, "playdate-launch.bat")
SYSTEM       = platform.system()

# User data files
USER_DATA = {
    "config.json":  ("Steam API credentials and settings",  os.path.join(INSTALL_DIR, "config.json")),
    "state.json":   ("Library filters, sort order, shelves", os.path.join(INSTALL_DIR, "state.json")),
    "games.db":     ("Your entire game library database",    os.path.join(INSTALL_DIR, "games.db")),
    "playdate.log": ("Application log file",                 os.path.join(INSTALL_DIR, "playdate.log")),
}

# ── Colours ───────────────────────────────────────────────────────────────────
BG      = "#1b2838"
FG      = "#c7d5e0"
ACCENT  = "#66c0f4"
SUCCESS = "#5c9e31"
ERROR   = "#c94f4f"
WARN    = "#c9a03a"
DARK    = "#131a22"
BTN_BG  = "#2a475e"
BTN_FG  = "#ffffff"
CHK_BG  = "#162231"


class UninstallerApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("PlayDate Uninstaller")
        self.configure(bg=BG)
        self.resizable(False, False)
        self._center(540, 520)
        self._set_icon()
        self._phase = "confirm"   # "confirm" → "uninstalling" → "done"
        self._build_confirm_ui()

    def _set_icon(self):
        icon = os.path.join(INSTALL_DIR, "static", "img", "favicon.png")
        try:
            if SYSTEM == "Windows" and os.path.exists(icon):
                self.iconbitmap(icon)
            elif os.path.exists(icon):
                img = tk.PhotoImage(file=icon)
                self.iconphoto(True, img)
        except Exception:
            pass

    def _center(self, w, h):
        self.update_idletasks()
        sw = self.winfo_screenwidth()
        sh = self.winfo_screenheight()
        self.geometry(f"{w}x{h}+{(sw-w)//2}+{(sh-h)//2}")

    # ── Phase 1: Confirmation screen ──────────────────────────────────────────
    def _build_confirm_ui(self):
        # Header
        hdr = tk.Frame(self, bg=DARK, pady=16)
        hdr.pack(fill="x")
        tk.Label(hdr, text="PlayDate", font=("Segoe UI", 20, "bold"),
                 bg=DARK, fg=ACCENT).pack()
        tk.Label(hdr, text="Uninstaller", font=("Segoe UI", 11),
                 bg=DARK, fg=FG).pack()

        body = tk.Frame(self, bg=BG, padx=28, pady=14)
        body.pack(fill="both", expand=True)

        # Info
        tk.Label(body,
                 text="The following will be removed:",
                 font=("Segoe UI", 10, "bold"),
                 bg=BG, fg=FG, anchor="w").pack(fill="x", pady=(0, 4))

        always_frame = tk.Frame(body, bg=CHK_BG, padx=12, pady=10,
                                relief="flat", bd=0)
        always_frame.pack(fill="x", pady=(0, 12))

        always_items = [
            "Virtual environment  (.venv/)",
            "Launcher script  (playdate-launch.sh / .bat)",
        ]
        if SYSTEM == "Darwin":
            always_items.append("PlayDate.app  (~/Applications/PlayDate.app)")
        elif SYSTEM == "Linux":
            always_items.append("Desktop entry  (~/.local/share/applications/playdate.desktop)")
        elif SYSTEM == "Windows":
            always_items.append("Start Menu shortcut")

        for item in always_items:
            tk.Label(always_frame, text=f"  ✔  {item}",
                     font=("Consolas", 9), bg=CHK_BG, fg=FG,
                     anchor="w").pack(fill="x")

        # ── User data section ──────────────────────────────────────────────────
        tk.Label(body,
                 text="User data  (optional — check to delete):",
                 font=("Segoe UI", 10, "bold"),
                 bg=BG, fg=WARN, anchor="w").pack(fill="x", pady=(0, 4))

        data_frame = tk.Frame(body, bg=CHK_BG, padx=12, pady=10)
        data_frame.pack(fill="x", pady=(0, 14))

        self._data_vars = {}
        style = ttk.Style(self)
        style.theme_use("default")

        for filename, (description, filepath) in USER_DATA.items():
            exists = os.path.exists(filepath)
            var = tk.BooleanVar(value=False)
            self._data_vars[filename] = (var, filepath)

            row = tk.Frame(data_frame, bg=CHK_BG)
            row.pack(fill="x", pady=2)

            cb = tk.Checkbutton(
                row, variable=var,
                bg=CHK_BG, fg=FG if exists else "#555",
                activebackground=CHK_BG, activeforeground=FG,
                selectcolor=BTN_BG,
                state="normal" if exists else "disabled",
                cursor="hand2" if exists else "arrow"
            )
            cb.pack(side="left")

            name_lbl = tk.Label(row, text=filename,
                                font=("Consolas", 9, "bold"),
                                bg=CHK_BG, fg=ACCENT if exists else "#555",
                                width=16, anchor="w")
            name_lbl.pack(side="left")

            tk.Label(row, text=description,
                     font=("Segoe UI", 9),
                     bg=CHK_BG, fg=FG if exists else "#555",
                     anchor="w").pack(side="left")

            if not exists:
                tk.Label(row, text=" (not found)",
                         font=("Segoe UI", 9, "italic"),
                         bg=CHK_BG, fg="#555", anchor="w").pack(side="left")

        # Safe note
        tk.Label(body,
                 text="⚠  Deleted files cannot be recovered. Your PlayDate folder will remain.",
                 font=("Segoe UI", 8, "italic"),
                 bg=BG, fg=WARN, wraplength=480, justify="left").pack(fill="x")

        # Buttons
        btn_row = tk.Frame(self, bg=BG)
        btn_row.pack(pady=14)

        tk.Button(btn_row, text="Cancel",
                  bg=BTN_BG, fg=BTN_FG,
                  font=("Segoe UI", 10),
                  relief="flat", cursor="hand2",
                  padx=20, pady=8,
                  command=self.destroy).pack(side="left", padx=8)

        tk.Button(btn_row, text="Uninstall",
                  bg=ERROR, fg=BTN_FG,
                  font=("Segoe UI", 10, "bold"),
                  relief="flat", cursor="hand2",
                  padx=20, pady=8,
                  command=self._confirm_and_proceed).pack(side="left", padx=8)

    def _confirm_and_proceed(self):
        selected = [f for f, (v, _) in self._data_vars.items() if v.get()]
        msg = "This will remove PlayDate's launcher, virtual environment, and system registration."
        if selected:
            msg += f"\n\nThe following user data will also be permanently deleted:\n  • " + "\n  • ".join(selected)
        msg += "\n\nContinue?"

        if not messagebox.askyesno("Confirm Uninstall", msg, icon="warning"):
            return

        # Switch to progress UI
        for widget in self.winfo_children():
            widget.destroy()
        self._build_progress_ui()
        threading.Thread(target=self._run_uninstall, daemon=True).start()

    # ── Phase 2: Progress screen ───────────────────────────────────────────────
    def _build_progress_ui(self):
        hdr = tk.Frame(self, bg=DARK, pady=16)
        hdr.pack(fill="x")
        tk.Label(hdr, text="PlayDate", font=("Segoe UI", 20, "bold"),
                 bg=DARK, fg=ACCENT).pack()
        tk.Label(hdr, text="Uninstalling…", font=("Segoe UI", 11),
                 bg=DARK, fg=FG).pack()

        body = tk.Frame(self, bg=BG, padx=28, pady=16)
        body.pack(fill="both", expand=True)

        self._step_var = tk.StringVar(value="Starting…")
        tk.Label(body, textvariable=self._step_var,
                 font=("Segoe UI", 10, "bold"),
                 bg=BG, fg=ACCENT, anchor="w").pack(fill="x", pady=(0, 6))

        style = ttk.Style(self)
        style.configure("PD.Horizontal.TProgressbar",
                        troughcolor=DARK, background=ACCENT,
                        thickness=14, borderwidth=0)
        self._prog = ttk.Progressbar(body, style="PD.Horizontal.TProgressbar",
                                     mode="determinate", length=480)
        self._prog.pack(fill="x", pady=(0, 10))

        log_frame = tk.Frame(body, bg=DARK, bd=1, relief="sunken")
        log_frame.pack(fill="both", expand=True)
        self._log = tk.Text(log_frame, bg=DARK, fg=FG,
                            font=("Consolas", 9), relief="flat",
                            state="disabled", wrap="word",
                            height=12, padx=8, pady=6)
        sb = ttk.Scrollbar(log_frame, command=self._log.yview)
        self._log.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        self._log.pack(side="left", fill="both", expand=True)
        self._log.tag_configure("ok",   foreground=SUCCESS)
        self._log.tag_configure("warn", foreground=WARN)
        self._log.tag_configure("err",  foreground=ERROR)
        self._log.tag_configure("info", foreground=FG)

        self._btn_var = tk.StringVar(value="Uninstalling…")
        self._btn = tk.Button(self, textvariable=self._btn_var,
                              bg=BTN_BG, fg=BTN_FG,
                              font=("Segoe UI", 10, "bold"),
                              relief="flat", cursor="arrow",
                              state="disabled", padx=20, pady=8,
                              command=self.destroy)
        self._btn.pack(pady=12)

    # ── Thread-safe helpers ────────────────────────────────────────────────────
    def _log_line(self, msg, tag="info"):
        def _do():
            self._log.configure(state="normal")
            self._log.insert("end", msg + "\n", tag)
            self._log.see("end")
            self._log.configure(state="disabled")
        self.after(0, _do)

    def _set_progress(self, pct, label):
        def _do():
            self._step_var.set(label)
            self._prog["value"] = pct
        self.after(0, _do)

    def _finish_ok(self):
        def _do():
            self._prog["value"] = 100
            self._step_var.set("Uninstall complete.")
            self._btn_var.set("Close")
            self._btn.configure(state="normal", bg=SUCCESS, cursor="hand2")
        self.after(0, _do)

    def _finish_err(self, msg):
        def _do():
            self._step_var.set("An error occurred.")
            self._log_line(f"\n✘  {msg}", "err")
            self._btn_var.set("Close")
            self._btn.configure(state="normal", bg=ERROR, cursor="hand2")
        self.after(0, _do)

    # ── Uninstall logic ────────────────────────────────────────────────────────
    def _count_steps(self):
        base = 3  # system reg + launcher + venv
        data_selected = sum(1 for _, (v, p) in self._data_vars.items() if v.get() and os.path.exists(p))
        return base + data_selected

    def _run_uninstall(self):
        try:
            total = self._count_steps()
            done  = 0

            def advance(label):
                nonlocal done
                done += 1
                self._set_progress(int(done / total * 100), label)

            # ── Step 1: System registration ────────────────────────────────────
            self._log_line("→  Removing system registration…", "info")
            if SYSTEM == "Darwin":
                app_bundle = os.path.expanduser("~/Applications/PlayDate.app")
                if os.path.isdir(app_bundle):
                    shutil.rmtree(app_bundle)
                    subprocess.run(["mdimport", "-d1", os.path.expanduser("~/Applications")],
                                   capture_output=True)
                    self._log_line("✔  PlayDate.app removed", "ok")
                else:
                    self._log_line("⚠  PlayDate.app not found — skipping", "warn")

            elif SYSTEM == "Linux":
                df = os.path.expanduser("~/.local/share/applications/playdate.desktop")
                if os.path.exists(df):
                    os.remove(df)
                    subprocess.run(["update-desktop-database",
                                    os.path.dirname(df)], capture_output=True)
                    self._log_line("✔  Desktop entry removed", "ok")
                else:
                    self._log_line("⚠  Desktop entry not found — skipping", "warn")

            elif SYSTEM == "Windows":
                shortcut = os.path.join(
                    os.environ.get("APPDATA", ""),
                    "Microsoft", "Windows", "Start Menu", "Programs", "PlayDate.lnk"
                )
                if os.path.exists(shortcut):
                    os.remove(shortcut)
                    self._log_line("✔  Start Menu shortcut removed", "ok")
                else:
                    self._log_line("⚠  Start Menu shortcut not found — skipping", "warn")

            advance("Step 1 — System registration removed")

            # ── Step 2: Launcher ───────────────────────────────────────────────
            self._log_line("→  Removing launcher script…", "info")
            for launcher in (LAUNCHER_SH, LAUNCHER_BAT):
                if os.path.exists(launcher):
                    os.remove(launcher)
                    self._log_line(f"✔  Removed {os.path.basename(launcher)}", "ok")
            advance("Step 2 — Launcher removed")

            # ── Step 3: Virtual environment ────────────────────────────────────
            self._log_line("→  Removing virtual environment (may take a moment)…", "info")
            if os.path.isdir(VENV_DIR):
                shutil.rmtree(VENV_DIR)
                self._log_line("✔  .venv/ removed", "ok")
            else:
                self._log_line("⚠  .venv/ not found — skipping", "warn")
            advance("Step 3 — Virtual environment removed")

            # ── Step 4+: User data (only what was checked) ─────────────────────
            for filename, (var, filepath) in self._data_vars.items():
                if not var.get():
                    continue
                if not os.path.exists(filepath):
                    self._log_line(f"⚠  {filename} not found — skipping", "warn")
                    continue
                self._log_line(f"→  Deleting {filename}…", "info")
                os.remove(filepath)
                self._log_line(f"✔  {filename} deleted", "ok")
                advance(f"Removed {filename}")

            self._log_line("\n✔  PlayDate has been uninstalled.", "ok")
            self._log_line(f"   Your PlayDate folder is untouched: {INSTALL_DIR}", "info")
            self._finish_ok()

        except Exception as e:
            self._finish_err(str(e))


if __name__ == "__main__":
    try:
        import tkinter  # noqa
    except ImportError:
        print("ERROR: tkinter is not available. Install python3-tk and re-run.")
        sys.exit(1)

    app = UninstallerApp()
    app.mainloop()
