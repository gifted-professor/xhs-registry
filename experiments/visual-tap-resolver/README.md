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

## Speed & accuracy stages (2026-08-10)

Local block-split chain was reworked in stages (commits carry the tag; see the
registry `PROGRESS.md` section and knowledge `visual-tap-resolver-cv-split-20260810`).

- **A — bit-identical speedup**: single shared gray pass, bbox-scoped media
  masks, overlap prefilter, parallel refine (output byte-identical, serial
  fallback), full-rect safe-point analytic shortcut. Synthetic total
  **588.8ms → 182.8ms**.
- **B — A/B GrabCut reduction** (config switches, all off by default):
  `--grabcut-iters 1` → **111ms**; `--skip-compact-grabcut --compact-score 0.70`
  → **40.5ms**. B1 was the first `ResolverConfig` field addition and is the
  **manifest-change commit**: the serialized `config` is part of the
  `candidate_manifest_id` basis, so toggling any flag forces consumers to
  re-emit vision packs. `--workers` is *not* a config field and never touches
  the manifest.
- **C — accuracy**: `--half-res-media --merge-media --min-component-score F`
  cut the immersive fixture (douyin 256-cap proxy) from ~180 blocks to
  **18–21** while keeping every named control; `classify_kind` adds
  icon/button/card semantics (`--no-kind-taxonomy` reverts); the C3 test gates
  assert all 12 synthetic hit regions and all 9 immersive controls.
- **D — OCR crash fix**: oneDNN is disabled before PaddleOCR init
  (`FLAGS_use_mkldnn=0` / `PADDLE_PDX_DISABLE_MKLDNN=1` /
  `enable_mkldnn=False`); `resolve --ocr` runs on this machine.

`visual_tap_demo.py immersive --output-dir <dir>` generates the douyin-like
fixture (texture band + 5 named controls + 4 tabs + `ground-truth.json`).
`accept_benchmark.py` is the real-page acceptance template:

```bash
.venv-ocr/Scripts/python.exe accept_benchmark.py \
  --evidence <evidence-root> --half-res-media --merge-media --min-component-score 0.55
```

Evidence migration checklist (real-page gates stay deferred until this is done):
source machine `DESKTOP-3I1EVHE`; source roots `C:\Users\Public\xhs-agent-runs`
(long-lived) and `...\Temp\xhs-explore` (transient/config-machine); copy the 9
`page-{a,b,c}.{png,xml}` pairs per app (`xhs`/`douyin`/`xianyu`) into
`<evidence-root>/{app}/`, verify end-to-end SHA-256, and confirm each page by the
XML `package=` attribute (file names are not identity). Never commit binary
screenshots. With no evidence the script exits cleanly ("evidence not present",
code 2) — it never crashes and never reports a false PASS.

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
