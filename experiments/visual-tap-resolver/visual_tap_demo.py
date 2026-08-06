#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from statistics import mean, median

import cv2
import numpy as np

from resolver import ResolverConfig, render_overlay, resolve_image, serializable_result


def write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def resolve_command(args: argparse.Namespace) -> int:
    output_dir = Path(args.output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    config = ResolverConfig(max_side=args.max_side, max_blocks=args.max_blocks)
    result = resolve_image(Path(args.input), config)
    serializable = serializable_result(result)
    write_json(output_dir / "blocks.json", serializable)
    roots = set(result["rootBlockIds"])
    root_blocks = [block for block in result["blocks"] if block["blockId"] in roots]
    overlay = render_overlay(result["_source"], root_blocks)
    cv2.imwrite(str(output_dir / "overlay.png"), overlay)
    cv2.imwrite(
        str(output_dir / "overlay-all.png"),
        render_overlay(result["_source"], result["blocks"]),
    )
    if args.write_masks:
        masks_dir = output_dir / "masks"
        masks_dir.mkdir(exist_ok=True)
        for block_id, (mask, _) in result["_masks"].items():
            cv2.imwrite(str(masks_dir / f"{block_id}.png"), mask)
    print(f"BLOCKS={len(result['blocks'])}")
    print(f"ROOT_BLOCKS={len(root_blocks)}")
    print(f"TOTAL_MS={result['timingMs']['total']}")
    print(f"JSON={output_dir / 'blocks.json'}")
    print(f"OVERLAY={output_dir / 'overlay.png'}")
    print(f"OVERLAY_ALL={output_dir / 'overlay-all.png'}")
    return 0


def benchmark_command(args: argparse.Namespace) -> int:
    config = ResolverConfig(max_side=args.max_side, max_blocks=args.max_blocks)
    totals: list[float] = []
    stages: dict[str, list[float]] = {}
    for _ in range(args.iterations):
        result = resolve_image(Path(args.input), config)
        totals.append(float(result["timingMs"]["total"]))
        for name, value in result["timingMs"].items():
            stages.setdefault(name, []).append(float(value))
    ordered = sorted(totals)
    p95 = ordered[min(len(ordered) - 1, max(0, round(len(ordered) * 0.95) - 1))]
    summary = {
        "iterations": args.iterations,
        "totalMs": {
            "mean": round(mean(totals), 3),
            "median": round(median(totals), 3),
            "p95": round(p95, 3),
            "min": round(min(totals), 3),
            "max": round(max(totals), 3),
        },
        "stageMeanMs": {name: round(mean(values), 3) for name, values in stages.items()},
        "note": "local algorithm only; screenshot acquisition, dump acquisition, and LLM latency excluded",
    }
    if args.reference_dump_ms is not None:
        summary["referenceDumpMs"] = args.reference_dump_ms
        summary["localVsReferenceSpeedup"] = round(args.reference_dump_ms / mean(totals), 3)
        summary["referenceWarning"] = (
            "reference value is user-supplied; it is comparable only when captured on the same page and path"
        )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


def synthetic_command(args: argparse.Namespace) -> int:
    output_dir = Path(args.output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    width, height = 540, 1200
    image = np.full((height, width, 3), (244, 244, 244), np.uint8)
    ground_truth: list[dict[str, object]] = []

    cv2.rectangle(image, (0, 0), (width, 82), (38, 38, 38), -1)
    for index, center in enumerate([(46, 41), (445, 41), (500, 41)], start=1):
        cv2.circle(image, center, 17, (235, 235, 235), 3)
        ground_truth.append({"id": f"top-{index}", "bbox": [center[0] - 24, 12, 48, 58]})

    row_top = 125
    for index in range(5):
        y = row_top + index * 132
        cv2.rectangle(image, (18, y), (522, y + 108), (255, 255, 255), -1)
        cv2.rectangle(image, (18, y), (522, y + 108), (214, 214, 214), 2)
        color = [(74, 176, 70), (229, 152, 47), (76, 118, 231), (202, 80, 181), (78, 182, 191)][index]
        cv2.circle(image, (72, y + 54), 28, color, -1)
        cv2.rectangle(image, (124, y + 28), (360, y + 43), (100, 100, 100), -1)
        cv2.rectangle(image, (124, y + 60), (430, y + 74), (175, 175, 175), -1)
        cv2.polylines(image, [np.array([[485, y + 42], [497, y + 54], [485, y + 66]])], False, (120, 120, 120), 3)
        ground_truth.append({"id": f"row-{index + 1}", "bbox": [18, y, 504, 108]})

    nav_y = 1080
    cv2.rectangle(image, (0, nav_y), (width, height), (255, 255, 255), -1)
    for index, center_x in enumerate([68, 202, 338, 472], start=1):
        cv2.circle(image, (center_x, 1124), 21, (50 + index * 34, 180, 110 + index * 20), -1)
        cv2.rectangle(image, (center_x - 30, 1161), (center_x + 30, 1171), (130, 130, 130), -1)
        ground_truth.append({"id": f"tab-{index}", "bbox": [center_x - 48, 1090, 96, 94]})

    cv2.imwrite(str(output_dir / "screen.png"), image)
    write_json(
        output_dir / "ground-truth.json",
        {"resolution": [width, height], "hitRegions": ground_truth},
    )
    print(f"SCREEN={output_dir / 'screen.png'}")
    print(f"GROUND_TRUTH={output_dir / 'ground-truth.json'}")
    return 0


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(description="Offline visual tap resolver demo")
    subparsers = root.add_subparsers(dest="command", required=True)

    resolve = subparsers.add_parser("resolve", help="resolve visual blocks from a screenshot")
    resolve.add_argument("--input", required=True)
    resolve.add_argument("--output-dir", required=True)
    resolve.add_argument("--max-side", type=int, default=1280)
    resolve.add_argument("--max-blocks", type=int, default=256)
    resolve.add_argument("--write-masks", action="store_true")
    resolve.set_defaults(func=resolve_command)

    benchmark = subparsers.add_parser("benchmark", help="benchmark local resolve only")
    benchmark.add_argument("--input", required=True)
    benchmark.add_argument("--iterations", type=int, default=20)
    benchmark.add_argument("--max-side", type=int, default=1280)
    benchmark.add_argument("--max-blocks", type=int, default=256)
    benchmark.add_argument("--reference-dump-ms", type=float)
    benchmark.set_defaults(func=benchmark_command)

    synthetic = subparsers.add_parser("synthetic", help="generate a deterministic phone UI fixture")
    synthetic.add_argument("--output-dir", required=True)
    synthetic.set_defaults(func=synthetic_command)
    return root


if __name__ == "__main__":
    arguments = parser().parse_args()
    raise SystemExit(arguments.func(arguments))
