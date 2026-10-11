# Character and animal motion

Read this when generating expressive or articulated character action. Plan the performance before generating images: interpolation connects supplied states and cannot reliably choreograph a blink, ear rebound, or tail swing absent from those states.

## Plan coupled action

For each timed keyframe, describe the primary action and the relevant visible details together:

- Body, head and limbs: weight shift, foot contact/lift, takeoff, landing and recovery. Preserve limb count and plausible attachments.
- Eyes and gaze: open/closing/closed/reopening, gaze direction, or a deliberate wink. Keep eye shape and color consistent while allowing expression to change.
- Ears and tail, when present: orientation, bend and recovery, tied to body acceleration or expression. Keep length, attachment and side consistent; avoid unexplained jumps through the body.
- Clothing or fur, when relevant: restrained follow-through such as a bandana lifting during a hop and settling after landing.

Choose only details that serve the requested action and can be seen. Intentional stillness is valid. Do not add perpetual blinking or tail movement to every subject. Ensure framing exposes the planned features, and keep the camera/background stable while establishing motion.

Use `prompt` for the shot's action plan and a project prompt record for individual keyframe instructions. The renderer ignores this prose. Keep the unchanged identity, wardrobe, palette, lighting and camera in `continuity`; do not freeze eye openness, ear angle or tail position in that invariant block. Derive pose edits from an inspected anchor/reference so expression changes do not become identity changes.

## Example: a stylized two-second puppy dance

This example illustrates coordinated states, not a mandatory dance or timing template. In the puppy trial, eight distinct generated images provided nine timed positions, with the anchor reused at the endpoint.

| Time (s) | Body and feet | Eyes/head | Ears/tail and follow-through |
| --- | --- | --- | --- |
| 0.00 | Ready, feet planted | Eyes open, head centered | Ears upright, tail visible |
| 0.25 | Begin a dip | Eyes half closed | Ears lower outward, tail lifts |
| 0.50 | Lowest dip | Both eyes closed in a happy blink, head tilts | Ears flop outward, tail lowers |
| 0.75 | Step left, lift one hind paw | Reopen eyes | Ears recover, tail follows sway |
| 1.00 | Hop, both feet off ground | Eyes wide, head centered | Ears perk, tail lifts, bandana flutters |
| 1.25 | Land and sway right | Look slightly right | Ears lag left, tail swings sideways |
| 1.50 | Step right, lift opposite hind paw | One-eye wink | Ear tips bend, tail lifts |
| 1.75 | Recover toward ready | Eyes open | Ears and tail settle |
| 2.00 | Return to anchor pose | Same expression as start | Same endpoint geometry |

At 24 fps, two seconds contains 48 output frames. Nine keyframe positions do not mean nine independent images per output frame; the backend fills intervals. A short blink or fast reversal may need additional images closer together, especially a closed state and a reopening state. Check that those event times fit the available integer frames; increase duration/fps or simplify the plan if they do not. Returning to the anchor helps endpoint continuity, but does not by itself prove a seamless repeating loop.

An individual edit instruction should couple changes explicitly, for example:

> From the same puppy anchor, show the lowest dance dip with both hind feet planted, head tilted slightly left and both eyes fully closed in a happy blink. Bend both ears outward with unchanged attachments and lower the visible tail. Preserve the same character, red bandana, peach studio, lighting and framing.

## Lessons from the rendered trial

- Paw-focused poses produced an incomplete performance: ears, eyes and other details need their own planned states. More interpolated frames alone cannot supply missing choreography.
- FFmpeg optical flow showed ghosting and tearing around paws and ears in this trial, including with denser inputs. Density helps motion coverage but does not guarantee correct pixel correspondence. Compare backend results on the same approved poses.
- RIFE v4.6 recursive interpolation gave a cleaner result with coordinated poses. The verified trial was 1280x720, 24 fps, 48 frames, two seconds, without audio, rendered with `--strict` and no fallback. Minor paw softening/deformation remained; this is not physical simulation or a guarantee for other actions.
- Before declaring RIFE unavailable, check configured paths and known task-local tool directories and test the executable/model with a small inference. A failed PATH lookup alone does not establish absence. Do not download a runtime or model silently.
- Hold/cut can give a clean animatic when interpolation fails. A prior eight-pose-per-second result was encoded at 24 fps by repeating frames: disclose that distinction instead of calling it smooth interpolation.

## Acceptance checks

### Adjacent source-image continuity

Compare every neighboring pair side by side or in an aligned overlay before interpolation. Follow stable landmarks such as eyes, shoulder attachments, glove cuffs, planted paws and tail base. Confirm character scale, anatomy, markings, framing, floor/shadow and background remain consistent except for planned changes. Check the whole silhouette as well as crops; a good-looking face can conceal a displaced body or foot.

Track moving parts through the timed sequence rather than interpreting each picture independently. For boxing, the same arm must stay responsible for its punch from preparation to extension and recovery, while the other guards; a left/right swap creates an impossible trajectory. Check event order and reasonable displacement over each time interval. Regenerate identity/geometry drift, adjust timing for a plausible path, or add a bridge pose when a large change lacks an intermediate state. Do not expect a stronger interpolation model to repair incompatible source poses.

### Rendered temporal continuity

Inspect multiple in-between frames in each image pair, including frames immediately before and after keyframe joins. Review the full clip at normal speed when a player is available; replay suspect intervals slowly to locate defects. Normal-speed playback reveals rhythm and stutters that isolated stills can miss, while slow review exposes disappearing arms, glove fusion, doubled ears or tail jumps. If only frame samples were inspected, record that evidence level explicitly.

Check both motion and scene stability: continuous trajectories, appropriate anticipation/recovery, no accidental boundary freeze or speed jump, no unexplained scale change, flickering stripes, shifting background or sliding foot contacts. Follow-through should agree with the primary movement without requiring every feature to move constantly. At a shot transition, verify the intended cut/overlap and chronology rather than demanding continuous motion across an intentional cut. Do not claim a seamless loop without checking the last-to-first playback boundary.

Record suspect frame/time locations, their source pair and the remedy. Re-render and recheck the repaired interval together with neighboring intervals. Temporal-luma and duplicate-frame metrics can flag locations for inspection; they do not certify natural choreography or smooth playback.

Before rendering, compare images to the timed plan. Verify actual eye closure/reopening, intended ear/tail states, stable attachments, visible framing, and body/foot contacts where required. If only the limbs change while requested details stay frozen, regenerate the affected keyframes.

After rendering, inspect the full sequence and frames around each planned event, including in-between frames rather than only source poses. Use face and appendage crops alongside full-body views to catch eye smearing, doubled ears, tail discontinuities, malformed paws and landing/contact errors. Full decode, fps/frame-count checks and temporal metrics verify technical properties; they do not establish semantic motion quality. Report the actual backend, fallback status and any remaining visible defects.
