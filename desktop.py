"""Windows desktop shell for the Pyla web UI.

Only the standard library and ctypes are used here, so everything keeps working
inside a Nuitka build (no pywebview, no Qt, no extra runtime DLL to ship).

Two jobs:
  * open_app_window() runs the local Flask UI inside a Chromium "app" window
    (Edge, Chrome or Brave) so Pyla looks like a standalone Windows app instead
    of a browser tab, and repaints the window chrome with the Pyla colors.
  * hide_console() hides the console window when Pyla is started with
    --no-console. Without that flag the console stays visible.
"""

from __future__ import annotations

import ctypes
import os
import socket
import subprocess
import sys
import threading
import time
import webbrowser
from pathlib import Path
from urllib.parse import urlsplit

IS_WINDOWS = os.name == "nt"

# Pyla look and feel, kept in sync with the CSS variables in static/css/tailwind.css
WINDOW_TITLE = "PylaAI"
CAPTION_COLOR = "#0a0b0e"       # --bg-surface
CAPTION_TEXT_COLOR = "#ffffff"  # --text-primary
BORDER_COLOR = "#0a0b0e"        # same tone as the caption; set to None for no border at all
WINDOW_SIZE = (1440, 900)

# Browsers able to run a chromeless "--app" window, preferred order.
BROWSER_CANDIDATES = (
    ("msedge.exe", Path("Microsoft/Edge/Application/msedge.exe")),
    ("chrome.exe", Path("Google/Chrome/Application/chrome.exe")),
    ("brave.exe", Path("BraveSoftware/Brave-Browser/Application/brave.exe")),
)

_SW_HIDE = 0
_TH32CS_SNAPPROCESS = 0x00000002
# https://learn.microsoft.com/windows/win32/api/dwmapi/ne-dwmapi-dwmwindowattribute
_DWMWA_USE_IMMERSIVE_DARK_MODE = 20
_DWMWA_BORDER_COLOR = 34
_DWMWA_CAPTION_COLOR = 35
_DWMWA_TEXT_COLOR = 36
_DWM_COLOR_NONE = 0xFFFFFFFE  # DWMWA_COLOR_NONE: draw no border at all


def pyla_data_dir() -> Path:
    base = os.environ.get("LOCALAPPDATA") or str(Path.home())
    return Path(base) / "PylaAI"


def console_log_path() -> Path:
    return pyla_data_dir() / "pyla.log"


# ---------------------------------------------------------------------------
# Console visibility (--no-console)
# ---------------------------------------------------------------------------

def hide_console(log_path: Path | None = None) -> bool:
    """Hide the console window and send stdout/stderr to a log file.

    Returns False (and leaves everything untouched) when there is no console to
    hide, or when the console is shared with the terminal that started Pyla:
    hiding it would take the user's own terminal window down with it.
    """
    if not IS_WINDOWS:
        return False

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    kernel32.GetConsoleWindow.restype = ctypes.c_void_p
    user32.ShowWindow.argtypes = [ctypes.c_void_p, ctypes.c_int]

    console_hwnd = kernel32.GetConsoleWindow()
    if not console_hwnd or not _owns_console(kernel32):
        return False

    user32.ShowWindow(ctypes.c_void_p(console_hwnd), _SW_HIDE)
    _redirect_standard_streams(log_path or console_log_path())
    kernel32.FreeConsole()
    return True


def _owns_console(kernel32) -> bool:
    process_ids = (ctypes.c_ulong * 16)()
    attached = kernel32.GetConsoleProcessList(process_ids, len(process_ids))
    return attached == 1


def _redirect_standard_streams(log_path: Path):
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.flush()
        except Exception:
            pass

    try:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        log_fd = os.open(log_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o644)
        null_fd = os.open(os.devnull, os.O_RDONLY)
    except OSError as error:
        print(f"Could not open the log file {log_path}: {error}")
        return

    # The file descriptors have to survive FreeConsole(), otherwise every later
    # print() would fail on a dangling console handle.
    os.dup2(log_fd, 1)
    os.dup2(log_fd, 2)
    os.dup2(null_fd, 0)
    if log_fd > 2:
        os.close(log_fd)
    if null_fd > 2:
        os.close(null_fd)

    sys.stdout = open(1, "w", buffering=1, encoding="utf-8", errors="replace", closefd=False)
    sys.stderr = open(2, "w", buffering=1, encoding="utf-8", errors="replace", closefd=False)
    sys.stdin = open(0, "r", encoding="utf-8", errors="replace", closefd=False)


