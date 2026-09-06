"""Desktop startup helpers for the local PylaAI web interface."""

from __future__ import annotations

import ctypes
import os
import sys
import threading
from pathlib import Path
from typing import Any, Callable


IS_WINDOWS = os.name == "nt"
WINDOW_TITLE = "PylaAI"
WINDOW_SIZE = (1440, 900)
APP_ICON_PATH = Path(__file__).resolve().parent / "images" / "logo.ico"
WINDOWS_APP_ID = "PylaAI.Desktop"
_SW_HIDE = 0
_BUNDLED_WEBVIEW_BINARIES = (
    Path("pythonnet/runtime/Python.Runtime.dll"),
    Path("clr_loader/ffi/dlls/amd64/ClrLoader.dll"),
    Path("webview/lib/Microsoft.Web.WebView2.Core.dll"),
    Path("webview/lib/Microsoft.Web.WebView2.WinForms.dll"),
    Path("webview/lib/WebBrowserInterop.x64.dll"),
    Path("webview/lib/runtimes/win-x64/native/WebView2Loader.dll"),
)


def console_log_path() -> Path:
    return Path.cwd() / "pyla.log"


def hide_console(log_path: Path | None = None) -> bool:
    """Hide a console owned only by PylaAI and redirect its streams to a log.

    A console shared with the terminal that launched PylaAI is deliberately left
    alone, because hiding it would also hide the user's terminal window.
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


def _owns_console(kernel32: Any) -> bool:
    process_ids = (ctypes.c_ulong * 16)()
    attached_processes = kernel32.GetConsoleProcessList(process_ids, len(process_ids))
    return attached_processes == 1


def _redirect_standard_streams(log_path: Path) -> None:
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

    # These descriptors must remain valid after FreeConsole(), otherwise later
    # print calls would still point at the detached console handles.
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


def unblock_bundled_webview_binaries(base_dir: Path | None = None) -> list[Path]:
    """Remove Internet-zone markers from the .NET files shipped with PylaAI.

    Windows propagates the downloaded ZIP's ``Zone.Identifier`` stream to
    extracted files.  The executable itself may still run, but .NET Framework
    then refuses to load Python.Runtime.dll and clr_loader reports the rather
    misleading "Failed to resolve ... Loader.Initialize" error.

    Only PylaAI's explicitly listed pywebview/pythonnet binaries are touched.
    Source checkouts normally have none of these files next to desktop.py, so
    this is effectively a frozen-build startup repair.
    """
    if not IS_WINDOWS:
        return []

    bundle_dir = Path(base_dir) if base_dir is not None else Path(__file__).resolve().parent
    unblocked: list[Path] = []
    failures: list[tuple[Path, OSError]] = []

    for relative_path in _BUNDLED_WEBVIEW_BINARIES:
        binary_path = bundle_dir / relative_path
        if not binary_path.is_file():
            continue

        zone_identifier = f"{binary_path}:Zone.Identifier"
        try:
            os.remove(zone_identifier)
        except FileNotFoundError:
            continue
        except OSError as error:
            failures.append((binary_path, error))
        else:
            unblocked.append(binary_path)

    if unblocked:
        print(f"Removed Windows download blocking from {len(unblocked)} bundled UI file(s).")
    for binary_path, error in failures:
        print(f"Could not remove Windows download blocking from {binary_path}: {error}")

    return unblocked


def import_webview() -> tuple[Any | None, Exception | None]:
    """Return the optional pywebview module, or the reason it could not load."""
    unblock_bundled_webview_binaries()
    try:
        # Keep this as a regular import so PyInstaller can discover pywebview
        # and run its hook, which bundles the Windows WebView2/.NET files.
        import webview

        return webview, None
    except Exception as error:
        return None, error


def set_windows_app_id(app_id: str = WINDOWS_APP_ID) -> bool:
    """Give interpreted runs their own Windows taskbar identity.

    Without an explicit AppUserModelID, Windows groups the pywebview form under
    python.exe and may keep showing Python's icon even when Form.Icon is set.
    """
    if not IS_WINDOWS:
        return False

    try:
        shell32 = ctypes.WinDLL("shell32", use_last_error=True)
        set_app_id = shell32.SetCurrentProcessExplicitAppUserModelID
        set_app_id.argtypes = [ctypes.c_wchar_p]
        set_app_id.restype = ctypes.c_long
        return set_app_id(app_id) >= 0
    except (AttributeError, OSError):
        return False


def run_webview(
    app: Any,
    local_url: str,
    webview_module: Any,
    on_close: Callable[[], None] | None = None,
    window_size: tuple[int, int] = WINDOW_SIZE,
    window_title: str = WINDOW_TITLE,
) -> None:
    """Serve Flask in the background and run pywebview on the main thread."""
    from werkzeug.serving import make_server

    set_windows_app_id()
    host = "127.0.0.1"
    port = int(local_url.rsplit(":", 1)[1].split("/", 1)[0])
    server = make_server(host, port, app, threaded=True)
    server_thread = threading.Thread(
        target=server.serve_forever,
        daemon=True,
        name="pyla-web-server",
    )
    server_thread.start()

    try:
        window = webview_module.create_window(
            window_title,
            local_url,
            width=window_size[0],
            height=window_size[1],
            maximized=True,
        )
        if on_close is not None:
            window.events.closed += lambda *_args: on_close()
        print("PylaAI is running in a pywebview desktop window.")
        icon = str(APP_ICON_PATH) if APP_ICON_PATH.is_file() else None
        webview_module.start(icon=icon)
    finally:
        server.shutdown()
        server.server_close()
        server_thread.join(timeout=5)
