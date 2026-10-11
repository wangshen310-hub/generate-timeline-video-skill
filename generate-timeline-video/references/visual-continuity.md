# Image and video continuity

Use these checks for all video subjects, including projects without characters. Select visible properties relevant to the intended shot; no requirement to animate eyes, ears, tails or any feature absent from the content.

## Before interpolation: adjacent images

Compare every adjacent pair side by side or in an aligned overlay. Track stable landmarks and distinguish intended changes from accidental generation drift:

- Geometry: object identity, shape, proportions, position, scale, attachments, occlusion and contact points.
- Appearance: materials, texture, colors, markings, lettering and edge clarity.
- Scene: framing, camera viewpoint, perspective, lighting, shadows, reflections and background layout.
- Action: a consistent moving part and plausible trajectory through the declared times. Add a bridge image, adjust timing or regenerate inconsistent geometry when needed.

Content-specific examples:

| Content | What to follow |
| --- | --- |
| Product/object | Silhouette, labels, surface finish, supports, reflections and turntable rotation |
| Landscape/environment | Horizon, buildings, terrain, camera path, illumination and the intended evolution of water/clouds |
| Typography/graphics | Exact text, glyph shape, alignment, edge sharpness and planned element transitions |
| Abstract/light changes | Intended color/shape evolution and whether a blend is deliberate rather than ghosting |
| Character/animal | Identity, body attachments, foot contacts, expression and relevant secondary motion; see [character-motion.md](character-motion.md) |

Do not demand unchanged lighting or geometry when their transformation is the purpose of the shot. The timeline and generation plan establish the intended change. Split unrelated compositions into shots rather than asking interpolation to reconcile them.

## After rendering: motion and joins

Inspect several in-between frames from each pair and frames immediately before/after keyframe joins and shot transitions. Review the entire clip at normal speed when a player is available; replay suspect intervals slowly. Check trajectories, rhythm, accidental freezes, sudden speed/direction or scale changes, flicker, ghost edges, unstable text and background wobble. For camera motion, follow the horizon and object paths to detect movement restarting at a keyframe join.

Intentional holds, anticipation, cuts and abrupt graphic transitions are valid when they serve the requested scene and its recorded plan. Do not retroactively call a freeze/cut intentional to excuse broken continuous action. Check the last-to-first boundary only when a repeating loop is requested; matching endpoint images alone does not prove seamless playback.

Record suspect frame/time locations and their source pairs. Fix incompatible source images, missing motion states or timing first; compare interpolation backends when correspondence causes artifacts. Re-render and inspect the affected interval and its neighbors. Technical probe/decode and temporal metrics complement visual review. If only frame samples were inspected, disclose that normal-speed playback was not verified and avoid claiming natural or smooth motion solely from those samples.

## Executable review workflow

Run `inspect final.mp4 --manifest timeline.json --output-dir review-001` using the renderer. Choose a fresh directory for each run. It checks the manifest against the video, fully decodes it, generates source-pair images, multiple samples per interpolation interval, join neighbors and high temporal-change samples, and creates `index.html` with normal/slow playback. It also creates `report.json` and `review.json` with visual checks explicitly marked `not_reviewed`.

If rendering used an `--interpolation` override, pass the same override to `inspect`. In particular, `--interpolation hold` ignores unused intermediate/end images during both rendering and inspection.

Inspect the page, then record source-pair, intermediate-frame and normal-speed outcomes separately in `review.json`, including issue frame/time, source pair and remedy. Static samples and metrics never automatically promote visual status to passed. Generated PNG samples are full-frame; use additional detail crops for suspected local defects. Re-run inspection into a new directory after repairing the affected source or render. The HTML page is a local review aid, not a claim that playback has been observed.

## Delivery status

For the three review fields use only `not_reviewed`, `pass` or `revise`. The value `reviewed` describes activity but does not establish acceptance. Each issue should include its frame/time, description, remedy and `resolved: false`; mark it true only after checking the repair. Keep playback `not_reviewed` if a player could not be observed. Do not infer it from successful decoding, a page opening, frame samples or smooth-looking source images.

Run `review-status review-001 --write`. It checks the recorded outcomes, unresolved issues and the SHA256 of the inspection's `preview.mp4`, and updates `report.json`. Exit 0 means `ready_for_delivery`; exit 2 means `needs_review` or `needs_revision`. A replaced video or older report without a hash needs fresh inspection. This checks records and file identity, not the truth of a subjective judgment.

Deliver unreviewed playback as a **review preview** with the missing check stated, even when the MP4 is technically valid. Known unresolved motion defects require revision rather than a completed-animation claim. An explicitly requested draft or still animatic can still be delivered under that requested scope; do not claim smooth continuous animation for it.
