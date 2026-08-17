from __future__ import annotations

import io
import os
import tempfile
import unittest
from argparse import Namespace
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
import sys  # noqa: E402

sys.path.insert(0, str(ROOT))
from accept_benchmark import EXIT_EVIDENCE_MISSING, main  # noqa: E402
from visual_tap_demo import immersive_command  # noqa: E402

MINIMAL_XML = (
    "<node><node clickable=\"true\" enabled=\"true\" "
    "bounds=\"[22,116][70,164]\"/></node>"
)


def _build_evidence(directory: Path) -> Path:
    """Build a fake evidence tree with one page: douyin-c is the immersive
    fixture (floods at default, cuts under the C1 config), plus a minimal UI
    XML so the clickable-bounds coverage path runs."""
    root = directory / "evidence"
    (root / "douyin").mkdir(parents=True)
    immersive_command(Namespace(output_dir=str(directory / "imm")))
    (directory / "imm" / "screen.png").rename(root / "douyin" / "page-c.png")
    (root / "douyin" / "page-c.xml").write_text(MINIMAL_XML, encoding="utf-8")
    return root


class AcceptBenchmarkTests(unittest.TestCase):
    def test_evidence_missing_is_clean_skip(self) -> None:
        # No --evidence and no env var -> clean "evidence not present", code 2,
        # never a crash and never a PASS/FAIL. The empty-evidence short-circuit
        # returns before any filesystem access.
        with mock.patch.dict(os.environ, {}, clear=True):
            with redirect_stdout(io.StringIO()) as captured:
                code = main([])
        self.assertEqual(code, EXIT_EVIDENCE_MISSING)
        self.assertIn("evidence not present", captured.getvalue())

    def test_douyin_c_gate_fails_at_default_floods(self) -> None:
        # Default config leaves the immersive page flooded (179 blocks) so the
        # real acceptance gate FAILs and exits 1.
        with tempfile.TemporaryDirectory() as directory:
            evidence = _build_evidence(Path(directory))
            with redirect_stdout(io.StringIO()) as captured:
                code = main(["--evidence", str(evidence), "--runs", "1"])
            self.assertEqual(code, 1)
            self.assertIn("douyin-c candidates", captured.getvalue())
            self.assertIn("FAIL", captured.getvalue())

    def test_douyin_c_gate_passes_with_c1_config(self) -> None:
        # The C1 A/B flags cut the same page to <=40 and the gate PASSes (exit 0).
        with tempfile.TemporaryDirectory() as directory:
            evidence = _build_evidence(Path(directory))
            with redirect_stdout(io.StringIO()) as captured:
                code = main(
                    [
                        "--evidence", str(evidence),
                        "--runs", "1",
                        "--half-res-media",
                        "--merge-media",
                        "--min-component-score", "0.55",
                    ]
                )
            self.assertEqual(code, 0)
            self.assertIn("PASS", captured.getvalue())

    def test_parse_expect_accepts_inline_json(self) -> None:
        from accept_benchmark import parse_expect

        expect = parse_expect('{"douyin_c_blocks": 30}')
        self.assertEqual(expect["douyin_c_blocks"], 30.0)
        # untouched defaults carry through
        self.assertEqual(expect["coverage_total"], 90.0)


if __name__ == "__main__":
    unittest.main()
