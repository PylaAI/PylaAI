import os
import time

import cv2
from utils import (
    count_hsv_pixels,
    load_toml_as_dict, config_bool, load_brawlers_info,
    normalize_brawler_filename, sleep_ui, ui_delay,
)


class LobbyAutomation:

    def __init__(self, window_controller):
        self.gray_pixels_treshold = load_toml_as_dict("./cfg/bot_config.toml").get('idle_pixels_minimum', 500)
        self.idle_reconnect_coords = load_toml_as_dict("cfg/buttons_config.toml")["idle_reconnect"]
        if self.idle_reconnect_coords and isinstance(self.idle_reconnect_coords[0], (int, float)):
            self.idle_reconnect_coords = [self.idle_reconnect_coords]
        self.window_controller = window_controller
        self.verbose_debug = config_bool(load_toml_as_dict("cfg/debug_settings.toml").get('verbose_debug'), False)
        self.idle_disconnect_hsv_high_bounds = load_toml_as_dict("cfg/lobby_config.toml").get("hsv_bounds", {}).get("idle_reconnect_high_bounds", [[10, 22, 42], [10, 22, 90], [118, 66, 46]])

    def check_for_idle(self, frame):
        wr = self.window_controller.width_ratio
        hr = self.window_controller.height_ratio
        x_start, x_end = int(460 * wr), int(1460 * wr)
        y_start, y_end = int(400 * hr), int(675 * hr)
        if self.verbose_debug:
            print(f"gray pixels (if > {self.gray_pixels_treshold} then bot will try to unidle)")
        for idle_disconnect_hsv_high_bound in self.idle_disconnect_hsv_high_bounds:
            gray_pixels = count_hsv_pixels(frame[y_start:y_end, x_start:x_end], (0, 0, 0), tuple(idle_disconnect_hsv_high_bound), self.window_controller)
            if self.verbose_debug:
                try:
                    cv2.imwrite(f"./debug_frames/idle_detection_{gray_pixels}_{len(os.listdir('./debug_frames'))}.png", cv2.cvtColor(frame[y_start:y_end, x_start:x_end], cv2.COLOR_BGR2RGB))
                except Exception:
                    pass
            if gray_pixels > self.gray_pixels_treshold:
                print("Idle detected, clicking to unidle")
                for idle_reconnect_coord in self.idle_reconnect_coords:
                    self.window_controller.click(idle_reconnect_coord[0], idle_reconnect_coord[1], already_include_ratio=False)


    @staticmethod
    def _should_interrupt(runtime_control=None, stop_event=None):
        if runtime_control and (runtime_control.should_stop() or runtime_control.should_pause()):
            return True
        return stop_event is not None and stop_event.is_set()

    @staticmethod
    def _sleep_interruptible(duration, runtime_control=None, stop_event=None, poll_interval=0.1):
        end_time = time.time() + ui_delay(duration)
        while time.time() < end_time:
            if LobbyAutomation._should_interrupt(runtime_control, stop_event):
                return True
            time.sleep(min(poll_interval, max(end_time - time.time(), 0)))
        return False

    def select_brawler(self, brawler, get_latest_state, stop_event=None, runtime_control=None):
        self.window_controller.screenshot()
        wr = self.window_controller.width_ratio
        hr = self.window_controller.height_ratio
        brawler = str(brawler).lower().strip()
        normalized_brawler = normalize_brawler_filename(brawler)
        brawler_info = load_brawlers_info().get(normalized_brawler, {})
        brawler_search_name = brawler_info.get("actual_name") or normalized_brawler

        x, y = load_toml_as_dict("cfg/buttons_config.toml")["brawlers_menu"]
        self.window_controller.click(x, y, already_include_ratio=False)
        sleep_ui(1.25)
        print("Automatic brawler selection started for", brawler_search_name)
        for i in range(100):
            if self._should_interrupt(runtime_control, stop_event):
                print("Brawler selection aborted by user.")
                return "aborted"
            self.window_controller.screenshot()
            current_state = get_latest_state()
            if current_state == "shop":
                print("Brawler menu is still opening")
                sleep_ui(1)
                continue

            if current_state != "brawler_selection":
                print("Latest screenshot is no longer of the lobby, aborting brawler selection...")
                return "stuck"

            self.window_controller.press("brawler_search")
            if self._sleep_interruptible(1, runtime_control, stop_event):
                print("Brawler selection aborted by user.")
                return "aborted"

            if not self.window_controller.type_text(brawler_search_name):
                print(f"Could not enter brawler name '{brawler_search_name}' in the search field.")
                return "error"
            if self._sleep_interruptible(0.5, runtime_control, stop_event):
                print("Brawler selection aborted by user.")
                return "aborted"

            first_brawler_x, first_brawler_y = load_toml_as_dict("cfg/buttons_config.toml")["first_brawler_icon"]
            self.window_controller.click(first_brawler_x, first_brawler_y, already_include_ratio=False)
            if self._sleep_interruptible(1, runtime_control, stop_event):
                print("Brawler selection aborted by user.")
                return "aborted"

            select_x, select_y = load_toml_as_dict("cfg/buttons_config.toml")["select_brawler"]
            self.window_controller.click(select_x, select_y, already_include_ratio=False)
            if self._sleep_interruptible(1.5, runtime_control, stop_event):
                print("Brawler selection aborted by user.")
                return "aborted"
            self.window_controller.screenshot()
            print("Selected brawler ", brawler_search_name)
            return "success"

        print(f"WARNING: Brawler '{brawler}' was not found after 100 scroll attempts.")
        return "failed"
