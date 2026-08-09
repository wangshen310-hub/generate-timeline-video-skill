# Dense articulated running regression

This code-first regression fixture exercises timed semantic keyframes. The
1.5-second shot declares `subject_motion: "articulated"` and contains seven
distinct gait poses at 0.25-second spacing: contacts, push-offs, and flight
phases. It exists to detect the failure mode where interpolation moves a body
while the feet keep the same pose.

The manifest was scaffolded by the renderer itself:

```bash
python generate-timeline-video/scripts/timeline_video.py plan-keyframes dense-running-test/timeline.json --write
```

Validate and render with an explicitly supplied RIFE v4 runtime:

```bash
python generate-timeline-video/scripts/timeline_video.py validate dense-running-test/timeline.json
python generate-timeline-video/scripts/timeline_video.py render dense-running-test/timeline.json \
  --output dense-running-test/output/dense-running-rife.mp4 \
  --rife-executable /path/to/rife-ncnn-vulkan \
  --rife-model /path/to/rife-v4.6 --rife-strategy recursive --strict
python generate-timeline-video/scripts/timeline_video.py probe \
  dense-running-test/output/dense-running-rife.mp4 \
  --manifest dense-running-test/timeline.json
```

The checked-in strict recursive-RIFE render is H.264, 1280x720, 24 fps, 36
frames, and 1.500 seconds. SHA-256:
`8D2BA802547832A6085F305D0BE45D524D90A014607BC6B9454617B10B9E46B2`. Its
benchmark has zero near-duplicate adjacent pairs; temporal-luma jerk p95 is
0.880291, so semantic-pose boundaries still require visual QA.

The images are generated test inputs, not evidence that interpolation is
physically exact. Visual inspection of the full encoded sequence remains
required.
