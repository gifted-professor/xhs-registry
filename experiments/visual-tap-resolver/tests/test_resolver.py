from __future__ import annotations

import json
import sys
import tempfile
import unittest
from argparse import Namespace
from pathlib import Path

import cv2
import numpy as np


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from resolver import (  # noqa: E402
    ResolverConfig,
    box_iou,
    detect_media_regions,
    overlapping_component,
    resize_for_analysis,
    resolve_image,
    safe_point,
    source_box,
    source_point,
    weak_control_proposals,
)
from visual_tap_demo import synthetic_command  # noqa: E402


def _ref_full_rect_safe_point(h: int, w: int) -> tuple[int, int, float]:
    """Reference safe_point for a full-rect mask via the distance-transform
    path (what A6's analytic shortcut must replicate exactly)."""
    binary = np.full((h, w), 255, np.uint8)
    padded = cv2.copyMakeBorder(binary, 1, 1, 1, 1, cv2.BORDER_CONSTANT, value=0)
    distance = cv2.distanceTransform(padded, cv2.DIST_L2, 5)[1:-1, 1:-1]
    maximum = float(distance.max())
    candidates = np.argwhere(distance >= max(0.0, maximum - 1e-6))
    target = np.array([(h - 1) / 2.0, (w - 1) / 2.0])
    best_index = int(np.argmin(np.square(candidates - target).sum(axis=1)))
    best_y, best_x = candidates[best_index]
    return int(best_x), int(best_y), maximum


class SafePointTests(unittest.TestCase):
    def test_full_mask_resolves_near_center(self) -> None:
        mask = np.full((80, 120), 255, np.uint8)
        x, y, clearance = safe_point(mask, (200, 300, 120, 80))
        self.assertLessEqual(abs(x - 260), 1)
        self.assertLessEqual(abs(y - 340), 1)
        self.assertGreater(clearance, 38)

    def test_full_rect_shortcut_matches_distance_transform(self) -> None:
        # A6 guard: the analytic full-rect shortcut must replicate the
        # distance-transform plateau + row-major argmin exactly for every
        # odd/even parity. If any mismatch, drop the shortcut.
        for h, w in [(79, 119), (80, 120), (81, 121), (82, 120), (80, 121), (81, 120), (79, 120), (120, 80)]:
            reference = _ref_full_rect_safe_point(h, w)
            x, y, clearance = safe_point(np.full((h, w), 255, np.uint8), (0, 0, w, h))
            self.assertEqual(
                (x, y, clearance), reference,
                f"full-rect shortcut diverged from distance transform at h={h} w={w}",
            )

    def test_rectangle_safe_point_is_inside(self) -> None:
        mask = np.zeros((80, 120), np.uint8)
        cv2.rectangle(mask, (12, 8), (108, 70), 255, -1)
        x, y, clearance = safe_point(mask, (200, 300, 120, 80))
        self.assertTrue(212 <= x <= 308)
        self.assertTrue(308 <= y <= 370)
        self.assertGreater(clearance, 20)

    def test_hollow_ring_safe_point_stays_on_foreground(self) -> None:
        mask = np.zeros((100, 100), np.uint8)
        cv2.circle(mask, (50, 50), 38, 255, -1)
        cv2.circle(mask, (50, 50), 22, 0, -1)
        x, y, clearance = safe_point(mask, (40, 60, 100, 100))
        self.assertGreater(mask[y - 60, x - 40], 0)
        self.assertGreater(clearance, 6)

    def test_irregular_shape_point_stays_on_foreground(self) -> None:
        mask = np.zeros((100, 120), np.uint8)
        polygon = np.array([[8, 12], [108, 15], [82, 44], [104, 88], [44, 78], [12, 94]])
        cv2.fillPoly(mask, [polygon], 255)
        x, y, _ = safe_point(mask, (7, 11, 120, 100))
        self.assertGreater(mask[y - 11, x - 7], 0)


