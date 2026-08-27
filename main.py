import inspect
import os
import sys

# Monkey-patch inspect.getfile to prevent Nuitka + PyTorch crash
_original_getfile = inspect.getfile
def _patched_getfile(obj):
    res = _original_getfile(obj)
    return res if res is not None else "<unknown_nuitka_file>"

inspect.getfile = _patched_getfile


if __name__ == "__main__" and len(sys.argv) >= 9 and sys.argv[1] == "--debug-viewer-worker":
    from debug_view import DEFAULT_DEBUG_VIEW_FPS, run_viewer_worker

    run_viewer_worker(
        shared_memory_name=sys.argv[2],
        debug_memory_name=sys.argv[3],
        height=int(sys.argv[4]),
        width=int(sys.argv[5]),
        channels=int(sys.argv[6]),
        dtype_text=sys.argv[7],
        title=sys.argv[8],
        clip_fps=float(sys.argv[9]) if len(sys.argv) >= 10 else DEFAULT_DEBUG_VIEW_FPS,
        record_clips=(len(sys.argv) >= 11 and sys.argv[10] == "1"),
    )
    sys.exit(0)

from adbutils import AdbError
import socket
import threading
import time
import webbrowser
from lobby_automation import LobbyAutomation
from play import Play
from stage_manager import StageManager
from state_finder import get_state
from time_management import TimeManagement
from utils import load_toml_as_dict, current_wall_model_is_latest, api_base_url, load_pyla_script, save_brawler_data, \
    clean_queue, get_discord_link
from utils import get_brawler_list, update_missing_brawlers_info, check_version, notify_user, update_wall_model_classes, get_latest_wall_model_file, cprint
from window_controller import WindowController
from webui import create_app


def apply_play_order(queue_data):
    play_order = str(load_toml_as_dict("cfg/general_config.toml").get("play_order", "in_order")).strip().lower()
    if play_order == "lowest_to_highest":
        ordered_data = sorted(queue_data, key=lambda item: int(item.get("trophies", 0) or 0))
    elif play_order == "highest_to_lowest":
        ordered_data = sorted(queue_data, key=lambda item: int(item.get("trophies", 0) or 0), reverse=True)
    else:
        return queue_data

    for item in ordered_data:
        item["automatically_pick"] = True
    return ordered_data


