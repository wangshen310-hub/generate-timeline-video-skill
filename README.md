# pic2gif

将用户提供或 AI 生成的静帧按顺序和停留时长合成为 GIF。每一张图就是实际显示的一帧，不使用 RIFE、光流、LTX 或混帧来生成中间动作。

技能目录与调用名为 `pic2gif`，默认输出 GIF。旧视频渲染器与回归用例保留，只有明确要求旧 MP4 流程时才使用。

## 工作方式

1. 规划可见状态、每帧时长和循环方式，适用于角色、物体、场景、特效与抽象动画。
2. 生成或整理连续静帧；保持身份、画面构图和必要背景一致，检查三个以上状态的节奏。
3. 用实际图片制作短试片，检查正常速度播放与末帧接首帧，修复跳变后再扩展。
4. 编码为预览 GIF，核对实际属性变化、固定区域、逐帧时长和循环；审查通过后才发布最终文件。

GIF 不会自动让稀疏动作变顺。缺失的姿态需要制作出来；重复图片或提高标称帧率不能创造动作。默认可从最长边 512 像素、每帧 100 毫秒开始，按实际动作调整。

## 使用

依赖 Python 3.10+、FFmpeg，以及需要生成素材时的图像生成能力。Python 无第三方包依赖。

```text
python pic2gif/scripts/still_gif.py init my-gif --frames 12
# 先填写 plan、每帧状态、时长和提示词。
python pic2gif/scripts/still_gif.py plan-check my-gif/gif.json --allow-missing
# 然后生成并检查 images/ 中的图片。
python pic2gif/scripts/still_gif.py validate my-gif/gif.json
python pic2gif/scripts/still_gif.py render my-gif/gif.json --output my-gif/preview.gif
python pic2gif/scripts/still_gif.py inspect my-gif/gif.json --output my-gif/preview.gif --review-dir my-gif/review-001
# 打开审查页，填写真实观测与检查记录；未审/返修/素材变化不能发布。
python pic2gif/scripts/still_gif.py review-status my-gif/review-001
python pic2gif/scripts/still_gif.py publish my-gif/review-001 --output my-gif/delivery/final.gif
```

- [技能工作流](pic2gif/SKILL.md)
- [GIF 清单格式与时间精度](pic2gif/references/gif-schema.md)
- [计划、实际观测与审查契约](pic2gif/references/review-workflow.md)
- [旧 MP4 工作流](pic2gif/references/legacy-video-workflow.md)

将 `pic2gif` 文件夹复制到自己的 Codex skills 目录，然后调用：

```text
使用 $pic2gif 制作一个由连续静帧组成的 GIF 动图。
```

## 验证

```text
python -m unittest discover -s tests -v
```

把 FFmpeg 和 FFprobe 加入 PATH 后运行完整测试。CI 在 Python 3.10 和 3.13 上执行同一套测试，包括真实 GIF 编码、解码后画面顺序、非均匀帧时长、循环设置和原子发布，以及保留的视频回归测试。技术检查通过不代表视觉流畅度通过。

GIF 无音轨，最多 256 色。当前渲染器按原比例缩放并补白，将透明区域合成白色背景；不支持透明 GIF 输出。每帧时长必须是 10 毫秒的整数倍且至少 20 毫秒，以避免极短延迟在播放器中被明显重解释；不同播放器的实际调度仍可能不同。

## 通用质量检查

`plan.intent` 区分运动和合法静止，实际属性观测使用声明的参考系与单位。可选速度/加速度检查包括循环接头；固定区域检查使用输出解码像素，不按角色或场景关键词分支。检查不能自动推断自然运动。

`inspect` 创建可播放的 GIF 审查页和三帧窗口，观测值初始为 null，必须从实际素材测量。素材、时间线、成片或审查快照改变会使原验收失效。`publish` 只发布通过记录对应的原始字节；`render` 始终只表明技术预览成功。

初始化会明确报告已有图片，不覆写素材。可选调色板颜色数、抖动与文件大小预算支持按用途优化。旧无 plan 清单仍可生成预览，需要补充计划与审查才能通过新发布流程。
