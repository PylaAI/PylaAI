import atexit
import math
import random
from concurrent.futures import ThreadPoolExecutor
import threading
import time

import scrcpy
from adbutils import adb, AdbDevice
from debug_view import DebugViewPublisher
from utils import config_bool, load_toml_as_dict, save_dict_as_toml, invalidate_toml_cache

brawl_stars_width, brawl_stars_height = 1920, 1080

press_coords_dict = load_toml_as_dict("cfg/buttons_config.toml")
KNOWN_BS_PACKAGES = ("com.supercell.brawlstars", "bsd.suitcase.release")


def restart_adb_server() -> None:
    try:
        adb.server_kill()
    except Exception:
        pass
    time.sleep(0.5)
    try:
        adb.server_start()
    except Exception:
        pass
    time.sleep(0.5)


def online_devices():
    out = []
    for d in adb.device_list():
        try:
            state = d.get_state() if hasattr(d, "get_state") else d.state
        except Exception:
            state = "device"
        if state == "device":
            out.append(d)
    return out


def discover_device(verbose: bool = False) -> AdbDevice:
    preferred_port = load_toml_as_dict("cfg/general_config.toml").get("emulator_port")

    def _safe_connect(port: int):
        dev = adb.connect(f"127.0.0.1:{port}")
        return dev

    if preferred_port:
        try:
            port_str = str(preferred_port).strip()
            if port_str.isdigit():
                port_num = int(port_str)
                if verbose:
                    print(f"Attempting connection to configured preferred port: {port_num}")
                try:
                    _safe_connect(port_num)
                except Exception:
                    pass

                devices = online_devices()
                pref = next((d for d in devices if d.serial.endswith(f"{port_str}")), None)
                if pref:
                    if verbose:
                        print(f"Successfully connected to configured preferred port: {pref.serial}")
                    return pref
        except Exception as e:
            if verbose:
                print(f"Warning: Error handling preferred port connection: {e}")

    candidates = [5137, 5555, 16384, 7555, 5635, 62001, 62025, 62026, 7556, 7565, 16416] + list(range(5556, 5566)) + list(range(5565, 5756, 10)) + list(range(16385, 16415))

    def _try(port):
        try:
            _safe_connect(port)
        except Exception:
            pass

    with ThreadPoolExecutor(max_workers=len(candidates)) as executor:
        executor.map(_try, candidates)

    devices = online_devices()
    if verbose:
        print(f"Online devices after scan: {[d.serial for d in devices]}")

    if not devices:
        raise ConnectionError("No ADB devices came online after scan.")

    if len(devices) == 1:
        return devices[0]

    chosen = devices[0]
    print(f"Multiple ADB devices online and no port configured. "
          f"Picking {chosen.serial} (first one). Others: "
          f"{[d.serial for d in devices if d is not chosen]}")
    return chosen

