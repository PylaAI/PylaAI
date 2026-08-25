"""Thin wrapper around the Discord HTTP API.

Only the three calls the auth backend needs: exchanging an OAuth code,
identifying the user behind an access token, and reading a guild member's roles.
"""

import logging

import requests

API_BASE = "https://discord.com/api/v10"
REQUEST_TIMEOUT = 10

logger = logging.getLogger(__name__)


class DiscordError(RuntimeError):
    """Raised when Discord answers with something we cannot act on."""


def exchange_code(client_id: str, client_secret: str, code: str, redirect_uri: str) -> str:
    """Trade an OAuth authorization code for a user access token."""
    response = requests.post(
        f"{API_BASE}/oauth2/token",
        data={
            "client_id": client_id,
            "client_secret": client_secret,
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": redirect_uri,
        },
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        timeout=REQUEST_TIMEOUT,
    )
    if response.status_code != 200:
        logger.warning("Code exchange rejected by Discord: %s", response.status_code)
        raise DiscordError("Discord rejected the authorization code.")

    access_token = response.json().get("access_token")
    if not access_token:
        raise DiscordError("Discord returned no access token.")
    return access_token


def identify(access_token: str) -> dict:
    """Return the Discord account behind a user access token."""
    response = requests.get(
        f"{API_BASE}/users/@me",
        headers={"Authorization": f"Bearer {access_token}"},
        timeout=REQUEST_TIMEOUT,
    )
    if response.status_code != 200:
        raise DiscordError("Could not read the Discord account.")
    return response.json()


def get_member(bot_token: str, guild_id: str, user_id: str) -> dict | None:
    """Return the guild member record, or None when the user is not in the guild.

    Uses the bot token rather than the user's access token, so the roles come
    from the guild itself and cannot be influenced by the client.
    """
    response = requests.get(
        f"{API_BASE}/guilds/{guild_id}/members/{user_id}",
        headers={"Authorization": f"Bot {bot_token}"},
        timeout=REQUEST_TIMEOUT,
    )
    if response.status_code == 404:
        return None
    if response.status_code == 401:
        raise DiscordError("Bot token is invalid.")
    if response.status_code == 403:
        raise DiscordError("The bot is not allowed to read members of this guild.")
    if response.status_code == 429:
        retry_after = response.json().get("retry_after", "?")
        raise DiscordError(f"Rate limited by Discord, retry after {retry_after}s.")
    if response.status_code != 200:
        raise DiscordError(f"Discord returned {response.status_code} while reading the member.")
    return response.json()
