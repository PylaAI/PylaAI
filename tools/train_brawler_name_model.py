#!/usr/bin/env python3
"""Train and export the lightweight brawler-name classifier."""

from __future__ import annotations

import argparse
import csv
import json
import random
import sys
from collections import Counter
from pathlib import Path

import cv2
import numpy as np
import torch
from torch import nn
from torch.utils.data import DataLoader, Dataset, WeightedRandomSampler

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from brawler_name_recognizer import (  # noqa: E402
    BrawlerNameRecognizer,
    LOCKED_LEFT_EDGES,
    UNLOCKED_RIGHT_EDGES,
)


INPUT_WIDTH = 192
INPUT_HEIGHT = 48


def augment(image: np.ndarray, rng: np.random.Generator) -> np.ndarray:
    shift_x = int(rng.integers(-5, 6))
    shift_y = int(rng.integers(-3, 4))
    matrix = np.float32([[1, 0, shift_x], [0, 1, shift_y]])
    image = cv2.warpAffine(
        image,
        matrix,
        (INPUT_WIDTH, INPUT_HEIGHT),
        flags=cv2.INTER_LINEAR,
        borderMode=cv2.BORDER_REFLECT_101,
    )
    contrast = float(rng.uniform(0.85, 1.15))
    brightness = float(rng.uniform(-0.06, 0.06))
    image = np.clip(image * contrast + brightness, 0.0, 1.0)
    if rng.random() < 0.35:
        image = np.clip(image + rng.normal(0.0, 0.015, image.shape), 0.0, 1.0)
    return image.astype(np.float32)


class NameDataset(Dataset):
    def __init__(self, samples: list[tuple[np.ndarray, int]], training: bool, seed: int):
        self.samples = samples
        self.training = training
        self.seed = seed

    def __len__(self):
        return len(self.samples)

    def __getitem__(self, index: int):
        image, label = self.samples[index]
        if self.training:
            rng = np.random.default_rng(self.seed + index + random.randrange(1_000_000))
            image = augment(image, rng)
        tensor = torch.from_numpy(image.copy()).unsqueeze(0)
        return tensor, label


class BrawlerNameClassifier(nn.Module):
    def __init__(self, class_count: int):
        super().__init__()
        self.features = nn.Sequential(
            nn.Conv2d(1, 16, 3, padding=1, bias=False),
            nn.BatchNorm2d(16),
            nn.ReLU(inplace=True),
            nn.MaxPool2d(2),
            nn.Conv2d(16, 32, 3, padding=1, bias=False),
            nn.BatchNorm2d(32),
            nn.ReLU(inplace=True),
            nn.MaxPool2d(2),
            nn.Conv2d(32, 48, 3, padding=1, bias=False),
            nn.BatchNorm2d(48),
            nn.ReLU(inplace=True),
            nn.MaxPool2d(2),
            nn.Conv2d(48, 64, 3, padding=1, bias=False),
            nn.BatchNorm2d(64),
            nn.ReLU(inplace=True),
            nn.AdaptiveAvgPool2d((2, 8)),
        )
        self.classifier = nn.Sequential(
            nn.Flatten(),
            nn.Linear(64 * 2 * 8, 128),
            nn.ReLU(inplace=True),
            nn.Dropout(0.15),
            nn.Linear(128, class_count),
        )

    def forward(self, image):
        return self.classifier(self.features(image))


