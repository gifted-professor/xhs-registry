# Visual Tap Resolver demo

Offline proof of concept for the fallback path described in
[`docs/plans/2026-08-06-visual-tap-resolver-demo-design.md`](../../docs/plans/2026-08-06-visual-tap-resolver-demo-design.md).

It reads an existing screenshot, proposes stable visual blocks, optionally
refines component proposals with GrabCut, calculates a safe interior point, and
writes JSON plus an annotated image. It never connects to a device and never
emits a tap.

## Setup

```bash
cd experiments/visual-tap-resolver
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

## Try it

Generate a deterministic phone-like fixture and resolve it:

```bash
.venv/bin/python visual_tap_demo.py synthetic --output-dir /tmp/visual-tap-synthetic
.venv/bin/python visual_tap_demo.py resolve \
  --input /tmp/visual-tap-synthetic/screen.png \
  --output-dir /tmp/visual-tap-result \
  --write-masks
```

Benchmark only the local algorithm:

```bash
.venv/bin/python visual_tap_demo.py benchmark \
  --input /tmp/visual-tap-synthetic/screen.png \
  --iterations 20 \
  --reference-dump-ms 7000
```

`--reference-dump-ms` is optional and never runs a dump. Use a measurement from
the same page/device/path; otherwise the reported ratio is illustrative only.

Outputs:

- `blocks.json`: screenshot hash, coordinate transform, blocks, safe points,
  and stage timings;
- `overlay.png`: root-level rows/controls and safe points;
- `overlay-all.png`: all fine-grained child blocks for debugging;
- `masks/`: optional debug masks.

## Interpreting the result

The demo discovers visual regions; it does **not** prove Android clickability or
understand business meaning. A future resolver may let an LLM choose a
`blockId`, but the LLM must not invent or transform physical coordinates.
Fine-grained icon/text blocks inside a detected row receive `parentBlockId`;
the default overlay shows only root blocks to avoid an unreadable wall of IDs.

For a fair runtime comparison, measure acquisition separately:

```text
dump path  = dump acquisition + transfer + XML parse
local path = screenshot acquisition + transfer + local resolve
LLM path   = screenshot acquisition + upload + remote inference
```

## Tests

```bash
.venv/bin/python -m unittest discover -s tests -v
```
