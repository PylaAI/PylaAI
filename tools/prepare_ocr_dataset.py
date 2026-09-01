#!/usr/bin/env python3
"""Prepare collected OCR captures for a lightweight brawler-name model."""

from __future__ import annotations

import argparse
import csv
import difflib
import json
from collections import Counter, defaultdict
from pathlib import Path

import cv2
import numpy as np


CARD_NAME_RIGHT_EDGES = (500, 930, 1360)
CARD_NAME_RIGHT_EDGE_TOLERANCE = 45
LOCKED_CARD_NAME_LEFT_EDGES = (177, 606, 1037)
LOCKED_CARD_NAME_LEFT_EDGE_TOLERANCE = 45


def normalize_text(value: str) -> str:
    return "".join(character for character in str(value).casefold() if character.isalnum())


def load_name_maps(names_path: Path):
    names = json.loads(names_path.read_text(encoding="utf-8"))
    alias_labels: dict[str, set[str]] = defaultdict(set)

    for label, aliases in names.items():
        alias_labels[normalize_text(label)].add(label)
        for alias in aliases:
            alias_labels[normalize_text(alias)].add(label)

    return names, alias_labels


def card_name_candidate(detection: dict) -> bool:
    text = str(detection.get("text", ""))
    if not any(character.isalpha() for character in text):
        return False

    bbox = detection.get("bbox") or []
    if len(bbox) != 4:
        return False

    xs = [float(point[0]) for point in bbox]
    ys = [float(point[1]) for point in bbox]
    width = max(xs) - min(xs)
    height = max(ys) - min(ys)
    left_edge = min(xs)
    right_edge = max(xs)

    aligned_with_unlocked_card = any(
        abs(right_edge - expected_edge) <= CARD_NAME_RIGHT_EDGE_TOLERANCE
        for expected_edge in CARD_NAME_RIGHT_EDGES
    )
    aligned_with_locked_card = any(
        abs(left_edge - expected_edge) <= LOCKED_CARD_NAME_LEFT_EDGE_TOLERANCE
        for expected_edge in LOCKED_CARD_NAME_LEFT_EDGES
    )
    return (aligned_with_unlocked_card or aligned_with_locked_card) and 15 <= width <= 240 and 18 <= height <= 70


def match_label(text: str, names: dict, alias_labels: dict[str, set[str]]):
    normalized = normalize_text(text)
    exact_labels = alias_labels.get(normalized, set())
    if len(exact_labels) == 1:
        return next(iter(exact_labels)), "exact", 1.0, None, 0.0

    ranked = sorted(
        (
            (difflib.SequenceMatcher(None, normalized, normalize_text(label)).ratio(), label)
            for label in names
        ),
        reverse=True,
    )
    best_score, best_label = ranked[0]
    second_score, second_label = ranked[1]
    margin = best_score - second_score

    if len(normalized) >= 3 and best_score >= 0.84 and margin >= 0.12:
        return best_label, "fuzzy", best_score, second_label, second_score
    return None, "rejected", best_score, best_label, second_score


def crop_detection(image: np.ndarray, bbox: list, padding_x: int = 8, padding_y: int = 6):
    xs = [float(point[0]) for point in bbox]
    ys = [float(point[1]) for point in bbox]
    x1 = max(0, int(min(xs)) - padding_x)
    y1 = max(0, int(min(ys)) - padding_y)
    x2 = min(image.shape[1], int(max(xs)) + padding_x + 1)
    y2 = min(image.shape[0], int(max(ys)) + padding_y + 1)
    return image[y1:y2, x1:x2], [x1, y1, x2, y2]


