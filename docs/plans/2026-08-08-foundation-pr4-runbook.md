# Foundation PR4-1 — DeployShadow Runbook Draft（2026-08-09）

> **本文件状态：Draft · 未执行 · 0 live 动作**  
> 依赖：PR4-0 包（`docs/plans/2026-08-08-foundation-pr4-plan.md` / `-baseline.md` / `-files.json`，已提交 `e0db476`）  
> 执行前置：**人显式开闸 A** 后才允许跑 live 步骤；本 Draft 只供人审。  
> 所有默认参数取自 baseline（2026-08-08 初采 + 2026-08-09 实测加厚）。

## 0. 前置状态（实测 baseline · 2026-08-09）

| 项 | 实测值 | 注 |
|---|---|---|
| registry 仓 | `C:\Users\Public\xhs-registry` @ `6853d3b` → 已提交 PR4-0 至 `e0db476`（`foundation/pr4-deploy-shadow`） | `origin/main` 陈旧 `a305f59` |
| routing 仓 | `C:\Users\Public\xhs-routing-v1-1` HEAD `42b8964` @ 分支 `foundation/pr2-submit-integrity-lock` | `origin/main` 陈旧 `3b1c9ae` |
| 目标 | routing `fb7747feefd975ad14fdd51c3313b3487ae978ee` · registry `b1e5e70d3a53c8c1d119b078833e9066f8ccf107` | 双仓本地对象均缺失，须 fetch |
| task-launch | `524c21e…` / `rel-shadow-2026-08-02-repair-consumer-v1` / shadow / dual / pilot `[]` / `requireMainOrigin:true` / `requireTestReceipt:true` / `allowDirtyWorktree:false` | 保留非冲突字段 |
| cross-repo | 15 字段全采样（见 §6 表） | `registryCommit` `446494a…` ≠ `windowsRegistryCommit` `5e25df8…` |
| 控制面 17920 | **down**：`XhsDeviceControlPlaneV1` 上次运行 08/06 16:51 结果 `0xC000013A`（Ctrl+C）；AtStartup 无下次运行 | 见 D0 |
| registry 17930 | 运行中（`XhsDeviceRegistry` Running，例 PID 30576） | — |
| `registry.mjs` 字节 | 磁盘 CRLF SHA `18450588…`；`git show …:registry.mjs` blob LF SHA `151aa93b…` | `core.autocrlf=true` |

**执行纪律（全程）**：0 pilot · 0 真机 · 0 支付 · 0 无 lease 旁路 · 每阶段人确认 checkpoint · 控制面不可达时**禁止**把 registry 聚合 `leases=0` 当绿灯。

---

## 1. 阶段零 — 控制面现状裁决（决策点 D0）

目的：闸 A 预检 #0「控制面 17920 liveness」。基线已记 down；本阶段决定「先恢复旧 shadow 还是走主流程」。

```powershell
# 尝试恢复旧 shadow 控制面（不改变任何配置/代码，只拉起既有服务）
schtasks /run /tn XhsDeviceControlPlaneV1
# 等 20s 后探测（最多重试 3 次）
curl.exe -s -m 5 -o NUL -w "%{http_code}" http://127.0.0.1:17920/control/v1/health
```

- **若 200** → 旧 shadow 控制面恢复。重采 liveness 入 baseline；继续预检 #2/#3（租约/job/四机）。
- **若连接失败**（预期，因 checkout `42b8964` 在 feature 分支且 `requireMainOrigin:true` 可能拒启动）→ 走主流程：
  1. 把「预部署态控制面 down」记为**已知基线**（非缺陷引入）；
  2. **跳过** 预检 #2/#3 的「旧态」读数，改在 §4 部署后控制面首次拉起时读「新态」基线；
  3. 回滚成功标准相应改为「恢复 manifest/checkout + 与备份一致的可达性」，**不虚构旧 PID**（plan 回滚 §4 已记）。