class CoordinateTransformTests(unittest.TestCase):
    def test_uniform_scale_round_trip_is_within_one_pixel(self) -> None:
        image = np.zeros((2400, 1080, 3), np.uint8)
        resized, scale = resize_for_analysis(image, 1280)
        self.assertEqual((resized.shape[1], resized.shape[0]), (576, 1280))
        original = [731, 1819]
        analysis = [
            round((original[0] + 0.5) * scale - 0.5),
            round((original[1] + 0.5) * scale - 0.5),
        ]
        restored = source_point(tuple(analysis), scale, 1080, 2400)
        self.assertLessEqual(abs(restored[0] - original[0]), 1)
        self.assertLessEqual(abs(restored[1] - original[1]), 1)

    def test_source_box_stays_in_bounds(self) -> None:
        result = source_box((500, 1100, 200, 300), 0.5, 1080, 2400)
        x, y, width, height = result
        self.assertGreaterEqual(x, 0)
        self.assertGreaterEqual(y, 0)
        self.assertLessEqual(x + width, 1080)
        self.assertLessEqual(y + height, 2400)

    def test_odd_resolution_uses_effective_axis_scales(self) -> None:
        image = np.zeros((2532, 1170, 3), np.uint8)
        resized, _ = resize_for_analysis(image, 1280)
        scales = (resized.shape[1] / 1170, resized.shape[0] / 2532)
        original = [680, 1901]
        analysis = [
            round((original[0] + 0.5) * scales[0] - 0.5),
            round((original[1] + 0.5) * scales[1] - 0.5),
        ]
        restored = source_point(tuple(analysis), scales, 1170, 2532)
        self.assertLessEqual(abs(restored[0] - original[0]), 1)
        self.assertLessEqual(abs(restored[1] - original[1]), 1)

    def test_aggressive_downscale_maps_pixel_centers_not_edges(self) -> None:
        self.assertEqual(source_point((5, 5), 0.1, 100, 100), [54, 54])


