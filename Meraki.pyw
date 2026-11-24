"""Windows launcher for the VIctory runtime bundled with Meraki."""

import codecs
import ctypes
from ctypes import wintypes
from datetime import datetime
import os
from pathlib import Path
import subprocess
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
import xml.etree.ElementTree as ET


ROOT = Path(__file__).resolve().parent
LOCAL = ROOT / ".local"
LOGS = LOCAL / "logs"
TARGET = ROOT / "baseline" / "target"

WM_SYSCOMMAND = 0x0112
SC_CLOSE = 0xF060
GA_ROOT = 2
# The runtime suspends for up to one second before saving its pipeline cache
# and ending; allow that plus the cache serialisation before forcing it.
CLOSE_GRACE_MS = 5000

_EnumWindowsProc = getattr(ctypes, "WINFUNCTYPE", ctypes.CFUNCTYPE)(
    wintypes.BOOL, wintypes.HWND, wintypes.LPARAM
)


def _user32():
    """Load and type the user32 entry points used to close a title window."""
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    user32.EnumWindows.argtypes = [_EnumWindowsProc, wintypes.LPARAM]
    user32.EnumWindows.restype = wintypes.BOOL
    user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
    user32.GetWindowThreadProcessId.restype = wintypes.DWORD
    user32.IsWindowVisible.argtypes = [wintypes.HWND]
    user32.IsWindowVisible.restype = wintypes.BOOL
    user32.GetAncestor.argtypes = [wintypes.HWND, wintypes.UINT]
    user32.GetAncestor.restype = wintypes.HWND
    user32.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
    user32.PostMessageW.restype = wintypes.BOOL
    return user32


def find_visible_window(pid):
    """Return a visible top-level window owned by ``pid``, or None."""
    if not pid:
        return None
    try:
        user32 = _user32()
    except (OSError, AttributeError):
        return None
    found = []

    @_EnumWindowsProc
    def visit(hwnd, _):
        owner = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.pointer(owner))
        if owner.value != pid or not user32.IsWindowVisible(hwnd):
            return True
        if user32.GetAncestor(hwnd, GA_ROOT) != hwnd:
            return True
        found.append(hwnd)
        return False

    try:
        user32.EnumWindows(visit, 0)
    except OSError:
        return None
    return found[0] if found else None


def post_system_close(hwnd):
    """Post WM_SYSCOMMAND/SC_CLOSE to ``hwnd`` without waiting for it."""
    if not hwnd:
        return False
    try:
        return bool(_user32().PostMessageW(hwnd, WM_SYSCOMMAND, SC_CLOSE, 0))
    except (OSError, AttributeError):
        return False


def detect_title():
    drive = Path("D:/")
    for pattern in ("MicrosoftGame.Config", "*/MicrosoftGame.Config"):
        for manifest in drive.glob(pattern):
            try:
                title = ET.parse(manifest).find("./ExecutableList/Executable")
                if title is None:
                    continue
                package = manifest.parent.resolve()
                exe = (package / title.attrib["Name"]).resolve()
                if package in exe.parents and exe.is_file() and exe.suffix.lower() == ".exe":
                    return str(exe)
            except (ET.ParseError, OSError, KeyError, ValueError):
                continue
    return ""


def runtime_command(action, exe):
    diag = TARGET / "diag" / "victory.exe"
    release = TARGET / "release" / "victory.exe"
    runtime = diag if diag.is_file() else release
    if not runtime.is_file() or (action == "launch" and runtime != diag):
        raise ValueError("Build the diagnostics runtime first. Run .\\Build.ps1 in the Meraki folder.")
    if action == "launch":
        return [str(runtime), "run", str(exe), "--execute"]
    if action == "check":
        return [str(runtime), "run", str(exe)]
    return [str(runtime), "inspect", str(exe)]


