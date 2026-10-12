# 静帧 GIF 生成 Skill

将用户提供或 AI 生成的静帧按顺序和停留时长合成为 GIF。每一张图就是实际显示的一帧，不使用 RIFE、光流、LTX 或混帧来生成中间动作。

仓库及调用名 `generate-timeline-video` 保持兼容；默认工作流已改为 GIF。旧视频渲染器与回归用例保留，只有明确要求旧 MP4 流程时才使用。

## 工作方式

1. 规划可见状态、每帧时长和循环方式，适用于角色、物体、场景、特效与抽象动画。
2. 生成或整理连续静帧；保持身份、画面构图和必要背景一致，检查三个以上状态的节奏。
3. 用实际图片制作短试片，检查正常速度播放与末帧接首帧，修复跳变后再扩展。
4. 共享调色板编码为 GIF，验证逐帧时间、尺寸、帧数、循环及完整解码，再原子发布。

GIF 不会自动让稀疏动作变顺。缺失的姿态需要制作出来；重复图片或提高标称帧率不能创造动作。默认可从最长边 512 像素、每帧 100 毫秒开始，按实际动作调整。

## 使用

依赖 Python 3.10+、FFmpeg，以及需要生成素材时的图像生成能力。Python 无第三方包依赖。

```text
python generate-timeline-video/scripts/still_gif.py init my-gif --frames 12
# 填写 gif.json 中的状态和提示词，生成 images/ 中的图片。
python generate-timeline-video/scripts/still_gif.py validate my-gif/gif.json
python generate-timeline-video/scripts/still_gif.py render my-gif/gif.json --output my-gif/final.gif
python generate-timeline-video/scripts/still_gif.py probe my-gif/gif.json --output my-gif/final.gif
```

- [技能工作流](generate-timeline-video/SKILL.md)
- [GIF 清单格式与时间精度](generate-timeline-video/references/gif-schema.md)
- [旧 MP4 工作流](generate-timeline-video/references/legacy-video-workflow.md)

将 `generate-timeline-video` 文件夹复制到自己的 Codex skills 目录，然后调用：

```text
使用 $generate-timeline-video 制作一个由连续静帧组成的 GIF 动图。
```

## 验证

```text
python -m unittest discover -s tests -v
```

把 FFmpeg 和 FFprobe 加入 PATH 后运行完整测试。CI 在 Python 3.10 和 3.13 上执行同一套测试，包括真实 GIF 编码、解码后画面顺序、非均匀帧时长、循环设置和原子发布，以及保留的视频回归测试。技术检查通过不代表视觉流畅度通过。

GIF 无音轨，最多 256 色。当前渲染器按原比例缩放并补白，将透明区域合成白色背景；不支持透明 GIF 输出。每帧时长必须是 10 毫秒的整数倍且至少 20 毫秒，以避免极短延迟在播放器中被明显重解释；不同播放器的实际调度仍可能不同。
