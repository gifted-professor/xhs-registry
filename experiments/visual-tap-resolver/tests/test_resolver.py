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
    resize_for_analysis,
    resolve_image,
    safe_point,
    source_box,
    source_point,
)
from visual_tap_demo import synthetic_command  # noqa: E402


class SafePointTests(unittest.TestCase):
    def test_full_mask_resolves_near_center(self) -> None:
        mask = np.full((80, 120), 255, np.uint8)
        x, y, clearance = safe_point(mask, (200, 300, 120, 80))
        self.assertLessEqual(abs(x - 260), 1)
        self.assertLessEqual(abs(y - 340), 1)
        self.assertGreater(clearance, 38)

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
        analysis = [round(original[0] * scale), round(original[1] * scale)]
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


class SyntheticIntegrationTests(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
