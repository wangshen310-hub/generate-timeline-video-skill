# Plan and test change through time

Apply this workflow to every shot. Select checks from what changes and how it is observed, not from subject names. A still title, moving camera, articulated subject and evolving cloud share the same decisions; their relevant properties differ. Scale the work to the risk: a deliberate still needs no invented movement or dense pose plan.

## 1. Specify the observable result

Before filling keyframe slots, record the intended event and the minimum properties needed to recognize it in `prompt` and `motion_plan`. For each property identify:

- **Identity and reference frame:** the same object/part/region throughout; observed relative to the screen, the scene, or another object.
- **Behavior:** constant, continuously changing, or a discrete event. A property cannot be both fixed and changing in the same reference frame over the same interval.
- **Time evolution:** initial state, intermediate events and end state; direction/path, approximate extent, duration, and intended acceleration, pauses or reversals. Specify event ordering and contacts/attachments when relevant.
- **Evidence:** what would show success or failure in the actual images and rendered clip. Desired-result prose is not evidence that it occurred.

Use numeric samples when an observable property can be measured reliably; otherwise retain an explicit qualitative check. Optional [`motion_checks`](motion-checks.md) validate numeric plans and compare annotated output measurements, including position, angle, extent, opacity or brightness. Do not manufacture measurements for unobservable properties or impose one speed/acceleration threshold on every shot.

Resolve contradictions before image generation. Read the assembled prompt, including its invariant block. Fixed identity does not imply fixed pose, projected size, illumination or screen position. If a camera tracks a moving object, describe corresponding background/ground motion; if the scene stays fixed while the camera moves, screen coordinates generally change. Record these relationships rather than asking for both tracking and an unchanged background. Software checks explicit numeric identities and constraints, not contradictions hidden in prose.

## 2. Choose representation and sample the event

Choose the backend from the required change and source correspondence. `hold` represents a still or a supported whole-image camera transform. `blend` represents a deliberate visual mixture. Optical flow/RIFE connect nearby images with matchable structures. None provides a persistent scene, rig, depth model or simulator. The current pairwise renderer has no velocity constraint across three or more keyframes.

For continuous change, expose motion direction, occlusion and event order. Put additional samples around reversals, contact, newly visible structure, formation or disappearance. Check displacement divided by elapsed time, then compare velocities across **three or more consecutive states**. Pairwise similarity can hide a stall followed by a jump. Intended impacts, flashes, stops and cuts need event-specific checks rather than universal smoothness limits.

Keyframe spacing and output fps are sampling constraints, not motion quality. `plan-keyframes` fills slots; it does not choose choreography or speed. Revisit times after inspecting actual generated displacement. Add a bridge when a necessary state is missing; retime when the path is sound but its pace is wrong; regenerate when geometry, identity or trajectory is inconsistent.

Keep continuous events continuous. A hold or cut needs a narrative/viewpoint reason recorded before rendering. A recurring action needs one coherent complete cycle before duplication. For a requested seamless loop, check direction and speed across the seam as well as endpoint appearance; a closed endpoint occupying the last displayed frame is not automatically a seamless loop.

## 3. Prove the difficult part before scaling up

For a new or materially changed motion setup, make the smallest **representative test** before generating/rendering the full sequence. Select its span from the failure risk: at least a three-state window for a velocity change, a full period for cyclic motion, both sides of an occlusion/contact, or formation through expansion for a changing shape. This applies beyond effects and characters. A static/simple already-verified setup may use the shot itself as the test; record that reason instead of making unnecessary media.

Generate the pilot with the same references, scale, fps and backend intended for production. Use the inspected preceding state for temporal progression and the anchor for identity; when only one reference is possible, choose deliberately and check the omitted role. Reusing the anchor for every edit is allowed only if the resulting sequence still follows the trajectory. It does not enforce that trajectory by itself.

Compare generated images against the plan, adjacent pairs, and the multi-state window. Check actual changes, not just whether each picture looks good. Render the pilot and inspect in-between frames, joins and normal-speed playback. Record source and output failures separately with time/frame, observation and remedy. Apply [visual-continuity.md](visual-continuity.md) for evidence and [character-motion.md](character-motion.md) only when applicable.

Do not expand or repeat an unapproved pilot as if it were successful. If playback cannot be observed, retain a clearly labeled pilot preview. On failure, correct the earliest responsible stage and retest the same span with neighboring frames. Changed source, timing, camera transform or backend invalidates corresponding acceptance. Stop repeated generation when correspondence is not improving; state the capability gap. Switching production systems requires authorization when outside the user's chosen workflow.

## 4. Carry evidence to the full clip

After the pilot passes, expand the sequence and repeat checks at new joins, events and transition/camera effects added during assembly. Test the full clip at normal speed; a successful pair does not prove the assembled result. `inspect` creates samples and measurement templates but never supplies visual approval. `review-status` checks judgments, unresolved issues, video identity and declared numeric checks.

Keep source images, plan/parameters and inspected video identifiable in the project. Mark user-reported playback defects as `revise`, with unresolved issues, until repaired and reviewed. A technically valid MP4 may still fail its intended behavior.

## Applying the same decisions

These are examples of properties, not subject-triggered code paths or fixed recipes.

| Requested change | Stable relationship | Planned change / representative test |
| --- | --- | --- |
| Articulated action | Part identity and attachment | Contact and trajectory through a full action/cycle; relevant secondary motion |
| Product rotation | Shape and label content | Angle and newly exposed surface through an occlusion; inspect legibility |
| Moving viewpoint | Scene layout in scene coordinates | Screen trajectories, scale and parallax across a camera-path join |
| Fire, fluid or breakup | Major region/fragment identities while they exist | Formation, expansion and disappearance; test topology change |
| Typography or graphics | Exact content and intended geometry | Translation, opacity or discrete replacement; readability at event times |
| Light, abstract change or still | Only properties declared constant | Color/brightness/shape trajectory, or stillness without manufactured motion |

## Diagnose by stage

On stutter feedback, inspect plan, prompts, assets, render report and acceptance record first. Separate confirmed defects from hypotheses. Contradiction or wrong trajectory belongs to planning/source generation; uneven displacement over time calls for retiming; artifacts between compatible states call for backend comparison; new defects after composition belong to assembly. Inspect timestamps/duplicates for encoding faults. Temporal-luma spikes locate candidates but cannot decide whether a flash or motion is wrong. Keep the comparison interval fixed while testing a hypothesis; do not automatically increase fps, add images, or regenerate the whole project.
