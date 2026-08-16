import hashlib
import html
import io
import math
import os
import random
import ssl
import threading
import time
from io import BytesIO
import ctypes
import json
from pathlib import Path
import requests
import toml
from PIL import Image
import cv2
from packaging import version
import traceback

try:
    from early_access.early_access import get_brawler_stats, get_player_info
    early_access = True
except (ImportError, ModuleNotFoundError):
    def get_brawler_stats(_player_info, _brawler_name):
        return None, None

    def get_player_info(_tag):
        return None
    early_access = False

def extract_text_and_positions(image_path):
    results = reader.readtext(image_path)
    text_details = {}
    for (bbox, text, prob) in results:
        top_left, top_right, bottom_right, bottom_left = bbox
        cx = (top_left[0] + top_right[0] + bottom_right[0] + bottom_left[0]) / 4
        cy = (top_left[1] + top_right[1] + bottom_right[1] + bottom_left[1]) / 4
        center = (cx, cy)
        formatted_bbox = {
            'top_left': top_left,
            'top_right': top_right,
            'bottom_right': bottom_right,
            'bottom_left': bottom_left,
            'center': center
        }

        text_details[text.lower()] = formatted_bbox

    return text_details


class DefaultEasyOCR:
    REQUIRED_MODELS = ("craft_mlt_25k.pth", "english_g2.pth")

    def __init__(self):
        self.reader = None
        self.lock = threading.Lock()

    def readtext(self, image_input):
        if self.reader is None:
            with self.lock:
                if self.reader is None:
                    self.reader = self.create_reader()
        return self.reader.readtext(image_input)

    def create_reader(self):
        model_dir = resolve_project_path("models", "easyocr")
        self.validate_model_directory(model_dir)
        try:
            import easyocr
            try:
                return easyocr.Reader(
                    ['en'],
                    model_storage_directory=str(model_dir),
                    download_enabled=False,
                    verbose=False,
                    gpu=False
                )
            except Exception as exc:
                raise EasyOCRInitializationError(f"EasyOCR failed to load bundled models from {model_dir}: {exc}") from exc
        except ssl.SSLCertVerificationError:
            raise EasyOCRInitializationError("EasyOCR initialization failed due to SSL certificate verification error. To fix this, please check https://discord.com/channels/1205263029269438574/1227618442073342002/1499330873538117703 for a solution.")

    def validate_model_directory(self, model_dir):
        missing = [filename for filename in self.REQUIRED_MODELS if not (model_dir / filename).exists()]
        if missing:
            raise EasyOCRInitializationError(f"Missing EasyOCR model file(s) in {model_dir}: {', '.join(missing)}")


class EasyOCRInitializationError(RuntimeError):
    pass


def _get_project_root():
    import sys
    from pathlib import Path
    if getattr(sys, 'frozen', False):
        return Path(sys.executable).parent.parent
    return Path.cwd().resolve()


PROJECT_ROOT = _get_project_root()


def resolve_project_path(*parts) -> Path:
    return PROJECT_ROOT.joinpath(*parts)

cached_toml = {}
def load_toml_as_dict(file_path, cache=True):
    full_path = PROJECT_ROOT / str(file_path).lstrip('/\\')
    if str(full_path) in cached_toml and cache:
        return cached_toml[str(full_path)]
    try:
        with open(full_path, 'r', encoding='utf-8') as f:
            data = toml.load(f)
            cached_toml[str(full_path)] = data
            return data
    except Exception as e:
        print(f"Error loading {full_path}: {e}")
        return {}

def invalidate_toml_cache(file_path):
    full_path = PROJECT_ROOT / str(file_path).lstrip('/\\')
    del cached_toml[str(full_path)]


def save_dict_as_toml(data, file_path):
    full_path = PROJECT_ROOT / str(file_path).lstrip('/\\')
    with open(full_path, 'w', encoding='utf-8') as f:
        toml.dump(data, f)
    cached_toml[str(full_path)] = data


reader = DefaultEasyOCR()
try:
    from early_access.early_access import OFFICIAL_API
    default_api = OFFICIAL_API
except (ImportError, ModuleNotFoundError):
    default_api = "localhost"
cfg_api_base_url = load_toml_as_dict("cfg/general_config.toml").get("api_base_url", "default")
api_base_url = cfg_api_base_url if cfg_api_base_url != "default" else default_api
brawlers_info_file_path = PROJECT_ROOT / "cfg" / "brawlers_info.json"


