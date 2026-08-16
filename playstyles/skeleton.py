import math
import random
import time
from typing import List, Tuple, Dict, Any, Optional, Union

# =====================================================================
# MODULES & BUILT-INS
# =====================================================================
# math, random, time, abs, min, max, sum, round, len, range, zip, map,
# int, float, str, print are natively available in Python.

def time_now() -> float:
    """Returns the current time in seconds (equivalent to time.time())."""
    return time.time()

def random_int(a: int, b: int) -> int:
    """Returns a random integer between a and b (equivalent to random.randint)."""
    return random.randint(a, b)


# =====================================================================
# GAME STATE VARIABLES (Context)
# =====================================================================

player_data: List[float] = [0.0, 0.0, 0.0, 0.0]
"""Bounding box of the player [x1, y1, x2, y2]."""

enemy_data: List[List[float]] = []
"""List of bounding boxes for enemies: [[x1, y1, x2, y2], ...]."""

teammate_data: List[List[float]] = []
"""List of bounding boxes for teammates: [[x1, y1, x2, y2], ...]."""

brawler: str = ""
"""Name of the selected brawler (e.g., 'shelly', 'colt')."""

current_brawler: Optional[str] = None
"""Current brawler active in the session."""

walls: List[List[float]] =[]
"""List of bounding boxes for walls: [[x1, y1, x2, y2], ...]."""

bushes: List[List[float]] = []
"""List of bounding boxes for bushes: [[x1, y1, x2, y2], ...]."""

brawlers_info: Dict[str, Any] = {}
"""Dictionary containing parsed info from brawlers_info.json/toml."""

persistent_data: Dict[str, Any] = {"time_since_holding_attack": None}
"""Dictionary to keep track of variables across different frames/ticks."""

is_gadget_ready: bool = False
"""True if the gadget button is detected as ready."""

is_hypercharge_ready: bool = False
"""True if the hypercharge button is detected as ready."""

is_super_ready: bool = False
"""True if the super button is detected as ready."""

TILE_SIZE: int = 60
"""The configured size of a map tile in pixels."""

last_movement: Tuple[float, float] = ""
"""The string representing the last movement sent."""

last_movement_change_time: float = 0.0
"""Timestamp of when the movement direction was last changed."""

seconds_to_hold_attack_after_reaching_max: float = 0.0
"""Time to hold the attack button based on config."""

width_ratio: int = 1
"""Ratio between frame width and expected width"""

height_ratio: int = 1
"""Ratio between frame height and expected height"""

debug: bool = False
"""True if super debug mode is enabled."""

# Expected Output Variable
movement: tuple[float] = (0.0, 0.0)
"""
SET THIS VARIABLE IN YOUR SCRIPT. 
The double float representing the position of the joystick to move to. -75 <= x <= 75.
"""

JOYSTICK_RADIUS: int = 100
"""The radius in pixels for the virtual joystick area around the player center."""

PI = math.pi
"""The mathematical constant π (pi)."""


# =====================================================================
# CONTEXT FUNCTIONS
# =====================================================================

def must_brawler_hold_attack(brawler_name: str, brawlers_info_dict: Optional[Dict] = None) -> bool:
    """Check if the specific brawler needs to hold attack (e.g., Amber)."""
    return False

def get_entity_pos(entity: List[float]) -> Tuple[float, float]:
    """Returns the center (x, y) coordinates of the player bounding box."""
    return (0.0, 0.0)

def get_actual_player_box(player_box: List[float]) -> List[float]:
    """Returns the 106px hit-circle bounding box [x1, y1, x2, y2] derived from the detected player box."""
    return [0.0, 0.0, 0.0, 0.0]

def get_distance(enemy_coords: Tuple[float, float], player_coords: Tuple[float, float]) -> float:
    """Calculates the distance between two coordinates."""
    return 0.0

def get_brawler_range(brawler_name: str) -> List[int]:
    """Returns the scaled ranges for the brawler: [safe_range, attack_range, super_range]."""
    return[0, 0, 0]

def is_there_enemy(enemies: List[List[float]]) -> bool:
    """Returns True if the enemy list is not empty."""
    return False

def attack(touch_up: bool = True, touch_down: bool = True) -> None:
    """Presses the attack button."""
    pass

def use_hypercharge() -> None:
    """Presses the hypercharge button."""
    pass

def use_super() -> None:
    """Presses the super button."""
    pass

def use_gadget() -> None:
    """Presses the gadget button."""
    pass

def get_random_movement() -> Tuple[float, float]:
    """Generates a random movement."""
    return 0, 0

def find_closest_enemy(
    enemies: List[List[float]],
    player_coords: Tuple[float, float],
    walls_list: List[List[float]],
    skill_type: str
) -> Union[Tuple[Tuple[float, float], float], Tuple[None, None]]:
    """
    Finds the closest enemy considering walls and skill type ('attack' or 'super').
    Returns a tuple of (enemy_pos, distance) or (None, None).
    """
    return (0.0, 0.0), 0.0

def find_closest_teammate(
    teammates: List[List[float]],
    player_coords: Tuple[float, float],
    walls_list: List[List[float]]
) -> Union[Tuple[Tuple[float, float], float], Tuple[None, None]]:
    """
    Finds the closest teammate considering walls.
    Returns a tuple of (teammate_pos, distance) or (None, None).
    """
    return (0.0, 0.0), 0.0

def is_there_poison_gas(player_data: tuple[float, float, float, float], threshold: float, area_from_player_checked: int) -> dict:
    """Checks for enough poison gas in the specified area around the player and returns a dict with directions."""
    return {"up": 0, "down": 0, "left": 0, "right": 0}

def is_path_blocked(
    player_box: Tuple[float, float, float, float],
    move_direction: str,
    walls_list: List[List[float]],
    distance: Optional[float] = None
) -> bool:
    """Checks if the player's 53px-radius hit circle would collide with walls while moving."""
    return False

def is_enemy_hittable(
    player_pos: Tuple[float, float],
    enemy_pos: Tuple[float, float],
    walls_list: List[List[float]],
    skill_type: str
) -> bool:
    """Checks if there's a clear line of sight to the enemy for the given skill type."""
    return False

def rotate_movement(move_str: str, angle_radian: float) -> str:
    """Rotates the movement keys by a given angle in radians."""
    return ""
