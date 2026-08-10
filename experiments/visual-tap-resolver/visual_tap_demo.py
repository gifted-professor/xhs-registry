#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from statistics import mean, median

import cv2
import numpy as np

from resolver import (  # noqa: E402
    ResolverConfig,
    find_blocks_by_text,
    get_ocr_engine,
    render_overlay,
    resolve_image,
    serializable_result,
)
from vision_contract import (  # noqa: E402
    build_vision_pack,
    file_sha256,
    validate_vision_decision,
    vision_prompt,
)


MAX_BLOCKS_JSON_BYTES = 16 * 1024 * 1024
MAX_PACK_JSON_BYTES = 4 * 1024 * 1024
MAX_DECISION_JSON_BYTES = 64 * 1024


class StrictJsonError(ValueError):
    """A bounded JSON input could not be decoded unambiguously."""


def add_config_args(parser: argparse.ArgumentParser) -> None:
    """A/B switches shared by resolve/find/vision-pack/benchmark (Stage B/C).

    Every flag maps onto a ResolverConfig field, which is part of the manifest
    ``config`` basis -> toggling any of them changes every candidate_manifest_id
    and consumers must re-emit vision packs. The one exception is ``--workers``:
    it maps to the ``refine_workers`` resolve_image keyword argument and never
    touches the manifest.
    """
    parser.add_argument("--weak-control", dest="weak_control", action="store_true", default=True,
                        help="low-contrast control detection (default: on)")
    parser.add_argument("--no-weak-control", dest="weak_control", action="store_false",
                        help="disable low-contrast control detection")
    parser.add_argument("--media-suppress", dest="media_suppression", action="store_true", default=True,
                        help="media-region suppression (default: on)")
    parser.add_argument("--no-media-suppress", dest="media_suppression", action="store_false",
                        help="disable media-region suppression")
    parser.add_argument("--grabcut-iters", type=int, default=None, metavar="N",
                        help="GrabCut iterations (default: resolver default, 3)")
    parser.add_argument("--skip-compact-grabcut", action="store_true",
                        help="skip GrabCut for high-score compact components (B2)")
    parser.add_argument("--compact-score", type=float, default=0.80, metavar="F",
                        help="score threshold for --skip-compact-grabcut (default: 0.80)")
    parser.add_argument("--half-res-media", action="store_true",
                        help="detect media regions at half resolution (media_detection_scale=0.5, C1)")
    parser.add_argument("--grabcut-crop-cap", type=int, default=0, metavar="N",
                        help="downscale GrabCut crops longer than N px (0=off, B4)")
    parser.add_argument("--merge-media", action="store_true",
                        help="merge overlapping media regions (media_merge_iou=0.5, C1)")
    parser.add_argument("--min-component-score", type=float, default=0.0, metavar="F",
                        help="drop kind=component proposals below this score (C1)")
    parser.add_argument("--no-kind-taxonomy", dest="kind_taxonomy", action="store_false", default=True,
                        help="disable icon/button/card kind refinement (C2 A/B)")
    parser.add_argument("--workers", type=int, default=None, metavar="N",
                        help="parallel refine workers; NOT a config field, never affects manifest")


def build_config(args: argparse.Namespace) -> ResolverConfig:
    """Build a config from CLI args, pre-warming the OCR engine when enabled so
    the one-time model load is not attributed to the page resolve."""
    enable_ocr = getattr(args, "ocr", False)
    grabcut_iters = getattr(args, "grabcut_iters", None)
    config = ResolverConfig(
        max_side=args.max_side,
        max_blocks=args.max_blocks,
        enable_ocr=enable_ocr,
        weak_control_detection=getattr(args, "weak_control", True),
        media_suppression=getattr(args, "media_suppression", True),
        grabcut_iterations=grabcut_iters if grabcut_iters is not None else ResolverConfig.grabcut_iterations,
        skip_compact_grabcut=getattr(args, "skip_compact_grabcut", False),
        compact_grabcut_score=getattr(args, "compact_score", ResolverConfig.compact_grabcut_score),
        grabcut_crop_max_side=getattr(args, "grabcut_crop_cap", 0),
        media_detection_scale=0.5 if getattr(args, "half_res_media", False) else 1.0,
        media_merge_iou=0.5 if getattr(args, "merge_media", False) else 0.0,
        min_component_score=getattr(args, "min_component_score", 0.0),
        kind_taxonomy=getattr(args, "kind_taxonomy", True),
    )
    if enable_ocr:
        engine = get_ocr_engine(config.ocr_lang)
        object.__setattr__(config, "ocr_engine", engine)
    return config


