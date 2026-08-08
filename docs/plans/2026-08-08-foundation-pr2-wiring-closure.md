# Foundation PR2 wiring closure（2026-08-08 post-merge）

分支：`foundation/pr2-wiring-closure`（基于 main @ `a305f59`，PR3 已合入之后）

> **状态：Merged to main via PR #6 (`b1e5e70`) · paired Routing #43 (`fb7747f`) · Not deployed · Pilot inactive · PR4 gate open**

## Round-2 findings addressed (Registry)

| Finding | Fix |
|---|---|
| Blocker 1 stable `operationKey` | Worker submits `idempotencyKey: assignment.operationKey` only; no attempt suffix / slice |
| Blocker 2 Scheduler constraints | Orchestrator uses `executionPlan.constraints`; business forced 1/false/1 |
| Blocker 3 hash recompute | `assertExecutionPlan()` canonical rehash → `EXECUTION_PLAN_HASH_MISMATCH` |
| High 1 route auth fail-open | Require `authorization.decision === "allow"` + non-empty `decisionId` |
| High 2 final decisionId | Receipt prefers Job auth decisionId; pre-submit uses `null` (no `"unbound"`) |
| Medium retryClass | Integrity-bound reads only `boundNode.retryClass` |
| Medium binder assertions | Exact raw↔live effect/retry mismatch |
| Medium parent symlink | Segment-wise `lstat` rejects parent-directory symlinks |
| Medium receipt fencing | v2 fences executionPlanHash/operationKey/contract/algo/closure |
| Blocker 4 expected hashes on submit | Registry **sends** expected*; Routing #43 enforces atomically in `submitJob` |

## Paired heads

- Registry merge: `b1e5e70` (PR #6)
- Routing merge: `fb7747f` (PR #43); historical PR2 tip `aca4d52` (PR #41), not intermediate `524a675`
- Handoff: `HANDOFF-2026-08-08-foundation-pr4-gate.md`

## Red lines

0 deploy · 0 Windows reload · 0 Pilot · 0 device I/O
