# Foundation → PR4 开闸交接（2026-08-08）

## 一句话状态

PR2 wiring closure + submit integrity lock **已源码合入两侧 main**，独立复审通过（自审 Approve 被 GitHub 拒，以复审记录为准）。  
**可以开始 PR4（DeployShadow / Pilot）**；**尚未** Windows 部署、reload、ActivatePilot、真机 canary。

不要把当前状态说成「integrity 已上线」或「Pilot 已开」——只是 **source merged · not deployed · pilot inactive**，且 PR4 闸门已开。

## 冻结锚点（merge 后 main）

| 仓 | PR | merge commit | 说明 |
|---|---|---|---|
| Routing `xhs-device-agent` | [#43](https://github.com/gifted-professor/xhs-device-agent/pull/43) | `fb7747f` | submit-time `expected*` 原子锁；presence fail-closed；catalog/auth 暴露 algorithm |
| Registry `xhs-registry` | [#6](https://github.com/gifted-professor/xhs-registry/pull/6) | `b1e5e70` | ExecutionPlan 强制；stable `operationKey`；constraints；hash 重算；route allow+decisionId；receipt 最终 decisionId；父目录 symlink；submit 携带 `expected*` |

**合并顺序（已执行）**：Routing #43 → Registry #6（中间未部署）。

历史配对（勿混）：
- 原 PR2 routing tip：`aca4d52`（PR #41），不是中间 `524a675`
- Registry wiring round-1：`57c1b42` → round-2：`6853d3b` → merge `b1e5e70`

## 本轮已闭合（接手不必重做）

### Registry #6（含 round-2 REQUEST CHANGES）
- Orchestrator **必须** ExecutionPlan；`assertExecutionPlan` 重算 canonical hash
- Assignment 带 `boundNode`；Worker 读 integrity / `retryClass` 只从 bound
- Worker **不再**本地判 risk/R2/idempotency/automation
- Submit 只用稳定 `assignment.operationKey`（无 attempt 后缀）
- Scheduler **只**用 `executionPlan.constraints`（business → 1/false/1）
- Route fail-closed：`authorization.decision === "allow"` + 非空 `decisionId`
- Receipt v2：最终 Job `authorizationDecisionId`；`notSent` → `null`（无 `"unbound"`）
- 父目录 symlink fail-closed；v2 fencing；submit 带 `expectedCapabilityContractHash|Algorithm|expectedImplementationClosureHash`

### Routing #43
- `submitJob` 内、建 Job/lease **之前** `assertExpectedImplementationAtSubmit`
- presence 对称 fail-closed；algorithm 校验
- Catalog / auth snapshot 暴露 `capabilityContractHashAlgorithm`
- 缺 `expected*` → legacy 兼容（有意）

### 复审结论
- Verdict：**Approve（配对）**；无 P0/P1/P2 blocker
- Residual（不阻塞）：`expected*` 全 null ≡ omit → legacy；Worker post-submit snapshot 仍「双侧皆有才比」；部分 plan 文案可能仍写「in progress」

### 测试债（已知、非本切片引入）
Registry 全量约 `258 / 256 pass / 2 fail`：
1. concurrent observer screen singleflight（`0 !== 1` READ）
2. filesystem/Git verifiers Windows symlink `EPERM`

Wiring / submit-lock focused suites：绿。

## 红线（PR4 开工后仍默认守，除非切片显式开闸）

```text
0 Windows deploy / reload     ← 除非 PR4 DeployShadow 闸门显式通过
0 ActivatePilot               ← 除非 Pilot 闸门显式通过
0 真机业务 canary / 支付路径
0 无 lease 旁路碰机
中间禁止「合了就 reload」
```

## 下一步：PR4

**范围（既有命名）**：`DeployShadow` →（另闸）`ActivatePilot` / 真机 canary。

### 已完成（PR4-0）

- 计划稿：`docs/plans/2026-08-08-foundation-pr4-plan.md`（含 2026-08-09 review 收口）
- 基线：`docs/plans/2026-08-08-foundation-pr4-baseline.md`（含控制面 down / CRLF / 四层漂移）
- 范围机读：`docs/plans/2026-08-08-foundation-pr4.files.json`
- 进度：`docs/plans/2026-08-08-foundation-pr4-progress.md`
- Bridge review：`outbox/claude-bridge/20260808-235037-9081d5e7/review.md`
- 交互实测加厚：`outbox/claude-bridge/20260809-live-verify-notes.md`

### 建议后续（别跳过闸门）

1. ~~写 PR4 计划 + baseline~~ → **已完成**
2. ~~review findings 收口进 plan~~ → **已完成**
3. **DeployShadow runbook Draft**（fetch / CRLF / 回滚 vs requireMainOrigin / 控制面 precondition）；补 routing 仓对称指针
4. **先恢复 17920**，再谈 **闸 A** DeployShadow
5. **闸 B** ActivatePilot / 最小非支付 canary（L 级）；支付 / final commit 仍人确认

**明确延后（非 PR4 merge prerequisite）**：
- 闲鱼真 TCB / manifest 挂满 live capabilities
- 用 Pilot 宣称「多设备生产已上线」

## 关键指针

| 读什么 | 路径 |
|---|---|
| 冷启动 | `AGENTS.md` → live `agent-entry.md` |
| 本仓总状 | `PROGRESS.md`（顶节应反映 wiring 已合、PR4 可开） |
| wiring 设计 | `docs/plans/2026-08-08-foundation-pr2-wiring-closure.md` |
| PR2/PR3 进度 | `docs/plans/2026-08-08-foundation-pr2-progress.md`、`…-pr3-progress.md` |
| 治理分流 | `modes/governance.md` |

## 接手三问（答不出不准部署）

1. 当前 Windows live HEAD / task-launch 是否仍是 **旧** release（预期：是，尚未 DeployShadow）？
2. PR4 本切片是 **只写 Draft**，还是 **已获人确认可 DeployShadow**？
3. Pilot / 真机 canary 是否 **另闸**（默认：是）？

## 给下一任的最短命令

```bash
# 核对两侧 main 锚点
gh api repos/gifted-professor/xhs-registry/commits/main --jq .sha
gh api repos/gifted-professor/xhs-device-agent/commits/main --jq .sha
# 期望含：registry b1e5e70… / routing fb7747f…

# 不要默认执行：
# schtasks reload · 对照部署 · ActivatePilot · 碰机 job
```

## 会话上下文

- 对话 transcript：`6252af21-d877-4a09-89ef-d753b2c3f63c`（Cursor agent-transcripts）
- 流程已走完：Review →（自审 Approve 不可）→ Merge #43→#6 → **PR4 闸门打开**
- 用户确认：可以开始 PR4；下一步先写计划/Draft，不默认部署
- PR4-0 计划/baseline 已写（2026-08-08）；bridge + 2026-08-09 实测 findings 已收口进文（2026-08-09）
- 下一步：PR4-1 runbook；**控制面 down 时不开闸 A**；仍 0 deploy
