#!/usr/bin/env python3
"""Offline acceptance for the visual tap resolver against the 9 real pages.

Pairs each screenshot with its UI dump, extracts clickable bounds, and measures
geometric coverage of visual safe points. Read-only; never touches a device.

Evidence is NOT committed to this repo (HANDOFF §10). Point this script at a
migrated evidence tree with ``--evidence`` or ``$VISUAL_TAP_EVIDENCE``:

  source machine  DESKTOP-3I1EVHE
  source roots    C:\\Users\\Public\\xhs-agent-runs   (long-lived)
                  ...\\Temp\\xhs-explore              (transient / config machine)
  layout          <root>/{xhs,douyin,xianyu}/page-{a,b,c}.{png,xml}

When migrating: verify end-to-end SHA-256 and confirm the app by the XML
``package=`` attribute (file names are not identity, HANDOFF §3.4). Missing
evidence produces a clean "evidence not present" exit (code 2) — never a
crash, never a false PASS.

The A/B switches from visual_tap_demo are accepted here too (--half-res-media,
--merge-media, --min-component-score, ...), so the gates below measure the
resolver under the exact config the douyin-256-cap cut relies on.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from resolver import ResolverConfig, resolve_image  # noqa: E402
from visual_tap_demo import add_config_args, build_config  # noqa: E402

PAGES = [
    ("xhs", "a"), ("xhs", "b"), ("xhs", "c"),
    ("douyin", "a"), ("douyin", "b"), ("douyin", "c"),
    ("xianyu", "a"), ("xianyu", "b"), ("xianyu", "c"),
]
# HANDOFF §6 acceptance numbers — the real-page gates that the local
# synthetic/immersive tests proxy for. They only run once evidence is migrated.
DEFAULT_EXPECT = {
    "douyin_c_blocks": 40,   # immersive 256-cap candidate cut
    "coverage_total": 90.0,  # 26-dump compact-region coverage
    "coverage_xhs": 88.0,
    "coverage_xianyu": 88.0,
}

# Exit codes: 0 all gates PASS, 1 a gate FAILed, 2 evidence not present (skip).
EXIT_EVIDENCE_MISSING = 2


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


def parse_expect(raw: str) -> dict[str, float]:
    """``--expect`` accepts an inline JSON object or a path to a JSON file."""
    text = raw
    if not raw.startswith("{"):
        text = Path(raw).read_text(encoding="utf-8")
    overrides = json.loads(text)
    merged = dict(DEFAULT_EXPECT)
    merged.update({key: float(value) for key, value in overrides.items()})
    return merged


def add_common_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--evidence", default="",
                        help="evidence tree root (else $VISUAL_TAP_EVIDENCE)")
    parser.add_argument("--expect", default="",
                        help="gate thresholds: inline JSON object or file path")
    parser.add_argument("--runs", type=int, default=3, metavar="N",
                        help="benchmark repetitions per page (default: 3)")
    parser.add_argument("--max-side", type=int, default=ResolverConfig.max_side)
    parser.add_argument("--max-blocks", type=int, default=ResolverConfig.max_blocks)
    add_config_args(parser)


def _pct(covs: list[float]) -> float:
    return (sum(covs) / len(covs) * 100) if covs else float("nan")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    add_common_args(parser)
    args = parser.parse_args(argv)
    expect = parse_expect(args.expect) if args.expect else dict(DEFAULT_EXPECT)

    evidence_raw = args.evidence or os.environ.get("VISUAL_TAP_EVIDENCE", "")
    evidence = Path(evidence_raw) if evidence_raw else Path()
    if not evidence_raw or not evidence.exists():
        print(f"evidence not present: {evidence_raw or '(VISUAL_TAP_EVIDENCE unset)'}")
        print("migrate the 9 page-{a,b,c}.{png,xml} pairs from DESKTOP-3I1EVHE "
              "(see README evidence-migration checklist) and re-run.")
        return EXIT_EVIDENCE_MISSING

    config = build_config(args)
    rows = []
    app_cov: dict[str, list[float]] = {app: [] for app, _ in PAGES}
    for app, page in PAGES:
        png = evidence / app / f"page-{page}.png"
        xml = evidence / app / f"page-{page}.xml"
        if not png.exists():
            continue
        # warm decode for dims
        first = resolve_image(png, config)
        sw, sh = first["input"]["sourceResolution"]
        gt = clickable_bounds(xml, sw, sh) if xml.exists() else []

        times = []
        result = first
        for _ in range(args.runs):
            t0 = time.perf_counter()
            result = resolve_image(png, config)
            times.append((time.perf_counter() - t0) * 1000)
        times.sort()
        med = times[len(times) // 2]

        blocks = result["blocks"]
        media = result.get("mediaRegions", [])
        covered = sum(
            1
            for box in gt
            if any(
                box[0] <= b["sourceSafePoint"][0] < box[0] + box[2]
                and box[1] <= b["sourceSafePoint"][1] < box[1] + box[3]
                for b in blocks
            )
        )
        if gt:
            app_cov[app].append(covered / len(gt))
        cov = f"{covered}/{len(gt)}" if gt else "n/a"
        pct = f"{covered / len(gt) * 100:.1f}%" if gt else "  -  "
        rows.append((f"{app}-{page}", len(blocks), len(media), med, cov, pct))
        print(f"{app}-{page:>2}  blocks={len(blocks):>3}  media={len(media)}  "
              f"med={med:7.1f}ms  cover={cov:>8} {pct}")

    print("\nAcceptance (handoff targets):")
    failed = False

    dc = next((r for r in rows if r[0] == "douyin-c"), None)
    if dc is None:
        print("  douyin-c candidates           : SKIP (evidence missing page)")
    else:
        ok = dc[1] <= expect["douyin_c_blocks"]
        failed |= not ok
        print(f"  douyin-c candidates            : {dc[1]:<7} {'PASS' if ok else 'FAIL'}")

    all_cov = [c for covs in app_cov.values() for c in covs]
    total = _pct(all_cov)
    ok = bool(all_cov) and total >= expect["coverage_total"]
    failed |= bool(all_cov) and not ok
    print(f"  total coverage                 : {total:7.1f}% {'PASS' if ok else ('FAIL' if all_cov else 'SKIP')}")

    for app in ("xhs", "xianyu"):
        covs = app_cov[app]
        avg = _pct(covs)
        ok = bool(covs) and avg >= expect[f"coverage_{app}"]
        failed |= bool(covs) and not ok
        print(f"  {app} coverage                  : {avg:7.1f}% {'PASS' if ok else ('FAIL' if covs else 'SKIP')}")

    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
