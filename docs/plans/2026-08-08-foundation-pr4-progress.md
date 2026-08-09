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
- [x] **人审 runbook 通过**（2026-08-09）：D0 按主流程 / D1 事故留痕 + 旧状态清理入 §11 / `windowsRegistryCommit` 统一
- [ ] routing 仓对称指针（PR4-1 前补）
- [ ] 恢复控制面 + 重采 liveness → 人显式批 **闸 A** 才执行

## 未做（红线）

- [ ] 恢复控制面 17920（闸 A 前置，非本切片默认动作）
- [ ] DeployShadow 执行 / Windows reload
- [ ] ActivatePilot
- [ ] 真机 canary

## 下一步

1. （可选）补 routing 仓对称指针
2. **恢复控制面 17920** + 重采 liveness baseline
3. 预检 #1–#5 全绿后，人显式批 **闸 A** 才执行 runbook（DeployShadow）
4. DeployShadow 后按 runbook §11 清旧分支/陈旧 ref（贴人确认再删）

## 取消

- Bridge 重跑 bundle `20260809-001949-fb6de338`（快照与首轮相同，未外发；以实测加厚为准）
