# Generate Timeline Video Skill

一个供 Codex 使用的时间线视频生成 Skill：先规划分镜并生成连续关键帧，再使用 FFmpeg 把关键帧补成指定帧率的视频。

This Codex skill turns a written timeline into a reproducible MP4 by generating continuity-aware keyframes, interpolating them, assembling transitions, and validating the encoded result.

## 工作原理

1. 明确每个镜头的可观察目标：什么保持不变、什么连续变化、什么是离散事件，以及相对于画面、场景或其他对象的关系。
2. 按轨迹、速度变化、接触和遮挡等事件安排关键帧；检查提示词中的约束是否冲突。
3. 用图像生成能力制作代表性短片的素材，检查实际图片能否组成连续过程，再用 `hold`、`blend`、FFmpeg 光流或可选 RIFE 渲染试验。
4. 试验通过后扩展时长、合并镜头和可选音轨，再检查新接头与整段播放。
5. 分别验证文件技术指标、可测属性与视觉表现；缺少播放审查保持待审，已知缺陷需要返修。

插帧无法从任意两张图片恢复正确的运动。先判断缺陷属于意图/约束、源图、时间安排、插值还是合成，再修复相应环节；更多关键帧和更高帧率本身不保证流畅。

## 目录

- `generate-timeline-video/`：Codex Skill 和无第三方 Python 依赖的渲染器。
- `seaside-running-test/`：海边跑步测试的时间线、关键帧和 24 fps 成片。
- `seaside-running-motion-test/`: an older three-pose-per-shot motion fixture.
- `dense-running-test/`: the code-planned 0.25-second articulated-motion regression fixture.

## 依赖

- Python 3.10+
- FFmpeg
- ffprobe
- Codex 图像生成能力，或者用户提供的关键帧

渲染器本身只使用 Python 标准库。

## 动作计划、精确时间与检查工具

- 显式中间关键帧按 `floor(at * fps + 0.5)` 定位；过近事件会报错，成片报告列出实际帧号和时间调整。
- 递归 RIFE 用中点网格及局部时间推理生成目标帧，不再通过 FFmpeg 时域混帧对齐帧率。
- `plan-motion timeline.json --write` 生成可编辑的动作计划，记录变化对象、状态、保持项、参考图和人工检查状态，适用于角色及非角色内容。
- `render ... --cache-dir .timeline-cache --command-timeout 300` 保留已验证的片段，按图片、参数、工具和模型内容失效；中断后可复用已完成片段。
- `inspect final.mp4 --manifest timeline.json --output-dir review-001` 生成相邻图片对照、带帧号的成片抽样、异常位置和本地播放页。检查结果默认待审，不把技术通过当作视觉通过。
- `review-status review-001 --write` 核对检查记录、未解决问题和受检视频哈希。播放未检查或存在问题时只能交付待审预览；该命令不代替视觉判断。
- 可选 `motion_checks` 为输出属性声明参考系、预期采样、容差和速度/加速度范围；`validate` 检查计划一致性。`inspect` 生成绑定视频哈希的 `motion-observations.json` 空模板，`review-status` 比较真实测量与计划。它不自动追踪像素，也不能从文字状态推断自然运动。
- 所有场景共享[运动规划流程](generate-timeline-video/references/motion-planning.md)：跨三个以上状态检查节奏，新运动设置先试验代表区间，周期动作先验收完整周期；简单静态镜头可直接用自身验证。固定场景坐标与固定屏幕坐标需要区分，避免约束冲突。

缓存是可丢弃的临时资产，不应放在源素材目录。真实 RIFE 运行时仍需单独提供；CI 使用可控的运动边缘推理替身验证时间采样和实际编码结果，不能代替真实模型的视觉质检。

## 渲染正确性与验证

- `blend` 包含精确的首尾采样；共享 cut 边界使用半开区间，下一镜头提供边界帧。
- 多关键帧先插值拼接，再对整个镜头应用一次运镜，避免平移和缩放在片段边界重启。
- `hold`（包括 `--interpolation hold`）只读取首图，忽略未使用的中间图、尾图和时间点。
- 校验和关键帧规划均检查帧预算；规划保留时间精度，重复 `--write` 不增加槽位，也不复用冲突的文件名。
- 光流和 RIFE 的图片归一化缓存在单次渲染内复用；纯 cut 拼接使用视频 stream-copy。带转场的拼接仍编码。
- 标准输出只包含 JSON，执行日志写入标准错误。成片检查尺寸、帧数、帧率、视频/容器时长、音轨和完整解码后才发布。
- 输出必须为 `.mp4`。临时成片与输出在同一文件系统；`--force` 原子替换，无 `--force` 时原子创建并拒绝并发覆盖。

运行完整测试（必须先把 FFmpeg 与 FFprobe 加入 PATH，否则集成测试会跳过）：

```text
python -m unittest discover -s tests -v
```

CI 在 Python 3.10 和 3.13 上运行单元测试、真实 FFmpeg 集成测试及三个固定示例的校验。数值约束测试覆盖静止、连续变化、离散事件、非均匀采样和方向反转，并从实际编码的画面检测停顿/突变与转场时间映射。RIFE 实际推理需要外部运行时；CI 的可控推理替身验证采样逻辑，不能证明真实生成内容自然。

