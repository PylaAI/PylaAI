import json
import time

import cv2
import numpy as np
from utils import (
    count_hsv_pixels,
    extract_text_and_positions,
    load_toml_as_dict, load_all_brawlers_names, config_bool, resolve_project_path,
)


class LobbyAutomation:

    def __init__(self, window_controller):
        self.gray_pixels_treshold = load_toml_as_dict("./cfg/bot_config.toml").get('idle_pixels_minimum', 500)
        self.idle_reconnect_coords = load_toml_as_dict("cfg/buttons_config.toml")["idle_reconnect"]
        self.ocr_scale_down_factor = max(0.5, min(1, load_toml_as_dict("./cfg/general_config.toml").get('ocr_scale_down_factor', 1)))
        self.ocr_scale_up_factor = 1 / self.ocr_scale_down_factor
        self.all_brawlers_names = load_all_brawlers_names()
        self.window_controller = window_controller
        debug_settings = load_toml_as_dict("cfg/debug_settings.toml")
        self.verbose_debug = config_bool(debug_settings.get('verbose_debug'), False)
        self.collect_ocr_dataset = config_bool(debug_settings.get('collect_ocr_dataset'), False)
        self.full_ocr_dataset_scan = self.collect_ocr_dataset and config_bool(
            debug_settings.get('full_ocr_dataset_scan'), False
        )

    @staticmethod
    def _dataset_scan_fingerprint(screenshot):
        height, width = screenshot.shape[:2]
        roster = screenshot[int(height * 0.08):int(height * 0.98), int(width * 0.07):int(width * 0.93)]
        grayscale = cv2.cvtColor(roster, cv2.COLOR_RGB2GRAY)
        reduced = cv2.resize(grayscale, (32, 32), interpolation=cv2.INTER_AREA)
        return reduced > np.median(reduced)

    @staticmethod
    def _same_dataset_scan_screen(previous_fingerprint, current_fingerprint):
        if previous_fingerprint is None:
            return False
        return float(np.mean(previous_fingerprint != current_fingerprint)) < 0.10

    def _record_ocr_sample(self, screenshot, target_brawler, results, state, status, matched_name, attempt,
                           source_size):
        if not self.collect_ocr_dataset:
            return

        try:
            dataset_dir = resolve_project_path("ocr_dataset")
            images_dir = dataset_dir / "images"
            metadata_dir = dataset_dir / "metadata"
            images_dir.mkdir(parents=True, exist_ok=True)
            metadata_dir.mkdir(parents=True, exist_ok=True)

            sample_id = f"{time.time_ns()}_{attempt:03d}"
            image_name = f"{sample_id}.png"
            image_path = images_dir / image_name
            metadata_path = metadata_dir / f"{sample_id}.json"

            image_bgr = cv2.cvtColor(screenshot, cv2.COLOR_RGB2BGR)
            if not cv2.imwrite(str(image_path), image_bgr):
                raise OSError(f"Could not write OCR dataset image to {image_path}")

            detections = []
            for normalized_text, details in results.items():
                bbox = [
                    [float(value) for value in details[corner]]
                    for corner in ("top_left", "top_right", "bottom_right", "bottom_left")
                ]
                detections.append({
                    "text": str(details.get("text", normalized_text)),
                    "normalized_text": normalized_text,
                    "confidence": float(details.get("confidence", 0.0)),
                    "bbox": bbox,
                })

            metadata = {
                "schema_version": 1,
                "created_at_unix": time.time(),
                "image": f"images/{image_name}",
                "target_brawler": target_brawler,
                "matched_name": matched_name,
                "selection_status": status,
                "screen_state": state,
                "attempt": attempt,
                "ocr_scale_down_factor": self.ocr_scale_down_factor,
                "source_size": {"width": source_size[0], "height": source_size[1]},
                "ocr_size": {"width": screenshot.shape[1], "height": screenshot.shape[0]},
                "detections": detections,
            }
            with open(metadata_path, "w", encoding="utf-8") as metadata_file:
                json.dump(metadata, metadata_file, ensure_ascii=False, indent=2)
            print(f"Saved OCR dataset sample: {sample_id}")
        except Exception as exc:
            print(f"WARNING: Could not save OCR dataset sample: {exc}")

    def check_for_idle(self, frame):
        wr = self.window_controller.width_ratio
        hr = self.window_controller.height_ratio
        x_start, x_end = int(460 * wr), int(1460 * wr)
        y_start, y_end = int(400 * hr), int(675 * hr)
        gray_pixels = count_hsv_pixels(frame[y_start:y_end, x_start:x_end], (0, 0, 10), (30, 60, 67))
        if self.verbose_debug: print(f"gray pixels (if > {self.gray_pixels_treshold} then bot will try to unidle) :", gray_pixels)
        if gray_pixels > self.gray_pixels_treshold:
            self.window_controller.click(self.idle_reconnect_coords[0], self.idle_reconnect_coords[1], already_include_ratio=False)
            print("Idle detected, clicking to unidle")

    @staticmethod
    def _should_interrupt(runtime_control=None, stop_event=None):
        if runtime_control and (runtime_control.should_stop() or runtime_control.should_pause()):
            return True
        return stop_event is not None and stop_event.is_set()

    @staticmethod
    def _sleep_interruptible(duration, runtime_control=None, stop_event=None, poll_interval=0.1):
        end_time = time.time() + duration
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
        for symbol in [' ', '-', '.', "&"]:
            brawler = brawler.replace(symbol, "")

        x, y = load_toml_as_dict("cfg/buttons_config.toml")["brawlers_menu"]
        self.window_controller.click(x, y, already_include_ratio=False)
        time.sleep(0.5)
        c = 0
        print("Automatic brawler selection started for", brawler)
        if self.full_ocr_dataset_scan:
            print("Full OCR dataset scan enabled: no brawler will be selected.")
        previous_scan_fingerprint = None
        stable_scan_screens = 0
        for i in range(100):
            if self._should_interrupt(runtime_control, stop_event):
                print("Brawler selection aborted by user.")
                return "aborted"
            screenshot = self.window_controller.screenshot()
            source_size = (screenshot.shape[1], screenshot.shape[0])
            screenshot = cv2.resize(screenshot, (int(screenshot.shape[1] * self.ocr_scale_down_factor), int(screenshot.shape[0] * self.ocr_scale_down_factor)), interpolation=cv2.INTER_AREA)

            print("Recognizing brawlers on current screen...")
            try:
                ocr_results = extract_text_and_positions(screenshot)
            except Exception as exc:
                print(f"WARNING: Automatic brawler selection could not recognize this screen: {exc}")
                print("The bot will continue without changing the currently selected brawler.")
                return "error"
            results = {k: v for k, v in ocr_results.items() if len(k) >= 2}
            clean_results = {}
            for key in results.keys():
                orig_key = key
                for symbol in [' ', '-', '.', "&"]:
                    key = key.replace(symbol, "")
                clean_results[key.lower()] = results[orig_key]

            current_state = get_latest_state()
            if current_state != "brawler_selection":
                self._record_ocr_sample(screenshot, brawler, ocr_results, current_state, "unexpected_state", None,
                                        i, source_size)
                print("Latest screenshot is no longer of the lobby, aborting brawler selection...")
                return "stuck"
            elif self.full_ocr_dataset_scan:
                self._record_ocr_sample(
                    screenshot, brawler, ocr_results, current_state, "full_scan", None, i, source_size
                )
                current_fingerprint = self._dataset_scan_fingerprint(screenshot)
                if self._same_dataset_scan_screen(previous_scan_fingerprint, current_fingerprint):
                    stable_scan_screens += 1
                else:
                    stable_scan_screens = 0
                previous_scan_fingerprint = current_fingerprint

                if i >= 5 and stable_scan_screens >= 2:
                    print("Full OCR dataset scan reached the bottom of the brawler list.")
                    return "dataset_complete"

                self.window_controller.swipe(
                    int(1700 * wr), int(900 * hr), int(1700 * wr), int(600 * hr), duration=0.5
                )
                if self._sleep_interruptible(3, runtime_control, stop_event):
                    print("OCR dataset scan aborted by user.")
                    return "aborted"
                continue
            elif brawler in clean_results.keys():
                matched_key = brawler
            else:
                matched_key = None
                for detected_name in clean_results.keys():
                    if detected_name in self.all_brawlers_names[brawler]:
                        matched_key = detected_name
                        print(f"Matched detected name '{detected_name}' to brawler '{brawler}' using alias list.")
                        break

            self._record_ocr_sample(
                screenshot,
                brawler,
                ocr_results,
                current_state,
                "locked" if matched_key and clean_results[matched_key].get("locked") else (
                    "matched" if matched_key else "not_found"
                ),
                matched_key,
                i,
                source_size,
            )

            if self.verbose_debug:
                print("OCR detected the following potential matches for the brawler name:")
                import difflib
                for detected_name in clean_results.keys():
                    match_ratio = difflib.SequenceMatcher(None, detected_name, brawler).ratio()
                    if match_ratio >= 0.25:
                        print(f" - '{detected_name}' with match ratio {match_ratio:.2f}")
            if matched_key:
                if clean_results[matched_key].get("locked"):
                    print(
                        f"WARNING: Brawler '{brawler}' was found but is not unlocked. "
                        "Automatic selection has been paused."
                    )
                    if runtime_control:
                        runtime_control.request_pause()
                    return "locked"
                x, y = clean_results[matched_key]['center']
                y_offset = 50*self.ocr_scale_down_factor
                y -= y_offset
                self.window_controller.click(int(x * self.ocr_scale_up_factor), int(y * self.ocr_scale_up_factor))
                print(f"Found brawler {brawler} ({matched_key}) clicking on its icon at {int(x * self.ocr_scale_up_factor)} {int(y * self.ocr_scale_up_factor)}")
                if self._sleep_interruptible(1, runtime_control, stop_event):
                    print("Brawler selection aborted by user.")
                    return "aborted"
                select_x, select_y = load_toml_as_dict("cfg/buttons_config.toml")["select_brawler"]
                self.window_controller.click(select_x, select_y, already_include_ratio=False)
                if self._sleep_interruptible(1.5, runtime_control, stop_event):
                    print("Brawler selection aborted by user.")
                    return "aborted"
                self.window_controller.screenshot()
                print("Selected brawler ", brawler)
                return "success"
            else:
                print("Brawler name not found on screen, scrolling down to load more brawlers...")

            self.window_controller.swipe(int(1100 * wr), int(1040 * hr), int(400 * wr), int(1040 * hr), duration=0.4)
            if self._sleep_interruptible(3, runtime_control, stop_event):
                print("Brawler selection aborted by user.")
                return "aborted"

        print(f"WARNING: Brawler '{brawler}' was not found after 100 scroll attempts.")
        return "failed"