class DeterminismTests(unittest.TestCase):
    def test_resize_is_deterministic(self) -> None:
        rng = np.random.default_rng(7)
        image = rng.integers(0, 256, (300, 160, 3), dtype=np.uint8)
        first, first_scale = resize_for_analysis(image, 128)
        second, second_scale = resize_for_analysis(image, 128)
        self.assertEqual(first_scale, second_scale)
        self.assertTrue(np.array_equal(first, second))

    def test_full_block_result_is_deterministic(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            synthetic_command(Namespace(output_dir=str(output)))
            first = resolve_image(output / "screen.png")
            second = resolve_image(output / "screen.png")
            self.assertEqual(first["blocks"], second["blocks"])
            self.assertEqual(first["rootBlockIds"], second["rootBlockIds"])

    def test_parallel_refine_matches_serial(self) -> None:
        # A4 guard: the thread pool must produce byte-identical blocks to the
        # serial path. ``test_full_block_result_is_deterministic`` compares two
        # same-mode runs; this one proves parallel == serial across modes.
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            synthetic_command(Namespace(output_dir=str(output)))
            serial = resolve_image(output / "screen.png", refine_workers=1)
            parallel = resolve_image(output / "screen.png", refine_workers=4)
            self.assertEqual(serial["blocks"], parallel["blocks"])
            self.assertEqual(serial["rootBlockIds"], parallel["rootBlockIds"])

    def test_resolve_does_not_mutate_source_or_analysis(self) -> None:
        # The synthetic frame is 540x1200 under max_side=1280, so analysis IS
        # source after A5 (no copy). If any resolver stage mutates the analysis
        # array in place, the decoded source is corrupted too — guard that the
        # returned _source still matches the file bytes exactly.
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            synthetic_command(Namespace(output_dir=str(output)))
            fresh = cv2.imread(str(output / "screen.png"))
            result = resolve_image(output / "screen.png")
            self.assertTrue(
                np.array_equal(result["_source"], fresh),
                "resolve_image mutated the decoded source image (aliased analysis)",
            )


class SyntheticIntegrationTests(unittest.TestCase):
    def test_weak_control_detection_finds_low_contrast_toggle(self) -> None:
        # A light-gray toggle on a near-white card produces almost no strong
        # Canny edges; the weak-control pass must still surface it. Use a
        # phone-like frame so the toggle's area ratio matches a real screenshot.
        image = np.full((1280, 576, 3), 252, np.uint8)
        cv2.rectangle(image, (40, 40), (536, 1240), (255, 255, 255), -1)  # card
        track = (232, 232, 232)
        tx, ty = 440, 1000
        cv2.rectangle(image, (tx, ty), (tx + 78, ty + 34), track, 2)      # track
        cv2.circle(image, (tx + 20, ty + 17), 15, track, -1)              # knob
        proposals = weak_control_proposals(image, ResolverConfig())
        cx, cy = tx + 39, ty + 17
        hit = any(
            abs(p.bbox[0] + p.bbox[2] / 2 - cx) < 45 and abs(p.bbox[1] + p.bbox[3] / 2 - cy) < 35
            for p in proposals
        )
        self.assertTrue(hit, "weak-control pass missed the low-contrast toggle")

    def test_media_region_detected_for_large_textured_area(self) -> None:
        rng = np.random.default_rng(3)
        image = np.full((400, 240, 3), 245, np.uint8)
        # busy photo occupies most of the frame
        photo = rng.integers(40, 220, (260, 240, 3), dtype=np.uint8)
        image[110:370, :, :] = photo
        regions = detect_media_regions(image, ResolverConfig())
        self.assertTrue(regions, "no media region detected for a large photo")
        self.assertGreaterEqual(regions[0].area_ratio, 0.4)
        # A2 guard: the region bbox must be tight to the photo's own pixels, not
        # the full frame (bbox-scoped mask re-derivation must not swallow chrome).
        # Photo is rows [110,370) = 260 tall; a swallowed full-frame region would
        # be ~400 tall. Allow the blur-margin boundary pixels on each side.
        bx, by, bw, bh = regions[0].bbox
        self.assertGreaterEqual(bh, 230, f"media region collapsed below photo height, got {regions[0].bbox}")
        self.assertLessEqual(bh, 270, f"media region swallowed the full frame, got {regions[0].bbox}")

    def test_every_list_row_has_a_safe_row_candidate(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            synthetic_command(Namespace(output_dir=str(output)))
            truth = json.loads((output / "ground-truth.json").read_text(encoding="utf-8"))
            result = resolve_image(output / "screen.png", ResolverConfig(max_blocks=256))
            row_blocks = [block for block in result["blocks"] if block["kind"] == "row"]
            expected_rows = [region for region in truth["hitRegions"] if region["id"].startswith("row-")]
            self.assertEqual(len(expected_rows), 5)

            for expected in expected_rows:
                ex, ey, ew, eh = expected["bbox"]
                matches = []
                for block in row_blocks:
                    px, py = block["sourceSafePoint"]
                    if ex <= px < ex + ew and ey <= py < ey + eh:
                        matches.append(block)
                self.assertTrue(matches, f"no row safe point for {expected['id']}")
                self.assertTrue(
                    any(box_iou(tuple(block["sourceBBox"]), tuple(expected["bbox"])) > 0.45 for block in matches),
                    f"no sufficiently overlapping row block for {expected['id']}",
                )


class OverlappingComponentTests(unittest.TestCase):
    def test_bbox_prefilter_selects_only_the_seed_overlapping_label(self) -> None:
        # Two disconnected blobs: one inside the seed rect, one far outside.
        # The bbox prefilter must skip the outside blob (zero overlap) and
        # return exactly the inside one.
        mask = np.zeros((60, 60), np.uint8)
        cv2.rectangle(mask, (10, 10), (20, 20), 255, -1)  # inside seed
        cv2.rectangle(mask, (45, 45), (55, 55), 255, -1)  # outside seed
        seed = (8, 8, 15, 15)
        out = overlapping_component(mask, seed)
        self.assertIsNotNone(out, "expected a component overlapping the seed rect")
        ys, xs = np.where(out > 0)
        self.assertTrue((xs >= 10).all() and (xs <= 20).all(), f"returned pixels outside inside-blob x: {xs.tolist()}")
        self.assertTrue((ys >= 10).all() and (ys <= 20).all(), f"returned pixels outside inside-blob y: {ys.tolist()}")


if __name__ == "__main__":
    unittest.main()
