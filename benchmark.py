"""Performance check: is the bot slow, or the emulator?

Run it with Brawl Stars open on the emulator (the lobby is fine) and the bot stopped. It measures:
- capture: how many frames per second actually reach Pyla, and the longest gaps between them;
- emulator delay: from an action sent to the emulator until Pyla sees its result on screen (input + rendering +
  capture together, what every bot reaction waits for). The action is opening and closing Android's notification
  shade: clearly visible, harmless, and no game input;
- bot processing: the entity and wall models on this PC, run as in a match (entities every frame, walls at the
  wall detection interval);
- optionally, frame age: how old a frame is when Pyla receives it, one way. The emulator delay above contains it,
  but only a picture that carries the time it was drawn can tell it apart: a tiny test app (pyla-frame-age.apk) shows
  its draw time as a block code and answers clock queries; it is installed for the test and removed afterwards;
- optionally, touch input latency: from Pyla sending a touch (through its own touch path: MuMu's touch or scrcpy) to
  Android delivering it to an app, one way, with a second test app (pyla-input-latency.apk) that timestamps each
  touch and answers clock queries; installed for the test and removed afterwards;
- optionally, ping: TCP handshakes with the Brawl Stars game server (no data is sent), the network part of every
  action's delay in a match;
- the game's frame rate, as frames whose picture changed (a moving match screen; a still lobby shows fewer): the
  game reads touches once per rendered frame.
Nothing in the game is touched. Use it from the web UI (Test emulator delay, with the bot stopped) or
`PylaAI --benchmark [--frame-age] [--input-latency] [--ping]`.
"""
import binascii
import os
import socket
import statistics
import struct
import threading
import time

import cv2
import numpy as np
import scrcpy
from scrcpy.core import push_file

from detect import Detect
from utils import load_toml_as_dict
from window_controller import WindowController

# The models main.py loads for Play.
ENTITY_MODEL = "./models/mainInGameModel.onnx"
WALL_MODEL = "./models/tileDetector.onnx"
SETTING_FILES = {"time_thresholds": "cfg/time_tresholds.toml"}


def load_setting(name, key):
    """A value of cfg/<name>.toml, as Play reads it."""
    return load_toml_as_dict(SETTING_FILES.get(name, f"cfg/{name}.toml"))[key]

CAPTURE_SECONDS = 5.0
ROUND_TRIPS = 8
PROCESSING_SECONDS = 4.0
SAMPLED_FRAMES = 30
# Emulator delay: the notification shade is detected in the top band of the screen, on a small grey copy.
CHANGE_BAND = 0.35
CHANGE_SIZE = (96, 32)
MIN_CHANGE = 6.0                 # mean grey-level difference that counts as "the shade appeared"
ROUND_TRIP_TIMEOUT = 2.0
# Frame age test app: shipped beside the scrcpy server jars, which Pyla pushes to the device the same way.
FRAME_AGE_APK = os.path.join(os.path.dirname(os.path.abspath(scrcpy.__file__)), "pyla-frame-age.apk")
FRAME_AGE_PACKAGE = "dev.pyla.frameage"
FRAME_AGE_SOCKET = "pyla_frame_age_v1"
FRAME_AGE_SECONDS = 5.0
# Touch input latency test app: shipped beside the frame age app.
INPUT_LATENCY_APK = os.path.join(os.path.dirname(os.path.abspath(scrcpy.__file__)), "pyla-input-latency.apk")
INPUT_LATENCY_PACKAGE = "dev.pyla.inputlatency"
INPUT_LATENCY_SOCKET = "pyla_input_latency_v1"
INPUT_LATENCY_TRIALS = 20
# Ping: the Brawl Stars game server's address (the client connects there; a battle's traffic may be routed further).
GAME_SERVER = ("game.brawlstarsgame.com", 9339)
PING_SAMPLES = 12
# A captured frame "changed" when its small grey copy differs from the previous one by more than this (0-255).
CHANGED_FRAME_THRESHOLD = 1.0
# Ratings: (good up to, fair up to); worse is slow. Frame rates are rated the other way round.
EMULATOR_DELAY_MS = (110, 180)
FRAME_AGE_MS = (50, 100)
CAPTURE_FPS = (50, 30)
BOT_FRAME_MS = (25, 45)


