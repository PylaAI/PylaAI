"""Restart Brawl Stars when it froze: the screen stays pixel-identical while the capture keeps delivering frames."""
import time

import numpy as np

# The screen stayed exactly the same for this long: Brawl Stars froze (time_tresholds frozen_screen_restart, 0 = off).
FROZEN_SCREEN_RESTART_SECONDS = 60
# How often the check compares the frame with the last one that differed.
FROZEN_SCREEN_SAMPLE_SECONDS = 1.0
# No player seen for this long: Brawl Stars is assumed stuck and restarted (time_tresholds no_detections_restart).
NO_DETECTIONS_RESTART_SECONDS = 5 * 60


def load_threshold(config, name, default):
    """A time_tresholds value, or default when the config file predates the setting (or holds an invalid value)."""
    try:
        return float(config.get(name, default))
    except (TypeError, ValueError):
        return default


class FrozenScreenWatch:
    """Brawl Stars can freeze while the capture keeps delivering frames (an emulator's capture repeats the last image
    on still screens), e.g. stuck at 100% on a loading screen: the bot then presses 'proceed' every few seconds until
    the no-detection restart, minutes later. A running game always moves something (lobby brawler, matchmaking timer,
    the match itself), so a screen that stays strictly identical for `limit` seconds means the game froze."""

    def __init__(self, limit, sample_seconds=FROZEN_SCREEN_SAMPLE_SECONDS):
        self.limit = limit
        self.sample_seconds = sample_seconds
        self.reset()

    def reset(self, t_now=None):
        self.last_frame = None
        self.unchanged_since = time.time() if t_now is None else t_now
        self.last_sample_at = None

    def update(self, frame, t_now):
        """True when the screen has not changed for `limit` seconds."""
        if not self.limit or self.limit <= 0 or frame is None:
            return False
        if self.last_sample_at is not None and t_now - self.last_sample_at < self.sample_seconds:
            return False
        # A long gap between samples means the loop did not watch the screen (pause, stale feed, restart): the time
        # unwatched is not counted as frozen.
        watched = self.last_sample_at is not None and t_now - self.last_sample_at <= max(5.0, 5 * self.sample_seconds)
        self.last_sample_at = t_now
        frame = np.asarray(frame)
        if (not watched or self.last_frame is None or self.last_frame.shape != frame.shape
                or not np.array_equal(self.last_frame, frame)):
            self.last_frame = frame.copy()
            self.unchanged_since = t_now
            return False
        return t_now - self.unchanged_since >= self.limit
