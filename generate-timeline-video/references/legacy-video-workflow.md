> Legacy MP4 workflow: use only when explicitly requested. The primary skill now creates still-frame GIFs.

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

Locate this skill directory, then set `SCRIPT` to `scripts/timeline_video.py` inside it. Resolve the Python interpreter by preferring `python3` and falling back to `python`, then set `PYTHON` to that command. Confirm that FFmpeg and FFprobe are available. If a task-local FFmpeg `bin` directory already exists, add it only to the current process PATH; otherwise ask for a path or installation authorization. Do not install packages silently; the default renderer uses only Python's standard library and FFmpeg. RIFE is optional, uses an external executable plus model, and must not be downloaded silently. Read [references/interpolation-backends.md](interpolation-backends.md) before enabling it.

### 2. Create the project and timeline

Read [references/timeline-schema.md](timeline-schema.md) when authoring or repairing `timeline.json`.

Initialize a safe project skeleton:

```bash
"$PYTHON" "$SCRIPT" init <project-dir> --title "<title>" --shots 1 --shot-duration 3 --size 1280x720 --fps 24
```

Translate the request into contiguous shots with a visual purpose. Put generation instructions in `prompt` and actual invariant facts in `continuity`. Declare `subject_motion` from the required change (`none`, `slow` or `articulated`); it is a sampling hint, not a classification of what is visible. A camera-only move or still can use one image.

For every shot, read [references/motion-planning.md](motion-planning.md) before choosing timing or generating images. Identify relevant properties, their reference frames (screen, scene or another object), and whether each is constant, continuous or an event. Plan paths/extent, timing and coupled relationships; choose evidence that would show whether generated output meets the intent. Reconcile contradictions in the assembled prompt, including invariants. Scale this plan to the shot; a still does not need artificial motion. Where numeric measurements are meaningful, read [references/motion-checks.md](motion-checks.md) and declare optional `motion_checks` before rendering.

```bash
"$PYTHON" "$SCRIPT" plan-keyframes <project-dir>/timeline.json --write
```

This writes explicit `at` times and deterministic placeholder paths. Choose the representative pilot before generating the full list; the renderer is downstream of the temporal plan. Validate planned structure with `validate timeline.json --allow-missing` before spending on generation.

After planning slots, run `plan-motion timeline.json --write` for structured records for any subject. Fill target/state changes, reference frame, invariants and reference image; keep review pending until inspecting actual assets. `plan-keyframes` creates slots, not action decisions. Keep changing properties out of `continuity`.

For character/animal action, additionally read [references/character-motion.md](character-motion.md). Couple the primary action to relevant expression and secondary motion (eyes/gaze, head, ears, tail or clothing when present). Animate only details that serve the scene; intentional stillness is valid.

Planning checks the frame budget before writing. Increase duration/fps or relax the gap if the requested semantic poses cannot fit. Repeated planning preserves full time precision and is idempotent; generated paths avoid existing assets and referenced names.

### 3. Choose interpolation and test a representative span

- Use `hold` for one image, freeze frames, or a still with optional camera motion.
  Only the start image is read, including when `--interpolation hold` overrides a shot; unused intermediate/end images and their timing are ignored.
- Use `blend` when pixel mixing is the intended change, such as a dissolve or some lighting/abstract transitions. A moving label or rigid graphic may visibly ghost; choose by property behavior rather than the subject category.
- Use `optical-flow` for modest displacement with stable, textured correspondences. Use `hold` plus a camera preset only when that transform satisfies the requested motion; it cannot replace object deformation or independent movement.
- Use separate shots for intended cuts or unrelated compositions. Within continuous events, plan intermediate states for large changes, entry, occlusion or disappearance. Before scaling a new motion setup, test a representative span with the intended backend as described in [motion-planning.md](motion-planning.md): a multi-state window, complete cycle or critical event as appropriate. This applies to all subjects. Expand only after source continuity and rendered motion pass; static/simple verified setups can use the shot itself as the test. If playback is unavailable or correspondence remains unsuitable, retain a limited pilot preview and state the gap. Do not substitute an unrequested freeze/cut or switch production systems to hide failure.

- Keep the `balanced` optical-flow profile as the default. Treat `large-motion` as experimental and compare its output visually because wider search can create tearing or duplicated anatomy.
- Use optional `rife` for larger or articulated motion only when the user has an available RIFE ncnn Vulkan executable and v4 model. Prefer its `recursive` midpoint strategy for stable endpoints; use `direct` only when faster rendering is worth extra endpoint QA. It falls back to optical flow and then blend unless `--strict` is set.
Camera motion presets are `static`, `zoom-in`, `zoom-out`, `pan-left`, `pan-right`, `pan-up`, and `pan-down`. The pan name describes the camera viewport, so foreground content appears to travel in the opposite direction. These are compositional moves, not 3D scene reconstruction.
For multiple keyframes, interpolation segments are joined before camera motion is applied across the whole shot.

### 4. Generate and expand accepted keyframes

Use the available image-generation capability rather than drawing frames in Python. Apply these instructions first to the pilot selected in step 3, then expand only after its source and output review passes. Use a small pilot manifest referencing its selected states so ungenerated production assets do not block the test.

