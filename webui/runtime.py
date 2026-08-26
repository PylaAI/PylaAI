from __future__ import annotations

import threading
from typing import Any, Callable
import traceback


class RuntimeControl:
    def __init__(self, state_callback: Callable[[str], None]):
        self._state_callback = state_callback
        self._stop_event = threading.Event()
        self._pause_requested = threading.Event()

    def request_pause(self):
        self._pause_requested.set()

    def resume(self):
        self._pause_requested.clear()

    def request_stop(self):
        self._stop_event.set()
        self._pause_requested.clear()

    def should_stop(self) -> bool:
        return self._stop_event.is_set()

    def should_pause(self) -> bool:
        return self._pause_requested.is_set() and not self._stop_event.is_set()

    def mark_running(self):
        self._state_callback("running")

    def mark_paused(self):
        self._state_callback("paused")


class RuntimeManager:
    def __init__(self, pyla_main):
        self.pyla_main = pyla_main
        self._thread: threading.Thread | None = None
        self.rt_control: RuntimeControl | None = None
        self._lock = threading.Lock()
        self._state = "idle"
        self._last_error = ""
        self.queue_provider: Callable[[], list[dict[str, Any]]] | None = None
        self._auth_provider: Callable[[], dict[str, Any]] | None = None
    def _set_state(self, state: str):
        with self._lock:
            self._state = state

    def configure_start_gate(
            self,
            queue_provider: Callable[[], list[dict[str, Any]]],
            auth_provider: Callable[[], dict[str, Any]],
    ):
        self.queue_provider = queue_provider
        self._auth_provider = auth_provider

    def get_status(self) -> dict[str, Any]:
        with self._lock:
            thread_alive = self._thread.is_alive() if self._thread else False
            if not thread_alive and self._state != "error":
                self._state = "idle"
                self._thread = None
                self.rt_control = None
            return {
                "state": self._state,
                "is_running": thread_alive,
                "last_error": self._last_error,
            }

    def start(self, queue_data: list[dict[str, Any]], discord_bot) -> dict[str, Any]:
        with self._lock:
            thread_alive = self._thread.is_alive() if self._thread else False

            if thread_alive:
                if self._state == "paused" and self.rt_control:
                    self.rt_control.resume()
                    self._state = "running"
                    self._last_error = ""
                    return {"ok": True, "message": "Pyla resumed."}
                return {"ok": False, "message": f"Pyla cannot start while state is {self._state}."}

            self.rt_control = RuntimeControl(self._set_state)
            self._state = "running"
            self._last_error = ""
            self._thread = threading.Thread(
                target=self._run_worker,
                args=(queue_data, self.rt_control, discord_bot),
                daemon=True,
                name="pyla-runtime",
            )
            self._thread.start()
            return {"ok": True, "message": "Pyla started."}

    def start_current_queue(self, discord_bot) -> dict[str, Any]:
        if not self.queue_provider or not self._auth_provider:
            return {
                "ok": False,
                "message": "Runtime start gate is not configured.",
                "code": "START_GATE_NOT_CONFIGURED",
            }

        runtime_state = self.get_status()["state"]
        queue_data = self.queue_provider()
        if runtime_state != "paused" and not queue_data:
            return {"ok": False, "message": "Queue is empty.", "code": "EMPTY_QUEUE"}

        auth_state = self._auth_provider()
        if auth_state.get("required") and not auth_state.get("authenticated"):
            return {
                "ok": False,
                "message": auth_state.get("message") or "Login required before starting.",
                "code": auth_state.get("code") or "LOGIN_REQUIRED",
                "auth": auth_state,
            }

        return self.start(queue_data, discord_bot)

    def _run_worker(self, queue_data: list[dict[str, Any]], control: RuntimeControl, discord_bot):
        try:
            self.pyla_main(discord_bot, queue_data, runtime_control=control)
            with self._lock:
                if self._state != "error":
                    self._state = "idle"
        except SystemExit as exc:
            code = exc.code if isinstance(exc.code, int) else 0
            with self._lock:
                if code in (0, None):
                    self._state = "idle"
                    self._last_error = ""
                else:
                    self._state = "error"
                    self._last_error = f"Pyla exited with code {code}."
        except Exception as exc:
            with self._lock:
                self._state = "error"
                self._last_error = str(exc)
                print(str(exc))
                traceback.print_exc()
        finally:
            with self._lock:
                self._thread = None
                self.rt_control = None

    def pause(self) -> dict[str, Any]:
        with self._lock:
            thread_alive = self._thread.is_alive() if self._thread else False
            if not thread_alive or not self.rt_control:
                return {"ok": False, "message": "Pyla is not running."}

            if self._state == "running":
                self.rt_control.request_pause()
                self._state = "pausing"
                return {"ok": True, "message": "Pause requested. Pyla will pause in the lobby."}

            if self._state in {"pausing", "paused"}:
                return {"ok": True, "message": "Pause already requested."}

            return {"ok": False, "message": f"Pyla cannot pause while state is {self._state}."}

    def stop(self) -> dict[str, Any]:
        with self._lock:
            thread_alive = self._thread.is_alive() if self._thread else False
            if not thread_alive or not self.rt_control:
                self._state = "idle"
                return {"ok": True, "message": "Pyla is already stopped."}

            thread = self._thread
            was_paused = self._state == "paused"
            self.rt_control.request_stop()
            self._state = "stopping"

        if was_paused and thread:
            thread.join(timeout=2)
            if not thread.is_alive():
                with self._lock:
                    stopped_state = self._state
                    self._thread = None
                    self.rt_control = None
                    if self._state != "error":
                        self._state = "idle"
                        stopped_state = "idle"
                if stopped_state == "error":
                    return {"ok": False, "message": self._last_error or "Pyla stopped with an error."}
                return {"ok": True, "message": "Pyla stopped."}

        return {"ok": True, "message": "Stop requested. Pyla is shutting down."}
