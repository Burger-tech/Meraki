"""Windows launcher for the VIctory runtime bundled with Meraki."""

import codecs
import ctypes
from ctypes import wintypes
from datetime import datetime
import os
from pathlib import Path
import re
import subprocess
import sys
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

FONT = "Segoe UI"
MONO = "Consolas"
BG = "#edf1f6"
CARD = "#ffffff"
INK = "#17222e"
MUTED = "#5d6d7e"
BORDER = "#d5dde6"
ACCENT = "#0b63b6"
DANGER = "#b3261e"

STATUS_TONES = {
    "ready": {"bg": "#eaf1fa", "fg": "#173f6b", "muted": "#4b6786", "accent": "#3b72a8"},
    "busy": {"bg": "#e7f0fe", "fg": "#0b4f9e", "muted": "#426994", "accent": "#0b63b6"},
    "running": {"bg": "#e6f5ec", "fg": "#135c32", "muted": "#477a5c", "accent": "#1a7f37"},
    "stopping": {"bg": "#fff3d8", "fg": "#6b4a00", "muted": "#80693a", "accent": "#9a6700"},
    "done": {"bg": "#eef1f5", "fg": "#2a3a4a", "muted": "#5d6d7e", "accent": "#6b7b8b"},
    "error": {"bg": "#fdecea", "fg": "#7a1f19", "muted": "#8c534e", "accent": "#b3261e"},
}

CHIP_TONES = {
    "ok": ("#e3f4e9", "#165f34"),
    "unknown": ("#fff2d6", "#7a5600"),
    "missing": ("#eef1f4", "#55667a"),
    "error": ("#fde9e7", "#8a1d17"),
}

ARCHIVES = ("common.rpf", "levels.rpf", "audio.rpf")

_ANSI = re.compile(r"\x1b\[[0-9;]*m")
_LOG_PREFIX = re.compile(r"^\d{4}-\d\d-\d\dT\S+\s+(?:INFO|WARN|ERROR)\s+\S+:\s*")
_FRAME = re.compile(r"frame presented.*?\bframe=(\d+)")
_FPS = re.compile(r"([\d.]+) fps, ([\d.]+) ms/frame")
_IMPORTS = re.compile(r"imports bound hle=(\d+) host=(\d+) missing=(\d+)")
_PRESENT = re.compile(r"presenting to a window width=(\d+) height=(\d+)")

_EnumWindowsProc = getattr(ctypes, "WINFUNCTYPE", ctypes.CFUNCTYPE)(
    wintypes.BOOL, wintypes.HWND, wintypes.LPARAM
)


def enable_dpi_awareness():
    """Ask Windows for crisp text scaling; safe to skip when unavailable."""
    if sys.platform != "win32":
        return
    windll = getattr(ctypes, "windll", None)
    if windll is None:
        return
    for library, name, value in (("shcore", "SetProcessDpiAwareness", 1),
                                 ("user32", "SetProcessDPIAware", None)):
        try:
            function = getattr(getattr(windll, library), name)
            function() if value is None else function(value)
            return
        except (AttributeError, OSError, TypeError):
            continue


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


def resolve_runtime():
    """Return the preferred runtime path and its profile, or (None, None)."""
    diag = TARGET / "diag" / "victory.exe"
    release = TARGET / "release" / "victory.exe"
    if diag.is_file():
        return diag, "diag"
    if release.is_file():
        return release, "release"
    return None, None


def runtime_state():
    """Describe build availability for the launcher diagnostics panel."""
    runtime, profile = resolve_runtime()
    if runtime is None:
        return "missing", "Not built"
    if profile == "diag":
        return "diag", "Diagnostics ready"
    return "release", "Release only"


def runtime_command(action, exe):
    runtime, profile = resolve_runtime()
    if runtime is None or (action == "launch" and profile != "diag"):
        raise ValueError("Build the diagnostics runtime first. Run .\\Build.ps1 in the Meraki folder.")
    if action == "launch":
        return [str(runtime), "run", str(exe), "--execute"]
    if action == "check":
        return [str(runtime), "run", str(exe)]
    return [str(runtime), "inspect", str(exe)]


