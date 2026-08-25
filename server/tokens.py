"""Short-lived signed tokens handed to the desktop client.

Deliberately tiny: an HMAC-SHA256 signature over a JSON payload, in the same
shape as a JWT but without pulling in a JWT dependency. The token proves the
backend authenticated the user; it is not a capability on its own, because
/auth/validate re-checks the Discord role on every call.
"""

import base64
import hashlib
import hmac
import json
import time


class TokenError(RuntimeError):
    """Raised when a token is malformed, forged, or expired."""


def _b64encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _b64decode(text: str) -> bytes:
    padding = "=" * (-len(text) % 4)
    return base64.urlsafe_b64decode(text + padding)


def _sign(secret: str, payload: str) -> str:
    digest = hmac.new(secret.encode("utf-8"), payload.encode("ascii"), hashlib.sha256).digest()
    return _b64encode(digest)


def issue(secret: str, discord_id: str, username: str, ttl_seconds: int) -> str:
    now = int(time.time())
    payload = _b64encode(
        json.dumps(
            {
                "sub": discord_id,
                "username": username,
                "iat": now,
                "exp": now + ttl_seconds,
            },
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    )
    return f"{payload}.{_sign(secret, payload)}"


def verify(secret: str, token: str) -> dict:
    """Return the token payload, or raise TokenError."""
    try:
        payload, signature = token.strip().split(".", 1)
    except ValueError:
        raise TokenError("Malformed token.")

    # compare_digest keeps the check constant-time, so a forged signature
    # cannot be recovered byte by byte from response timing.
    if not hmac.compare_digest(signature, _sign(secret, payload)):
        raise TokenError("Invalid token signature.")

    try:
        claims = json.loads(_b64decode(payload))
    except (ValueError, json.JSONDecodeError):
        raise TokenError("Malformed token payload.")

    if int(claims.get("exp", 0)) < time.time():
        raise TokenError("Token expired.")

    return claims
