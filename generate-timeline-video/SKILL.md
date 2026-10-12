---
name: generate-timeline-video
description: Create animated GIFs from an ordered sequence of still images, using image generation or supplied pictures, explicit per-frame timing, palette encoding, loop planning, and output verification. Use for 静帧生成GIF、图片序列动画、逐帧动图 and storyboard-to-GIF requests. The historical skill name is retained for compatibility.
---

# Still Images to GIF

Create a reproducible frame-by-frame GIF. Each supplied still becomes one displayed frame with an explicit duration. The default output is GIF, not MP4. Do not invoke RIFE, optical flow, LTX, pixel blending, or automatic in-between generation in this workflow. GIF encoding does not itself make sparse poses move naturally.

The directory and invocation name remain `generate-timeline-video` for existing installations. The previous MP4 workflow is retained in [legacy-video-workflow.md](references/legacy-video-workflow.md), only for an explicit request to use that older pipeline. Its interpolation planning, fps rules and review commands do not apply to GIF manifests.

## 1. Plan the actual displayed frames

Start with a short, meaningful animation or complete cycle. Use a 512-pixel longest edge, preserving the requested aspect ratio, and 100 ms per image as an initial practical setting. Adjust timing to the action, not a mandatory frame rate. A typical initial pilot has 8–16 distinct states; this is a workload suggestion, not a quality guarantee. A supplied sequence can use its existing length and dimensions. Keep all assets inside the chosen project directory.

Record what changes, what stays fixed and the reference frame (screen, scene or another object). Plan each displayed state and duration before bulk image generation. Include anticipation, contact, reversals, peaks and settling where relevant. For non-character scenes, track relevant shape, position, light, material, water, smoke or other changes. Do not insert eyes, ears or anatomy checks into scenes that lack them.

For characters or animals, coordinate the primary action with relevant gaze, head, ears, tail, limbs and contact. Secondary motion can lag the main motion; it need not change in every frame. Keep intentional stillness. Resolve contradictory constraints, such as screen-fixed scenery paired with a tracking camera.

For looping motion, plan a complete cycle and inspect last → first as another adjacent step. Normally omit a duplicate first pose at the end: its extra exposure creates a pause. Keep an endpoint hold only when intentional. Do not reverse the sequence automatically: ping-pong playback can reverse gravity, contact, smoke or other one-way processes. For a non-looping event, set `loop: false` unless the user requests a designed reset.

## 2. Create the manifest

Locate `scripts/still_gif.py` in this skill directory. Use Python 3.10+ and FFmpeg already available on PATH. The script uses only Python's standard library; no RIFE or generative video model is required. If FFmpeg is missing, resolve an existing installation before proposing installation.

```text
python <skill-dir>/scripts/still_gif.py init <project-dir> --frames 12
python <skill-dir>/scripts/still_gif.py validate <project-dir>/gif.json --allow-missing
```

Read [gif-schema.md](references/gif-schema.md) for explicit timing, loop settings and commands. Fill each frame's `state` and `prompt` with the actual intended change. The initializer creates slots, not motion. Never silently reuse a video `timeline.json` as a GIF manifest.

## 3. Generate or collect still frames

Use supplied images when requested. Otherwise use the available image-generation capability, following its applicable instructions, rather than drawing replacement artwork in Python.

- Establish an inspected anchor for appearance, style, composition and any fixed background.
- Use the preceding accepted frame for progression and the anchor for identity when references are supported. Anchor-only references do not establish temporal motion.
- Generate small incremental state changes with consistent framing. Every displayed pose must exist as an actual source image; the encoder will not invent missing poses.
- Review each image and windows of at least three consecutive states. Check shape, placement, scale, palette, background stability, displacement per interval and appropriate coupled details. For a loop, include the closing window.
- Fix accidental drift, geometry errors and missing events in the source sequence. If transitions jump, add or redraw the necessary displayed states and adjust exposure times. Repeating a frame changes its hold duration, not its motion smoothness.

Render a representative complete cycle or event before expanding an expensive sequence. If generation costs are excessive, shorten or simplify the action within the user's intent rather than silently changing to a video model or interpolator.

## 4. Encode and verify

```text
python <skill-dir>/scripts/still_gif.py validate <project-dir>/gif.json
python <skill-dir>/scripts/still_gif.py render <project-dir>/gif.json --output <project-dir>/output/final.gif
python <skill-dir>/scripts/still_gif.py probe <project-dir>/gif.json --output <project-dir>/output/final.gif
```

Encoding fits images to the canvas without cropping, flattens transparency onto white, builds a shared palette and uses fixed ordered dithering. If the design requires a transparent GIF or another background treatment, prepare compatible source artwork or extend the renderer explicitly; do not claim transparency is preserved. GIF has at most 256 palette colors and no audio.

The script verifies GIF dimensions, frame count, every frame delay, total duration and loop extension, then performs full FFmpeg decoding before atomic publication. Without `--force`, existing or concurrently created output is protected. `--force` allows replacement only after verification; sources and manifest remain protected. Commands emit JSON; failures return nonzero. These are technical checks, not a visual assessment.

Open the final GIF in a viewer that plays animation, inspect at its intended speed and watch at least two loops when looping. Check discontinuities, unintended pauses, palette flicker/banding, detail loss and the closing step. Frame sheets alone cannot establish playback quality. If playback cannot be inspected, label the delivery as a technically verified preview awaiting playback review. Do not expand a failed pilot and call it accepted.

Deliver `final.gif`, `gif.json` and the source images. Report dimensions, frame count, total duration, loop behavior and any remaining visual limitation. Preserve frame prompts and timing for revision. Do not claim that high frame count or a valid file proves natural motion.
