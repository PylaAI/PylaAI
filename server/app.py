"""PylaAI authentication backend.

Owns the Discord client secret and the bot token, so neither ever ships inside
the desktop application. The desktop client only ever holds a short-lived
signed token, and every validation re-reads the user's roles from Discord, so
removing the role in Discord locks the tool out within one cache window.
"""

import logging
import secrets
import threading
import time
from urllib.parse import urlencode

from flask import Flask, jsonify, redirect, render_template_string, request

import discord_api
import tokens
from config import Config

logger = logging.getLogger("pyla.auth")

AUTHORIZE_URL = "https://discord.com/oauth2/authorize"

# Only 'identify' is requested: the roles are read with the bot token, from the
# guild itself, so a user cannot influence what we see by tampering with scopes.
OAUTH_SCOPE = "identify"

_RESULT_PAGE = """<!doctype html>
<html><head><meta charset="utf-8"><title>PylaAI</title>
<style>
  body { font-family: system-ui, sans-serif; background: #0f1115; color: #e6e8ec;
         display: flex; align-items: center; justify-content: center; height: 100vh; margin: 0; }
  .card { text-align: center; max-width: 30rem; padding: 2rem; }
  h1 { font-size: 1.25rem; margin: 0 0 .75rem; }
  p { color: #9aa3b2; line-height: 1.5; margin: 0; }
  .bad { color: #ff6b6b; }
</style></head>
<body><div class="card">
  <h1 class="{{ 'bad' if error else '' }}">{{ title }}</h1>
  <p>{{ detail }}</p>
</div></body></html>"""


def _render(title: str, detail: str, error: bool = False, status: int = 200):
    return render_template_string(_RESULT_PAGE, title=title, detail=detail, error=error), status


class RoleChecker:
    """Reads guild roles from Discord, with a short cache to stay clear of rate limits."""

    def __init__(self, config: Config):
        self._config = config
        self._cache: dict[str, tuple[float, bool, list[str]]] = {}
        self._lock = threading.Lock()

    def _cached(self, user_id: str):
        with self._lock:
            entry = self._cache.get(user_id)
        if not entry:
            return None
        cached_at, has_role, roles = entry
        if time.time() - cached_at > self._config.role_cache_ttl:
            return None
        return has_role, roles

    def check(self, user_id: str, use_cache: bool = True) -> tuple[bool, list[str]]:
        """Return (has_required_role, role_ids). Raises DiscordError on API failure."""
        if use_cache:
            cached = self._cached(user_id)
            if cached is not None:
                return cached

        member = discord_api.get_member(self._config.bot_token, self._config.guild_id, user_id)
        if member is None:
            result = (False, [])
        else:
            roles = [str(role) for role in member.get("roles", [])]
            result = (any(role in self._config.role_ids for role in roles), roles)

        with self._lock:
            self._cache[user_id] = (time.time(), result[0], result[1])
        return result


class StateStore:
    """One-shot OAuth state values, mapped to the client's loopback port."""

    def __init__(self, ttl: int):
        self._ttl = ttl
        self._states: dict[str, tuple[float, int]] = {}
        self._lock = threading.Lock()

    def issue(self, loopback_port: int) -> str:
        state = secrets.token_urlsafe(32)
        with self._lock:
            self._prune_locked()
            self._states[state] = (time.time(), loopback_port)
        return state

    def consume(self, state: str) -> int | None:
        """Return the loopback port for a state, removing it. None if unknown/expired."""
        with self._lock:
            self._prune_locked()
            entry = self._states.pop(state, None)
        if not entry:
            return None
        return entry[1]

    def _prune_locked(self):
        cutoff = time.time() - self._ttl
        for state in [s for s, (created, _) in self._states.items() if created < cutoff]:
            del self._states[state]