def write_csv(path: Path, rows: list[dict], fieldnames: list[str]):
    with path.open("w", encoding="utf-8", newline="") as output_file:
        writer = csv.DictWriter(output_file, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def create_contact_sheet(entries: list[dict], output_dir: Path, output_path: Path, columns: int = 5):
    if not entries:
        return

    tile_width = 250
    tile_height = 92
    crop_height = 56
    rows = (len(entries) + columns - 1) // columns
    sheet = np.full((rows * tile_height, columns * tile_width, 3), 28, dtype=np.uint8)

    for index, entry in enumerate(entries):
        crop = cv2.imread(str(output_dir / entry["crop_path"]))
        if crop is None or crop.size == 0:
            continue

        scale = min((tile_width - 12) / crop.shape[1], crop_height / crop.shape[0])
        resized = cv2.resize(
            crop,
            (max(1, int(crop.shape[1] * scale)), max(1, int(crop.shape[0] * scale))),
            interpolation=cv2.INTER_AREA if scale < 1 else cv2.INTER_CUBIC,
        )
        row, column = divmod(index, columns)
        x = column * tile_width + 6
        y = row * tile_height + 4
        sheet[y:y + resized.shape[0], x:x + resized.shape[1]] = resized

        label = entry.get("label") or f"? {entry.get('suggested_label', '')}"
        source_text = entry.get("source_text", "")
        caption = f"{label} | OCR: {source_text}"[:36]
        cv2.putText(
            sheet,
            caption,
            (column * tile_width + 6, row * tile_height + 80),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.42,
            (235, 235, 235),
            1,
            cv2.LINE_AA,
        )

    cv2.imwrite(str(output_path), sheet, [cv2.IMWRITE_JPEG_QUALITY, 92])


def prepare_dataset(source_dir: Path, names_path: Path, output_dir: Path):
    if output_dir.exists() and any(output_dir.iterdir()):
        raise FileExistsError(
            f"Output directory is not empty: {output_dir}. Choose another directory to preserve previous results."
        )

    accepted_dir = output_dir / "crops"
    rejected_dir = output_dir / "rejected_crops"
    accepted_dir.mkdir(parents=True, exist_ok=True)
    rejected_dir.mkdir(parents=True, exist_ok=True)

    names, alias_labels = load_name_maps(names_path)
    metadata_files = sorted((source_dir / "metadata").glob("*.json"))
    accepted_rows = []
    rejected_rows = []
    run_id = 0

    for metadata_path in metadata_files:
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        if int(metadata.get("attempt", 0)) == 0:
            run_id += 1
        split = "validation" if run_id % 2 == 0 else "train"

        image_path = source_dir / metadata["image"]
        image = cv2.imread(str(image_path))
        if image is None:
            raise FileNotFoundError(f"Could not read source image: {image_path}")

        for detection_index, detection in enumerate(metadata.get("detections", [])):
            if not card_name_candidate(detection):
                continue

            source_text = str(detection.get("text", ""))
            label, match_type, score, second_label, second_score = match_label(
                source_text,
                names,
                alias_labels,
            )
            crop, crop_bbox = crop_detection(image, detection["bbox"])
            if crop.size == 0:
                continue

            crop_name = f"{metadata_path.stem}_{detection_index:02d}.png"
            common = {
                "crop_path": "",
                "source_sample": metadata_path.stem,
                "source_image": metadata["image"],
                "run_id": run_id,
                "split": split,
                "target_brawler": metadata.get("target_brawler"),
                "source_text": source_text,
                "ocr_confidence": float(detection.get("confidence", 0.0)),
                "match_score": score,
                "second_label": second_label or "",
                "second_score": second_score,
                "crop_bbox": json.dumps(crop_bbox),
                "ocr_bbox": json.dumps(detection["bbox"]),
            }

            if label:
                label_dir = accepted_dir / label
                label_dir.mkdir(parents=True, exist_ok=True)
                crop_path = label_dir / crop_name
                cv2.imwrite(str(crop_path), crop)
                accepted_rows.append({
                    **common,
                    "crop_path": crop_path.relative_to(output_dir).as_posix(),
                    "label": label,
                    "match_type": match_type,
                })
            else:
                crop_path = rejected_dir / crop_name
                cv2.imwrite(str(crop_path), crop)
                rejected_rows.append({
                    **common,
                    "crop_path": crop_path.relative_to(output_dir).as_posix(),
                    "suggested_label": second_label or "",
                    "match_type": match_type,
                })

    train_labels = {row["label"] for row in accepted_rows if row["split"] == "train"}
    validation_labels = {row["label"] for row in accepted_rows if row["split"] == "validation"}
    for missing_label in validation_labels - train_labels:
        next(
            row for row in accepted_rows
            if row["label"] == missing_label and row["split"] == "validation"
        )["split"] = "train"

    manifest_fields = [
        "crop_path", "label", "match_type", "source_sample", "source_image", "run_id", "split",
        "target_brawler", "source_text", "ocr_confidence", "match_score", "second_label", "second_score",
        "crop_bbox", "ocr_bbox",
    ]
    rejected_fields = [
        "crop_path", "suggested_label", "match_type", "source_sample", "source_image", "run_id", "split",
        "target_brawler", "source_text", "ocr_confidence", "match_score", "second_label", "second_score",
        "crop_bbox", "ocr_bbox",
    ]
    write_csv(output_dir / "manifest.csv", accepted_rows, manifest_fields)
    write_csv(output_dir / "rejected_manifest.csv", rejected_rows, rejected_fields)
    create_contact_sheet(accepted_rows, output_dir, output_dir / "contact_sheet.jpg")
    create_contact_sheet(rejected_rows, output_dir, output_dir / "rejected_contact_sheet.jpg")
    representative_rows = []
    represented_labels = set()
    for row in sorted(accepted_rows, key=lambda item: item["label"]):
        if row["label"] not in represented_labels:
            representative_rows.append(row)
            represented_labels.add(row["label"])
    create_contact_sheet(representative_rows, output_dir, output_dir / "label_overview.jpg")

    label_counts = Counter(row["label"] for row in accepted_rows)
    split_counts = Counter(row["split"] for row in accepted_rows)
    labels_by_split = defaultdict(set)
    for row in accepted_rows:
        labels_by_split[row["split"]].add(row["label"])

    summary = {
        "source_samples": len(metadata_files),
        "runs": run_id,
        "accepted_crops": len(accepted_rows),
        "rejected_candidates": len(rejected_rows),
        "labels": len(label_counts),
        "label_counts": dict(sorted(label_counts.items())),
        "split_counts": dict(split_counts),
        "labels_missing_from_train": sorted(labels_by_split["validation"] - labels_by_split["train"]),
        "labels_missing_from_validation": sorted(labels_by_split["train"] - labels_by_split["validation"]),
    }
    (output_dir / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return summary


def parse_args():
    project_root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=project_root / "ocr_dataset")
    parser.add_argument("--names", type=Path, default=project_root / "cfg" / "names.json")
    parser.add_argument("--output", type=Path, default=project_root / "ocr_dataset" / "prepared")
    return parser.parse_args()


def main():
    args = parse_args()
    summary = prepare_dataset(args.source.resolve(), args.names.resolve(), args.output.resolve())
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
