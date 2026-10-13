# Plan and review contract

This contract supplements `gif-schema.md`. It describes optional measurements, not a scene classifier or automatic animation generator. Old version-1 manifests can still validate/render previews. A complete `plan` is required for `plan-check`, `inspect`, `review-status` and `publish`.

```json
{
  "intent": "motion",
  "source_mode": "provided",
  "summary": "A visible element changes position across three states",
  "measurements": [
    {
      "id": "position",
      "property": "horizontal position",
      "space": "screen",
      "unit": "normalized canvas width",
      "expected": [0.2, 0.4, 0.6],
      "tolerance": 0.03
    }
  ],
  "fixed_regions": [
    {"id": "corner", "rect": [0, 0, 0.1, 0.1], "max_mae": 4}
  ]
}
```

Place this object under `plan` in `gif.json`, matching the actual frame count. This example has no speed constraints and does not imply a physically seamless loop. Decide `loop` and frame exposures from intent.

## Planning

- `intent`: `motion` or `still`. It drives duplicate-state handling, not object-specific rules.
- `source_mode`: `generated` requires nonempty state and prompt on every frame; `provided` requires state only. `summary` is nonempty text. Neither text nor a successful plan check proves semantic quality or historical planning order.
- `measurements`: optional list, default empty. Each item has a unique `id`, `property`, `space`, `unit`, one scalar or 1–4-component vector `expected` value per frame, and a nonnegative `tolerance` in the same units. Vectors use Euclidean distances. All values are finite; dimensions must match.
- Optional `min_speed`, `max_speed`, `max_acceleration` use those units per second / per second squared. Bounds apply to every edge, including the wrap if `loop` is true and there is more than one frame. Do not use a positive minimum speed on an intentional hold. Plan checking rejects expected values that contradict their own limits.
- Interval i→i+1 uses frame i's exposure, including last→first. Acceleration compares neighboring velocity vectors over the average of their two interval lengths. This is a discrete diagnostic, not a physical model. Explicitly unwrap cyclic measurements such as angles; mark discrete events through frame states and visual checks rather than forcing smooth-velocity limits on them.
- `fixed_regions`: optional list of normalized output-canvas `[x,y,width,height]` rectangles fully inside [0,1]. `max_mae` is an explicit 0–255 RGB threshold against frame 0. Inspection downsamples the decoded GIF to at most 512 pixels on the longest edge, records `analysis_size`, and includes palette/dithering effects in this check. Use the same interpretation when selecting thresholds. It does not measure source-only drift or automatically compensate for camera motion.
- Optional `max_bytes`: positive integer delivery budget. Exceeding it requires revision, not silent rescaling.
- IDs are unique across measurements and fixed regions. State, timing, check thresholds and plan revisions should be saved before the relevant generation/review stage. Genuine later revisions should be explained; don't loosen thresholds to conceal failure.

## Review commands and files

```text
python scripts/still_gif.py plan-check project/gif.json --allow-missing
python scripts/still_gif.py render project/gif.json --output project/preview.gif
python scripts/still_gif.py inspect project/gif.json --output project/preview.gif --review-dir project/review-001
python scripts/still_gif.py review-status project/review-001
python scripts/still_gif.py publish project/review-001 --output project/delivery/final.gif
```

Run from the skill directory or use the script's absolute path. `inspect` creates a new directory, refuses an existing destination, and snapshots `preview.gif`, decoded PNGs, `analysis.json` and `index.html`. These plus original manifest, source and output bytes are hash-bound. It leaves partial diagnostic files on an inspection failure; choose a new directory for a retry. A review package is not portable away from its bound source paths: regenerate inspection after moving the project.

`review.json` contains required `checks`, `issues` (unresolved strings) and measurement `observations`. Edit those fields only. Example observation:

```json
{"values": [0.21, 0.39, 0.61], "evidence": "Measured element center in decoded output frame pixels, divided by the full canvas width."}
```

Values start as null, never as the expectations. Measurements can come from appropriate pixel tooling or actual manual annotation; explain the method and limitations. There is no automatic object detector. A metric does not replace human/agent visual review.

Required checks are `source_sequence`, `timing_and_events`, `normal_speed_playback`, plus `loop_join` when looping and `duplicate_holds` when moving content has identical adjacent decoded frames. Each has `status` (`pending`, `pass`, `revise`) and a concrete `note`; pass without a note remains pending. Missing required checks remain pending. Document legitimate repeated exposures in duplicate_holds; a motion plan whose entire decoded sequence is identical requires revision regardless of notes. A still plan permits identical frames.

`review-status` uses exit 0 only for pass; pending/revise/stale return 2, malformed inputs return 1. Known failures take precedence over pending checks. Missing or changed bound artifacts cannot pass; missing paths may report an error instead of stale. Changing a snapshot, source, output, timing, expected values or thresholds requires a new `inspect`. It does not write an acceptance file or automatically turn pending notes into pass.

`publish` refuses non-passing reviews, protected source paths and paths inside the review package. It copies exactly the reviewed bytes, verifies timing/full decoding and rechecks review status before atomic publication. `--force` replaces only an unrelated existing delivery file after checks. Original rendering still produces a technically checked preview even if the plan/visual review has not passed; filenames do not confer acceptance.

## Playback

The page embeds the actual GIF at original speed, has a replay button, and provides a three-frame window with state/exposure/start time plus a last-frame shortcut. It does not mark checks or collect telemetry. If file:// viewing is unsupported:

```text
python -m http.server 8779 --bind 127.0.0.1 --directory project/review-001
```

Open `http://127.0.0.1:8779/`; use another free port if needed. Serve only the intended review directory. Check actual frame advancement and the required events; one screenshot or queued panel is insufficient evidence of full normal-speed review.

Automatic diagnostics are recomputed from the actual GIF during review-status, including byte size, identical states and region differences. Edited cached conclusions or mismatched snapshots are rejected even if their declared hashes were updated. Inspection is bound to the current decoder/page implementation; regenerate inspection after implementation or FFmpeg changes that alter snapshot bytes. Review notes are not authenticated human testimony, and local JSON hashes are not cryptographic signatures.
