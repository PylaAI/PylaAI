import os
import secrets
import time
import requests
from utils import load_toml_as_dict, save_dict_as_toml, api_base_url, hash_playstyle, PYLA_VERSION, resolve_project_path
import pandas as pd
from enum import Enum
from dataclasses import dataclass
from typing import Optional
from datetime import datetime


class GameMode(Enum):
    CLASSIC = "classic"
    TRIO_SHOWDOWN = "trio_showdown"


class MatchResult(Enum):
    VICTORY = "victory"
    DRAW = "draw"
    DEFEAT = "defeat"


@dataclass
class ParsedGameResult:
    gamemode: GameMode
    result: MatchResult
    place: Optional[int] = None
    raw_string: str = ""


class TrophyObserver:

    @staticmethod
    def _replace_when_available(source, destination):
        """Replace destination once Windows releases any external file lock."""
        retry_delay = 0.1
        waiting = False

        while True:
            try:
                os.replace(source, destination)
                if waiting:
                    print(f"File lock released; saved {destination.name}.")
                return
            except PermissionError as error:
                if not waiting:
                    print(
                        f"Waiting for {destination.name} to become writable "
                        f"({error})..."
                    )
                    waiting = True
                time.sleep(retry_delay)
                retry_delay = min(retry_delay * 2, 2.0)

    def __init__(self):
        self.history_file = resolve_project_path("cfg", "match_history.csv")
        
        self.current_trophies = None
        self.current_wins = None
        self.match_history = self.load_history()
        self.last_sent_index = len(self.match_history)
        self.win_streak = 0
        self.match_counter = 0  # New counter for the number of matches
        self.trophy_lose_ranges = [(49, 0), (299, 1), (599, 2), (799, 3), (999, 4), (1099, 5), (1199, 6), (1299, 7),
                                   (1499, 8), (1799, 9), (3999, 10), (float("inf"), 15)]
        self.trophy_win_ranges = [(1999, 10), (2499, 8), (2799, 6), (2999, 4), (3099, 2), (float("inf"), 1)]
        self.showdown_trio_ranges = [
            (49, (11, 5, 5, 5)),
            (99, (11, 5, 4, -1)),
            (199, (11, 5, 3, -1)),
            (299, (11, 5, 2, -1)),
            (499, (11, 5, 2, -2)),
            (599, (11, 5, 1, -2)),
            (799, (11, 5, 1, -3)),
            (999, (11, 5, 1, -4)),
            (1099, (11, 5, 0, -6)),
            (1199, (11, 5, 0, -7)),
            (1299, (11, 5, 0, -8)),
            (1499, (11, 5, 0, -9)),
            (1799, (11, 5, -5, -10)),
            (1999, (11, 5, -5, -11)),
            (2199, (9, 4, -5, -11)),
            (float("inf"), (9, 4, -5, -11)),
        ]
        self.trophies_multiplier = int(load_toml_as_dict("./cfg/general_config.toml")["trophies_multiplier"])

    def win_streak_gain(self):
        return min(self.win_streak - 1, 10) if self.current_trophies < 2000 else 0

    def calc_lost_decrement(self):
        for max_trophies, loss in self.trophy_lose_ranges:
            if float(self.current_trophies) <= float(max_trophies):
                return loss
        raise ValueError("Current trophies exceed all defined ranges")

    def calc_win_increment(self):
        for max_trophies, gain in self.trophy_win_ranges:
            if float(self.current_trophies) <= float(max_trophies):
                return gain * self.trophies_multiplier + self.win_streak_gain()
        raise ValueError("Current trophies exceed all defined ranges")

    def calc_showdown_delta(self, place):
        for max_trophies, deltas in self.showdown_trio_ranges:
            if float(self.current_trophies) <= float(max_trophies):
                return deltas[place] * self.trophies_multiplier + (self.win_streak_gain() if place < 2 else 0)
        raise ValueError("Current trophies exceed all defined ranges")

    def load_history(self):
        if os.path.exists(self.history_file):
            history = pd.read_csv(self.history_file)
        else:
            history = pd.DataFrame(
                columns=["date_time", "brawler_name", "result", "current_trophies", "trophy_delta", "new_winstreak",
                         "playstyle_hash", "playstyle_name", "playstyle_gamemodes", "playstyle_brawlers",
                         "pyla_version", "power_level"])
        return history

    def save_history(self):
        self.history_file.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.history_file.with_name(
            f".{self.history_file.name}.{secrets.token_hex(8)}.tmp"
        )
        try:
            self.match_history.to_csv(temporary, index=False)
            with open(temporary, "r+b") as handle:
                handle.flush()
                os.fsync(handle.fileno())
            self._replace_when_available(temporary, self.history_file)
        finally:
            if temporary.exists():
                temporary.unlink()


    def parse_game_result(self, raw_result: str) -> ParsedGameResult:
        """Parses raw game result string into a structured data class."""
        print(f"Found game result: {raw_result}")
        if "showdown" in raw_result:
            place = int(raw_result.split("_")[-1])
            gamemode = GameMode.TRIO_SHOWDOWN if "trio_showdown" in raw_result else GameMode.CLASSIC

            if place < 2:
                result = MatchResult.VICTORY
            elif place == 2:
                if self.current_trophies is not None:
                    try:
                        delta = self.calc_showdown_delta(place)
                        if delta < 0:
                            result = MatchResult.DEFEAT
                        else:
                            result = MatchResult.DRAW
                    except Exception as e:
                        print(f"Error calculating showdown delta for place {place}: {e}")
                        result = MatchResult.DRAW
                else:
                    result = MatchResult.DRAW
            else:
                result = MatchResult.DEFEAT

            return ParsedGameResult(gamemode=gamemode, result=result, place=place, raw_string=raw_result)
        else:
            result_map = {
                "victory": MatchResult.VICTORY,
                "draw": MatchResult.DRAW,
                "defeat": MatchResult.DEFEAT
            }
            return ParsedGameResult(
                gamemode=GameMode.CLASSIC,
                result=result_map.get(raw_result, MatchResult.DEFEAT),
                place=None,
                raw_string=raw_result
            )

    def add_trophies(self, parsed_result: ParsedGameResult, current_brawler, playstyle_info, power_level=None):
        old_trophies = self.current_trophies
        old_win_streak = self.win_streak

        if parsed_result.result == MatchResult.VICTORY:
            self.win_streak += 1
            if parsed_result.place is not None:
                trophy_delta = self.calc_showdown_delta(parsed_result.place)
            else:
                trophy_delta = self.calc_win_increment()
        elif parsed_result.result == MatchResult.DEFEAT:
            self.win_streak = 0
            if parsed_result.place is not None:
                trophy_delta = self.calc_showdown_delta(parsed_result.place)
            else:
                trophy_delta = -self.calc_lost_decrement()
        elif parsed_result.result == MatchResult.DRAW:
            if parsed_result.place is not None:
                trophy_delta = self.calc_showdown_delta(parsed_result.place)
            else:
                print("Nothing changed. Draw detected")
                trophy_delta = 0
        else:
            print("Catastrophic failure")
            trophy_delta = 0
        if self.current_trophies >= 1000 and self.current_trophies + trophy_delta < 1000:
            self.current_trophies = 1000
        elif self.current_trophies >= 2000 and self.current_trophies + trophy_delta < 2000:
            self.current_trophies = 2000
        else:
            self.current_trophies += trophy_delta

        print(f"Trophies: {old_trophies} -> {self.current_trophies}")
        print(f"Win Streak: {old_win_streak} -> {self.win_streak}")
        if self.current_wins:
            print(f"Current Wins: {self.current_wins}")

        self.match_history.loc[len(self.match_history)] = [datetime.now().isoformat(), current_brawler,
                                                           parsed_result.result.value, old_trophies, trophy_delta,
                                                           self.win_streak, hash_playstyle(playstyle_info),
                                                           playstyle_info["name"],
                                                           "|".join(playstyle_info["gamemodes"]),
                                                           "|".join(playstyle_info["brawlers"]), PYLA_VERSION,
                                                           (power_level if power_level is not None else -1)]
        self.match_counter += 1
        self.send_results_to_api()
        self.save_history()

    def add_win(self, parsed_result: ParsedGameResult):
        if parsed_result.result == MatchResult.VICTORY:
            self.current_wins += 1
        print("Current wins:", self.current_wins)

    def change_trophies(self, new):
        print(f"Trophies changed from {self.current_trophies} to {new}")
        self.current_trophies = new

    def send_results_to_api(self):
        new_matches = self.match_history.iloc[self.last_sent_index:]
        if new_matches.empty:
            return
        payload = new_matches.to_dict(orient="records")
        if api_base_url != "localhost":
            try:
                response = requests.post(f'https://{api_base_url}/api/matches', json=payload)
                if response.status_code == 200:
                    print("Match history successfully sent to API")
                    self.last_sent_index = len(self.match_history)
                else:
                    print(f"Failed to send match history to API. Status code: {response.status_code}")
            except requests.exceptions.RequestException as e:
                print(f"Error sending match history to API: {e}")