def archive_status(package):
    """Return (name, state, detail) for each package archive header."""
    rows = []
    for name in ARCHIVES:
        try:
            with (package / name).open("rb") as archive:
                magic = archive.read(4)
            if magic == b"9FPR":
                state, detail = "ok", "RPF9 header detected"
            else:
                state, detail = "unknown", "Unrecognized header"
        except FileNotFoundError:
            state, detail = "missing", "Missing"
        except OSError as error:
            state, detail = "error", str(error)
        rows.append((name, state, detail))
    return rows


def archive_report(package):
    lines = ["Package archives"]
    for name, _state, detail in archive_status(package):
        lines.append(f"  {name}: {detail}")
    return "\n".join(lines) + "\n\n"
def describe_log_chunk(content):
    """Summarise the newest useful runtime output for the status band."""
    error_detail = ""
    warning_detail = ""
    frame_detail = ""
    fps_detail = ""
    info_detail = ""
    last_detail = ""
    for raw in content.splitlines():
        line = _ANSI.sub("", raw).strip()
        if not line:
            continue
        clean = _LOG_PREFIX.sub("", line).strip()
        upper = line.upper()
        last_detail = clean or line
        if " ERROR " in upper or upper.startswith("ERROR") or "TRACEBACK" in upper:
            error_detail = clean or line
            continue
        if " WARN " in upper or upper.startswith("WARN") or " WARNING " in upper:
            warning_detail = clean or line
            continue
        match = _FPS.search(line)
        if match:
            fps_detail = f"{match.group(1)} FPS  ·  {match.group(2)} ms/frame"
            continue
        match = _FRAME.search(line)
        if match:
            frame_detail = f"Rendering  ·  frame {match.group(1)}"
            continue
        match = _IMPORTS.search(line)
        if match:
            info_detail = f"Imports bound  ·  {match.group(3)} missing"
            continue
        match = _PRESENT.search(line)
        if match:
            info_detail = f"Presenting  ·  {match.group(1)}x{match.group(2)}"
            continue
        lowered = line.lower()
        if "host device on the software adapter" in lowered:
            info_detail = "D3D12 software adapter (WARP) ready"
        elif "host d3d12 device ready" in lowered:
            info_detail = "D3D12 device ready"
        elif "diagnostic frames" in lowered:
            info_detail = "Diagnostic capture active"
    detail = error_detail or fps_detail or frame_detail or info_detail or warning_detail or last_detail
    if len(detail) > 160:
        detail = detail[:157].rstrip() + "..."
    tone = "error" if error_detail else ("running" if (fps_detail or frame_detail) else None)
    return detail, tone


def _set_status(launcher, text, detail=None, tone=None):
    launcher.status.set(text)
    if detail is not None:
        variable = getattr(launcher, "detail", None)
        if variable is not None:
            variable.set(detail)
    if tone:
        _paint_status(launcher, tone)


def _paint_status(launcher, tone):
    palette = STATUS_TONES.get(tone, STATUS_TONES["ready"])
    for name in ("status_panel", "status_text_frame", "status_title",
                 "status_detail_label", "status_clock_frame", "status_clock_label",
                 "status_clock_caption"):
        widget = getattr(launcher, name, None)
        if widget is not None:
            widget.configure(bg=palette["bg"])
    title = getattr(launcher, "status_title", None)
    if title is not None:
        title.configure(fg=palette["fg"])
    clock = getattr(launcher, "status_clock_label", None)
    if clock is not None:
        clock.configure(fg=palette["fg"])
    detail = getattr(launcher, "status_detail_label", None)
    if detail is not None:
        detail.configure(fg=palette["muted"])
    caption = getattr(launcher, "status_clock_caption", None)
    if caption is not None:
        caption.configure(fg=palette["muted"])
    accent = getattr(launcher, "status_accent", None)
    if accent is not None:
        accent.configure(bg=palette["accent"])


def _set_controls(launcher, enabled):
    state = "normal" if enabled else "disabled"
    for name in ("entry", "browse", "inspect", "check", "launch", "capture_toggle"):
        control = getattr(launcher, name, None)
        if control is not None:
            control.configure(state=state)


def _append_output(launcher, content):
    output = launcher.output
    start_line = None
    try:
        start_line = int(str(output.index("end-1c")).split(".", 1)[0])
    except Exception:
        start_line = None
    output.configure(state="normal")
    output.insert("end", content)
    if start_line is not None and hasattr(output, "tag_add"):
        for offset, raw in enumerate(content.splitlines()):
            tag = _line_tag(raw)
            if tag:
                output.tag_add(tag, f"{start_line + offset}.0", f"{start_line + offset}.end")
    output.delete("1.0", "end-100000c")
    output.see("end")
    output.configure(state="disabled")


