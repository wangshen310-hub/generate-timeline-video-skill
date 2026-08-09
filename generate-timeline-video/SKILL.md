---
name: generate-timeline-video
description: Create short videos from a written timeline by planning shots, generating continuity-aware AI keyframes, interpolating each image pair into exact-frame-rate motion, assembling transitions, and muxing optional audio into an MP4. Use when Codex is asked to generate a video, animate still images, turn a script or storyboard into video, create an animatic, synthesize in-between frames, or build a timeline-based MP4; also trigger for Chinese requests involving 视频、分镜、关键帧、插帧、补帧, or 图片生成视频.
---

# Generate Timeline Video

Turn a narrative timeline into a reproducible video project. Use image generation for visual content and the bundled FFmpeg pipeline for deterministic frame interpolation, transitions, encoding, and verification.

## Set expectations

- Treat generated images as keyframes, not as 24 independently generated frames per second. Independent generations flicker and lose identity.
- Describe `blend` as pixel blending and `optical-flow` as motion estimation. Never claim either method reconstructs physically correct hidden motion.
- Add intermediate keyframes or split a shot when pose, layout, camera angle, lighting, or object identity changes substantially.
- Default to 1280x720, 24 fps, H.264 MP4, 2-4 seconds per shot, and no audio unless the request says otherwise.
- Keep every generated or copied artifact inside the user's chosen project directory.

## Run the workflow

### 1. Check the local renderer

Locate this skill directory, then set `SCRIPT` to `scripts/timeline_video.py` inside it. Confirm that `python3`, `ffmpeg`, and `ffprobe` are available. Do not install packages silently; the renderer uses only Python's standard library and FFmpeg.

### 2. Create the project and timeline

Read [references/timeline-schema.md](references/timeline-schema.md) when authoring or repairing `timeline.json`.

Initialize a safe project skeleton:

```bash
python3 "$SCRIPT" init <project-dir> --title "<title>" --shots 3 --shot-duration 3 --size 1280x720 --fps 24
```

Translate the request into contiguous shots. Give each shot one visual purpose and put generation instructions in `prompt` plus invariant facts in `continuity`. Use two keyframes for visible motion and one for an intentional hold.

### 3. Generate continuity-aware keyframes

Use the available image-generation capability rather than drawing frames in Python.

1. Generate the first appearance of each recurring character, object, and location as an anchor.
2. Derive later keyframes by editing the preceding image or reusing the anchor whenever the tool supports image references. Avoid independent regeneration.
3. Repeat the same continuity block verbatim: identity, wardrobe, palette, lens, time of day, and aspect ratio.
4. Ask for clean full-frame imagery without captions, watermarks, borders, or UI unless those are intentional.
5. Inspect every image. Regenerate identity drift, accidental text, malformed anatomy, or discontinuous geometry before rendering.
6. Save files at the exact paths recorded in `timeline.json`.

Keep adjacent optical-flow keyframes close in composition. As a rule of thumb, insert another keyframe every 1-2 seconds for articulated motion and every 2-3 seconds for slow camera or atmospheric motion.

### 4. Choose interpolation deliberately

- Use `hold` for one image, freeze frames, or a still with optional camera motion.
- Use `blend` for lighting changes, abstract imagery, flat graphics, and the most reliable fallback.
- Use `optical-flow` for modest spatial displacement with stable, textured subjects and backgrounds. Prefer `blend` or `hold` plus camera motion for crisp geometric graphics that would visibly ghost.
- Split the shot instead of interpolating through cuts, large pose changes, entering or disappearing objects, or unrelated compositions.

Camera motion presets are `static`, `zoom-in`, `zoom-out`, `pan-left`, `pan-right`, `pan-up`, and `pan-down`. The pan name describes the camera viewport, so foreground content appears to travel in the opposite direction. These are compositional moves, not 3D scene reconstruction.

### 5. Validate before rendering

```bash
python3 "$SCRIPT" validate <project-dir>/timeline.json
```

Resolve every reported error. Treat frame-rounding notices as intentional only after checking timing. The renderer rounds each duration to the nearest whole frame.

### 6. Render and verify

```bash
python3 "$SCRIPT" render <project-dir>/timeline.json --output <project-dir>/output/final.mp4
python3 "$SCRIPT" probe <project-dir>/output/final.mp4 --manifest <project-dir>/timeline.json
```

The renderer falls back from failed optical flow to `blend` and reports that choice. Pass `--strict` when silent fallback is unacceptable. Pass `--force` only when replacing the requested output is safe.

Inspect at least the first, middle, and last frame of every shot plus every transition. Confirm subject continuity, chronology, aspect ratio, exact fps, total frame count, and audio sync. If an interpolation artifact appears, add a keyframe or switch only that shot to `blend`; do not lower QA thresholds to preserve a first render.

## Preserve reproducibility

Return the MP4 together with `timeline.json` and the keyframes. Keep prompt and continuity fields in the manifest even though the renderer ignores them. State any optical-flow fallback, rounded timing, missing audio, or intentional limitation in the handoff.