# ---------------------------------------------------------------------------
# Desktop window
# ---------------------------------------------------------------------------

def open_app_window(url: str, on_close=None, window_size=WINDOW_SIZE, window_title=WINDOW_TITLE):
    """Open the Pyla UI as a desktop window, once the local server answers.

    Falls back to the default browser when no Chromium based browser is found.
    `on_close` is called when the app window is closed by the user.
    """
    thread = threading.Thread(
        target=_run_app_window,
        args=(url, on_close, window_size, window_title),
        daemon=True,
        name="pyla-webapp",
    )
    thread.start()
    return thread


def _run_app_window(url, on_close, window_size, window_title):
    if not _wait_for_server(url):
        print("The Pyla web UI did not start in time, opening it in the default browser instead.")
        webbrowser.open(url)
        return

    browser = find_browser() if IS_WINDOWS else None
    if browser is None:
        print("No Chromium based browser found, opening the Pyla UI in the default browser.")
        webbrowser.open(url)
        return

    # Any window already carrying our title is somebody else's, not the one we
    # are about to open.
    known_windows = set(_find_app_windows(set(), window_title))
    command = _browser_command(browser, url, window_size)
    try:
        process = subprocess.Popen(command)
    except OSError as error:
        print(f"Could not start the Pyla desktop window ({error}), falling back to the default browser.")
        webbrowser.open(url)
        return

    hwnd = _wait_for_app_window(process.pid, window_title, known_windows)
    if hwnd is None:
        print("The Pyla desktop window did not open, using the default browser instead.")
        webbrowser.open(url)
        return

    print(f"Pyla is running in a desktop window ({browser.name}).")
    apply_window_theme(hwnd)

    # The launched process is only a stub on some browsers, so the window
    # itself is what tells us the user is done with Pyla.
    _wait_until_window_closed(hwnd)
    if on_close is not None:
        on_close()


def _wait_for_server(url: str, timeout: float = 30.0) -> bool:
    parts = urlsplit(url)
    host = parts.hostname or "127.0.0.1"
    port = parts.port or (443 if parts.scheme == "https" else 80)
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.settimeout(0.5)
            if sock.connect_ex((host, port)) == 0:
                return True
        time.sleep(0.2)
    return False


def find_browser() -> Path | None:
    override = os.environ.get("PYLA_WEBAPP_BROWSER", "").strip().strip('"')
    if override:
        candidate = Path(override)
        if candidate.is_file():
            return candidate
        print(f"PYLA_WEBAPP_BROWSER points to {candidate}, which does not exist. Looking for an installed browser.")

    for executable_name, relative_path in BROWSER_CANDIDATES:
        from_registry = _browser_from_registry(executable_name)
        if from_registry is not None:
            return from_registry
        for base in _program_directories():
            candidate = base / relative_path
            if candidate.is_file():
                return candidate
    return None


def _program_directories():
    for variable in ("PROGRAMFILES", "PROGRAMFILES(X86)", "LOCALAPPDATA"):
        value = os.environ.get(variable)
        if value:
            yield Path(value)


def _browser_from_registry(executable_name: str) -> Path | None:
    import winreg

    key_path = rf"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\{executable_name}"
    for root in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
        try:
            with winreg.OpenKey(root, key_path) as key:
                candidate = Path(winreg.QueryValue(key, None).strip('"'))
        except OSError:
            continue
        if candidate.is_file():
            return candidate
    return None


def _browser_command(browser: Path, url: str, window_size) -> list[str]:
    width, height = window_size
    red, green, blue = _rgb(CAPTION_COLOR)
    command = [
        str(browser),
        f"--app={url}",
        f"--user-data-dir={_browser_profile_dir()}",
        f"--window-size={width},{height}",
        # The title bar of an app window is drawn by the browser itself, and a
        # generated theme is what it takes its color from.
        f"--install-autogenerated-theme={red},{green},{blue}",
        "--force-dark-mode",
        "--no-first-run",
        "--no-default-browser-check",
        "--disable-session-crashed-bubble",
        "--disable-background-mode",
        "--disable-features=Translate",
    ]
    position = _centered_position(window_size)
    if position is not None:
        command.append(f"--window-position={position[0]},{position[1]}")
    return command