- **禁止**：控制面 down 时把 `leases=0` 读成绿灯。

> Checkpoint：人确认 D0 结果后进入阶段一。

## 2. 阶段一 — fetch / 对齐（两仓，全在预检 #1 完成）

```bash
# registry
cd /c/Users/Public/xhs-registry
git fetch origin
git cat-file -t b1e5e70d3a53c8c1d119b078833e9066f8ccf107        # 必须输出 commit，否则停
test "$(git rev-parse origin/main)" = "b1e5e70d3a53c8c1d119b078833e9066f8ccf107" || echo "STOP: origin/main 未对齐"

# routing
cd /c/Users/Public/xhs-routing-v1-1
git fetch origin
git cat-file -t fb7747feefd975ad14fdd51c3313b3487ae978ee        # 必须输出 commit，否则停
test "$(git rev-parse origin/main)" = "fb7747feefd975ad14fdd51c3313b3487ae978ee" || echo "STOP: origin/main 未对齐"
```

> 若任一 `cat-file`/对齐失败 → 停，回滚锚点未变化，无需回滚。

## 3. 阶段二 — 备份（落盘，开任何写操作前）

```bash
TS=$(date -u +%Y%m%d-%H%M%S)
BK="C:/Users/Public/xhs-registry/backups/registry-deploy-shadow-pr4-$TS"
mkdir -p "$BK/control" "$BK/routing"
# 控制面 manifest 全文
cp /c/Users/Public/xhs-agent-control/task-launch.json "$BK/control/"
cp /c/Users/Public/xhs-agent-control/cross-repo-release.json "$BK/control/"
# registry 树 + 运行库
cp /c/Users/Public/xhs-registry/registry.mjs "$BK/"
# db/wal/shm（若存在，须与应用停服一致——本 runbook 不要求停服，仅冷备当前状态）
find /c/Users/Public/xhs-registry -maxdepth 1 -name "*.db*" -exec cp {} "$BK/" \; 2>/dev/null || true
# 回滚锚点写入（机读）
cat > "$BK/rollback-anchors.json" <<EOF
{
  "liveRoutingCheckout": "42b89640e5b2ecc20bc01bb22e68d26b787acd3f",
  "liveRoutingBranch": "foundation/pr2-submit-integrity-lock",
  "liveTaskLaunchCommit": "524c21e540e951d1174cbfecaca0049b3c4058c7",
  "liveLocalRoutingOriginMain": "3b1c9ae",
  "liveLocalRegistryOriginMain": "a305f59",
  "liveRegistryWorkingTree": "6853d3bb5045b390c2081903307574d3e35b566d",
  "liveCrossRepoReleaseId": "rel-shadow-2026-08-02-repair-consumer-v1",
  "liveRegistryDiskSha256Crlf": "1845058809133162b2168b014b38313fe47a9e6f550a82be1347856a42b501ec",
  "registryTipBlobSha256Lf": "151aa93bd8d0d2b4bb40863494f47ec70625f8fa459f8e7a72d14e2107b7575b",
  "controlPlaneLastResult": "0xC000013A (Ctrl+C 08/06 16:51; 预部署态 down)"
}
EOF
echo "backup: $BK"
```

> 备份后核对：`rollback-anchors.json` 四 SHA 与 baseline 一致才继续。

## 4. 阶段三 — Routing 部署（先 routing，再 registry；中间禁 ActivatePilot）

```bash
cd /c/Users/Public/xhs-routing-v1-1
git switch main                       # 满足 requireMainOrigin
git reset --hard fb7747feefd975ad14fdd51c3313b3487ae978ee   # 完整 40 字符
git rev-parse HEAD                    # 必须 = fb7747f 全量
```

改 `C:\Users\Public\xhs-agent-control\task-launch.json`（**保留** `requireMainOrigin`/`requireTestReceipt`/`allowDirtyWorktree`/`recipeOverlay*`/`repoRoot`/`nodeExe`/`deviceConfig` 等非冲突字段，只改下列）：

