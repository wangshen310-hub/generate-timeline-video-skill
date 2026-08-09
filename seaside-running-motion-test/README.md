# Seaside running motion demo

This is the motion-positive companion to `seaside-running-test/`. The original
folder remains a fixed sparse-keyframe regression benchmark. This folder adds
one distinct stride pose to each 1.5-second shot so the renderer has actual
foot-contact changes to interpolate.

RIFE and optical flow interpolate supplied images; neither can invent a missing
footstep from two copies of the same pose. The `intermediate_images` field is
therefore intentional and is part of the reproducible demo input.

## Render with the tested RIFE backend

Resolve `python3`/`python`, put FFmpeg and FFprobe on `PATH`, and keep the
RIFE executable/model outside the repository:

```bash
SCRIPT=generate-timeline-video/scripts/timeline_video.py
python3 "$SCRIPT" validate seaside-running-motion-test/timeline.json
python3 "$SCRIPT" render seaside-running-motion-test/timeline.json \
  --output seaside-running-motion-test/output/rife-recursive.mp4 \
  --interpolation rife \
  --rife-executable /path/to/rife-ncnn-vulkan \
  --rife-model /path/to/rife-v4.6 \
  --rife-gpu 0 \
  --rife-strategy recursive \
  --strict
python3 "$SCRIPT" probe seaside-running-motion-test/output/rife-recursive.mp4 \
  --manifest seaside-running-motion-test/timeline.json
python3 "$SCRIPT" benchmark seaside-running-motion-test/output/rife-recursive.mp4
```

On Windows PowerShell, replace `python3` with `python`; invoke the script with
`& $PYTHON $SCRIPT ...` when the command is stored in a variable.

The checked motion-positive run on FFmpeg 9.0 and RIFE v4.6 is 1280x720, 24 fps,
72 frames, and 3.0 seconds. It has no near-duplicate frame pairs. RIFE is an
optional external dependency and is never committed to this repository.

## Keyframe checksums

| file | SHA-256 |
| --- | --- |
| `shot-001-start.png` | `045B7D7FB134AB30F9DCB19A765EDA7D72C5FB14CF57DBDE243A94AE105AA8D7` |
| `shot-001-mid.png` | `240D993644386B8CF0C9AE68DB3CAF96820502FAABE60E02026EEB15BC38C940` |
| `shot-001-end.png` | `C0484C45DAA83BB126C5184DDD778F7F78DE36843D19A87D4DFDC45EEE185DFB` |
| `shot-002-start.png` | `C0484C45DAA83BB126C5184DDD778F7F78DE36843D19A87D4DFDC45EEE185DFB` |
| `shot-002-mid.png` | `B353DEE6F762099B81961FC952785E824D5D66D497BAE4B1F6CBB6F22D86806B` |
| `shot-002-end.png` | `3BFD9E770BCE41F3C039CCB97C5E16F8D432F14D79AA9CCBC2BD04C07AC36B70` |
