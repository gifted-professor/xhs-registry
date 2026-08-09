# Foundation PR4 progress（2026-08-08 → 2026-08-09）

> **状态：闸 A DeployShadow 已执行（GO 00:49Z）· 闸 B ActivatePilot 已执行（GO 01:15Z）· P1 三只读任务全绿 · P2 等 checkpoint · PR7 review 7/7 闭合**  
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

## PR4-3 — ActivatePilot（闸 B，2026-08-09）

人显式开闸「现在开闸，P1 起步」→ 执行 runbook `2026-08-09-foundation-pr4-gate-b-activate-pilot-runbook.md` §1–§5。

- [x] 备份 shadow 态 → `backups/registry-activate-pilot-pr4-20260809-011332/`（含 rollback-anchors.json）
- [x] task-launch 翻转：`autonomyPolicyMode=nonpayment_v1` · `pilotActors=[claude-pilot-20260809]` · `pilotAliases=[01,02,03,04]` · `releaseId=rel-pilot-2026-08-09-foundation-pr4`
- [x] cross-repo 同步：`policyMode=nonpayment_v1` · `pilotConfigured=true` · 17 键保留
- [x] 控制面 reload → health `{mode:nonpayment_v1, active:true, pilotOnly:true, pilotConfigured:true}`
- [x] GO 探针 1–8 全绿（#9 支付无靶子，见发现 1）
- [x] **P1**：01 上 `xiaowei.device.list` + `xianyu.observe.snapshot` + `wechat.observe.probe` → **3/3 succeeded**，全只读、evidence 落库（含截图 486KB）、restoration 正常、四台无 quarantine、activeLeases=0
- [x] **P2**（人 checkpoint「现在开 P2」后）：按各设备能力白名单扩 4 台只读 observe → **6/7 succeeded**，4 台各 ≥1 成功，无新增 quarantine（详见 P2 块）
- [x] **P3**（人 checkpoint「开 P3 dry_run」后）：01 上 `input_dry_run`+`open_dry_run` 绿、`image_dry_run` 干净失败（staging 相册已不在手机）→ dry_run 语义+三探针验证（详见 P3 块）

### P2 结果（2026-08-09，扩 4 台只读 observe）

提交方式：`devicectl job submit --actor claude-pilot-20260809 --alias <a> --physical-label rack-<a> --capability <cap>`，placement 需 `alias+physicalLabel` 双 selector（P1 即如此）。按设备 routing 白名单（`control.db devices.routing_json`）选取能力：

| alias | capability | jobId | 结果 | evidence |
|---|---|---|---|---|
| 02 | `xiaowei.device.list` | job_562614ab | ✅ succeeded | result 252B |
| 02 | `xianyu.observe.snapshot` | job_e5a67473 | ✅ succeeded | result 582B |
| 02 | `wechat.observe.probe` | job_59d54041 | ✅ succeeded | result 696B + **screenshot 577KB**（sha `47c5e2f6…`） |
| 03 | `xiaowei.device.list` | job_a32c80e9 | ✅ succeeded | result 252B |
| 03 | `xianyu.observe.snapshot` | job_53f6f992 | ✅ succeeded | result 539B |
| 04 | `xiaowei.device.list` | job_77d3e6cb | ✅ succeeded | result 233B |
| 04 | `xhs.observe.feed` | job_0cead745 | ❌ failed | `ADAPTER_HTTP_UNAVAILABLE`（loopback `127.0.0.1:17896` 不可达；restoration return_home 亦无法达 leased device） |

全部 `approvalRequired=false` / `externalEffect=false`。四台 online 无 quarantine（quarantine=0）。`leases` 表空（activeLeases=0）。控制面 health 维持 `nonpayment_v1/active/pilotOnly/pilotConfigured`。

**P2 判据核验**：4 台各 ≥1 job 成功 ✓；无新增 quarantine ✓；activeLeases=0 ✓。

### P3 结果（2026-08-09，dry_run 试写，01 起步）

`xianyu.publish.*_dry_run` 是 publish 类能力（capability 级 `externalEffect=true`），但 dry_run 语义 = 预检/试写，**不点发布、不真发**。01 上三个：

