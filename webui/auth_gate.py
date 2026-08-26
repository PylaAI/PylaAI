"""Optional HTTP Basic Auth gate for the web UI.

Enabled only when PYLA_WEB_PASSWORD is set, so it is invisible for the normal
local desktop build and protects the UI when the app is exposed on a server.
Wraps the WSGI app rather than touching the routes, so it stays out of the way.
"""

import hmac
import os
from base64 import b64decode


class BasicAuthGate:
    def __init__(self, app, username: str, password: str):
        self.app = app
        self._username = username
        self._password = password

    def _authorized(self, header: str) -> bool:
        if not header or not header.startswith("Basic "):
            return False
        try:
            decoded = b64decode(header[6:]).decode("utf-8")
            user, _, pwd = decoded.partition(":")
        except (ValueError, UnicodeDecodeError):
            return False
        # compare_digest on both fields keeps the check constant-time.
        return hmac.compare_digest(user, self._username) and hmac.compare_digest(
            pwd, self._password
        )

    def __call__(self, environ, start_response):
        if self._authorized(environ.get("HTTP_AUTHORIZATION", "")):
            return self.app(environ, start_response)
        start_response(
            "401 Unauthorized",
            [
                ("WWW-Authenticate", 'Basic realm="PylaAI"'),
                ("Content-Type", "text/plain; charset=utf-8"),
                ("Content-Length", "13"),
            ],
        )
        return [b"Unauthorized\n"]


def wrap_if_configured(app):
    """Return the app wrapped in Basic Auth when PYLA_WEB_PASSWORD is set."""
    password = os.environ.get("PYLA_WEB_PASSWORD", "").strip()
    if not password:
        return app
    username = os.environ.get("PYLA_WEB_USERNAME", "pyla").strip() or "pyla"
    return BasicAuthGate(app, username, password)
