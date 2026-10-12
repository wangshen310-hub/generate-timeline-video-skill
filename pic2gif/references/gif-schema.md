# Still-frame GIF manifest

`gif.json` is separate from the legacy MP4 timeline schema.

```json
{
  "version": 1,
  "width": 512,
  "height": 512,
  "loop": true,
  "frames": [
    {"image": "images/frame-000.png", "duration_ms": 100, "state": "initial state", "prompt": "..."},
    {"image": "images/frame-001.png", "duration_ms": 80, "state": "next visible state", "prompt": "..."},
    {"image": "images/frame-002.png", "duration_ms": 120, "state": "state before closing the loop", "prompt": "..."}
  ]
}
```

- `version`: 1. Canvas width/height are integers from 1 to 4096. Default initializer uses 512×512; choose aspect ratio from the intended artwork.
- `loop`: boolean, defaults to true (infinite looping). False omits the looping extension and plays once. Design the reset explicitly for non-cyclic events.
- `frames`: nonempty ordered list. List order is playback order, independent of filenames.
- `image`: path relative to the manifest, or absolute path. Images must exist before rendering. An animated source contributes its first decoded image only.
- `duration_ms`: integer multiple of 10, range 20–655350 inclusive. GIF stores centiseconds. Delays are not silently rounded. There is no `fps` field: 100 ms means 10 displayed states per second; 80/90 ms alternating can approximate other rates when appropriate.
- `state`, `prompt`, and additional planning metadata are retained but not interpreted by the encoder. They do not establish visual acceptance.
- Total duration is the sum of delays. A repeated source path is a deliberately repeated exposure. It is not deduplicated, and the last frame's delay is preserved exactly.
- `audio`, `interpolation`, `fps`, `shots` are rejected to prevent accidental use of the old video schema.

Commands use `scripts/still_gif.py`: `init <directory> --frames N` creates placeholders without overwriting an existing manifest; `validate <manifest> --allow-missing` checks a plan; omit that flag for production. `render <manifest> --output <file.gif>` encodes and verifies. `probe <manifest> --output <file.gif>` rechecks an existing result, including full decoding. Use `--command-timeout 300` for a per-FFmpeg-command timeout and `--force` only with render to replace an existing output.

Sources are fitted without cropping, padded/flattened to white, and quantized with a shared palette and ordered dithering. The output has no audio or preserved transparency. Temporary files are created beside the output and cleaned after success or failure. Source-path normalization is reused within one render. Output publication occurs only after exact GIF block/timing validation and full decode; no-force publication uses atomic exclusive creation.

Reports include per-frame durations, total duration, loop count (`0` infinite, `null` once), dimensions and SHA-256. `technical_status: pass` means file checks passed. `visual_status: not_reviewed` is intentional: the CLI cannot certify playback, motion, appearance or loop continuity. Inspect those separately before describing the result as accepted.
