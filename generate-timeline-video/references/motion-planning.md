# Plan continuous motion before generating pictures

Use this for any continuous action or transformation, regardless of subject. Decide what should move, change shape, appear or disappear, and what should remain stable. Character anatomy, object travel and fluid effects need different states, but all require a coherent progression through time.

## Phases and timing

Describe onset, development, peak and recovery/dissipation where relevant. Track direction, approximate displacement/extent and whether speed is increasing, steady or decreasing. Store this in existing `prompt` and `motion_plan.changes` state descriptions; no new renderer fields are required. Use the actual fps to ensure short events get distinct frames. The planner fills temporal slots but does not choose realistic velocity or infer action phases.

Put closer keyframes at rapid changes, reversals, contacts and newly visible structure, with wider spacing only where the motion supports it. Uniform 0.25-second spacing is not a universal production recipe. Increasing output fps alone does not repair missing states or incompatible shapes. Compare neighboring states over their time interval, not merely their visual similarity.

A hold or cut must have a scene-level reason recorded before rendering. An explosion can have a sudden flash without cutting from a frozen rocket to a disconnected fireball. Preserve a continuous action when requested or implied; use extra states around the transition, or report the pipeline's limitation if it cannot represent the transition convincingly.

## Rapid deformation and effects

For fire, smoke, water, breaking objects and other evolving shapes, track the same major structures between references: cloud lobes, flame regions, fragment identities and trajectories. Plan how structures form, become occluded or leave the frame. Do not ask every image to invent a completely new texture or cloud silhouette. Lock camera and background where appropriate, while permitting the intended lighting and geometry change.

For a rocket explosion, an illustrative progression is: initial rupture/flash, outward expansion, separating fragments, cooling flame and rising smoke. The time spent in each phase should fit the desired real-time or slow-motion presentation; this is not a fixed timing template. Give fragment paths and changes in cloud extent consistent directions. A large size jump or a suddenly replaced cloud at a keyframe boundary is a source problem even when each image looks good alone.

Before generating the entire sequence, make a short test of the most difficult adjacent states with the chosen backend. Inspect in-between frames and normal-speed playback when available. RIFE/optical flow estimate between pictures; they do not simulate combustion, fluids, fragmentation or physical acceleration. If the test morphs, stalls or tears, improve the source correspondence or timing and retest that interval. If it remains unsuitable, deliver only an explicitly limited preview or explain the capability gap. Do not switch to another production system without authorization.

## Feedback and acceptance

When the user reports stutter, first inspect the existing plan, render report and review record. Check for holds/cuts, discontinuities in source displacement, speed changes at joins and incomplete playback review. Temporal-luma spikes can come from an intentional flash; they identify inspection locations, not a motion-quality verdict. Do not respond automatically by increasing fps or regenerating the whole clip.

Record confirmed defects separately from hypotheses. Fix the plan, source pair or backend responsible, preserve approved content, and compare the same interval before and after. A technically valid MP4 with unreviewed playback is a review preview. A recorded playback failure remains `revise` until checked again after repair.