def load_samples(manifest_path: Path):
    rows = list(csv.DictReader(manifest_path.open(encoding="utf-8")))
    labels = sorted({row["label"] for row in rows})
    label_indices = {label: index for index, label in enumerate(labels)}
    source_root = manifest_path.parent.parent
    image_cache: dict[str, np.ndarray] = {}
    location_cache = {}
    samples = {"train": [], "validation": []}

    for row in rows:
        source_image = row["source_image"]
        if source_image not in image_cache:
            image = cv2.imread(str(source_root / source_image))
            if image is None:
                raise FileNotFoundError(source_root / source_image)
            image_rgb = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
            image_cache[source_image] = image_rgb
            location_cache[source_image] = (
                BrawlerNameRecognizer._unlocked_rows(image_rgb),
                BrawlerNameRecognizer._locked_names(image_rgb),
            )

        bbox = json.loads(row["ocr_bbox"])
        xs = [float(point[0]) for point in bbox]
        ys = [float(point[1]) for point in bbox]
        left, right = min(xs), max(xs)
        annotation_center = int(round((min(ys) + max(ys)) / 2))
        unlocked_edge = min(UNLOCKED_RIGHT_EDGES, key=lambda edge: abs(right - edge))
        locked_edge = min(LOCKED_LEFT_EDGES, key=lambda edge: abs(left - edge))
        unlocked = abs(right - unlocked_edge) <= abs(left - locked_edge)
        unlocked_rows, locked_names = location_cache[source_image]
        if unlocked:
            if not unlocked_rows:
                continue
            center_y = min(unlocked_rows, key=lambda center: abs(center - annotation_center))
            anchor = unlocked_edge
        else:
            same_column = [center for edge, center in locked_names if edge == locked_edge]
            if not same_column:
                continue
            center_y = min(same_column, key=lambda center: abs(center - annotation_center))
            anchor = locked_edge
        if abs(center_y - annotation_center) > 35:
            continue
        crop = BrawlerNameRecognizer._fixed_crop(
            image_cache[source_image], anchor, center_y, unlocked
        )
        label_index = label_indices[row["label"]]
        samples[row["split"]].append((crop, label_index))
        if row["split"] == "train":
            # Locked names are left-aligned and unlocked names are right-aligned.
            # Teach every class both layouts so a newly unlocked brawler does not
            # require a second set of manual annotations.
            alignment_shift = -86 if unlocked else 86
            alternate_alignment = cv2.warpAffine(
                crop,
                np.float32([[1, 0, alignment_shift], [0, 1, 0]]),
                (INPUT_WIDTH, INPUT_HEIGHT),
                flags=cv2.INTER_LINEAR,
                borderMode=cv2.BORDER_REFLECT_101,
            )
            samples["train"].append((alternate_alignment, label_index))
    return samples, labels


def accuracy(model: nn.Module, loader: DataLoader, device: torch.device):
    model.eval()
    correct_1 = correct_3 = total = 0
    mistakes = Counter()
    with torch.inference_mode():
        for images, targets in loader:
            logits = model(images.to(device))
            top3 = logits.topk(3, dim=1).indices.cpu()
            correct_1 += int((top3[:, 0] == targets).sum())
            correct_3 += int((top3 == targets.unsqueeze(1)).any(dim=1).sum())
            total += targets.numel()
            for target, predicted in zip(targets, top3[:, 0]):
                if target != predicted:
                    mistakes[(int(target), int(predicted))] += 1
    return correct_1 / total, correct_3 / total, mistakes


