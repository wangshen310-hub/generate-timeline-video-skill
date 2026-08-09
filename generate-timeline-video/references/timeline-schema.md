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
      "duration": 3.0,
      "start_image": "keyframes/shot-001-start.png",
      "end_image": "keyframes/shot-001-end.png",
      "intermediate_images": ["keyframes/shot-001-mid.png"],
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
      "prompt": "The train enters from frame left while the traveler remains beside the red suitcase",
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
| `intermediate_images` | no | Ordered paths for distinct poses between `start_image` and `end_image`; use for articulated motion instead of stretching one pair. |
| `end_image` | no | Last keyframe path; omit for a hold. |
| `interpolation` | no | `hold`, `blend`, `optical-flow`, or optional `rife`; inferred from image count when omitted. |
| `optical_flow_profile` | no | `balanced` by default, or experimental `large-motion`. |
| `rife_strategy` | no | `recursive` by default for stable endpoints, or faster `direct`. |
| `motion` | no | Camera preset; defaults to `static`. |
| `transition_to_next` | no | Transition beginning near this shot's end. Defaults to a cut. |
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
shot_frames = round(shot_duration_seconds * fps)
transition_frames = round(transition_duration_seconds * fps)
output_frames = sum(shot_frames) - sum(non_cut_transition_frames)
output_duration = output_frames / fps
```

Use durations aligned to whole frames whenever possible. At 24 fps, one frame is `0.0416667` seconds. A 0.5-second transition is exactly 12 frames.
When a subject changes pose, put every materially different pose in
`intermediate_images`. The renderer distributes the shot's frame intervals
across each adjacent pair, removes repeated pair boundaries, and preserves the
declared total frame count. Interpolation cannot invent an unseen footstep from
two keyframes that have the same leg pose.
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

For a recurring subject, use an image edit/reference workflow and ask for only the stated change. If the requested change is too large for reliable interpolation, split it into additional shots or keyframe pairs.