def _line_tag(raw):
    upper = raw.upper()
    if " ERROR " in upper or upper.startswith("ERROR") or "TRACEBACK" in upper:
        return "error"
    if " WARN " in upper or upper.startswith("WARN") or " WARNING " in upper:
        return "warn"
    if "FRAME PRESENTED" in upper or "IMPORTS BOUND" in upper or "DEVICE READY" in upper:
        return "ok"
    if "DIAGNOSTIC FRAMES" in upper:
        return "info"
    return None


def _note_chunk(launcher, content):
    detail, tone = describe_log_chunk(content)
    if not detail:
        return
    variable = getattr(launcher, "detail", None)
    if variable is not None:
        variable.set(detail)
    if tone:
        _paint_status(launcher, tone)


def _refresh_clock(launcher):
    variable = getattr(launcher, "clock_var", None)
    started = getattr(launcher, "started_at", None)
    if variable is None or started is None:
        return
    seconds = max(0, int((datetime.now() - started).total_seconds()))
    variable.set(f"{seconds // 60:02d}:{seconds % 60:02d}")


def _refresh_session_info(launcher):
    if getattr(launcher, "log_name_var", None) is None:
        return
    log = getattr(launcher, "log_path", None)
    if log is None:
        launcher.log_name_var.set("No session yet")
        launcher.log_path_var.set("Start an action to create a session log.")
        launcher.open_log.configure(state="disabled")
    else:
        path = Path(log)
        launcher.log_name_var.set(path.name)
        launcher.log_path_var.set(str(path))
        launcher.open_log.configure(state="normal")
    frames = getattr(launcher, "frames_path", None)
    if frames is None:
        launcher.frames_name_var.set("Off")
        launcher.frames_path_var.set("Enable capture above to save presented frames.")
        open_frames = getattr(launcher, "open_frames", None)
        if open_frames is not None:
            open_frames.configure(state="disabled")
    else:
        path = Path(frames)
        launcher.frames_name_var.set(path.name + " (folder)")
        launcher.frames_path_var.set(str(path))
        open_frames = getattr(launcher, "open_frames", None)
        if open_frames is not None and path.is_dir():
            open_frames.configure(state="normal")


