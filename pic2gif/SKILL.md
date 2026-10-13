---
name: pic2gif
description: Create and review animated GIFs from ordered still images, with explicit frame timing, motion or still intent, optional property measurements and fixed-region checks, and hash-bound acceptance before final publication. Use for 静帧生成GIF、图片序列动画、逐帧动图 and storyboard-to-GIF requests.
---

# pic2gif

Each still is one displayed frame with an explicit exposure. Use image generation or supplied images, then GIF encoding; do not introduce RIFE, optical flow, LTX or synthetic in-between frames. GIF encoding cannot make an incoherent sequence natural.

Default to an infinitely looping GIF with a visually continuous closing interval. Design that full cycle before generating keyframes. Setting the GIF repeat flag alone does not satisfy this requirement. Use one-shot playback only when the user explicitly requests it.

The older MP4 renderer remains available only for an explicit legacy request; see [legacy-video-workflow.md](references/legacy-video-workflow.md). Its schema and commands are separate.

## 1. Plan the change before generating assets

Resolve `scripts/still_gif.py`, Python 3.10+ and an existing FFmpeg installation. Initialize with `python <script> init <project> --frames N`. Inspect reported `existing_paths` before reuse; the initializer does not overwrite them. Read [gif-schema.md](references/gif-schema.md) for timing and encoding, and [review-workflow.md](references/review-workflow.md) for plan/check/review fields.

Choose duration, aspect ratio, intended playback and a representative pilot from the request. A 512-pixel longest edge and 100ms exposures are useful starting points, not movement requirements. Frame count follows the necessary changes, contacts, reversals and events; do not fit every action into 8 or 12 poses. The default pilot must cover one complete cycle, including the return path, before expanding the workload. If a file-size requirement exists, record `plan.max_bytes` before encoding.

Declare `plan.intent` as `motion` or `still`, and `source_mode` as `generated` or `provided`. Record a concise summary, each displayed `state`, exposure and generation prompt (prompts are optional for provided images). Keep the original plan and describe later revisions; retrospective analysis of provided assets must not be presented as a plan made before generation.

Identify what changes, what stays fixed, and relative to what. Where a property can be measured meaningfully, declare optional `measurements` with property, reference space, units, per-frame expectations, tolerance and appropriate speed/acceleration bounds. Select constraints from intended behavior, not subject keywords. Units and measurements must agree; this tool does not infer physical coordinates. Some properties are discrete or cyclic; do not impose continuous speed bounds on a discrete event, or treat wrapped angles as ordinary linear coordinates without unwrapping them.

For truly fixed screen regions, optionally declare normalized `fixed_regions` and an acceptable RGB MAE from frame 0. Do not include intended lighting changes, moving texture, effects or camera motion in an invariant region. Choose tolerance before inspecting the candidate; do not widen it merely to turn a failure green. Record legitimate plan changes and create a new review.

For characters, coordinate relevant secondary features with the action, permitting intentional stillness or lag. Other scenes use relevant properties such as position, shape, illumination, scale or event boundaries. A scene without characters needs no anatomy checklist.

Set `loop: true` explicitly. In `plan.summary`, describe the cycle phases, return mechanism and closing interval; write the corresponding states, exposures and prompts before generating the anchor. Budget actual frames for the return, not only the outward action. The final frame is the state just before the next cycle's first frame; first and last images need not be identical. Usually omit a duplicated starting pose at the end unless a pause is intended.

Match position, shape, scale, camera, background and lighting across the closing interval, together with relevant direction, speed and secondary-motion phase. Equal endpoint poses alone can still produce a jerk or pause. For a one-way event, plan a coherent reset or recurring composition consistent with the request. Do not automatically reverse irreversible events or append a hard reset. If no plausible cycle preserves the requested event, explain the conflict and ask about an alternative before generation; do not silently switch to one-shot playback. `loop: false` remains available for an explicit user exception.

Run `plan-check <project>/gif.json --allow-missing` before generation. This checks structure and declared numerical consistency; it cannot prove when planning occurred or whether a prompt is visually meaningful.

## 2. Generate, save and check a representative sequence

Use provided artwork when requested; otherwise use the available image-generation capability and its applicable skill. Every displayed pose must exist as a source image. Do not draw replacement artwork in Python.

Establish and inspect an anchor. Use the preceding accepted state for progression and the anchor for identity where reference inputs are supported. Match framing and scale. For localized movement, request edits limited to the changing region rather than unnecessarily redesigning the entire scene. References are guidance, not a guarantee that fixed regions remain unchanged.

