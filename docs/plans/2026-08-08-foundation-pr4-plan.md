# Foundation PR4 计划稿 — DeployShadow →（另闸）ActivatePilot（2026-08-08）

> **本文件状态：Draft · review findings 已收口进文 · 未获 DeployShadow 开闸 · 0 live 动作**  
> 交接：`HANDOFF-2026-08-08-foundation-pr4-gate.md`  
> 基线：`2026-08-08-foundation-pr4-baseline.md`  
> 范围机读：`2026-08-08-foundation-pr4.files.json`  
> Review 输入：bridge `…/20260808-235037-9081d5e7/review.md` + 交互实测加厚（2026-08-09，控制面 down / CRLF / 双仓缺对象）

## 一句话

PR2 wiring + submit integrity lock **已合两侧 main**；PR4 把它们 **暗部署到 Windows（DeployShadow）**，再另闸才谈 Pilot / 最小非支付 canary。  
**DeployShadow ≠ ActivatePilot**。合了 main ≠ 已上线 ≠ Pilot 已开。

## 冻结源码锚点（DeployShadow 目标）

| 仓 | merge | 完整 SHA | PR |
|---|---|---|---|
| Routing `xhs-device-agent` | `fb7747f` | `fb7747feefd975ad14fdd51c3313b3487ae978ee` | [#43](https://github.com/gifted-professor/xhs-device-agent/pull/43) |
| Registry `xhs-registry` | `b1e5e70` | `b1e5e70d3a53c8c1d119b078833e9066f8ccf107` | [#6](https://github.com/gifted-professor/xhs-registry/pull/6) |

合并顺序已执行：**routing #43 → registry #6**（中间未部署）。DeployShadow 部署顺序仍建议 **先 routing / 控制面，再 registry**（与合入纪律一致；中间禁止 ActivatePilot）。

## 两个闸门（禁止合并表述）

| 闸门 | 做什么 | 不做什么 | 默认 |
|---|---|---|---|
| **A · DeployShadow** | 对照 SHA 把上述 tip 落到 Windows；reload 服务；写/核 `task-launch` + `cross-repo-release`；健康探针全绿 | 不填 pilot；不碰真机业务；不宣称 integrity「生产已强制」对 legacy omit 路径 | **需人显式开闸** |
| **B · ActivatePilot**（另闸） | 非空 `pilotActors`/`pilotAliases`（或等价策略）；最小 **L 级非支付** canary | 支付 / final commit；多机生产宣称；闲鱼 TCB 挂满 | **DeployShadow GO 之后另批** |

```text
合入 main ──► 写本计划/Draft ──► [闸 A] DeployShadow ──► [闸 B] ActivatePilot / L-canary
                 ▲ 你在这里（Draft · findings 已收口）
```

## DeployShadow 语义（本轮）

沿用 REX Phase 6 暗部署精神，落到 foundation 代码：

1. **`autonomyPolicyMode` / `policyMode` / `effectiveDecisionSource` 一律字面 `shadow`**（禁止「等价暗模式」开口）；`pilotActors=[]` / `pilotAliases=[]` / `pilotConfigured=false`
2. **不把 Pilot 名单写进 task-launch**
3. **零新端口 / 零新常驻服务**；只替换既有控制面 checkout + registry 树 + 计划任务 reload
4. **零碰机**：DeployShadow 验收禁止 submit 业务 job / session canary（只读 health / agent-entry / leases）
5. **integrity 上线形状**：带 `expected*` 的 submit 走原子锁；**缺 `expected*` 仍 legacy 兼容**（已知 residual，不挡 DeployShadow）——验收文案不得写成「全路径已强制 integrity」
6. **GO ≠ wiring 已在 Windows 验证**：绿灯只表示「服务起 + manifest 对齐 + 无 spawn」；不证明 `expected*` / ExecutionPlan / symlink fail-closed 在部署机可用

## 部署对象清单

### 共同：fetch / 本地对象（两仓都做）

`gh api …/commits/main` **只证明 GitHub 权威 tip**，不证明本机有对象。Deploy 前硬步骤：

1. `git fetch origin`（registry 与 `xhs-routing-v1-1` 各一次）
2. `git cat-file -t <fullSha>` → 必须为 `commit`（否则停）
3. `git rev-parse origin/main` → 完整 40 字符等于目标 tip（否则停；不得用陈旧 remote-tracking 当 tip）

### Routing / 控制面（Windows）

| 项 | 路径 / 动作 |
|---|---|
| Checkout | `C:\Users\Public\xhs-routing-v1-1`：fetch 后 `git checkout main` + 对齐 `fb7747feefd975ad14fdd51c3313b3487ae978ee`（完整 40 字符；满足 `requireMainOrigin: true`） |
| task-launch | `C:\Users\Public\xhs-agent-control\task-launch.json`：`gitCommit` = 同上 40 字符；新 `releaseId`（建议 `rel-shadow-2026-08-08-foundation-pr4`）；`autonomyPolicyMode=shadow`；`evidenceMode=dual`；pilot 双数组空；**保留**既有非冲突字段（如 `requireMainOrigin`） |
| 控制面任务 | **预检 #0 已证明 17920 可达之后**再 `schtasks` end/run `XhsDeviceControlPlaneV1`；等 health 200 |
| FastOperator | **默认不批量重启**；仅当 health/probe 证明必要再单台拉起（另记） |

### Registry（Windows）

| 项 | 路径 / 动作 |
|---|---|
| 源 tip | `git fetch` 后本地可解析的 `b1e5e70d3a53c8c1d119b078833e9066f8ccf107`（`origin/main` 对齐） |
| 主路径 | **整树对齐 tip**（`git checkout` / reset 到 tip，工作区干净）；避免只拷单文件漏附属 |
| 文件集（探针覆盖） | **至少**：`registry.mjs`。若 tip 相对 live 另有 diff：`scripts/lib/**`、`contracts/**`、`install-registry-task.ps1` 等凡 tip 改过的路径——runbook 用 `git diff --name-only <liveAnchor>..<tip>` **列死**后再拷/对齐 |
| 权威字节 | 期望 SHA256 = `git show <tip>:registry.mjs` 的 **blob 字节**（LF）。写盘时用 `git show … > registry.mjs`（或等价）避免 autocrlf 把「源 tip」与磁盘搅成假绿/假红；探针 #10 规则见下 |
| 备份 | `backups/registry-deploy-shadow-pr4-<UTC>`（代码 + 当时存在的 db/wal/shm） |
| 任务 | `schtasks /End` + `/Run` `XhsDeviceRegistry`；确认 `StopOnIdleEnd=false`；17930 LISTEN |

### Cross-repo release manifest

写/更新 `C:\Users\Public\xhs-agent-control\cross-repo-release.json`（`xhs.cross-repo-release.v1`）。**保留 schema 全字段**；不得只写 7 列把其余静默丢掉。

| 字段 | DeployShadow 期望 |
|---|---|
| `schemaId` / `schemaVersion` | 保持既有（`xhs.cross-repo-release.v1` / `1`） |
| `releaseId` | 与 task-launch 同 |
| `registryCommit` | `b1e5e70d3a53c8c1d119b078833e9066f8ccf107` |
| `windowsRegistryCommit` | **同** `registryCommit`（本轮收口；旧 live 两字段曾不同——`446494a` vs `5e25df8`——runbook 注明消费者若分叉需回归） |
| `deviceAgentCommit` / `taskLaunchCommit` | `fb7747feefd975ad14fdd51c3313b3487ae978ee` |
| `policyMode` / `effectiveDecisionSource` | `shadow` |
| `evidenceMode` | `dual`（与 task-launch 一致） |
| `runtimePolicyVersion` | 保留既有或显式记录（旧：`xhs.nonpayment-autonomy.v1`） |
| `pilotActors` / `pilotAliases` | `[]` |
| `pilotConfigured` | `false` |
| `policyDocDebt` / `schemaContracts` | 保留数组（默认可 `[]`）；禁止删键 |
| `deployedAt` | DeployShadow 时刻 ISO |

## 预检（开闸 A 前必须绿）

0. **控制面 liveness（硬）**：`GET :17920/control/v1/health` → 200；计划任务 `XhsDeviceControlPlaneV1` 为 Running 且 17920 LISTEN。**今天 baseline 采样为 down——未恢复前禁止开闸 A**。不得用「registry 聚合 leases=0」代替本条。
1. GitHub tip 仍含上述 SHA（`gh api …/commits/main`）**且**本机两仓 `git fetch` 后 `cat-file` / `origin/main` 对齐（见上）
2. **leases / jobs / pending 只认控制面**：`GET :17920/control/v1/leases`（或等价）与控制面 job/approvals 视图 → 均为空闲/终态。**禁止**在控制面不可达时用 registry 降级身份缓存把 leases=0 读成绿灯（真空变绿）
3. 01–04 按 agent-entry：**ready + lease free**（须控制面可达；或书面记下不可恢复机并缩范围——默认四机全绿才 Deploy）
4. 记录 **回滚锚点**（写入备份目录 + `files.json` baselines；**彼此独立**）：
   - `liveRoutingCheckout` = 实际 Windows routing `git rev-parse HEAD`（baseline：`42b8964…`）
   - `liveRoutingBranch` = 实际分支名（baseline：`foundation/pr2-submit-integrity-lock`）
   - `liveTaskLaunchCommit` = task-launch pin（baseline：`524c21e…`）——**≠** checkout
   - `liveLocalOriginMain` = 当时陈旧 `origin/main`（仅审计）
   - 旧 `cross-repo-release.json` 全文备份
   - 旧 `registry.mjs` 磁盘 SHA256（CRLF 实况）+ tip blob SHA256（LF）
   - 控制面 PID（若当时未运行 → 记 `null` + 任务状态，不得假装有 PID）
5. wiring focused suite 再跑一轮仍绿（全量 flaky 不挡；focused 回归失败则停）
6. 文档分支：若落 git，从 `main`（或含 tip 的基线）建/切 `foundation/pr4-deploy-shadow` 再提交；**不要**堆在已合入的 `foundation/pr2-wiring-closure` 脏树上长期漂

## DeployShadow GO 门（探针清单）

全部只读；任一失败 → **停并回滚**，不进入闸 B。  
**语义钉死**：GO = 服务起 + manifest 对齐 + 无 spawn；**≠** integrity / symlink 路径已在 Windows 业务验证。

| # | 探针 | 机读期望 |
|---|---|---|
| 1 | `GET :17920/control/v1/health` | HTTP 200；JSON 含 `policyMode.mode == "shadow"`（或控制面等价字段）且 pilot 未激活（`pilotConfigured != true` / pilot 数组空——以 health 实际字段名为准） |
| 2 | Windows routing `git rev-parse HEAD` | **完整 40 字符** = `fb7747feefd975ad14fdd51c3313b3487ae978ee` |
| 3 | `task-launch.json` `gitCommit` | **完整 40 字符** = 探针 #2 的 HEAD（短 hash **不**过闸） |
| 4 | `cross-repo-release.json` | 上表 SHA/policy/pilot 字段全匹配；未丢键 |
| 5 | `GET :17930/api/health` | HTTP 200 |
| 6 | `GET :17930/api/agent-entry` → `release` | `present`；`policyMode == "shadow"`；`evidenceMode == "dual"`；`pilotConfigured == false`；`deviceAgentCommit`/`taskLaunchCommit`（或 entry 暴露的等价 commit 字段）= routing tip；registry 侧 commit 字段 = registry tip |
| 7 | `GET :17930/agent-entry.md` | 含 Release / runtime policy 段 |
| 8 | 控制面 leases / running jobs / pending | 均为 0（与部署前一致；**数据源同预检 #2**） |
| 9 | 面板 `/`、`/api/devices` | HTTP 200 |
| 10 | `registry.mjs` 完整性 | 部署后文件的 SHA256（**先按 LF 归一化：去 `\r` 再哈希，或两侧都取 `git hash-object`/`git show` blob**）= `git show b1e5e70…:registry.mjs` 的 blob SHA；**禁止**「工作区文件哈希 vs 工作区文件」自我对照；**禁止**未归一化时直接比 CRLF 磁盘 vs LF blob |

**明确不进 GO 门**：真机 job、session canary、ActivatePilot、支付路径、宣称「多设备生产已上线」、宣称「integrity 已在 Windows 验证」。

## 回滚（DeployShadow 失败或需撤）

1. 恢复 `task-launch.json` + `cross-repo-release.json` 到备份（旧 release 全文）
2. **routing checkout 回到 `liveRoutingCheckout`（`42b8964…`），不是 task-launch pin（`524c21e…`）**。  
   - 若 `requireMainOrigin: true` 与 feature 分支 checkout 冲突：回滚后控制面可能无法 reload——runbook 必须二选一写死：**(a)** 回滚只还原 manifest/registry、routing 留在可启动的 main 旧 pin 并**书面记录**与真实预部署漂移不一致；**(b)** 临时允许非 main 启动仅用于撤出（需人批）。**默认推荐 (a) 并升级为事故留痕**，因预部署态本身已违规漂移。
3. registry 树从 `backups/…` 还原；按探针 #10 同规则核旧字节
4. 依次试图 reload 控制面 → registry；控制面若预部署即 down，回滚目标是「恢复到备份 manifest + 与备份一致的可达性」，不是虚构旧 PID
5. 留痕：PROGRESS + 知识库 pitfall（若新坑）+ progress 节记 NO-GO

历史参考：REX Phase 7 曾短时 pilot 后退回 `rel-shadow-*-p7-no-go`——**本轮 DeployShadow 默认不走 pilot，回滚应更短。**

## 切片顺序（建议）

| 切片 | 产出 | live？ | 开闸 |
|---|---|---|---|
| **PR4-0**（本稿） | 计划 + baseline + files.json（含 review 收口） | 否 | 写计划已开 |
| **PR4-1** | DeployShadow **runbook Draft**（逐步命令、备份路径、探针 curl、CRLF/fetch/`requireMainOrigin` 决策）仍可不碰 live | 否 | 人审 Draft |
| **PR4-2** | Review → Approve →（若有脚本/文档 PR）merge；跨仓仍 routing→registry | 否 | merge ≠ deploy |
| **PR4-3** | **闸 A** 显式通过后执行 DeployShadow + GO 门（**先恢复控制面**） | 是（服务） | **人批 A** |
| **PR4-4** | **闸 B** ActivatePilot + 最小 L 非支付 canary 计划（另文） | 是（受限） | **人批 B** |

## ActivatePilot / canary（仅轮廓；非本 Draft 开闸范围）

- 默认单 alias（历史偏好 `01`）、非支付、L1→L 递进；支付 / final commit **永远人确认**，transport 保持 0
- 可复用已有 P1 session canary 经验（`ops/xw-session-canary-noop.mjs`、微信余额只读 L4）——**另闸另文**，不绑 DeployShadow merge prerequisite
- **明确延后**：闲鱼真 TCB / manifest 挂满 live capabilities；用 Pilot 宣称多机生产

## 红线（全文有效直至对应闸门通过）

```text
0 Windows deploy / reload     ← 除非闸 A（且预检 #0 控制面可达）
0 ActivatePilot               ← 除非闸 B
0 真机业务 canary / 支付路径
0 无 lease 旁路碰机
0 「合了就 reload」
0 控制面 down 时用 registry 真空 leases=0 开闸
```

## 配对 routing 指针

Routing 仓应有对称说明（若尚未）：`docs/plans/2026-08-08-foundation-pr4-deploy-shadow.md`（或同名），锚点 `fb7747f` + 指向本 registry 计划。  
本 Draft **不要求** routing 立刻有文件才算 PR4-0 完成；PR4-1 runbook 前补齐指针即可。

## 接手三问（答不出不准部署）

1. Windows live HEAD / task-launch 是否仍是 **旧** release？（baseline：是；且 checkout≠pin）
2. 本切片是 **只写 Draft**，还是 **已获人确认可 DeployShadow**？（当前：只写 Draft；控制面 down → 闸 A 不可开）
3. Pilot / 真机 canary 是否 **另闸**？（默认：是）
