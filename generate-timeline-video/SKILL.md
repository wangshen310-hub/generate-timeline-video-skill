---
name: generate-timeline-video
description: Create short videos from a written timeline by planning shots, generating continuity-aware AI keyframes, interpolating each image pair into exact-frame-rate motion, assembling transitions, and muxing optional audio into an MP4. Use when Codex is asked to generate a video, animate still images, turn a script or storyboard into video, create an animatic, synthesize in-between frames, or build a timeline-based MP4; also trigger for Chinese requests involving 视频、分镜、关键帧、插帧、补帧, or 图片生成视频.
---

# Generate Timeline Video

Turn a narrative timeline into a reproducible video project. Use image generation for visual content and the bundled FFmpeg pipeline for deterministic frame interpolation, transitions, encoding, and verification.

## Set expectations

- Treat generated images as keyframes, not as 24 independently generated frames per second. Independent generations flicker and lose identity.
- Describe `blend` as pixel blending and `optical-flow` as motion estimation. Never claim either method reconstructs physically correct hidden motion.
- Preserve the requested temporal continuity. Add intermediate states for a continuous event; split shots when the narrative or viewpoint calls for a cut, not merely because interpolation is difficult.
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

For continuous action, read [references/motion-planning.md](references/motion-planning.md) before choosing shots or timing. Record action phases, trajectories and reasons for any hold/cut in `prompt` or the project plan. An opening still is not a default requirement. Do not label a pause or cut "intentional" after rendering merely to dismiss a continuity defect; it must serve the requested scene. Plan timing from changes in the action rather than distributing visual states evenly by convenience.

```bash
"$PYTHON" "$SCRIPT" plan-keyframes <project-dir>/timeline.json --write
```

This writes explicit `at` times and deterministic placeholder paths. Generate those images next; the renderer is downstream of this motion plan.

For character or animal action, read [references/character-motion.md](references/character-motion.md) before generating keyframes. Plan visible whole-body action together with relevant expression and secondary motion: eyes/gaze, head, ears, tail, and clothing when present. After planning time slots, run `plan-motion timeline.json --write` to create structured `motion_plan` records. Fill each record's target/state changes, invariants and reference image; mark visual review as pending/pass/revise. These records work for any subject. `plan-keyframes` creates time slots, not action decisions. Keep identity and scene invariants in `continuity`, and changing expression or appendage states in the per-keyframe instructions. Choose purposeful changes and intentional stillness for this shot rather than moving every feature constantly.

Planning checks the frame budget before writing. Increase duration/fps or relax the gap if the requested semantic poses cannot fit. Repeated planning preserves full time precision and is idempotent; generated paths avoid existing assets and referenced names.

### 3. Generate continuity-aware keyframes

Use the available image-generation capability rather than drawing frames in Python.

1. Generate the first appearance of each recurring character, object, and location as an anchor.
2. Derive later keyframes by editing the preceding image or reusing the anchor whenever the tool supports image references. Avoid independent regeneration.
3. Repeat the same continuity block verbatim: identity, wardrobe, palette, lens, time of day, and aspect ratio.
4. Ask for clean full-frame imagery without captions, watermarks, borders, or UI unless those are intentional.
5. Inspect every image. Regenerate identity drift, accidental text, malformed anatomy, or discontinuous geometry before rendering.
6. Save files at the exact paths recorded in `timeline.json`.

Check each keyframe against its timed motion plan, including visible eyes, ears, tail, head, limb contacts, and silhouette as applicable. A new paw pose alone is insufficient when the requested performance also needs expression or secondary motion. Keep those features in frame, and regenerate missing or inconsistent changes before interpolation. Add timed images at short events such as eye closure/reopening or an ear/tail reversal when the existing slots would miss them; the 0.25-second default is a maximum gap, not a guarantee of adequate event sampling.

For every project, read [references/visual-continuity.md](references/visual-continuity.md) and compare every adjacent image pair before rendering, not just each image in isolation. Check subject/object shape, scale, framing, materials, attachments, shadows, background and lighting; distinguish planned changes from generation drift. Select the checks relevant to the content: products, landscapes, abstract imagery and text graphics do not need character expression or anatomy checks. For character action, also verify that the same limb follows its planned trajectory through preparation, extension and recovery.

Keep adjacent optical-flow keyframes close in composition. For articulated motion, put distinct pose images at explicit `at` times in `intermediate_images`; RIFE cannot invent a footstep when supplied poses keep the same leg configuration. Default to at most 0.25 seconds between semantic poses for articulated action and up to 1 second for slow subject motion. Rapidly deforming effects require an explicit, event-based `max_keyframe_gap` and closer samples around onset, peak or disappearance; being non-character content does not make them static. The current schema has no separate effects class: when `subject_motion: "none"` is used for effects, supply the explicit gap and motion plan. A gap check passing only checks spacing. If validation reports a motion-gap warning, rerun `plan-keyframes --write` and generate every missing state before rendering.

### 4. Choose interpolation deliberately

