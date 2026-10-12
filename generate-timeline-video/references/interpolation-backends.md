# Interpolation backends

The renderer keeps a zero-Python-dependency path while allowing an optional
learned interpolator for difficult motion.

Choose from the planned change and source correspondence, using the shared
[representative-test workflow](motion-planning.md) before expanding new motion.
These are candidate backends, not guarantees by subject category. In particular,
pairwise interpolation has no persistent object model or cross-keyframe velocity
constraint; compatible inputs, timing and output review remain necessary.

| Backend | Best for | Runtime dependency | Failure behavior |
| --- | --- | --- | --- |
| hold | Intentional stills and camera-only motion | FFmpeg | Fails on FFmpeg errors |
| blend | Lighting changes, graphics, and deterministic fallback | FFmpeg | Fails on FFmpeg errors |
| optical-flow + balanced | Modest displacement with stable texture | FFmpeg | Falls back to blend unless strict |
| optical-flow + large-motion | Experimental wider block search | FFmpeg | Falls back to blend unless strict |
| rife + recursive | Quality-first articulated motion with stable source endpoints | FFmpeg plus RIFE ncnn Vulkan and a v4 model | Falls back to optical flow, then blend, unless strict |
| rife + direct | Faster arbitrary-timestep rendering after endpoint QA | Same optional RIFE runtime | Same fallback chain |

The large-motion profile is not automatically better. Its wider search can
create tearing or duplicated anatomy when the two images differ in topology.
Compare it against balanced on the actual project and keep it only when visual
QA passes.

## Optional RIFE integration

The selected optional backend is
[nihui/rife-ncnn-vulkan](https://github.com/nihui/rife-ncnn-vulkan), an MIT
licensed portable executable built on Tencent ncnn. Its official release
includes the executable and models and does not require a PyTorch or CUDA
installation. Only a RIFE v4 model supports the arbitrary timesteps used by
the `direct` strategy; the renderer standardizes on v4 models for both
strategies.

Download and extract an official release outside the video project. Resolve
the interpreter first: use `python3` on Unix-like systems and `python` on
Windows when `python3` is not available. Resolve FFmpeg/FFprobe similarly.

On Unix-like systems:

```bash
python3 generate-timeline-video/scripts/timeline_video.py render timeline.json \
  --interpolation rife \
  --rife-executable /path/to/rife-ncnn-vulkan \
  --rife-model /path/to/rife-v4.6 \
  --rife-gpu 0 \
  --rife-strategy recursive \
  --strict
```

On Windows PowerShell, replace `python3` with `python` and use the same
arguments. Use `--rife-gpu -1` to request the upstream CPU path. The executable
and model are never copied into the repository.

RIFE and optical flow only interpolate between supplied images. For a running
person, provide `intermediate_images` with visibly different foot contacts or
stride phases; a long pair whose legs have the same pose will translate the
runner without creating a convincing step cycle. The renderer splits each
adjacent pair and removes repeated boundaries while preserving the requested
frame count.

### RIFE strategies

`recursive` is the default. It builds the smallest power-of-two grid covering
the shot, generates only RIFE midpoints (`t=0.5`), preserves the exact source
endpoints, and evaluates non-grid output times with RIFE between their adjacent
midpoint-grid images. Encoding uses the target fps directly, with no FFmpeg
pixel-blending temporal filter. This costs additional inference calls; it avoids
full-span arbitrary-time endpoint reconstruction and the old resampling ghosts.
The local-timestep refinement still needs visual QA; it does not guarantee artifact-free motion.

`direct` asks RIFE v4 for every requested arbitrary timestep. It is faster and
can be selected with `--rife-strategy direct` or a shot-level
`"rife_strategy": "direct"`. It must pass endpoint and cut-boundary QA because
RIFE output may not converge to the supplied image as the timestep approaches
zero or one.

Both strategies apply configured camera motion after interpolation and encode
the exact requested frame count. See the fixed
[seaside regression record](../../seaside-running-test/README.md) for the
measured trade-off.

## Backend decision record

The following primary repositories were compared:

- [RIFE ncnn Vulkan](https://github.com/nihui/rife-ncnn-vulkan): selected as
  the optional integration because it is portable, MIT licensed, and avoids a
  mandatory Python ML stack.
- [ECCV2022 RIFE](https://github.com/hzwer/ECCV2022-RIFE): MIT licensed and
  authoritative, but its PyTorch environment and separately downloaded model
  make it too heavy for the default skill dependency.
- [FILM](https://github.com/google-research/frame-interpolation): Apache-2.0
  and designed for large motion, but the repository is archived and its
  TensorFlow/CUDA setup is substantially heavier.

## Shared cut boundaries

When one shot's end_image and the next shot's start_image are byte-identical
and the transition is a cut, the renderer samples the first shot on an open
interval. The next shot supplies the shared endpoint exactly once. This removes
a one-frame freeze without changing the declared frame count or duration.
