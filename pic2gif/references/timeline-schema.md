# Timeline manifest

Use UTF-8 JSON. Resolve all relative media paths from the directory containing `timeline.json`.

## Complete example

```json
{
  "version": 1,
  "title": "Rainy platform",
  "fps": 24,
  "width": 1280,
  "height": 720,
  "shots": [
    {
      "id": "shot-001",
      "duration": 1.5,
      "start_image": "keyframes/shot-001-start.png",
      "end_image": "keyframes/shot-001-end.png",
      "intermediate_images": [
        {"image": "keyframes/shot-001-dense-000250ms.png", "at": 0.25},
        {"image": "keyframes/shot-001-dense-000500ms.png", "at": 0.5},
        {"image": "keyframes/shot-001-dense-000750ms.png", "at": 0.75},
        {"image": "keyframes/shot-001-dense-001000ms.png", "at": 1.0},
        {"image": "keyframes/shot-001-dense-001250ms.png", "at": 1.25}
      ],
      "subject_motion": "articulated",
      "max_keyframe_gap": 0.25,
      "interpolation": "optical-flow",
      "motion": "zoom-in",
      "transition_to_next": {
        "type": "fade",
        "duration": 0.5
      },
      "prompt": "Wide cinematic view of a lone traveler waiting on a rainy train platform, blue hour, 35 mm lens",
      "continuity": "Same traveler, navy coat, red suitcase, blue-hour rain, realistic cinematic photography, 16:9"
    },
    {
      "id": "shot-002",
      "duration": 3.0,
      "start_image": "keyframes/shot-002-start.png",
      "interpolation": "hold",
      "motion": "pan-right",
      "transition_to_next": {
        "type": "cut",
        "duration": 0
      },
      "prompt": "Camera pans across the stationary train and traveler beside the red suitcase",
      "continuity": "Same traveler, navy coat, red suitcase, blue-hour rain, realistic cinematic photography, 16:9"
    }
  ],
  "audio": {
    "file": "audio/soundtrack.wav",
    "volume": 0.85,
    "loop": false,
    "fade_in": 0.25,
    "fade_out": 0.75
  }
}
```

## Top-level fields

| Field | Required | Meaning |
| --- | --- | --- |
| `version` | yes | Schema version; use `1`. |
| `title` | yes | Human-readable project title. |
| `fps` | yes | Integer output frame rate from 1 to 120; use `24` by default. |
| `width`, `height` | yes | Positive even output dimensions. |
| `shots` | yes | Non-empty ordered list of shots. |
| `audio` | no | One optional audio file to loop/pad, fade, and mux. |

## Shot fields

| Field | Required | Meaning |
| --- | --- | --- |
| `id` | yes | Unique filename-safe identifier. |
| `duration` | yes | Shot duration in seconds before transition overlap. |
| `start_image` | yes | First keyframe path. |
| `intermediate_images` | no | Either ordered path strings (legacy equal spacing) or ordered `{"image": path, "at": seconds}` objects. Do not mix forms. Prefer timed objects for subject motion. |
| `end_image` | no | Last keyframe path; omit for a hold. |
| `interpolation` | no | `hold`, `blend`, `optical-flow`, or optional `rife`; inferred from image count when omitted. |
| `optical_flow_profile` | no | `balanced` by default, or experimental `large-motion`. |
| `rife_strategy` | no | `recursive` by default for stable endpoints, or faster `direct`. |
| `motion` | no | Camera preset; defaults to `static`. |
| `subject_motion` | no | `none`, `slow`, or `articulated`. Defaults to `none`; `articulated` enforces a 0.25-second default gap. |
| `max_keyframe_gap` | no | Positive maximum seconds between semantic keyframes; overrides the motion-class default. |
| `transition_to_next` | no | Transition beginning near this shot's end. Defaults to a cut. |
| `motion_plan` | no | Structured per-keyframe action and review records; see below. |
| `motion_checks` | no | Numeric output-property expectations and optional rate limits; see [motion-checks.md](motion-checks.md). |
| `prompt` | no | Image-generation instruction retained for reproducibility. |
| `continuity` | no | Invariants copied unchanged across related keyframe prompts. |

Allowed non-cut transition types are `fade`, `dissolve`, `wipeleft`, `wiperight`, `wipeup`, `wipedown`, `slideleft`, `slideright`, `slideup`, and `slidedown`. A transition duration must be shorter than both neighboring shots.

The `rife` backend is configured at render time with `--rife-executable`
and `--rife-model`; environment-specific executable and model paths do not
belong in the portable manifest. The portable `rife_strategy` field may select
quality-first `recursive` midpoint subdivision or faster `direct`
arbitrary-timestep rendering. CLI `--rife-strategy` overrides every shot. See
[interpolation-backends.md](interpolation-backends.md).

Prefer `fade` as the neutral transition. FFmpeg's `dissolve` intentionally uses a granular dissolve pattern and can look speckled on flat-color graphics. Pan names describe movement of the camera viewport; visible scene content shifts in the opposite direction.

## Frame and duration rules

The renderer computes each shot as:

```text
shot_frames = floor(shot_duration_seconds * fps + 0.5)
transition_frames = floor(transition_duration_seconds * fps + 0.5)
output_frames = sum(shot_frames) - sum(non_cut_transition_frames)
output_duration = output_frames / fps
```

Use durations aligned to whole frames whenever possible. At 24 fps, one frame is `0.0416667` seconds. A 0.5-second transition is exactly 12 frames.
When a subject changes pose, put every materially different pose in
`intermediate_images`. Use `plan-keyframes timeline.json --write` to create
deterministic timed placeholders before generating images. For articulated
action, the default maximum gap is 0.25 seconds; slow subject motion defaults to
1 second. The renderer maps explicit intermediate `at` values to `floor(at * fps + 0.5)` frame positions without rescaling the whole timeline,
removes repeated pair boundaries, and preserves the declared total frame count.
Legacy path strings remain supported and are spaced evenly. Interpolation cannot
invent an unseen footstep from two keyframes that have the same leg pose.
For optical-flow and RIFE shots, validation also warns when adjacent keyframe files are byte-identical. Treat that warning as a missing-motion input defect, not as a renderer-quality problem. The reproducible [`seaside-running-motion-test`](../../seaside-running-motion-test/README.md) shows the expected layout.

The final frame of one image pair is normally the intended end keyframe.
Optical-flow works best when both images preserve subject count, topology,
lighting, and camera viewpoint.

For a cut whose current `end_image` and next `start_image` are byte-identical,
the renderer samples the current shot on an open interval and lets the next shot
supply the endpoint exactly once. This avoids a duplicate boundary frame while
preserving the manifest's output frame count and duration.

## Audio fields

- `file`: required path when `audio` exists.
- `volume`: linear gain from `0` to `4`; default `1`.
- `loop`: repeat short audio until the video ends; default `false`. Without looping, silence pads the tail.
- `fade_in`, `fade_out`: non-negative seconds, each shorter than the video.

The pipeline does not synthesize narration or music. Generate or obtain permitted audio separately, then reference it here.

## Keyframe prompt pattern

Build each prompt in this order:

```text
[shot action and composition]
[what changes from the preceding keyframe]
[unchanged continuity block]
[camera/lens and lighting]
[target aspect ratio; no captions, watermark, border, or UI]
```

For character action, describe coupled body, expression and secondary-motion states at each planned time. Keep changing eye openness, gaze, ear bend and tail position out of the invariant `continuity` block. Use `motion_plan` for structured per-keyframe states and a project prompt record for full generation wording. The renderer validates the records but does not interpret their prose; `plan-keyframes` schedules slots without inferring semantic actions. Read [character-motion.md](character-motion.md) for the puppy example and visual acceptance checks.

For a recurring subject, use an image edit/reference workflow and ask for only the stated change. If the requested change is too large for reliable interpolation, split it into additional shots or keyframe pairs.

## Structured motion plan

After `plan-keyframes`, run `plan-motion timeline.json --write`. It creates a record for every image/time slot and preserves matching existing records on repeated runs. Obsolete records are reported for reconciliation rather than silently deleted. Empty changes are valid for deliberate stillness, but generated records are `pending` and require content-specific planning and visual review. A hold has a single record at time zero.

Each optional shot-level `motion_plan` entry has:

```json
{
  "at": 0.5,
  "image": "keyframes/pose-02.png",
  "reference_image": "keyframes/pose-01.png",
  "changes": [{"target": "image-right glove", "state": "half extension, same shoulder attachment"}],
  "keep": ["character identity", "contact paw fixed relative to floor during support", "scene layout in scene coordinates"],
  "review": "pending"
}
```

The example is one entry, not a complete plan: a plan must match every ordered image/time slot. `changes` contains target/state strings, `keep` contains invariant strings, `reference_image` identifies the generation reference and `review` is pending/pass/revise. Validation checks structure and correspondence, not whether image pixels satisfy the prose. Pending/revise records produce a warning. Rendering still requires visual acceptance; `pass` is a recorded reviewer judgment, not an automated inference. An explicit `--interpolation hold` override ignores unused motion records as well as unused images.

These records are not a trajectory solver. Apply [motion-planning.md](motion-planning.md) to define property identities, coordinate/reference frames, event timing and multi-state continuity first. For measurable quantities, `motion_checks` is separate from the image-slot plan: it describes final output at shot-local frame indices, including in-between samples. Its schema and observation workflow are in [motion-checks.md](motion-checks.md). Output expectations remain active with interpolation overrides; revise the intent explicitly if an override changes it.

## Event timing and render reports

An intermediate event at 2.125 seconds in a 24 fps shot occupies frame 51. Events rounding to the same frame, or leaving no room for the following endpoint, fail validation instead of being silently shifted. For a closed 2.5-second shot, 60 displayed frames have timestamps 0 through 59/24; its declared end image is sampled at frame 59. Shared-cut endpoints are supplied by the next shot. `keyframe_timing` reports declared/actual time, frame index and adjustment for each point. Legacy untimed arrays retain their existing interval distribution.

`segment_cache` reports pair-level hit/miss events. Recursive RIFE uses midpoint generation followed by RIFE local-time refinement for non-grid target times, without FFmpeg temporal pixel blending. Reports distinguish the requested strategy and actual backend/fallback.
