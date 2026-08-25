"""Discord login for the desktop client.

The client never holds the Discord client secret. It opens the system browser
against the auth backend, listens on a loopback port for the redirect, and
stores the short-lived signed token the backend hands back.
"""

import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs, urlparse

import requests

from utils import load_toml_as_dict, save_dict_as_toml

LOGIN_TIMEOUT_SECONDS = 300
VALIDATE_TIMEOUT_SECONDS = 15

_SUCCESS_PAGE = b"""<!doctype html>
<html><head><meta charset="utf-8"><title>PylaAI</title>
<style>
  body { font-family: system-ui, sans-serif; background: #0f1115; color: #e6e8ec;
         display: flex; align-items: center; justify-content: center; height: 100vh; margin: 0; }
  .card { text-align: center; padding: 2rem; }
  h1 { font-size: 1.25rem; margin: 0 0 .75rem; }
  p { color: #9aa3b2; margin: 0; }
</style></head>
<body><div class="card">
  <h1>You are logged in</h1>
  <p>You can close this tab and go back to PylaAI.</p>
</div></body></html>"""


def auth_base_url() -> str:
    """Base URL of the auth backend, or an empty string when Discord login is off."""
    value = load_toml_as_dict("cfg/general_config.toml").get("auth_base_url", "")
    return str(value).strip().rstrip("/")


def is_configured() -> bool:
    return bool(auth_base_url())


def load_saved_token() -> str:
    return str(load_toml_as_dict("cfg/login.toml", cache=False).get("key", "")).strip()


def save_token(token: str) -> None:
    save_dict_as_toml({"key": token}, "cfg/login.toml")


def clear_token() -> None:
    save_dict_as_toml({"key": ""}, "cfg/login.toml")


def validate_token(token: str) -> dict:
    """Ask the backend whether this token still grants access.

    Returns the same shape the web UI already expects from a login check.
    """
    if not token:
        return _denied("Login required.", "MISSING_TOKEN")

    base_url = auth_base_url()
    if not base_url:
        return _denied("Discord login is not configured.", "AUTH_NOT_CONFIGURED")

    try:
        response = requests.post(
            f"{base_url}/auth/validate",
            json={"token": token},
            timeout=VALIDATE_TIMEOUT_SECONDS,
        )
    except requests.RequestException as exc:
        return _denied(f"Could not reach the auth server: {exc}", "AUTH_SERVER_UNREACHABLE")

    try:
        return response.json()
    except ValueError:
        return _denied(
            f"Auth server returned an unexpected response ({response.status_code}).",
            "AUTH_SERVER_ERROR",
        )


class _CallbackHandler(BaseHTTPRequestHandler):
    def do_GET(self):  # noqa: N802 - name imposed by BaseHTTPRequestHandler
        parsed = urlparse(self.path)
        if parsed.path != "/callback":
            self.send_response(404)
            self.end_headers()
            return

        token = parse_qs(parsed.query).get("token", [""])[0]
        self.server.received_token = token
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(_SUCCESS_PAGE)))
        self.end_headers()
        self.wfile.write(_SUCCESS_PAGE)

    def log_message(self, *_args):
        """Silence the default stderr access log."""


class LoginSession:
    """One in-flight browser login.

    Started from the UI: `authorize_url` is opened in the browser, and the
    session resolves once the backend redirects back to the loopback port.
    """

    def __init__(self):
        self._server = HTTPServer(("127.0.0.1", 0), _CallbackHandler)
        self._server.received_token = ""
        self._server.timeout = 1
        self.port = self._server.server_port
        self.started_at = time.time()
        self.result: dict | None = None
        self._lock = threading.Lock()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    @property
    def authorize_url(self) -> str:
        return f"{auth_base_url()}/auth/discord/start?port={self.port}"

    def _run(self):
        deadline = self.started_at + LOGIN_TIMEOUT_SECONDS
        try:
            while time.time() < deadline:
                self._server.handle_request()
                token = self._server.received_token
                if token:
                    result = validate_token(token)
                    if result.get("ok") and result.get("authenticated"):
                        save_token(token)
                    with self._lock:
                        self.result = result
                    return
            with self._lock:
                self.result = _denied("Login timed out. Try again.", "LOGIN_TIMEOUT")
        finally:
            self._server.server_close()

    def status(self) -> dict:
        with self._lock:
            if self.result is None:
                return {"pending": True, "authorize_url": self.authorize_url}
            return {"pending": False, **self.result}


def _denied(message: str, code: str) -> dict:
    return {"ok": False, "authenticated": False, "message": message, "code": code}
