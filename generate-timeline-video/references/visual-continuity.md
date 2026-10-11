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

Intentional holds, anticipation, cuts and abrupt graphic transitions are valid. Assess them against the intended timing and narrative. Check the last-to-first boundary only when a repeating loop is requested; matching endpoint images alone does not prove seamless playback.

Record suspect frame/time locations and their source pairs. Fix incompatible source images, missing motion states or timing first; compare interpolation backends when correspondence causes artifacts. Re-render and inspect the affected interval and its neighbors. Technical probe/decode and temporal metrics complement visual review. If only frame samples were inspected, disclose that normal-speed playback was not verified and avoid claiming natural or smooth motion solely from those samples.