def _browser_profile_dir() -> Path:
    """A profile of our own keeps Pyla out of the user's browser session.

    It also guarantees the browser we launch is the one owning the window,
    instead of handing the URL over to an already running instance.
    """
    profile = pyla_data_dir() / "webapp-profile"
    profile.mkdir(parents=True, exist_ok=True)
    try:
        # Sentinel file Chromium looks for to skip its first run experience.
        (profile / "First Run").touch(exist_ok=True)
    except OSError:
        pass
    return profile


def _centered_position(window_size):
    if not IS_WINDOWS:
        return None
    try:
        user32 = ctypes.WinDLL("user32", use_last_error=True)
        screen_width = user32.GetSystemMetrics(0)
        screen_height = user32.GetSystemMetrics(1)
    except OSError:
        return None
    if not screen_width or not screen_height:
        return None
    return (
        max((screen_width - window_size[0]) // 2, 0),
        max((screen_height - window_size[1]) // 2, 0),
    )


# ---------------------------------------------------------------------------
# Native window chrome
# ---------------------------------------------------------------------------

def _wait_for_app_window(browser_pid: int, window_title: str, known_windows: set, timeout: float = 30.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        for hwnd in _find_app_windows(_process_tree(browser_pid), window_title):
            if hwnd not in known_windows:
                return hwnd
        time.sleep(0.25)
    return None


def _wait_until_window_closed(hwnd: int, poll_interval: float = 0.5):
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    user32.IsWindow.argtypes = [ctypes.c_void_p]
    while user32.IsWindow(ctypes.c_void_p(hwnd)):
        time.sleep(poll_interval)


def apply_window_theme(hwnd: int) -> bool:
    """Paint the window frame with the Pyla colors.

    This handles the parts Windows owns: the border around the window, and the
    caption itself when the browser is configured to use the system title bar
    (otherwise the browser draws it, hence --install-autogenerated-theme).
    The window keeps its regular Windows behaviour either way (drag, snap
    layouts, minimise / maximise / close, taskbar preview): only colors change.
    Those attributes need Windows 11 (build 22000+); on older builds the calls
    fail silently and the window simply keeps its default frame.
    """
    try:
        dwmapi = ctypes.WinDLL("dwmapi")
    except OSError:
        return False

    dwmapi.DwmSetWindowAttribute.argtypes = [
        ctypes.c_void_p, ctypes.c_uint, ctypes.c_void_p, ctypes.c_uint,
    ]

    def set_attribute(attribute: int, value: int) -> bool:
        data = ctypes.c_uint(value)
        result = dwmapi.DwmSetWindowAttribute(
            ctypes.c_void_p(hwnd), ctypes.c_uint(attribute), ctypes.byref(data), ctypes.sizeof(data)
        )
        return result == 0

    border = _DWM_COLOR_NONE if BORDER_COLOR is None else _colorref(BORDER_COLOR)
    applied = set_attribute(_DWMWA_USE_IMMERSIVE_DARK_MODE, 1)
    applied |= set_attribute(_DWMWA_CAPTION_COLOR, _colorref(CAPTION_COLOR))
    applied |= set_attribute(_DWMWA_TEXT_COLOR, _colorref(CAPTION_TEXT_COLOR))
    applied |= set_attribute(_DWMWA_BORDER_COLOR, border)
    return applied


def _rgb(hex_color: str) -> tuple:
    value = hex_color.lstrip("#")
    return tuple(int(value[index:index + 2], 16) for index in (0, 2, 4))


def _colorref(hex_color: str) -> int:
    red, green, blue = _rgb(hex_color)
    return (blue << 16) | (green << 8) | red


_WNDENUMPROC = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p) if IS_WINDOWS else None


def _find_app_windows(process_ids: set[int], window_title: str) -> list:
    """Every visible browser window that looks like our app window.

    Chromium app windows use the page title as their window title, while a
    regular browser window appends the browser name to it, so an exact title
    match keeps the Pyla UI opened in a normal tab out of the way.
    """
    if not IS_WINDOWS:
        return []

    user32 = ctypes.WinDLL("user32", use_last_error=True)
    user32.EnumWindows.argtypes = [_WNDENUMPROC, ctypes.c_void_p]
    user32.IsWindowVisible.argtypes = [ctypes.c_void_p]
    user32.GetClassNameW.argtypes = [ctypes.c_void_p, ctypes.c_wchar_p, ctypes.c_int]
    user32.GetWindowTextW.argtypes = [ctypes.c_void_p, ctypes.c_wchar_p, ctypes.c_int]
    user32.GetWindowThreadProcessId.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_ulong)]

    found = []
    text_buffer = ctypes.create_unicode_buffer(512)

    def on_window(hwnd, _lparam):
        if not user32.IsWindowVisible(hwnd):
            return True
        user32.GetClassNameW(hwnd, text_buffer, len(text_buffer))
        if not text_buffer.value.startswith("Chrome_WidgetWin_"):
            return True

        user32.GetWindowTextW(hwnd, text_buffer, len(text_buffer))
        title = text_buffer.value
        if title != window_title:
            # Edge (and others) relaunch themselves at startup, so the window is
            # not always owned by the process we spawned. When it is, accept it
            # even if its title has not settled on the page title yet.
            process_id = ctypes.c_ulong()
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(process_id))
            if not title or process_id.value not in process_ids:
                return True

        found.append(hwnd)
        return True

    user32.EnumWindows(_WNDENUMPROC(on_window), None)
    return found


