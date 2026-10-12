# Numeric motion checks

Use optional shot-level checks for properties measurable from output. They supplement planning and visual review; they do not track pixels, understand prompts, reconstruct geometry or certify natural animation. Existing manifests remain valid without them. Choose relevant observables, not arbitrary measurements for every object.

## Declare expectations before rendering

`motion_checks` is a non-empty array when supplied. One example entry for a 24 fps, one-second shot:

```json
{
  "id": "marker-path", "target": "marker", "property": "center",
  "space": "screen", "unit": "fraction-of-frame", "behavior": "continuous",
  "tolerance": 0.025, "min_speed": 0.3, "max_speed": 0.5, "max_acceleration": 0.1,
  "samples": [
    {"frame": 0, "value": [0.2, 0.5]},
    {"frame": 12, "value": [0.4, 0.5]},
    {"frame": 23, "value": [0.5833333333333333, 0.5]}
  ]
}
```

- `id`, `target`, `property`, `space`, `unit`: non-empty, case-sensitive strings. Use consistent identities. Duplicate IDs or target/property/space declarations in one shot are rejected; reconcile expectations in one track. This catches explicit conflicting declarations, not semantic aliases or prose contradictions.
- `behavior`: `constant`, `continuous` or `event`. A constant track plans exactly the same value at every sample; `tolerance` allows measurement error. Events may jump, such as a flash or opacity switch. Continuous tracks may pause or reverse deliberately.
- `samples`: at least two strictly increasing, zero-based **shot-local output frame indices**, each with an expected finite scalar or same-size numeric vector. Keep the same scalar/vector form. Samples may focus on a critical span and need not coincide with source keyframes. Use three or more for velocity changes. N frames end at N-1, including holds and shared-cut shots.
- `tolerance`: required non-negative Euclidean distance in the declared value space. Choose compatible units/scales for vectors. It applies to value error, not rate limits.
- `min_speed`, `max_speed`, `max_acceleration`: optional non-negative bounds for `continuous` tracks only, in units/second and units/second squared. No universal defaults. Minimum speed detects unwanted stalls only where nonzero speed is expected; omit it across intended stops. Acceleration requires three samples.

Speed is the norm of value difference divided by elapsed frame time. Acceleration is the norm of the difference in successive velocity **vectors**, divided by the time between interval midpoints. This detects reversals even at unchanged speed and handles unequal spacing. These are sampled finite differences; defects between observations can be missed. Unwrap angles across 360 degrees. Leave occluded/unobservable measurements unresolved instead of inventing values.

`validate` rejects malformed checks, contradictory constant values, planned rates outside their bounds, and changing screen-space expectations for a standalone static hold. Holds involved in incoming/outgoing transitions may change in the composed output and are exempt from that last check. It cannot infer camera/scene relationships from prose. Expectations concern the **final composed output**: account for camera transforms and transition overlap. Scene-relative values need a recoverable reference; do not relabel screen coordinates as world coordinates.

## Measure the inspected output

`inspect video.mp4 --manifest timeline.json --output-dir review-001` snapshots checks in `report.json`, includes their sample frames, and writes `motion-observations.json`:

```json
{
  "video_sha256": "hash-written-by-inspect",
  "tracks": [
    {"shot": "shot-001", "id": "marker-path", "samples": [
      {"frame": 0, "value": null},
      {"frame": 12, "value": null},
      {"frame": 23, "value": null}
    ]}
  ]
}
```

The template uses **global video frame indices**, including transition overlap. Fill only values, measured from the declared property in `preview.mp4` or its samples. Samples are scaled for viewing; convert to declared units. Keep an annotation/method note when measurement requires interpretation. Never copy expected values to pass a check. `null` means unresolved, not zero. Preserve video hash and track/frame identities.

Run `review-status review-001 --write`. Missing, duplicate, unknown, misaligned or stale observations keep delivery in `needs_review`; measured deviations or rate violations produce `needs_revision`, even when visual fields say `pass`. Measurements cannot pass missing playback review or unresolved issues. A changed video **or plan** requires fresh inspection: review-status assesses the snapshotted plan, not a live manifest.

Use these checks in the pilot and final assembly. They make chosen numeric constraints falsifiable; visual review remains responsible for anatomy, topology, content, appearance and rhythm.
