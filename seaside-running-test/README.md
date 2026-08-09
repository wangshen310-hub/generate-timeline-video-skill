# 海边跑步固定回归基准

这个目录的主要用途是测量渲染器代码，而不是反复更换素材来追求某一条演示视频的观感。除非基准本身升级，`timeline.json` 和四张关键帧应保持不变。

## 固定输入

- 2 个镜头，每段 1.5 秒；输出 1280×720、24 fps、72 帧、3 秒。
- `shot-001-end.png` 与 `shot-002-start.png` 字节相同，用于测试共享切点。
- 跑步包含大幅肢体运动，故意用稀疏关键帧暴露光流重影和端点不连续。

| 文件 | SHA-256 |
| --- | --- |
| `shot-001-start.png` | `045B7D7FB134AB30F9DCB19A765EDA7D72C5FB14CF57DBDE243A94AE105AA8D7` |
| `shot-001-end.png` | `C0484C45DAA83BB126C5184DDD778F7F78DE36843D19A87D4DFDC45EEE185DFB` |
| `shot-002-start.png` | `C0484C45DAA83BB126C5184DDD778F7F78DE36843D19A87D4DFDC45EEE185DFB` |
| `shot-002-end.png` | `3BFD9E770BCE41F3C039CCB97C5E16F8D432F14D79AA9CCBC2BD04C07AC36B70` |

## 验收顺序

1. `probe` 必须确认分辨率、帧率、帧数和时长完全匹配。
2. 严格渲染不得发生未报告的后端降级。
3. `benchmark` 检查近重复帧和最大时序突变所在帧。
4. 最后检查每个镜头首、中、尾及切点附近逐帧画面。数值不能代替主体数量、肢体结构和背景稳定性的视觉判断。

## 2026-08-09 实测

环境为 FFmpeg 9.0、官方 `rife-ncnn-vulkan` 20221029 Release、`rife-v4.6`、NVIDIA RTX 4060 Laptop GPU。时间只用于同机相对比较。

| 方案 | YDIF 近重复对 | YDIF jerk p95 | 约用时 | 视觉结论 |
| --- | ---: | ---: | ---: | --- |
| 仓库原成片 | 3 | 0.543 | — | 中间帧有明显双跑者重影 |
| 修复后 balanced 光流 | 2 | 0.741 | 数秒 | 去掉共享切点冻结，但大幅运动重影仍在 |
| RIFE direct | 0 | 1.938 | 66 秒 | 单一主体清晰，但模型在端点附近不收敛，背景变化突增 |
| RIFE recursive | 0 | 0.337 | 118 秒 | 单一主体、端点稳定、切点最平顺 |

OpenCV 的独立检查中，recursive 版本为 72/72 解码帧、0 个 MAD<0.5 的近重复对，光流 p95 逐帧 jerk 为 0.176。direct 版本对应值为 1.687。

额外测试的 `large-motion` FFmpeg 配置虽然降低部分数值，却产生肢体撕裂和背景拖拽，因此保留为实验项，不作为默认。端点线性锚定也能降低 jerk，但会重新引入透明残影，同样未采用。

## 决策

- 项目默认依赖仍是 Python 标准库加 FFmpeg；`balanced` 保持默认光流配置。
- 用户显式选择 RIFE 时，默认使用质量优先的 `recursive` 中点二分策略。
- `direct` 保留为速度选项，但必须额外检查片头、片尾和共享切点。
- 对真实制作，大幅人体运动仍应增加关键帧；更强插帧不能恢复不存在的物理信息。

## 复现

```bash
SCRIPT=generate-timeline-video/scripts/timeline_video.py

python3 "$SCRIPT" validate seaside-running-test/timeline.json

python3 "$SCRIPT" render seaside-running-test/timeline.json \
  --output seaside-running-test/output/rife-recursive.mp4 \
  --interpolation rife \
  --rife-strategy recursive \
  --rife-executable /path/to/rife-ncnn-vulkan \
  --rife-model /path/to/rife-v4.6 \
  --rife-gpu 0 \
  --strict

python3 "$SCRIPT" benchmark \
  seaside-running-test/output/rife-recursive.mp4 \
  --baseline seaside-running-test/output/seaside-running.mp4
```

RIFE 可执行文件和模型不得提交到仓库。
