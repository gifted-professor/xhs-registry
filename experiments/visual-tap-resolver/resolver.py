"""Offline visual-block proposal and safe-point resolver.

This module has no device transport. Coordinates are bound to the exact source
image SHA and are suitable only for overlay/dry-run evaluation.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from hashlib import sha256
from pathlib import Path
from time import perf_counter
from typing import Any

import cv2
import numpy as np


@dataclass(frozen=True)
class ResolverConfig:
    max_side: int = 1280
    min_side: int = 12
    min_area_ratio: float = 0.00008
    max_area_ratio: float = 0.18
    proposal_pad_ratio: float = 0.18
    grabcut_iterations: int = 3
    max_blocks: int = 256


@dataclass(frozen=True)
class Proposal:
    kind: str
    bbox: tuple[int, int, int, int]
    score: float


def image_sha256(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def resize_for_analysis(image: np.ndarray, max_side: int) -> tuple[np.ndarray, float]:
    height, width = image.shape[:2]
    scale = min(1.0, max_side / max(height, width))
    if scale == 1.0:
        return image.copy(), scale
    resized = cv2.resize(
        image,
        (max(1, round(width * scale)), max(1, round(height * scale))),
        interpolation=cv2.INTER_AREA,
    )
    return resized, scale


def box_iou(a: tuple[int, int, int, int], b: tuple[int, int, int, int]) -> float:
    ax, ay, aw, ah = a
    bx, by, bw, bh = b
    x1 = max(ax, bx)
    y1 = max(ay, by)
    x2 = min(ax + aw, bx + bw)
    y2 = min(ay + ah, by + bh)
    overlap = max(0, x2 - x1) * max(0, y2 - y1)
    union = aw * ah + bw * bh - overlap
    return overlap / max(1, union)


def box_contains(outer: tuple[int, int, int, int], inner: tuple[int, int, int, int]) -> bool:
    ox, oy, ow, oh = outer
    ix, iy, iw, ih = inner
    return ox <= ix and oy <= iy and ox + ow >= ix + iw and oy + oh >= iy + ih


def contour_proposals(image: np.ndarray, config: ResolverConfig) -> list[Proposal]:
    height, width = image.shape[:2]
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    gray = cv2.GaussianBlur(gray, (3, 3), 0)
    edges = cv2.Canny(gray, 48, 132)
    edges = cv2.morphologyEx(edges, cv2.MORPH_CLOSE, np.ones((3, 3), np.uint8), iterations=1)
    contours, _ = cv2.findContours(edges, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
    image_area = width * height
    proposals: list[Proposal] = []

    for contour in contours:
        x, y, w, h = cv2.boundingRect(contour)
        area = w * h
        if min(w, h) < config.min_side:
            continue
        if area < image_area * config.min_area_ratio or area > image_area * config.max_area_ratio:
            continue
        if w > width * 0.97 or h > height * 0.45:
            continue
        contour_area = max(1.0, cv2.contourArea(contour))
        fill = min(1.0, contour_area / max(1, area))
        perimeter = max(1.0, cv2.arcLength(contour, True))
        compactness = min(1.0, 4.0 * np.pi * contour_area / (perimeter * perimeter))
        size_signal = min(1.0, area / max(1, image_area * 0.015))
        score = 0.32 + fill * 0.28 + compactness * 0.20 + size_signal * 0.20
        aspect = w / max(1, h)
        kind = "row" if aspect >= 3.2 and height * 0.035 <= h <= height * 0.20 else "component"
        proposals.append(Proposal(kind, (x, y, w, h), round(float(score), 4)))

    return proposals


def row_band_proposals(image: np.ndarray) -> list[Proposal]:
    """Propose wide list-row bands from strong horizontal boundaries."""

    height, width = image.shape[:2]
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    sobel_y = np.abs(cv2.Sobel(gray, cv2.CV_32F, 0, 1, ksize=3))
    profile = sobel_y[:, int(width * 0.04) : int(width * 0.96)].mean(axis=1)
    threshold = max(float(np.percentile(profile, 84)), float(profile.mean() + profile.std() * 0.8))
    active = np.flatnonzero(profile >= threshold)
    if not len(active):
        return []

    peaks: list[int] = []
    start = previous = int(active[0])
    for value in active[1:]:
        value = int(value)
        if value > previous + 2:
            peaks.append((start + previous) // 2)
            start = value
        previous = value
    peaks.append((start + previous) // 2)

    min_height = max(30, round(height * 0.035))
    max_height = max(min_height + 1, round(height * 0.20))
    margin = max(2, round(width * 0.025))
    boundaries = sorted({0, *peaks, height - 1})
    proposals: list[Proposal] = []
    for top, bottom in zip(boundaries, boundaries[1:]):
        band_height = bottom - top
        if min_height <= band_height <= max_height:
            band_edges = sobel_y[top:bottom, margin : width - margin]
            edge_density = float(np.count_nonzero(band_edges > threshold) / max(1, band_edges.size))
            if edge_density < 0.012:
                continue
            proposals.append(
                Proposal("row", (margin, top, width - margin * 2, band_height), 0.58)
            )
    return proposals


def deduplicate_proposals(proposals: list[Proposal], limit: int) -> list[Proposal]:
    selected: list[Proposal] = []
    ordered = sorted(proposals, key=lambda item: (-item.score, item.bbox[1], item.bbox[0]))
    for proposal in ordered:
        duplicate = False
        for existing in selected:
            iou = box_iou(proposal.bbox, existing.bbox)
            nested = box_contains(existing.bbox, proposal.bbox) or box_contains(proposal.bbox, existing.bbox)
            same_kind = proposal.kind == existing.kind
            if iou >= 0.72 or (same_kind and nested and iou >= 0.48):
                duplicate = True
                break
        if not duplicate:
            selected.append(proposal)
        if len(selected) >= limit:
            break
    return selected


def fill_holes(mask: np.ndarray) -> np.ndarray:
    flood = mask.copy()
    padded = cv2.copyMakeBorder(flood, 1, 1, 1, 1, cv2.BORDER_CONSTANT, value=0)
    flood_mask = np.zeros((padded.shape[0] + 2, padded.shape[1] + 2), np.uint8)
    cv2.floodFill(padded, flood_mask, (0, 0), 255)
    flood = padded[1:-1, 1:-1]
    holes = cv2.bitwise_not(flood)
    return cv2.bitwise_or(mask, holes)


def overlapping_component(mask: np.ndarray, seed_rect: tuple[int, int, int, int]) -> np.ndarray | None:
    sx, sy, sw, sh = seed_rect
    seed = np.zeros_like(mask)
    seed[sy : sy + sh, sx : sx + sw] = 255
    count, labels, stats, _ = cv2.connectedComponentsWithStats(mask, 8)
    best_label = 0
    best_score = 0.0
    for label in range(1, count):
        component = np.where(labels == label, 255, 0).astype(np.uint8)
        overlap = cv2.countNonZero(cv2.bitwise_and(component, seed))
        area = int(stats[label, cv2.CC_STAT_AREA])
        score = overlap + min(overlap, area) * 0.25
        if overlap > 0 and score > best_score:
            best_label = label
            best_score = score
    if best_label == 0:
        return None
    return np.where(labels == best_label, 255, 0).astype(np.uint8)


def padded_crop(
    bbox: tuple[int, int, int, int], image_width: int, image_height: int, pad_ratio: float
) -> tuple[int, int, int, int]:
    x, y, w, h = bbox
    pad = max(6, round(max(w, h) * pad_ratio))
    x1 = max(0, x - pad)
    y1 = max(0, y - pad)
    x2 = min(image_width, x + w + pad)
    y2 = min(image_height, y + h + pad)
    return x1, y1, max(1, x2 - x1), max(1, y2 - y1)


def refine_component(
    image: np.ndarray, proposal: Proposal, config: ResolverConfig
) -> tuple[np.ndarray, tuple[int, int, int, int], str]:
    image_height, image_width = image.shape[:2]
    x, y, w, h = proposal.bbox
    if proposal.kind == "row":
        mask = np.full((h, w), 255, np.uint8)
        return mask, proposal.bbox, "row-band"

    crop_x, crop_y, crop_w, crop_h = padded_crop(
        proposal.bbox, image_width, image_height, config.proposal_pad_ratio
    )
    crop = image[crop_y : crop_y + crop_h, crop_x : crop_x + crop_w].copy()
    rect_x = max(1, x - crop_x)
    rect_y = max(1, y - crop_y)
    rect_w = min(w, crop_w - rect_x - 1)
    rect_h = min(h, crop_h - rect_y - 1)
    if rect_w < 2 or rect_h < 2:
        return np.full((h, w), 255, np.uint8), proposal.bbox, "bbox"

    grab_mask = np.zeros((crop_h, crop_w), np.uint8)
    background = np.zeros((1, 65), np.float64)
    foreground = np.zeros((1, 65), np.float64)
    try:
        cv2.setRNGSeed(0)
        cv2.grabCut(
            crop,
            grab_mask,
            (rect_x, rect_y, rect_w, rect_h),
            background,
            foreground,
            config.grabcut_iterations,
            cv2.GC_INIT_WITH_RECT,
        )
        binary = np.where(
            (grab_mask == cv2.GC_FGD) | (grab_mask == cv2.GC_PR_FGD), 255, 0
        ).astype(np.uint8)
        selected = overlapping_component(binary, (rect_x, rect_y, rect_w, rect_h))
        if selected is None or cv2.countNonZero(selected) < 9:
            raise ValueError("empty GrabCut component")
        kernel = np.ones((3, 3), np.uint8)
        selected = cv2.morphologyEx(selected, cv2.MORPH_CLOSE, kernel, iterations=1)
        selected = cv2.morphologyEx(selected, cv2.MORPH_OPEN, kernel, iterations=1)
        selected = fill_holes(selected)
        ys, xs = np.where(selected > 0)
        if not len(xs):
            raise ValueError("empty cleaned mask")
        local_x1, local_y1 = int(xs.min()), int(ys.min())
        local_x2, local_y2 = int(xs.max()) + 1, int(ys.max()) + 1
        tight = selected[local_y1:local_y2, local_x1:local_x2]
        return tight, (
            crop_x + local_x1,
            crop_y + local_y1,
            local_x2 - local_x1,
            local_y2 - local_y1,
        ), "grabcut"
    except (cv2.error, ValueError):
        return np.full((h, w), 255, np.uint8), proposal.bbox, "bbox-fallback"


def safe_point(mask: np.ndarray, bbox: tuple[int, int, int, int]) -> tuple[int, int, float]:
    if mask.dtype != np.uint8:
        mask = mask.astype(np.uint8)
    binary = np.where(mask > 0, 255, 0).astype(np.uint8)
    if not cv2.countNonZero(binary):
        x, y, w, h = bbox
        return x + w // 2, y + h // 2, 0.0
    # OpenCV needs an explicit zero-valued boundary. Without it, a full
    # rectangular mask has no background seed and may incorrectly resolve to a
    # corner instead of the center.
    padded = cv2.copyMakeBorder(binary, 1, 1, 1, 1, cv2.BORDER_CONSTANT, value=0)
    distance = cv2.distanceTransform(padded, cv2.DIST_L2, 5)[1:-1, 1:-1]
    maximum = float(distance.max())
    candidates = np.argwhere(distance >= max(0.0, maximum - 1e-6))
    mask_height, mask_width = binary.shape[:2]
    target = np.array([(mask_height - 1) / 2.0, (mask_width - 1) / 2.0])
    best_index = int(np.argmin(np.square(candidates - target).sum(axis=1)))
    best_y, best_x = candidates[best_index]
    x, y, _, _ = bbox
    return x + int(best_x), y + int(best_y), maximum


def source_box(box: tuple[int, int, int, int], scale: float, width: int, height: int) -> list[int]:
    x, y, w, h = box
    x1 = min(width - 1, max(0, round(x / scale)))
    y1 = min(height - 1, max(0, round(y / scale)))
    x2 = min(width, max(x1 + 1, round((x + w) / scale)))
    y2 = min(height, max(y1 + 1, round((y + h) / scale)))
    return [x1, y1, x2 - x1, y2 - y1]


def source_point(point: tuple[int, int], scale: float, width: int, height: int) -> list[int]:
    x, y = point
    return [
        min(width - 1, max(0, round(x / scale))),
        min(height - 1, max(0, round(y / scale))),
    ]


def point_in_box(point: list[int], box: list[int]) -> bool:
    px, py = point
    x, y, width, height = box
    return x <= px < x + width and y <= py < y + height


def assign_block_hierarchy(blocks: list[dict[str, Any]]) -> list[str]:
    rows = [block for block in blocks if block["kind"] == "row"]
    for block in blocks:
        if block["kind"] == "row":
            continue
        block_area = block["sourceBBox"][2] * block["sourceBBox"][3]
        parents = [
            row
            for row in rows
            if point_in_box(block["sourceSafePoint"], row["sourceBBox"])
            and row["sourceBBox"][2] * row["sourceBBox"][3] >= block_area * 1.5
        ]
        if parents:
            parent = min(parents, key=lambda row: row["sourceBBox"][2] * row["sourceBBox"][3])
            block["parentBlockId"] = parent["blockId"]
    return [block["blockId"] for block in blocks if "parentBlockId" not in block]


def resolve_image(path: Path, config: ResolverConfig | None = None) -> dict[str, Any]:
    config = config or ResolverConfig()
    started = perf_counter()
    source = cv2.imread(str(path), cv2.IMREAD_COLOR)
    if source is None:
        raise ValueError(f"unable to decode image: {path}")
    decoded = perf_counter()
    source_height, source_width = source.shape[:2]
    analysis, scale = resize_for_analysis(source, config.max_side)
    resized = perf_counter()

    proposals = deduplicate_proposals(
        contour_proposals(analysis, config) + row_band_proposals(analysis),
        config.max_blocks,
    )
    proposed = perf_counter()
    blocks: list[dict[str, Any]] = []
    masks: dict[str, tuple[np.ndarray, tuple[int, int, int, int]]] = {}

    for proposal in proposals:
        mask, mask_box, method = refine_component(analysis, proposal, config)
        px, py, clearance = safe_point(mask, mask_box)
        block = {
            "kind": proposal.kind,
            "method": method,
            "proposalScore": proposal.score,
            "analysisBBox": list(proposal.bbox),
            "analysisMaskBBox": list(mask_box),
            "sourceBBox": source_box(mask_box, scale, source_width, source_height),
            "analysisSafePoint": [px, py],
            "sourceSafePoint": source_point((px, py), scale, source_width, source_height),
            "safeClearancePx": round(clearance / scale, 2),
            "maskArea": int(cv2.countNonZero(mask)),
            "_mask": mask,
        }
        blocks.append(block)

    blocks.sort(key=lambda item: (item["sourceSafePoint"][1], item["sourceSafePoint"][0], item["kind"]))
    for index, block in enumerate(blocks, start=1):
        block_id = f"b{index:03d}"
        block["blockId"] = block_id
        masks[block_id] = (block.pop("_mask"), tuple(block["analysisMaskBBox"]))
    root_block_ids = assign_block_hierarchy(blocks)
    refined = perf_counter()

    return {
        "schemaVersion": "visual-tap-blocks.v0",
        "effect": "none",
        "input": {
            "path": str(path.resolve()),
            "sha256": image_sha256(path),
            "sourceResolution": [source_width, source_height],
            "analysisResolution": [analysis.shape[1], analysis.shape[0]],
        },
        "transform": {
            "kind": "uniform-scale",
            "analysisToSourceScale": round(1.0 / scale, 8),
            "cropOffset": [0, 0],
            "padding": [0, 0],
        },
        "config": asdict(config),
        "blocks": blocks,
        "rootBlockIds": root_block_ids,
        "timingMs": {
            "decode": round((decoded - started) * 1000, 3),
            "resize": round((resized - decoded) * 1000, 3),
            "proposals": round((proposed - resized) * 1000, 3),
            "refine": round((refined - proposed) * 1000, 3),
            "total": round((refined - started) * 1000, 3),
        },
        "_source": source,
        "_masks": masks,
    }


def render_overlay(source: np.ndarray, blocks: list[dict[str, Any]]) -> np.ndarray:
    overlay = source.copy()
    palette = {
        "component": (35, 210, 70),
        "row": (255, 170, 30),
    }
    for block in blocks:
        x, y, w, h = block["sourceBBox"]
        px, py = block["sourceSafePoint"]
        color = palette.get(block["kind"], (255, 255, 0))
        cv2.rectangle(overlay, (x, y), (x + w, y + h), color, 2)
        cv2.drawMarker(overlay, (px, py), (0, 0, 255), cv2.MARKER_CROSS, 14, 2)
        cv2.putText(
            overlay,
            block["blockId"],
            (x, max(14, y - 4)),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.42,
            color,
            1,
            cv2.LINE_AA,
        )
    return overlay


def serializable_result(result: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in result.items() if not key.startswith("_")}
