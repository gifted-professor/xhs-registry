# Visual Tap Resolver 小 Demo 交接

> 更新时间：2026-08-06  
> 状态：离线 PoC 已完成，真实截图跨 App 验证已完成；尚未接入控制面、设备或点击链路。  
> 当前分支：`codex/visual-tap-resolver-demo`  
> 当前 HEAD：`3a953cf fix: retain candidates on real device screens`

## 1. 一句话结论

这个 demo 已证明：当 Android UI dump 为空、过稀或获取较慢时，可以用本地截图算法生成候选块、计算安全点击点并映射回手机物理坐标。对可用 dump 验真的 7 张真实页面，视觉候选覆盖了 `95/107 = 88.8%` 的可点击区域。

它目前是 **dump 的保底候选生成器**，不是 dump 的替代品，也不能把所有候选依次点击。复杂图片/视频内容会产生大量无意义轮廓，下一步最高优先级是加入“媒体内容区抑制”。

## 2. 仓库、代码和提交

独立 worktree：

```text
/Users/a1234/Desktop/Coding/.worktrees/xhs-visual-tap-resolver-demo
```

分支：

```text
codex/visual-tap-resolver-demo
```

提交：

```text
92b5f9d docs: design visual tap resolver demo
688ed6e feat: add offline visual tap resolver demo
e34fd41 chore: clean visual demo requirements
3a953cf fix: retain candidates on real device screens
```

核心文件：

```text
experiments/visual-tap-resolver/resolver.py
experiments/visual-tap-resolver/visual_tap_demo.py
experiments/visual-tap-resolver/tests/test_resolver.py
experiments/visual-tap-resolver/README.md
docs/plans/2026-08-06-visual-tap-resolver-demo-design.md
```

当前 worktree 干净，未 push。

## 3. Windows 图片从哪里来

Windows 目标机必须先确认是：

```text
DESKTOP-3I1EVHE
```

### 3.1 Windows 两个来源目录

正式运行证据根目录：

```text
C:\Users\Public\xhs-agent-runs
```

Explorer 临时截图与 dump：

```text
C:\Users\windows 10\AppData\Local\Temp\xhs-explore
```

补充说明：正式根目录里还有长期保留的 Explorer 子目录：

```text
C:\Users\Public\xhs-agent-runs\_explore
```

临时目录会被清理；需要复现实验的文件必须先校验并复制到 Mac。正式目录是运行证据真相，临时目录只能作为配对和补样本来源。

### 3.2 本次已经下载到 Mac 的位置

本次 9 组跨 App 样本及算法输出统一放在：

```text
/Users/a1234/.codex/visualizations/2026/08/06/019fd4e1-ac4b-7261-a10d-3358b6d75f76/multi-app-evidence
```

目录结构：

```text
multi-app-evidence/
├── benchmark-report.md
├── xhs/
│   ├── page-{a,b,c}.png
│   ├── page-{a,b,c}.xml
│   └── resolved-{a,b,c}/
├── douyin/
│   ├── page-{a,b,c}.png
│   ├── page-{a,b,c}.xml
│   └── resolved-{a,b,c}/
└── xianyu/
    ├── page-{a,b,c}.png
    ├── page-{a,b,c}.xml
    └── resolved-{a,b,c}/
```

每个 `resolved-*` 中包含：

```text
blocks.json       # 候选块、截图 SHA、坐标变换、安全点、分阶段耗时
overlay.png       # 只显示顶层候选
overlay-all.png   # 显示全部候选，适合排查过分割
```

更早的 03 号真机“应用升级”页面验证在：

```text
/Users/a1234/.codex/visualizations/2026/08/06/019fd4e1-ac4b-7261-a10d-3358b6d75f76/real-03-evidence
```

不要把二进制截图提交到 Git；交接文档只记录证据位置、来源和校验关系。

### 3.3 正确的下载方式

使用本机 `windows-tailscale-bridge`，不要使用裸 IP、SMB、临时 HTTP 或猜测的 SSH key。

先确认主机身份：