def _percentile(values, fraction):
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int(fraction * len(ordered)))]


def _stats_ms(seconds):
    ms = [v * 1000 for v in seconds]
    return {"median": round(statistics.median(ms), 1), "p90": round(_percentile(ms, .9), 1), "max": round(max(ms), 1)}


def _next_frame(wc, last_received_at, timeout=0.5):
    """(frame, received_at, pts_us) of the next frame after last_received_at, or None on timeout."""
    if not wc.wait_for_new_frame(last_received_at, timeout=timeout):
        return None
    frame, received_at, pts_us = wc.screenshot_with_timing()
    return None if received_at == last_received_at else (frame, received_at, pts_us)


def measure_capture(wc, seconds=CAPTURE_SECONDS):
    """Frame rate and gaps of the live capture; also returns a sample of frames for measure_processing."""
    times, pts, samples = [], [], []
    changed, previous_small = [], None
    last = None
    deadline = time.perf_counter() + seconds
    while time.perf_counter() < deadline:
        got = _next_frame(wc, last)
        if got is None:
            continue
        frame, last, pts_us = got
        times.append(last)
        pts.append(pts_us)
        small = cv2.resize(cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY), (64, 36), interpolation=cv2.INTER_AREA)
        if previous_small is None or float(np.abs(small.astype(np.int16) - previous_small).mean()) > CHANGED_FRAME_THRESHOLD:
            changed.append(last)
        previous_small = small.astype(np.int16)
        if len(times) % 5 == 0 and len(samples) < SAMPLED_FRAMES:
            samples.append(frame.copy())
    if len(times) < 2:
        return samples, {"ok": False, "reason": "Fewer than two frames arrived in 5 seconds."}
    gaps = [b - a for a, b in zip(times, times[1:])]
    result = {"ok": True, "fps": round((len(times) - 1) / (times[-1] - times[0]), 1), "gap_ms": _stats_ms(gaps)}
    if len(changed) >= 2:
        # The game's frame rate when the picture moves every frame (a match); capped by the capture's own rate.
        result["changed_fps"] = round((len(changed) - 1) / (changed[-1] - changed[0]), 1)
    if all(p is not None for p in pts):
        # scrcpy stamps each frame when Android encoded it: how much later than usual a frame arrives shows the
        # emulator's delay spikes (the usual delay itself is in the emulator delay below).
        offsets = [t - p / 1e6 for t, p in zip(times, pts)]
        result["late_ms"] = _stats_ms([o - min(offsets) for o in offsets])
    return samples, result


def _top_band(frame):
    h = frame.shape[0]
    grey = cv2.cvtColor(frame[:int(h * CHANGE_BAND)], cv2.COLOR_RGB2GRAY)
    return cv2.resize(grey, CHANGE_SIZE, interpolation=cv2.INTER_AREA).astype(np.float32)


def _wait_for(wc, reference, changed, threshold, last, timeout):
    """received_at of the first frame whose top band differs from reference (changed=True) or is back to it
    (changed=False), and the last frame time seen."""
    deadline = time.perf_counter() + timeout
    while time.perf_counter() < deadline:
        got = _next_frame(wc, last, timeout=0.1)
        if got is None:
            continue
        frame, last, _ = got
        difference = float(np.abs(_top_band(frame) - reference).mean())
        if (difference > threshold) == changed:
            return last, last
    return None, last


