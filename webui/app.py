from __future__ import annotations

import logging
import threading

from flask import Flask, jsonify, render_template, request, send_file
from werkzeug.exceptions import HTTPException

from discord_bot import DiscordBot
from utils import get_brawler_icon_path, resolve_project_path
from .runtime import RuntimeManager
from .services import WebDataService


class _SuppressRuntimeStatusPolling(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        message = record.getMessage()
        return not (
            '"GET /api/queue ' in message
            and ' 200 -' in message
        )

class _SuppressQueuePolling(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        message = record.getMessage()
        return not (
            '"GET /api/runtime/status ' in message
            and ' 200 -' in message
        )

class _SuppressAssetsGetting(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        message = record.getMessage()
        return not (
            'GET /api/assets' in message
            and '304 -' in message
        )

class _SupressHistoryPolling(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        message = record.getMessage()
        return not (
            'GET /api/history ' in message
            and ' 200 -' in message
        )

def _configure_request_logging():
    werkzeug_logger = logging.getLogger("werkzeug")
    if not any(isinstance(log_filter, _SuppressRuntimeStatusPolling) for log_filter in werkzeug_logger.filters):
        werkzeug_logger.addFilter(_SuppressRuntimeStatusPolling())
    if not any(isinstance(log_filter, _SuppressQueuePolling) for log_filter in werkzeug_logger.filters):
        werkzeug_logger.addFilter(_SuppressQueuePolling())
    if not any(isinstance(log_filter, _SuppressAssetsGetting) for log_filter in werkzeug_logger.filters):
        werkzeug_logger.addFilter(_SuppressAssetsGetting())
    if not any(isinstance(log_filter, _SupressHistoryPolling) for log_filter in werkzeug_logger.filters):
        werkzeug_logger.addFilter(_SupressHistoryPolling())


def _start_discord_bot_thread(app: Flask):
    discord_bot = app.config["discord_bot"]
    with app.config["discord_bot_lock"]:
        discord_thread = app.config.get("discord_bot_thread")
        if discord_thread and discord_thread.is_alive():
            return

        discord_thread = threading.Thread(
            target=discord_bot.run_bot,
            daemon=True,
            name="pyla-discord-bot",
        )
        app.config["discord_bot_thread"] = discord_thread
        discord_thread.start()


def create_app(pyla_main, start_discord_bot=False):
    app = Flask(
        __name__,
        template_folder=str(resolve_project_path("templates")),
        static_folder=str(resolve_project_path("static")),
    )

    runtime_manager = RuntimeManager(pyla_main)
    data_service = WebDataService(runtime_manager)
    discord_bot = DiscordBot(runtime_manager, data_service)
    runtime_manager.configure_start_gate(data_service.get_queue_data, data_service.get_auth_state)
    app.config["runtime_manager"] = runtime_manager
    app.config["data_service"] = data_service
    app.config["discord_bot"] = discord_bot
    app.config["discord_bot_thread"] = None
    app.config["discord_bot_lock"] = threading.Lock()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s [%(name)s] %(message)s")
    _configure_request_logging()

    @app.get("/")
    def index():
        return render_template("index.html")

    @app.get("/api/bootstrap")
    def bootstrap():
        return jsonify(data_service.get_bootstrap_payload())

    @app.errorhandler(KeyError)
    @app.errorhandler(FileNotFoundError)
    @app.errorhandler(ValueError)
    def handle_known_errors(error):
        app.logger.warning("Handled request error at %s: %s", request.path, error)
        return jsonify({"ok": False, "message": str(error)}), 400

    @app.errorhandler(Exception)
    def handle_unexpected_error(error):
        if isinstance(error, HTTPException):
            return error
        app.logger.exception("Unhandled request error at %s", request.path)
        return jsonify({"ok": False, "message": str(error)}), 500

    @app.post("/api/login/validate")
    def validate_login():
        payload = request.get_json(silent=True) or {}
        result = data_service.validate_login(payload.get("api_key", ""))
        return jsonify(result), (200 if result.get("ok") else 400)

    @app.get("/api/player-info")
    def player_info():
        result = data_service.get_player_info_payload(request.args.get("tag", ""))
        return jsonify(result), (200 if result.get("ok") else 400)

    @app.get("/api/queue")
    def get_queue():
        return jsonify({"items": data_service.get_queue_data()})

    @app.post("/api/queue")
    def add_queue():
        payload = request.get_json(silent=True) or {}
        items = data_service.add_or_update_queue_item(payload)
        return jsonify({"ok": True, "items": items})

    @app.post("/api/queue/import")
    def import_queue():
        uploaded_file = request.files.get("file")
        items = data_service.import_queue_file(uploaded_file)
        return jsonify({"ok": True, "items": items})

    @app.put("/api/queue/<path:brawler_name>")
    def update_queue_item(brawler_name: str):
        payload = request.get_json(silent=True) or {}
        payload["brawler"] = brawler_name
        items = data_service.add_or_update_queue_item(payload)
        return jsonify({"ok": True, "items": items})

    @app.post("/api/queue/reorder")
    def reorder_queue():
        payload = request.get_json(silent=True) or {}
        items = data_service.reorder_queue(payload.get("order", []))
        return jsonify({"ok": True, "items": items})

    @app.post("/api/queue/push-all-to-target")
    def push_all_to_target():
        result = data_service.push_all_to_default_target()
        return jsonify({"ok": True, **result})

    @app.delete("/api/queue")
    def clear_queue():
        items = data_service.clear_queue()
        return jsonify({"ok": True, "items": items})

    @app.delete("/api/queue/<path:brawler_name>")
    def delete_queue_item(brawler_name: str):
        items = data_service.delete_queue_item(brawler_name)
        return jsonify({"ok": True, "items": items})

    @app.get("/api/playstyles")
    def get_playstyles():
        return jsonify(data_service.get_playstyles_payload())

    @app.post("/api/playstyles/import")
    def import_playstyle():
        uploaded_file = request.files.get("file")
        result = data_service.import_playstyle(uploaded_file)
        return jsonify(result)
    @app.delete("/api/playstyles/<path:filename>")
    def delete_playstyle(filename: str):
        result = data_service.delete_playstyle(filename)
        return jsonify(result)

    @app.put("/api/playstyles/active")
    def activate_playstyle():
        payload = request.get_json(silent=True) or {}
        result = data_service.activate_playstyle(payload.get("filename", ""))
        return jsonify(result)

    @app.get("/api/settings/<section>")
    def get_settings(section: str):
        return jsonify(data_service.get_settings_payload(section))

    @app.put("/api/settings/<section>")
    def update_settings(section: str):
        payload = request.get_json(silent=True) or {}
        return jsonify(data_service.update_settings(section, payload))

    @app.post("/api/settings/<section>/reset")
    def reset_settings(section: str):
        return jsonify(data_service.reset_settings(section))

    @app.post("/api/runtime/start")
    def runtime_start():
        result = runtime_manager.start_current_queue(discord_bot)
        if result.get("ok"):
            status_code = 200
        elif result.get("code") == "EMPTY_QUEUE":
            status_code = 400
        elif "auth" in result:
            status_code = 403
        else:
            status_code = 409
        return jsonify({**result, "runtime": runtime_manager.get_status()}), status_code

    @app.get("/api/runtime/status")
    def runtime_status():
        return jsonify({"ok": True, "runtime": runtime_manager.get_status()})

    @app.post("/api/runtime/pause")
    def runtime_pause():
        result = runtime_manager.pause()
        status_code = 200 if result.get("ok") else 409
        return jsonify({**result, "runtime": runtime_manager.get_status()}), status_code

    @app.post("/api/runtime/stop")
    def runtime_stop():
        result = runtime_manager.stop()
        status_code = 200 if result.get("ok") else 409
        return jsonify({**result, "runtime": runtime_manager.get_status()}), status_code

    @app.get("/api/history")
    def history():
        return jsonify(data_service.get_match_history_payload())

    @app.get("/api/assets/brawlers/<path:brawler_name>")
    def brawler_icon(brawler_name: str):
        icon_path = get_brawler_icon_path(brawler_name)
        if icon_path is None:
            return ("", 404)
        return send_file(icon_path)

    @app.get("/api/assets/support/<path:filename>")
    def support_asset(filename: str):
        target = resolve_project_path("images", filename)
        if not target.exists():
            return ("", 404)
        return send_file(target)

    if start_discord_bot:
        _start_discord_bot_thread(app)

    return app