def count_hsv_pixels(cv_image, low_hsv, high_hsv):
    hsv_image = cv2.cvtColor(cv_image, cv2.COLOR_RGB2HSV)
    mask = cv2.inRange(hsv_image, low_hsv, high_hsv)
    return cv2.countNonZero(mask)


def count_mask_pixels(mask, x1, y1, x2, y2):
    height, width = mask.shape[:2]
    x1 = max(0, min(width, int(x1)))
    x2 = max(0, min(width, int(x2)))
    y1 = max(0, min(height, int(y1)))
    y2 = max(0, min(height, int(y2)))
    if x1 >= x2 or y1 >= y2:
        return 0
    return cv2.countNonZero(mask[y1:y2, x1:x2])

def save_brawler_data(data):
    """
    Save the given data to a json file. As a list of dictionaries.
    """
    queue_path = resolve_project_path("latest_brawler_data.json")
    with open(queue_path, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=4)


def load_brawler_data():
    queue_path = resolve_project_path("latest_brawler_data.json")
    if not queue_path.exists():
        return []
    try:
        with open(queue_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        return clean_queue(data) if isinstance(data, list) else []
    except Exception as e:
        traceback.print_exc()
        print(f"Error loading queue data from {queue_path}: {e}")
        return []

def load_all_brawlers_names():
    brawler_names_path = resolve_project_path("cfg", "names.json")
    if not brawler_names_path.exists():
        return {}
    try:
        with open(brawler_names_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except Exception as e:
        traceback.print_exc()
        print(f"Error loading brawler names from {brawler_names_path}: {e}")
        return {}


def api_update_brawler_data(brawler_data):
    if not early_access:
        return
    player_tag = load_toml_as_dict("cfg/general_config.toml")["player_tag"]
    if not player_tag:
        return
    player_info = get_player_info(player_tag)
    if not player_info:
        return
    for brawler in brawler_data:
        trophies, win_streak = get_brawler_stats(player_info, brawler['brawler'])
        if trophies is not None:
            brawler['trophies'] = trophies
        if win_streak is not None:
            brawler['win_streak'] = win_streak
    save_brawler_data(brawler_data)


def clear_brawler_data():
    queue_path = resolve_project_path("latest_brawler_data.json")
    if queue_path.exists():
        queue_path.unlink()


def clean_queue(data):
    cleaned_data = []
    for brawler_data in data:
        if brawler_data['type'] not in ["trophies", "wins"]:
            brawler_data['type'] = "trophies"
        type_of_push = brawler_data['type']
        if brawler_data[type_of_push] == "":
            brawler_data[type_of_push] = 0

        if brawler_data['push_until'] == "":
            if type_of_push == "wins":
                brawler_data['push_until'] = 300
            elif type_of_push == "trophies":
                brawler_data['push_until'] = 1000
        value = brawler_data[type_of_push]
        if isinstance(value, str):
            try:
                value = int(value)
            except ValueError:
                value = 0
        current_win_streak = brawler_data["win_streak"] if "win_streak" in brawler_data else 0
        if not isinstance(current_win_streak, int):
            try:
                current_win_streak = int(current_win_streak)
            except ValueError:
                current_win_streak = 0
        automatically_pick = brawler_data["automatically_pick"]
        if not isinstance(automatically_pick, bool):
            automatically_pick = str(automatically_pick).strip().lower() in {"1", "true", "yes", "on"}
        current_wins = brawler_data["wins"]
        if not isinstance(current_wins, int):
            try:
                current_wins = int(current_wins)
            except ValueError:
                current_wins = 0
        current_trophies = brawler_data["trophies"]
        if not isinstance(current_trophies, int):
            try:
                current_trophies = int(current_trophies)
            except ValueError:
                current_trophies = 0
        push_until = brawler_data['push_until']
        if not isinstance(push_until, int):
            try:
                push_until = int(push_until)
            except ValueError:
                push_until = 0

        if value < push_until:
            final_brawler_data = {"brawler": brawler_data['brawler'], "type": type_of_push, "trophies": current_trophies, "wins": current_wins, "push_until": push_until, "automatically_pick": automatically_pick, "win_streak": current_win_streak}
            cleaned_data.append(final_brawler_data)
    return cleaned_data


def find_template_center(main_img, template, threshold=0.8):

    main_image_cv = cv2.cvtColor(main_img, cv2.COLOR_RGB2GRAY)
    if len(template.shape) == 3 and template.shape[2] == 3:
        template_cv = cv2.cvtColor(template, cv2.COLOR_BGR2GRAY)
    else:
        template_cv = template
    w, h = template_cv.shape[::-1]

    # Perform template matching
    result = cv2.matchTemplate(main_image_cv, template_cv, cv2.TM_CCOEFF_NORMED)
    min_val, max_val, min_loc, max_loc = cv2.minMaxLoc(result)

    # Check if the match is found based on a threshold value
    if max_val >= threshold:
        center_x = max_loc[0] + w // 2
        center_y = max_loc[1] + h // 2

        return center_x, center_y
    else:
        return False


def load_brawlers_info():
    if os.path.exists(brawlers_info_file_path):
        with open(brawlers_info_file_path, 'r') as f:
            return json.load(f)
    else:
        return {}


def update_brawlers_info(brawlers_info):
    with open(brawlers_info_file_path, 'w') as f:
        json.dump(brawlers_info, f, indent=4)


def get_brawler_list():
    if api_base_url == "localhost":
        brawler_list = list(load_brawlers_info().keys())
        return brawler_list
    url = f'https://{api_base_url}/get_brawler_list'
    response = requests.post(url)
    if response.status_code == 201:
        data = response.json()
        return list(set(data.get('brawlers', []) + list(load_brawlers_info().keys())))
    else:
        return []


def update_missing_brawlers_info(brawlers):
    brawlers_info = load_brawlers_info()
    for brawler in brawlers:
        if brawler not in brawlers_info:
            brawler_info = get_brawler_info(brawler)
            if brawler_info:
                brawlers_info[brawler] = brawler_info
                update_brawlers_info(brawlers_info)
                print(f"Added info for brawler '{brawler}': {brawler_info}")
                # Download the brawler icon
                save_brawler_icon(brawler)
            else:
                print(f"Could not find info for brawler '{brawler}'")
        if not os.path.exists(PROJECT_ROOT / "api" / "assets" / "brawler_icons" / f"{brawler}.png"):
            save_brawler_icon(brawler)


def get_brawler_info(brawler_name):
    url = f'https://{api_base_url}/get_brawler_info'  # Adjust the URL if necessary
    response = requests.post(url, json={'brawler_name': brawler_name})
    if response.status_code == 200:
        data = response.json()
        return data.get('info', [])
    else:
        print(f"Error fetching info for '{brawler_name}': {response.status_code} - {response.text}")
        return None


def save_brawler_icon(brawler_name):
    # Clean the brawler name for filename
    brawler_name_clean = brawler_name.lower().replace(' ', '').replace('-', '').replace('.', '').replace('&',
                                                                                                         '')
    brawlers_url = "https://api.brawlify.com/v1/brawlers"
    response = requests.get(brawlers_url)
    if response.status_code != 200:
        print(f"Failed to fetch brawlers from API: {response.status_code}")
        return
    brawlers_data = response.json()['list']

    # Find the brawler in the API data
    for brawler_obj in brawlers_data:
        api_brawler_name = brawler_obj['name'].lower().replace(' ', '').replace('-', '').replace('.', '').replace('&', '')
        if api_brawler_name == brawler_name_clean:
            icon_url = brawler_obj['imageUrl2']
            img_response = requests.get(icon_url)
            if img_response.status_code == 200:
                image = Image.open(BytesIO(img_response.content))
                safe_name = os.path.basename(brawler_name_clean).replace('/', '').replace('\\', '')
                icon_path = PROJECT_ROOT / "api" / "assets" / "brawler_icons" / f"{safe_name}.png"
                icon_path.parent.mkdir(parents=True, exist_ok=True)
                image.save(str(icon_path))
                print(f"Saved icon for brawler '{brawler_name}'")
            else:
                print(f"Failed to download icon for '{brawler_name}'")
            return
    print(f"Icon not found for brawler '{brawler_name}'")


PYLA_VERSION = "0.8.14"


def get_latest_version():
    url = f'https://{api_base_url}/check_version'
    response = requests.get(url)
    if response.status_code == 200:
        data = response.json()
        return data.get('version', '')
    else:
        return None


def check_version():
    if api_base_url != "localhost":
        latest_version = get_latest_version()
        if latest_version:
            if version.parse(PYLA_VERSION) < version.parse(latest_version):
                print(f"Warning: (ignore if you're using early access) You are not using the latest public version of Pyla. \nCheck the discord for the latest download link.")
        else:
            print("Error, couldn't get the version, please check your internet connection or go ask for help in the discord.")


def format_notification_status(stage_manager) -> str:
    current_brawler_data = stage_manager.brawlers_pick_data[0]
    push_type = current_brawler_data["type"]
    target = current_brawler_data["push_until"]
    trophy_observer = stage_manager.Trophy_observer

    if push_type == "wins":
        current_amount = trophy_observer.current_wins
    else:
        current_amount = trophy_observer.current_trophies

    win_streak = trophy_observer.win_streak
    next_brawler = stage_manager.brawlers_pick_data[1]["brawler"] if len(stage_manager.brawlers_pick_data) > 1 else "None"
    brawlers_left = max(len(stage_manager.brawlers_pick_data) - 1, 0)

    return (
        f"Current brawler: {current_brawler_data['brawler']} \n"
        f"{push_type.capitalize()}: {current_amount}/{target} | "
        f"Win streak: {win_streak} \n"
        f"Next brawler: {next_brawler} | "
        f"Brawlers left: {brawlers_left}"
    )


def notify_user(message_type, screenshot, stage_manager) -> None:
    user_id = load_toml_as_dict("cfg/webhook_config.toml")["discord_id"].strip()
    webhook_url = load_toml_as_dict("cfg/webhook_config.toml")["webhook_url"].strip()
    telegram_token = load_toml_as_dict("cfg/webhook_config.toml")["telegram_token"].strip()
    telegram_chat_id = load_toml_as_dict("cfg/webhook_config.toml")["telegram_chat_id"].strip()
    has_discord = webhook_url
    has_telegram = telegram_token and telegram_chat_id

    if not has_discord and not has_telegram:
        print("Couldn't notify: no Discord webhook or Telegram bot configured.")
        return

    if message_type == "completed":
        status_line = f"Pyla has completed all its targets!"
    elif message_type == "bot_is_stuck":
        status_line = f"Your bot is currently stuck, attempted to restart brawl stars !"
    elif message_type == "brawler_goal":
        current_brawler = stage_manager.brawlers_pick_data[0]["brawler"]
        status_line = f"Pyla completed brawler goal for {current_brawler}!"
    elif message_type in ["regular_minutes_ping", "regular_matches_ping"]:
        status_line = "Pyla is still running."
    elif message_type == "bot_failed_brawler_selection":
        current_brawler = stage_manager.brawlers_pick_data[0]["brawler"]
        status_line = f"Pyla failed to select the brawler {current_brawler} after multiple attempts, try changing the OCR Scale Down setting or select it manually and restart. Putting it at the end of the queue and skipping it..."
    else:
        status_line = "Notification"

    stage_status = format_notification_status(stage_manager)
    if stage_status:
        status_line = f"{status_line}\n{stage_status}"

    image_buffer = None
    if screenshot is not None:
        try:
            screenshot_pil = Image.fromarray(screenshot)
            image_buffer = io.BytesIO()
            screenshot_pil.save(image_buffer, format="PNG")
            image_buffer.seek(0)
        except Exception as e:
            print(f"Failed to prepare screenshot: {e}")
            image_buffer = None

    if has_discord:
        ping = f"<@{user_id}>" if user_id else ""
        files = {}
        if image_buffer is not None:
            image_buffer.seek(0)
            files["file"] = ("screenshot.png", image_buffer, "image/png")

        embed = {
            "description": status_line
        }

        if files:
            embed["image"] = {"url": "attachment://screenshot.png"}

        payload = {
            "content": ping,
            "username": "Pyla notifier",
            "embeds": [embed],
        }

        print("Sending Discord webhook...")
        try:
            if files:
                response = requests.post(webhook_url, data={"payload_json": json.dumps(payload)}, files=files, timeout=15)
            else:
                response = requests.post(webhook_url, json=payload, timeout=15)

            if response.status_code not in (200, 204):
                print(f"Failed to send Discord webhook: {response.status_code} {response.text}")

        except Exception as e:
            print(f"Error sending Discord webhook: {e}")

    if has_telegram:
        print("Sending Telegram notification...")
        try:
            safe_text = html.escape(status_line)

            if image_buffer is not None:
                image_buffer.seek(0)
                url = f"https://api.telegram.org/bot{telegram_token}/sendPhoto"
                response = requests.post(url,
                    data={
                        "chat_id": telegram_chat_id,
                        "caption": safe_text,
                        "parse_mode": "HTML",
                    },
                    files={
                        "photo": ("screenshot.png", image_buffer, "image/png")
                    }, timeout=15)

            else:
                url = f"https://api.telegram.org/bot{telegram_token}/sendMessage"
                response = requests.post(url,
                    data={
                        "chat_id": telegram_chat_id,
                        "text": safe_text,
                        "parse_mode": "HTML",
                    }, timeout=15)

            if response.status_code != 200:
                print(f"Failed to send Telegram notification: {response.status_code} {response.text}")

        except Exception as e:
            print(f"Error sending Telegram notification: {e}")


def get_discord_link():
    if api_base_url == "localhost":
        return "https://discord.gg/xUusk3fw4A"
    url = f'https://{api_base_url}/get_discord_link'
    response = requests.get(url)
    if response.status_code == 200:
        data = response.json()
        return data.get('link', '')
    else:
        return None


def get_online_wall_model_hash():
    url = f'https://{api_base_url}/get_wall_model_hash'
    response = requests.get(url)
    if response.status_code == 200:
        data = response.json()
        return data.get('hash', '')
    else:
        return None


def calculate_sha256(file_path):
    """
    Calculate the SHA-256 hash of a file.
    """
    sha256_hash = hashlib.sha256()
    with open(file_path, "rb") as file:
        # Read the file in chunks to handle large files
        for chunk in iter(lambda: file.read(4096), b""):
            sha256_hash.update(chunk)
    return sha256_hash.hexdigest()


def current_wall_model_is_latest() -> bool:
    """
    Check if the current wall model is the latest version.
    """
    if not os.path.exists("models/tileDetector.onnx"):
        return False
    local_hash = calculate_sha256("models/tileDetector.onnx")
    online_hash = get_online_wall_model_hash()
    return local_hash == online_hash


def get_latest_wall_model_file():
    #download the new model to replace the current file and also updates the tile list
    url = f'https://{api_base_url}/get_wall_model_file'
    response = requests.get(url)
    if response.status_code == 200:
        with open("./models/tileDetector.onnx", "wb") as file:
            file.write(response.content)
        print("Downloaded the latest wall model.")
    else:
        print(f"Failed to download the latest wall model. Status code: {response.status_code}")


def get_latest_wall_model_classes():
    url = f'https://{api_base_url}/get_wall_model_classes'
    response = requests.get(url)
    if response.status_code == 200:
        data = response.json()
        return data.get('classes', [])
    else:
        return None


def update_wall_model_classes():
    classes = get_latest_wall_model_classes()
    current_classes = load_toml_as_dict("cfg/bot_config.toml")["wall_model_classes"]
    if classes:
        if classes != current_classes:
            print("New wall model classes found. Updating...")
            full_config = load_toml_as_dict("cfg/bot_config.toml")
            full_config["wall_model_classes"] = classes
            save_dict_as_toml(full_config, "cfg/bot_config.toml")
            print("Updated the wall model classes.")
    else:
        print("Failed to update the wall model classes, please report this error.")


def cprint(text: str, hex_color: str):
    try:
        hex_color = hex_color.lstrip("#")
        r, g, b = tuple(int(hex_color[i:i+2], 16) for i in (0, 2, 4))
        print(f"\033[38;2;{r};{g};{b}m{text}\033[0m")
    except Exception:
        print(text)


def mask_secret(value: str | None, keep: int = 4) -> dict:
    value = (value or "").strip()
    if not value:
        return {"configured": False, "masked": ""}
    if len(value) <= keep:
        return {"configured": True, "masked": "•" * len(value)}
    return {
        "configured": True,
        "masked": f"{value[:2]}{'•' * max(len(value) - (keep + 2), 2)}{value[-keep:]}"
    }


def normalize_brawler_filename(brawler_name: str) -> str:
    return str(brawler_name).lower().replace(' ', '').replace('-', '').replace('.', '').replace('&', '')


def get_brawler_icon_path(brawler_name: str) -> Path | None:
    if not brawler_name:
        return None

    normalized = normalize_brawler_filename(brawler_name)
    candidates = [
        resolve_project_path("api", "assets", "brawler_icons", f"{normalized}.png"),
        resolve_project_path("api", "assets", "brawler_icons2", f"{str(brawler_name).lower()}.png"),
        resolve_project_path("api", "assets", "brawler_icons2", f"{str(brawler_name).lower().strip()}.png"),
    ]

    for candidate in candidates:
        if candidate.exists():
            return candidate
    return None


def get_dpi_scale():
    user32 = ctypes.windll.user32
    user32.SetProcessDPIAware()
    return int(user32.GetDpiForSystem())


SAFE_GLOBALS = {
    'math': math,
    'random': random,
    'abs': abs,
    'min': min,
    'max': max,
    'sum': sum,
    'round': round,
    'len': len,
    'range': range,
    'zip': zip,
    'map': map,
    'int': int,
    'float': float,
    'str': str,
    'print': print,
    'time_now': lambda: time.time(),
    'random_int': random.randint,
}


import ast

def is_safe_ast(code_str):
    try:
        tree = ast.parse(code_str)
    except SyntaxError as e:
        return False, f"Syntax Error: {e}"

    for node in ast.walk(tree):
        # 1. Block access to any attributes starting with underscore (e.g. __class__)
        if isinstance(node, ast.Attribute):
            if node.attr.startswith('_'):
                return False, f"Access to private/dunder attribute '{node.attr}' is forbidden."
        
        # 2. Block imports of any kind inside the script
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            return False, "Imports are not allowed in playstyle scripts."
            
        # 3. Block calling of eval, exec, compile, etc.
        if isinstance(node, ast.Name):
            if node.id in {'exec', 'eval', 'compile', 'getattr', 'setattr', 'delattr', '__import__'}:
                return False, f"Call to '{node.id}' is forbidden."

    return True, None


def interpret_pyla_code(pyla_code, context):
    safe_globals = SAFE_GLOBALS.copy()
    safe_globals.update(context)
    safe_globals['__builtins__'] = {}

    try:
        if isinstance(pyla_code, str):
            is_safe, error_msg = is_safe_ast(pyla_code)
            if not is_safe:
                print(f"Security/Syntax Validation Failed for playstyle: {error_msg}")
                return None, safe_globals
            compiled_code = compile(pyla_code, '<string>', 'exec')
        else:
            compiled_code = pyla_code

        if compiled_code is not None:
            exec(compiled_code, safe_globals)
    except Exception as e:
        print(f"Error executing .pyla code")
        traceback.print_exc()
        return None, safe_globals

    return safe_globals.get('movement', None), safe_globals


def load_pyla_script(filename):
    script_path = resolve_project_path("playstyles", filename)
    try:
        with open(script_path, 'r', encoding='utf-8') as file:
            metadata_header = file.readline().strip()
            metadata = json.loads(metadata_header) if metadata_header else {}
            pyla_script = file.read()
        return metadata, pyla_script
    except FileNotFoundError:
        print(f"Error: The file {script_path} was not found.")
        return "", ""
    except Exception as e:
        print(f"An error occurred while loading the .pyla script: {e}")
        traceback.print_exc()
        return "", ""


def get_playstyles_list():
    playstyles_dir = resolve_project_path("playstyles")
    playstyles = []
    if playstyles_dir.exists():
        for filename in os.listdir(playstyles_dir):
            if filename.endswith(".pyla"):
                metadata, _ = load_pyla_script(filename)
                playstyles.append({
                    "filename": filename,
                    "metadata": metadata
                })
    return playstyles


def load_default_pyla_script():
    config = load_toml_as_dict("cfg/bot_config.toml")
    current_playstyle = config.get("current_playstyle", "default_up.pyla")
    return load_pyla_script(current_playstyle)


def hash_playstyle(playstyle_info):
    return hashlib.sha256(str(playstyle_info).encode('utf-8')).hexdigest()


def config_bool(value, default=False):
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return bool(value)



def clamp(x: int, low: int, high: int) -> int:
    if x < low:
        return low
    if x > high:
        return high
    return x

JOYSTICK_RADIUS = 75