def measure_emulator_delay(wc, trials=ROUND_TRIPS):
    """Action -> visible delay, with the notification shade (scrcpy control: expand, then collapse). With MuMu touch
    no scrcpy control connection runs, so a temporary one opens the shade (sending through it takes ~1 ms of the
    ~100 ms measured)."""
    control = wc.scrcpy_client.control
    temporary = None
    if not hasattr(control, "expand_notification_panel"):
        temporary = scrcpy.Client(device=wc.device, video=False)
        temporary.start()
        control = temporary.control
    delays = []
    last = None
    try:
        for trial in range(trials):
            # Let the screen settle, then measure how much it changes on its own (lobby animations).
            time.sleep(0.5)
            bands = []
            settle_end = time.perf_counter() + 0.4
            while time.perf_counter() < settle_end:
                got = _next_frame(wc, last, timeout=0.1)
                if got is not None:
                    last = got[1]
                    bands.append(_top_band(got[0]))
            if not bands:
                return {"ok": False, "reason": "No frames arrived while measuring."}
            reference = bands[-1]
            noise = max((float(np.abs(b - reference).mean()) for b in bands), default=0.0)
            threshold = max(MIN_CHANGE, 3 * noise + 2)

            sent_at = time.perf_counter()
            control.expand_notification_panel()
            seen_at, last = _wait_for(wc, reference, True, threshold, last, ROUND_TRIP_TIMEOUT)
            control.collapse_panels()
            if seen_at is not None:
                delays.append(seen_at - sent_at)
            elif trial >= 2 and not delays:
                return {"ok": False, "reason": "The notification shade never appeared: this emulator does not "
                                               "support it, so the delay cannot be measured this way."}
            _, last = _wait_for(wc, reference, False, threshold, last, ROUND_TRIP_TIMEOUT)
    finally:
        try:
            control.collapse_panels()
        finally:
            if temporary is not None:
                temporary.stop()
    if not delays:
        return {"ok": False, "reason": "No measurement succeeded."}
    return {"ok": True, "trials": len(delays), "delay_ms": _stats_ms(delays)}


class DrawTimeCode:
    """Reads the test app's block code: 16 x 8 black/white cells in the middle of the screen, 128 bits = magic
    "PA" 1, 24-bit sequence, 64-bit draw time (device clock, microseconds), CRC16. None for a frame without a clean
    code (mid-transition, blurred by the video encoder)."""

    def __init__(self):
        self.shape = None

    def read(self, frame):
        h, w = frame.shape[:2]
        if min(h, w) < 64:
            return None
        if self.shape != (h, w):
            cols, rows = np.tile(np.arange(16), 8), np.repeat(np.arange(8), 16)
            self.x = ((.10 + (cols + .5) * .80 / 16) * w).astype(int)
            self.y = ((.25 + (rows + .5) * .60 / 8) * h).astype(int)
            self.shape = (h, w)
        # The middle of every cell and its 4 neighbours, away from compression and scaling edges.
        samples = np.stack([frame[self.y + dy, self.x + dx, :3] for dy, dx in
                            ((0, 0), (-1, 0), (1, 0), (0, -1), (0, 1))]).mean(axis=(0, 2))
        if np.any((samples > 80) & (samples < 175)):
            return None
        data = np.packbits(samples >= 128).tobytes()
        if data[:3] != b"PA\x01" or binascii.crc_hqx(data[:14], 0xffff) != int.from_bytes(data[14:], "big"):
            return None
        return int.from_bytes(data[3:6], "big"), int.from_bytes(data[6:14], "big")


def _read_exact(sock, length):
    data = bytearray()
    while len(data) < length:
        chunk = sock.recv(length - len(data))
        if not chunk:
            raise ConnectionError("The frame age app closed its clock socket.")
        data.extend(chunk)
    return bytes(data)