def train(args):
    random.seed(args.seed)
    np.random.seed(args.seed)
    torch.manual_seed(args.seed)
    samples, labels = load_samples(args.manifest)
    expected_labels = set(json.loads(args.names.read_text(encoding="utf-8")))
    actual_labels = set(labels)
    if actual_labels != expected_labels:
        missing = sorted(expected_labels - actual_labels)
        unexpected = sorted(actual_labels - expected_labels)
        raise RuntimeError(
            "Dataset labels do not match cfg/names.json: "
            f"missing={missing}, unexpected={unexpected}"
        )

    train_targets = [label for _, label in samples["train"]]
    counts = Counter(train_targets)
    weights = torch.tensor([1.0 / counts[label] for label in train_targets], dtype=torch.double)
    sampler = WeightedRandomSampler(
        weights,
        num_samples=max(len(train_targets), len(labels) * args.samples_per_class),
        replacement=True,
    )
    train_loader = DataLoader(
        NameDataset(samples["train"], training=True, seed=args.seed),
        batch_size=args.batch_size,
        sampler=sampler,
        num_workers=0,
    )
    validation_loader = DataLoader(
        NameDataset(samples["validation"], training=False, seed=args.seed),
        batch_size=args.batch_size,
        shuffle=False,
        num_workers=0,
    )

    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    model = BrawlerNameClassifier(len(labels)).to(device)
    optimizer = torch.optim.AdamW(model.parameters(), lr=args.learning_rate, weight_decay=1e-4)
    scheduler = torch.optim.lr_scheduler.CosineAnnealingLR(optimizer, T_max=args.epochs)
    criterion = nn.CrossEntropyLoss(label_smoothing=0.03)
    best_accuracy = -1.0
    best_state = None

    print(f"Training on {device}: {len(samples['train'])} train / {len(samples['validation'])} validation")
    for epoch in range(1, args.epochs + 1):
        model.train()
        loss_sum = sample_count = 0
        for images, targets in train_loader:
            images, targets = images.to(device), targets.to(device)
            optimizer.zero_grad(set_to_none=True)
            loss = criterion(model(images), targets)
            loss.backward()
            optimizer.step()
            loss_sum += float(loss) * targets.numel()
            sample_count += targets.numel()
        scheduler.step()

        top1, top3, _ = accuracy(model, validation_loader, device)
        if top1 >= best_accuracy:
            best_accuracy = top1
            best_state = {key: value.detach().cpu().clone() for key, value in model.state_dict().items()}
        if epoch == 1 or epoch % 5 == 0 or epoch == args.epochs:
            print(f"epoch {epoch:03d} loss={loss_sum / sample_count:.4f} val_top1={top1:.4f} val_top3={top3:.4f}")

    model.load_state_dict(best_state)
    model.eval().cpu()
    top1, top3, mistakes = accuracy(model, validation_loader, torch.device("cpu"))
    print(f"best validation: top1={top1:.4f}, top3={top3:.4f}")
    for (expected, predicted), count in mistakes.most_common(15):
        print(f"  {labels[expected]} -> {labels[predicted]}: {count}")

    args.output.parent.mkdir(parents=True, exist_ok=True)
    dummy = torch.zeros(1, 1, INPUT_HEIGHT, INPUT_WIDTH)
    torch.onnx.export(
        model,
        dummy,
        args.output,
        input_names=["image"],
        output_names=["logits"],
        dynamic_axes={"image": {0: "batch"}, "logits": {0: "batch"}},
        opset_version=17,
        dynamo=False,
    )
    labels_path = args.output.with_name(f"{args.output.stem}_labels.json")
    labels_path.write_text(json.dumps(labels, ensure_ascii=False, indent=2), encoding="utf-8")
    summary = {
        "model": str(args.output),
        "labels": str(labels_path),
        "classes": len(labels),
        "parameters": sum(parameter.numel() for parameter in model.parameters()),
        "validation_top1": top1,
        "validation_top3": top3,
        "input_shape": [1, INPUT_HEIGHT, INPUT_WIDTH],
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))


def parse_args():
    project_root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--manifest",
        type=Path,
        default=project_root / "ocr_dataset" / "prepared" / "manifest.csv",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=project_root / "models" / "brawlerNameClassifier.onnx",
    )
    parser.add_argument("--names", type=Path, default=project_root / "cfg" / "names.json")
    parser.add_argument("--epochs", type=int, default=60)
    parser.add_argument("--batch-size", type=int, default=64)
    parser.add_argument("--samples-per-class", type=int, default=12)
    parser.add_argument("--learning-rate", type=float, default=1e-3)
    parser.add_argument("--seed", type=int, default=1337)
    return parser.parse_args()


if __name__ == "__main__":
    train(parse_args())