| 能力 | jobId | 结果 | 实际动作 |
|---|---|---|---|
| `xianyu.publish.input_dry_run` | job_d09e94da | ✅ succeeded | 把测试文本打进闲鱼发布编辑器输入框（textLen=40 textVerified=true flutterInputActive），**无 submit/publish 动作**；restore 回桌面 |
| `xianyu.publish.open_dry_run` | job_29affad6 | ✅ succeeded | 打开发布流程页，`{ok:true}`，无输入无提交；restore 回桌面 |
| `xianyu.publish.image_dry_run` | job_30f27593 | ❌ `VERIFICATION_FAILED` | `step=image-album-missing`——历史 staging 相册 `XianyuStg2`（`/sdcard/Pictures/XianyuStg2/{a,b}.png`）已不在 01 手机（早前会话测试图已清）。**干净失败**：dry_run 无副作用，能力自验手机真实状态未造假 |

**P3 三探针**：dry_run 返回 expected（不真发）✓（input/open audit 无 submit 动作）· approval_audit 0 新增（仍 2 行，试点前遗留）✓ · financial_commit 0 job 0 event ✓ · leases 空 ✓。

**副作用说明**：input_dry_run 把测试文本留在了 01 闲鱼发布编辑器的**未发送草稿**里（试写即此意，非真实发布、非支付）。可在闲鱼 app 手动清草稿。

### 闸 B 发现

1. **支付无靶子**：29 能力 effect classes 仅 `none/publish/reversible/social`，无 `financial_commit` 类能力 → 探针 #9 无直接靶子；硬闸由策略代码（`financial_commit→wait_financial_commit` + protected-commit）保证。
2. **explore 是 `canary_only/lab_only/E1`**：普通 job submit 会被 `CANARY_SESSION_REQUIRED` 拦，须 `session acquire --canary`（P4 用）。
3. **registry observer 端点**：截图在 `/api/observer/v1/screen/:alias`（需 observer token），非 `/api/fleet/screen`；P1 截图经 control.db evidence 确认。
4. **隔离硬拦已证**：非 pilot actor → `AUTONOMY_PILOT_SCOPE_MISS` block；pilot actor+alias → `NONPAYMENT_AUTONOMY_ACTIVE` allow。
5. **设备能力白名单差异（P2 新增）**：不是每台都路由同一组 observe——04 无 `xianyu.observe.snapshot`/`wechat.observe.probe`（有 `image_manifest`/`feed`），03 无 `wechat.observe.*`。P2 按白名单配能力，避免盲目同质提交。
6. **04 `xhs.observe.feed` 环境失败（P2 新增）**：`ADAPTER_HTTP_UNAVAILABLE`——loopback adapter `127.0.0.1:17896` 对 04 不可达（restoration 也报 return_home_error "gateway could not reach the leased device"）。同一设备 `device.list` 成功（走 transport:xiaowei:22222），说明是 xhs 专用 adapter/传输不可达，**非能力逻辑缺陷、非隔离拦截**。未盲目重试，记为环境债（`pitfall-…-20260809`）。

### 红线状态

0 支付 · 0 douyin share_link · 0 xhs.comment.send · 非 pilot actor 被硬拦。**P1+P2 已过（4 台各 ≥1 只读成功），P3 未开等 checkpoint**。

## PR4-4 — PR #7 review closure（REQUEST CHANGES，2026-08-09）

独立审查结论：需要修的是**审计表达与证据不可变性**，不是重新执行 DeployShadow。7 项发现全部闭合，证据写进 `foundation-pr4.files.json` `evidenceClosure`（7/7 verdict=fixed）：

| 项 | 闭合 |
|---|---|
| H-01 | auditVersion 2：authorizedBefore（不可变授权快照，source=e0db476+闸 A 备份）与 observedAfter（gateA/gateB 执行块）分离 |
| H-02 | 探针 #6 字面偏差 → `probe6=PASS_WITH_WAIVER` + reason（agent-entry schema 无 pilot 字段；语义经 health+cross-repo 证明） |
| H-03 | scoped receipt 非事后挑选（见下证据链） |
| M-01 | `migrateLegacyPending` 在 `pilotOnly===true` 返回 null（control-plane.mjs:363）；live DB 0 waiting（12 行全终态） |
| M-02 | 全量 SHA-256；authorized 两值经闸 A 备份 `sha256sum` **字节级交叉验证** |
| M-03 | PR body 措辞钉死：本 PR 仅 docs；记录的是已发生（人授权下受控运维）的部署/写配置/进程重启，不改运行时代码 |
| M-04 | 可执行两级回滚（见下） |