| 字段 | 新值 |
|---|---|
| `gitCommit` | `fb7747feefd975ad14fdd51c3313b3487ae978ee` |
| `releaseId` | `rel-shadow-2026-08-08-foundation-pr4` |
| `autonomyPolicyMode` | `shadow`（不变） |
| `evidenceMode` | `dual`（不变） |
| `pilotActors` / `pilotAliases` | `[]`（不变） |

reload 控制面（**预检 #0 或 D0 已确认 17920 可达之后**；若 D0 走了主流程，此处是控制面首次拉起）：

```powershell
schtasks /end /tn XhsDeviceControlPlaneV1
schtasks /run /tn XhsDeviceControlPlaneV1
# 等 health（最多 60s，5s 间隔）
curl.exe -s -m 5 http://127.0.0.1:17920/control/v1/health
```

> 若 control plane 拒启动（`requireMainOrigin` 之外的错误）→ **停**，进入 §8 回滚。

## 5. 阶段四 — Registry 部署

本 registry 为单文件运行模型（CLAUDE.md），**用 `git show` blob 落盘**，不做整树 checkout（避免 detach PR4 分支 + 保 worktree 干净）。若 tip 相对 live 有额外运行时文件改动：

```bash
cd /c/Users/Public/xhs-registry
# 列死改动文件集（旧锚点 6853d3b .. tip b1e5e70）
git diff --name-only 6853d3bb5045b390c2081903307574d3e35b566d..b1e5e70d3a53c8c1d119b078833e9066f8ccf107
# 主文件：LF blob 直写（避免 autocrlf 引入 CRLF，保持与 tip blob 字节一致）
git show b1e5e70d3a53c8c1d119b078833e9066f8ccf107:registry.mjs > registry.mjs
sha256sum registry.mjs                # 期望 = 151aa93b…（tip blob LF）
# 若上面 diff 列出的还有运行时文件（scripts/lib、contracts、install-registry-task.ps1 等）→ 逐个 git show 落盘
```

reload：

```powershell
schtasks /end /tn XhsDeviceRegistry
schtasks /run /tn XhsDeviceRegistry
# 等 health（最多 60s）
curl.exe -s -m 5 http://127.0.0.1:17930/api/health
```

> 注意：`git show … > registry.mjs` 写盘后，磁盘文件为 LF；registry 正常解析 LF/CRLF 均可（零依赖 node 脚本）。部署后若需再次 git 提交，autocrlf 会在下次 checkout 时归一化——**不要**为「好看」把 LF 又转回 CRLF。

## 6. 阶段五 — cross-repo-release.json 重写（保留全字段）

以 `C:\Users\Public\xhs-agent-control\cross-repo-release.json` 现行 15 字段为底，只改下列（**不得删键**；`policyDocDebt`/`schemaContracts` 默认可 `[]`）：

| 字段 | 新值 |
|---|---|
| `releaseId` | `rel-shadow-2026-08-08-foundation-pr4` |
| `registryCommit` | `b1e5e70d3a53c8c1d119b078833e9066f8ccf107` |
| `windowsRegistryCommit` | **同** `registryCommit`（本轮收口；旧 live `446494a…` vs `5e25df8…` 曾分叉，见 baseline；runbook 注明：若有消费者依赖两字段分叉需回归） |
| `deviceAgentCommit` / `taskLaunchCommit` | `fb7747feefd975ad14fdd51c3313b3487ae978ee` |
| `policyMode` / `effectiveDecisionSource` | `shadow`（不变） |
| `evidenceMode` | `dual`（不变） |
| `runtimePolicyVersion` | `xhs.nonpayment-autonomy.v1`（保留） |
| `pilotActors` / `pilotAliases` | `[]`（不变） |
| `pilotConfigured` | `false`（不变） |
| `deployedAt` | DeployShadow 时刻 ISO |

