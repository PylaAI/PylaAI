"""Anonymous user count: one tiny ping per day so we know how many people use Pyla.

What is sent, at most once per UTC day, to the Pyla API (/usage/ping):
    id       a random install id (uuid4), made on this computer, tied to nothing else
    version  this Pyla's version
    channel  "public"
Nothing else: no player tag, Discord id, hardware id or settings. The server keeps a keyed hash of the id for 35 days
(to count daily, weekly and monthly users) and only the totals after that.

Until the user picks (first-launch notice or Settings), the server's default applies (/usage/config), so it can be
turned off without a release. Turning it off deletes the install id: turning it back on starts a new one that can't
be linked to the old.

Everything lives in cfg/usage_stats.json (git-ignored), so copying settings to another installation never carries
the id along.
"""
import json
import os
import re
import threading
import time
from datetime import datetime, timezone
from uuid import uuid4

import requests

from utils import PYLA_VERSION as VERSION, api_base_url, resolve_project_path

CHANNEL = "public"
CHECK_INTERVAL_S = 3600  # a bot left running for days still pings once per day
FALLBACK_DEFAULT = True  # the server's default when it was never reached
PROMPT_VERSION = 1       # raise it when what is sent changes, to show the notice again
_ID_RE = re.compile("[0-9a-f]{32}")
_lock = threading.RLock()
_started = False


def _path():
    return resolve_project_path("cfg", "usage_stats.json")


def _load():
    try:
        with open(_path(), encoding="utf-8") as handle:
            data = json.load(handle)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _save(state):
    path = _path()
    temporary = path.with_suffix(".tmp")
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary.write_text(json.dumps(state, indent=2), encoding="utf-8")
        os.replace(temporary, path)
    except OSError as exc:
        print(f"Could not save the usage stats state: {exc}")


def server_default(refresh=False):
    """The server's default for users who haven't picked, cached for offline launches."""
    with _lock:
        state = _load()
        cached = state.get("server_default")
        if refresh and api_base_url != "localhost":
            try:
                response = requests.get(f"https://{api_base_url}/usage/config", timeout=3.0)
                value = response.json().get("default_enabled") if response.status_code == 200 else None
            except (requests.RequestException, ValueError, AttributeError):
                value = None
            if isinstance(value, bool):
                if value != cached:
                    state["server_default"] = value
                    _save(state)
                return value
        return cached if isinstance(cached, bool) else FALLBACK_DEFAULT


def enabled():
    choice = _load().get("choice")
    return server_default() if not isinstance(choice, bool) else choice


def set_choice(value, from_prompt=False):
    """The user's pick. Off deletes the install id. A Settings save that changes nothing keeps the server default."""
    value = bool(value)
    with _lock:
        state = _load()
        if from_prompt or isinstance(state.get("choice"), bool) or value != enabled():
            state["choice"] = value
        if not value:
            state.pop("id", None)
            state.pop("last_ping", None)
        if from_prompt:
            state["prompt_version"] = PROMPT_VERSION
        _save(state)


def prompt_state():
    seen = _load().get("prompt_version")
    return {"show": not isinstance(seen, int) or seen < PROMPT_VERSION, "usage_stats": enabled()}


def ping_if_due():
    if api_base_url == "localhost" or not enabled():
        return False
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    with _lock:
        state = _load()
        if state.get("last_ping") == today:
            return True
        install_id = state.get("id")
        if not isinstance(install_id, str) or not _ID_RE.fullmatch(install_id):
            install_id = state["id"] = uuid4().hex
            _save(state)
    try:
        response = requests.post(f"https://{api_base_url}/usage/ping", timeout=5.0, allow_redirects=False,
                                 json={"id": install_id, "version": VERSION, "channel": CHANNEL})
    except requests.RequestException:
        return False
    if response.status_code not in (200, 204):
        return False
    with _lock:
        state = _load()
        if state.get("id") == install_id:  # not turned off while the request ran
            state["last_ping"] = today
            _save(state)
    return True


def _loop():
    server_default(refresh=True)
    while True:
        try:
            ping_if_due()
        except Exception as exc:  # never let stats break anything
            print(f"Usage stats ping failed: {exc}")
        time.sleep(CHECK_INTERVAL_S)


def start():
    """Start the background daily ping (once per process)."""
    global _started
    if _started:
        return
    _started = True
    threading.Thread(target=_loop, name="pyla-usage-stats", daemon=True).start()