- Use `hold` for one image, freeze frames, or a still with optional camera motion.
  Only the start image is read, including when `--interpolation hold` overrides a shot; unused intermediate/end images and their timing are ignored.
- Use `blend` for lighting changes, abstract imagery, flat graphics, and the most reliable fallback.
- Use `optical-flow` for modest spatial displacement with stable, textured subjects and backgrounds. Prefer `blend` or `hold` plus camera motion for crisp geometric graphics that would visibly ghost.
- Use separate shots for intended cuts or unrelated compositions. Within a continuous event, first plan intermediate states for large changes, entry, occlusion or disappearance. Fire, smoke and breaking objects need a short feasibility test on the hardest interval before generating the whole sequence; see [motion-planning.md](references/motion-planning.md). Do not substitute an unrequested freeze/cut for unsupported motion or keep adding frames without checking whether correspondence improves.

- Keep the `balanced` optical-flow profile as the default. Treat `large-motion` as experimental and compare its output visually because wider search can create tearing or duplicated anatomy.
- Use optional `rife` for larger or articulated motion only when the user has an available RIFE ncnn Vulkan executable and v4 model. Prefer its `recursive` midpoint strategy for stable endpoints; use `direct` only when faster rendering is worth extra endpoint QA. It falls back to optical flow and then blend unless `--strict` is set.
Camera motion presets are `static`, `zoom-in`, `zoom-out`, `pan-left`, `pan-right`, `pan-up`, and `pan-down`. The pan name describes the camera viewport, so foreground content appears to travel in the opposite direction. These are compositional moves, not 3D scene reconstruction.
For multiple keyframes, interpolation segments are joined before camera motion is applied across the whole shot.

### 5. Validate before rendering

```bash
"$PYTHON" "$SCRIPT" validate <project-dir>/timeline.json
```

Resolve every reported error. Treat frame-rounding notices as intentional only after checking timing. The renderer rounds durations to whole frames and places explicit intermediate times at `round(at * fps)` (half up). Events colliding on a frame are rejected. A closed shot's end image occupies its last displayed frame; the timing report distinguishes this endpoint adjustment from intermediate event timing.
Treat a warning that adjacent optical-flow/RIFE keyframes are byte-identical as an input defect: add a distinct pose or choose `hold`; interpolation cannot create the missing motion. Use `dense-running-test/` as the repository's dense motion reference.

### 6. Render and verify

```bash
"$PYTHON" "$SCRIPT" render <project-dir>/timeline.json --output <project-dir>/output/final.mp4 --cache-dir <project-dir>/.timeline-cache --command-timeout 300
"$PYTHON" "$SCRIPT" probe <project-dir>/output/final.mp4 --manifest <project-dir>/timeline.json
"$PYTHON" "$SCRIPT" inspect <project-dir>/output/final.mp4 --manifest <project-dir>/timeline.json --output-dir <project-dir>/review-001
```

When the project has a fixed demo or prior render, run `benchmark <candidate> --baseline <baseline>`. Treat its temporal-luma and near-duplicate metrics as regression signals, not a replacement for visual inspection; a candidate may have more semantic motion while also having a larger luma jerk.

The renderer reports the actual backend, RIFE strategy, and optical-flow profile. Failed RIFE falls back to optical flow, then failed optical flow falls back to `blend`. Pass `--strict` when any fallback is unacceptable. A candidate is probed before atomically replacing the output, and source media paths are protected even with `--force`.

Use an `.mp4` output path. Publication follows geometry, frame count/rate, video/container duration, audio and full-decode checks. Without `--force`, publication refuses an output created by another process during rendering. JSON results are on stdout and progress/command logs are on stderr. Image normalization is cached only within a render; pure cuts use stream-copy while transitions require encoding.

Open the generated review page for adjacent source-image pairs, timestamped rendered samples, suspicious temporal changes and normal/slow playback. Apply [references/visual-continuity.md](references/visual-continuity.md) to every subject, and the character-specific checks only when applicable. Record each outcome as `not_reviewed`, `pass` or `revise` in `review.json`; "reviewed" alone is not an acceptance decision. Run `review-status <project-dir>/review-001 --write` before describing the result as ready. Unresolved issues require revision. If playback cannot be inspected, keep it `not_reviewed` and deliver a clearly labeled review preview, not a completed smooth-animation claim. This is a record of performed checks, not an automatic visual judge.

The optional cache retains verified pair clips across runs, keyed by source bytes, timing, geometry, effective interpolation settings, renderer/tool/model contents and GPU selection. Source edits or settings changes invalidate affected pairs; camera motion is reapplied over the whole shot. Failed or degraded fallback clips are not cached. Rerun the same command after interruption to reuse completed pairs. The cache is disposable and can grow; put it in a task-owned directory outside source assets. Each external render command has a configurable timeout; no automatic infinite retry is performed.

## Preserve reproducibility

Return the MP4 together with `timeline.json` and the keyframes. Keep prompt and continuity fields in the manifest even though the renderer ignores them. State the actual interpolation backend/profile, de-duplicated cut boundaries, any fallback, reported keyframe timing adjustments, cache reuse, missing audio, or intentional limitation in the handoff.
