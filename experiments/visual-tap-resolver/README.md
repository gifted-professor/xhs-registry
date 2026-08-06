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

On Windows, use the venv under `Scripts`:

```powershell
py -3.12 -m venv .venv-ocr
.\.venv-ocr\Scripts\python.exe -m pip install -r requirements.txt
```

## Vision chooses a block; code owns coordinates

Create a query-bound pack and annotated overlay for an LLM vision call:

```powershell
.\.venv-ocr\Scripts\python.exe visual_tap_demo.py vision-pack `
  --input shot.png `
  --output-dir out\vision `
  --query "微信底部的通讯录入口"
```

Send `vision-overlay-all.png` with `vision-prompt.txt` to the model. The model
must return JSON containing the exact `selectionRequestId`, `frameId`, and
`manifestId`, plus either one listed `blockId` or an explicit
`ambiguous`/`not_found` status. It must never return coordinates.

Validate a saved model response:

```powershell
.\.venv-ocr\Scripts\python.exe visual_tap_demo.py select `
  --input shot.png `
  --blocks out\vision\blocks.json `
  --pack out\vision\vision-pack.json `
  --overlay out\vision\vision-overlay-all.png `
  --prompt out\vision\vision-prompt.txt `
  --decision decision.json `
  --output out\vision\verified-point.json
```

The validator rejects cross-frame, stale-frame, cross-query, changed-manifest,
changed-overlay, unknown-block, raw-coordinate, low-confidence, and malformed
responses. A successful result is still `effect=none`, `tapAuthorized=false`,
and `executionEligibility=offline_only`.

Offline screenshots only prove coordinates in `source-image-pixels`. They do
not prove Android physical-screen coordinates. A future live adapter must add
trusted device/session/capture metadata (display geometry, rotation, crop,
insets, monotonic capture sequence, foreground package) and must capture again
immediately before any separately authorized tap.

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

`vision-pack` additionally writes:

- `vision-overlay-all.png`: every ID that Vision is allowed to select;
- `vision-pack.json`: frame + candidate-manifest + query + overlay bindings;
- `vision-prompt.txt`: strict block-only response instructions.

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