Generate the planned return states as part of the same sequence. When producing closing frames, reference the first accepted state as the upcoming target as well as the preceding state where supported. Inspect both wrap windows (penultimate, last, first) and (last, first, second) before considering the pilot complete. If the gap is too large, generate the missing return poses or revise the cycle; repeating the GIF, duplicating the first frame or adding a long hold cannot repair it.

Save each returned image to its planned project path before the next call, inspect it, and record the actual prompt, reference roles, attempt and disposition. If saving/tool-result parsing fails, first recover the already generated asset; do not generate a new image just to obtain another save path. Keep rejected candidates separately. Distinguish generation failures, quality revisions and asset-save retries in the cost record.

Compare each new image with its expected state and a three-state window: position, scale, timing, event order and relevant coupled properties. Check the wrap window for loops. When movement is measurable, compare actual positions and displacement per exposure to the plan. A prompt saying “same height” is not a measurement. Identify fixed-region drift separately from desired changes. Do not use a single global image-difference score as a naturalness verdict.

If a state or interval fails, fix that earliest failure: regenerate the source, add a necessary actual pose, simplify within the requested intent, or revise timing with a recorded reason. Do not merely increase nominal frame rate, repeat pictures, change thresholds, or replace observations with expectations. Use bounded targeted revisions; if a pilot still fails, retain a diagnostic preview and explain the specific limitation instead of expanding it.

## 3. Render a preview and create a review package

```text
python <script> validate <project>/gif.json
python <script> render <project>/gif.json --output <project>/preview.gif
python <script> inspect <project>/gif.json --output <project>/preview.gif --review-dir <project>/review-001
```

`render` remains usable with older manifests for diagnostic previews. `inspect` requires a complete plan and creates a new directory with the actual GIF, decoded frame snapshots, an original-speed/three-frame/loop-join review page, diagnostics and `review.json`. Reuse of an existing review directory is refused. Inspect after a changed plan, source or output into a new review directory; previous acceptance does not transfer.

Open `review-001/index.html` in a browser. If file navigation is unsupported, serve just this review directory with `python -m http.server 8779 --bind 127.0.0.1 --directory <review-dir>` (choose a free port) and open its loopback URL. A queued panel or a screenshot of one frame does not establish animation playback. The page offers original GIF replay and a frame-by-frame three-state window; for one-shot sequences, navigation stops at endpoints and never reverses playback. Keep the local server scoped to this review directory.

Observe intended-speed playback, important events, unwanted pauses, palette artifacts and, for loops, at least two cycles and the closing step. Inspect the frame windows to locate faults, not to substitute for playback. The automated report checks fixed-region RGB differences and identical decoded frames, not aesthetic or physical correctness.

Record `loop_join` evidence for both wrap windows and at least two uninterrupted original-speed cycles, including direction/speed continuity and any visible reset, flicker or pause. A visible unintended seam requires `revise`; unavailable playback evidence remains `pending`. A loop flag or matching endpoint image is not evidence of seamless playback. After changing a sequence or its loop mode, render and inspect again rather than reusing an earlier acceptance.

## 4. Record evidence and publish only accepted output

Fill the required entries in `review.json.checks` with `pending`, `pass` or `revise` and concrete notes. List unresolved problems in `issues`. Fill declared measurement `observations` with actual values and their measurement method; empty values start as null. Do not copy expected values into observations. Measurement coordinates refer to the declared space and units; review thumbnails may be scaled and must be converted when measuring output pixels.

```text
python <script> review-status <project>/review-001
python <script> publish <project>/review-001 --output <project>/delivery/final.gif
```

`review-status` returns nonzero for pending, revise or stale results. Missing playback/measurement evidence remains pending; failed checks require revision; material changes invalidate hashes. `publish` only accepts a passing record and atomically copies the reviewed GIF bytes to a separate delivery path after decoding checks. It cannot independently verify the truth of a reviewer note. Never mark pass merely to get past this gate. If visual review is unavailable, deliver `preview.gif` explicitly as unaccepted diagnostic output.

The renderer fits without cropping, pads/flattens transparency to white, and uses a shared palette. GIF supports at most 256 colors and no audio. Optional `encoding.colors`/`dither` support measured size/quality tradeoffs; do not claim transparency is preserved. Technical checks cover dimensions, per-frame delays, frame count, loop mode and decoding. Source/manifest paths and concurrent outputs are protected.

Deliver the accepted GIF or clearly labeled preview with its manifest, source images and review evidence. State frame count, dimensions, duration, loop mode, byte size and remaining limitations. Technical correctness and recorded visual acceptance are separate claims.
