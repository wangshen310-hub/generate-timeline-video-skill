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
- Keep provided demo media fixed when it is being used as a regression benchmark; improve the code before changing the test input.
- Keep every generated or copied artifact inside the user's chosen project directory.

## Run the workflow

### 1. Check the local renderer

Locate this skill directory, then set `SCRIPT` to `scripts/timeline_video.py` inside it. Resolve the Python interpreter by preferring `python3` and falling back to `python`, then set `PYTHON` to that command. Confirm that FFmpeg and FFprobe are available. If a task-local FFmpeg `bin` directory already exists, add it only to the current process PATH; otherwise ask for a path or installation authorization. Do not install packages silently; the default renderer uses only Python's standard library and FFmpeg. RIFE is optional, uses an external executable plus model, and must not be downloaded silently. Read [references/interpolation-backends.md](references/interpolation-backends.md) before enabling it.

### 2. Create the project and timeline

Read [references/timeline-schema.md](references/timeline-schema.md) when authoring or repairing `timeline.json`.

Initialize a safe project skeleton:

```bash
"$PYTHON" "$SCRIPT" init <project-dir> --title "<title>" --shots 3 --shot-duration 3 --size 1280x720 --fps 24 --subject-motion articulated
```

Translate the request into contiguous shots. Give each shot one visual purpose and put generation instructions in `prompt` plus invariant facts in `continuity`. Use one image for an intentional hold. For visible subject motion, declare `subject_motion` and plan the semantic poses before generating assets:

```bash
"$PYTHON" "$SCRIPT" plan-keyframes <project-dir>/timeline.json --write
```

This writes explicit `at` times and deterministic placeholder paths. Generate those images next; the renderer is downstream of this motion plan.

### 3. Generate continuity-aware keyframes

Use the available image-generation capability rather than drawing frames in Python.

1. Generate the first appearance of each recurring character, object, and location as an anchor.
2. Derive later keyframes by editing the preceding image or reusing the anchor whenever the tool supports image references. Avoid independent regeneration.
3. Repeat the same continuity block verbatim: identity, wardrobe, palette, lens, time of day, and aspect ratio.
4. Ask for clean full-frame imagery without captions, watermarks, borders, or UI unless those are intentional.
5. Inspect every image. Regenerate identity drift, accidental text, malformed anatomy, or discontinuous geometry before rendering.
6. Save files at the exact paths recorded in `timeline.json`.

Keep adjacent optical-flow keyframes close in composition. For articulated motion, put distinct pose images at explicit `at` times in `intermediate_images`; RIFE cannot invent a footstep when supplied poses keep the same leg configuration. Default to at most 0.25 seconds between semantic poses for walking, running, hands, or other articulated action. Use up to 1 second for slow subject motion. Camera-only or atmospheric motion may use `subject_motion: "none"`. If validation reports a motion-gap warning, rerun `plan-keyframes --write` and generate every missing pose before rendering.

### 4. Choose interpolation deliberately

- Use `hold` for one image, freeze frames, or a still with optional camera motion.
- Use `blend` for lighting changes, abstract imagery, flat graphics, and the most reliable fallback.
- Use `optical-flow` for modest spatial displacement with stable, textured subjects and backgrounds. Prefer `blend` or `hold` plus camera motion for crisp geometric graphics that would visibly ghost.
- Split the shot instead of interpolating through cuts, large pose changes, entering or disappearing objects, or unrelated compositions.

- Keep the `balanced` optical-flow profile as the default. Treat `large-motion` as experimental and compare its output visually because wider search can create tearing or duplicated anatomy.
- Use optional `rife` for larger or articulated motion only when the user has an available RIFE ncnn Vulkan executable and v4 model. Prefer its `recursive` midpoint strategy for stable endpoints; use `direct` only when faster rendering is worth extra endpoint QA. It falls back to optical flow and then blend unless `--strict` is set.
Camera motion presets are `static`, `zoom-in`, `zoom-out`, `pan-left`, `pan-right`, `pan-up`, and `pan-down`. The pan name describes the camera viewport, so foreground content appears to travel in the opposite direction. These are compositional moves, not 3D scene reconstruction.

### 5. Validate before rendering

```bash
"$PYTHON" "$SCRIPT" validate <project-dir>/timeline.json
```

Resolve every reported error. Treat frame-rounding notices as intentional only after checking timing. The renderer rounds each duration to the nearest whole frame.
Treat a warning that adjacent optical-flow/RIFE keyframes are byte-identical as an input defect: add a distinct pose or choose `hold`; interpolation cannot create the missing motion. Use `seaside-running-motion-test/` as the repository's motion-positive reference.

### 6. Render and verify

```bash
"$PYTHON" "$SCRIPT" render <project-dir>/timeline.json --output <project-dir>/output/final.mp4
"$PYTHON" "$SCRIPT" probe <project-dir>/output/final.mp4 --manifest <project-dir>/timeline.json
```

When the project has a fixed demo or prior render, run `benchmark <candidate> --baseline <baseline>`. Treat its temporal-luma and near-duplicate metrics as regression signals, not a replacement for visual inspection; a candidate may have more semantic motion while also having a larger luma jerk.

The renderer reports the actual backend, RIFE strategy, and optical-flow profile. Failed RIFE falls back to optical flow, then failed optical flow falls back to `blend`. Pass `--strict` when any fallback is unacceptable. A candidate is probed before atomically replacing the output, and source media paths are protected even with `--force`.

Inspect at least the first, middle, and last frame of every shot plus every transition. Confirm subject continuity, chronology, aspect ratio, exact fps, total frame count, audio sync, and that shared cut boundaries do not freeze. If an interpolation artifact appears, add a keyframe, change only that shot's backend/profile, or switch it to `blend`; do not lower QA thresholds to preserve a first render.

## Preserve reproducibility

Return the MP4 together with `timeline.json` and the keyframes. Keep prompt and continuity fields in the manifest even though the renderer ignores them. State the actual interpolation backend/profile, de-duplicated cut boundaries, any fallback, rounded timing, missing audio, or intentional limitation in the handoff.