改完 `node -e` 或 JSON 校验器验证合法 JSON，且与 task-launch 同 `releaseId`。

## 7. 阶段六 — GO 探针（1–10，全部只读）

语义钉死：**GO = 服务起 + manifest 对齐 + 无 spawn；≠ integrity / symlink 已在 Windows 验证。**

| # | 命令（PowerShell） | 机读期望 |
|---|---|---|
| 1 | `curl.exe -s http://127.0.0.1:17920/control/v1/health` | 200；含 `policyMode`/pilot 等价字段且 pilot 未激活 |
| 2 | `git -C C:\Users\Public\xhs-routing-v1-1 rev-parse HEAD` | 完整 40 字符 `= fb7747feefd975ad14fdd51c3313b3487ae978ee` |
| 3 | `(Get-Content C:\Users\Public\xhs-agent-control\task-launch.json | ConvertFrom-Json).gitCommit` | `= 探针 #2`（**短 hash 不过闸**） |
| 4 | cross-repo-release.json 四 SHA | 与 §6 一致；键未丢 |
| 5 | `curl.exe -s http://127.0.0.1:17930/api/health` | 200 |
| 6 | `curl.exe -s http://127.0.0.1:17930/api/agent-entry` | `release.policyMode == "shadow"`；`pilotConfigured == false`；commit 字段 = 两侧 tip |
| 7 | `curl.exe -s http://127.0.0.1:17930/agent-entry.md` | 含 Release / runtime policy 段 |
| 8 | 控制面 leases/jobs/pending（**数据源 = 控制面，非同 registry 聚合**） | 均为 0 / 终态 |
| 9 | `curl.exe -s -o NUL -w "%{http_code}" http://127.0.0.1:17930/` 与 `/api/devices` | 200 |
| 10 | `git show b1e5e70…:registry.mjs | sha256sum` 对比部署后文件（**先 LF 归一化**） | 相等；禁止「工作区 vs 工作区」自比 |

任一失败 → **停并回滚**（§8），不进闸 B。

## 8. 回滚（DeployShadow 失败或需撤）

1. `task-launch.json` + `cross-repo-release.json` 从 `$BK/control/` 全文还原。
2. **routing checkout 回到 `liveRoutingCheckout`（`42b8964…`），不是 task-launch pin（`524c21e…`）**（决策点 D1）：
   - 若 `requireMainOrigin:true` 与 feature 分支冲突导致无法 reload → **默认推荐 (a)**：routing 留在可启动的 main 旧 pin（`524c21e…`），**书面记录**与真实预部署态（`42b8964` 分支）不一致，升级为事故留痕；**(b)** 仅当人批才临时允许非 main 启动撤出。
3. registry 树从 `$BK/` 还原；按探针 #10 同规则核旧字节。
4. 控制面预部署即 down 时：回滚目标 =「恢复备份 manifest + 与备份一致的可达性」，**不虚构旧 PID**。
5. 留痕：PROGRESS + progress 节记 NO-GO + 知识库 pitfall（若新坑）。

## 9. 留痕（执行后必须）

- PROGRESS.md 顶节改「DeployShadow 已执行 + GO 时间戳 + releaseId」
- `foundation-pr4-progress.md` 标记闸 A 通过、探针结果表
- 若踩新坑 → 知识库 pitfall（`appliesTo`/`verifyMode`）
- 更新 `files.json` `live*` baseline 为部署后值

## 10. 待解决项（人审时确认）

- D0：控制面恢复失败是否按主流程推进（runbook 默认：是，记录为已知基线）
- D1：回滚时 `requireMainOrigin` vs feature 分支的取舍（runbook 默认：(a) 事故留痕）
- `registryCommit`/`windowsRegistryCommit` 收口是否有消费者依赖分叉
- 本 runbook 文件需在 commit 时扩进 `files.json` registry `allowedPrefixes`
