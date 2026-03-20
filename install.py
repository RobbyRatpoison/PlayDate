"""
install.py — PlayDate GUI Installer
Uses only tkinter (ships with Python — no pip install needed).
Run with: python install.py
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
INSTALL_DIR = os.path.dirname(os.path.abspath(__file__))
VENV_DIR    = os.path.join(INSTALL_DIR, ".venv")
MAIN_PY     = os.path.join(INSTALL_DIR, "main.py")
REQ_FILE    = os.path.join(INSTALL_DIR, "requirements.txt")
ICON_PATH   = os.path.join(INSTALL_DIR, "static", "img", "favicon.png")
LAUNCHER_SH = os.path.join(INSTALL_DIR, "playdate-launch.sh")
LAUNCHER_BAT= os.path.join(INSTALL_DIR, "playdate-launch.bat")
SYSTEM      = platform.system()  # "Windows", "Darwin", "Linux"

VENV_PYTHON = (
    os.path.join(VENV_DIR, "Scripts", "python.exe") if SYSTEM == "Windows"
    else os.path.join(VENV_DIR, "bin", "python")
)
VENV_PIP = (
    os.path.join(VENV_DIR, "Scripts", "pip.exe") if SYSTEM == "Windows"
    else os.path.join(VENV_DIR, "bin", "pip")
)

# ── Colours ───────────────────────────────────────────────────────────────────
BG       = "#1b2838"
FG       = "#c7d5e0"
ACCENT   = "#66c0f4"
SUCCESS  = "#5c9e31"
ERROR    = "#c94f4f"
WARN     = "#c9a03a"
DARK     = "#131a22"
BTN_BG   = "#2a475e"
BTN_FG   = "#ffffff"


class InstallerApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("PlayDate Installer")
        self.configure(bg=BG)
        self.resizable(False, False)
        self._center(540, 400)

        # Set window icon if available
        self._set_icon()

        self._build_ui()
        self._steps_done = 0
        self._total_steps = self._count_steps()

        # Start install on a background thread
        threading.Thread(target=self._run_install, daemon=True).start()

    def _set_icon(self):
        try:
            if SYSTEM == "Windows" and os.path.exists(ICON_PATH):
                self.iconbitmap(ICON_PATH)
            elif os.path.exists(ICON_PATH):
                img = tk.PhotoImage(file=ICON_PATH)
                self.iconphoto(True, img)
        except Exception:
            pass

    def _center(self, w, h):
        self.update_idletasks()
        sw = self.winfo_screenwidth()
        sh = self.winfo_screenheight()
        x  = (sw - w) // 2
        y  = (sh - h) // 2
        self.geometry(f"{w}x{h}+{x}+{y}")

    def _count_steps(self):
        steps = 4  # sanity, python, venv, deps
        if SYSTEM == "Darwin": steps += 2   # launcher + .app
        elif SYSTEM == "Linux": steps += 2  # launcher + .desktop
        elif SYSTEM == "Windows": steps += 2  # launcher + shortcut
        return steps

    def _build_ui(self):
        # ── Header ────────────────────────────────────────────────────────────
        hdr = tk.Frame(self, bg=DARK, pady=16)
        hdr.pack(fill="x")
        tk.Label(hdr, text="PlayDate", font=("Segoe UI", 20, "bold"),
                 bg=DARK, fg=ACCENT).pack()
        tk.Label(hdr, text="Installer", font=("Segoe UI", 11),
                 bg=DARK, fg=FG).pack()

        # ── Body ──────────────────────────────────────────────────────────────
        body = tk.Frame(self, bg=BG, padx=28, pady=16)
        body.pack(fill="both", expand=True)

        # Step label
        self._step_var = tk.StringVar(value="Starting…")
        tk.Label(body, textvariable=self._step_var,
                 font=("Segoe UI", 10, "bold"),
                 bg=BG, fg=ACCENT, anchor="w").pack(fill="x", pady=(0, 6))

        # Progress bar
        style = ttk.Style(self)
        style.theme_use("default")
        style.configure("PD.Horizontal.TProgressbar",
                        troughcolor=DARK, background=ACCENT,
                        thickness=14, borderwidth=0)
        self._prog = ttk.Progressbar(body, style="PD.Horizontal.TProgressbar",
                                     mode="determinate", length=480)
        self._prog.pack(fill="x", pady=(0, 10))

        # Log box
        log_frame = tk.Frame(body, bg=DARK, bd=1, relief="sunken")
        log_frame.pack(fill="both", expand=True)

        self._log = tk.Text(log_frame, bg=DARK, fg=FG,
                            font=("Consolas", 9),
                            relief="flat", state="disabled",
                            wrap="word", height=10, padx=8, pady=6)
        sb = ttk.Scrollbar(log_frame, command=self._log.yview)
        self._log.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        self._log.pack(side="left", fill="both", expand=True)

        # Tag colours for log messages
        self._log.tag_configure("ok",   foreground=SUCCESS)
        self._log.tag_configure("warn", foreground=WARN)
        self._log.tag_configure("err",  foreground=ERROR)
        self._log.tag_configure("info", foreground=FG)
        self._log.tag_configure("pkg",  foreground="#8f98a0")

        # ── Footer ────────────────────────────────────────────────────────────
        footer = tk.Frame(self, bg=BG)
        footer.pack(fill="x", pady=(0, 12))

        self._shortcut_var = tk.BooleanVar(value=False)
        tk.Checkbutton(
            footer, text="Create desktop shortcut",
            variable=self._shortcut_var,
            bg=BG, fg=FG, selectcolor=DARK,
            activebackground=BG, activeforeground=FG,
            font=("Segoe UI", 9)
        ).pack(pady=(4, 0))

        btn_row = tk.Frame(footer, bg=BG)
        btn_row.pack(pady=8)

        self._btn_launch = tk.Button(
            btn_row, text="Launch PlayDate",
            bg=SUCCESS, fg=BTN_FG,
            font=("Segoe UI", 10, "bold"),
            relief="flat", cursor="arrow",
            state="disabled", padx=20, pady=8,
            command=self._launch_and_close
        )
        self._btn_launch.pack(side="left", padx=(0, 8))

        self._btn_close = tk.Button(
            btn_row, text="Installing…",
            bg=BTN_BG, fg=BTN_FG,
            font=("Segoe UI", 10, "bold"),
            relief="flat", cursor="arrow",
            state="disabled", padx=20, pady=8,
            command=self.destroy
        )
        self._btn_close.pack(side="left")

    # ── Thread-safe UI helpers ─────────────────────────────────────────────────
    def _log_line(self, msg, tag="info"):
        def _do():
            self._log.configure(state="normal")
            self._log.insert("end", msg + "\n", tag)
            self._log.see("end")
            self._log.configure(state="disabled")
        self.after(0, _do)

    def _set_step(self, label):
        def _do():
            self._step_var.set(label)
        self.after(0, _do)

    def _advance(self, label):
        self._steps_done += 1
        pct = int(self._steps_done / self._total_steps * 100)
        def _do():
            self._step_var.set(label)
            self._prog["value"] = pct
        self.after(0, _do)

    def _launch_and_close(self):
        subprocess.Popen([VENV_PYTHON, MAIN_PY])
        self.destroy()

    def _finish_ok(self):
        def _do():
            self._prog["value"] = 100
            self._step_var.set("Installation complete!")
            self._btn_launch.configure(state="normal", cursor="hand2")
            self._btn_close.configure(state="normal", text="Finish", cursor="hand2")
        self.after(0, _do)

    def _finish_err(self, msg):
        def _do():
            self._step_var.set("Installation failed.")
            self._log_line(f"\n✘  {msg}", "err")
            self._btn_close.configure(state="normal", text="Close", bg=ERROR, cursor="hand2")
        self.after(0, _do)

    # ── Install logic (runs on background thread) ──────────────────────────────
    def _run_install(self):
        try:
            self._step_sanity()
            self._step_python()
            self._step_venv()
            self._step_deps()
            self._step_launcher()
            self._step_register()
            self._finish_ok()
        except Exception as e:
            self._finish_err(str(e))

    def _step_sanity(self):
        self._set_step("Step 1 — Checking project files…")
        if not os.path.exists(MAIN_PY):
            raise RuntimeError(f"main.py not found in {INSTALL_DIR}.\nMake sure install.py is in the PlayDate folder.")
        self._log_line("✔  Project files found", "ok")
        self._advance("Step 1 — Project files OK")

    def _step_python(self):
        self._set_step("Step 2 — Checking Python…")
        ver = sys.version.split()[0]
        self._log_line(f"✔  Python {ver} at {sys.executable}", "ok")

        major, minor = sys.version_info[:2]
        if major == 3 and minor < 10:
            msg = ("Python " + str(major) + "." + str(minor) + " is too old.\n\n"
                   "PlayDate requires Python 3.10 or newer.\n\n"
                   "Please install Python 3.10 or later from python.org and re-run the installer.")
            raise RuntimeError(msg)

        if SYSTEM == "Linux":
            # Check python3-gi
            try:
                subprocess.check_call(
                    [sys.executable, "-c", "import gi"],
                    stderr=subprocess.DEVNULL
                )
                self._log_line("✔  python3-gi found", "ok")
            except subprocess.CalledProcessError:
                # Detect distro to show the right install command
                distro_id = ""
                try:
                    with open("/etc/os-release") as f:
                        for line in f:
                            if line.startswith("ID_LIKE=") or line.startswith("ID="):
                                distro_id = line.split("=", 1)[1].strip().strip('"').lower()
                                break
                except Exception:
                    pass

                if any(d in distro_id for d in ("debian", "ubuntu")):
                    cmd = "sudo apt install python3-gi python3-gi-cairo gir1.2-webkit2-4.0"
                elif any(d in distro_id for d in ("fedora", "rhel", "centos")):
                    cmd = "sudo dnf install python3-gobject webkit2gtk4.0"
                elif "arch" in distro_id:
                    cmd = "sudo pacman -S python-gobject webkit2gtk"
                else:
                    cmd = "See README.md for instructions for your distribution."

                raise RuntimeError(
                    "python3-gi is not installed. PlayDate requires system-level\n"
                    "GTK/WebKit libraries that cannot be installed via pip.\n\n"
                    f"Run this command, then re-run the installer:\n\n"
                    f"    {cmd}\n\n"
                    "See README.md for full prerequisites and troubleshooting."
                )
        self._advance("Step 2 — Python OK")

    def _step_venv(self):
        self._set_step("Step 3 — Setting up virtual environment…")
        if os.path.isdir(VENV_DIR):
            self._log_line("⚠  Virtual environment already exists — skipping", "warn")
        else:
            self._log_line("→  Creating virtual environment…", "info")
            args = [sys.executable, "-m", "venv"]
            if SYSTEM == "Linux":
                args.append("--system-site-packages")
            args.append(VENV_DIR)
            subprocess.check_call(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            self._log_line("✔  Virtual environment created", "ok")
        self._advance("Step 3 — Virtual environment ready")

    def _step_deps(self):
        self._set_step("Step 4 — Installing dependencies…")
        if not os.path.exists(REQ_FILE):
            self._log_line("⚠  No requirements.txt found — skipping", "warn")
            self._advance("Step 4 — Dependencies skipped")
            return

        # Count packages for progress
        with open(REQ_FILE) as f:
            pkgs = [l.strip() for l in f if l.strip() and not l.startswith("#")]
        total = len(pkgs)
        self._log_line("→  Upgrading pip…", "info")
        try:
            result = subprocess.run(
                [VENV_PYTHON, "-m", "pip", "install", "--quiet", "--upgrade", "pip"],
                capture_output=True, text=True
            )
            if result.returncode == 0:
                self._log_line("✔  pip upgraded", "ok")
            else:
                # Non-fatal: warn and continue — existing pip is likely fine
                self._log_line("⚠  pip upgrade failed (non-fatal) — continuing with existing pip", "warn")
                if result.stderr.strip():
                    for ln in result.stderr.strip().splitlines():
                        self._log_line(f"  {ln}", "warn")
        except Exception as e:
            self._log_line(f"⚠  pip upgrade skipped: {e}", "warn")

        self._log_line(f"→  Installing {total} packages…", "info")
        installed = 0

        # On Fedora/RHEL/Nobara, pip may try to rebuild selinux from source
        # and fail because the original build directory no longer exists.
        # --system-site-packages on the venv already provides the system
        # selinux bindings, so we tell pip to leave them alone.
        pip_cmd = [VENV_PYTHON, "-m", "pip", "install", "-r", REQ_FILE]
        if SYSTEM == "Linux":
            try:
                with open("/etc/os-release") as f:
                    os_release = f.read().lower()
            except Exception:
                os_release = ""
            if any(d in os_release for d in ("fedora", "rhel", "centos", "nobara")):
                self._log_line("\u2192  Fedora/Nobara detected \u2014 working around selinux build bug\u2026", "info")
                # pip tries to rebuild selinux from source and fails because
                # the original RPM build tree is gone. Solution: write a tiny
                # pure-Python selinux shim directly into the venv so that pip
                # resolves it as already satisfied without touching the system
                # package at all.
                import glob
                sp_dirs = (
                    glob.glob(os.path.join(VENV_DIR, "lib",   "python*", "site-packages")) +
                    glob.glob(os.path.join(VENV_DIR, "lib64", "python*", "site-packages"))
                )
                for sp in sp_dirs:
                    if not os.path.isdir(sp):
                        continue
                    # Remove any broken existing selinux artefacts
                    for pat in ("selinux*", "libselinux*"):
                        for path in glob.glob(os.path.join(sp, pat)):
                            try:
                                shutil.rmtree(path) if os.path.isdir(path) else os.remove(path)
                            except Exception:
                                pass
                    # Write a shim module so `import selinux` works
                    shim_path = os.path.join(sp, "selinux.py")
                    with open(shim_path, "w") as sf:
                        sf.write(
                            "# selinux shim — installed by PlayDate installer\n"
                            "# Prevents pip from trying to rebuild the system selinux package.\n"
                            "def is_selinux_enabled(): return False\n"
                            "def is_selinux_mls_enabled(): return False\n"
                            "def getfilecon(path): return None\n"
                            "def restorecon(path, recursive=False): pass\n"
                        )
                    # Write dist-info so pip sees it as installed
                    stub_dir = os.path.join(sp, "selinux-99.0.dist-info")
                    os.makedirs(stub_dir, exist_ok=True)
                    with open(os.path.join(stub_dir, "METADATA"), "w") as mf:
                        mf.write("Metadata-Version: 2.1\nName: selinux\nVersion: 99.0\nProvides-Extra:\n")
                    with open(os.path.join(stub_dir, "INSTALLER"), "w") as inf:
                        inf.write("pip\n")
                    with open(os.path.join(stub_dir, "RECORD"), "w") as rf:
                        rf.write(f"selinux.py,,\n{stub_dir}/METADATA,,\n{stub_dir}/INSTALLER,,\n{stub_dir}/RECORD,,\n")
                    self._log_line(f"  selinux shim installed in {os.path.basename(sp)}", "pkg")

        proc = subprocess.Popen(
            pip_cmd,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, bufsize=1
        )

        pip_log_lines = []
        for line in proc.stdout:
            line = line.rstrip()
            pip_log_lines.append(line)
            if any(line.startswith(k) for k in ("Collecting", "Downloading", "Installing collected")):
                installed += 1
                pct_sub = int(installed / max(total, 1) * 100)
                self._log_line(f"  [{pct_sub:3d}%] {line}", "pkg")
                overall_pct = int((self._steps_done + installed / max(total, 1)) / self._total_steps * 100)
                def _upd(p=overall_pct): self._prog.configure(value=p)
                self.after(0, _upd)
            elif line.strip():
                # Show ALL non-empty pip output — errors, warnings, OSErrors etc.
                tag = "err" if any(k in line for k in ("ERROR", "error", "Error", "OSError", "No such file")) else "pkg"
                self._log_line(f"  {line}", tag)

        proc.wait()
        if proc.returncode != 0:
            # Also write the full pip output to a log file next to install.py
            log_path = os.path.join(INSTALL_DIR, "install-error.log")
            try:
                with open(log_path, "w") as lf:
                    lf.write("\n".join(pip_log_lines))
                self._log_line(f"  Full output saved to: {log_path}", "warn")
            except Exception:
                pass
            raise RuntimeError("pip install failed. Check the log above or install-error.log.")

        self._log_line(f"✔  All dependencies installed", "ok")
        self._advance("Step 4 — Dependencies installed")

    def _step_launcher(self):
        self._set_step("Step 5 — Creating launcher…")
        if SYSTEM == "Windows":
            with open(LAUNCHER_BAT, "w") as f:
                f.write(f'@echo off\ncd /d "{INSTALL_DIR}"\nstart "" "{VENV_PYTHON}" "{MAIN_PY}"\n')
            self._log_line(f"✔  Launcher created: playdate-launch.bat", "ok")
        else:
            with open(LAUNCHER_SH, "w") as f:
                if SYSTEM == "Linux":
                    f.write(
                        f'#!/usr/bin/env bash\n'
                        f'cd "{INSTALL_DIR}"\n'
                        f'"{VENV_PYTHON}" "{MAIN_PY}" "$@" &\n'
                        f'PY_PID=$!\n'
                        f'if command -v wmctrl &>/dev/null; then\n'
                        f'    for i in $(seq 1 20); do\n'
                        f'        sleep 0.5\n'
                        f'        wmctrl -r "PlayDate" -x "playdate.playdate-launch" 2>/dev/null && break\n'
                        f'    done\n'
                        f'fi\n'
                        f'wait $PY_PID\n'
                    )
                else:
                    f.write(f'#!/usr/bin/env bash\ncd "{INSTALL_DIR}"\nexec "{VENV_PYTHON}" "{MAIN_PY}" "$@"\n')
            os.chmod(LAUNCHER_SH, 0o755)
            self._log_line(f"✔  Launcher created: playdate-launch.sh", "ok")
        self._advance("Step 5 — Launcher ready")

    def _step_register(self):
        if SYSTEM == "Darwin":
            self._set_step("Step 6 — Creating PlayDate.app…")
            self._register_macos()
        elif SYSTEM == "Linux":
            self._set_step("Step 6 — Registering desktop entry…")
            self._register_linux()
        elif SYSTEM == "Windows":
            self._set_step("Step 6 — Adding Start Menu shortcut…")
            self._register_windows()
        if self._shortcut_var.get():
            self._register_desktop_shortcut()
        self._advance("Step 6 — Registration complete")

    def _register_desktop_shortcut(self):
        """Copy a shortcut to the user's desktop (wallpaper area)."""
        if SYSTEM == "Linux":
            desktop_dir = os.path.expanduser("~/Desktop")
            if not os.path.isdir(desktop_dir):
                self._log_line("⚠  ~/Desktop not found — skipping desktop shortcut", "warn")
                return
            dest = os.path.join(desktop_dir, "PlayDate.desktop")
            src  = os.path.join(os.path.expanduser("~/.local/share/applications"), "playdate.desktop")
            try:
                shutil.copy(src, dest)
                os.chmod(dest, 0o755)
                self._log_line("✔  Desktop shortcut created", "ok")
            except Exception as e:
                self._log_line(f"⚠  Could not create desktop shortcut: {e}", "warn")
        elif SYSTEM == "Windows":
            desktop_dir = os.path.join(os.path.expanduser("~"), "Desktop")
            shortcut = os.path.join(desktop_dir, "PlayDate.lnk")
            ps = (
                f"$ws = New-Object -ComObject WScript.Shell; "
                f"$s = $ws.CreateShortcut('{shortcut}'); "
                f"$s.TargetPath = '{LAUNCHER_BAT}'; "
                f"$s.WorkingDirectory = '{INSTALL_DIR}'; "
                f"$s.IconLocation = '{ICON_PATH}'; "
                f"$s.Description = 'Your personal Steam library manager'; "
                f"$s.Save()"
            )
            result = subprocess.run(
                ["powershell", "-NoProfile", "-Command", ps],
                capture_output=True
            )
            if result.returncode == 0:
                self._log_line("✔  Desktop shortcut created", "ok")
            else:
                self._log_line("⚠  Could not create desktop shortcut (non-fatal)", "warn")
        elif SYSTEM == "Darwin":
            desktop_dir = os.path.expanduser("~/Desktop")
            dest = os.path.join(desktop_dir, "PlayDate.app")
            src  = os.path.expanduser("~/Applications/PlayDate.app")
            try:
                if os.path.isdir(dest):
                    shutil.rmtree(dest)
                shutil.copytree(src, dest)
                self._log_line("✔  Desktop shortcut created", "ok")
            except Exception as e:
                self._log_line(f"⚠  Could not create desktop shortcut: {e}", "warn")

    def _register_macos(self):
        app_bundle   = os.path.expanduser("~/Applications/PlayDate.app")
        app_contents = os.path.join(app_bundle, "Contents")
        app_macos    = os.path.join(app_contents, "MacOS")
        app_res      = os.path.join(app_contents, "Resources")

        if os.path.isdir(app_bundle):
            shutil.rmtree(app_bundle)
        os.makedirs(app_macos); os.makedirs(app_res)

        exe = os.path.join(app_macos, "PlayDate")
        with open(exe, "w") as f:
            f.write(f'#!/usr/bin/env bash\ncd "{INSTALL_DIR}"\nexec "{VENV_PYTHON}" "{MAIN_PY}"\n')
        os.chmod(exe, 0o755)

        with open(os.path.join(app_contents, "Info.plist"), "w") as f:
            f.write("""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
    <key>CFBundleName</key>        <string>PlayDate</string>
    <key>CFBundleDisplayName</key> <string>PlayDate</string>
    <key>CFBundleIdentifier</key>  <string>com.playdate.app</string>
    <key>CFBundleVersion</key>     <string>1.0</string>
    <key>CFBundleExecutable</key>  <string>PlayDate</string>
    <key>CFBundlePackageType</key> <string>APPL</string>
    <key>CFBundleIconFile</key>    <string>favicon</string>
    <key>LSUIElement</key>         <false/>
</dict></plist>""")

        if os.path.exists(ICON_PATH):
            shutil.copy(ICON_PATH, os.path.join(app_res, "favicon.png"))

        subprocess.run(["mdimport", app_bundle], capture_output=True)
        self._log_line("✔  PlayDate.app created in ~/Applications", "ok")

    def _register_linux(self):
        desktop_dir  = os.path.expanduser("~/.local/share/applications")
        desktop_file = os.path.join(desktop_dir, "playdate.desktop")
        os.makedirs(desktop_dir, exist_ok=True)
        with open(desktop_file, "w") as f:
            f.write(
                "[Desktop Entry]\nVersion=1.0\nType=Application\nName=PlayDate\n"
                "Comment=Your personal Steam library manager\n"
                f"Exec={LAUNCHER_SH}\nIcon={ICON_PATH}\nTerminal=false\n"
                "Categories=Game;\nStartupWMClass=main.py\n"
            )
        os.chmod(desktop_file, 0o755)
        subprocess.run(["update-desktop-database", desktop_dir], capture_output=True)
        self._log_line("✔  Desktop entry registered", "ok")

    def _register_windows(self):
        shortcut_dir = os.path.join(
            os.environ.get("APPDATA", ""),
            "Microsoft", "Windows", "Start Menu", "Programs"
        )
        shortcut = os.path.join(shortcut_dir, "PlayDate.lnk")
        ps = (
            f"$ws = New-Object -ComObject WScript.Shell; "
            f"$s = $ws.CreateShortcut('{shortcut}'); "
            f"$s.TargetPath = '{LAUNCHER_BAT}'; "
            f"$s.WorkingDirectory = '{INSTALL_DIR}'; "
            f"$s.IconLocation = '{ICON_PATH}'; "
            f"$s.Description = 'Your personal Steam library manager'; "
            f"$s.Save()"
        )
        result = subprocess.run(
            ["powershell", "-NoProfile", "-Command", ps],
            capture_output=True
        )
        if result.returncode == 0:
            self._log_line("✔  Start Menu shortcut created", "ok")
        else:
            self._log_line("⚠  Could not create Start Menu shortcut (non-fatal)", "warn")


if __name__ == "__main__":
    # Sanity: make sure tkinter is actually available
    try:
        import tkinter  # noqa
    except ImportError:
        print("ERROR: tkinter is not available. Install python3-tk and re-run.")
        sys.exit(1)

    app = InstallerApp()
    app.mainloop()