class _ProcessEntry32(ctypes.Structure):
    _fields_ = [
        ("dwSize", ctypes.c_ulong),
        ("cntUsage", ctypes.c_ulong),
        ("th32ProcessID", ctypes.c_ulong),
        ("th32DefaultHeapID", ctypes.c_size_t),
        ("th32ModuleID", ctypes.c_ulong),
        ("cntThreads", ctypes.c_ulong),
        ("th32ParentProcessID", ctypes.c_ulong),
        ("pcPriClassBase", ctypes.c_long),
        ("dwFlags", ctypes.c_ulong),
        ("szExeFile", ctypes.c_char * 260),
    ]


def _process_tree(root_pid: int) -> set[int]:
    """Every pid spawned by root_pid, itself included.

    Browsers spread over several processes, and some of them relaunch
    themselves at startup, so the window we are looking for is not necessarily
    owned by the process we started.
    """
    if not IS_WINDOWS:
        return {root_pid}

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateToolhelp32Snapshot.argtypes = [ctypes.c_ulong, ctypes.c_ulong]
    kernel32.CreateToolhelp32Snapshot.restype = ctypes.c_void_p
    kernel32.Process32First.argtypes = [ctypes.c_void_p, ctypes.POINTER(_ProcessEntry32)]
    kernel32.Process32Next.argtypes = [ctypes.c_void_p, ctypes.POINTER(_ProcessEntry32)]
    kernel32.CloseHandle.argtypes = [ctypes.c_void_p]

    snapshot = kernel32.CreateToolhelp32Snapshot(_TH32CS_SNAPPROCESS, 0)
    if not snapshot or snapshot == ctypes.c_void_p(-1).value:
        return {root_pid}

    children: dict[int, list[int]] = {}
    entry = _ProcessEntry32()
    entry.dwSize = ctypes.sizeof(_ProcessEntry32)
    try:
        has_entry = kernel32.Process32First(ctypes.c_void_p(snapshot), ctypes.byref(entry))
        while has_entry:
            children.setdefault(entry.th32ParentProcessID, []).append(entry.th32ProcessID)
            has_entry = kernel32.Process32Next(ctypes.c_void_p(snapshot), ctypes.byref(entry))
    finally:
        kernel32.CloseHandle(ctypes.c_void_p(snapshot))

    tree: set[int] = set()
    pending = [root_pid]
    while pending:
        pid = pending.pop()
        if pid in tree:
            continue
        tree.add(pid)
        pending.extend(children.get(pid, ()))
    return tree
