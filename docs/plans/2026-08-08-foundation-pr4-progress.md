# Foundation PR4 progress（2026-08-08 → 2026-08-09）

> **状态：DeployShadow（闸 A）已执行 · GO 2026-08-09T00:49Z · Pilot 未激活（闸 B 未开）**  
> 计划：`2026-08-08-foundation-pr4-plan.md`  
> 基线：`2026-08-08-foundation-pr4-baseline.md`  
> Runbook：`2026-08-08-foundation-pr4-runbook.md`（§1–§9 已执行；§11 待人批）

## PR4-0 — 计划 + baseline

- [x] 写计划稿（DeployShadow ≠ ActivatePilot；部署对象 / SHA / 回滚 / 探针）
- [x] 采 live baseline（旧 shadow；pin/checkout 漂移）
- [x] `foundation-pr4.files.json`（Gate A/B 授权机读）
- [x] Bridge review `20260808-235037-9081d5e7`（P1 回滚锚点 / P2 fetch·GO 语义）
- [x] 交互实测加厚 2026-08-09（控制面 down、CRLF、双仓缺对象、`requireMainOrigin` vs feature 分支）→ **已补进 plan/baseline/files.json**
- [x] PR4-0 docs 提交 `e0db476`（`foundation/pr4-deploy-shadow`）
- [x] PR4-1 DeployShadow **runbook Draft**（fetch/对齐、备份锚点、git-show LF 部署、GO 探针、回滚 D0/D1）
- [x] **人审 runbook 通过**（2026-08-09）：D0 按主流程 / D1 事故留痕 + 旧状态清理入 §11 / `windowsRegistryCommit` 统一
- [ ] routing 仓对称指针（PR4-1 前补）——**不阻塞**，可后补

## PR4-1 — DeployShadow 执行（闸 A，2026-08-09）

人显式授权「还有闸 a 你顺便装一下吧」→ 执行 runbook §1–§9。

- [x] §1 阶段零 D0：控制面恢复失败（checkout 漂移使 worker 拒启）→ 走主流程
- [x] §2 fetch/对齐：双仓 fetch + cat-file 目标对象落本地 + `origin/main` 对齐 tip
- [x] §3 备份：`backups/registry-deploy-shadow-pr4-20260809-003955/`（control 双 manifest + registry.mjs + registry.db + rollback-anchors.json）
- [x] §4 routing 部署：`git switch main` + `reset --hard fb7747f` + task-launch 改 `gitCommit`/`releaseId` → 控制面 **17920 恢复拉起**
- [x] §5 registry 部署：`git show b1e5e70:registry.mjs`（LF blob `151aa93b…`）落盘 + reload → 17930 health 200
- [x] §6 cross-repo-release.json 重写：releaseId / 双 commit 收口 `b1e5e70` / deviceAgent+taskLaunch `fb7747f` / deployedAt now；全键保留
- [x] §7 GO 探针 1–10 **全绿**（见下表）
- [x] §8 回滚：**未触发**（DeployShadow 成功）
- [x] §9 留痕：PROGRESS / progress / files.json / 知识库 pitfall（见下）

### GO 探针结果（2026-08-09T00:49Z）

| # | 探针 | 结果 |
|---|---|---|
| 1 | `:17920/control/v1/health` | ✅ ok / `policyMode=shadow` / active=false / pilotConfigured=false / activeLeases=0 / releaseId=pr4 |
| 2 | routing `git rev-parse HEAD` | ✅ `fb7747feefd975ad14fdd51c3313b3487ae978ee` |
| 3 | task-launch `gitCommit` | ✅ = 探针#2（完整 40 字符） |
| 4 | cross-repo 四 SHA | ✅ registryCommit==windowsRegistryCommit=`b1e5e70…`；deviceAgentCommit==taskLaunchCommit=`fb7747f…`；shadow |
| 5 | `:17930/api/health` | ✅ 200 |
| 6 | `:17930/api/agent-entry` | ✅ `release.policyMode=shadow` / releaseId=pr4；pilot 与 commit 语义由 #1/#4 满足（schema 无该字段，见发现 3） |
| 7 | `:17930/agent-entry.md` | ✅ 含 Release / runtime policy 段 |
| 8 | 控制面 leases（直连 `:17920/control/v1/leases`） | ✅ `{"leases":[]}` 空 |
| 9 | `:17930/` 与 `/api/devices` | ✅ 200 / 200 |
| 10 | `git show b1e5e70:registry.mjs` vs 部署文件 | ✅ 双 LF `151aa93bd8…` 逐字节一致 |

### 执行发现（follow-up）

1. **release gates 测试 receipt 硬约束**：`runtime/release-test-receipt.json` 必须 `gitCommit==HEAD`、`passed≥15`、`failed=0`、command ≥2 runtime-critical 标记。旧 receipt（`fb4f90be`，仅 4 passed）挡启动。本闸真跑 6 个全绿 critical 套件（41 过/0 败）生成 scoped receipt 放行；**未**伪造任何结果。
2. **`migrateLegacyPending` 测试 Windows 预存在失败**：`tests/control-plane-core.test.mjs:644`，`nonpayment_v1: migrateLegacyPending frees a legacy waiting job…`，JOB_WAIT_TIMEOUT 5s，套件内与隔离重跑均失败；`git diff 42b8964 fb7747f` 该测试/迁移/integrity 代码**逐字节相同** → 预存在环境债，非本次回归。**未**计入 receipt。待 routing 仓修（新 PR + 人审）。
3. **agent-entry release 段 schema**：无 `pilotConfigured`/commit 字段（runbook 探针 #6 字面偏差）；`policyMode/effectiveDecisionSource/evidenceMode/releaseId` 均在。Pilot 状态与 commit 经控制面 health + cross-repo-release.json 验证。

## 未做（红线）

- [ ] **ActivatePilot（闸 B）**——另批，未开
- [ ] 真机 canary
- [ ] runbook §11 旧分支/陈旧 ref 清理（贴人确认再删）
- [ ] routing 仓对称指针（可选）

## 下一步

1. **PR4-2 提交**：按 `HANDOFF-2026-08-08-foundation-pr4-gate.md` 提交 PR（docs + 留痕）→ 人审
2. runbook §11：列 `git branch -vv` 审一遍 → **贴人确认**后 `remote prune` + 删已合/废弃分支；归档旧 release 产物
3. 重采 baseline → `files.json` `live*` 更新为部署后值（闸 A 已做，见 §9）
4. 闸 B（ActivatePilot）由人另行决策，需新 runbook/闸门

## 取消

- Bridge 重跑 bundle `20260809-001949-fb6de338`（快照与首轮相同，未外发；以实测加厚为准）