1. Generate the first appearance of each recurring character, object, and location as an anchor.
2. Use the inspected preceding image for temporal progression and the anchor for identity whenever supported. If choosing one reference, inspect the role it cannot enforce. Anchor reuse alone does not establish a continuous trajectory.
3. Repeat only actual invariants in the continuity block. Identity, wardrobe, palette, lens or time of day belong there only while intended to remain fixed. Keep changing lighting, viewpoint and other planned changes in timed instructions.
4. Ask for clean full-frame imagery without captions, watermarks, borders, or UI unless those are intentional.
5. Inspect every image. Regenerate identity drift, accidental text, malformed anatomy, or discontinuous geometry before rendering.
6. Save files at the exact paths recorded in `timeline.json`.

Check each keyframe against its timed motion plan, including visible eyes, ears, tail, head, limb contacts, and silhouette as applicable. A new paw pose alone is insufficient when the requested performance also needs expression or secondary motion. Keep those features in frame, and regenerate missing or inconsistent changes before interpolation. Add timed images at short events such as eye closure/reopening or an ear/tail reversal when the existing slots would miss them; the 0.25-second default is a maximum gap, not a guarantee of adequate event sampling.

For every project, read [references/visual-continuity.md](visual-continuity.md). Compare images to the plan, adjacent pairs and three-or-more-state windows: follow the same properties through time, including their displacement per interval and changes in speed. Distinguish planned changes from drift in geometry, appearance, lighting and reference frame. Select only relevant checks; products, landscapes, abstract imagery and text do not need character anatomy. A per-image `pass` does not establish temporal acceptance.

Keep adjacent optical-flow keyframes close in composition. For articulated motion, put distinct pose images at explicit `at` times in `intermediate_images`; RIFE cannot invent a footstep when supplied poses keep the same leg configuration. Default to at most 0.25 seconds between semantic poses for articulated action and up to 1 second for slow subject motion. Rapidly deforming effects require an explicit, event-based `max_keyframe_gap` and closer samples around onset, peak or disappearance; being non-character content does not make them static. The current schema has no separate effects class: when `subject_motion: "none"` is used for effects, supply the explicit gap and motion plan. A gap check passing only checks spacing. If validation reports a motion-gap warning, rerun `plan-keyframes --write` and generate every missing state before rendering.

### 5. Validate before rendering

```bash
"$PYTHON" "$SCRIPT" validate <project-dir>/timeline.json
```

Resolve every reported error. Treat frame-rounding notices as intentional only after checking timing. The renderer rounds durations to whole frames and places explicit intermediate times at `round(at * fps)` (half up). Events colliding on a frame are rejected. A closed shot's end image occupies its last displayed frame; the timing report distinguishes this endpoint adjustment from intermediate event timing.
Treat a warning that adjacent optical-flow/RIFE keyframes are byte-identical as a possible missing-motion input: check whether stillness is intended and represented correctly. `dense-running-test/` is a fixed sampling/renderer regression fixture, not a guarantee of natural motion or a production recipe.

### 6. Render and verify

```bash
"$PYTHON" "$SCRIPT" render <project-dir>/timeline.json --output <project-dir>/output/final.mp4 --cache-dir <project-dir>/.timeline-cache --command-timeout 300
"$PYTHON" "$SCRIPT" probe <project-dir>/output/final.mp4 --manifest <project-dir>/timeline.json
"$PYTHON" "$SCRIPT" inspect <project-dir>/output/final.mp4 --manifest <project-dir>/timeline.json --output-dir <project-dir>/review-001
```

When the project has a fixed demo or prior render, run `benchmark <candidate> --baseline <baseline>`. Treat its temporal-luma and near-duplicate metrics as regression signals, not a replacement for visual inspection; a candidate may have more semantic motion while also having a larger luma jerk.

The renderer reports the actual backend, RIFE strategy, and optical-flow profile. Failed RIFE falls back to optical flow, then failed optical flow falls back to `blend`. Pass `--strict` when any fallback is unacceptable. A candidate is probed before atomically replacing the output, and source media paths are protected even with `--force`.

Use an `.mp4` output path. Publication follows geometry, frame count/rate, video/container duration, audio and full-decode checks. Without `--force`, publication refuses an output created by another process during rendering. JSON results are on stdout and progress/command logs are on stderr. Image normalization is cached only within a render; pure cuts use stream-copy while transitions require encoding.

Open the review page for sources, timestamped samples, joins and normal/slow playback. Check the final assembly against the plan, including new joins/camera transforms; pilot approval does not cover later changes. Apply [references/visual-continuity.md](visual-continuity.md) to all subjects. Record `not_reviewed`, `pass` or `revise` in `review.json` with observations, locations and unresolved issues. When `motion_checks` are declared, fill `motion-observations.json` from actual output measurements; expectations are never observations. Run `review-status <project-dir>/review-001 --write`: missing measurements/playback remain pending, and observed violations require revision. User-reported playback failure stays `revise` until repaired and reviewed. If playback is unavailable, deliver only a clearly labeled preview. These checks do not automatically judge natural motion.

The optional cache retains verified pair clips across runs, keyed by source bytes, timing, geometry, effective interpolation settings, renderer/tool/model contents and GPU selection. Source edits or settings changes invalidate affected pairs; camera motion is reapplied over the whole shot. Failed or degraded fallback clips are not cached. Rerun the same command after interruption to reuse completed pairs. The cache is disposable and can grow; put it in a task-owned directory outside source assets. Each external render command has a configurable timeout; no automatic infinite retry is performed.

## Preserve reproducibility

Return the MP4 together with `timeline.json` and the keyframes. Keep prompt and continuity fields in the manifest even though the renderer ignores them. State the actual interpolation backend/profile, de-duplicated cut boundaries, any fallback, reported keyframe timing adjustments, cache reuse, missing audio, or intentional limitation in the handoff.

