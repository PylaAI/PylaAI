# PylaAI auth backend

Gates PylaAI behind a Discord role. The desktop app never holds the Discord
client secret or the bot token — it only receives a short-lived signed token,
and every check re-reads the user's roles from Discord.

## How it works

```
Desktop app                  This backend                    Discord
    |                              |                            |
    |-- opens browser ------------>|                            |
    |                              |-- OAuth authorize -------->|
    |                              |<-- code -------------------|
    |                              |-- exchange code ---------->|
    |                              |-- read member roles ------>|  (bot token)
    |                              |                            |
    |<-- redirect to 127.0.0.1 ----|  signed token, if the role matches
    |                              |
    |-- POST /auth/validate ------>|-- re-read roles ---------->|  (every check)
```

The app listens on a random loopback port and the backend redirects there with
the token, so no secret and no inbound port is needed on the client side.

Roles are read with the **bot token**, from the guild — not from the user's own
OAuth token. A user cannot grant themselves access by tampering with scopes.

## 1. Create the Discord application

In the [Discord Developer Portal](https://discord.com/developers/applications):

1. **New Application** → name it → copy the **Application ID** into
   `DISCORD_CLIENT_ID`.
2. **OAuth2** tab → **Reset Secret** → copy it into `DISCORD_CLIENT_SECRET`.
3. **OAuth2 → Redirects** → add exactly:
   `https://auth.example.com/auth/discord/callback`
   (your `PYLA_PUBLIC_URL` + `/auth/discord/callback`). It must match
   character for character or Discord rejects the login.
4. **Bot** tab → **Add Bot** → **Reset Token** → copy it into
   `DISCORD_BOT_TOKEN`.
5. Still on the Bot tab, enable the **Server Members Intent**. Without it
   Discord will not return member roles.

## 2. Invite the bot to your guild

Build the invite URL with your application ID:

```
https://discord.com/oauth2/authorize?client_id=YOUR_CLIENT_ID&scope=bot&permissions=0
```

No permissions are needed — reading members works through the intent alone.
The bot only has to be *present* in the guild.

## 3. Collect the guild and role IDs

Enable **Settings → Advanced → Developer Mode** in Discord, then:

- Right-click your server → **Copy Server ID** → `DISCORD_GUILD_ID`
- **Server Settings → Roles** → right-click the paying role → **Copy Role ID**
  → `DISCORD_ROLE_IDS`

Several roles can unlock the tool — separate them with commas:
`DISCORD_ROLE_IDS=111...,222...`

## 4. Configure and run

```sh
cp .env.example .env    # then fill it in
python3 -c "import secrets; print(secrets.token_urlsafe(48))"   # PYLA_TOKEN_SECRET
```

Local run:

```sh
pip install -r requirements.txt
set -a && . ./.env && set +a
python app.py
```

Production, behind a TLS-terminating reverse proxy:

```sh
set -a && . ./.env && set +a
gunicorn --workers 1 --bind 127.0.0.1:8080 'app:create_app()'
```

> **Keep `--workers 1`.** In-flight OAuth state and the role cache live in
> process memory, so a second worker would reject logins that started on the
> other one. Move both to Redis before scaling out.

The service must sit behind HTTPS: `PYLA_PUBLIC_URL` has to be the public
`https://` origin, since Discord refuses plaintext redirect URIs.

## 5. Point the desktop app at it

In the client's `cfg/general_config.toml`:

```toml
auth_base_url = "https://auth.example.com"
```

Leave it empty to disable Discord login and fall back to the previous
API-key flow.

## Endpoints

| Method | Path | Purpose |
| --- | --- | --- |
| `GET` | `/health` | Liveness probe. |
| `GET` | `/auth/discord/start?port=N` | Starts the flow for a client on loopback port `N`. |
| `GET` | `/auth/discord/callback` | Discord redirect target; issues the token. |
| `POST` | `/auth/validate` | Re-checks a token's signature, expiry, and live role. |

## Revoking access

Remove the role in Discord. The next `/auth/validate` fails once the cached
lookup expires — at most `PYLA_ROLE_CACHE_TTL` seconds (60 by default). The
client re-validates on start and while it runs, so a revoked user is locked
out without any action on the backend.