def pyla_main(discord_bot, queue_data, stop_event=None, runtime_control=None):
    class Main:
        def __init__(self):
            current_playstyle = load_toml_as_dict("cfg/bot_config.toml").get("current_playstyle", "default_up.pyla")
            try:
                self.max_ips = int(load_toml_as_dict("cfg/general_config.toml")['max_ips'])
            except ValueError:
                self.max_ips = None

            if self.max_ips:
                self.window_controller = WindowController(self.max_ips)
            else:
                self.window_controller = WindowController()
            data = clean_queue(queue_data)
            data = apply_play_order(data)
            if not data:
                raise ValueError("No valid brawler data found. Please add a brawler configuration in the UI before starting the bot.")
            save_brawler_data(data)
            print("Starting with queue data:", data)
            self.playstyle_info, pyla_code = load_pyla_script(current_playstyle)
            self.Play = Play(*self.load_models(), self.window_controller, pyla_code)
            self.Time_management = TimeManagement()
            self.lobby_automator = LobbyAutomation(self.window_controller)
            self.runtime_control = runtime_control
            self.Stage_manager = StageManager(data, self.lobby_automator, self.window_controller, self.playstyle_info, self.get_latest_state, runtime_control=runtime_control)
            self.states_requiring_data = ["lobby"]
            self.no_detections_action_threshold = 60 * 8
            self.state = None
            self.stop_event = stop_event
            self.state_lock = threading.Lock()
            self.latest_state_frame_time = 0.0
            self.max_cached_state_age = 1.0
            self.state_checker_stop_event = threading.Event()
            self.state_checker_thread = None
            self.update_trophy_observer()

            self.run_for_minutes = int(load_toml_as_dict("cfg/general_config.toml")['run_for_minutes'])
            self.webhook_ping_every_minutes = load_toml_as_dict("cfg/webhook_config.toml")['ping_every_x_minutes']
            self.time_since_last_webhook_ping = time.time()
            self.start_time = time.time()
            self.time_to_stop = False
            self.in_cooldown = False
            self.cooldown_start_time = 0
            self.cooldown_duration = 3 * 60
            self.window_controller.screenshot()
            discord_bot.set_window_controller(self.window_controller)
            self.start_state_checker()
            print("Initialization complete, starting main loop.")
            self.picked_first_brawler = False
            self.time_since_checked_if_brawl_stars_crashed = time.time()
            self.check_if_brawl_stars_crashed_timer = load_toml_as_dict("cfg/time_tresholds.toml")["check_if_brawl_stars_crashed"]
            self.ping_when_stuck = load_toml_as_dict("cfg/webhook_config.toml")["ping_when_stuck"]

        def update_trophy_observer(self):
            current_brawler_data = self.Stage_manager.brawlers_pick_data[0]
            self.Stage_manager.Trophy_observer.win_streak = current_brawler_data['win_streak']
            self.Stage_manager.Trophy_observer.current_trophies = current_brawler_data['trophies']
            self.Stage_manager.Trophy_observer.current_wins = current_brawler_data['wins'] if current_brawler_data['wins'] != "" else 0

        @staticmethod
        def load_models():
            folder_path = "./models/"
            return [
                folder_path + 'mainInGameModel.onnx',
                folder_path + 'tileDetector.onnx',
                folder_path + 'closeTileDetector.onnx',
            ]

        def restart_brawl_stars(self):
            self.window_controller.restart_brawl_stars()
            self.time_since_checked_if_brawl_stars_crashed = time.time()
            self.Play.time_since_detections["player"] = time.time()
            self.Play.time_since_detections["enemy"] = time.time()
            if not self.window_controller.is_brawl_stars_running():
                ping_when_stuck = load_toml_as_dict("cfg/webhook_config.toml")["ping_when_stuck"]
                if ping_when_stuck:
                    screenshot = self.window_controller.screenshot()
                    notify_user("bot_is_stuck", screenshot, self.Stage_manager)
                    print("Bot got stuck. User notified.")
                print("Shutting down.")
                self.window_controller.release_movement()
                self.window_controller.close()
                discord_bot.set_window_controller(None)
                sys.exit(1)

        def should_stop(self):
            return bool(self.stop_event and self.stop_event.is_set()) or bool(self.runtime_control and self.runtime_control.should_stop())

        def should_pause(self):
            return bool(self.runtime_control and self.runtime_control.should_pause())

        def sleep_interruptible(self, duration, allow_pause=True, poll_interval=0.1):
            end_time = time.time() + duration
            while time.time() < end_time:
                if self.should_stop():
                    return "stop"
                if allow_pause and self.should_pause():
                    return "pause"
                time.sleep(min(poll_interval, max(end_time - time.time(), 0)))
            return None

        def stop_gracefully(self):
            cprint("Stop requested from UI - shutting down gracefully", "#AAE5A4")
            self.stop_state_checker()
            self.window_controller.release_movement()
            self.window_controller.close()
            discord_bot.set_window_controller(None)

        def start_state_checker(self):
            if self.state_checker_thread and self.state_checker_thread.is_alive():
                return
            self.state_checker_stop_event.clear()
            self.state_checker_thread = threading.Thread(
                target=self.state_checker_loop,
                daemon=True,
                name="pyla-state-checker"
            )
            self.state_checker_thread.start()

        def stop_state_checker(self):
            self.state_checker_stop_event.set()
            if self.state_checker_thread and self.state_checker_thread.is_alive():
                self.state_checker_thread.join(timeout=1.0)

        def set_latest_state(self, state):
            with self.state_lock:
                self.state = state

        def get_latest_state(self):
            with self.state_lock:
                return self.state

        def handle_detected_state(self, state):
            if state is None:
                return
            self.set_latest_state(state)

            print(f"State: {state}")
            frame_data = None
            self.Stage_manager.do_state(state, frame_data)
            if state != "match":
                self.Play.time_since_last_proceeding = time.time()

        def state_checker_loop(self):
            last_checked_frame_time = 0.0
            while not self.state_checker_stop_event.is_set():
                frame, frame_time = self.window_controller.get_latest_frame()
                if frame is None or frame_time <= last_checked_frame_time:
                    self.state_checker_stop_event.wait(0.01)
                    continue

                last_checked_frame_time = frame_time
                try:
                    self.set_latest_state(get_state(frame))
                except Exception as e:
                    print(f"State checker failed: {e}")
                    self.state_checker_stop_event.wait(0.1)

        def wait_while_paused(self):
            if not self.runtime_control:
                return

            self.window_controller.release_movement()
            self.runtime_control.mark_paused()
            cprint("Pyla is paused in the lobby. Waiting for Start to resume.", "#AAE5A4")

            while self.should_pause() and not self.should_stop():
                state = self.get_latest_state()
                if state is None:
                    if self.sleep_interruptible(0.25, allow_pause=False) == "stop":
                        return
                    continue
                if self.sleep_interruptible(0.75, allow_pause=False) == "stop":
                    return

            if not self.should_stop():
                self.runtime_control.mark_running()
                self.time_since_last_webhook_ping = time.time()
                print("Pause released, resuming run.")

        def handle_pause_request(self):
            if self.should_pause() and not self.should_stop():
                cprint("Pause requested from UI - waiting", "#AAE5A4")
                self.wait_while_paused()

        def manage_time_tasks(self, frame):
            if self.Time_management.state_check():
                state = self.get_latest_state()
                if state is not None:
                    self.handle_detected_state(state)
            if self.Time_management.no_detections_check():
                frame_data = self.Play.time_since_detections
                t_now = time.time()
                for key, value in frame_data.items():
                    if t_now - value > self.no_detections_action_threshold:
                        self.restart_brawl_stars()
            if self.Time_management.idle_check():
                self.lobby_automator.check_for_idle(frame)

            current_time = time.time()
            if self.webhook_ping_every_minutes and current_time - self.time_since_last_webhook_ping >= self.webhook_ping_every_minutes * 60:
                screenshot = self.window_controller.screenshot()
                notify_user("regular_minutes_ping", screenshot, self.Stage_manager)
                self.time_since_last_webhook_ping = current_time
                print(f"Sent regular webhook ping after {self.webhook_ping_every_minutes} minutes.")

        def check_and_handle_brawl_stars_crash(self):
            c_time = time.time()
            if c_time - self.time_since_checked_if_brawl_stars_crashed > self.check_if_brawl_stars_crashed_timer:
                try:
                    opened_app = self.window_controller.device.app_current().package.strip()
                    if not self.window_controller.is_brawl_stars_running():
                        print(f"Brawl stars has crashed, {opened_app} is the app opened ! Restarting...")
                        self.window_controller.device.app_start(self.window_controller.BRAWL_STARS_PACKAGE)
                        time.sleep(3)
                        self.time_since_checked_if_brawl_stars_crashed = time.time()
                    else:
                        self.time_since_checked_if_brawl_stars_crashed = c_time
                except AdbError:
                    print("There was an error checking if Brawl Stars is running. Attempting to reconnect scrcpy...")
                    if not self.window_controller.reconnect_scrcpy():
                        print("Reconnect failed -- restarting Brawl Stars")
                        self.restart_brawl_stars()

        def main(self):
            s_time = time.time()
            c = 0
            self.time_since_last_webhook_ping = time.time()
            if self.runtime_control:
                self.runtime_control.mark_running()

            while True:
                if self.get_latest_state() == "lobby":
                    if self.should_stop():
                        self.stop_gracefully()
                        break

                    if self.should_pause():
                        self.handle_pause_request()
                        if self.should_stop():
                            self.stop_gracefully()
                            break
                        if self.should_pause():
                            continue

                if not self.picked_first_brawler and self.get_latest_state() == "lobby":
                    if self.Stage_manager.brawlers_pick_data[0]['automatically_pick']:
                        next_brawler_name = self.Stage_manager.brawlers_pick_data[0]['brawler']
                        print("Picking brawler automatically")
                        if self.runtime_control:
                            self.runtime_control.mark_running()
                        select_brawler = self.lobby_automator.select_brawler(next_brawler_name, self.get_latest_state, runtime_control=self.runtime_control)

                        while select_brawler in ["failed", "error"]:
                            print("Automatic brawler selection failed.")
                            if self.ping_when_stuck:
                                screenshot = self.window_controller.screenshot()
                                notify_user("bot_failed_brawler_selection", screenshot, self.Stage_manager)
                            failed_brawler = self.Stage_manager.brawlers_pick_data.pop(0)
                            self.Stage_manager.brawlers_pick_data.append(failed_brawler)
                            next_brawler_name = self.Stage_manager.brawlers_pick_data[0]['brawler']
                            select_brawler = self.lobby_automator.select_brawler(next_brawler_name, self.get_latest_state, runtime_control=self.runtime_control)

                        if select_brawler == "aborted" or select_brawler == "stuck":
                            continue
                        self.picked_first_brawler = True
                        self.update_trophy_observer()
                    else:
                        self.picked_first_brawler = True
                t_now = time.time()
                if self.max_ips:
                    frame_start = time.perf_counter()

                if self.run_for_minutes > 0 and not self.in_cooldown:
                    elapsed_time = (t_now - self.start_time) / 60
                    if elapsed_time >= self.run_for_minutes:
                        cprint(f"timer is done, {self.run_for_minutes} is over. continuing for 3 minutes if in game", "#AAE5A4")
                        self.in_cooldown = True
                        self.cooldown_start_time = t_now
                        self.Stage_manager.states['lobby'] = lambda: 0

                if self.in_cooldown and t_now - self.cooldown_start_time >= self.cooldown_duration:
                    cprint("stopping bot fully", "#AAE5A4")
                    self.stop_gracefully()
                    break

                if abs(s_time - t_now) > 1:
                    elapsed = t_now - s_time
                    if elapsed > 0:
                        print(f"{c / elapsed:.2f} IPS")
                    s_time = t_now
                    c = 0
                self.check_and_handle_brawl_stars_crash()
                frame = self.window_controller.screenshot()

                _, last_ft = self.window_controller.get_latest_frame()
                if last_ft > 0 and (t_now - last_ft) > self.window_controller.FRAME_STALE_TIMEOUT:
                    stale_age = t_now - last_ft
                    self.Play.window_controller.release_movement()
                    if stale_age > 30:
                        print(f"Scrcpy feed stale for {stale_age:.0f}s -- attempting reconnect")
                        if not self.window_controller.reconnect_scrcpy():
                            print("Reconnect failed -- restarting Brawl Stars")
                            self.restart_brawl_stars()
                    else:
                        print("Stale frame detected -- pausing actions until feed resumes")
                        if self.sleep_interruptible(1) == "stop":
                            self.stop_gracefully()
                            break
                    continue

                self.manage_time_tasks(frame)

                brawler = self.Stage_manager.brawlers_pick_data[0]['brawler']
                self.Play.current_brawler = brawler
                self.Play.main(frame, brawler, self)
                c += 1

                if self.max_ips:
                    target_period = 1 / self.max_ips
                    work_time = time.perf_counter() - frame_start
                    if work_time < target_period:
                        time.sleep(target_period - work_time)

    os.makedirs("debug_frames", exist_ok=True)
    main = Main()
    main.main()


all_brawlers = get_brawler_list()
if api_base_url != "localhost":
    update_missing_brawlers_info(all_brawlers)
    check_version()
    update_wall_model_classes()
    if not current_wall_model_is_latest():
        print("New Wall detection model found, downloading... (this might take a few minutes depending on your internet)")
        get_latest_wall_model_file()


def find_open_port(start_port=5185, host="127.0.0.1"):
    for port in range(start_port, start_port + 50):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            if sock.connect_ex((host, port)) != 0:
                return port
    raise RuntimeError("Could not find an open localhost port for the Flask UI.")


def open_browser_later(local_url):
    def _open():
        time.sleep(1.5)
        webbrowser.open(local_url)

    threading.Thread(target=_open, daemon=True, name="pyla-browser-launcher").start()


if __name__ == "__main__":
    print("Starting PylaAI, the best free and open source brawl stars bot")
    print("The only official discord is", get_discord_link())
    port = find_open_port()
    app = create_app(pyla_main, start_discord_bot=True)
    local_url = f"http://127.0.0.1:{port}"
    print(f"Starting Pyla web UI at {local_url}")
    open_browser_later(local_url)
    app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False)
