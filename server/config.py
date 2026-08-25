"""Backend configuration, read from the environment.

Every value is required except the tunables at the bottom; the service refuses
to boot with an incomplete configuration rather than failing later, mid-login.
"""

import os


class ConfigError(RuntimeError):
    pass


def _required(name: str) -> str:
    value = (os.environ.get(name) or "").strip()
    if not value:
        raise ConfigError(
            f"Missing required environment variable {name}. "
            "See server/README.md for the full list."
        )
    return value


class Config:
    def __init__(self):
        self.client_id = _required("DISCORD_CLIENT_ID")
        self.client_secret = _required("DISCORD_CLIENT_SECRET")
        self.bot_token = _required("DISCORD_BOT_TOKEN")
        self.guild_id = _required("DISCORD_GUILD_ID")

        # Comma-separated so several tiers can unlock the tool (e.g. "Premium,Lifetime").
        self.role_ids = [
            role_id.strip()
            for role_id in _required("DISCORD_ROLE_IDS").split(",")
            if role_id.strip()
        ]
        if not self.role_ids:
            raise ConfigError("DISCORD_ROLE_IDS contained no usable role id.")

        # Public HTTPS origin of this service, used to build the OAuth redirect URI.
        self.public_url = _required("PYLA_PUBLIC_URL").rstrip("/")
        self.token_secret = _required("PYLA_TOKEN_SECRET")
        if len(self.token_secret) < 32:
            raise ConfigError("PYLA_TOKEN_SECRET must be at least 32 characters.")

        self.token_ttl = int(os.environ.get("PYLA_TOKEN_TTL", 86400))
        self.role_cache_ttl = int(os.environ.get("PYLA_ROLE_CACHE_TTL", 60))
        self.state_ttl = int(os.environ.get("PYLA_STATE_TTL", 600))

    @property
    def redirect_uri(self) -> str:
        return f"{self.public_url}/auth/discord/callback"
