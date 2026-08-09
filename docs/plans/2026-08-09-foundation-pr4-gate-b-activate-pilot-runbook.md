# Foundation PR4-3 — ActivatePilot（闸 B）Runbook Draft（2026-08-09）

> **本文件状态：Draft · 未执行 · 0 live 动作**
> 依赖：闸 A 已执行（`rel-shadow-2026-08-08-foundation-pr4`，GO 2026-08-09T00:49Z）。
> 执行前置：**人显式开闸 B** 后才允许改配置 / reload / 提交试点任务；本 Draft 只供人审。
> 基线：闸 A 部署后实测（2026-08-09，见 §0）。

## 0. 当前状态（实测 2026-08-09）

| 项 | 实测值 | 注 |
|---|---|---|
| 控制面 17920 | 200 ok · `policyMode:{mode:"shadow",active:false,pilotOnly:false,pilotConfigured:false}` · 4 设备 · 29 能力 · activeLeases=0 | 全部 online、无 quarantine |
| task-launch | `gitCommit=fb7747f` · `autonomyPolicyMode:shadow` · pilot `[]`/`[]` | 闸 A 值 |
| cross-repo | `policyMode:shadow` · `pilotConfigured:false` | 闸 A 值 |
| registry 17930 | 200 · identities=4 | 正常 |

## 1. 目标状态（唯一 live 改动：task-launch + cross-repo + reload）

### 1.1 task-launch.json 改动

| 字段 | 闸 A（现在） | 闸 B（目标） |
|---|---|---|
| `autonomyPolicyMode` | `shadow` | **`nonpayment_v1`** |
| `pilotActors` | `[]` | **`["claude-pilot-20260809"]`** |
| `pilotAliases` | `[]` | **`["01","02","03","04"]`** |
| `releaseId` | `rel-shadow-2026-08-08-foundation-pr4` | **`rel-pilot-2026-08-09-foundation-pr4`** |
| 其余（gitCommit/evidenceMode/recipeOverlay*/require*） | 不变 | 不变 |

**语义确认**（读 `nonpayment-autonomy-policy.mjs` + `authorization-decision.mjs`）：
- `active` = mode==nonpayment_v1 && (fake || (real && pilotConfigured))。真 adapter 下必须 selectors 非空。
- `pilotOnly` = mode==nonpayment_v1 && adapterKind==real → 是。
- `isPilotScope` = pilotOnly && active && pilotConfigured && actor∈pilotActors && (alias∈pilotAliases **或** physicalLabel∈pilotAliases)。`01` alias 与 `rack-01` physicalLabel 均可命中。
- **名单外一律 block**：`pilotOnly && pilotScope==="out_of_scope"` → `AUTONOMY_PILOT_SCOPE_MISS`（authorization-decision.mjs:146）。隔离是硬的，不是软标记。
- **支付永远人闸**：`financial_commit` → `wait_financial_commit`（humanApprovalRequired + paymentHold），与 mode 无关。

### 1.2 cross-repo-release.json 改动

| 字段 | 新值 |
|---|---|
| `releaseId` | `rel-pilot-2026-08-09-foundation-pr4` |
| `policyMode` / `effectiveDecisionSource` | `nonpayment_v1` / `deployed-runtime` |
| `pilotActors` / `pilotAliases` | `["claude-pilot-20260809"]` / `["01","02","03","04"]` |
| `pilotConfigured` | `true` |
| 其余键 | 保留 |

### 1.3 reload 控制面

```powershell
schtasks /end /tn XhsDeviceControlPlaneV1
schtasks /run /tn XhsDeviceControlPlaneV1
curl.exe -s -m 5 http://127.0.0.1:17920/control/v1/health
# 期望：policyMode.mode == "nonpayment_v1" && active == true && pilotConfigured == true
```

## 2. 能力分层（按当前策略代码，非按历史跑过）

提交方式由**成熟度 + canary 位**决定（`authorization-decision.mjs:119`：E0/E1 或 lab_only → `CANARY_SESSION_REQUIRED`，除非 canary session）：

### Tier 1 — E2/E3 automatic · 可直接 `job submit`（不碰手机做只读/试写）

| 能力 | 成熟度 | risk | 来源 |
|---|---|---|---|
| `xianyu.observe.snapshot` | E2 | R0 | 274/298 ✅ |
| `xianyu.observe.image_manifest` | E2 | R0 | 4/5 |
| `xhs.observe.metrics` | E3 | R0 | 35/47 |
| `xhs.observe.feed` | E3 | R0 | 15/35（较低，观察类可跑） |
| `xhs.observe.note_detail` | E3 | R0 | 0/14（历史 0 成功，慎） |
| `xhs.explore.open_feed_note` | E2 | R0 | 22 次 |
| `douyin.observe.snapshot` | E2 | R0 | 14/26（只观察） |
| `douyin.observe.search` | E2 | R0 | 12/13 |
| `wechat.observe.main` / `probe` | E2 | R0 | 3/3 ✅ |
| `xiaowei.device.list` | E3 | R0 | 13/13 ✅ |
| `xianyu.publish.input_dry_run` | E2 | R1 | 14/19 |
| `xianyu.publish.open_dry_run` | E2 | R1 | 12/15 |
| `xianyu.publish.image_dry_run` | E2 | R1 | 7/10 |
| `xianyu.publish.full_dry_run` | E2 | R1 | 45/85（偏低，放最后） |

### Tier 2 — E1 / lab_only / canary_only · **必须 `session acquire --canary` + `session action`**

| 能力 | 成熟度 | risk | 注 |
|---|---|---|---|
| `xiaowei.explorer.primitive` | E1 | R1 | **explore 核心**，history 9992/10056 但全走 canary session |
| `xiaowei.lab.raw` | E1 | R1 | 原始动作，试点慎用 |
| `xianyu.probe.flutter_pointer_tap` | E1 | R1 | repair 点击类 |

