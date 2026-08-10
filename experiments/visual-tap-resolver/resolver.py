"""Offline visual-block proposal and safe-point resolver.

This module has no device transport. Coordinates are bound to the exact source
image SHA and are suitable only for overlay/dry-run evaluation.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from hashlib import sha256
from math import ceil, floor
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
    # Media-region suppression. A large contiguous photo/video area should not
    # spawn per-texture candidates; overlay UI on it is kept separately.
    media_suppression: bool = True
    media_min_area_ratio: float = 0.22
    media_edge_density: float = 0.045
    media_saturation_mean: float = 28.0
    media_overlay_max_area_ratio: float = 0.004
    media_overlay_edge_margin: int = 20
    media_overlay_score: float = 0.68
    media_card_min_area_ratio: float = 0.02
    media_card_score: float = 0.60
    media_close_kernel: int = 9
    media_close_iterations: int = 2
    # Low-contrast controls (toggles, hollow icons) sit near the background
    # luminance and produce no strong Canny edges. Detect them separately with
    # a low threshold so they are not invisible to the resolver.
    weak_control_detection: bool = True
    weak_control_min_area_ratio: float = 0.0004
    weak_control_max_area_ratio: float = 0.012
    weak_control_max_aspect: float = 3.2
    weak_control_min_fill: float = 0.45
    # Optional OCR pass. Off by default: it adds a heavy one-time model load and
    # a per-page inference cost, so it is enabled only when geometric candidates
    # lack text semantics (no-dump fallback). OCR supplies text boxes and labels;
    # it never replaces the resolver's own coordinate geometry.
    enable_ocr: bool = False
    ocr_lang: str = "ch"


@dataclass(frozen=True)
class Proposal:
    kind: str
    bbox: tuple[int, int, int, int]
    score: float


@dataclass(frozen=True)
class MediaRegion:
    bbox: tuple[int, int, int, int]
    area_ratio: float
    edge_density: float
    saturation_mean: float


def image_sha256(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def decode_source_image(path: Path) -> tuple[np.ndarray, str]:
    """Read, hash, and decode one immutable byte snapshot of ``path``.

    Reading the bytes once is part of the coordinate safety contract: the
    returned SHA must describe the exact pixels used to calculate every block
    and safe point. Hashing the path again after decoding would allow a file
    replacement race to bind coordinates from frame A to the SHA of frame B.
    """

    encoded_bytes = path.read_bytes()
    digest = sha256(encoded_bytes).hexdigest()
    encoded = np.frombuffer(encoded_bytes, dtype=np.uint8)
    source = cv2.imdecode(encoded, cv2.IMREAD_COLOR)
    if source is None:
        raise ValueError(f"unable to decode image: {path}")
    return source, digest


def resize_for_analysis(image: np.ndarray, max_side: int) -> tuple[np.ndarray, float]:
    height, width = image.shape[:2]
    scale = min(1.0, max_side / max(height, width))
    if scale == 1.0:
        # No downsampling needed: reuse the array instead of copying. Safe only
        # because the resolver never mutates the analysis array in place (the
        # lone indexed assignment is a local seed mask, not analysis). The
        # mutation-safety test guards this aliasing contract.
        return image, scale
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


def box_intersection(a: tuple[int, int, int, int], b: tuple[int, int, int, int]) -> int:
    ax, ay, aw, ah = a
    bx, by, bw, bh = b
    x1 = max(ax, bx)
    y1 = max(ay, by)
    x2 = min(ax + aw, bx + bw)
    y2 = min(ay + ah, by + bh)
    return max(0, x2 - x1) * max(0, y2 - y1)


def box_center(box: tuple[int, int, int, int]) -> tuple[float, float]:
    x, y, w, h = box
    return x + w / 2.0, y + h / 2.0


def detect_media_regions(
    image: np.ndarray, config: ResolverConfig, gray: np.ndarray | None = None
) -> list[MediaRegion]:
    """Detect large contiguous photo/video areas.

    A media region is a big connected component whose interior is texture-rich
    (high edge density) and color-rich (non-trivial saturation), unlike flat UI
    surfaces. Single-frame heuristic; a second frame would make this far more
    reliable but is out of scope for the offline PoC.

    ``gray`` is the pre-blurred 5x5 grayscale of ``image`` when supplied
    (callers that already computed it avoid a duplicate full-image conversion);
    otherwise it is computed here. Bit-identical either way.
    """

    height, width = image.shape[:2]
    image_area = width * height
    if gray is None:
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        gray = cv2.GaussianBlur(gray, (5, 5), 0)
    edges = cv2.Canny(gray, 40, 120)
    # Close texture into solid blobs, then fill holes so a photo becomes one region.
    # Kernel/iterations stay modest so the media blob does not bridge across the
    # gap into the top or bottom UI bars.
    kernel = cv2.getStructuringElement(
        cv2.MORPH_RECT, (config.media_close_kernel, config.media_close_kernel)
    )
    blobs = cv2.morphologyEx(edges, cv2.MORPH_CLOSE, kernel, iterations=config.media_close_iterations)
    blobs = fill_holes(blobs)
    contours, _ = cv2.findContours(blobs, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    # Physical screen chrome (status bar, top app bar, bottom nav) is never media.
    top_ui_limit = round(height * 0.10)
    bottom_ui_start = round(height * 0.93)

    hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)
    saturation = hsv[:, :, 1]
    regions: list[MediaRegion] = []
    for contour in contours:
        x, y, w, h = cv2.boundingRect(contour)
        area = w * h
        if area < image_area * config.media_min_area_ratio:
            continue
        if w < width * 0.4 or h < height * 0.18:
            continue
        # Re-derive a tight bounding box from this component's own filled pixels
        # so a rectangular bbox never swallows adjacent UI bars. Do it on a mask
        # sized to the contour's own bbox (translated to the origin); translation
        # is an isometry, so the resulting region is bit-identical to the old
        # full-frame allocation minus a full-frame np.zeros + drawContours.
        component = np.zeros((h, w), np.uint8)
        shifted = (contour - np.array([x, y], dtype=np.int32)).astype(np.int32)
        cv2.drawContours(component, [shifted], -1, 255, -1)
        inner, _ = cv2.findContours(component, cv2.RETR_CCOMP, cv2.CHAIN_APPROX_SIMPLE)
        if not inner:
            continue
        largest = max(inner, key=cv2.contourArea)
        lx, ly, tw, th = cv2.boundingRect(largest)
        tx, ty = x + lx, y + ly
        # Clip to the content band: even if the blob bridges into chrome, the
        # reported region must not extend over the status/top bars or bottom nav.
        ty = max(ty, top_ui_limit)
        bottom = min(ty + th, bottom_ui_start)
        th = bottom - ty
        if th < height * 0.15:
            continue
        region_edges = edges[ty : ty + th, tx : tx + tw]
        edge_density = float(cv2.countNonZero(region_edges) / max(1, region_edges.size))
        sat_mean = float(saturation[ty : ty + th, tx : tx + tw].mean())
        if edge_density < config.media_edge_density and sat_mean < config.media_saturation_mean:
            continue
        regions.append(
            MediaRegion(
                bbox=(tx, ty, tw, th),
                area_ratio=round((tw * th) / image_area, 4),
                edge_density=round(edge_density, 4),
                saturation_mean=round(sat_mean, 2),
            )
        )
    regions.sort(key=lambda region: -region.area_ratio)
    return regions


def is_media_overlay(
    proposal: Proposal, region: MediaRegion, config: ResolverConfig, image_area: int
) -> bool:
    """A small high-contrast block sitting on media is likely a floating control
    (pause, mute, scan, close-ad) rather than media texture, so it survives.

    Overlay controls are compact and roughly icon-shaped; tree/rock/brush
    textures are larger, elongated, or weak. A natural texture blob rarely has
    both a tight bounding box and a high shape score."""

    x, y, w, h = proposal.bbox
    rx, ry, rw, rh = region.bbox
    area = w * h
    if area > image_area * config.media_overlay_max_area_ratio:
        return False
    if proposal.score < config.media_overlay_score:
        return False
    aspect = max(w, h) / max(1, min(w, h))
    if aspect > 3.0:
        return False
    margin = config.media_overlay_edge_margin
    near_edge = (
        x - rx <= margin
        or y - ry <= margin
        or (rx + rw) - (x + w) <= margin
        or (ry + rh) - (y + h) <= margin
    )
    # Strong, compact shapes survive anywhere on the media (pause/mute icons sit
    # mid-frame); near the edge we also allow slightly weaker close/scan chips.
    return proposal.score >= config.media_overlay_score + 0.06 or near_edge


def is_media_card(proposal: Proposal, config: ResolverConfig, image_area: int) -> bool:
    """A large, well-formed photo block inside the media region is a tappable
    content card (search-result / feed thumbnail), not background texture.
    Keep one candidate per card so it stays clickable."""

    x, y, w, h = proposal.bbox
    area = w * h
    if area < image_area * config.media_card_min_area_ratio:
        return False
    if proposal.score < config.media_card_score:
        return False
    aspect = max(w, h) / max(1, min(w, h))
    # Cards are portrait/landscape rectangles, not long thin texture streaks.
    return aspect <= 2.4


def contour_proposals(
    image: np.ndarray, config: ResolverConfig, gray: np.ndarray | None = None
) -> list[Proposal]:
    height, width = image.shape[:2]
    if gray is None:
        gray = cv2.GaussianBlur(cv2.cvtColor(image, cv2.COLOR_BGR2GRAY), (3, 3), 0)
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


def weak_control_proposals(
    image: np.ndarray, config: ResolverConfig, gray: np.ndarray | None = None
) -> list[Proposal]:
    """Propose low-contrast, text-free controls (toggles, hollow icons).

    The main Canny pass misses controls that are only a few gray levels away
    from the page background. This pass uses a low edge threshold plus tight
    size/shape gating so it recovers such controls without flooding the
    candidate set with text strokes or noise.

    ``gray`` is the pre-blurred 3x3 grayscale of ``image`` when supplied
    (callers that already computed it avoid a duplicate full-image conversion);
    otherwise it is computed here. Bit-identical either way.
    """

    height, width = image.shape[:2]
    image_area = width * height
    if gray is None:
        gray = cv2.GaussianBlur(cv2.cvtColor(image, cv2.COLOR_BGR2GRAY), (3, 3), 0)
    edges = cv2.Canny(gray, 16, 48)
    edges = cv2.morphologyEx(edges, cv2.MORPH_CLOSE, np.ones((3, 3), np.uint8), iterations=1)
    contours, _ = cv2.findContours(edges, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    proposals: list[Proposal] = []
    for contour in contours:
        x, y, w, h = cv2.boundingRect(contour)
        area = w * h
        if area < image_area * config.weak_control_min_area_ratio:
            continue
        if area > image_area * config.weak_control_max_area_ratio:
            continue
        aspect = max(w, h) / max(1, min(w, h))
        if aspect > config.weak_control_max_aspect:
            continue
        contour_area = max(1.0, cv2.contourArea(contour))
        fill = contour_area / max(1, area)
        if fill < config.weak_control_min_fill:
            continue
        # Low-contrast controls are weaker than primary candidates, so they sort
        # below strong text/icon blocks but above pure noise.
        score = 0.42 + min(0.18, fill * 0.18)
        proposals.append(Proposal("component", (x, y, w, h), round(float(score), 4)))
    return proposals


def row_band_proposals(
    image: np.ndarray, gray: np.ndarray | None = None
) -> list[Proposal]:
    """Propose wide list-row bands from strong horizontal boundaries.

    ``gray`` is the unblurred grayscale of ``image`` when supplied (callers
    that already computed it avoid a duplicate full-image conversion);
    otherwise it is computed here. Bit-identical either way.
    """

    height, width = image.shape[:2]
    if gray is None:
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


def media_center_proposal(region: MediaRegion) -> Proposal:
    """Keep exactly one safe tap target for the media surface itself."""

    x, y, w, h = region.bbox
    side = max(24, round(min(w, h) * 0.10))
    cx, cy = box_center(region.bbox)
    bbox = (round(cx - side / 2), round(cy - side / 2), side, side)
    return Proposal("media-center", bbox, 0.5)


def filter_proposals_by_media(
    proposals: list[Proposal], regions: list[MediaRegion], config: ResolverConfig, image_area: int
) -> list[Proposal]:
    """Drop proposals that are just texture inside a media region.

    Kept: anything outside media, small overlay controls on media, and one
    explicit media-center target per region. Rows are layout structure and are
    not suppressed here; the row generator is a separate path.
    """

    if not regions:
        return proposals
    kept: list[Proposal] = []
    for proposal in proposals:
        if proposal.kind == "row":
            kept.append(proposal)
            continue
        inside_region: MediaRegion | None = None
        for region in regions:
            inter = box_intersection(proposal.bbox, region.bbox)
            area = proposal.bbox[2] * proposal.bbox[3]
            if area and inter / area >= 0.7:
                inside_region = region
                break
        if inside_region is None:
            kept.append(proposal)
            continue
        if is_media_card(proposal, config, image_area):
            kept.append(proposal)
            continue
        if is_media_overlay(proposal, inside_region, config, image_area):
            kept.append(proposal)
    for region in regions:
        kept.append(media_center_proposal(region))
    return kept


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
        # A label's pixels are a subset of its stats bbox, so a bbox that does
        # not intersect the seed rect provably has zero overlap. Skipping it
        # avoids materializing the full-crop np.where for background labels.
        left = int(stats[label, cv2.CC_STAT_LEFT])
        top = int(stats[label, cv2.CC_STAT_TOP])
        lw = int(stats[label, cv2.CC_STAT_WIDTH])
        lh = int(stats[label, cv2.CC_STAT_HEIGHT])
        if left + lw <= sx or left >= sx + sw or top + lh <= sy or top >= sy + sh:
            continue
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
    if proposal.kind == "media-center":
        # The media surface is a valid tap target but needs no segmentation.
        mask = np.full((h, w), 255, np.uint8)
        return mask, proposal.bbox, "media-center"
    if proposal.kind == "text":
        # Keep the full OCR text box. Running GrabCut on text tightens the mask
        # to a single glyph, which makes the safe point unstable; the whole box
        # is the tappable unit.
        mask = np.full((h, w), 255, np.uint8)
        return mask, proposal.bbox, "text-box"
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


def _axis_scales(scale: float | tuple[float, float]) -> tuple[float, float]:
    if isinstance(scale, tuple):
        return scale
    return scale, scale


def source_box(
    box: tuple[int, int, int, int],
    scale: float | tuple[float, float],
    width: int,
    height: int,
) -> list[int]:
    x, y, w, h = box
    scale_x, scale_y = _axis_scales(scale)
    # Bounding boxes describe pixel edges, so map their half-open interval with
    # floor/ceil to conservatively contain every contributing source pixel.
    x1 = min(width - 1, max(0, floor(x / scale_x)))
    y1 = min(height - 1, max(0, floor(y / scale_y)))
    x2 = min(width, max(x1 + 1, ceil((x + w) / scale_x)))
    y2 = min(height, max(y1 + 1, ceil((y + h) / scale_y)))
    return [x1, y1, x2 - x1, y2 - y1]


def source_point(
    point: tuple[int, int],
    scale: float | tuple[float, float],
    width: int,
    height: int,
) -> list[int]:
    x, y = point
    scale_x, scale_y = _axis_scales(scale)
    # OpenCV resize maps pixel centers rather than pixel-edge indices. Applying
    # x/scale directly biases every point toward the top-left, increasingly so
    # at aggressive downscales.
    source_x = (x + 0.5) / scale_x - 0.5
    source_y = (y + 0.5) / scale_y - 0.5
    return [
        min(width - 1, max(0, round(source_x))),
        min(height - 1, max(0, round(source_y))),
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


_OCR_ENGINES: dict[str, Any] = {}


def get_ocr_engine(lang: str, engine: Any = None) -> Any:
    """Reuse one PaddleOCR engine per language; model load dominates cost.

    A caller that already built an engine (e.g. the CLI so it can time the load
    separately) can pass it in and it becomes the cached instance.
    """

    if engine is not None:
        _OCR_ENGINES[lang] = engine
    if lang not in _OCR_ENGINES:
        from ocr_integration import OcrEngine

        _OCR_ENGINES[lang] = OcrEngine(lang=lang)
    return _OCR_ENGINES[lang]


def find_blocks_by_text(result: dict[str, Any], query: str) -> list[dict[str, Any]]:
    """Return blocks whose OCR text contains the query (substring match).

    Read-only lookup over a resolved result; never emits a tap. Each match keeps
    the resolver-computed ``sourceSafePoint`` so a caller can resolve
    "tap <text>" to a blockId and its physical point without any LLM guessing.
    """

    query = query.strip()
    if not query:
        return []
    matches = []
    for block in result.get("blocks", []):
        text = block.get("text")
        if text and query in text:
            matches.append(
                {
                    "blockId": block["blockId"],
                    "kind": block["kind"],
                    "text": text,
                    "sourceBBox": block["sourceBBox"],
                    "sourceSafePoint": block["sourceSafePoint"],
                    "confidence": block["proposalScore"],
                }
            )
    return matches


def resolve_image(path: Path, config: ResolverConfig | None = None) -> dict[str, Any]:
    config = config or ResolverConfig()
    started = perf_counter()
    source, source_sha = decode_source_image(path)
    decoded = perf_counter()
    source_height, source_width = source.shape[:2]
    analysis, _nominal_scale = resize_for_analysis(source, config.max_side)
    scale_x = analysis.shape[1] / source_width
    scale_y = analysis.shape[0] / source_height
    source_scales = (scale_x, scale_y)
    resized = perf_counter()

    # One full-image grayscale conversion, shared by the three proposal passes
    # and (if enabled) media detection. Bit-identical to each pass computing
    # its own gray; blur kernels differ (3x3 vs 5x5) so they are prepared
    # separately, the 5x5 only when media suppression actually runs.
    raw_gray = cv2.cvtColor(analysis, cv2.COLOR_BGR2GRAY)
    gray3 = cv2.GaussianBlur(raw_gray, (3, 3), 0)
    raw_proposals = contour_proposals(analysis, config, gray3) + row_band_proposals(analysis, raw_gray)
    if config.weak_control_detection:
        raw_proposals = raw_proposals + weak_control_proposals(analysis, config, gray3)
    proposals = deduplicate_proposals(raw_proposals, config.max_blocks)
    proposed = perf_counter()

    media_regions: list[MediaRegion] = []
    if config.media_suppression:
        gray5 = cv2.GaussianBlur(raw_gray, (5, 5), 0)
        media_regions = detect_media_regions(analysis, config, gray5)
        proposals = deduplicate_proposals(
            filter_proposals_by_media(
                proposals, media_regions, config, analysis.shape[0] * analysis.shape[1]
            ),
            config.max_blocks,
        )
    media_done = perf_counter()

    # Optional OCR pass: text boxes become text candidates and label any
    # overlapping geometric block. Runs after media suppression so OCR text on
    # the media surface is not treated as a texture candidate, and so OCR can
    # annotate the surviving UI blocks.
    ocr_boxes: list[Any] = []
    if config.enable_ocr:
        from ocr_integration import text_proposals

        engine = get_ocr_engine(config.ocr_lang, getattr(config, "ocr_engine", None))
        ocr_boxes = engine.detect(analysis)
        proposals = deduplicate_proposals(
            proposals + text_proposals(ocr_boxes), config.max_blocks
        )
    ocr_done = perf_counter()

    # Map each OCR box to the block index that contains its center, for labels.
    text_by_center: list[tuple[int, int, str]] = [
        (b.bbox[0] + b.bbox[2] // 2, b.bbox[1] + b.bbox[3] // 2, b.text) for b in ocr_boxes
    ]

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
            "sourceBBox": source_box(mask_box, source_scales, source_width, source_height),
            "analysisSafePoint": [px, py],
            "sourceSafePoint": source_point((px, py), source_scales, source_width, source_height),
            "safeClearancePx": round(clearance / max(source_scales), 2),
            "maskArea": int(cv2.countNonZero(mask)),
            "_mask": mask,
        }
        if proposal.kind == "text":
            # Label a text block with the OCR string whose center it contains.
            bx, by, bw, bh = proposal.bbox
            block["text"] = next(
                (t for cx, cy, t in text_by_center if bx <= cx < bx + bw and by <= cy < by + bh),
                None,
            )
        blocks.append(block)

    # Annotate non-text blocks with any OCR text whose center they contain.
    if ocr_boxes:
        for block in blocks:
            if block["kind"] == "text":
                continue
            bx, by, bw, bh = (int(v) for v in block["analysisBBox"])
            label = next(
                (t for cx, cy, t in text_by_center if bx <= cx < bx + bw and by <= cy < by + bh),
                None,
            )
            if label:
                block["text"] = label

    blocks.sort(key=lambda item: (item["sourceSafePoint"][1], item["sourceSafePoint"][0], item["kind"]))
    for index, block in enumerate(blocks, start=1):
        block_id = f"b{index:03d}"
        block["blockId"] = block_id
        masks[block_id] = (block.pop("_mask"), tuple(block["analysisMaskBBox"]))
    root_block_ids = assign_block_hierarchy(blocks)
    refined = perf_counter()

    media_payload = [
        {
            "bbox": list(region.bbox),
            "areaRatio": region.area_ratio,
            "edgeDensity": region.edge_density,
            "saturationMean": region.saturation_mean,
        }
        for region in media_regions
    ]

    return {
        "schemaVersion": "visual-tap-blocks.v0",
        "effect": "none",
        "input": {
            "path": str(path.resolve()),
            "sha256": source_sha,
            "frameId": f"sha256:{source_sha}",
            "coordinateSpace": "source-image-pixels",
            "sourceResolution": [source_width, source_height],
            "analysisResolution": [analysis.shape[1], analysis.shape[0]],
        },
        "transform": {
            "kind": "axis-scale",
            "analysisToSourceScale": [round(1.0 / scale_x, 8), round(1.0 / scale_y, 8)],
            "pixelCenterConvention": "source=(analysis+0.5)/scale-0.5",
            "cropOffset": [0, 0],
            "padding": [0, 0],
        },
        "config": asdict(config),
        "blocks": blocks,
        "rootBlockIds": root_block_ids,
        "mediaRegions": media_payload,
        "timingMs": {
            "decode": round((decoded - started) * 1000, 3),
            "resize": round((resized - decoded) * 1000, 3),
            "proposals": round((proposed - resized) * 1000, 3),
            "mediaSuppress": round((media_done - proposed) * 1000, 3),
            "ocr": round((ocr_done - media_done) * 1000, 3),
            "refine": round((refined - ocr_done) * 1000, 3),
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
