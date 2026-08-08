# Foundation PR4 baseline（2026-08-08 · pre-DeployShadow；2026-08-09 实测加厚）

> 入场快照：写计划时采一次；2026-08-09 交互实测补控制面 liveness / CRLF / 双仓缺对象 / 分支。  
> **判定：live 仍为旧 shadow · 控制面曾实测 down · 可写 PR4 Draft · 不可默认 Deploy · 未恢复 17920 前不可开闸 A。**

## 源码 tip（DeployShadow 目标 · GitHub 权威）

| 仓 | short | full |
|---|---|---|
| registry origin/main | `b1e5e70` | `b1e5e70d3a53c8c1d119b078833e9066f8ccf107` |
| routing origin/main | `fb7747f` | `fb7747feefd975ad14fdd51c3313b3487ae978ee` |

采样：`gh api repos/gifted-professor/{xhs-registry,xhs-device-agent}/commits/main`（2026-08-08）。

## Live 现状（Windows）

### 服务

| 探针 | 2026-08-08（计划初采） | 2026-08-09（实测加厚） |
|---|---|---|
| `:17930/api/health` | 200 `ok`；identities=4 | 200；任务 Running（例 PID 30576） |
| `:17920/control/v1/health` | **未采样（缺陷）** | **down**：无 LISTEN；HTTP 000；`XhsDeviceControlPlaneV1` Ready 未运行 |
| 碰机 | 未做 | 未做 |

**含义**：闸 A GO 探针 #1 依赖 17920；预检 #2 leases **必须**走控制面。控制面 down 时 registry 聚合可能真空 `leases=0` → **禁止当绿灯**。

### `task-launch.json`（`C:\Users\Public\xhs-agent-control\`）

| 字段 | 值 |
|---|---|
| `gitCommit` | `524c21e540e951d1174cbfecaca0049b3c4058c7` |
| `releaseId` | `rel-shadow-2026-08-02-repair-consumer-v1` |
| `autonomyPolicyMode` | `shadow` |
| `evidenceMode` | `dual` |
| `pilotActors` / `pilotAliases` | `[]` |
| `requireMainOrigin` | `true`（与 feature 分支 checkout 冲突——回滚/reload 必答） |

### `cross-repo-release.json`（采样字段；全文应备份）

| 字段 | 值 |
|---|---|
| `releaseId` | `rel-shadow-2026-08-02-repair-consumer-v1` |
| `registryCommit` | `446494ab7d03382b268ff973ac12951cb13fc4c6` |
| `windowsRegistryCommit` | `5e25df8e62b5a64f8ad4e86173b4975c013e18a1`（**≠** registryCommit） |
| `deviceAgentCommit` | `1e1d7f6cc423c8b7176ebbba199a18bfea58a161` |
| `taskLaunchCommit` | `1e1d7f6cc423c8b7176ebbba199a18bfea58a161` |
| `policyMode` / `effectiveDecisionSource` | `shadow` |
| `evidenceMode` | `dual` |
| `runtimePolicyVersion` | `xhs.nonpayment-autonomy.v1` |
| `pilotConfigured` | `false` |
| `policyDocDebt` / `schemaContracts` | `[]` |
| `deployedAt` | `2026-08-05T07:28:47.604Z` |

### 四层漂移（DeployShadow 必须收口）

| 层 | 值 | 注 |
|---|---|---|
| GitHub routing main | `fb7747f…` | Deploy 目标 |
| 本地 routing `origin/main`（2026-08-09） | `3b1c9ae…` | **陈旧**；缺 `fb7747f` 对象直至 fetch |
| Windows routing **实际 checkout** | `42b89640e5b2ecc20bc01bb22e68d26b787acd3f` | 分支 `foundation/pr2-submit-integrity-lock`（**非 main**）= **回滚真锚点** |
| task-launch pin | `524c21e…` | **从未**是运行 checkout |
| cross-repo deviceAgent | `1e1d7f6…` | 更旧 |
| GitHub registry main | `b1e5e70…` | Deploy 目标；本地对象曾 **不存在** |
| 本地 registry `origin/main` | `a305f59…` | **陈旧** |
| registry working tree | `6853d3b…` @ `foundation/pr2-wiring-closure` | ≠ merge tip |

**结论**：live = **旧 shadow release + 四层漂移 + 控制面曾 down**。DeployShadow = fetch/对齐 tip + 重写 manifest + **先恢复控制面** + 双服务 reload。中间禁止 ActivatePilot。

### registry.mjs 字节（autocrlf）

| 源 | 观察（2026-08-09） |
|---|---|
| `core.autocrlf` | registry 仓 `true` |
| 磁盘 `registry.mjs` | CRLF；例 SHA `18450588…` |
| `git show HEAD:registry.mjs` blob | LF；例 SHA `151aa93b…` |

字面「磁盘 SHA == tip blob SHA」**今天必红**。探针 #10 必须 LF 归一化或两侧同取 blob 规则（见 plan）。

## 测试债（不挡写计划；Deploy 前再确认 focused 绿）

Registry 全量约 `258 / 256 pass / 2 fail`（与 wiring 交接一致）：

1. concurrent observer screen singleflight（`0 !== 1` READ）
2. filesystem/Git verifiers Windows symlink `EPERM`（与 PR6 父目录 symlink fail-closed 重叠风险；GO 不覆盖）

Wiring / submit-lock focused suites：合入前绿。全量环境债 **不**作为 DeployShadow 的硬挡板，除非 focused 回归。

## 闸门结论

| 规则 | 结果 |
|---|---|
| 源码 tip 已合 main（GitHub） | **是** |
| 本机已 fetch 对齐 tip | **否**（须 Deploy 预检） |
| live 已 DeployShadow | **否** |
| Pilot 已开 | **否** |
| 控制面 17920 健康（开闸 A 前置） | **否**（2026-08-09 实测 down） |
| 允许写 PR4 计划 / runbook Draft | **是** |
| 允许执行 Windows deploy/reload | **否**（待闸 A；且先恢复控制面） |