class Launcher:
    def __init__(self, root):
        self.root = root
        self.process = None
        self.reader = None
        self.stopping = False
        self.closing = False
        self.stop_timer = None
        self.log_path = None
        self.frames_path = None
        self.started_at = None
        self.action = None
        self.package_dir = None
        self.path = tk.StringVar(value=detect_title())
        self.capture = tk.BooleanVar(value=False)
        self.status = tk.StringVar(value="Ready. WARP uses the CPU to render graphics.")
        self.detail = tk.StringVar(value="Choose a package, then inspect it or launch with WARP.")
        self.clock_var = tk.StringVar(value="00:00")
        self.package_var = tk.StringVar(value="No package selected.")
        self.executable_var = tk.StringVar(value="No executable")
        self.manifest_var = tk.StringVar(value="No manifest")
        self.runtime_name_var = tk.StringVar(value="Checking build...")
        self.runtime_path_var = tk.StringVar(value="")
        self.log_name_var = tk.StringVar(value="No session yet")
        self.log_path_var = tk.StringVar(value="Start an action to create a session log.")
        self.frames_name_var = tk.StringVar(value="Off")
        self.frames_path_var = tk.StringVar(value="Enable capture above to save presented frames.")
        root.title("Meraki")
        root.geometry("1000x760")
        root.minsize(800, 680)
        root.configure(bg=BG)
        root.protocol("WM_DELETE_WINDOW", self.close)
        self._build()
        try:
            self.path.trace_add("write", lambda *_args: self._refresh_package())
        except (AttributeError, tk.TclError):
            pass
        self._refresh_package()
        self._refresh_runtime()
        build_state, _build_label = runtime_state()
        if build_state == "missing":
            self.detail.set("Runtime not built. Run .\\Build.ps1 before launching.")
            _paint_status(self, "stopping")
        elif build_state == "release":
            self.detail.set("Release build only. Build diagnostics to launch with WARP.")
            _paint_status(self, "stopping")
        elif self.package_dir is not None:
            self.detail.set("Package ready. Inspect it, check imports or launch with WARP.")
        _refresh_session_info(self)
        self.root.bind("<Control-o>", lambda _event: self.choose())
        self.root.bind("<F5>", lambda _event: self.start("launch"))
        self.root.bind("<Escape>", lambda _event: self.terminate())
        self.root.bind("<Control-Shift-C>", lambda _event: self.copy_output())

    # -- layout ---------------------------------------------------------

    def _build(self):
        style = ttk.Style(self.root)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        style.configure("Card.TFrame", background=CARD)
        style.configure("CardHead.TLabel", background=CARD, foreground=INK,
                        font=(FONT, 9, "bold"))
        style.configure("Secondary.TButton", font=(FONT, 9), padding=(13, 8),
                        background="#e8edf4", foreground=INK, borderwidth=0)
        style.map("Secondary.TButton", background=[("active", "#dce4ee"), ("disabled", "#f1f3f6")],
                  foreground=[("disabled", "#8c99a6")])
        style.configure("Accent.TButton", font=(FONT, 10, "bold"), padding=(20, 10),
                        background=ACCENT, foreground="#ffffff", borderwidth=0)
        style.map("Accent.TButton", background=[("active", "#0957a3"), ("pressed", "#084a8b"),
                                               ("disabled", "#a7bdd5")],
                  foreground=[("disabled", "#eef3f8")])
        style.configure("Danger.TButton", font=(FONT, 9, "bold"), padding=(15, 9),
                        background=DANGER, foreground="#ffffff", borderwidth=0)
        style.map("Danger.TButton", background=[("active", "#96201a"), ("pressed", "#821a15"),
                                               ("disabled", "#e2c7c4")],
                  foreground=[("disabled", "#f7eceb")])
        style.configure("Path.TEntry", fieldbackground="#f7f9fc", foreground=INK,
                        padding=(8, 7), borderwidth=1)
        style.configure("Card.TCheckbutton", background=CARD, foreground=INK, font=(FONT, 9))
        style.map("Card.TCheckbutton", background=[("active", CARD)], foreground=[("disabled", "#8c99a6")])

        outer = tk.Frame(self.root, bg=BG)
        outer.pack(fill="both", expand=True, padx=18, pady=16)

        header = tk.Frame(outer, bg=BG)
        header.pack(fill="x")
        tk.Label(header, text="Meraki", font=(FONT, 23, "bold"), bg=BG, fg=INK).pack(anchor="w")
        tk.Label(header, text="Xbox title launcher for Windows 11  ·  WARP renderer",
                 font=(FONT, 10), bg=BG, fg=MUTED).pack(anchor="w", pady=(1, 0))

        self._build_status(outer)
        self._build_package(outer)
        self._build_body(outer)
        tk.Label(outer,
                 text="Session logs, diagnostic frames, shader caches and saves stay in .local",
                 font=(FONT, 8), bg=BG, fg=MUTED).pack(anchor="w", pady=(10, 0))

    def _build_status(self, parent):
        palette = STATUS_TONES["ready"]
        self.status_panel = tk.Frame(parent, bg=palette["bg"], highlightbackground=BORDER,
                                     highlightthickness=1, bd=0)
        self.status_panel.pack(fill="x", pady=(14, 0))
        self.status_panel.grid_columnconfigure(1, weight=1)
        self.status_accent = tk.Frame(self.status_panel, bg=palette["accent"], width=6)
        self.status_accent.grid(row=0, column=0, sticky="ns")
        self.status_text_frame = tk.Frame(self.status_panel, bg=palette["bg"])
        self.status_text_frame.grid(row=0, column=1, sticky="ew", padx=14, pady=10)
        self.status_text_frame.grid_columnconfigure(0, weight=1)
        self.status_title = tk.Label(self.status_text_frame, textvariable=self.status,
                                     font=(FONT, 13, "bold"), bg=palette["bg"],
                                     fg=palette["fg"], anchor="w")
        self.status_title.grid(row=0, column=0, sticky="w")
        self.status_detail_label = tk.Label(self.status_text_frame, textvariable=self.detail,
                                            font=(FONT, 9), bg=palette["bg"],
                                            fg=palette["muted"], anchor="w", justify="left",
                                            wraplength=600)
        self.status_detail_label.grid(row=1, column=0, sticky="w", pady=(2, 0))
        self.status_clock_frame = tk.Frame(self.status_panel, bg=palette["bg"])
        self.status_clock_frame.grid(row=0, column=2, sticky="e", padx=(10, 16))
        self.status_clock_caption = tk.Label(self.status_clock_frame, text="SESSION",
                                             font=(FONT, 7, "bold"), bg=palette["bg"],
                                             fg=palette["muted"])
        self.status_clock_caption.pack(anchor="e")
        self.status_clock_label = tk.Label(self.status_clock_frame, textvariable=self.clock_var,
                                           font=(MONO, 15, "bold"), bg=palette["bg"],
                                           fg=palette["fg"])
        self.status_clock_label.pack(anchor="e")

    def _build_package(self, parent):
        card = tk.Frame(parent, bg=CARD, highlightbackground=BORDER, highlightthickness=1, bd=0)
        card.pack(fill="x", pady=(14, 0))
        inner = tk.Frame(card, bg=CARD)
        inner.pack(fill="x", padx=16, pady=13)

        heading = tk.Frame(inner, bg=CARD)
        heading.pack(fill="x")
        tk.Label(heading, text="TITLE PACKAGE", font=(FONT, 8, "bold"), bg=CARD,
                 fg=MUTED).pack(side="left")
        self.package_state_label = tk.Label(heading, text="No package", font=(FONT, 8, "bold"),
                                            bg="#eef1f4", fg="#55667a", padx=8, pady=2)
        self.package_state_label.pack(side="right")

        row = tk.Frame(inner, bg=CARD)
        row.pack(fill="x", pady=(7, 0))
        self.entry = ttk.Entry(row, textvariable=self.path, style="Path.TEntry")
        self.entry.pack(side="left", fill="x", expand=True)
        self.browse = ttk.Button(row, text="Browse...", style="Secondary.TButton",
                                 command=self.choose)
        self.browse.pack(side="left", padx=(9, 0))
        self.open_package = ttk.Button(row, text="Folder", style="Secondary.TButton",
                                       command=self.show_package, state="disabled")
        self.open_package.pack(side="left", padx=(7, 0))

        tk.Label(inner, textvariable=self.package_var, font=(MONO, 8), bg=CARD, fg=MUTED,
                 anchor="w", justify="left", wraplength=700).pack(fill="x", pady=(7, 0))
        meta = tk.Frame(inner, bg=CARD)
        meta.pack(fill="x", pady=(4, 0))
        tk.Label(meta, text="Executable", font=(FONT, 8), bg=CARD, fg=MUTED).pack(side="left")
        tk.Label(meta, textvariable=self.executable_var, font=(FONT, 9, "bold"), bg=CARD,
                 fg=INK).pack(side="left", padx=(6, 20))
        tk.Label(meta, text="Manifest", font=(FONT, 8), bg=CARD, fg=MUTED).pack(side="left")
        tk.Label(meta, textvariable=self.manifest_var, font=(FONT, 9), bg=CARD,
                 fg=MUTED).pack(side="left", padx=(6, 0))

        archives = tk.Frame(inner, bg=CARD)
        archives.pack(fill="x", pady=(9, 0))
        tk.Label(archives, text="ARCHIVES", font=(FONT, 8, "bold"), bg=CARD,
                 fg=MUTED).pack(side="left", padx=(0, 10))
        self.archive_labels = {}
        for name in ARCHIVES:
            label = tk.Label(archives, text=f"{name}  ·  Not checked", font=(FONT, 8, "bold"),
                             bg="#eef1f4", fg="#55667a", padx=8, pady=3)
            label.pack(side="left", padx=(0, 7))
            self.archive_labels[name] = label

        tk.Frame(inner, bg=BORDER, height=1).pack(fill="x", pady=(12, 11))
        actions = tk.Frame(inner, bg=CARD)
        actions.pack(fill="x")
        self.inspect = ttk.Button(actions, text="Inspect", style="Secondary.TButton",
                                  command=lambda: self.start("inspect"))
        self.inspect.pack(side="left", padx=(0, 7))
        self.check = ttk.Button(actions, text="Check imports", style="Secondary.TButton",
                                command=lambda: self.start("check"))
        self.check.pack(side="left")
        self.capture_toggle = ttk.Checkbutton(
            actions, text="Save diagnostic frames on launch", variable=self.capture,
            style="Card.TCheckbutton")
        self.capture_toggle.pack(side="left", padx=(17, 0))
        self.launch = ttk.Button(actions, text="Launch with WARP", style="Accent.TButton",
                                 command=lambda: self.start("launch"))
        self.launch.pack(side="right")
        self.stop = ttk.Button(actions, text="Stop", style="Danger.TButton",
                               command=self.terminate, state="disabled")
        self.stop.pack(side="right", padx=(0, 9))
    def _build_body(self, parent):
        body = tk.Frame(parent, bg=BG)
        body.pack(fill="both", expand=True, pady=(14, 0))
        body.grid_rowconfigure(0, weight=1)
        body.grid_columnconfigure(0, minsize=324)
        body.grid_columnconfigure(1, weight=1)

        session = tk.Frame(body, bg=CARD, highlightbackground=BORDER, highlightthickness=1, bd=0)
        session.grid(row=0, column=0, sticky="nsew", padx=(0, 14))
        s = tk.Frame(session, bg=CARD)
        s.pack(fill="both", expand=True, padx=15, pady=13)
        tk.Label(s, text="DIAGNOSTICS", font=(FONT, 8, "bold"), bg=CARD, fg=MUTED).pack(anchor="w")

        tk.Label(s, text="RUNTIME", font=(FONT, 8), bg=CARD, fg=MUTED).pack(anchor="w", pady=(9, 2))
        runtime_row = tk.Frame(s, bg=CARD)
        runtime_row.pack(fill="x")
        tk.Label(runtime_row, textvariable=self.runtime_name_var, font=(FONT, 9, "bold"),
                 bg=CARD, fg=INK).pack(side="left")
        self.runtime_state_label = tk.Label(runtime_row, text="Checking", font=(FONT, 8, "bold"),
                                            bg="#eef1f4", fg="#55667a", padx=6, pady=1)
        self.runtime_state_label.pack(side="right")
        tk.Label(s, textvariable=self.runtime_path_var, font=(MONO, 8), bg=CARD, fg=MUTED,
                 wraplength=285, justify="left").pack(anchor="w", pady=(1, 0))

        tk.Label(s, text="SESSION LOG", font=(FONT, 8), bg=CARD, fg=MUTED).pack(anchor="w", pady=(9, 2))
        tk.Label(s, textvariable=self.log_name_var, font=(FONT, 9, "bold"), bg=CARD,
                 fg=INK).pack(anchor="w")
        tk.Label(s, textvariable=self.log_path_var, font=(MONO, 8), bg=CARD, fg=MUTED,
                 wraplength=285, justify="left").pack(anchor="w", pady=(1, 0))
        self.open_log = ttk.Button(s, text="Open full log", style="Secondary.TButton",
                                   command=self.show_log, state="disabled")
        self.open_log.pack(fill="x", pady=(4, 0))

        tk.Label(s, text="DIAGNOSTIC FRAMES", font=(FONT, 8), bg=CARD, fg=MUTED).pack(
            anchor="w", pady=(9, 2))
        tk.Label(s, textvariable=self.frames_name_var, font=(FONT, 9, "bold"), bg=CARD,
                 fg=INK).pack(anchor="w")
        tk.Label(s, textvariable=self.frames_path_var, font=(MONO, 8), bg=CARD, fg=MUTED,
                 wraplength=285, justify="left").pack(anchor="w", pady=(1, 0))
        self.open_frames = ttk.Button(s, text="Open frames", style="Secondary.TButton",
                                      command=self.show_frames, state="disabled")
        self.open_frames.pack(fill="x", pady=(4, 0))

        logcard = tk.Frame(body, bg=CARD, highlightbackground=BORDER, highlightthickness=1, bd=0)
        logcard.grid(row=0, column=1, sticky="nsew")
        l = tk.Frame(logcard, bg=CARD)
        l.pack(fill="both", expand=True, padx=14, pady=12)
        loghead = tk.Frame(l, bg=CARD)
        loghead.pack(fill="x")
        tk.Label(loghead, text="LIVE OUTPUT", font=(FONT, 8, "bold"), bg=CARD,
                 fg=MUTED).pack(side="left")
        self.copy = ttk.Button(loghead, text="Copy", style="Secondary.TButton",
                               command=self.copy_output)
        self.copy.pack(side="right")
        self.clear = ttk.Button(loghead, text="Clear", style="Secondary.TButton",
                                command=self.clear_output)
        self.clear.pack(side="right", padx=(0, 6))
        tk.Label(l, text="Streams as the runtime writes it, including Inspect and Check imports.",
                 font=(FONT, 8), bg=CARD, fg=MUTED).pack(anchor="w", pady=(2, 7))

        logframe = tk.Frame(l, bg="#0e1724")
        logframe.pack(fill="both", expand=True)
        scroll = ttk.Scrollbar(logframe, command=None)
        self.output = tk.Text(logframe, wrap="word", font=(MONO, 9),
                              bg="#0e1724", fg="#d9e4f0", insertbackground="#d9e4f0",
                              selectbackground="#274b73", relief="flat", bd=0,
                              padx=11, pady=9, spacing1=1, spacing3=1)
        scroll.configure(command=self.output.yview)
        self.output.configure(yscrollcommand=scroll.set)
        scroll.pack(side="right", fill="y")
        self.output.pack(side="left", fill="both", expand=True)
        self.output.tag_configure("error", foreground="#ff9d97")
        self.output.tag_configure("warn", foreground="#ffd27d")
        self.output.tag_configure("ok", foreground="#8fe0a8")
        self.output.tag_configure("info", foreground="#9ec8f5")
        self.output.insert("1.0", "Session output will appear here. Choose a package, then "
                                  "inspect it, check imports or launch with WARP.\n")
        self.output.configure(state="disabled")

    # -- package, runtime and session panels ---------------------------

    def _refresh_package(self):
        raw = self.path.get().strip().strip('"')
        self.package_dir = None
        if not raw:
            self.package_var.set("No package selected.")
            self.executable_var.set("No executable")
            self.manifest_var.set("No manifest")
            self._paint_package_state("No package", "missing")
            for name in ARCHIVES:
                self._paint_chip(name, "missing", "Not checked")
            self.open_package.configure(state="disabled")
            return
        try:
            exe = Path(raw).expanduser().resolve()
        except OSError as error:
            self.package_var.set(str(error))
            self.executable_var.set("No executable")
            self.manifest_var.set("No manifest")
            self._paint_package_state("Path error", "error")
            for name in ARCHIVES:
                self._paint_chip(name, "error", "Not checked")
            self.open_package.configure(state="disabled")
            return
        if not exe.is_file() or exe.suffix.lower() != ".exe":
            self.package_var.set(str(exe.parent) if exe.parent else raw)
            self.executable_var.set(exe.name or "Not an executable")
            self.manifest_var.set("No manifest")
            self._paint_package_state("Not executable", "error")
            for name in ARCHIVES:
                self._paint_chip(name, "error", "Not checked")
            self.open_package.configure(state="disabled")
            return
        self.package_dir = exe.parent
        self.package_var.set(str(exe.parent))
        self.executable_var.set(exe.name)
        manifest = exe.parent / "MicrosoftGame.Config"
        self.manifest_var.set("MicrosoftGame.Config found" if manifest.is_file() else "Not beside executable")
        self._paint_package_state("Ready", "ok")
        for name, state, _detail in archive_status(exe.parent):
            self._paint_chip(name, state, {
                "ok": "RPF9", "unknown": "Unrecognized", "missing": "Missing",
                "error": "Error",
            }[state])
        self.open_package.configure(state="normal")

    def _paint_package_state(self, text, state):
        bg, fg = CHIP_TONES.get(state, CHIP_TONES["missing"])
        self.package_state_label.configure(text=text, bg=bg, fg=fg)

    def _paint_chip(self, name, state, text):
        label = self.archive_labels.get(name)
        if label is None:
            return
        bg, fg = CHIP_TONES.get(state, CHIP_TONES["missing"])
        label.configure(text=f"{name}  ·  {text}", bg=bg, fg=fg)

    def _refresh_runtime(self):
        state, label = runtime_state()
        runtime, profile = resolve_runtime()
        bg, fg = CHIP_TONES.get("ok" if state == "diag" else
                                "unknown" if state == "release" else "error")
        self.runtime_state_label.configure(text=label, bg=bg, fg=fg)
        if runtime is None:
            self.runtime_name_var.set("Runtime not built")
            self.runtime_path_var.set("Run .\\Build.ps1 in the Meraki folder.")
            return
        self.runtime_name_var.set("Diagnostics build" if profile == "diag" else "Release build")
        try:
            display = runtime.relative_to(ROOT)
        except ValueError:
            display = runtime
        self.runtime_path_var.set(str(display))

    # -- actions --------------------------------------------------------

    def choose(self):
        if getattr(self, "process", None) is not None:
            return
        current = Path(self.path.get().strip().strip('"')) if self.path.get().strip() else None
        initial = current.parent if current is not None and current.is_file() else ROOT
        exe = filedialog.askopenfilename(
            parent=self.root, title="Select the Xbox title executable",
            initialdir=str(initial),
            filetypes=[("Title executable", "*.exe"), ("All files", "*.*")])
        if exe:
            self.path.set(exe)
            self._refresh_package()

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
            self.frames_path = None
            with path.open("xb") as sink:
                if action == "launch" and self.capture.get():
                    frames = path.with_suffix("")
                    frames.mkdir()
                    self.frames_path = frames
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
            _set_status(self, "Could not start", str(error), "error")
            messagebox.showerror("Meraki", str(error), parent=self.root)
            return
        self.action = action
        self.started_at = datetime.now()
        clock = getattr(self, "clock_var", None)
        if clock is not None:
            clock.set("00:00")
        self.decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")
        self.output.configure(state="normal")
        self.output.delete("1.0", "end")
        self.output.configure(state="disabled")
        _set_controls(self, False)
        self.open_log.configure(state="normal")
        self.stop.configure(state="normal")
        _set_status(self, {"inspect": "Inspecting executable...",
                           "check": "Checking title imports...",
                           "launch": "Running title with WARP..."}[action],
                    "Preparing session..." if action != "launch" else "Starting the WARP runtime...",
                    "busy")
        _refresh_session_info(self)
        self.poll()

    def poll(self):
        code = self.process.poll()
        chunk = self.reader.read(65536)
        done = code is not None and not chunk
        content = self.decoder.decode(chunk, final=done)
        if content:
            _append_output(self, content)
            _note_chunk(self, content)
        if not done:
            _refresh_clock(self)
            self.root.after(10 if chunk else 180, self.poll)
            return
        self._cancel_stop_timer()
        self.reader.close()
        self.reader = None
        self.process = None
        _refresh_clock(self)
        if self.stopping:
            _set_status(self, "Stopped.", "The title closed after the stop request.", "done")
        elif code == 0:
            _set_status(self, "Runtime exited with code 0.",
                        "Session complete. The full log remains available.",
                        "done")
        else:
            _set_status(self, f"Runtime exited with code {code}.",
                        "Open the session log for details.", "error")
        self.stopping = False
        self.stop.configure(state="disabled")
        if self.closing:
            self._finish_close()
            return
        _set_controls(self, True)

    def show_log(self):
        _open_path(self.root, getattr(self, "log_path", None), "Open log")

    def show_frames(self):
        _open_path(self.root, getattr(self, "frames_path", None), "Open frames")

    def show_package(self):
        _open_path(self.root, getattr(self, "package_dir", None), "Open package")

    def copy_output(self):
        text = self.output.get("1.0", "end-1c")
        self.root.clipboard_clear()
        self.root.clipboard_append(text)
        variable = getattr(self, "detail", None)
        if variable is not None:
            variable.set("Output copied to the clipboard.")

    def clear_output(self):
        self.output.configure(state="normal")
        self.output.delete("1.0", "end")
        self.output.configure(state="disabled")

    def terminate(self):
        """Ask the title to close its window, forcing it after a bounded wait."""
        process = self.process
        if not process or process.poll() is not None or self.stopping:
            return
        self.stopping = True
        _set_status(self, "Stopping...", "Waiting for the title to close its window.", "stopping")
        self.stop.configure(state="disabled")
        # The close request goes to the title window, not to our console host.
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


def _open_path(root, path, title):
    if path is None:
        return
    try:
        os.startfile(path)
    except OSError as error:
        messagebox.showerror(title, str(error), parent=root)


if __name__ == "__main__":
    enable_dpi_awareness()
    window = tk.Tk()
    Launcher(window)
    window.mainloop()