```bash
python3 /Users/a1234/.agents/skills/windows-tailscale-bridge/scripts/windows_bridge.py probe
```

输出必须包含：

```text
hostname=DESKTOP-3I1EVHE
```

对每个明确文件先检查元数据和 SHA-256：

```bash
python3 /Users/a1234/.agents/skills/windows-tailscale-bridge/scripts/windows_bridge.py stat \
  'C:\Users\Public\xhs-agent-runs\_explore\shot-04-1785724031035.png'

python3 /Users/a1234/.agents/skills/windows-tailscale-bridge/scripts/windows_bridge.py hash \
  'C:\Users\Public\xhs-agent-runs\_explore\shot-04-1785724031035.png'
```

再原子下载并自动核对远端/本地 SHA：

```bash
python3 /Users/a1234/.agents/skills/windows-tailscale-bridge/scripts/windows_bridge.py fetch \
  'C:\Users\Public\xhs-agent-runs\_explore\shot-04-1785724031035.png' \
  '/absolute/local/path/page-a.png'
```

成功输出必须有：

```text
verified: true
hostname: DESKTOP-3I1EVHE
```

### 3.4 截图和 dump 如何配对

不要靠文件名中的 App 名称判断，也不要把相邻文件随便凑成一组。配对规则：

1. dump 内 `package="..."` 决定实际 App：
   - 小红书：`com.xingin.xhs`
   - 抖音：`com.ss.android.ugc.aweme`
   - 闲鱼：`com.taobao.idlefish`
2. 截图与 dump 的设备别名必须一致，例如都为 `01` 或都为 `04`。
3. 时间差优先控制在 5 秒以内；本次多数样本在 0.3–4.1 秒内。
4. 页面内容可能在时间差内变化，下载后仍需人工查看截图，并从 XML 提取可见文本做一次交叉确认。
5. 保存远端与本地 SHA-256，确保不是传输或临时文件变化造成的错配。

本次发现两份正式证据虽然文件名为 `xhs-feed-*`，但截图实际是闲鱼，dump package 也是 `com.taobao.idlefish`。这两份没有计入小红书结果：

```text
run_570fdc1d-8986-491b-9235-3f5d7754c620/evidence/xhs-feed-*
run_b3099efa-e8a5-44ce-ae67-07cb88ca4d82/evidence/xhs-feed-*
```

这说明 **文件名不是 App 身份证据，package 才是**。

## 4. 算法现在怎么走

完整链路如下：

```text
既有截图
  → 绑定截图 SHA-256 与原始分辨率
  → 等比例缩放到最长边不超过 1280
  → 生成轮廓候选 + 横向行候选
  → 候选去重与数量限制
  → 普通组件扩边裁切并运行 GrabCut
  → 选择与原候选重叠最好的连通区域
  → 闭运算 / 开运算 / 填小孔
  → 距离变换计算安全点
  → 安全点映射回原始截图坐标
  → 建立行与子组件层级
  → 输出 blocks.json 和调试叠加图
```

### 4.1 输入绑定

`resolve_image()` 读取 PNG/JPEG，记录：

- 文件绝对路径；
- SHA-256；
- 原始分辨率；
- 分析分辨率；
- 分析坐标映射回原图的比例。

坐标只对同一 SHA 的截图有效，禁止把旧截图坐标直接复用到新画面。

### 4.2 候选生成

目前有两路候选：

1. `contour_proposals()`：灰度化、3×3 模糊、Canny 边缘、闭运算、轮廓框选，再按面积、尺寸、长宽比、填充度和紧致度打分。
2. `row_band_proposals()`：使用 Y 方向 Sobel 梯度形成横向强度曲线，根据边界峰值组合列表行。

两路候选合并后由 `deduplicate_proposals()` 按 IoU、包含关系和类型去重。当前默认最多保留 256 个；该值从 160 调高，是因为第一张真实页面在 160 处截断了返回和下载按钮。

### 4.3 RockClimbing 风格的 GrabCut 精修

列表行直接保留矩形，不跑 GrabCut。普通组件会：