class WindowController:
    def __init__(self, max_fps="auto"):
        self.scale_factor = None
        self.width = None
        self.height = None
        self.width_ratio = None
        self.height_ratio = None
        self.movement_joystick_x, self.movement_joystick_y = None, None
        self.original_movement_joystick = (None, None)
        self.BRAWL_STARS_PACKAGE = load_toml_as_dict("cfg/general_config.toml")["brawl_stars_package"]
        self.verbose_debug = config_bool(
            load_toml_as_dict("cfg/debug_settings.toml").get("verbose_debug"),
            False
        )
        print("Connecting to ADB (might take up to 2 minutes)...")
        try:
            self.device = discover_device(verbose=self.verbose_debug)
            print(f"Connected to device: {self.device.serial}")

            self.frame_lock = threading.Lock()
            self.max_fps = max_fps
            self.scrcpy_client = scrcpy.Client(device=self.device, max_width=0, bitrate=4000000) if self.max_fps == "auto" else scrcpy.Client(device=self.device, max_width=0, bitrate=4000000, max_fps=self.max_fps)
            self.last_frame = None
            self.last_frame_time = 0.0
            self.last_joystick_pos = (None, None)
            self.FRAME_STALE_TIMEOUT = 15.0
            self.re_apply_movement = config_bool(
                load_toml_as_dict("cfg/debug_settings.toml").get("re_apply_movement"),
                True
            )
            self.debug_view = DebugViewPublisher.from_config()

            def on_frame(frame):
                if frame is not None:
                    with self.frame_lock:
                        self.last_frame = frame
                        self.last_frame_time = time.time()

            self.scrcpy_client.add_listener(scrcpy.EVENT_FRAME, on_frame)
            self.scrcpy_client.start(threaded=True)
            atexit.register(self.close)
            print("Scrcpy client started successfully.")

        except Exception:
            raise Exception(f"Error during ADB/scrcpy initialization\nFailed to connect to the emulator/device.\nMake sure you have ADB enabled in your emulator settings. If you don't know how, check https://vimeo.com/1174882529?fl=pl&fe=s.\n if it still doesn't work, check https://discord.com/channels/1205263029269438574/1227618442073342002/1499331741838610433 to try fixing it.")
        self.are_we_moving = False
        self.PID_JOYSTICK = 1
        self.PID_ATTACK = 2

    def get_latest_frame(self):
        with self.frame_lock:
            if self.last_frame is None:
                return None, 0.0
            return self.last_frame, self.last_frame_time

    def force_rediscover(self) -> bool:
        print("Restarting ADB server and re-discovering device.")
        try:
            self.scrcpy_client.stop()
        except Exception:
            pass
        restart_adb_server()
        try:
            new_dev = discover_device(self.verbose_debug)
        except ConnectionError:
            return False
        self.device = new_dev
        print(f"Re-discovered device: {self.device.serial}")
        return True

    def reconnect_scrcpy(self, max_retries=3):
        for attempt in range(1, max_retries + 1):
            print(f"Scrcpy reconnect attempt {attempt}/{max_retries}")
            try:
                self.scrcpy_client.stop()
            except Exception:
                pass
            time.sleep(1)

            with self.frame_lock:
                self.last_frame = None
                self.last_frame_time = 0.0

            self.are_we_moving = False
            self.last_joystick_pos = (None, None)

            try:
                _ = self.device.get_state()
            except Exception:
                if not self.force_rediscover():
                    print("Device gone and re-discovery failed.")
                    time.sleep(2 * attempt)
                    continue

            def on_frame(frame):
                if frame is not None:
                    with self.frame_lock:
                        self.last_frame = frame
                        self.last_frame_time = time.time()

            try:
                self.scrcpy_client = scrcpy.Client(device=self.device, max_width=0, bitrate=4000000) if self.max_fps == "auto" else scrcpy.Client(device=self.device, max_width=0, bitrate=4000000, max_fps=self.max_fps)
                self.scrcpy_client.add_listener(scrcpy.EVENT_FRAME, on_frame)
                self.scrcpy_client.start(threaded=True)
            except Exception as e:
                print(f"Scrcpy client creation failed: {e}")
                time.sleep(2 * attempt)
                continue

            deadline = time.time() + 8
            while time.time() < deadline:
                _, ft = self.get_latest_frame()
                if ft > 0 and (time.time() - ft) < 2:
                    print(f"Scrcpy feed restored on attempt {attempt}")
                    return True
                time.sleep(0.5)

            print(f"Attempt {attempt} did not restore frame feed")
            time.sleep(2 * attempt)

        print("All scrcpy reconnect attempts exhausted")
        return False

    def restart_brawl_stars(self):
        self.device.app_stop(self.BRAWL_STARS_PACKAGE)
        time.sleep(1)
        self.device.app_start(self.BRAWL_STARS_PACKAGE)
        time.sleep(3)
        print("Brawl stars restarted successfully.")

    def is_brawl_stars_running(self):
        try:
            opened_app = self.device.app_current().package.strip()
            detected_known_package = False
            for package in KNOWN_BS_PACKAGES:
                if opened_app == package:
                    detected_known_package = True
                    break
            if detected_known_package:
                if opened_app != self.BRAWL_STARS_PACKAGE:
                    general_config = load_toml_as_dict("cfg/general_config.toml")
                    general_config["brawl_stars_package"] = opened_app
                    save_dict_as_toml(general_config, "cfg/general_config.toml")
                    self.BRAWL_STARS_PACKAGE = opened_app
                    invalidate_toml_cache("cfg/general_config.toml")
                    print(f"Detected Brawl Stars running under the '{opened_app}' package. Updating configuration to match.")
            return opened_app == self.BRAWL_STARS_PACKAGE.strip()
        except Exception as e:
            print(f"Error checking if Brawl Stars is running: {e}")
            return False

    def screenshot(self):
        frame, frame_time = self.get_latest_frame()

        deadline = time.time() + 15
        while frame is None:
            if time.time() > deadline:
                raise ConnectionError(
                    "No frame received from scrcpy within 15s. "
                    "Check USB/emulator connection."
                )
            print("Waiting for first frame...")
            time.sleep(0.1)
            frame, frame_time = self.get_latest_frame()

        age = time.time() - frame_time
        if frame_time > 0 and age > self.FRAME_STALE_TIMEOUT:
            print(f"WARNING: scrcpy frame is {age:.1f}s stale -- feed may be frozen")

        if not self.width or not self.height:
            self.width = frame.shape[1]
            self.height = frame.shape[0]
            if (self.width, self.height) != (brawl_stars_width, brawl_stars_height):
                print(f"WARNING: Unexpected resolution: {self.width}x{self.height}. Expected {brawl_stars_width}x{brawl_stars_height}. Please set your emulator resolution to 1920x1080 for best results.")
            self.width_ratio = self.width / brawl_stars_width
            self.height_ratio = self.height / brawl_stars_height
            movement_joystick = press_coords_dict.get("movement_joystick", [180, 900])
            self.movement_joystick_x, self.movement_joystick_y = movement_joystick[0] * self.width_ratio, movement_joystick[1] * self.height_ratio
            self.original_movement_joystick = (self.movement_joystick_x, self.movement_joystick_y)
            self.scale_factor = min(self.width_ratio, self.height_ratio)
        return frame

    def reset_to_default_resolution(self):
        print("Resetting window controller dimensions to 1920x1080 and updating scale ratios...")
        self.width = brawl_stars_width
        self.height = brawl_stars_height
        self.width_ratio = self.width / brawl_stars_width
        self.height_ratio = self.height / brawl_stars_height
        movement_joystick = press_coords_dict.get("movement_joystick", [180, 900])
        self.movement_joystick_x, self.movement_joystick_y = movement_joystick[0] * self.width_ratio, movement_joystick[1] * self.height_ratio
        self.original_movement_joystick = (self.movement_joystick_x, self.movement_joystick_y)
        self.scale_factor = min(self.width_ratio, self.height_ratio)

    def touch_down(self, x, y, pointer_id=0):
        try:
            self.scrcpy_client.control.touch(int(x), int(y), scrcpy.ACTION_DOWN, pointer_id)
        except Exception as e:
            print(f"Error during touch_down at ({x}, {y}) with pointer_id {pointer_id}: {e}")
            if self.reconnect_scrcpy() :
                try:
                    self.scrcpy_client.control.touch(int(x), int(y), scrcpy.ACTION_DOWN, pointer_id)
                except Exception as e2:
                    print(f"Retry after reconnect failed during touch_down at ({x}, {y}) with pointer_id {pointer_id}: {e2}")

    def touch_move(self, x, y, pointer_id=0):
        try:
            self.scrcpy_client.control.touch(int(x), int(y), scrcpy.ACTION_MOVE, pointer_id)
        except Exception as e:
            print(f"Error during touch_move at ({x}, {y}) with pointer_id {pointer_id}: {e}")
            if self.reconnect_scrcpy():
                try:
                    self.scrcpy_client.control.touch(int(x), int(y), scrcpy.ACTION_MOVE, pointer_id)
                except Exception as e2:
                    print(f"Retry after reconnect failed during touch_move at ({x}, {y}) with pointer_id {pointer_id}: {e2}")

    def touch_up(self, x, y, pointer_id=0):
        try:
            self.scrcpy_client.control.touch(int(x), int(y), scrcpy.ACTION_UP, pointer_id)
        except Exception as e:
            print(f"Error during touch_up at ({x}, {y}) with pointer_id {pointer_id}: {e}")
            if self.reconnect_scrcpy():
                try:
                    self.scrcpy_client.control.touch(int(x), int(y), scrcpy.ACTION_UP, pointer_id)
                except Exception as e2:
                    print(f"Retry after reconnect failed during touch_up at ({x}, {y}) with pointer_id {pointer_id}: {e2}")

    def move(self, x, y):
        if not self.are_we_moving:
            if self.original_movement_joystick[0] is not None:
                self.movement_joystick_x = self.original_movement_joystick[0] + random.randint(-5, 5) * self.width_ratio
                self.movement_joystick_y = self.original_movement_joystick[1] + random.randint(-5, 5) * self.height_ratio
            else:
                self.movement_joystick_x = 180 * self.width_ratio + random.randint(-5, 5) * self.width_ratio
                self.movement_joystick_y = 900 * self.height_ratio + random.randint(-5, 5) * self.height_ratio
        target_x = self.movement_joystick_x + x
        target_y = self.movement_joystick_y + y
        if not self.are_we_moving:
            self.touch_down(self.movement_joystick_x, self.movement_joystick_y, pointer_id=self.PID_JOYSTICK)
            time.sleep(0.05)
            self.touch_move(target_x, target_y, pointer_id=self.PID_JOYSTICK)
            self.are_we_moving = True
            self.last_joystick_pos = (target_x, target_y)
            return

        if not self.re_apply_movement and self.last_joystick_pos == (target_x, target_y):
            return

        self.touch_move(target_x, target_y, pointer_id=self.PID_JOYSTICK)
        self.last_joystick_pos = (target_x, target_y)

    def release_movement(self):
        if self.are_we_moving:
            self.touch_up(self.movement_joystick_x, self.movement_joystick_y, pointer_id=self.PID_JOYSTICK)
            self.are_we_moving = False
            self.last_joystick_pos = (None, None)

    def click(self, x: int, y: int, delay=0.02, already_include_ratio=True, touch_up=True, touch_down=True):
        if not already_include_ratio:
            x = x * self.width_ratio
            y = y * self.height_ratio
        if touch_down: self.touch_down(x, y, pointer_id=self.PID_ATTACK)
        time.sleep(delay)
        if touch_up: self.touch_up(x, y, pointer_id=self.PID_ATTACK)

    def press(self, key, delay=0.02, touch_up=True, touch_down=True):
        if key not in press_coords_dict:
            return
        x, y = press_coords_dict[key]
        target_x = x * self.width_ratio
        target_y = y * self.height_ratio
        self.click(target_x, target_y, delay, touch_up=touch_up, touch_down=touch_down)

    def swipe(self, start_x, start_y, end_x, end_y, duration=0.2):
        dist_x = end_x - start_x
        dist_y = end_y - start_y
        distance = math.sqrt(dist_x ** 2 + dist_y ** 2)

        if distance == 0:
            return

        step_len = 25
        steps = max(int(distance / step_len), 1)
        step_delay = duration / steps

        self.touch_down(int(start_x), int(start_y), pointer_id=self.PID_ATTACK)
        for i in range(1, steps + 1):
            t = i / steps
            cx = start_x + dist_x * t
            cy = start_y + dist_y * t
            time.sleep(step_delay)
            self.touch_move(int(cx), int(cy), pointer_id=self.PID_ATTACK)
        self.touch_up(int(end_x), int(end_y), pointer_id=self.PID_ATTACK)

    def close(self):
        try:
            self.debug_view.close()
        except Exception as exc:
            print(f"Debug view close failed: {exc}")
        self.stop_scrcpy_with_timeout()

    def stop_scrcpy_with_timeout(self, timeout=2.0):
        def stop_client():
            try:
                self.scrcpy_client.stop()
            except Exception as exc:
                print(f"Scrcpy stop failed: {exc}")

        stop_thread = threading.Thread(target=stop_client, daemon=True, name="scrcpy-stop")
        stop_thread.start()
        stop_thread.join(timeout=timeout)
        if stop_thread.is_alive():
            print("Scrcpy stop is still running in the background; continuing shutdown.")
