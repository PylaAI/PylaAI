from __future__ import annotations

import csv
from datetime import datetime
import json
import logging
import shutil
from pathlib import Path
from typing import Any
import requests
from packaging import version
from werkzeug.utils import secure_filename

from utils import (
    api_base_url,
    clean_queue,
    get_brawler_list,
    get_discord_link,
    get_latest_version,
    get_playstyles_list,
    load_brawlers_info,
    load_brawler_data,
    load_pyla_script,
    load_toml_as_dict,
    normalize_brawler_filename,
    resolve_project_path,
    save_dict_as_toml, PYLA_VERSION, api_update_brawler_data, clear_brawler_data, save_brawler_data,
)

try:
    from early_access.early_access import (
        get_brawler_stats,
        get_player_info,
        validate_login as validate_early_access_login,
    )

    early_access = True

except (ImportError, ModuleNotFoundError):
    def get_brawler_stats(_player_info, _brawler_name):
        return None, None

    def get_player_info(_tag):
        return None

    def validate_early_access_login(_api_key):
        return {
            "ok": False,
            "authenticated": False,
            "message": "Early access module is missing.",
            "code": "EARLY_ACCESS_MODULE_MISSING",
        }

    early_access = False


def check_user_exists(username):
    url = f'https://{api_base_url}/check_user'

    params = {'username': username, "API-Key": "apikeyhaha"}
    response = requests.get(url, params=params)

    if response.status_code == 200:
        data = response.json()
        return data['exists']
    else:
        print(f"Error: Unable to check user. Status code: {response.status_code}")
        return False


def check_if_exists(username):
    user_exists = check_user_exists(username)
    if user_exists is not None:
        print(f"User '{username}' exists: {user_exists}")
        return user_exists
    else:
        print("Failed to check user existence.")
        return False


PATREON_LINK = "https://www.patreon.com/pyla/membership"
PATREON_LABEL = "www.patreon.com/c/pyla"
INVALID_PLAYER_TAG_MESSAGE = "Player tag is incorrect. Use your Brawl Stars player tag, not your Supercell ID."
logger = logging.getLogger(__name__)