提交路径：
```bash
# devicectl（在 Windows routing 仓）：
node control-plane/devicectl.mjs session acquire --actor claude-pilot-20260809 --alias 01 --capability xiaowei.explorer.primitive --canary
node control-plane/devicectl.mjs session action  --actor claude-pilot-20260809 --alias 01 --capability xiaowei.explorer.primitive --canary [--params ...]
# 或经 registry /api/operator/*（当前 501 冻结，不启用）
```

### 排除（红线）

- ❌ `douyin.observe.share_link` —— 01 恢复超时，人禁止继续碰
- ❌ `xhs.comment.send` —— internal/approval_gated/canary_only，且是外发副作用
- ❌ `xhs.follow.ensure` —— 未实现（MISSING）
- ❌ 一切 `financial_commit` / 支付 —— 策略硬闸，即便误提交也 wait_financial_commit

## 3. 分级试点计划（时间顺序 = 人确认 OK）

> 每级先探针全绿，人 checkpoint 后再进下一级。**任何一级失败 → 停，回滚 §6。**

### P1 — 01 只读 observe（最小暴露）
- 提交：`xianyu.observe.snapshot` · `wechat.observe.probe` · `xiaowei.device.list`（Tier 1，job submit，actor=claude-pilot-20260809）
- 探针：job succeeded + evidence 落库 + 截图存在（`/api/fleet/screen/01`）
- 成功标准：3 能力各 1 次成功，无 quarantine，无支付行为

### P2 — 扩 4 台 observe
- 同 Tier 1 observe，alias 01/02/03/04
- 探针：4 台各 ≥1 job 成功；`/control/v1/devices` 无新增 quarantine

### P3 — dry_run 试写（xianyu publish）
- `xianyu.publish.input/open/image_dry_run`（Tier 1，E2 R1）
- 探针：dry_run 返回 expected（不真发）；`approval_audit` 无新增；无 financial_commit 事件

### P4 — explorer + repair（canary session）
- `session acquire --canary` 跑 `xiaowei.explorer.primitive`（01 起步）；`xianyu.probe.flutter_pointer_tap`
- 探针：session 建立 → 动作成功 → session release；证据链完整
- **explorer 若在 01 异常**：不换机重试超 2 次，回滚

## 4. GO 探针（ActivatePilot 完成后，全部只读）

| # | 探针 | 期望 |
|---|---|---|
| 1 | `:17920/control/v1/health` | mode=`nonpayment_v1` · active=true · pilotOnly=true · pilotConfigured=true · pilotActors=`["claude-pilot-20260809"]` |
| 2 | task-launch `autonomyPolicyMode` | `nonpayment_v1` |
| 3 | cross-repo `policyMode` / `pilotConfigured` | `nonpayment_v1` / `true` |
| 4 | task-launch `gitCommit` | `fb7747f…`（不变） |
| 5 | `:17930/api/health` | 200 |
| 6 | `:17930/api/agent-entry` | `release.policyMode` 反映 pilot（闸 A 已知 schema 无 pilotConfigured 字段，语义经 #1/#3 满足） |
| 7 | `:17920/control/v1/leases` | 无非终态 lease（试点跑完即空） |
| 8 | 名单外 actor 提交（探针只读：用非 pilot actor 试 `planRoute`） | 返回 `AUTONOMY_PILOT_SCOPE_MISS` / block |
| 9 | 支付类能力 plan | `wait_financial_commit` / block（绝不放行） |

## 5. 试点任务提交的 actor 约定

- **固定一个身份**：`claude-pilot-20260809`（试点期间所有任务、session 都用它）。
- 任务实例靠 **jobId / idempotency-key** 区分，不靠 actor。
- 新增第二个运营者时才加第二个固定 actor（一个运营者 = 一个固定 actor，一份审计）。
- 历史 `codex-*/grok-*` 临时名是脚本时代产物，本闸不延续。

## 6. 回滚（ActivatePilot 失败或需撤）

1. task-launch：`autonomyPolicyMode`→`shadow`、`pilotActors`/`pilotAliases`→`[]`、`releaseId`→`rel-shadow-…`，reload 控制面。
2. cross-repo：同步回 shadow / false / `[]`。
3. 探针 #1/#3 复核回 shadow 态。
4. 若试点中已产生 lease/job：等终态或 cancel（`POST /control/v1/jobs/:id/cancel`），不硬杀。
5. 留痕：PROGRESS + progress 节记回滚 + 知识库 pitfall（若新坑）。

## 7. 留痕（执行后必须）

- PROGRESS.md 顶节改「ActivatePilot 已执行 + GO 时间戳 + releaseId + pilot 状态」
- `foundation-pr4-progress.md` 加闸 B 节：探针结果表 + 试点各级结果
- `foundation-pr4.files.json`：`status`→`gate-b-executed`，`gates.B_ActivatePilot`→GO 时间戳，`baselines.live*` 更新
- 试点各级结果写知识库（recipe/pitfall，带 `appliesTo`/`verifyMode`）

## 8. 人审结论（2026-08-09 待批）

- [ ] **pilotActors = `["claude-pilot-20260809"]`**（人已口头确认「就按你说的这个 Claude」）
- [ ] **pilotAliases = `["01","02","03","04"]`**（人已确认四台都可测）
- [ ] **时间顺序 P1→P4 分级 OK**（人已确认「时间顺序我觉得也 ok」）
- [ ] **独立身份语义 OK**（固定一人 vs 每次新 worker → 已答：固定一人 + jobId 区分实例）
- [ ] 明确「开闸 B」→ 执行 §1–§5；未批前 0 live 动作
