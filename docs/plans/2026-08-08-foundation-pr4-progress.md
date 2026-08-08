# Foundation PR4 progress（2026-08-08 → 2026-08-09）

> **状态：Plan Draft · review findings 已收口 · Not deployed · Pilot inactive · 控制面曾实测 down**  
> 计划：`2026-08-08-foundation-pr4-plan.md`  
> 基线：`2026-08-08-foundation-pr4-baseline.md`

## PR4-0 — 计划 + baseline

- [x] 写计划稿（DeployShadow ≠ ActivatePilot；部署对象 / SHA / 回滚 / 探针）
- [x] 采 live baseline（旧 shadow；pin/checkout 漂移）
- [x] `foundation-pr4.files.json`（Gate A/B 授权机读）
- [x] Bridge review `20260808-235037-9081d5e7`（P1 回滚锚点 / P2 fetch·GO 语义）
- [x] 交互实测加厚 2026-08-09（控制面 down、CRLF、双仓缺对象、`requireMainOrigin` vs feature 分支）→ **已补进 plan/baseline/files.json**
- [x] PR4-0 docs 提交 `e0db476`（`foundation/pr4-deploy-shadow`）
- [x] PR4-1 DeployShadow **runbook Draft**（`2026-08-08-foundation-pr4-runbook.md`；fetch/对齐、备份锚点、git-show LF 部署、GO 探针、回滚 D0/D1）
- [ ] routing 仓对称指针（PR4-1 前补）
- [ ] **人审 runbook Draft** → 之后才谈闸 A 执行

## 未做（红线）

- [ ] 恢复控制面 17920（闸 A 前置，非本切片默认动作）
- [ ] DeployShadow 执行 / Windows reload
- [ ] ActivatePilot
- [ ] 真机 canary

## 下一步

1. **人审 PR4-1 runbook Draft**（含决策点 D0 控制面恢复 / D1 回滚 `requireMainOrigin` 取舍、`windowsRegistryCommit` 收口）
2. 恢复控制面并重采 baseline liveness 后，人显式批 **闸 A** 才 DeployShadow

## 取消

- Bridge 重跑 bundle `20260809-001949-fb6de338`（快照与首轮相同，未外发；以实测加厚为准）