Windows PowerShell 示例：

```powershell
$renderer = "generate-timeline-video/scripts/timeline_video.py"
python $renderer validate dense-running-test/timeline.json
python $renderer render dense-running-test/timeline.json --interpolation blend --output demo.mp4
python $renderer probe demo.mp4 --manifest dense-running-test/timeline.json
```

## 安装 Skill

将 `generate-timeline-video` 目录复制到 Codex Skill 目录：

```bash
cp -R generate-timeline-video "${CODEX_HOME:-$HOME/.codex}/skills/"
```

然后在 Codex 中调用：

```text
使用 $generate-timeline-video 把我的时间线制作成 24 fps MP4。
```

## 命令行渲染
以下示例使用 `python3`；Windows 如果只有 `python`，直接替换命令名即可。


```bash
SCRIPT=generate-timeline-video/scripts/timeline_video.py

python3 "$SCRIPT" init my-video \
  --title "My video" \
  --shots 3 \
  --shot-duration 3 \
  --size 1280x720 \
  --fps 24 \
  --subject-motion articulated

python3 "$SCRIPT" plan-keyframes my-video/timeline.json --write
# 先规划可观察属性并试验代表性区间；通过后再扩展，补齐 missing_images。
python3 "$SCRIPT" validate my-video/timeline.json
python3 "$SCRIPT" render my-video/timeline.json --output my-video/output/final.mp4
python3 "$SCRIPT" probe my-video/output/final.mp4 --manifest my-video/timeline.json
```

完整字段说明见 [`timeline-schema.md`](generate-timeline-video/references/timeline-schema.md)。

## 演示

- [海边跑步时间线](seaside-running-test/timeline.json)
- [24 fps 演示视频](seaside-running-test/output/seaside-running.mp4)
- [固定回归基准与实测记录](seaside-running-test/README.md)

演示视频技术指标：1280×720、24 fps、72 帧、3 秒、H.264 MP4，无音轨。

这是一个刻意使用稀疏关键帧的插值压力测试。跑步包含大幅肢体运动，仅用三个关键帧会在中间帧出现可见的光流重影。实际制作应遵循共享规划与试验流程；`subject_motion: "articulated"` 的 0.25 秒默认间隔只检查采样密度，不能证明轨迹、步态或节奏正确。

## Quality controls and optional backends

- Byte-identical cut boundaries are de-duplicated without changing the declared
  frame count or duration.
- The balanced FFmpeg optical-flow profile remains the default. The
  large-motion profile is experimental and must pass project-specific visual
  QA before use.
- RIFE ncnn Vulkan is supported as an optional backend through explicit CLI
  paths. Its executable and model are not bundled with this repository.
  Recursive midpoint interpolation is the quality-first default; direct
  arbitrary-timestep interpolation remains available when speed matters.
- Motion-density validation warns whenever semantic keyframe spacing exceeds the
  declared limit (0.25 s by default for articulated action). `plan-keyframes`
  can write the missing timed pose slots before any video render starts.
- A completed render is probed before it atomically replaces the requested
  output. Even with `--force`, the manifest and referenced source media cannot
  be used as output paths.

Example profile override:

    python3 "$SCRIPT" render my-video/timeline.json \
      --output my-video/output/final.mp4 \
      --optical-flow-profile large-motion

Example optional RIFE render:

    python3 "$SCRIPT" render my-video/timeline.json \
      --interpolation rife \
      --rife-executable /path/to/rife-ncnn-vulkan \
      --rife-model /path/to/rife-v4.6 \
      --rife-gpu 0 \
      --rife-strategy recursive \
      --strict

See [interpolation-backends.md](generate-timeline-video/references/interpolation-backends.md)
for backend selection, GitHub implementation comparisons, licenses, and
fallback behavior.

## Regression benchmark

Use the same source media and compare a candidate against a known baseline:

    python3 "$SCRIPT" benchmark my-video/output/candidate.mp4 \
      --baseline my-video/output/baseline.mp4

The JSON report checks geometry and reports FFmpeg signalstats temporal-luma
difference, temporal-luma jerk, near-duplicate adjacent frame pairs, and the
five frame locations with the largest motion change. These are descriptive
regression signals, not automatic proof of visual quality; always pair them
with first/middle/last-frame and transition inspection.

## Tests

The test suite uses only Python's standard library. FFmpeg integration tests run
automatically when ffmpeg and ffprobe are on PATH:

    python3 -m unittest discover -s tests -v

GitHub Actions runs the same suite and validates the fixed seaside demo
manifest on every push and pull request.

## License

[MIT](LICENSE)

## Motion-positive demo

The fixed `seaside-running-test/` input is intentionally sparse for renderer regression. The older [`seaside-running-motion-test/`](seaside-running-motion-test/README.md) adds one stride midpoint per shot but does not prove fluent articulated motion. Production uses the shared property/trajectory/pilot workflow; the 0.25-second spacing policy is only a sampling check.

The renderer now warns when adjacent optical-flow or RIFE keyframes are byte-identical, because interpolation cannot invent motion between duplicate poses.
