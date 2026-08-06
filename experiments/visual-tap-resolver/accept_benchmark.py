#!/usr/bin/env python3
"""Offline acceptance for the visual tap resolver against the 9 real pages.

Pairs each screenshot with its UI dump, extracts clickable bounds, and measures
geometric coverage of visual safe points. Read-only; never touches a device.
"""
from __future__ import annotations

import json
import sys
import time
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from resolver import ResolverConfig, resolve_image  # noqa: E402

EVIDENCE = Path(
    "/Users/a1234/.codex/visualizations/2026/08/06/"
    "019fd4e1-ac4b-7261-a10d-3358b6d75f76/multi-app-evidence"
)
PAGES = [
    ("xhs", "a"), ("xhs", "b"), ("xhs", "c"),
    ("douyin", "a"), ("douyin", "b"), ("douyin", "c"),
    ("xianyu", "a"), ("xianyu", "b"), ("xianyu", "c"),
]


def parse_bounds(raw: str) -> list[int] | None:
    raw = raw.strip()
    if not (raw.startswith("[") and "][" in raw):
        return None
    try:
        lt, rb = raw[1:].split("][")
        x1, y1 = (int(v) for v in lt.split(","))
        x2, y2 = (int(v) for v in rb.rstrip("]").split(","))
    except ValueError:
        return None
    return [x1, y1, x2 - x1, y2 - y1]


def clickable_bounds(xml_path: Path, screen_w: int, screen_h: int) -> list[list[int]]:
    tree = ET.parse(xml_path)
    seen: set[tuple[int, int, int, int]] = set()
    out: list[list[int]] = []
    for node in tree.iter("node"):
        if node.get("clickable") != "true" or node.get("enabled") == "false":
            continue
        box = parse_bounds(node.get("bounds", ""))
        if not box:
            continue
        x, y, w, h = box
        if w < 8 or h < 8:
            continue
        if w * h > screen_w * screen_h * 0.25:
            continue
        key = (x, y, w, h)
        if key in seen:
            continue
        seen.add(key)
        out.append(box)
    return out


def main() -> int:
    runs = int(sys.argv[1]) if len(sys.argv) > 1 else 3
    config = ResolverConfig()
    rows = []
    for app, page in PAGES:
        png = EVIDENCE / app / f"page-{page}.png"
        xml = EVIDENCE / app / f"page-{page}.xml"
        if not png.exists():
            continue
        # warm decode for dims
        first = resolve_image(png, config)
        sw, sh = first["input"]["sourceResolution"]
        gt = clickable_bounds(xml, sw, sh) if xml.exists() else []

        times = []
        result = first
        for _ in range(runs):
            t0 = time.perf_counter()
            result = resolve_image(png, config)
            times.append((time.perf_counter() - t0) * 1000)
        times.sort()
        med = times[len(times) // 2]

        blocks = result["blocks"]
        media = result.get("mediaRegions", [])
        covered = 0
        for box in gt:
            x, y, w, h = box
            hit = any(
                x <= b["sourceSafePoint"][0] < x + w and y <= b["sourceSafePoint"][1] < y + h
                for b in blocks
            )
            if hit:
                covered += 1
        cov = f"{covered}/{len(gt)}" if gt else "n/a"
        pct = f"{covered/len(gt)*100:.1f}%" if gt else "  -  "
        rows.append((f"{app}-{page}", len(blocks), len(media), med, cov, pct))
        print(f"{app}-{page:>2}  blocks={len(blocks):>3}  media={len(media)}  "
              f"med={med:7.1f}ms  cover={cov:>8} {pct}")

    print("\nAcceptance (handoff §8):")
    dc = next(r for r in rows if r[0] == "douyin-c")
    print(f"  douyin-c candidates <= 40 : {dc[1]}  {'PASS' if dc[1] <= 40 else 'FAIL'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
