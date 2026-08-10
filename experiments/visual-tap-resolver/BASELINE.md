# BASELINE — CV 分块基准（2026-08-10）

Stage A0 锚定基线。后续每个优化 stage 必须与此对比，证明不回归。

## 机器 / 运行环境

- 机器：i3-12100 4C/8T、16GB、无 NVIDIA GPU（Intel UHD 730），CPU-only。
- OS：Windows 10 Pro 10.0.19045。
- 解释器：`.venv-ocr\Scripts\python.exe`（cv2 4.10.0 / numpy 2.3.5）。
  **不要用系统 python 3.14.6**（无 cv2，会误判成算法回归）。
- 输入：`visual_tap_demo.py synthetic` 生成的 540x1200 合成页（3 状态栏图标 + 5 行 + 4 底栏 tab）。

## 测试基线

`python -m unittest discover -s tests -v` → **38 个全绿**（test_resolver 13 + test_vision_contract 25），3.03s。

## Benchmark 基线（synthetic screen.png，iterations=20）

```
totalMs:  mean 588.813  median 580.695  p95 654.119  min 554.75  max 699.426
stageMeanMs:
  decode         4.421
  resize         0.566
  proposals     16.447
  mediaSuppress  8.710
  ocr            0.002
  refine       558.668   ← 占 total 94.9%，唯一大头（GrabCut）
  total        588.813
```

**关键结论：refine 桶（逐组件 GrabCut）占 95%。** 这是提速的唯一大杠杆：
A4 并行化（输出逐位一致）+ Stage B 降 GrabCut（改输出，config 开关隔离）是唯二能到
<150ms 目标的路径；proposals/mediaSuppress 是微优化（合计 ~25ms）。

## resolve 基线（`resolve --output-dir ./out/baseline --write-masks`）

- BLOCKS=37，ROOT_BLOCKS=17，TOTAL_MS≈589.55。
- blocks.json 顶层含 `timingMs`（非 manifest 基字段，对比时剥掉）；其余字段全部确定性。

## HANDOFF 目标（未达成项，后续 stage 的验收线）

| 目标 | 现状 | 目标值 |
|---|---|---|
| 单页本地处理 | ~589ms（synthetic） | **<150ms** |
| 抖音沉浸页候选数 | 256（cap 被媒体过分割灌满） | **≤40** |
| 同页 26 dump 紧凑区覆盖 | 69.2% | **≥90%** |
| 返回/关注/搜索/暂停/静音/底栏按钮 | 保留 | 保留 |