def create_app(config: Config | None = None) -> Flask:
    config = config or Config()
    app = Flask(__name__)
    role_checker = RoleChecker(config)
    state_store = StateStore(config.state_ttl)

    @app.get("/health")
    def health():
        return jsonify({"ok": True, "service": "pyla-auth"})

    @app.get("/auth/discord/start")
    def start():
        """Kick off the OAuth flow for a desktop client listening on a loopback port."""
        raw_port = request.args.get("port", "")
        try:
            loopback_port = int(raw_port)
        except ValueError:
            return _render("Invalid request", "The client did not supply a valid port.", True, 400)
        if not 1024 <= loopback_port <= 65535:
            return _render("Invalid request", "The callback port is out of range.", True, 400)

        state = state_store.issue(loopback_port)
        query = urlencode(
            {
                "client_id": config.client_id,
                "redirect_uri": config.redirect_uri,
                "response_type": "code",
                "scope": OAUTH_SCOPE,
                "state": state,
                "prompt": "none",
            }
        )
        return redirect(f"{AUTHORIZE_URL}?{query}", code=302)

    @app.get("/auth/discord/callback")
    def callback():
        """Discord sends the user back here; we verify the role and hand back a token."""
        if request.args.get("error"):
            return _render("Login cancelled", "You declined the Discord authorization.", True, 400)

        state = request.args.get("state", "")
        code = request.args.get("code", "")
        if not state or not code:
            return _render("Invalid request", "Missing authorization code or state.", True, 400)

        loopback_port = state_store.consume(state)
        if loopback_port is None:
            return _render(
                "Login expired",
                "This login link is no longer valid. Start again from the app.",
                True,
                400,
            )

        try:
            access_token = discord_api.exchange_code(
                config.client_id, config.client_secret, code, config.redirect_uri
            )
            user = discord_api.identify(access_token)
        except discord_api.DiscordError as exc:
            logger.warning("OAuth exchange failed: %s", exc)
            return _render("Login failed", str(exc), True, 400)

        user_id = str(user.get("id", ""))
        username = user.get("username", "")
        if not user_id:
            return _render("Login failed", "Discord returned no account id.", True, 400)

        try:
            # Skip the cache here: a fresh login must reflect the role as it is now.
            has_role, _ = role_checker.check(user_id, use_cache=False)
        except discord_api.DiscordError as exc:
            logger.error("Role lookup failed for %s: %s", user_id, exc)
            return _render("Login failed", f"Could not read your roles: {exc}", True, 502)

        if not has_role:
            logger.info("Access denied for %s (%s): missing required role.", username, user_id)
            return _render(
                "Access denied",
                "Your Discord account does not have the role required to use PylaAI.",
                True,
                403,
            )

        token = tokens.issue(config.token_secret, user_id, username, config.token_ttl)
        logger.info("Issued token for %s (%s).", username, user_id)
        return redirect(f"http://127.0.0.1:{loopback_port}/callback?token={token}", code=302)

    @app.post("/auth/validate")
    def validate():
        """Re-check a stored token: signature, expiry, and the live Discord role."""
        payload = request.get_json(silent=True) or {}
        token = (payload.get("token") or "").strip()
        if not token:
            return jsonify(_denied("No token supplied.", "MISSING_TOKEN")), 400

        try:
            claims = tokens.verify(config.token_secret, token)
        except tokens.TokenError as exc:
            return jsonify(_denied(str(exc), "INVALID_TOKEN")), 401

        user_id = str(claims.get("sub", ""))
        try:
            has_role, _ = role_checker.check(user_id)
        except discord_api.DiscordError as exc:
            # Discord being unreachable is not the user's fault: report it as a
            # transient failure so the client can retry instead of logging out.
            logger.warning("Role re-check failed for %s: %s", user_id, exc)
            return jsonify(_denied(f"Could not reach Discord: {exc}", "DISCORD_UNAVAILABLE")), 503

        if not has_role:
            return jsonify(_denied("Your Discord role no longer grants access.", "ROLE_REVOKED")), 403

        return jsonify(
            {
                "ok": True,
                "authenticated": True,
                "message": "Authenticated.",
                "code": "OK",
                "username": claims.get("username", ""),
                "discord_id": user_id,
                "expires_at": claims.get("exp"),
            }
        )

    return app


def _denied(message: str, code: str) -> dict:
    return {"ok": False, "authenticated": False, "message": message, "code": code}


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s [%(name)s] %(message)s")
    create_app().run(host="127.0.0.1", port=8080)
