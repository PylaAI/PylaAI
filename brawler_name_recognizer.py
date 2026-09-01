"""Lightweight brawler-name recognition without EasyOCR or Torch."""

from __future__ import annotations

import json
import threading
from pathlib import Path

import cv2
import numpy as np
import onnxruntime as ort


REFERENCE_WIDTH = 1536
REFERENCE_HEIGHT = 864
INPUT_WIDTH = 192
INPUT_HEIGHT = 48
UNLOCKED_RIGHT_EDGES = (500, 930, 1360)
LOCKED_LEFT_EDGES = (177, 606, 1037)


class BrawlerNameRecognizer:
    """Locate fixed-layout name strips and classify them with a tiny ONNX model."""

    def __init__(self, model_path: Path, labels_path: Path, confidence_threshold: float = 0.70):
        self.model_path = Path(model_path)
        self.labels_path = Path(labels_path)
        self.confidence_threshold = confidence_threshold
        self._session = None
        self._labels = None
        self._lock = threading.Lock()

    def _ensure_loaded(self):
        if self._session is not None:
            return
        with self._lock:
            if self._session is not None:
                return
            if not self.model_path.is_file():
                raise FileNotFoundError(f"Missing brawler-name model: {self.model_path}")
            if not self.labels_path.is_file():
                raise FileNotFoundError(f"Missing brawler-name labels: {self.labels_path}")
            self._labels = json.loads(self.labels_path.read_text(encoding="utf-8"))
            self._session = ort.InferenceSession(
                str(self.model_path),
                providers=["CPUExecutionProvider"],
            )

    @staticmethod
    def _vertical_runs(mask: np.ndarray):
        active = ((mask > 0).sum(axis=1) >= 3).astype(np.uint8).reshape(-1, 1)
        active = cv2.morphologyEx(
            active,
            cv2.MORPH_CLOSE,
            np.ones((11, 1), dtype=np.uint8),
        ).ravel()
        changes = np.diff(np.concatenate(([0], active, [0])).astype(np.int16))
        starts = np.where(changes == 1)[0]
        stops = np.where(changes == -1)[0]
        return [(int(start), int(stop - 1)) for start, stop in zip(starts, stops) if stop - start >= 70]

    @classmethod
    def _unlocked_rows(cls, image_rgb: np.ndarray):
        hsv = cv2.cvtColor(image_rgb, cv2.COLOR_RGB2HSV)
        candidates = []
        for x in (505, 936, 1365):
            strip = hsv[:, x - 12:x + 13]
            cyan = cv2.inRange(strip, np.array([80, 100, 130]), np.array([105, 255, 255]))
            for start, end in cls._vertical_runs(cyan):
                candidates.extend((start + 215, end - 104))

        candidates = sorted(center for center in candidates if 75 <= center <= 850)
        clusters = []
        for center in candidates:
            if not clusters or center - clusters[-1][-1] > 30:
                clusters.append([center])
            else:
                clusters[-1].append(center)
        centers = [
            (int(round(float(np.median(cluster)))), len(cluster))
            for cluster in clusters
        ]
        if not centers:
            return []

        # Real card rows repeat every 360 px. A partial cyan border can suggest a
        # second, incorrect center; keep the most strongly supported row lattice.
        best_group = None
        best_score = None
        for seed, _ in centers:
            group = [
                item for item in centers
                if abs(abs(item[0] - seed) - round(abs(item[0] - seed) / 360) * 360) <= 22
            ]
            score = (len(group), sum(min(support, 3) for _, support in group))
            if best_score is None or score > best_score:
                best_group = group
                best_score = score
        return [center for center, _ in best_group]

    @staticmethod
    def _locked_names(image_rgb: np.ndarray):
        hsv = cv2.cvtColor(image_rgb, cv2.COLOR_RGB2HSV)
        white = cv2.inRange(hsv, np.array([0, 0, 175]), np.array([179, 115, 255]))
        white = cv2.morphologyEx(
            white,
            cv2.MORPH_CLOSE,
            np.ones((3, 11), dtype=np.uint8),
        )
        white = cv2.dilate(white, np.ones((3, 5), dtype=np.uint8))
        candidates = []
        contours = cv2.findContours(white, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)[0]
        for contour in contours:
            x, y, width, height = cv2.boundingRect(contour)
            if not (12 <= height <= 65 and 12 <= width <= 230 and y > 45):
                continue
            left_edge = min(LOCKED_LEFT_EDGES, key=lambda edge: abs(x - edge))
            if abs(x - left_edge) <= 65:
                candidates.append((left_edge, int(round(y + height / 2))))
        return candidates

    @staticmethod
    def _fixed_crop(image_rgb: np.ndarray, anchor: int, center_y: int, unlocked: bool):
        if unlocked:
            x1, x2 = anchor - 220, anchor + 8
        else:
            x1, x2 = anchor - 8, anchor + 220
        y1, y2 = center_y - 32, center_y + 32
        crop = image_rgb[max(0, y1):min(REFERENCE_HEIGHT, y2), max(0, x1):min(REFERENCE_WIDTH, x2)]
        if crop.shape[:2] != (64, 228):
            padded = np.zeros((64, 228, 3), dtype=np.uint8)
            target_y = max(0, -y1)
            target_x = max(0, -x1)
            padded[target_y:target_y + crop.shape[0], target_x:target_x + crop.shape[1]] = crop
            crop = padded
        gray = cv2.cvtColor(crop, cv2.COLOR_RGB2GRAY)
        gray = cv2.resize(gray, (INPUT_WIDTH, INPUT_HEIGHT), interpolation=cv2.INTER_AREA)
        return gray.astype(np.float32) / 255.0

    def recognize(self, image_rgb: np.ndarray):
        self._ensure_loaded()
        source_height, source_width = image_rgb.shape[:2]
        if (source_width, source_height) != (REFERENCE_WIDTH, REFERENCE_HEIGHT):
            reference = cv2.resize(
                image_rgb,
                (REFERENCE_WIDTH, REFERENCE_HEIGHT),
                interpolation=cv2.INTER_AREA,
            )
        else:
            reference = image_rgb

        candidates = []
        for center_y in self._unlocked_rows(reference):
            for right_edge in UNLOCKED_RIGHT_EDGES:
                candidates.append({
                    "anchor": right_edge,
                    "center_y": center_y,
                    "unlocked": True,
                    "card_center_x": right_edge - 170,
                })
        for left_edge, center_y in self._locked_names(reference):
            candidates.append({
                "anchor": left_edge,
                "center_y": center_y,
                "unlocked": False,
                "card_center_x": left_edge + 153,
            })
        if not candidates:
            return {}

        batch = np.stack([
            self._fixed_crop(reference, item["anchor"], item["center_y"], item["unlocked"])
            for item in candidates
        ])[:, np.newaxis, :, :]
        logits = self._session.run(None, {"image": batch})[0]
        logits -= logits.max(axis=1, keepdims=True)
        probabilities = np.exp(logits)
        probabilities /= probabilities.sum(axis=1, keepdims=True)

        scale_x = source_width / REFERENCE_WIDTH
        scale_y = source_height / REFERENCE_HEIGHT
        results = {}
        for item, scores in zip(candidates, probabilities):
            label_index = int(scores.argmax())
            confidence = float(scores[label_index])
            if confidence < self.confidence_threshold:
                continue
            label = self._labels[label_index]
            center_x = item["card_center_x"] * scale_x
            center_y = item["center_y"] * scale_y
            half_height = 32 * scale_y
            if item["unlocked"]:
                box_left = (item["anchor"] - 220) * scale_x
                box_right = (item["anchor"] + 8) * scale_x
            else:
                box_left = (item["anchor"] - 8) * scale_x
                box_right = (item["anchor"] + 220) * scale_x
            details = {
                "text": label,
                "confidence": confidence,
                "locked": not item["unlocked"],
                "top_left": [box_left, center_y - half_height],
                "top_right": [box_right, center_y - half_height],
                "bottom_right": [box_right, center_y + half_height],
                "bottom_left": [box_left, center_y + half_height],
                "center": (center_x, center_y),
            }
            if label not in results or confidence > results[label]["confidence"]:
                results[label] = details
        return results
