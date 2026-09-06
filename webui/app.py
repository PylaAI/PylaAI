from __future__ import annotations

from datetime import date
import hmac
import logging
import secrets
import threading
from urllib.parse import urlsplit

from flask import Flask, jsonify, render_template, request, send_file
from werkzeug.exceptions import HTTPException

from discord_bot import DiscordBot
from utils import get_brawler_icon_path, resolve_project_path, resolve_within
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
        )

class _SupressHistoryPolling(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        message = record.getMessage()
        return not (
            'GET /api/history' in message
            and ' 200 -' in message
        )

class _SuppressWebhookPutting(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        message = record.getMessage()
        return not (
            'PUT /api/webhook ' in message
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
    if not any(isinstance(log_filter, _SuppressWebhookPutting) for log_filter in werkzeug_logger.filters):
        werkzeug_logger.addFilter(_SuppressWebhookPutting())



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
    app.config["MAX_CONTENT_LENGTH"] = 2 * 1024 * 1024
    app.config["UI_API_TOKEN"] = secrets.token_urlsafe(32)

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

    def _parsed_request_host():
        try:
            return urlsplit(f"//{request.host}")
        except ValueError:
            return None

    def _is_allowed_origin(origin: str) -> bool:
        try:
            parsed_origin = urlsplit(origin)
            parsed_host = _parsed_request_host()
            if parsed_host is None:
                return False
            return (
                parsed_origin.scheme in {"http", "https"}
                and parsed_origin.hostname in {"127.0.0.1", "localhost", "::1"}
                and parsed_origin.hostname == parsed_host.hostname
                and parsed_origin.port == parsed_host.port
            )
        except ValueError:
            return False

    @app.before_request
    def protect_local_control_api():
        parsed_host = _parsed_request_host()
        if parsed_host is None or parsed_host.hostname not in {"127.0.0.1", "localhost", "::1"}:
            return jsonify({
                "ok": False,
                "message": "Invalid local UI host.",
                "code": "INVALID_LOCAL_HOST",
            }), 403

        if not request.path.startswith("/api/") or request.path.startswith("/api/assets/"):
            return None

        supplied_token = str(request.headers.get("X-Pyla-UI-Token", ""))
        if not hmac.compare_digest(supplied_token, app.config["UI_API_TOKEN"]):
            return jsonify({
                "ok": False,
                "message": "Invalid local UI session.",
                "code": "INVALID_UI_SESSION",
            }), 403

        origin = str(request.headers.get("Origin", "")).strip()
        if origin and not _is_allowed_origin(origin):
            return jsonify({
                "ok": False,
                "message": "Cross-origin local API request rejected.",
                "code": "INVALID_UI_ORIGIN",
            }), 403

        return None

    @app.after_request
    def add_local_security_headers(response):
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Cache-Control"] = "no-store"
        return response

    @app.get("/")
    def index():
        return render_template(
            "index.html",
            ui_api_token=app.config["UI_API_TOKEN"],
        )

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

    @app.get("/api/runtime/logs")
    def runtime_logs():
        return jsonify({"ok": True, "logs": runtime_manager.get_logs()})

    @app.delete("/api/runtime/logs")
    def clear_runtime_logs():
        runtime_manager.clear_logs()
        return jsonify({"ok": True, "items": []})

    @app.get("/api/history")
    def history():
        start_date_raw = str(request.args.get("start_date", "")).strip()
        end_date_raw = str(request.args.get("end_date", "")).strip()
        try:
            start_date = date.fromisoformat(start_date_raw) if start_date_raw else None
            end_date = date.fromisoformat(end_date_raw) if end_date_raw else None
        except ValueError:
            return jsonify({
                "ok": False,
                "message": "History dates must use the YYYY-MM-DD format.",
            }), 400

        if start_date and end_date and start_date > end_date:
            return jsonify({
                "ok": False,
                "message": "The history start date must be on or before the end date.",
            }), 400

        return jsonify(data_service.get_match_history_payload(
            start_date=start_date,
            end_date=end_date,
        ))

    @app.get("/api/assets/brawlers/<path:brawler_name>")
    def brawler_icon(brawler_name: str):
        icon_path = get_brawler_icon_path(brawler_name)
        if icon_path is None:
            return ("", 404)
        return send_file(icon_path)

    @app.get("/api/assets/support/<path:filename>")
    def support_asset(filename: str):
        try:
            target = resolve_within("images", filename)
        except ValueError:
            return ("", 404)
        if not target.is_file():
            return ("", 404)
        return send_file(target)

    if start_discord_bot:
        _start_discord_bot_thread(app)

    return app
