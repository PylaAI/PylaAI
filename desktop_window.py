"""Native desktop window for the PylaAI UI.

Wraps the existing Flask web UI in a real application window (pywebview) so the
tool ships as a single Windows app with its own icon, instead of a console plus
a browser tab. Falls back to opening the default browser when pywebview is not
installed, so nothing breaks in a plain dev checkout.
"""

import threading
import time

from utils import resolve_project_path

WINDOW_TITLE = "PylaAI"
WINDOW_WIDTH = 1280
WINDOW_HEIGHT = 820
WINDOW_MIN_SIZE = (1024, 680)


def _wait_until_up(url: str, timeout: float = 15.0) -> None:
    """Block until the Flask server answers, so the window never opens on a blank page."""
    import urllib.error
    import urllib.request

    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            urllib.request.urlopen(url, timeout=1)
            return
        except urllib.error.HTTPError:
            # Any HTTP status means the server is listening; that is enough.
            return
        except (urllib.error.URLError, ConnectionError, OSError):
            time.sleep(0.2)


def _open_in_browser(url: str) -> None:
    import webbrowser

    def _open():
        _wait_until_up(url)
        webbrowser.open(url)

    threading.Thread(target=_open, daemon=True, name="pyla-browser-launcher").start()


def run(url: str, start_server, prefer_window: bool = True) -> None:
    """Start the server and show the UI.

    Args:
        url: local URL the UI is served on.
        start_server: callable that runs the Flask server (blocking).
        prefer_window: open a native window when possible; otherwise use the browser.

    pywebview must own the main thread, so the Flask server is moved to a
    background thread and the window runs in the foreground. When pywebview is
    unavailable we invert that: the browser opener is the background thread and
    the server stays in the foreground, matching the original behaviour.
    """
    if not prefer_window:
        _open_in_browser(url)
        start_server()
        return

    try:
        import webview
    except ImportError:
        print("pywebview not installed; opening the UI in your browser instead.")
        _open_in_browser(url)
        start_server()
        return

    server_thread = threading.Thread(target=start_server, daemon=True, name="pyla-webui")
    server_thread.start()
    _wait_until_up(url)

    icon_path = resolve_project_path("images", "logo.png")
    window_kwargs = {
        "width": WINDOW_WIDTH,
        "height": WINDOW_HEIGHT,
        "min_size": WINDOW_MIN_SIZE,
    }

    webview.create_window(WINDOW_TITLE, url, **window_kwargs)

    start_kwargs = {}
    if icon_path.exists():
        # Only honoured on the GTK/Qt backends; harmless (ignored) on Windows,
        # where the icon comes from the compiled .exe instead.
        start_kwargs["icon"] = str(icon_path)

    try:
        webview.start(**start_kwargs)
    except TypeError:
        # Older pywebview builds do not accept the icon keyword.
        webview.start()