def archive_report(package):
    lines = ["Package archives"]
    for name in ("common.rpf", "levels.rpf", "audio.rpf"):
        try:
            with (package / name).open("rb") as archive:
                magic = archive.read(4)
            status = "RPF9 header detected" if magic == b"9FPR" else "Unrecognized header"
        except FileNotFoundError:
            status = "Missing"
        except OSError as error:
            status = str(error)
        lines.append(f"  {name}: {status}")
    return "\n".join(lines) + "\n\n"


class Launcher:
    def __init__(self, root):
        self.root = root
        self.process = None
        self.reader = None
        self.stopping = False
        self.closing = False
        self.stop_timer = None
        self.log_path = None
        root.title("Meraki")
        root.geometry("800x510")
        root.minsize(570, 360)
        root.protocol("WM_DELETE_WINDOW", self.close)
        frame = ttk.Frame(root, padding=18)
        frame.pack(fill="both", expand=True)
        frame.columnconfigure(0, weight=1)
        frame.rowconfigure(5, weight=1)
        ttk.Label(frame, text="Meraki", font=("Segoe UI", 20, "bold")).grid(sticky="w")
        ttk.Label(frame, text="Xbox title executable").grid(row=1, sticky="w", pady=(12, 4))
        self.path = tk.StringVar(value=detect_title())
        self.entry = ttk.Entry(frame, textvariable=self.path)
        self.entry.grid(row=2, column=0, sticky="ew")
        self.browse = ttk.Button(frame, text="Browse...", command=self.choose)
        self.browse.grid(row=2, column=1, padx=(8, 0))
        bar = ttk.Frame(frame)
        bar.grid(row=3, columnspan=2, sticky="w", pady=(12, 8))
        self.inspect = ttk.Button(bar, text="Inspect", command=lambda: self.start("inspect"))
        self.check = ttk.Button(bar, text="Check imports", command=lambda: self.start("check"))
        self.launch = ttk.Button(bar, text="Launch with WARP", command=lambda: self.start("launch"))
        self.stop = ttk.Button(bar, text="Stop", command=self.terminate, state="disabled")
        for button in (self.inspect, self.check, self.launch, self.stop):
            button.pack(side="left", padx=(0, 6))
        self.capture = tk.BooleanVar(value=False)
        self.capture_toggle = ttk.Checkbutton(frame, text="Save diagnostic frames on launch",
                                              variable=self.capture)
        self.capture_toggle.grid(row=6, column=0, sticky="w", pady=(8, 0))
        self.status = tk.StringVar(value="Ready. WARP uses the CPU to render graphics.")
        ttk.Label(frame, textvariable=self.status).grid(row=4, columnspan=2, sticky="w", pady=(0, 5))
        console = ttk.Frame(frame)
        console.grid(row=5, columnspan=2, sticky="nsew")
        self.output = tk.Text(console, wrap="word", font=("Consolas", 10), state="disabled")
        scroll = ttk.Scrollbar(console, command=self.output.yview)
        self.output.configure(yscrollcommand=scroll.set)
        scroll.pack(side="right", fill="y")
        self.output.pack(fill="both", expand=True)
        self.open_log = ttk.Button(frame, text="Open full log", command=self.show_log, state="disabled")
        self.open_log.grid(row=6, column=1, sticky="e", pady=(8, 0))

    def choose(self):
        exe = filedialog.askopenfilename(filetypes=[("Title executable", "*.exe")])
        if exe:
            self.path.set(exe)

    def start(self, action):
        if self.process:
            return
        try:
            exe = Path(self.path.get().strip().strip('"')).resolve()
            if not exe.is_file() or exe.suffix.lower() != ".exe":
                raise ValueError("Choose the Xbox title executable from your package.")
            command = runtime_command(action, exe)
            LOGS.mkdir(parents=True, exist_ok=True)
            temp = LOCAL / "tmp"
            temp.mkdir(exist_ok=True)
            env = {k: v for k, v in os.environ.items() if not k.upper().startswith("VICTORY_")}
            env.update(VICTORY_GAME_DIR=str(exe.parent), VICTORY_CACHE_DIR=str(LOCAL / "cache"),
                       VICTORY_DATA_DIR=str(LOCAL / "data"), VICTORY_D3D12_WARP="1",
                       TMP=str(temp), TEMP=str(temp), NO_COLOR="1")
            path = LOGS / f"{action}-{datetime.now():%Y%m%d-%H%M%S-%f}.log"
            with path.open("xb") as sink:
                if action == "launch" and self.capture.get():
                    frames = path.with_suffix("")
                    frames.mkdir()
                    env["VICTORY_CAPTURE"] = str(frames)
                    sink.write(f"Diagnostic frames: {frames}\n".encode("utf-8"))
                    sink.flush()
                if action == "inspect":
                    sink.write(archive_report(exe.parent).encode("utf-8"))
                    sink.flush()
                self.reader = path.open("rb")
                self.process = subprocess.Popen(command, cwd=ROOT, env=env, stdout=sink,
                                                stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                                                creationflags=subprocess.CREATE_NO_WINDOW)
            self.log_path = path
        except (OSError, ValueError) as error:
            if self.reader:
                self.reader.close()
                self.reader = None
            messagebox.showerror("Meraki", str(error), parent=self.root)
            return
        self.decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")
        self.output.configure(state="normal")
        self.output.delete("1.0", "end")
        self.output.configure(state="disabled")
        for control in (self.entry, self.browse, self.inspect, self.check, self.launch, self.capture_toggle):
            control.configure(state="disabled")
        self.open_log.configure(state="normal")
        self.stop.configure(state="normal")
        self.status.set({"inspect": "Inspecting executable...", "check": "Checking title imports...",
                         "launch": "Running title with WARP..."}[action])
        self.poll()

    def poll(self):
        code = self.process.poll()
        chunk = self.reader.read(65536)
        done = code is not None and not chunk
        content = self.decoder.decode(chunk, final=done)
        if content:
            self.output.configure(state="normal")
            self.output.insert("end", content)
            self.output.delete("1.0", "end-100000c")
            self.output.see("end")
            self.output.configure(state="disabled")
        if not done:
            self.root.after(10 if chunk else 180, self.poll)
            return
        self._cancel_stop_timer()
        self.reader.close()
        self.reader = None
        self.process = None
        self.status.set("Stopped." if self.stopping else f"Runtime exited with code {code}.")
        self.stopping = False
        self.stop.configure(state="disabled")
        if self.closing:
            self._finish_close()
            return
        for control in (self.entry, self.browse, self.inspect, self.check, self.launch, self.capture_toggle):
            control.configure(state="normal")

    def show_log(self):
        try:
            os.startfile(self.log_path)
        except OSError as error:
            messagebox.showerror("Open log", str(error), parent=self.root)

    def terminate(self):
        """Ask the title to close its window, forcing it after a bounded wait."""
        process = self.process
        if not process or process.poll() is not None or self.stopping:
            return
        self.stopping = True
        self.status.set("Stopping...")
        self.stop.configure(state="disabled")
        hwnd = find_visible_window(process.pid)
        if not hwnd or not post_system_close(hwnd):
            self._force_stop(process)
            return
        self.stop_timer = self.root.after(CLOSE_GRACE_MS, self._force_stop, process)

    def _force_stop(self, process):
        if self.process is not process:
            return
        self.stop_timer = None
        if process.poll() is None:
            try:
                process.terminate()
            except OSError:
                pass

    def _cancel_stop_timer(self):
        timer = getattr(self, "stop_timer", None)
        self.stop_timer = None
        if timer is None:
            return
        try:
            self.root.after_cancel(timer)
        except Exception:
            pass

    def _finish_close(self):
        self._cancel_stop_timer()
        reader, self.reader = self.reader, None
        if reader:
            try:
                reader.close()
            except OSError:
                pass
        self.root.destroy()

    def close(self):
        if self.process and self.process.poll() is None:
            if self.closing:
                return
            if not messagebox.askyesno("Close Meraki", "Stop the running process and close Meraki?"):
                return
            self.closing = True
            self.terminate()
            return
        self._finish_close()


if __name__ == "__main__":
    window = tk.Tk()
    Launcher(window)
    window.mainloop()
