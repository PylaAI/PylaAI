"""Optional public match diagnostics, written as compressed JSONL in match_logs/default.

Records contain match metadata, processed detections, movement and ability decisions,
touch coordinates and send durations, and the final detected state. Disk I/O runs on
a background thread. Timestamps use time.perf_counter() unless explicitly named wall_time.
"""
import atexit
import gzip
import json
import queue
import secrets
import threading
import time
from datetime import datetime, timezone

from utils import config_bool, load_toml_as_dict, resolve_project_path

LOG_VERSION = 1
# Frames in a non-match state before the recording is closed; the state checker can lag a little.
END_AFTER_NON_MATCH_FRAMES = 3
FLUSH_INTERVAL_S = 2.0


def _json_default(value):
    # numpy scalars (np.bool_, np.float32, ...) expose .item(); anything else is logged as text.
    return value.item() if hasattr(value, "item") else str(value)


def _round_box(box, conf=None):
    out = [round(float(v), 1) for v in box[:4]]
    if conf is not None:
        out.append(round(float(conf), 3))
    return out


class MatchLogger:
    def __init__(self, instance_id=None):
        self.instance_id = instance_id
        try:
            self.enabled = config_bool(load_toml_as_dict("cfg/debug_settings.toml").get("match_logging"), False)
        except ValueError:
            self.enabled = False
        self._lock = threading.RLock()
        self._closed = False
        self.active = False
        self.frame_index = 0
        self.non_match_frames = 0
        self._queue = None
        self._thread = None
        if self.enabled:
            self._queue = queue.SimpleQueue()
            self._thread = threading.Thread(target=self._writer, name="match-logger", daemon=True)
            self._thread.start()
            atexit.register(self.shutdown)

    # ---- recording lifecycle -------------------------------------------------------------------

    def start(self, header):
        with self._lock:
            if not self.enabled or self.active or self._closed:
                return
            stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
            instance = "".join(c for c in str(self.instance_id or "default") if c.isalnum() or c in "-_") or "default"
            folder = resolve_project_path("match_logs", instance)
            brawler = "".join(c for c in str(header.get("brawler") or "unknown") if c.isalnum())
            path = folder / f"{stamp}_{secrets.token_hex(8)}_{brawler}.jsonl.gz"
            self.active = True
            self.frame_index = 0
            self.non_match_frames = 0
            header = dict(header, version=LOG_VERSION, perf_counter=time.perf_counter(), wall_time=time.time())
            self._queue.put(("open", path))
            self.log("header", **header)
            print(f"Match logging to {path}")

    def stop(self, reason, state=None):
        with self._lock:
            if not self.active:
                return
            self.log("end", reason=reason, state=state, frames=self.frame_index)
            self.active = False
            self._queue.put(("close", None))

    def shutdown(self):
        """Close the current file so it gets a valid gzip trailer, e.g. when Pyla is stopped mid-match."""
        with self._lock:
            if self._thread is None or self._closed:
                return
            self._closed = True
            self.stop("shutdown")
            self._queue.put(("exit", None))
        self._thread.join(timeout=3.0)

    def observe_state(self, state):
        """Close the recording once the game has clearly left the match (result screen, lobby...)."""
        with self._lock:
            if not self.active:
                return
            if state == "match":
                self.non_match_frames = 0
                return
            self.non_match_frames += 1
            if self.non_match_frames >= END_AFTER_NON_MATCH_FRAMES:
                self.stop("state_changed", state)

    # ---- records -------------------------------------------------------------------------------

    def log(self, kind, **fields):
        with self._lock:
            if not self.active:
                return
            fields["k"] = kind
            self._queue.put(("rec", fields))

    def log_touch(self, action, x, y, pointer_id, t_before, t_after):
        with self._lock:
            if self.active:
                self._queue.put(("rec", {"k": "touch", "a": action, "x": round(float(x), 1), "y": round(float(y), 1),
                                         "p": pointer_id, "t0": t_before, "t1": t_after}))

    def log_frame(self, **fields):
        with self._lock:
            if not self.active:
                return
            fields["i"] = self.frame_index
            self.frame_index += 1
            self.log("frame", **fields)

    @staticmethod
    def detections_with_conf(raw):
        """Group Detect.last_raw [(cls, x1, y1, x2, y2, conf)] into {cls: [[x1, y1, x2, y2, conf], ...]}."""
        grouped = {}
        for cls, x1, y1, x2, y2, conf in raw or ():
            grouped.setdefault(cls, []).append(_round_box((x1, y1, x2, y2), conf))
        return grouped

    # ---- writer thread -------------------------------------------------------------------------

    def _writer(self):
        handle = None
        last_flush = time.perf_counter()
        while True:
            try:
                op, payload = self._queue.get(timeout=FLUSH_INTERVAL_S)
            except queue.Empty:
                op = None
            try:
                if op == "open":
                    if handle is not None:
                        handle.close()
                    payload.parent.mkdir(parents=True, exist_ok=True)
                    handle = gzip.open(payload, "wt", encoding="utf-8", compresslevel=6)
                elif op in ("close", "exit"):
                    if handle is not None:
                        handle.close()
                    handle = None
                    if op == "exit":
                        return
                elif op == "rec" and handle is not None:
                    handle.write(json.dumps(payload, separators=(",", ":"), default=_json_default))
                    handle.write("\n")
                now = time.perf_counter()
                # A sync flush keeps everything written so far readable if Pyla crashes mid-match.
                if handle is not None and now - last_flush >= FLUSH_INTERVAL_S:
                    handle.flush()
                    last_flush = now
            except Exception as e:
                # One bad record must not end the recording; only a failed open leaves handle unset.
                print(f"Match logger write failed ({op}): {e}")
