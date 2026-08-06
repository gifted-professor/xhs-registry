from __future__ import annotations

import copy
import hashlib
import json
import tempfile
import unittest
from argparse import Namespace
from pathlib import Path
from unittest.mock import patch

import cv2


ROOT = Path(__file__).resolve().parents[1]
import sys

sys.path.insert(0, str(ROOT))

from resolver import decode_source_image, render_overlay, resolve_image, serializable_result  # noqa: E402
from vision_contract import (  # noqa: E402
    DECISION_SCHEMA,
    build_vision_pack,
    file_sha256,
    validate_vision_decision,
    vision_prompt,
)
from visual_tap_demo import select_command, synthetic_command  # noqa: E402


class FrameBindingTests(unittest.TestCase):
    def test_decode_hashes_the_exact_bytes_it_reads_once(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            synthetic_command(Namespace(output_dir=str(output)))
            path = output / "screen.png"
            expected = hashlib.sha256(path.read_bytes()).hexdigest()
            original_read_bytes = Path.read_bytes
            with patch.object(
                Path,
                "read_bytes",
                autospec=True,
                side_effect=lambda current: original_read_bytes(current),
            ) as read_bytes:
                image, digest = decode_source_image(path)
            self.assertEqual(read_bytes.call_count, 1)
            self.assertEqual(digest, expected)
            self.assertEqual((image.shape[1], image.shape[0]), (540, 1200))


class VisionContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._temporary = tempfile.TemporaryDirectory()
        cls.output = Path(cls._temporary.name)
        synthetic_command(Namespace(output_dir=str(cls.output)))
        cls.screen = cls.output / "screen.png"
        cls.result = resolve_image(cls.screen)
        cls.blocks = serializable_result(cls.result)
        cls.overlay = cls.output / "vision-overlay-all.png"
        cv2.imwrite(str(cls.overlay), render_overlay(cls.result["_source"], cls.result["blocks"]))
        cls.primary = {
            "file": cls.overlay.name,
            "sha256": file_sha256(cls.overlay),
            "visibleBlockIds": [block["blockId"] for block in cls.blocks["blocks"]],
        }
        cls.pack = build_vision_pack(cls.blocks, "第二行右侧箭头", primary_overlay=cls.primary)
        cls.prompt = cls.output / "vision-prompt.txt"
        cls.prompt.write_text(vision_prompt(cls.pack) + "\n", encoding="utf-8", newline="\n")
        cls.blocks_path = cls.output / "blocks.json"
        cls.blocks_path.write_text(
            json.dumps(cls.blocks, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n"
        )
        cls.pack_path = cls.output / "vision-pack.json"
        cls.pack_path.write_text(
            json.dumps(cls.pack, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n"
        )

    @classmethod
    def tearDownClass(cls) -> None:
        cls._temporary.cleanup()

    def decision_for(self, pack: dict | None = None, block_id: str | None = None) -> dict:
        selected_pack = pack or self.pack
        return {
            "schemaVersion": DECISION_SCHEMA,
            "selectionRequestId": selected_pack["selectionRequestId"],
            "frameId": selected_pack["frame"]["frameId"],
            "manifestId": selected_pack["manifestId"],
            "status": "selected",
            "blockId": block_id or selected_pack["candidates"][0]["blockId"],
            "confidence": 0.95,
            "reason": "unique annotated block",
        }

    def prompt_for(self, pack: dict, name: str) -> Path:
        path = self.output / name
        path.write_text(vision_prompt(pack) + "\n", encoding="utf-8", newline="\n")
        return path

    def validate(
        self,
        decision: object,
        *,
        blocks: dict | None = None,
        pack: dict | None = None,
        image: Path | None = None,
        overlay: Path | None = None,
        prompt: Path | None = None,
    ) -> dict:
        return validate_vision_decision(
            blocks or self.blocks,
            pack or self.pack,
            decision,  # type: ignore[arg-type]
            image or self.screen,
            overlay or self.overlay,
            prompt or self.prompt,
        )

    def test_valid_selection_returns_passive_source_image_point(self) -> None:
        payload = self.validate(self.decision_for())
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["effect"], "none")
        self.assertFalse(payload["tapAuthorized"])
        self.assertEqual(payload["executionEligibility"], "offline_only")
        self.assertEqual(payload["resolved"]["coordinateSpace"], "source-image-pixels")

    def test_pack_exposes_ids_but_no_coordinates_to_vision(self) -> None:
        self.assertEqual(
            self.pack["assets"]["primaryOverlay"]["visibleBlockIds"],
            [candidate["blockId"] for candidate in self.pack["candidates"]],
        )
        for candidate in self.pack["candidates"]:
            self.assertNotIn("sourceSafePoint", candidate)
            self.assertNotIn("sourceBBox", candidate)

    def test_raw_coordinates_from_vision_are_rejected(self) -> None:
        decision = self.decision_for()
        decision["x"] = 100
        payload = self.validate(decision)
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["error"]["code"], "RAW_COORDINATES_FORBIDDEN")

    def test_ambiguous_decision_fails_closed(self) -> None:
        decision = self.decision_for()
        decision["status"] = "ambiguous"
        decision.pop("blockId")
        decision.pop("confidence")
        payload = self.validate(decision)
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["error"]["code"], "AMBIGUOUS")

    def test_stale_screenshot_is_rejected(self) -> None:
        stale = self.output / "stale.png"
        image = cv2.imread(str(self.screen))
        image[0, 0] = (255, 0, 255)
        cv2.imwrite(str(stale), image)
        payload = self.validate(self.decision_for(), image=stale)
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["error"]["code"], "STALE_FRAME")

    def test_tampered_geometry_breaks_manifest_binding(self) -> None:
        tampered = copy.deepcopy(self.blocks)
        tampered["blocks"][0]["sourceSafePoint"][0] += 1
        payload = self.validate(self.decision_for(), blocks=tampered)
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["error"]["code"], "MANIFEST_MISMATCH")

    def test_same_frame_different_candidate_manifest_is_rejected(self) -> None:
        changed = copy.deepcopy(self.blocks)
        changed["config"]["enable_ocr"] = True
        changed_pack = build_vision_pack(changed, "第二行右侧箭头", primary_overlay=self.primary)
        payload = self.validate(
            self.decision_for(),
            blocks=changed,
            pack=changed_pack,
            prompt=self.prompt_for(changed_pack, "changed-manifest-prompt.txt"),
        )
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["error"]["code"], "DECISION_REQUEST_MISMATCH")

    def test_decision_for_other_query_is_rejected(self) -> None:
        other_pack = build_vision_pack(self.blocks, "删除按钮", primary_overlay=self.primary)
        payload = self.validate(
            self.decision_for(),
            pack=other_pack,
            prompt=self.prompt_for(other_pack, "other-query-prompt.txt"),
        )
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["error"]["code"], "DECISION_REQUEST_MISMATCH")

    def test_different_overlay_is_rejected(self) -> None:
        changed_overlay = self.output / "changed-overlay.png"
        image = cv2.imread(str(self.overlay))
        image[0, 0] = (0, 255, 0)
        cv2.imwrite(str(changed_overlay), image)
        payload = self.validate(self.decision_for(), overlay=changed_overlay)
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["error"]["code"], "OVERLAY_MISMATCH")

    def test_changed_prompt_is_rejected(self) -> None:
        changed_prompt = self.output / "changed-prompt.txt"
        changed_prompt.write_text(
            vision_prompt(self.pack).replace("第二行", "删除") + "\n",
            encoding="utf-8",
            newline="\n",
        )
        payload = self.validate(self.decision_for(), prompt=changed_prompt)
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["error"]["code"], "PROMPT_MISMATCH")

    def test_pack_candidate_list_cannot_diverge_from_overlay(self) -> None:
        changed_pack = copy.deepcopy(self.pack)
        changed_pack["candidates"] = changed_pack["candidates"][:-1]
        changed_pack["candidateCount"] -= 1
        payload = self.validate(self.decision_for(), pack=changed_pack)
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["error"]["code"], "INVALID_PACK")

    def test_pack_frame_metadata_must_exactly_match_blocks(self) -> None:
        changed_pack = copy.deepcopy(self.pack)
        changed_pack["frame"]["sha256"] = "0" * 64
        payload = self.validate(self.decision_for(), pack=changed_pack)
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["error"]["code"], "PACK_FRAME_MISMATCH")

    def test_pack_passive_control_metadata_cannot_be_relaxed(self) -> None:
        changed_pack = copy.deepcopy(self.pack)
        changed_pack["executionEligibility"] = "live"
        changed_pack["tapAuthorized"] = True
        payload = self.validate(self.decision_for(), pack=changed_pack)
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["error"]["code"], "INVALID_PACK")

    def test_malformed_decision_never_raises(self) -> None:
        payload = self.validate([])
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["error"]["code"], "INVALID_DECISION")

    def test_non_finite_confidence_or_threshold_is_rejected(self) -> None:
        decision = self.decision_for()
        decision["confidence"] = float("nan")
        payload = self.validate(decision)
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["error"]["code"], "INVALID_CONFIDENCE")
        threshold_payload = validate_vision_decision(
            self.blocks,
            self.pack,
            self.decision_for(),
            self.screen,
            self.overlay,
            self.prompt,
            min_confidence=float("nan"),
        )
        self.assertFalse(threshold_payload["ok"])
        self.assertEqual(threshold_payload["error"]["code"], "INVALID_THRESHOLD")

    def test_boolean_or_short_point_fails_closed(self) -> None:
        malformed = copy.deepcopy(self.blocks)
        malformed["blocks"][0]["sourceSafePoint"] = [True, True]
        malformed_pack = build_vision_pack(malformed, "第二行右侧箭头", primary_overlay=self.primary)
        decision = self.decision_for(malformed_pack)
        payload = self.validate(
            decision,
            blocks=malformed,
            pack=malformed_pack,
            prompt=self.prompt_for(malformed_pack, "malformed-point-prompt.txt"),
        )
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["error"]["code"], "UNSAFE_BLOCK_DATA")

    def test_reason_must_be_short_plain_text(self) -> None:
        decision = self.decision_for()
        decision["reason"] = {"coordinates": [1, 2]}
        payload = self.validate(decision)
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["error"]["code"], "INVALID_REASON")

    def test_unverified_physical_coordinate_claim_is_rejected(self) -> None:
        physical = copy.deepcopy(self.blocks)
        physical["input"]["coordinateSpace"] = "physical-screen-pixels"
        physical_pack = build_vision_pack(physical, "第二行右侧箭头", primary_overlay=self.primary)
        decision = self.decision_for(physical_pack)
        payload = self.validate(decision, blocks=physical, pack=physical_pack)
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["error"]["code"], "UNVERIFIED_COORDINATE_SPACE")

    def test_primary_overlay_ids_must_match_visible_candidates(self) -> None:
        missing = copy.deepcopy(self.primary)
        missing["visibleBlockIds"] = missing["visibleBlockIds"][:-1]
        with self.assertRaises(ValueError):
            build_vision_pack(self.blocks, "第二行右侧箭头", primary_overlay=missing)

    def test_cli_read_failure_overwrites_stale_success_output(self) -> None:
        output = self.output / "stale-verified-point.json"
        output.write_text('{"ok":true}\n', encoding="utf-8", newline="\n")
        code = select_command(
            Namespace(
                blocks=str(self.output / "missing-blocks.json"),
                pack=str(self.output / "missing-pack.json"),
                decision=str(self.output / "missing-decision.json"),
                input=str(self.screen),
                overlay=str(self.overlay),
                prompt=str(self.prompt),
                output=str(output),
                min_confidence=0.8,
                json=False,
            )
        )
        self.assertEqual(code, 2)
        payload = json.loads(output.read_text(encoding="utf-8"))
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["error"]["code"], "INPUT_READ_FAILED")

    def test_cli_invalid_utf8_overwrites_stale_success_output(self) -> None:
        decision = self.output / "invalid-utf8-decision.json"
        decision.write_bytes(b"\xff\xfe")
        output = self.output / "utf8-stale-verified-point.json"
        output.write_text('{"ok":true}\n', encoding="utf-8", newline="\n")
        code = select_command(
            Namespace(
                blocks=str(self.blocks_path),
                pack=str(self.pack_path),
                decision=str(decision),
                input=str(self.screen),
                overlay=str(self.overlay),
                prompt=str(self.prompt),
                output=str(output),
                min_confidence=0.8,
                json=False,
            )
        )
        self.assertEqual(code, 2)
        payload = json.loads(output.read_text(encoding="utf-8"))
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["error"]["code"], "INPUT_READ_FAILED")

    def test_cli_duplicate_json_keys_fail_closed(self) -> None:
        decision = self.output / "duplicate-key-decision.json"
        raw = json.dumps(self.decision_for(), ensure_ascii=False)
        raw = raw.replace('"status": "selected"', '"status": "ambiguous", "status": "selected"')
        decision.write_text(raw + "\n", encoding="utf-8", newline="\n")
        output = self.output / "duplicate-key-verified-point.json"
        output.write_text('{"ok":true}\n', encoding="utf-8", newline="\n")
        code = select_command(
            Namespace(
                blocks=str(self.blocks_path),
                pack=str(self.pack_path),
                decision=str(decision),
                input=str(self.screen),
                overlay=str(self.overlay),
                prompt=str(self.prompt),
                output=str(output),
                min_confidence=0.8,
                json=False,
            )
        )
        self.assertEqual(code, 2)
        payload = json.loads(output.read_text(encoding="utf-8"))
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["error"]["code"], "INPUT_READ_FAILED")

    def test_cli_deeply_nested_decision_fails_closed(self) -> None:
        decision = self.output / "deeply-nested-decision.json"
        decision.write_text("[" * 5000 + "]" * 5000, encoding="utf-8", newline="\n")
        output = self.output / "deeply-nested-verified-point.json"
        output.write_text('{"ok":true}\n', encoding="utf-8", newline="\n")
        code = select_command(
            Namespace(
                blocks=str(self.blocks_path),
                pack=str(self.pack_path),
                decision=str(decision),
                input=str(self.screen),
                overlay=str(self.overlay),
                prompt=str(self.prompt),
                output=str(output),
                min_confidence=0.8,
                json=False,
            )
        )
        self.assertEqual(code, 2)
        payload = json.loads(output.read_text(encoding="utf-8"))
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["error"]["code"], "INPUT_READ_FAILED")

    def test_cli_oversized_decision_fails_closed(self) -> None:
        decision = self.output / "oversized-decision.json"
        decision.write_text(
            json.dumps({"reason": "x" * (64 * 1024)}, ensure_ascii=False),
            encoding="utf-8",
            newline="\n",
        )
        output = self.output / "oversized-verified-point.json"
        output.write_text('{"ok":true}\n', encoding="utf-8", newline="\n")
        code = select_command(
            Namespace(
                blocks=str(self.blocks_path),
                pack=str(self.pack_path),
                decision=str(decision),
                input=str(self.screen),
                overlay=str(self.overlay),
                prompt=str(self.prompt),
                output=str(output),
                min_confidence=0.8,
                json=False,
            )
        )
        self.assertEqual(code, 2)
        payload = json.loads(output.read_text(encoding="utf-8"))
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["error"]["code"], "INPUT_READ_FAILED")


if __name__ == "__main__":
    unittest.main()
