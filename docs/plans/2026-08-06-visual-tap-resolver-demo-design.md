# Visual Tap Resolver demo design

## Goal

Prove that a local image algorithm can resolve stable navigation controls and
list rows faster than an LLM vision round trip when Android UI hierarchy dumps
are empty, sparse, or slow. The demo is offline and read-only: it consumes an
existing screenshot and never connects to a device or emits a tap.

This is a fallback resolver, not a replacement for semantic UI dumps. Runtime
trust order remains:

1. valid semantic dump bounds;
2. high-confidence local visual block;
3. LLM vision selecting a visual `blockId`;
4. fail closed.

Dump and screenshot analysis may eventually run concurrently. Trust priority
does not require serially waiting for a slow dump before starting local image
work.

## Scope

The first demo targets stable chrome only:

- application icons;
- top-bar buttons;
- bottom navigation tabs;
- list rows;
- dialog buttons;
- rectangular, circular, hollow, and mildly irregular controls.

It does not identify objects inside video content, infer business meaning, tap
a device, or claim a region is clickable merely because it is visually
distinct.

## Pipeline

1. Load a PNG/JPEG and retain its SHA-256 and physical resolution.
2. Resize a copy to a bounded analysis resolution and persist the exact inverse
   coordinate transform.
3. Generate coarse proposals from edges, connected components, and simple
   horizontal row grouping.
4. For suitable proposals, apply a RockClimbing-inspired padded crop and
   GrabCut refinement.
5. Select the connected foreground component that best overlaps the proposal.
6. Clean its mask with close/open operations and small-hole filling.
7. Calculate a safe point with a distance transform: the foreground pixel
   farthest from the mask boundary, rather than the geometric box center.
8. Map the safe point back to source-image coordinates.
9. Emit JSON plus an overlay PNG containing `blockId`, bounds, and safe point.

Each result binds to the exact input SHA and records the method, confidence,
analysis/source resolutions, transform, mask area, bounds, safe point, and
timing stages. Stale coordinates cannot be reused against another screenshot.

## CLI and artifacts

```bash
python visual_tap_demo.py resolve --input screen.png --output-dir out
python visual_tap_demo.py benchmark --input screen.png --iterations 20
python visual_tap_demo.py synthetic --output-dir out/synthetic
```

`resolve` writes:

- `blocks.json`: machine-readable proposals;
- `overlay.png`: source screenshot with numbered blocks and safe points;
- `masks/`: optional per-block masks for debugging.

`benchmark` measures decoding, proposal generation, refinement, rendering, and
total wall time separately. Screenshot acquisition is deliberately outside the
algorithm timer and must be measured independently when compared with a real
dump path.

## Acceptance

The demo passes when:

- synthetic fixtures cover rectangles, circles, hollow shapes, rows, overlap,
  and multiple resolutions;
- every accepted synthetic safe point lies inside its ground-truth hit region;
- source/analysis/source round-trip coordinate error is at most one pixel;
- output is deterministic for the same screenshot and configuration;
- the CLI reports measured latency without claiming device or LLM speed;
- unit tests and syntax checks pass;
- no Windows connection, lease, job, session, ADB, or tap occurs.

## Follow-up gate

Only after offline acceptance should a separate lab-only
`vision.resolve_tap_dry_run` integration consume raw per-device screenshots.
That stage must render an overlay for human review before any formal session or
job is allowed to execute a coordinate.
