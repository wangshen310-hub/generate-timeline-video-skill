# Generate Timeline Video Skill

一个供 Codex 使用的时间线视频生成 Skill：先规划分镜并生成连续关键帧，再使用 FFmpeg 把关键帧补成指定帧率的视频。

This Codex skill turns a written timeline into a reproducible MP4 by generating continuity-aware keyframes, interpolating them, assembling transitions, and validating the encoded result.

## 工作原理

1. Codex 把脚本拆成时间线和镜头。
2. 图像生成能力创建少量、身份一致的关键帧。
3. `hold`、`blend` 或 FFmpeg motion-compensated interpolation 补齐中间帧。
4. FFmpeg 合并镜头、转场和可选音轨。
5. `ffprobe` 校验分辨率、帧率、帧数和时长。

插帧并不能从两张图片恢复物理上完全正确的运动。大幅姿态、构图或物体变化应该增加关键帧。

## 目录

- `generate-timeline-video/`：Codex Skill 和无第三方 Python 依赖的渲染器。
- `seaside-running-test/`：海边跑步测试的时间线、关键帧和 24 fps 成片。

## 依赖

- Python 3.10+
- FFmpeg
- ffprobe
- Codex 图像生成能力，或者用户提供的关键帧

渲染器本身只使用 Python 标准库。

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
?????? `python3`??? Windows ????? `python`??????? `python3` ??? `python`?


```bash
SCRIPT=generate-timeline-video/scripts/timeline_video.py

python3 "$SCRIPT" init my-video \
  --title "My video" \
  --shots 3 \
  --shot-duration 3 \
  --size 1280x720 \
  --fps 24

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

这是一个刻意使用稀疏关键帧的插值压力测试。跑步包含大幅肢体运动，仅用三个关键帧会在中间帧出现可见的光流重影；实际制作应把关键帧间隔缩短到约 0.5-1 秒，或者接入更强的专用视频/插帧模型。

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
- Sparse optical-flow or RIFE shots longer than one second produce a warning so
  visually risky timelines are not silently accepted.
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
