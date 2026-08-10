"""Optional OCR integration for the visual tap resolver.

OCR runs as an independent pass that produces text boxes. Each text box becomes
a ``kind="text"`` candidate so text-only controls (topic tabs, text buttons)
that geometric proposals miss are still resolvable, and every overlapping
geometric block is annotated with the recognized string so a future selector
can resolve "tap <text>" to a blockId. OCR never invents coordinates: safe
points still come from the resolver's own geometry.

Targets PaddleOCR 3.x (``PaddleOCR.predict`` -> ``rec_boxes``/``rec_texts``/
``rec_scores``). The dependency is optional; the resolver works without it.

oneDNN/MKL-DNN on some CPUs (i3-12100 here) crashes the OCR process, so it is
disabled before any PaddleOCR import — same recipe as the known-good
``scripts/lib/wechat-balance-ocr.py`` in the parent registry repo. Without
these env vars set first, PaddleOCR's native init picks up oneDNN and dies.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

# Must run before ``from paddleocr import PaddleOCR``: they gate the native
# oneDNN backend at Paddle's C++ init. setdefault so a caller-provided override
# (e.g. a working mkldnn build) still wins.
os.environ.setdefault("FLAGS_use_mkldnn", "0")
os.environ.setdefault("PADDLE_PDX_DISABLE_MKLDNN", "1")

import numpy as np

from resolver import Proposal


@dataclass(frozen=True)
class TextBox:
    bbox: tuple[int, int, int, int]
    text: str
    confidence: float


class OcrEngine:
    """Thin wrapper so the resolver does not hard-depend on PaddleOCR."""

    def __init__(self, lang: str = "ch") -> None:
        from paddleocr import PaddleOCR  # imported lazily; optional dependency

        self._ocr = PaddleOCR(
            lang=lang,
            use_doc_orientation_classify=False,
            use_doc_unwarping=False,
            use_textline_orientation=False,
            enable_mkldnn=False,
            cpu_threads=os.cpu_count(),
        )

    def detect(self, image: np.ndarray) -> list[TextBox]:
        height, width = image.shape[:2]
        result = self._ocr.predict(image)
        if not result:
            return []
        record = result[0]
        texts = list(record.get("rec_texts") or [])
        boxes = record.get("rec_boxes")
        boxes = list(boxes) if boxes is not None else []
        scores = record.get("rec_scores")
        scores = list(scores) if scores is not None else []
        out: list[TextBox] = []
        for text, raw_box, score in zip(texts, boxes, scores):
            x1, y1, x2, y2 = (int(v) for v in raw_box[:4])
            x1, x2 = max(0, x1), min(width, x2)
            y1, y2 = max(0, y1), min(height, y2)
            if x2 - x1 < 6 or y2 - y1 < 6:
                continue
            out.append(
                TextBox(
                    bbox=(x1, y1, x2 - x1, y2 - y1),
                    text=str(text).strip(),
                    confidence=round(float(score), 4),
                )
            )
        return out


def text_proposals(boxes: list[TextBox]) -> list[Proposal]:
    """Convert OCR boxes into resolver candidates."""
    proposals: list[Proposal] = []
    for box in boxes:
        # Whole-line text reads as one tappable unit; score by OCR confidence.
        score = 0.55 + box.confidence * 0.30
        proposals.append(Proposal("text", box.bbox, round(score, 4)))
    return proposals