class WebDataService:
    PLAY_ORDER_VALUES = {"in_order", "lowest_to_highest", "highest_to_lowest"}

    GENERAL_FIELDS: dict[str, tuple[str, Any]] = {
        "run_for_minutes": ("int", 0),
        "player_tag": ("str", ""),
        "default_trophy_target": ("int", 1000),
        "play_order": ("play_order", "in_order"),
        "max_ips": ("auto_int", "auto"),
        "used_threads": ("auto_int", "auto"),
        "ocr_scale_down_factor": ("float", 0.8),
        "brawl_stars_package": ("str", "com.supercell.brawlstars"),
        "emulator_port": ("int", 5037),
        "trophies_multiplier": ("int", 1),
        "auto_load_queue_on_startup": ("bool", True),
    }

    DEBUG_FIELDS: dict[str, tuple[str, Any]] = {
        "verbose_debug": ("bool", False),
        "state_finder_debug": ("bool", False),
        "re_apply_movement": ("bool", True),
        "debug_view": ("bool", False),
        "debug_view_fps": ("int", 30),
        "advanced_debug_visuals": ("bool", False),
        "record_debug_preview_clips": ("bool", False),
    }

    BOT_FIELDS: dict[str, tuple[str, Any]] = {
        "play_again_on_win": ("bool_str", False),
        "minimum_movement_delay": ("float", 0.1),
        "unstuck_movement_delay": ("float", 2.4),
        "unstuck_movement_hold_time": ("float", 1.4),
        "perceived_tile_size": ("int", 54),
        "centered_wall_detection": ("bool", False),
        "wall_detection_confidence": ("float", 0.6),
        "entity_detection_confidence": ("float", 0.6),
        "seconds_to_hold_attack_after_reaching_max": ("float", 1.5),
        "idle_pixels_minimum": ("float", 75000.0),
        "super_pixels_minimum": ("float", 1800.0),
        "gadget_pixels_minimum": ("float", 1300.0),
        "hypercharge_pixels_minimum": ("float", 1800.0),
    }

    TIMER_FIELDS: dict[str, tuple[str, Any]] = {
        "super": ("float", 0.1),
        "hypercharge": ("float", 0.1),
        "gadget": ("float", 0.1),
        "wall_detection": ("float", 0.2),
        "no_detection_proceed": ("float", 8),
        "state_check": ("float", 3.0),
        "idle": ("float", 3.0),
        "check_if_brawl_stars_crashed": ("float", 5.0),
    }

    WEBHOOK_FIELDS: dict[str, tuple[str, Any]] = {
        "webhook_url": ("str", ""),
        "discord_id": ("str", ""),
        "discord_bot_token": ("str", ""),
        "discord_guild_id": ("str", ""),
        "telegram_token": ("str", ""),
        "telegram_chat_id": ("str", ""),
        "ping_when_stuck": ("bool", True),
        "ping_when_target_is_reached": ("bool", True),
        "ping_every_x_match": ("int", 0),
        "ping_every_x_minutes": ("int", 0),
    }

    def __init__(self, runtime_manager):
        self.runtime_manager = runtime_manager
        self._latest_version_cache: str | None = None
        self._queue_items: list[dict[str, Any]] = []
        self._runtime_queue_mtime: float | None = None
        self._load_startup_queue_if_enabled()

    @staticmethod
    def _bool_from_string(value: Any) -> bool:
        return str(value).strip().lower() in {"1", "true", "yes", "on"}

    def _deserialize(self, value_type: str, value: Any):
        if value_type == "int":
            return int(value)
        if value_type == "float":
            return float(value)
        if value_type == "bool":
            if isinstance(value, str):
                return self._bool_from_string(value)
            return bool(value)
        if value_type == "bool_str":
            return self._bool_from_string(value)
        if value_type == "auto_int":
            value_str = str(value).strip()
            return value_str if value_str.lower() == "auto" else int(value_str)
        if value_type == "play_order":
            value_str = str(value or "").strip().lower()
            return value_str if value_str in self.PLAY_ORDER_VALUES else "in_order"
        return "" if value is None else str(value)

    def _serialize(self, value_type: str, value: Any):
        if value_type == "bool_str":
            return "yes" if bool(value) else "no"
        return value

    def _select_fields(self, config: dict[str, Any], schema: dict[str, tuple[str, Any]]) -> dict[str, Any]:
        selected = {}
        for key, (value_type, default) in schema.items():
            raw_value = config.get(key, default)
            selected[key] = self._deserialize(value_type, raw_value)
        return selected

    def _apply_updates(self, config: dict[str, Any], schema: dict[str, tuple[str, Any]], updates: dict[str, Any]) -> dict[str, Any]:
        for key, value in updates.items():
            if key not in schema:
                continue
            value_type, _default = schema[key]
            parsed = self._deserialize(value_type, value)
            config[key] = self._serialize(value_type, parsed)
        return config

    def _normalize_debug_settings(self, config: dict[str, Any]) -> dict[str, Any]:
        if not self._deserialize("bool", config.get("debug_view", False)):
            config["advanced_debug_visuals"] = False
            config["record_debug_preview_clips"] = False
        return config

    def _load_config(self, path: str) -> dict[str, Any]:
        return load_toml_as_dict(path).copy()

    def _save_config(self, path: str, data: dict[str, Any]):
        save_dict_as_toml(data, path)

    def _load_startup_queue_if_enabled(self):
        general_config = self._load_config("cfg/general_config.toml")
        should_load = self._deserialize(
            "bool",
            general_config.get("auto_load_queue_on_startup", True),
        )
        if not should_load:
            return

        try:
            loaded_brawler_data = load_brawler_data()
            loaded_brawler_data = clean_queue(loaded_brawler_data)
            api_update_brawler_data(loaded_brawler_data)
            self.save_queue_data(loaded_brawler_data)
        except Exception as exc:
            print(f"Unable to load startup queue: {exc}")
            import traceback
            traceback.print_exc()

    def get_auth_state(self) -> dict[str, Any]:
        login_required = api_base_url != "localhost" or early_access
        if not login_required:
            return {
                "required": False,
                "authenticated": True,
            }

        saved_key = load_toml_as_dict("cfg/login.toml").get("key", "").strip()

        if not saved_key:
            return {
                "required": True,
                "authenticated": False,
                "message": "Login required.",
                "code": "MISSING_API_KEY",
            }

        try:
            if early_access:
                logger.info("Checking saved API key authentication state.")
                result = validate_early_access_login(saved_key)
                authenticated = bool(result.get("ok") and result.get("authenticated"))
                logger.info(
                    "Saved API key auth state: authenticated=%s code=%s detected_version=%s max_version=%s",
                    authenticated,
                    result.get("code"),
                    result.get("detected_version"),
                    result.get("max_version"),
                )

                return {
                    "required": True,
                    "authenticated": authenticated,
                    "message": result.get("message", ""),
                    "code": result.get("code"),
                    "detected_version": result.get("detected_version"),
                    "max_version": result.get("max_version"),
                }

            # Old fallback, only if early_access module is missing.
            authenticated = check_if_exists(saved_key)

            return {
                "required": True,
                "authenticated": bool(authenticated),
            }

        except Exception as exc:
            logger.exception("Saved API key auth check failed.")
            return {
                "required": True,
                "authenticated": False,
                "message": f"Login check failed: {exc}",
                "code": "LOGIN_CHECK_FAILED",
            }

    def validate_login(self, api_key: str) -> dict[str, Any]:
        if api_base_url == "localhost" and not early_access:
            return {
                "ok": True,
                "authenticated": True,
                "message": "Local mode login bypassed.",
            }

        api_key = (api_key or "").strip()

        if not api_key:
            return {
                "ok": False,
                "authenticated": False,
                "message": "API key is required.",
                "code": "MISSING_API_KEY",
            }

        try:
            if early_access:
                logger.info("Manual API key validation started.")
                result = validate_early_access_login(api_key)

                if result.get("ok") and result.get("authenticated"):
                    save_dict_as_toml({"key": api_key}, "cfg/login.toml")
                    logger.info(
                        "Manual API key validation succeeded: detected_version=%s max_version=%s",
                        result.get("detected_version"),
                        result.get("max_version"),
                    )
                else:
                    logger.warning(
                        "Manual API key validation failed: code=%s message=%s detected_version=%s max_version=%s",
                        result.get("code"),
                        result.get("message"),
                        result.get("detected_version"),
                        result.get("max_version"),
                    )

                return result

            # Old fallback, only if early_access module is missing.
            if not check_if_exists(api_key):
                logger.warning("Legacy API key validation failed.")
                return {
                    "ok": False,
                    "authenticated": False,
                    "message": "Invalid API key.",
                    "code": "INVALID_API_KEY",
                }

            save_dict_as_toml({"key": api_key}, "cfg/login.toml")
            logger.info("Legacy API key validation succeeded.")

            return {
                "ok": True,
                "authenticated": True,
                "message": "Login successful.",
            }

        except Exception as exc:
            logger.exception("Manual API key validation crashed.")
            return {
                "ok": False,
                "authenticated": False,
                "message": f"Login failed: {exc}",
                "code": "LOGIN_FAILED",
            }

    def get_current_version(self) -> str:
        return PYLA_VERSION

    def get_latest_version_safe(self) -> str | None:
        if api_base_url == "localhost":
            return self.get_current_version()
        if self._latest_version_cache is not None:
            return self._latest_version_cache
        try:
            self._latest_version_cache = get_latest_version()
        except Exception:
            self._latest_version_cache = None
        return self._latest_version_cache

    def get_warnings(self) -> list[str]:
        warnings: list[str] = []
        current_version = self.get_current_version()
        latest_version = self.get_latest_version_safe()
        if latest_version:
            try:
                if version.parse(current_version) < version.parse(latest_version):
                    warnings.append(f"New version available: {latest_version}")
            except Exception:
                pass
        return warnings

    def _resolve_brawler_catalog(self) -> list[str]:
        names = get_brawler_list()
        if not names:
            names = list(load_brawlers_info().keys())
        return sorted({name for name in names if name})

    def get_brawler_catalog(self) -> list[dict[str, Any]]:
        return [
            {
                "name": name,
                "slug": normalize_brawler_filename(name),
                "icon_url": f"/api/assets/brawlers/{name}",
            }
            for name in self._resolve_brawler_catalog()
        ]

    def normalize_queue_entry(self, entry: dict[str, Any]) -> dict[str, Any]:
        target_type = str(entry.get("type", "trophies")).strip().lower()
        if target_type not in {"trophies", "wins"}:
            target_type = "trophies"

        brawler = str(entry.get("brawler", "")).strip()
        if not brawler:
            raise ValueError("Brawler is required.")

        normalized = {
            "brawler": brawler,
            "push_until": int(entry.get("push_until", 0) or 0),
            "trophies": int(entry.get("trophies", 0) or 0),
            "wins": int(entry.get("wins", 0) or 0),
            "type": target_type,
            "automatically_pick": True if self._sorted_play_order_enabled() else bool(entry.get("automatically_pick", False)),
            "win_streak": int(entry.get("win_streak", 0) or 0),
        }
        return normalized

    def _sorted_play_order_enabled(self) -> bool:
        play_order = str(self._load_config("cfg/general_config.toml").get("play_order", "in_order")).strip().lower()
        return play_order in {"lowest_to_highest", "highest_to_lowest"}

    def get_queue_data(self) -> list[dict[str, Any]]:
        self._sync_running_queue_from_saved_file()
        queue_items = []
        for item in self._queue_items:
            try:
                normalized = self.normalize_queue_entry(item)
                normalized["current_value"] = normalized[normalized["type"]]
                normalized["target_label"] = "Target Trophies" if normalized["type"] == "trophies" else "Target Wins"
                normalized["current_label"] = "Current Trophies" if normalized["type"] == "trophies" else "Current Wins"
                normalized["icon_url"] = f"/api/assets/brawlers/{normalized['brawler']}"
                queue_items.append(normalized)
            except Exception:
                continue
        return queue_items

    def _assert_queue_editable(self):
        status = self.runtime_manager.get_status()
        if status.get("is_running"):
            raise ValueError("Cannot edit queue while the bot is running or paused. Please stop the bot first.")

    def save_queue_data(self, queue_items: list[dict[str, Any]]):
        normalized_items = [self.normalize_queue_entry(item) for item in queue_items]
        self._queue_items = normalized_items
        try:
            save_brawler_data(normalized_items)
        except Exception as e:
            logger.error(f"Failed to save queue data to file: {e}")
        return normalized_items

    def _sync_running_queue_from_saved_file(self):
        runtime_status = self.runtime_manager.get_status()
        if not runtime_status.get("is_running"):
            return

        queue_path = resolve_project_path("latest_brawler_data.json")
        if not queue_path.exists():
            return

        current_mtime = queue_path.stat().st_mtime
        if self._runtime_queue_mtime == current_mtime:
            return

        loaded_brawler_data = load_brawler_data()
        if isinstance(loaded_brawler_data, list):
            self._queue_items = [self.normalize_queue_entry(item) for item in loaded_brawler_data]
            self._runtime_queue_mtime = current_mtime

    def import_queue_file(self, file_storage) -> list[dict[str, Any]]:
        self._assert_queue_editable()
        if file_storage is None or not file_storage.filename:
            raise ValueError("No queue file selected.")

        raw_content = file_storage.read()
        if not raw_content:
            raise ValueError("Queue file is empty.")

        try:
            payload = json.loads(raw_content.decode("utf-8-sig"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError(f"Queue file is not valid JSON: {exc}") from exc

        if isinstance(payload, dict) and isinstance(payload.get("items"), list):
            payload = payload["items"]

        if not isinstance(payload, list):
            raise ValueError("Queue file must contain a JSON list of brawlers.")

        loaded_brawler_data = clean_queue(payload)
        api_update_brawler_data(loaded_brawler_data)
        self.save_queue_data(loaded_brawler_data)
        return self.get_queue_data()

    def add_or_update_queue_item(self, item: dict[str, Any]) -> list[dict[str, Any]]:
        self._assert_queue_editable()
        normalized = self.normalize_queue_entry(item)
        queue_items = self.get_queue_data()
        for i in range(len(queue_items)):
            if queue_items[i]["brawler"].lower() == normalized["brawler"].lower():
                queue_items[i] = normalized
                break
        else:
            queue_items.append(normalized)
        self.save_queue_data(queue_items)
        return self.get_queue_data()

    def delete_queue_item(self, brawler_name: str) -> list[dict[str, Any]]:
        self._assert_queue_editable()
        queue_items = [entry for entry in self.get_queue_data() if entry["brawler"].lower() != brawler_name.lower()]
        self.save_queue_data(queue_items)
        return self.get_queue_data()

    def clear_queue(self) -> list[dict[str, Any]]:
        self._assert_queue_editable()
        self.save_queue_data([])
        clear_brawler_data()
        return self.get_queue_data()

    def reorder_queue(self, order: list[str]) -> list[dict[str, Any]]:
        self._assert_queue_editable()
        current_queue = self.get_queue_data()
        if current_queue:
            first_item = current_queue[0]
            if not first_item.get("automatically_pick"):
                first_name_lower = first_item["brawler"].lower()
                new_idx = -1
                for idx, name in enumerate(order):
                    if name.lower() == first_name_lower:
                        new_idx = idx
                        break
                if new_idx != 0:
                    first_item["automatically_pick"] = True

        current_items = {entry["brawler"]: entry for entry in current_queue}
        ordered_items = [current_items[name] for name in order if name in current_items]
        remaining = [entry for name, entry in current_items.items() if name not in order]
        self.save_queue_data(ordered_items + remaining)
        return self.get_queue_data()

    def save_queue_to_file(self):
        queue_data = self.get_queue_data()
        queue_data = clean_queue(queue_data)
        save_brawler_data(queue_data)

    def push_all_to_default_target(self) -> dict[str, Any]:
        self._assert_queue_editable()
        general_config = self.get_settings_payload("general")
        target = int(general_config.get("default_trophy_target") or 1000)
        player_tag = str(general_config.get("player_tag", "")).strip().replace("#", "").replace("%23", "")
        if not player_tag:
            raise ValueError("Enter a valid player tag before pushing all brawlers.")

        player_info = get_player_info(player_tag)
        if not self._has_player_values(player_info):
            raise ValueError(INVALID_PLAYER_TAG_MESSAGE)

        queue_items = self.get_queue_data()
        existing_by_key = {entry["brawler"].lower(): entry for entry in queue_items}
        below_target: dict[str, dict[str, Any]] = {}

        for brawler in self._resolve_brawler_catalog():
            trophies, win_streak = get_brawler_stats(player_info, brawler)
            if trophies is None:
                continue

            current_trophies = int(trophies or 0)
            if current_trophies >= target:
                continue

            key = brawler.lower()
            existing = existing_by_key.get(key, {})
            below_target[key] = {
                "brawler": brawler,
                "type": "trophies",
                "push_until": target,
                "trophies": current_trophies,
                "wins": int(existing.get("wins", 0) or 0),
                "automatically_pick": bool(existing.get("automatically_pick", True)),
                "win_streak": int(win_streak or 0),
            }

        updated_queue = []
        queued_keys = set()
        for item in queue_items:
            key = item["brawler"].lower()
            if key in below_target:
                updated_queue.append(below_target[key])
                queued_keys.add(key)
            else:
                updated_queue.append(item)

        for key, item in below_target.items():
            if key not in queued_keys:
                updated_queue.append(item)

        self.save_queue_data(updated_queue)
        return {"items": self.get_queue_data(), "added_count": len(below_target)}

    def get_playstyles_payload(self) -> dict[str, Any]:
        bot_config = self._load_config("cfg/bot_config.toml")
        current_playstyle = bot_config.get("current_playstyle", "default_up.pyla")
        playstyles = []
        for item in get_playstyles_list():
            metadata = item.get("metadata") or {}
            filename = item.get("filename")
            playstyles.append({
                "filename": filename,
                "name": metadata.get("name") or filename.replace(".pyla", ""),
                "description": metadata.get("description") or "No description provided.",
                "author": metadata.get("author") or "Unknown",
                "date": metadata.get("date") or "",
                "brawlers": metadata.get("brawlers") or [],
                "gamemodes": metadata.get("gamemodes") or [],
                "is_active": filename == current_playstyle,
            })

        playstyles.sort(key=lambda playstyle: playstyle["name"].lower())
        current = next((item for item in playstyles if item["is_active"]), None)
        return {"current": current, "items": playstyles}

    def activate_playstyle(self, filename: str) -> dict[str, Any]:
        target_path = resolve_project_path("playstyles", filename)
        if not target_path.exists():
            raise FileNotFoundError(f"Playstyle '{filename}' was not found.")

        metadata, script = load_pyla_script(filename)
        if not script.strip():
            raise ValueError("Playstyle file is empty or invalid.")

        bot_config = self._load_config("cfg/bot_config.toml")
        bot_config["current_playstyle"] = filename
        self._save_config("cfg/bot_config.toml", bot_config)
        return {"ok": True, "playstyles": self.get_playstyles_payload(), "metadata": metadata}

    def delete_playstyle(self, filename: str) -> dict[str, Any]:
        safe_filename = secure_filename(filename)
        if safe_filename != filename or not safe_filename.endswith(".pyla"):
            raise ValueError("Invalid playstyle filename.")

        filename = safe_filename
        target_path = resolve_project_path("playstyles", filename)
        if not target_path.exists():
            raise FileNotFoundError(f"Playstyle '{filename}' was not found.")

        bot_config = self._load_config("cfg/bot_config.toml")
        if bot_config.get("current_playstyle") == filename:
            raise ValueError("Cannot delete the currently active playstyle.")

        target_path.unlink()
        return {"ok": True, "playstyles": self.get_playstyles_payload()}

    def import_playstyle(self, file_storage) -> dict[str, Any]:
        if file_storage is None or not file_storage.filename:
            raise ValueError("No playstyle file uploaded.")

        original_name = secure_filename(file_storage.filename)
        base_name = Path(original_name).stem or "imported_playstyle"
        filename = f"{base_name}.pyla"
        target_path = resolve_project_path("playstyles", filename)

        temp_path = resolve_project_path("playstyles", f".__upload__{filename}")
        file_storage.save(temp_path)

        try:
            with open(temp_path, "r", encoding="utf-8") as handle:
                metadata_line = handle.readline().strip()
                if not metadata_line:
                    raise ValueError("Missing playstyle metadata header.")
                json.loads(metadata_line)

            uploaded_content = temp_path.read_text(encoding="utf-8")

            if target_path.exists():
                existing_content = target_path.read_text(encoding="utf-8")
                if existing_content == uploaded_content:
                    return {"ok": True, "filename": target_path.name, "playstyles": self.get_playstyles_payload()}

            if target_path.exists():
                suffix = 2
                while resolve_project_path("playstyles", f"{base_name}_{suffix}.pyla").exists():
                    suffix += 1
                target_path = resolve_project_path("playstyles", f"{base_name}_{suffix}.pyla")

            shutil.move(str(temp_path), str(target_path))
        finally:
            if temp_path.exists():
                temp_path.unlink()

        return {"ok": True, "filename": target_path.name, "playstyles": self.get_playstyles_payload()}

    def get_settings_payload(self, section: str) -> dict[str, Any]:
        section = section.lower()
        if section == "general":
            return self._select_fields(self._load_config("cfg/general_config.toml"), self.GENERAL_FIELDS)
        if section == "bot":
            payload = self._select_fields(self._load_config("cfg/bot_config.toml"), self.BOT_FIELDS)
            payload["current_playstyle"] = self._load_config("cfg/bot_config.toml").get("current_playstyle", "default_up.pyla")
            return payload
        if section == "timers":
            return self._select_fields(self._load_config("cfg/time_tresholds.toml"), self.TIMER_FIELDS)
        if section == "debug":
            return self._select_fields(self._normalize_debug_settings(self._load_config("cfg/debug_settings.toml")), self.DEBUG_FIELDS)
        if section == "webhook":
            config = self._load_config("cfg/webhook_config.toml")
            return self._select_fields(config, self.WEBHOOK_FIELDS)
        raise KeyError(f"Unknown settings section: {section}")

    def update_settings(self, section: str, payload: dict[str, Any]) -> dict[str, Any]:
        section = section.lower()
        payload = payload or {}
        if section == "general":
            config = self._load_config("cfg/general_config.toml")
            self._save_config("cfg/general_config.toml", self._apply_updates(config, self.GENERAL_FIELDS, payload))
            if "play_order" in payload and self.get_settings_payload("general").get("play_order") != "in_order":
                self.save_queue_data([
                    {**entry, "automatically_pick": True}
                    for entry in self.get_queue_data()
                ])
            return self.get_settings_payload("general")
        if section == "bot":
            config = self._load_config("cfg/bot_config.toml")
            if "current_playstyle" in payload:
                config["current_playstyle"] = str(payload["current_playstyle"])
            self._save_config("cfg/bot_config.toml", self._apply_updates(config, self.BOT_FIELDS, payload))
            return self.get_settings_payload("bot")
        if section == "timers":
            config = self._load_config("cfg/time_tresholds.toml")
            self._save_config("cfg/time_tresholds.toml", self._apply_updates(config, self.TIMER_FIELDS, payload))
            return self.get_settings_payload("timers")
        if section == "debug":
            config = self._load_config("cfg/debug_settings.toml")
            updated_config = self._normalize_debug_settings(self._apply_updates(config, self.DEBUG_FIELDS, payload))
            self._save_config("cfg/debug_settings.toml", updated_config)
            return self.get_settings_payload("debug")
        if section == "webhook":
            config = self._load_config("cfg/webhook_config.toml")
            self._save_config("cfg/webhook_config.toml", self._apply_updates(config, self.WEBHOOK_FIELDS, payload))
            return self.get_settings_payload("webhook")
        raise KeyError(f"Unknown settings section: {section}")

    def reset_settings(self, section: str) -> dict[str, Any]:
        section = section.lower()
        schema_map = {
            "general": (self.GENERAL_FIELDS, "cfg/general_config.toml"),
            "bot": (self.BOT_FIELDS, "cfg/bot_config.toml"),
            "timers": (self.TIMER_FIELDS, "cfg/time_tresholds.toml"),
            "debug": (self.DEBUG_FIELDS, "cfg/debug_settings.toml"),
            "webhook": (self.WEBHOOK_FIELDS, "cfg/webhook_config.toml"),
        }
        if section not in schema_map:
            raise KeyError(f"Unknown settings section: {section}")

        schema, path = schema_map[section]
        
        # Load the existing configuration to preserve other non-schema keys (like cpu_or_gpu, wall_model_classes)
        config = self._load_config(path)
        
        # Reset schema fields to their default values defined in services.py
        for key, (value_type, default_val) in schema.items():
            config[key] = self._serialize(value_type, default_val)
            
        # Ensure specified credential fields are empty as requested
        if section == "general":
            config["player_tag"] = ""
        elif section == "webhook":
            config["discord_id"] = ""
            config["discord_bot_token"] = ""
            config["discord_guild_id"] = ""
            
        self._save_config(path, config)

        # Post-reset processing
        if section == "general":
            if self.get_settings_payload("general").get("play_order") != "in_order":
                self.save_queue_data([
                    {**entry, "automatically_pick": True}
                    for entry in self.get_queue_data()
                ])
        elif section == "debug":
            config = self._load_config("cfg/debug_settings.toml")
            self._save_config("cfg/debug_settings.toml", self._normalize_debug_settings(config))

        return self.get_settings_payload(section)

    def get_player_info_payload(self, player_tag: str) -> dict[str, Any]:
        player_tag = (player_tag or "").strip()
        clean_tag = player_tag.replace("#", "").replace("%23", "")
        if not clean_tag:
            return {"ok": True, "player_tag": "", "player_name": "", "stats": {}}

        player_info = get_player_info(clean_tag)
        if not self._has_player_values(player_info):
            return {
                "ok": False,
                "message": INVALID_PLAYER_TAG_MESSAGE,
                "player_tag": clean_tag,
                "stats": {},
                "code": "INVALID_PLAYER_TAG",
            }

        stats = {}
        brawler_catalog = self._resolve_brawler_catalog()
        for brawler in brawler_catalog:
            trophies, win_streak = get_brawler_stats(player_info, brawler)
            if trophies is None and win_streak is None:
                continue
            stats[brawler] = {
                "trophies": int(trophies or 0),
                "win_streak": int(win_streak or 0),
            }

        if brawler_catalog and not stats:
            return {
                "ok": False,
                "message": INVALID_PLAYER_TAG_MESSAGE,
                "player_tag": clean_tag,
                "stats": {},
                "code": "INVALID_PLAYER_TAG",
            }

        return {
            "ok": True,
            "player_tag": clean_tag,
            "player_name": player_info.get("name", ""),
            "stats": stats,
        }

    @staticmethod
    def _has_player_values(player_info: Any) -> bool:
        if not isinstance(player_info, dict):
            return False
        return bool(player_info.get("name") and isinstance(player_info.get("brawlers"), list) and player_info.get("brawlers"))

    def get_match_history_payload(self) -> dict[str, Any]:
        csv_path = resolve_project_path("cfg", "match_history.csv")

        grouped: dict[str, dict[str, Any]] = {}

        with csv_path.open("r", encoding="utf-8-sig", newline="") as handle:
            for row in csv.DictReader(handle):
                brawler = str(row.get("brawler_name", "")).strip()
                if not brawler:
                    continue

                result = str(row.get("result", "")).strip().lower()
                item = grouped.setdefault(brawler, {
                    "brawler": brawler,
                    "wins": 0,
                    "losses": 0,
                    "total_matches": 0,
                    "trophy_delta": 0,
                    "matches": [],
                    "last_played": "",
                    "last_played_sort": "",
                })

                trophy_before = self._parse_int(row.get("current_trophies"))
                trophy_delta = self._parse_int(row.get("trophy_delta"), 0) or 0
                trophy_after = trophy_before + trophy_delta if trophy_before is not None else None
                win_streak = self._parse_int(row.get("new_winstreak"), 0) or 0
                power_level = self._parse_int(row.get("power_level"))
                item["trophy_delta"] += trophy_delta

                played_at = self._parse_match_datetime(row.get("date_time"))
                played_at_sort = played_at.isoformat() if played_at else ""
                if played_at and played_at.isoformat() > item["last_played_sort"]:
                    item["last_played"] = played_at.strftime("%Y-%m-%d %H:%M")
                    item["last_played_sort"] = played_at.isoformat()

                item["matches"].append({
                    "date_time": played_at.strftime("%Y-%m-%d %H:%M") if played_at else str(row.get("date_time", "")).strip(),
                    "date_sort": played_at_sort,
                    "result": result,
                    "trophy_before": trophy_before,
                    "trophy_delta": trophy_delta,
                    "trophy_after": trophy_after,
                    "win_streak": win_streak,
                    "playstyle_name": str(row.get("playstyle_name", "") or "").strip(),
                    "playstyle_gamemodes": [
                        value for value in str(row.get("playstyle_gamemodes", "") or "").split("|") if value
                    ],
                    "pyla_version": str(row.get("pyla_version", "") or "").strip(),
                    "power_level": power_level,
                })

                if result == "victory":
                    item["wins"] += 1
                elif result == "defeat":
                    item["losses"] += 1
                else:
                    continue

                item["total_matches"] += 1

        items = []
        for brawler, stats in grouped.items():
            total_matches = int(stats["total_matches"])
            if total_matches == 0:
                continue

            wins = int(stats["wins"])
            losses = int(stats["losses"])
            matches = sorted(stats["matches"], key=lambda match: match["date_sort"] or match["date_time"])
            trophy_points = [
                {
                    "label": match["date_time"],
                    "value": match["trophy_after"],
                    "delta": match["trophy_delta"],
                    "result": match["result"],
                }
                for match in matches
                if match["trophy_after"] is not None
            ]
            trophy_values = [point["value"] for point in trophy_points]
            playstyle_counts: dict[str, int] = {}
            for match in matches:
                playstyle_name = match["playstyle_name"] or "Unknown"
                playstyle_counts[playstyle_name] = playstyle_counts.get(playstyle_name, 0) + 1

            items.append({
                "brawler": brawler,
                "icon_url": f"/api/assets/brawlers/{brawler}",
                "wins": wins,
                "losses": losses,
                "total_matches": total_matches,
                "win_rate": round((wins / total_matches) * 100, 1),
                "loss_rate": round((losses / total_matches) * 100, 1),
                "trophy_delta": int(stats["trophy_delta"]),
                "last_played": stats["last_played"],
                "last_played_sort": stats["last_played_sort"],
                "current_trophies": trophy_values[-1] if trophy_values else None,
                "peak_trophies": max(trophy_values) if trophy_values else None,
                "lowest_trophies": min(trophy_values) if trophy_values else None,
                "best_trophy_delta": max((match["trophy_delta"] for match in matches), default=0),
                "worst_trophy_delta": min((match["trophy_delta"] for match in matches), default=0),
                "best_win_streak": max((match["win_streak"] for match in matches), default=0),
                "latest_power_level": next((match["power_level"] for match in reversed(matches) if match["power_level"] is not None and match["power_level"] >= 0), None),
                "trophy_points": trophy_points,
                "recent_matches": list(reversed(matches[-8:])),
                "playstyles": [
                    {"name": name, "matches": count}
                    for name, count in sorted(playstyle_counts.items(), key=lambda item: (-item[1], item[0].lower()))
                ],
            })

        items.sort(key=lambda item: (-item["total_matches"], item["brawler"]))
        return self._build_match_history_response(items)

    @staticmethod
    def _parse_match_datetime(value: Any) -> datetime | None:
        raw_value = str(value or "").strip()
        if not raw_value:
            return None
        try:
            return datetime.fromisoformat(raw_value)
        except ValueError:
            try:
                return datetime.strptime(raw_value, "%Y-%m-%d %H:%M:%S.%f")
            except ValueError:
                return None

    @staticmethod
    def _parse_int(value: Any, default: int | None = None) -> int | None:
        try:
            return int(float(value))
        except (TypeError, ValueError):
            return default

    @staticmethod
    def _build_match_history_response(items: list[dict[str, Any]]) -> dict[str, Any]:
        total_matches = sum(item["total_matches"] for item in items)
        wins = sum(item["wins"] for item in items)
        losses = sum(item["losses"] for item in items)
        summary = {
            "total_matches": total_matches,
            "wins": wins,
            "losses": losses,
            "tracked_brawlers": len(items),
        }
        if total_matches:
            summary["win_rate"] = round((summary["wins"] / total_matches) * 100, 1)
            summary["loss_rate"] = round((summary["losses"] / total_matches) * 100, 1)
        else:
            summary["win_rate"] = summary["loss_rate"] = 0.0

        return {"summary": summary, "items": items}

    def get_bootstrap_payload(self) -> dict[str, Any]:
        discord_link = get_discord_link()
        auth_payload = self.get_auth_state()
        auth_payload["early_access"] = early_access
        return {
            "app": {
                "name": "PylaAI",
                "version": self.get_current_version(),
                "latest_version": self.get_latest_version_safe(),
                "warnings": self.get_warnings(),
            },
            "auth": auth_payload,
            "runtime": self.runtime_manager.get_status(),
            "links": {
                "discord": {
                    "label": discord_link,
                    "url": discord_link,
                    "icon_url": "/api/assets/support/discord_logo.png",
                },
                "patreon": {
                    "label": PATREON_LABEL,
                    "url": PATREON_LINK,
                    "icon_url": "/api/assets/support/patreon.png",
                },
            },
            "queue": self.get_queue_data(),
            "playstyles": self.get_playstyles_payload(),
            "settings": {
                "general": self.get_settings_payload("general"),
                "bot": self.get_settings_payload("bot"),
                "timers": self.get_settings_payload("timers"),
                "debug": self.get_settings_payload("debug"),
                "webhook": self.get_settings_payload("webhook"),
            },
            "history": self.get_match_history_payload(),
            "brawlers": self.get_brawler_catalog(),
        }