1. 在候选框四周扩展约 18%；
2. 用原候选框作为 GrabCut 前景矩形种子；
3. 固定随机种子，运行 3 次迭代；
4. 从结果中选择与原候选重叠最好的连通区域；
5. 做一次闭运算、一次开运算和填孔；
6. 裁成紧 mask；失败则回退到原 bbox。

GrabCut 是当前主要耗时来源。真实页面的轮廓提议一般只有约 7–34 ms，但逐个精修可能把复杂抖音页面推到约 1.2 秒。

### 4.4 安全点击点

不直接使用矩形中心。`safe_point()` 对二值 mask 做距离变换，选择距离前景边缘最远的像素；若有多个同值点，选择最接近 mask 中心的一个。

这样可以避免：

- 空心图标中心落在洞里；
- 凹形组件的几何中心落到背景；
- 不规则组件点到透明边缘。

最终通过统一缩放比例映射回原始截图物理坐标，写入：

```json
{
  "blockId": "b123",
  "sourceBBox": [x, y, width, height],
  "sourceSafePoint": [x, y],
  "method": "grabcut",
  "safeClearancePx": 12.5
}
```

### 4.5 输出不是点击授权

当前 schema 的 `effect` 固定为 `none`。demo：

- 不连接手机；
- 不申请 lease；
- 不创建 job/session；
- 不调用 ADB；
- 不执行 tap。

未来即使 LLM 选择了 `blockId`，也只能使用算法生成的 `sourceSafePoint`，不能让 LLM 自己编物理坐标。

## 5. 怎么本地复现

推荐使用已具备 OpenCV 的本地环境：

```bash
cd /Users/a1234/Desktop/Coding/.worktrees/xhs-visual-tap-resolver-demo/experiments/visual-tap-resolver

/Users/a1234/Desktop/Coding/visual-grounding-poc/.venv/bin/python \
  visual_tap_demo.py resolve \
  --input /absolute/path/screen.png \
  --output-dir /absolute/path/resolved
```

跑基准：

```bash
/Users/a1234/Desktop/Coding/visual-grounding-poc/.venv/bin/python \
  visual_tap_demo.py benchmark \
  --input /absolute/path/screen.png \
  --iterations 20
```

测试：

```bash
/Users/a1234/Desktop/Coding/visual-grounding-poc/.venv/bin/python \
  -m unittest discover -s tests -p 'test_*.py' -v
```

最近验证结果：算法测试 `9/9` 通过，仓库 `npm run check` 通过。

当前系统默认 `python3` 是 Python 3.14，未安装 `cv2`，直接运行测试会在 import 阶段报 `ModuleNotFoundError: No module named 'cv2'`；这不是算法失败。也可以按 README 创建独立 `.venv` 并安装 `requirements.txt`。

## 6. 真实页面结果

详细报告：

```text
/Users/a1234/.codex/visualizations/2026/08/06/019fd4e1-ac4b-7261-a10d-3358b6d75f76/multi-app-evidence/benchmark-report.md
```

摘要：

| App | 页面 | 候选/顶层 | 3 次中位数 | dump 可点击覆盖 |
|---|---|---:|---:|---:|
| 小红书 | 长内容列表 | 256/159 | 588.7 ms | dump 无可点击节点，无法验真 |
| 小红书 | 本地草稿 | 67/46 | 145.0 ms | 4/4 = 100% |
| 小红书 | 保存草稿弹窗 | 76/25 | 154.0 ms | 2/2 = 100% |
| 抖音 | 搜索筛选 | 168/118 | 1038.8 ms | 23/26 = 88.5% |
| 抖音 | 双列搜索结果 | 187/111 | 1191.4 ms | 30/30 = 100% |
| 抖音 | 沉浸内容详情 | 256/183 | 454.0 ms | 18/26 = 69.2% |
| 闲鱼 | 草稿成功弹窗 | 67/44 | 199.0 ms | 2/2 = 100% |
| 闲鱼 | 发货方式/键盘 | 67/45 | 110.5 ms | dump 无可点击节点，无法验真 |
| 闲鱼 | 发布表单 | 92/46 | 216.6 ms | 16/17 = 94.1% |