### H-03 证据链（receipt 范围先于执行被固定）

1. **机械闸门先于执行**：`assert-release-gates.mjs` @ fb7747f（routing main，本 PR 未改）硬编码 8 个 `RUNTIME_CRITICAL_TEST_MARKERS`，要求 `passed≥15`、`failed=0`、`gitCommit==HEAD`、command 引用 ≥2 个 marker、receipt ≤48h。旧 receipt（fb4f90be，4 passed）挡启动——闸门是机械的，非人判。
2. **范围受闸门约束**：6 个被选套件全部落在预定义 8-marker 集合内；`failed=0` 强制已知失败套件（control-plane-core 的 migrateLegacyPending）退出任何通过性 receipt。该失败经 `git diff 42b8964 fb7747f` 逐字节相同证明为预存在。
3. **时间线（committer 日期）**：runbook draft `84a8a3e` 16:35:37Z → **人审 `a8ea70f` 00:33:17Z → receipt 写入 00:47:16.594Z（磁盘 mtime==completedAt，runtime/ gitignored）→ 执行记录 `de4aec0` 00:51:49Z**。人审先于测试执行。
4. **范围决策落留痕**：`outbox/claude-bridge/20260809-deploy-shadow-execution.md` §2 记录了人批「跑测试补 receipt」与「6 全绿 critical 套件（41/0）生成 scoped receipt，失败记留痕不伪造」。
5. **receipt 防篡改**：`write-release-test-receipt.mjs` @ fb7747f 把 gitCommit+command+passed+failed+completedAt 绑进 `bodyHash=a10f72a1…`；磁盘文件 sha=`abe90b90…`。
   - **残余未决（标注非解决）**：8 个 marker 之一 `assert-release-gates.test.mjs` 未被引用，执行时未记录排除原因。

### M-04 可执行两级回滚（字节级可验证）

| 层级 | 还原目标 | 备份源（sha） | 确认 |
|---|---|---|---|
| 闸 B undo（pilot→shadow-deployed） | task-launch @fb7747f · releaseId=rel-shadow-2026-08-08-foundation-pr4 · shadow | `backups/registry-activate-pilot-pr4-20260809-011332/control/`（task-launch `9cea710b` / cross-repo `67c2f61c`） | reload 控制面 → shadow active=false pilotConfigured=false |
| 闸 A undo（DeployShadow→pre-deploy） | task-launch @524c21e · releaseId=rel-shadow-2026-08-02-repair-consumer-v1 | `backups/registry-deploy-shadow-pr4-20260809-003955/control/` + registry.mjs + registry.db（task-launch `50f92183` / cross-repo `7200514a` **== authorizedBefore 精确一致**） | redeploy registry.mjs → 17930 health + gitCommit=524c21e |

**0-nonterminal barrier**：任何回滚前 control-plane `activeLeases` 必须为 0、approvals 队列空（pilot 空闲态两条件均满足）。不携带 in-flight 任务回滚。

## 未做（红线）

- [ ] **P2（扩 4 台 observe）**——等 checkpoint
- [ ] P3（dry_run 试写） / P4（explore/repair canary session）
- [ ] codex-luna 第二个 pilot actor（就绪后加入名单）
- [ ] runbook §11 旧分支/陈旧 ref 清理（贴人确认再删）
- [ ] routing 仓对称指针（可选）

## 下一步

1. **P2 checkpoint**：人确认后扩 4 台只读 observe（闸 B 已执行但审查当时 NO-GO——时间冲突待用户裁决，P2 暂停等拍板）
2. ~~PR7 review 继续~~ → **已完成**：7/7 闭合（PR4-4），commit 提交到分支（见 git 状态）
3. runbook §11：列 `git branch -vv` 审一遍 → **贴人确认**后 `remote prune` + 删已合/废弃分支
4. codex-luna 就绪 → 加入 pilotActors + reload

## 取消

- Bridge 重跑 bundle `20260809-001949-fb6de338`（快照与首轮相同，未外发；以实测加厚为准）