def _clock_offset(sock, exchanges=30):
    """Host perf_counter_ns minus the app's clock, from the exchange with the shortest round trip:
    (host time of the exchange, offset, uncertainty), ns. The app answers b"T" with its receive and send times."""
    best = None
    for _ in range(exchanges):
        sent = time.perf_counter_ns()
        sock.sendall(b"T")
        received_at_device, sent_at_device = struct.unpack(">QQ", _read_exact(sock, 16))
        received = time.perf_counter_ns()
        lower, upper = sent - received_at_device, received - sent_at_device   # offset bounds, transport delay >= 0
        if upper >= lower and (best is None or upper - lower < 2 * best[2]):
            best = ((sent + received) // 2, (lower + upper) / 2, (upper - lower) / 2)
        time.sleep(.002)
    if best is None:
        raise ConnectionError("The frame age app's clock answers are inconsistent.")
    return best


def _install_frame_age_app(device):
    """Install the test app unless it is there; True when this call installed it (and must remove it)."""
    return _install_test_app(device, FRAME_AGE_PACKAGE, FRAME_AGE_APK, "frame age")


def _install_test_app(device, package, apk, what):
    """Install a test app unless it is there; True when this call installed it (and must remove it)."""
    if package in device.shell(["pm", "list", "packages", package]):
        return False
    if not os.path.exists(apk):
        raise FileNotFoundError(f"The {what} test app is missing: {apk}")
    remote = f"/data/local/tmp/{os.path.basename(apk)}"
    push_file(device, apk, remote)
    try:
        output = device.shell(["pm", "install", "-r", "-t", remote], timeout=60)
    finally:
        device.shell(["rm", "-f", remote])
    if "Success" not in output:
        raise RuntimeError(f"The emulator refused to install the {what} test app: {output.strip()}")
    return True


def _connect_app_socket(device, name, what, timeout=15):
    from adbutils import Network
    deadline = time.monotonic() + timeout
    while True:
        try:
            sock = device.create_connection(Network.LOCAL_ABSTRACT, name)
            break
        except Exception:
            if time.monotonic() > deadline:
                raise ConnectionError(f"The {what} test app did not start.")
            time.sleep(.2)
    sock.settimeout(3)
    sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
    return sock


def measure_input_latency(wc, trials=INPUT_LATENCY_TRIALS):
    """One-way touch input latency through Pyla's own touch path (MuMu touch or scrcpy): from the touch call to
    Android delivering it to the test app's view (touch down, move, up). The game then reads it at its next rendered
    frame. The app is installed for the test if needed and removed again; the app that was in front comes back."""
    import random
    device = wc.device
    previous_app = device.app_current().package
    installed = _install_test_app(device, INPUT_LATENCY_PACKAGE, INPUT_LATENCY_APK, "input latency")
    sock, rows = None, []
    try:
        device.shell(["am", "start", "-n", f"{INPUT_LATENCY_PACKAGE}/.MainActivity"])
        sock = _connect_app_socket(device, INPUT_LATENCY_SOCKET, "input latency")
        time.sleep(1.0)                  # the launch animation
        before = _clock_offset(sock)
        x, y = wc.width // 2, wc.height // 2
        pid = wc.PID_ATTACK
        for trial in range(trials + 2):  # the first two are warm-up
            sock.sendall(b"A")           # arm: the app reports the touches that follow
            _read_exact(sock, 4)
            for action, dx in ((0, 0), (2, 2), (1, 2)):
                sent = time.perf_counter_ns()
                if action == 0:
                    wc.touch_down(x, y, pointer_id=pid)
                elif action == 2:
                    wc.touch_move(x + dx, y, pointer_id=pid)
                else:
                    wc.touch_up(x + dx, y, pointer_id=pid)
                sock.sendall(b"E")
                if _read_exact(sock, 1) != b"\x01":
                    raise TimeoutError("The input latency test app did not receive the touch.")
                stamp, got, pointers, _, _ = struct.unpack(">QIIff", _read_exact(sock, 24))
                if trial >= 2 and got == action and pointers == 1:
                    rows.append((action, sent, stamp))
                time.sleep(.01)
            time.sleep(random.uniform(.08, .16))
        after = _clock_offset(sock)
    finally:
        if sock is not None:
            sock.close()
        device.shell(["am", "force-stop", INPUT_LATENCY_PACKAGE])
        if installed:
            device.shell(["pm", "uninstall", INPUT_LATENCY_PACKAGE])
        if previous_app and device.app_current().package != previous_app:
            device.app_start(previous_app)
    if len(rows) < trials:
        return {"ok": False, "installed": installed, "reason": "The test app reported too few touches."}
    (t0, offset0, error0), (t1, offset1, error1) = before, after
    latency = {0: [], 2: [], 1: []}
    for action, sent, stamp in rows:
        fraction = min(max((sent - t0) / max(t1 - t0, 1), 0.0), 1.0)
        offset = offset0 + fraction * (offset1 - offset0)          # host = device + offset
        latency[action].append((stamp + offset - sent) / 1e9)
    every = latency[0] + latency[2] + latency[1]
    return {"ok": True, "installed": installed, "touch": getattr(wc.scrcpy_client, "touch_backend", "scrcpy"),
            "touches": len(every), "input_ms": _stats_ms(every),
            "by_action_ms": {"down": _stats_ms(latency[0]), "move": _stats_ms(latency[2]), "up": _stats_ms(latency[1])},
            "uncertainty_ms": round(max(error0, error1) / 1e6, 2)}


def measure_ping(server=GAME_SERVER, samples=PING_SAMPLES, timeout=2.0):
    """Round trips to the game server: TCP handshakes, closed at once (no data is sent)."""
    host, port = server
    try:
        address = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)[0][4]
    except OSError as exc:
        return {"ok": False, "reason": f"The game server's name did not resolve ({exc})."}
    rtts, failures = [], 0
    for _ in range(samples):
        sock = socket.socket(socket.AF_INET6 if len(address) == 4 else socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(timeout)
        started = time.perf_counter()
        try:
            sock.connect(address)
            rtts.append(time.perf_counter() - started)
        except OSError:
            failures += 1
        finally:
            sock.close()
        time.sleep(.1)
    if not rtts:
        return {"ok": False, "reason": "The game server did not answer (blocked network or port)."}
    return {"ok": True, "server": f"{host}:{port}", "rtt_ms": _stats_ms(rtts), "failures": failures}


def measure_frame_age(wc, seconds=FRAME_AGE_SECONDS):
    """One-way frame age through Pyla's own capture (scrcpy or MSC): the time from the app drawing a frame to Pyla
    receiving it. The app is installed for the test if needed and removed again; the app that was in front comes back."""
    from adbutils import Network
    device = wc.device
    previous_app = device.app_current().package
    installed = _install_frame_age_app(device)
    sock = None
    try:
        device.shell(["am", "start", "-n", f"{FRAME_AGE_PACKAGE}/.MainActivity"])
        deadline = time.monotonic() + 15
        while sock is None:
            try:
                sock = device.create_connection(Network.LOCAL_ABSTRACT, FRAME_AGE_SOCKET)
            except Exception:
                if time.monotonic() > deadline:
                    raise ConnectionError("The frame age app did not start.")
                time.sleep(.2)
        sock.settimeout(3)
        sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        time.sleep(1.0)                 # let the app's first frames and the launch animation pass
        before = _clock_offset(sock)
        code, first_seen, last = DrawTimeCode(), {}, None
        end = time.perf_counter() + seconds
        while time.perf_counter() < end:
            got = _next_frame(wc, last)
            if got is None:
                continue
            frame, last, _ = got
            stamp = code.read(frame)
            if stamp is not None and stamp not in first_seen:
                first_seen[stamp] = last          # a frame captured twice is aged from its first arrival
        after = _clock_offset(sock)
    finally:
        if sock is not None:
            sock.close()
        device.shell(["am", "force-stop", FRAME_AGE_PACKAGE])
        if installed:
            device.shell(["pm", "uninstall", FRAME_AGE_PACKAGE])
        if previous_app and device.app_current().package != previous_app:
            device.app_start(previous_app)
    if len(first_seen) < 10:
        return {"ok": False, "installed": installed,
                "reason": "The test app's code was not readable in the captured frames."}
    # The two clocks drift apart slowly: interpolate the offset between the checks before and after.
    (t0, offset0, error0), (t1, offset1, error1) = before, after
    ages = []
    for (_, draw_us), received_at in first_seen.items():
        received_ns = received_at * 1e9
        fraction = min(max((received_ns - t0) / max(t1 - t0, 1), 0.0), 1.0)
        offset = offset0 + fraction * (offset1 - offset0)
        ages.append((received_ns - (draw_us * 1000 + offset)) / 1e9)
    return {"ok": True, "installed": installed, "frames": len(ages), "age_ms": _stats_ms(ages),
            "uncertainty_ms": round(max(error0, error1) / 1e6, 2)}


def measure_processing(frames, scale_factor=1.0, seconds=PROCESSING_SECONDS):
    """Per-frame bot work on this PC, as Play does it: the entity model on every frame and the wall model whenever
    the wall detection interval has passed (in the frame loop, so a wall update lengthens that frame)."""
    if not frames:
        return {"ok": False, "reason": "No frames to process."}
    detector = Detect(ENTITY_MODEL, classes=['enemy', 'teammate', 'player'])
    walls = Detect(WALL_MODEL, classes=load_setting("bot_config", "wall_model_classes"))
    walls.tile_size = load_toml_as_dict("cfg/bot_config.toml").get("perceived_tile_size", 54) * (scale_factor or 1)
    entity_confidence = load_setting("bot_config", "entity_detection_confidence")
    wall_confidence = load_setting("bot_config", "wall_detection_confidence")
    wall_interval = float(load_setting("time_thresholds", "wall_detection"))
    detector.detect_objects(frames[0], conf_tresh=entity_confidence)      # first runs include GPU warm-up
    walls.detect_objects(frames[0], conf_tresh=wall_confidence)
    wall_times = []
    for frame in frames[:8]:
        started = time.perf_counter()
        walls.detect_objects(frame, conf_tresh=wall_confidence)
        wall_times.append(time.perf_counter() - started)

    frame_times, detection_times = [], []
    last_walls = 0.0
    end = time.perf_counter() + seconds
    i = 0
    while time.perf_counter() < end:
        frame = frames[i % len(frames)]
        i += 1
        started = time.perf_counter()
        detector.detect_objects(frame, conf_tresh=entity_confidence)
        detected = time.perf_counter()
        if detected - last_walls >= wall_interval:
            walls.detect_objects(frame, conf_tresh=wall_confidence)
            last_walls = detected
        finished = time.perf_counter()
        detection_times.append(detected - started)
        frame_times.append(finished - started)
    detection, wall_update = _stats_ms(detection_times), _stats_ms(wall_times)
    frame_ms = statistics.mean(frame_times) * 1000        # walls included, at their interval
    return {"ok": True, "device": _device_name(detector.device), "wall_device": _device_name(walls.device),
            "detection_ms": detection, "wall_update_ms": wall_update,
            "frame_ms": round(frame_ms, 1), "max_fps": round(1000 / frame_ms, 1) if frame_ms > 0 else None}


def _device_name(provider):
    return {"DmlExecutionProvider": "GPU (DirectML)", "CUDAExecutionProvider": "GPU (CUDA)"}.get(provider, "CPU")


def _rate(value, limits, higher_is_better=False):
    good, fair = limits
    if higher_is_better:
        return "good" if value >= good else "fair" if value >= fair else "slow"
    return "good" if value <= good else "fair" if value <= fair else "slow"


def verdict(result):
    """Ratings of each part, which one limits the bot, and what to try."""
    ratings, tips = {}, []
    capture, delay, processing = result.get("capture", {}), result.get("emulator_delay", {}), result.get("processing", {})
    frame_age = result.get("frame_age") or {}
    if delay.get("ok"):
        ratings["emulator_delay"] = _rate(delay["delay_ms"]["median"], EMULATOR_DELAY_MS)
    if frame_age.get("ok"):
        ratings["frame_age"] = _rate(frame_age["age_ms"]["median"], FRAME_AGE_MS)
    if capture.get("ok"):
        ratings["capture"] = _rate(capture["fps"], CAPTURE_FPS, higher_is_better=True)
    if processing.get("ok"):
        ratings["bot_processing"] = _rate(processing["frame_ms"], BOT_FRAME_MS)

    if ratings.get("emulator_delay") in ("fair", "slow") or ratings.get("capture") == "slow":
        tips.append("In the emulator settings: high frame rate (at least 60 FPS), DirectX or Vulkan renderer (try "
                    "both), at least 4 CPU cores and 4 GB of RAM. Close other heavy programs.")
    if ratings.get("capture") in ("fair", "slow"):
        tips.append("Keep Brawl Stars open and moving while you test: a still screen sends fewer frames.")
    if ratings.get("bot_processing") in ("fair", "slow"):
        if processing.get("device") == "CPU":
            tips.append("The models run on the CPU. Set CPU or GPU to Auto in Debug settings so a GPU is used when "
                        "there is one (DirectML works on most graphics cards).")
        else:
            tips.append("Close the debug view and other programs that use the GPU while Pyla runs.")

    order = {"good": 0, "fair": 1, "slow": 2}
    worst = max(ratings.items(), key=lambda kv: order[kv[1]], default=(None, "good"))
    if worst[1] == "good":
        summary = "Everything looks fine: neither the emulator nor this PC should hold the bot back."
    elif worst[0] == "bot_processing":
        summary = "This PC is the bottleneck: the bot needs more time per frame than the emulator does."
    else:
        summary = "The emulator is the bottleneck: the bot waits on it more than on its own processing."
    split, notes = None, []
    if delay.get("ok") and frame_age.get("ok"):
        # The emulator delay is input + drawing + frame age; frame age was measured on its own, on the test app.
        age, total = frame_age["age_ms"]["median"], delay["delay_ms"]["median"]
        if age <= total:
            split = {"frame_age_ms": age, "input_and_drawing_ms": round(total - age, 1)}
        else:
            # Seen on scrcpy at 1080p: the app changes most of the screen every frame, which the emulator's video
            # encoder falls behind on, while the emulator delay is measured on a calmer screen.
            notes.append("Frame age came out higher than the emulator delay: the test app changes most of the screen "
                         "every frame and the emulator's video encoder falls behind on it, while the delay test runs "
                         "on a calmer screen. Busy fights load the encoder the same way.")
    return {"ratings": ratings, "summary": summary, "tips": tips, "delay_split": split, "notes": notes}



def run_benchmark(report=print, frame_age=False, input_latency=False, ping=False):
    """Run every measurement on the emulator and return the results with a verdict. The web UI only starts it while
    the bot is stopped. frame_age / input_latency: also measure the one-way frame age / touch input latency with their
    test apps (installed for the test when missing, then removed). ping: round trips to the game server."""
    report("Connecting to the emulator...")
    wc = WindowController()
    try:
        wc.screenshot()
        client = wc.scrcpy_client
        result = {"backend": getattr(client, "backend_name", "scrcpy"), "touch": "scrcpy",
                  "device": wc.device.serial, "resolution": [wc.width, wc.height]}
        scale_factor = wc.scale_factor
        report(f"Measuring the capture for {CAPTURE_SECONDS:g} seconds...")
        frames, result["capture"] = measure_capture(wc)
        report("Measuring the emulator delay (the notification shade opens and closes a few times)...")
        result["emulator_delay"] = measure_emulator_delay(wc)
        if frame_age:
            report("Measuring the frame age (a small test app opens for a few seconds, then is removed)...")
            try:
                result["frame_age"] = measure_frame_age(wc)
            except Exception as exc:
                result["frame_age"] = {"ok": False, "reason": str(exc)}
        if input_latency:
            report("Measuring the touch input latency (a small test app opens for a few seconds, then is removed)...")
            try:
                result["input_latency"] = measure_input_latency(wc)
            except Exception as exc:
                result["input_latency"] = {"ok": False, "reason": str(exc)}
    finally:
        wc.close()
    if ping:
        report("Measuring the ping to the game server...")
        result["ping"] = measure_ping()
    report("Measuring the bot's processing on this PC...")
    result["processing"] = measure_processing(frames, scale_factor)
    result["verdict"] = verdict(result)
    report("Done.")
    return result


class BenchmarkJob:
    """run_benchmark on a background thread, for the web UI: progress messages, then the result or the error.
    The thread is named like a bot run so its output lands in the log."""

    def __init__(self, frame_age=False, input_latency=False, ping=False):
        self.frame_age = frame_age
        self.input_latency, self.ping = input_latency, ping
        self.progress = []
        self.result = None
        self.report = None
        self.error = None
        self._thread = threading.Thread(target=self._run, daemon=True, name="pyla-runtime-benchmark")
        self._thread.start()

    def _run(self):
        def report(message):
            print(message)
            self.progress.append(message)
        try:
            self.result = run_benchmark(report=report, frame_age=self.frame_age,
                                        input_latency=self.input_latency, ping=self.ping)
            self.report = format_report(self.result)
            print(self.report)
        except Exception as exc:
            self.error = str(exc)
            print(f"Emulator test failed: {exc}")

    @property
    def running(self):
        return self._thread.is_alive()

    def status(self):
        return {"running": self.running, "progress": list(self.progress), "result": self.result,
                "report": self.report, "error": self.error}


def format_report(result):
    """Plain-text version of run_benchmark's result (console)."""
    lines = [f"Pyla performance check ({result['backend']} capture, {result.get('touch', 'scrcpy')} touch, "
             f"{result['resolution'][0]}x{result['resolution'][1]}, {result['device']})"]
    ratings = result["verdict"]["ratings"]
    capture = result["capture"]
    if capture.get("ok"):
        late = f", frames late by up to {capture['late_ms']['p90']:.0f} ms (p90)" if "late_ms" in capture else ""
        lines.append(f"  Capture:         {capture['fps']:.0f} fps, longest gap {capture['gap_ms']['max']:.0f} ms{late}  [{ratings.get('capture')}]")
        if "changed_fps" in capture:
            lines.append(f"  Game frames:     {capture['changed_fps']:.0f} changed frames per second (the game's frame rate "
                         f"when the screen moves every frame)")
    else:
        lines.append(f"  Capture:         not measured ({capture.get('reason')})")
    delay = result["emulator_delay"]
    if delay.get("ok"):
        lines.append(f"  Emulator delay:  {delay['delay_ms']['median']:.0f} ms median, {delay['delay_ms']['p90']:.0f} ms p90  [{ratings.get('emulator_delay')}]")
    else:
        lines.append(f"  Emulator delay:  not measured ({delay.get('reason')})")
    frame_age = result.get("frame_age")
    if frame_age is not None:
        if frame_age.get("ok"):
            split = result["verdict"].get("delay_split")
            share = (f"; of the emulator delay, ~{split['frame_age_ms']:.0f} ms is frame age and "
                     f"~{split['input_and_drawing_ms']:.0f} ms input and drawing") if split else ""
            lines.append(f"  Frame age:       {frame_age['age_ms']['median']:.0f} ms median, {frame_age['age_ms']['p90']:.0f} ms p90 "
                         f"(+/-{frame_age['uncertainty_ms']:.1f} ms){share}  [{ratings.get('frame_age')}]")
        else:
            lines.append(f"  Frame age:       not measured ({frame_age.get('reason')})")
    latency = result.get("input_latency")
    if latency is not None:
        if latency.get("ok"):
            lines.append(f"  Touch input:     {latency['input_ms']['median']:.1f} ms median, {latency['input_ms']['p90']:.1f} ms p90 "
                         f"({latency['touch']} touch, {latency['touches']} touches, +/-{latency['uncertainty_ms']:.1f} ms)")
        else:
            lines.append(f"  Touch input:     not measured ({latency.get('reason')})")
    ping = result.get("ping")
    if ping is not None:
        if ping.get("ok"):
            lines.append(f"  Ping:            {ping['rtt_ms']['median']:.0f} ms median, {ping['rtt_ms']['p90']:.0f} ms p90 "
                         f"to {ping['server']}")
        else:
            lines.append(f"  Ping:            not measured ({ping.get('reason')})")
    processing = result["processing"]
    if processing.get("ok"):
        lines.append(f"  Bot processing:  {processing['frame_ms']:.0f} ms per frame on {processing['device']} "
                     f"(detection {processing['detection_ms']['median']:.0f} ms; up to {processing['max_fps']:.0f} fps), "
                     f"wall update {processing['wall_update_ms']['median']:.0f} ms  [{ratings.get('bot_processing')}]")
    lines.append("")
    lines.append(result["verdict"]["summary"])
    lines.extend(f"  Note: {note}" for note in result["verdict"]["notes"])
    lines.extend(f"  - {tip}" for tip in result["verdict"]["tips"])
    return "\n".join(lines)