def write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _reject_duplicate_json_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    value: dict[str, object] = {}
    for key, item in pairs:
        if key in value:
            raise ValueError(f"duplicate JSON key: {key}")
        value[key] = item
    return value


def read_json_strict(path: Path, *, max_bytes: int) -> object:
    with path.open("rb") as source:
        raw = source.read(max_bytes + 1)
    if len(raw) > max_bytes:
        raise StrictJsonError(
            f"JSON input exceeds {max_bytes} byte limit: {path.name}"
        )
    try:
        return json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=_reject_duplicate_json_keys,
        )
    except (UnicodeError, ValueError, RecursionError) as error:
        raise StrictJsonError(
            f"invalid strict JSON input {path.name}: {error}"
        ) from error


def resolve_command(args: argparse.Namespace) -> int:
    output_dir = Path(args.output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    config = build_config(args)
    result = resolve_image(Path(args.input), config, refine_workers=getattr(args, "workers", None))
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
    if args.json:
        print(json.dumps(serializable, ensure_ascii=False))
        return 0
    print(f"BLOCKS={len(result['blocks'])}")
    print(f"ROOT_BLOCKS={len(root_blocks)}")
    print(f"TOTAL_MS={result['timingMs']['total']}")
    print(f"JSON={output_dir / 'blocks.json'}")
    print(f"OVERLAY={output_dir / 'overlay.png'}")
    print(f"OVERLAY_ALL={output_dir / 'overlay-all.png'}")
    return 0


def find_command(args: argparse.Namespace) -> int:
    """Resolve a screenshot then find blocks by text; never emits a tap."""
    output_dir = Path(args.output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    config = build_config(args)
    result = resolve_image(Path(args.input), config, refine_workers=getattr(args, "workers", None))
    matches = find_blocks_by_text(result, args.text)
    serializable = serializable_result(result)
    payload = {
        "schemaVersion": "visual-tap-find.v1",
        "effect": "none",
        "input": serializable["input"],
        "transform": serializable["transform"],
        "query": args.text,
        "matchCount": len(matches),
        "matches": matches,
    }
    write_json(output_dir / "find.json", payload)
    if args.json:
        print(json.dumps(payload, ensure_ascii=False))
    else:
        print(f"QUERY={args.text}")
        print(f"MATCHES={len(matches)}")
        for match in matches:
            print(
                f"  {match['blockId']} [{match['kind']}] {match['sourceSafePoint']} "
                f"text={match['text']!r}"
            )
        print(f"JSON={output_dir / 'find.json'}")
    return 0 if matches else 1


def vision_pack_command(args: argparse.Namespace) -> int:
    """Generate a frame/query/manifest-bound pack for a block-only Vision call."""

    output_dir = Path(args.output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    config = build_config(args)
    result = resolve_image(Path(args.input), config, refine_workers=getattr(args, "workers", None))
    serializable = serializable_result(result)
    write_json(output_dir / "blocks.json", serializable)

    primary_path = output_dir / "vision-overlay-all.png"
    if not cv2.imwrite(str(primary_path), render_overlay(result["_source"], result["blocks"])):
        raise OSError(f"unable to write overlay: {primary_path}")

    primary_overlay = {
        "file": primary_path.name,
        "sha256": file_sha256(primary_path),
        "visibleBlockIds": [block["blockId"] for block in result["blocks"]],
    }
    pack = build_vision_pack(
        serializable,
        args.query,
        primary_overlay=primary_overlay,
    )
    write_json(output_dir / "vision-pack.json", pack)
    (output_dir / "vision-prompt.txt").write_text(
        vision_prompt(pack) + "\n", encoding="utf-8", newline="\n"
    )

    if args.json:
        print(json.dumps(pack, ensure_ascii=False))
    else:
        print(f"FRAME_ID={pack['frame']['frameId']}")
        print(f"MANIFEST_ID={pack['manifestId']}")
        print(f"SELECTION_REQUEST_ID={pack['selectionRequestId']}")
        print(f"CANDIDATES={pack['candidateCount']}")
        print(f"PACK={output_dir / 'vision-pack.json'}")
        print(f"PROMPT={output_dir / 'vision-prompt.txt'}")
        print(f"OVERLAY={primary_path}")
    return 0


def select_command(args: argparse.Namespace) -> int:
    """Validate one block-only Vision decision; never emits or performs a tap."""

    output_path = Path(args.output).resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        blocks = read_json_strict(
            Path(args.blocks), max_bytes=MAX_BLOCKS_JSON_BYTES
        )
        pack = read_json_strict(Path(args.pack), max_bytes=MAX_PACK_JSON_BYTES)
        decision = read_json_strict(
            Path(args.decision), max_bytes=MAX_DECISION_JSON_BYTES
        )
    except (OSError, StrictJsonError) as error:
        payload = {
            "schemaVersion": "visual-tap-verified-point.v1",
            "effect": "none",
            "ok": False,
            "tapAuthorized": False,
            "error": {"code": "INPUT_READ_FAILED", "message": str(error)},
        }
        write_json(output_path, payload)
        print(json.dumps(payload, ensure_ascii=False))
        return 2

    payload = validate_vision_decision(
        blocks,
        pack,
        decision,
        Path(args.input),
        Path(args.overlay),
        Path(args.prompt),
        min_confidence=args.min_confidence,
    )
    write_json(output_path, payload)
    if args.json:
        print(json.dumps(payload, ensure_ascii=False))
    elif payload["ok"]:
        resolved = payload["resolved"]
        print(f"BLOCK_ID={resolved['blockId']}")
        print(f"SOURCE_SAFE_POINT={resolved['sourceSafePoint']}")
        print("EFFECT=none")
        print("TAP_AUTHORIZED=no")
        print(f"OUTPUT={output_path}")
    else:
        print(f"REJECTED={payload['error']['code']}")
        print(f"OUTPUT={output_path}")
    return 0 if payload["ok"] else 2


def benchmark_command(args: argparse.Namespace) -> int:
    config = build_config(args)
    totals: list[float] = []
    stages: dict[str, list[float]] = {}
    for _ in range(args.iterations):
        result = resolve_image(Path(args.input), config, refine_workers=getattr(args, "workers", None))
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
    resolve.add_argument("--ocr", action="store_true", help="run the OCR text pass")
    resolve.add_argument("--json", action="store_true", help="print blocks JSON to stdout")
    resolve.add_argument("--write-masks", action="store_true")
    add_config_args(resolve)
    resolve.set_defaults(func=resolve_command)

    find = subparsers.add_parser("find", help="resolve then find blocks by text (no tap)")
    find.add_argument("--input", required=True)
    find.add_argument("--output-dir", required=True)
    find.add_argument("--text", required=True, help="substring to match in OCR text")
    find.add_argument("--max-side", type=int, default=1280)
    find.add_argument("--max-blocks", type=int, default=256)
    find.add_argument("--ocr", action="store_true", help="run the OCR text pass")
    find.add_argument("--json", action="store_true", help="print find JSON to stdout")
    add_config_args(find)
    find.set_defaults(func=find_command)

    vision_pack = subparsers.add_parser(
        "vision-pack", help="create an annotated, frame-bound block-selection pack"
    )
    vision_pack.add_argument("--input", required=True)
    vision_pack.add_argument("--output-dir", required=True)
    vision_pack.add_argument("--query", required=True, help="natural-language target for Vision")
    vision_pack.add_argument("--max-side", type=int, default=1280)
    vision_pack.add_argument("--max-blocks", type=int, default=256)
    vision_pack.add_argument("--ocr", action="store_true", help="include OCR labels before Vision")
    vision_pack.add_argument("--json", action="store_true", help="print pack JSON to stdout")
    add_config_args(vision_pack)
    vision_pack.set_defaults(func=vision_pack_command)

    select = subparsers.add_parser(
        "select", help="validate a block-only Vision decision against the current frame"
    )
    select.add_argument("--input", required=True, help="current screenshot; SHA must still match")
    select.add_argument("--blocks", required=True)
    select.add_argument("--pack", required=True)
    select.add_argument("--overlay", required=True, help="the exact primary overlay shown to Vision")
    select.add_argument("--prompt", required=True, help="the exact prompt sent with the overlay")
    select.add_argument("--decision", required=True)
    select.add_argument("--output", required=True)
    select.add_argument("--min-confidence", type=float, default=0.8)
    select.add_argument("--json", action="store_true")
    select.set_defaults(func=select_command)

    benchmark = subparsers.add_parser("benchmark", help="benchmark local resolve only")
    benchmark.add_argument("--input", required=True)
    benchmark.add_argument("--iterations", type=int, default=20)
    benchmark.add_argument("--max-side", type=int, default=1280)
    benchmark.add_argument("--max-blocks", type=int, default=256)
    benchmark.add_argument("--reference-dump-ms", type=float)
    add_config_args(benchmark)
    benchmark.set_defaults(func=benchmark_command)

    synthetic = subparsers.add_parser("synthetic", help="generate a deterministic phone UI fixture")
    synthetic.add_argument("--output-dir", required=True)
    synthetic.set_defaults(func=synthetic_command)
    return root


if __name__ == "__main__":
    arguments = parser().parse_args()
    raise SystemExit(arguments.func(arguments))