9 张截图整体处理耗时中位数约 216.6 ms。这个数字只包含本地算法，不包含截图获取、文件传输、dump 获取或 LLM 调用；不能据此直接宣称端到端比 dump 快多少。

## 7. 当前最明显的问题：图片/视频内容过分割

抖音沉浸详情页的树木、人物、石头、文字笔画都被当成候选，导致：

- 256 个候选撞上上限；
- 真正的返回、静音等小控件被淹没或截断；
- 大量时间浪费在对媒体纹理运行 GrabCut；
- “候选存在”不等于“适合点击”。

用户已明确确认：大块图文/视频内容与软件控件无关，应当剔除；但媒体层上的暂停、扫描、广告关闭等浮层控件必须保留。视频画面本身如需支持点击，只保留一个可选的媒体中心块即可。

## 8. 下一步建议：媒体区域抑制

建议新增：

```text
detect_media_regions(image)
filter_proposals_by_media(proposals, media_regions)
```

推荐流程：

```text
截图
  → 检测大面积媒体矩形
  → 媒体内部不再生成普通纹理轮廓
  → 保留媒体边缘/角落的 UI 型覆盖控件
  → 可选保留一个 media-center 候选
  → 其余候选再进入 GrabCut
```

单帧可组合的信号：

- 区域占屏幕面积较大，例如大于 25–30%；
- 连续纹理/颜色熵明显高于周围 UI；
- 外部存在清晰矩形边界或上下 UI 分隔线；
- 内部小轮廓密度极高，但缺乏规则排列；
- 与顶部栏、底部栏、卡片行边界不重叠。

如果能取得连续两帧，优先使用时序信号：视频/图片内容变化，而返回、暂停、关注、互动栏等 UI 位置稳定。两帧差分通常比单帧猜媒体区更稳。

不能简单删除整个媒体矩形。建议保留：

- 距离媒体边界较近的高对比小图标；
- 常见角落覆盖控件；
- dump 中已知的可点击 bounds；
- 一个显式标记为 `media-surface` 的中心安全点。

建议验收目标：

1. 抖音沉浸页候选从 256 降到不超过 40；
2. 同页 26 个 dump 紧凑可点击区域覆盖从 69.2% 提升到至少 90%；
3. 不丢失返回、关注、搜索、暂停、静音和底部互动按钮；
4. 单页本地处理时间目标小于 150 ms；这是工程目标，不是当前已证明结果；
5. 小红书草稿、确认弹窗和闲鱼表单覆盖率不回退超过 2%；
6. 输出继续绑定截图 SHA，继续保持 `effect=none`。

## 9. 推荐的最终运行决策链

```text
有效 dump
  → 直接使用语义节点 bounds

dump 为空 / 稀疏 / WebView / 过期
  → 本地视觉候选
  → 媒体内容抑制
  → OCR / 规则 / 小模型排序

候选仍然歧义
  → LLM 只选择 blockId

没有高置信候选
  → fail closed
```

dump 与本地视觉可以并行启动以减少等待，但最终信任顺序仍然是：

```text
有效 dump > 高置信本地视觉块 > LLM 选择视觉块 > 拒绝执行
```

## 10. 边界与下一位接手者注意事项

1. 这份 handoff 属于 Mac 治理侧离线实验，不授权连接设备或执行点击。
2. 如需进入真机 dry-run，必须另行设计正式 capability，通过控制面的 job/session 和可见 lease；禁止旁路 ADB/GatewayOperator。
3. 真机集成前先做 overlay 人工验收，不要把 `blocks.json` 直接接到 tap。
4. 不要为让仓库全套测试通过而弱化既有 repair scope guard；实验目录触发该守卫是范围治理问题，应单独调整正式 scope，而不是删除安全断言。
5. 只把测试、算法、证据和端到端效果分别陈述；本地算法测试通过不等于已部署，不等于设备动作成功。
6. 当前没有 push，也没有 Windows 代码或运行状态改变。
