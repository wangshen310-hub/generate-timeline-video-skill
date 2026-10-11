# Character and animal motion

Read this when generating expressive or articulated character action. Plan the performance before generating images: interpolation connects supplied states and cannot reliably choreograph a blink, ear rebound, or tail swing absent from those states.

## Plan coupled action

For each timed keyframe, describe the primary action and the relevant visible details together:

- Body, head and limbs: weight shift, foot contact/lift, takeoff, landing and recovery. Preserve limb count and plausible attachments.
- Eyes and gaze: open/closing/closed/reopening, gaze direction, or a deliberate wink. Keep eye shape and color consistent while allowing expression to change.
- Ears and tail, when present: orientation, bend and recovery, tied to body acceleration or expression. Keep length, attachment and side consistent; avoid unexplained jumps through the body.
- Clothing or fur, when relevant: restrained follow-through such as a bandana lifting during a hop and settling after landing.

Choose only details that serve the requested action and can be seen. Intentional stillness is valid. Do not add perpetual blinking or tail movement to every subject. Ensure framing exposes the planned features, and keep the camera/background stable while establishing motion.

Use the structured `motion_plan` for timed target/state changes and review status, with `prompt` or a prompt record for full generation wording. The renderer ignores this prose. Keep the unchanged identity, wardrobe, palette, lighting and camera in `continuity`; do not freeze eye openness, ear angle or tail position in that invariant block. Derive pose edits from an inspected anchor/reference so expression changes do not become identity changes.

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

### Rendered character checks

Use the shared [visual-continuity.md](visual-continuity.md) workflow and `inspect` output for source pairs, intermediate frames, event boundaries and playback. For characters, additionally check eye closure/reopening, stable ear/tail attachments, consistent punching/stepping side, planted foot contacts and follow-through. If only limbs change while requested details stay frozen, fix source poses. Record visible defects separately from technical probe/decode results; samples alone do not prove natural motion.
