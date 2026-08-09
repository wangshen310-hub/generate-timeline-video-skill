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

演示视频技术指标：1280×720、24 fps、72 帧、3 秒、H.264 MP4，无音轨。

这是一个刻意使用稀疏关键帧的插值压力测试。跑步包含大幅肢体运动，仅用三个关键帧会在中间帧出现可见的光流重影；实际制作应把关键帧间隔缩短到约 0.5-1 秒，或者接入更强的专用视频/插帧模型。

## License

[MIT](LICENSE)
