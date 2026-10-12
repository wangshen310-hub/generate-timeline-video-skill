#!/usr/bin/env python3
"""Encode explicitly timed stills as GIF; no synthesized motion. Standard library only."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile


def integer(value, low, high, label):
    if type(value) is not int or not low <= value <= high:
        raise ValueError(f"{label} must be an integer from {low} to {high}")
    return value


def load_manifest(path, allow_missing=False):
    path = Path(path).resolve()
    data = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(data, dict) or type(data.get("version")) is not int or data["version"] != 1:
        raise ValueError("Expected GIF manifest version 1")
    for key in ("audio", "interpolation", "fps", "shots"):
        if key in data:
            raise ValueError(f"{key} is not supported in a still-frame GIF manifest")
    integer(data.get("width"), 1, 4096, "width")
    integer(data.get("height"), 1, 4096, "height")
    if type(data.get("loop", True)) is not bool:
        raise ValueError("loop must be true or false")
    frames = data.get("frames")
    if not isinstance(frames, list) or not frames:
        raise ValueError("frames must be a nonempty ordered list")
    for frame in frames:
        if not isinstance(frame, dict) or not isinstance(frame.get("image"), str) or not frame["image"].strip():
            raise ValueError("Each frame needs an image path")
        integer(frame.get("duration_ms"), 20, 655350, "duration_ms")
        if frame["duration_ms"] % 10:
            raise ValueError("duration_ms must be a multiple of 10 (GIF centiseconds)")
        image = (path.parent / frame["image"]).resolve()
        if not allow_missing and not image.is_file():
            raise ValueError(f"Missing image: {image}")
    return data


def run(command, timeout):
    result = subprocess.run(command, capture_output=True, text=True, timeout=timeout)
    if result.returncode:
        raise RuntimeError(result.stderr[-6000:])
    return result.stdout


def inspect_gif(path):
    """Read GIF block timing directly; decoder validation is a separate step."""
    blob = Path(path).read_bytes()
    pos = 0

    def take(n):
        nonlocal pos
        value = blob[pos:pos + n]
        if len(value) != n:
            raise ValueError("Truncated GIF")
        pos += n
        return value

    def blocks():
        chunks = []
        while True:
            size = take(1)[0]
            if not size:
                return b"".join(chunks)
            chunks.append(take(size))

    if take(6) not in (b"GIF89a", b"GIF87a"):
        raise ValueError("Not a GIF")
    screen = take(7)
    width, height = int.from_bytes(screen[:2], "little"), int.from_bytes(screen[2:4], "little")
    if screen[4] & 128:
        take(3 * 2 ** ((screen[4] & 7) + 1))
    delay, durations, loop_count = 0, [], None
    while True:
        marker = take(1)[0]
        if marker == 0x3B:
            break
        if marker == 0x21:
            label = take(1)[0]
            payload = blocks()
            if label == 0xF9:
                if len(payload) != 4:
                    raise ValueError("Invalid GIF graphics control")
                delay = int.from_bytes(payload[1:3], "little") * 10
            elif label == 0xFF and payload[:11] in (b"NETSCAPE2.0", b"ANIMEXTS1.0"):
                if len(payload) >= 14 and payload[11] == 1:
                    loop_count = int.from_bytes(payload[12:14], "little")
        elif marker == 0x2C:
            desc = take(9)
            if desc[8] & 128:
                take(3 * 2 ** ((desc[8] & 7) + 1))
            take(1)
            blocks()
            durations.append(delay)
            delay = 0
        else:
            raise ValueError("Invalid GIF block")
    if not durations:
        raise ValueError("GIF contains no frames")
    return {"width": width, "height": height, "frames": len(durations),
            "durations_ms": durations, "duration_ms": sum(durations), "loop_count": loop_count,
            "sha256": hashlib.sha256(blob).hexdigest()}


def verify(path, data, ffmpeg, timeout):
    report = inspect_gif(path)
    expected = [f["duration_ms"] for f in data["frames"]]
    if (report["width"], report["height"]) != (data["width"], data["height"]):
        raise ValueError("GIF dimensions differ from manifest")
    if report["durations_ms"] != expected:
        raise ValueError(f"GIF timing mismatch: {report['durations_ms']} != {expected}")
    if report["loop_count"] != (0 if data.get("loop", True) else None):
        raise ValueError("GIF loop mode differs from manifest")
    run([ffmpeg, "-v", "error", "-xerror", "-ignore_loop", "1", "-i", str(path), "-f", "null", "-"], timeout)
    report["technical_status"] = "pass"
    report["visual_status"] = "not_reviewed"
    return report


def render(manifest, output, force=False, timeout=300):
    manifest, output = Path(manifest).resolve(), Path(output).resolve()
    data = load_manifest(manifest)
    sources = [(manifest.parent / f["image"]).resolve() for f in data["frames"]]
    if output.suffix.lower() != ".gif":
        raise ValueError("Output must use .gif")
    protected = [manifest, *sources]
    if output in protected or (output.exists() and any(os.path.samefile(output, p) for p in protected)):
        raise ValueError("Output must not overwrite manifest or source images")
    if output.exists() and not force:
        raise FileExistsError(f"Output exists: {output}")
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise RuntimeError("FFmpeg is required")
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".still-gif-", dir=output.parent) as temp:
        temp = Path(temp)
        normalized, listing = {}, []
        for source, frame in zip(sources, data["frames"]):
            if source not in normalized:
                target = temp / f"image-{len(normalized):06}.png"
                # Fit without cropping, flatten transparency onto white. One decoded image only.
                vf = (f"scale={data['width']}:{data['height']}:force_original_aspect_ratio=decrease,"
                      f"pad={data['width']}:{data['height']}:(ow-iw)/2:(oh-ih)/2:color=white,"
                      "format=rgba,split[bg][fg];[bg]lutrgb=r=255:g=255:b=255:a=255[white];"
                      "[white][fg]overlay=format=auto,format=rgb24")
                run([ffmpeg, "-v", "error", "-y", "-i", str(source), "-filter_complex", vf,
                     "-frames:v", "1", "-threads", "1", str(target)], timeout)
                normalized[source] = target.name
            listing.extend([f"file '{normalized[source]}'", "option framerate 100",
                            f"duration {frame['duration_ms'] / 1000:.2f}"])
        listing.extend([f"file '{normalized[sources[-1]]}'", "option framerate 100"])
        concat = temp / "frames.txt"
        concat.write_text("ffconcat version 1.0\n" + "\n".join(listing) + "\n", encoding="utf-8")
        candidate = temp / "candidate.gif"
        run([ffmpeg, "-v", "error", "-y", "-filter_complex_threads", "1", "-f", "concat", "-safe", "0",
             "-i", str(concat), "-filter_complex",
             "split[a][b];[a]palettegen=reserve_transparent=0[p];[b][p]paletteuse=dither=bayer:bayer_scale=3",
             "-fps_mode", "vfr", "-enc_time_base", "1:100", "-frames:v", str(len(sources)),
             "-loop", "0" if data.get("loop", True) else "-1",
             "-final_delay", str(data["frames"][-1]["duration_ms"] // 10), str(candidate)], timeout)
        report = verify(candidate, data, ffmpeg, timeout)
        if force:
            os.replace(candidate, output)
        else:
            os.link(candidate, output)  # Atomic create; never clobber a concurrent writer.
        report["output"] = str(output)
        return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    init = sub.add_parser("init")
    init.add_argument("directory", type=Path)
    init.add_argument("--frames", type=int, default=12)
    for name in ("validate", "render", "probe"):
        p = sub.add_parser(name)
        p.add_argument("manifest", type=Path)
        if name == "validate":
            p.add_argument("--allow-missing", action="store_true")
        else:
            p.add_argument("--output", type=Path, required=True)
            p.add_argument("--command-timeout", type=int, default=300)
        if name == "render":
            p.add_argument("--force", action="store_true")
    args = parser.parse_args()
    try:
        if args.command == "init":
            integer(args.frames, 1, 10000, "frames")
            args.directory.mkdir(parents=True, exist_ok=True)
            (args.directory / "images").mkdir(exist_ok=True)
            data = {"version": 1, "width": 512, "height": 512, "loop": True,
                    "frames": [{"image": f"images/frame-{i:03}.png", "duration_ms": 100,
                                "state": "", "prompt": ""} for i in range(args.frames)]}
            path = args.directory / "gif.json"
            with path.open("x", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            result = {"manifest": str(path), "missing_images": args.frames}
        elif args.command == "validate":
            data = load_manifest(args.manifest, args.allow_missing)
            result = {"valid": True, "frames": len(data["frames"]),
                      "duration_ms": sum(f["duration_ms"] for f in data["frames"])}
        elif args.command == "render":
            result = render(args.manifest, args.output, args.force, args.command_timeout)
        else:
            result = verify(args.output, load_manifest(args.manifest), shutil.which("ffmpeg") or "ffmpeg", args.command_timeout)
        print(json.dumps(result, ensure_ascii=False))
    except (ValueError, OSError, RuntimeError, subprocess.SubprocessError) as exc:
        print(json.dumps({"error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
