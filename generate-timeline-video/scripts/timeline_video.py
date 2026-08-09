#!/usr/bin/env python3
"""Render a JSON timeline of still-image keyframes into an exact-fps MP4.

Requires ffmpeg and ffprobe. Uses only Python's standard library.
"""

from __future__ import annotations

import argparse
import json
import math
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any


SCHEMA_VERSION = 1
INTERPOLATIONS = {"hold", "blend", "optical-flow"}
MOTIONS = {
    "static",
    "zoom-in",
    "zoom-out",
    "pan-left",
    "pan-right",
    "pan-up",
    "pan-down",
}
TRANSITIONS = {
    "cut",
    "fade",
    "dissolve",
    "wipeleft",
    "wiperight",
    "wipeup",
    "wipedown",
    "slideleft",
    "slideright",
    "slideup",
    "slidedown",
}
ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


class TimelineError(Exception):
    """Raised for actionable timeline or environment errors."""


def eprint(message: str) -> None:
    print(message, file=sys.stderr)


def require_tool(name: str) -> str:
    executable = shutil.which(name)
    if not executable:
        raise TimelineError(f"Required executable not found on PATH: {name}")
    return executable


def run(command: list[str], *, capture: bool = False) -> subprocess.CompletedProcess[str]:
    print(f"+ {shlex.join(command)}")
    return subprocess.run(
        command,
        check=True,
        text=True,
        stdout=subprocess.PIPE if capture else None,
        stderr=subprocess.PIPE if capture else None,
    )


def is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def frame_count(seconds: float, fps: int) -> int:
    return int(math.floor(seconds * fps + 0.5))


def resolve_media(base: Path, value: str) -> Path:
    path = Path(value).expanduser()
    return path if path.is_absolute() else (base / path).resolve()


def transition_for(shot: Any) -> tuple[str, Any]:
    if not isinstance(shot, dict):
        return "cut", 0
    transition = shot.get("transition_to_next") or {}
    if not isinstance(transition, dict):
        return "cut", 0
    return str(transition.get("type", "cut")), transition.get("duration", 0)


def interpolation_for(shot: dict[str, Any]) -> str:
    default = "optical-flow" if shot.get("end_image") else "hold"
    return str(shot.get("interpolation", default))


def motion_for(shot: dict[str, Any]) -> str:
    return str(shot.get("motion", "static"))


def load_and_validate(
    manifest_path: Path,
    *,
    require_files: bool = True,
    probe_files: bool = False,
) -> tuple[dict[str, Any], list[str]]:
    manifest_path = manifest_path.expanduser().resolve()
    if not manifest_path.is_file():
        raise TimelineError(f"Timeline does not exist: {manifest_path}")

    try:
        data = json.loads(manifest_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise TimelineError(f"Invalid JSON at line {exc.lineno}, column {exc.colno}: {exc.msg}") from exc

    if not isinstance(data, dict):
        raise TimelineError("Timeline root must be a JSON object")

    errors: list[str] = []
    warnings: list[str] = []

    if data.get("version") != SCHEMA_VERSION:
        errors.append(f"version must be {SCHEMA_VERSION}")
    if not isinstance(data.get("title"), str) or not data["title"].strip():
        errors.append("title must be a non-empty string")

    fps = data.get("fps")
    if not isinstance(fps, int) or isinstance(fps, bool) or not 1 <= fps <= 120:
        errors.append("fps must be an integer from 1 to 120")
        fps = 24

    width = data.get("width")
    height = data.get("height")
    for name, value in (("width", width), ("height", height)):
        if not isinstance(value, int) or isinstance(value, bool) or value <= 0 or value % 2:
            errors.append(f"{name} must be a positive even integer")

    shots = data.get("shots")
    if not isinstance(shots, list) or not shots:
        errors.append("shots must be a non-empty array")
        shots = []

    base = manifest_path.parent
    seen_ids: set[str] = set()
    shot_frames: list[int] = []
    media_to_probe: dict[Path, set[str]] = {}

    def expect_stream(path: Path, codec_type: str) -> None:
        media_to_probe.setdefault(path, set()).add(codec_type)

    for index, shot in enumerate(shots):
        prefix = f"shots[{index}]"
        if not isinstance(shot, dict):
            errors.append(f"{prefix} must be an object")
            shot_frames.append(0)
            continue

        shot_id = shot.get("id")
        if not isinstance(shot_id, str) or not ID_PATTERN.fullmatch(shot_id):
            errors.append(f"{prefix}.id must match {ID_PATTERN.pattern}")
        elif shot_id in seen_ids:
            errors.append(f"{prefix}.id is duplicated: {shot_id}")
        else:
            seen_ids.add(shot_id)

        duration = shot.get("duration")
        if not is_number(duration) or duration <= 0:
            errors.append(f"{prefix}.duration must be a positive number")
            frames = 0
        else:
            frames = frame_count(float(duration), fps)
            if frames < 2:
                errors.append(f"{prefix}.duration must contain at least 2 frames")
            if abs(float(duration) * fps - frames) > 1e-6:
                warnings.append(
                    f"{prefix}.duration rounds from {float(duration) * fps:.4f} to {frames} frames"
                )
        shot_frames.append(frames)

        start_image = shot.get("start_image")
        if not isinstance(start_image, str) or not start_image.strip():
            errors.append(f"{prefix}.start_image must be a non-empty path")
        else:
            path = resolve_media(base, start_image)
            if require_files and not path.is_file():
                errors.append(f"{prefix}.start_image does not exist: {path}")
            elif path.is_file():
                expect_stream(path, "video")

        end_image = shot.get("end_image")
        if end_image is not None and (not isinstance(end_image, str) or not end_image.strip()):
            errors.append(f"{prefix}.end_image must be a non-empty path when present")
        elif isinstance(end_image, str):
            path = resolve_media(base, end_image)
            if require_files and not path.is_file():
                errors.append(f"{prefix}.end_image does not exist: {path}")
            elif path.is_file():
                expect_stream(path, "video")

        interpolation = interpolation_for(shot)
        if interpolation not in INTERPOLATIONS:
            errors.append(f"{prefix}.interpolation must be one of {sorted(INTERPOLATIONS)}")
        elif interpolation != "hold" and not isinstance(end_image, str):
            errors.append(f"{prefix}.end_image is required for {interpolation}")
        elif interpolation == "hold" and isinstance(end_image, str):
            warnings.append(f"{prefix}.end_image is ignored because interpolation is hold")

        motion = motion_for(shot)
        if motion not in MOTIONS:
            errors.append(f"{prefix}.motion must be one of {sorted(MOTIONS)}")

        transition = shot.get("transition_to_next")
        if transition is not None and not isinstance(transition, dict):
            errors.append(f"{prefix}.transition_to_next must be an object")
        else:
            transition_type, transition_duration = transition_for(shot)
            if transition_type not in TRANSITIONS:
                errors.append(f"{prefix} transition type must be one of {sorted(TRANSITIONS)}")
            if transition_type == "cut":
                if transition_duration != 0:
                    warnings.append(f"{prefix} cut transition ignores its duration")
            elif not is_number(transition_duration) or transition_duration <= 0:
                errors.append(f"{prefix} non-cut transition duration must be positive")
            elif abs(transition_duration * fps - frame_count(transition_duration, fps)) > 1e-6:
                warnings.append(
                    f"{prefix} transition rounds from {transition_duration * fps:.4f} "
                    f"to {frame_count(transition_duration, fps)} frames"
                )

    for index in range(max(0, len(shots) - 1)):
        transition_type, transition_duration = transition_for(shots[index])
        if transition_type == "cut":
            continue
        if not is_number(transition_duration) or transition_duration <= 0:
            continue
        frames = frame_count(float(transition_duration), fps)
        if frames < 1:
            errors.append(f"shots[{index}] transition must contain at least 1 frame")
        if index + 1 < len(shot_frames) and frames >= min(shot_frames[index], shot_frames[index + 1]):
            errors.append(f"shots[{index}] transition must be shorter than both neighboring shots")

    if shots:
        last_type, _ = transition_for(shots[-1])
        if last_type != "cut":
            warnings.append("The last shot's transition_to_next is ignored")

    audio = data.get("audio")
    if audio is not None:
        if not isinstance(audio, dict):
            errors.append("audio must be an object")
        else:
            audio_file = audio.get("file")
            if not isinstance(audio_file, str) or not audio_file.strip():
                errors.append("audio.file must be a non-empty path")
            else:
                path = resolve_media(base, audio_file)
                if require_files and not path.is_file():
                    errors.append(f"audio.file does not exist: {path}")
                elif path.is_file():
                    expect_stream(path, "audio")
            volume = audio.get("volume", 1.0)
            if not is_number(volume) or not 0 <= volume <= 4:
                errors.append("audio.volume must be a number from 0 to 4")
            if not isinstance(audio.get("loop", False), bool):
                errors.append("audio.loop must be true or false")
            for field in ("fade_in", "fade_out"):
                value = audio.get(field, 0)
                if not is_number(value) or value < 0:
                    errors.append(f"audio.{field} must be a non-negative number")

    if errors:
        raise TimelineError("Timeline validation failed:\n- " + "\n- ".join(errors))

    if probe_files:
        ffprobe = require_tool("ffprobe")
        for path, expected_types in sorted(media_to_probe.items(), key=lambda item: str(item[0])):
            try:
                result = run(
                    [
                        ffprobe,
                        "-v",
                        "error",
                        "-show_entries",
                        "stream=codec_type,width,height,duration",
                        "-show_entries",
                        "format=duration",
                        "-of",
                        "json",
                        str(path),
                    ],
                    capture=True,
                )
                payload = json.loads(result.stdout)
                streams = payload.get("streams") or []
                if not streams:
                    raise ValueError("no media streams")
                codec_types = {stream.get("codec_type") for stream in streams}
                missing_types = expected_types - codec_types
                if missing_types:
                    raise ValueError(f"missing expected stream types: {sorted(missing_types)}")
            except (subprocess.CalledProcessError, json.JSONDecodeError, ValueError) as exc:
                raise TimelineError(f"ffprobe could not read media file: {path}") from exc

    return data, warnings


def total_output_frames(data: dict[str, Any]) -> int:
    fps = int(data["fps"])
    shots = data["shots"]
    total = sum(frame_count(float(shot["duration"]), fps) for shot in shots)
    for shot in shots[:-1]:
        transition_type, duration = transition_for(shot)
        if transition_type != "cut":
            total -= frame_count(float(duration), fps)
    return total


def base_image_filter(width: int, height: int) -> str:
    return (
        f"scale={width}:{height}:force_original_aspect_ratio=increase:flags=lanczos,"
        f"crop={width}:{height},setsar=1"
    )


def motion_filter(
    motion: str,
    width: int,
    height: int,
    frames: int,
    fps: int,
    *,
    normalized: bool = False,
) -> str:
    base = f"scale={width}:{height}:flags=lanczos,setsar=1" if normalized else base_image_filter(width, height)
    denominator = max(frames - 1, 1)

    if motion == "static":
        return base
    if motion in {"zoom-in", "zoom-out"}:
        if motion == "zoom-in":
            zoom = f"1+0.08*on/{denominator}"
        else:
            zoom = f"1.08-0.08*on/{denominator}"
        return (
            f"{base},zoompan=z='{zoom}':x='iw/2-(iw/zoom/2)':"
            f"y='ih/2-(ih/zoom/2)':d=1:s={width}x{height}:fps={fps}"
        )

    oversize_width = int(math.ceil(width * 1.08 / 2) * 2)
    oversize_height = int(math.ceil(height * 1.08 / 2) * 2)
    progress = f"n/{denominator}"
    if motion == "pan-left":
        x, y = f"(in_w-out_w)*(1-{progress})", "(in_h-out_h)/2"
    elif motion == "pan-right":
        x, y = f"(in_w-out_w)*{progress}", "(in_h-out_h)/2"
    elif motion == "pan-up":
        x, y = "(in_w-out_w)/2", f"(in_h-out_h)*(1-{progress})"
    else:
        x, y = "(in_w-out_w)/2", f"(in_h-out_h)*{progress}"
    return (
        f"{base},scale={oversize_width}:{oversize_height}:flags=lanczos,"
        f"crop={width}:{height}:x='{x}':y='{y}'"
    )


def encoding_args(preset: str, crf: int) -> list[str]:
    return [
        "-an",
        "-c:v",
        "libx264",
        "-preset",
        preset,
        "-crf",
        str(crf),
        "-pix_fmt",
        "yuv420p",
        "-movflags",
        "+faststart",
    ]


def normalize_image(ffmpeg: str, source: Path, target: Path, width: int, height: int) -> None:
    run(
        [
            ffmpeg,
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-i",
            str(source),
            "-vf",
            base_image_filter(width, height),
            "-frames:v",
            "1",
            str(target),
        ]
    )


def render_hold(
    ffmpeg: str,
    image: Path,
    output: Path,
    *,
    width: int,
    height: int,
    fps: int,
    frames: int,
    motion: str,
    preset: str,
    crf: int,
) -> None:
    video_filter = f"{motion_filter(motion, width, height, frames, fps)},fps={fps},format=yuv420p"
    run(
        [
            ffmpeg,
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-loop",
            "1",
            "-framerate",
            str(fps),
            "-i",
            str(image),
            "-vf",
            video_filter,
            "-frames:v",
            str(frames),
            "-r",
            str(fps),
            *encoding_args(preset, crf),
            str(output),
        ]
    )


def render_blend(
    ffmpeg: str,
    start_image: Path,
    end_image: Path,
    output: Path,
    *,
    width: int,
    height: int,
    fps: int,
    frames: int,
    motion: str,
    preset: str,
    crf: int,
) -> None:
    first = motion_filter(motion, width, height, frames, fps)
    second = motion_filter(motion, width, height, frames, fps)
    denominator = max(frames - 1, 1)
    graph = (
        f"[0:v]{first},fps={fps},trim=end_frame={frames},setpts=PTS-STARTPTS[a];"
        f"[1:v]{second},fps={fps},trim=end_frame={frames},setpts=PTS-STARTPTS[b];"
        f"[a][b]blend=all_expr='A*(1-N/{denominator})+B*N/{denominator}':shortest=1,"
        "format=yuv420p[out]"
    )
    run(
        [
            ffmpeg,
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-loop",
            "1",
            "-framerate",
            str(fps),
            "-i",
            str(start_image),
            "-loop",
            "1",
            "-framerate",
            str(fps),
            "-i",
            str(end_image),
            "-filter_complex",
            graph,
            "-map",
            "[out]",
            "-frames:v",
            str(frames),
            "-r",
            str(fps),
            *encoding_args(preset, crf),
            str(output),
        ]
    )


def render_optical_flow(
    ffmpeg: str,
    start_image: Path,
    end_image: Path,
    output: Path,
    work_dir: Path,
    *,
    width: int,
    height: int,
    fps: int,
    frames: int,
    motion: str,
    preset: str,
    crf: int,
) -> None:
    pair_dir = work_dir / f"pair-{output.stem}"
    pair_dir.mkdir(parents=True, exist_ok=False)
    first = pair_dir / "frame000000.png"
    second = pair_dir / "frame000001.png"
    third = pair_dir / "frame000002.png"
    normalize_image(ffmpeg, start_image, first, width, height)
    normalize_image(ffmpeg, end_image, second, width, height)
    shutil.copyfile(second, third)

    input_rate = f"{fps}/{max(frames - 1, 1)}"
    post_motion = motion_filter(motion, width, height, frames, fps, normalized=True)
    video_filter = (
        f"minterpolate=fps={fps}:mi_mode=mci:mc_mode=aobmc:me_mode=bidir:vsbmc=1:scd=none,"
        f"{post_motion},fps={fps},format=yuv420p"
    )
    run(
        [
            ffmpeg,
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-framerate",
            input_rate,
            "-start_number",
            "0",
            "-i",
            str(pair_dir / "frame%06d.png"),
            "-vf",
            video_filter,
            "-frames:v",
            str(frames),
            "-r",
            str(fps),
            *encoding_args(preset, crf),
            str(output),
        ]
    )


def render_shot(
    data: dict[str, Any],
    shot: dict[str, Any],
    manifest_dir: Path,
    output: Path,
    work_dir: Path,
    *,
    ffmpeg: str,
    interpolation_override: str | None,
    strict: bool,
    preset: str,
    crf: int,
) -> str:
    width = int(data["width"])
    height = int(data["height"])
    fps = int(data["fps"])
    frames = frame_count(float(shot["duration"]), fps)
    motion = motion_for(shot)
    interpolation = interpolation_override or interpolation_for(shot)
    start_image = resolve_media(manifest_dir, shot["start_image"])
    end_value = shot.get("end_image")
    end_image = resolve_media(manifest_dir, end_value) if isinstance(end_value, str) else None

    if interpolation == "hold":
        render_hold(
            ffmpeg,
            start_image,
            output,
            width=width,
            height=height,
            fps=fps,
            frames=frames,
            motion=motion,
            preset=preset,
            crf=crf,
        )
        return "hold"

    if end_image is None:
        raise TimelineError(f"Shot {shot['id']} needs end_image for {interpolation}")

    if interpolation == "blend":
        render_blend(
            ffmpeg,
            start_image,
            end_image,
            output,
            width=width,
            height=height,
            fps=fps,
            frames=frames,
            motion=motion,
            preset=preset,
            crf=crf,
        )
        return "blend"

    try:
        render_optical_flow(
            ffmpeg,
            start_image,
            end_image,
            output,
            work_dir,
            width=width,
            height=height,
            fps=fps,
            frames=frames,
            motion=motion,
            preset=preset,
            crf=crf,
        )
        return "optical-flow"
    except subprocess.CalledProcessError:
        if strict:
            raise
        eprint(f"WARNING: optical flow failed for {shot['id']}; falling back to blend")
        render_blend(
            ffmpeg,
            start_image,
            end_image,
            output,
            width=width,
            height=height,
            fps=fps,
            frames=frames,
            motion=motion,
            preset=preset,
            crf=crf,
        )
        return "blend-fallback"


def assemble_shots(
    ffmpeg: str,
    data: dict[str, Any],
    clips: list[Path],
    output: Path,
    *,
    preset: str,
    crf: int,
) -> int:
    fps = int(data["fps"])
    width = int(data["width"])
    height = int(data["height"])
    shots = data["shots"]
    expected_frames = total_output_frames(data)

    if len(clips) == 1:
        shutil.copyfile(clips[0], output)
        return expected_frames

    command = [ffmpeg, "-hide_banner", "-loglevel", "error", "-y"]
    for clip in clips:
        command.extend(["-i", str(clip)])

    filters: list[str] = []
    for index in range(len(clips)):
        filters.append(
            f"[{index}:v]fps={fps},scale={width}:{height},format=yuv420p,"
            f"settb=AVTB,setpts=PTS-STARTPTS[v{index}]"
        )

    current = "v0"
    current_frames = frame_count(float(shots[0]["duration"]), fps)
    for index in range(1, len(clips)):
        transition_type, transition_duration = transition_for(shots[index - 1])
        next_label = f"v{index}"
        combined = f"c{index}"
        next_frames = frame_count(float(shots[index]["duration"]), fps)
        if transition_type == "cut":
            filters.append(f"[{current}][{next_label}]concat=n=2:v=1:a=0[{combined}]")
            current_frames += next_frames
        else:
            overlap_frames = frame_count(float(transition_duration), fps)
            offset = (current_frames - overlap_frames) / fps
            duration = overlap_frames / fps
            filters.append(
                f"[{current}][{next_label}]xfade=transition={transition_type}:"
                f"duration={duration:.9f}:offset={offset:.9f}[{combined}]"
            )
            current_frames += next_frames - overlap_frames
        current = combined

    filters.append(f"[{current}]fps={fps},format=yuv420p[out]")
    command.extend(
        [
            "-filter_complex",
            ";".join(filters),
            "-map",
            "[out]",
            "-frames:v",
            str(expected_frames),
            "-r",
            str(fps),
            *encoding_args(preset, crf),
            str(output),
        ]
    )
    run(command)
    return expected_frames


def mux_audio(
    ffmpeg: str,
    data: dict[str, Any],
    manifest_dir: Path,
    video: Path,
    output: Path,
    total_frames: int,
) -> None:
    audio = data["audio"]
    fps = int(data["fps"])
    duration = total_frames / fps
    audio_path = resolve_media(manifest_dir, audio["file"])
    volume = float(audio.get("volume", 1.0))
    fade_in = min(float(audio.get("fade_in", 0)), duration)
    fade_out = min(float(audio.get("fade_out", 0)), duration)

    command = [ffmpeg, "-hide_banner", "-loglevel", "error", "-y", "-i", str(video)]
    if audio.get("loop", False):
        command.extend(["-stream_loop", "-1"])
    command.extend(["-i", str(audio_path)])

    filters = [
        "[1:a]asetpts=PTS-STARTPTS",
        f"volume={volume:.6f}",
        "apad",
        f"atrim=duration={duration:.9f}",
    ]
    if fade_in > 0:
        filters.append(f"afade=t=in:st=0:d={fade_in:.9f}")
    if fade_out > 0:
        filters.append(f"afade=t=out:st={max(0, duration - fade_out):.9f}:d={fade_out:.9f}")

    command.extend(
        [
            "-filter_complex",
            ",".join(filters) + "[a]",
            "-map",
            "0:v:0",
            "-map",
            "[a]",
            "-c:v",
            "copy",
            "-c:a",
            "aac",
            "-b:a",
            "192k",
            "-t",
            f"{duration:.9f}",
            "-movflags",
            "+faststart",
            str(output),
        ]
    )
    run(command)


def probe_video(video: Path) -> dict[str, Any]:
    ffprobe = require_tool("ffprobe")
    if not video.expanduser().is_file():
        raise TimelineError(f"Video does not exist: {video}")
    result = run(
        [
            ffprobe,
            "-v",
            "error",
            "-count_frames",
            "-show_entries",
            "stream=index,codec_type,codec_name,width,height,avg_frame_rate,r_frame_rate,"
            "nb_read_frames,duration,sample_rate,channels",
            "-show_entries",
            "format=duration,size",
            "-of",
            "json",
            str(video.expanduser().resolve()),
        ],
        capture=True,
    )
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise TimelineError("ffprobe returned invalid JSON") from exc


def rate_as_float(value: str) -> float:
    try:
        numerator, denominator = value.split("/", 1)
        return float(numerator) / float(denominator)
    except (AttributeError, ValueError, ZeroDivisionError):
        return 0.0


def command_init(args: argparse.Namespace) -> int:
    width, height = args.size
    if width % 2 or height % 2:
        raise TimelineError("Video width and height must be even")
    if not 1 <= args.fps <= 120:
        raise TimelineError("fps must be from 1 to 120")
    if args.shots < 1:
        raise TimelineError("shots must be at least 1")
    if args.shot_duration <= 0:
        raise TimelineError("shot-duration must be positive")
    frames_per_shot = frame_count(args.shot_duration, args.fps)
    if frames_per_shot < 2:
        raise TimelineError("shot-duration must contain at least 2 frames")
    if not args.title.strip():
        raise TimelineError("title must not be empty")
    transition_frames = min(max(1, frame_count(0.5, args.fps)), frames_per_shot - 1)
    transition_duration = transition_frames / args.fps

    project = args.project_dir.expanduser().resolve()
    manifest = project / "timeline.json"
    if manifest.exists():
        raise TimelineError(f"Refusing to replace existing timeline: {manifest}")
    project.mkdir(parents=True, exist_ok=True)
    for directory in ("keyframes", "audio", "output"):
        (project / directory).mkdir(exist_ok=True)

    shots: list[dict[str, Any]] = []
    for index in range(args.shots):
        shot_number = index + 1
        shot_id = f"shot-{shot_number:03d}"
        shot: dict[str, Any] = {
            "id": shot_id,
            "duration": args.shot_duration,
            "start_image": f"keyframes/{shot_id}-start.png",
            "end_image": f"keyframes/{shot_id}-end.png",
            "interpolation": "optical-flow",
            "motion": "static",
            "transition_to_next": {
                "type": "fade" if index < args.shots - 1 else "cut",
                "duration": transition_duration if index < args.shots - 1 else 0,
            },
            "prompt": f"Describe the composition and action for {shot_id}",
            "continuity": "Repeat unchanged identity, wardrobe, palette, lens, lighting, and aspect ratio",
        }
        shots.append(shot)

    payload = {
        "version": SCHEMA_VERSION,
        "title": args.title,
        "fps": args.fps,
        "width": width,
        "height": height,
        "shots": shots,
    }
    manifest.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Created {manifest}")
    print("Generate the referenced keyframes, then run the validate command.")
    return 0


def command_validate(args: argparse.Namespace) -> int:
    data, warnings = load_and_validate(
        args.manifest,
        require_files=not args.allow_missing,
        probe_files=not args.skip_probe and not args.allow_missing,
    )
    for warning in warnings:
        eprint(f"WARNING: {warning}")
    total_frames = total_output_frames(data)
    print(
        json.dumps(
            {
                "status": "valid",
                "shots": len(data["shots"]),
                "fps": data["fps"],
                "width": data["width"],
                "height": data["height"],
                "output_frames": total_frames,
                "output_duration": total_frames / data["fps"],
                "warnings": len(warnings),
            },
            indent=2,
        )
    )
    return 0


def command_render(args: argparse.Namespace) -> int:
    ffmpeg = require_tool("ffmpeg")
    require_tool("ffprobe")
    data, warnings = load_and_validate(args.manifest, require_files=True, probe_files=True)
    for warning in warnings:
        eprint(f"WARNING: {warning}")

    manifest_path = args.manifest.expanduser().resolve()
    manifest_dir = manifest_path.parent
    slug = re.sub(r"[^A-Za-z0-9._-]+", "-", data["title"].strip()).strip("-.") or "video"
    output = (args.output or (manifest_dir / "output" / f"{slug}.mp4")).expanduser().resolve()
    if output.exists() and not args.force:
        raise TimelineError(f"Output exists; pass --force to replace it: {output}")
    output.parent.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix="timeline-video-") as temp_name:
        work_dir = Path(temp_name)
        clips: list[Path] = []
        methods: dict[str, str] = {}
        for index, shot in enumerate(data["shots"]):
            clip = work_dir / f"shot-{index:04d}.mp4"
            print(f"Rendering {shot['id']} ({index + 1}/{len(data['shots'])})")
            methods[shot["id"]] = render_shot(
                data,
                shot,
                manifest_dir,
                clip,
                work_dir,
                ffmpeg=ffmpeg,
                interpolation_override=args.interpolation,
                strict=args.strict,
                preset=args.preset,
                crf=args.crf,
            )
            clips.append(clip)

        assembled = work_dir / "assembled.mp4"
        total_frames = assemble_shots(
            ffmpeg,
            data,
            clips,
            assembled,
            preset=args.preset,
            crf=args.crf,
        )
        final_temp = assembled
        if data.get("audio"):
            final_temp = work_dir / "with-audio.mp4"
            mux_audio(ffmpeg, data, manifest_dir, assembled, final_temp, total_frames)
        shutil.copyfile(final_temp, output)

    probe = probe_video(output)
    streams = probe.get("streams") or []
    stream = next((item for item in streams if item.get("codec_type") == "video"), {})
    actual_frames = int(stream.get("nb_read_frames", -1))
    actual_rate = rate_as_float(stream.get("avg_frame_rate", "0/1"))
    if actual_frames != total_frames:
        raise TimelineError(f"Rendered frame count {actual_frames} does not match expected {total_frames}")
    if abs(actual_rate - int(data["fps"])) > 1e-6:
        raise TimelineError(f"Rendered frame rate {actual_rate} does not match expected {data['fps']}")

    print(
        json.dumps(
            {
                "status": "rendered",
                "output": str(output),
                "frames": total_frames,
                "fps": data["fps"],
                "duration": total_frames / data["fps"],
                "interpolation_used": methods,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


def command_probe(args: argparse.Namespace) -> int:
    payload = probe_video(args.video)
    failures: list[str] = []
    if args.manifest:
        data, warnings = load_and_validate(args.manifest, require_files=False, probe_files=False)
        for warning in warnings:
            eprint(f"WARNING: {warning}")
        streams = payload.get("streams") or []
        video_stream = next((item for item in streams if item.get("codec_type") == "video"), None)
        if video_stream is None:
            failures.append("video stream is missing")
        else:
            if int(video_stream.get("width", -1)) != int(data["width"]):
                failures.append("width does not match manifest")
            if int(video_stream.get("height", -1)) != int(data["height"]):
                failures.append("height does not match manifest")
            if int(video_stream.get("nb_read_frames", -1)) != total_output_frames(data):
                failures.append("frame count does not match manifest")
            if abs(rate_as_float(video_stream.get("avg_frame_rate", "0/1")) - int(data["fps"])) > 1e-6:
                failures.append("frame rate does not match manifest")
        if data.get("audio") and not any(item.get("codec_type") == "audio" for item in streams):
            failures.append("audio stream declared by manifest is missing")
        payload["manifest_check"] = "passed" if not failures else {"failed": failures}
    print(json.dumps(payload, indent=2))
    return 1 if failures else 0


def parse_size(value: str) -> tuple[int, int]:
    match = re.fullmatch(r"([1-9][0-9]*)x([1-9][0-9]*)", value)
    if not match:
        raise argparse.ArgumentTypeError("size must look like 1280x720")
    return int(match.group(1)), int(match.group(2))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    init_parser = subparsers.add_parser("init", help="Create a project skeleton and timeline.json")
    init_parser.add_argument("project_dir", type=Path)
    init_parser.add_argument("--title", default="Timeline video")
    init_parser.add_argument("--shots", type=int, default=3)
    init_parser.add_argument("--shot-duration", type=float, default=3.0)
    init_parser.add_argument("--size", type=parse_size, default=(1280, 720), metavar="WIDTHxHEIGHT")
    init_parser.add_argument("--fps", type=int, default=24)
    init_parser.set_defaults(handler=command_init)

    validate_parser = subparsers.add_parser("validate", help="Validate a timeline and its media")
    validate_parser.add_argument("manifest", type=Path)
    validate_parser.add_argument("--allow-missing", action="store_true", help="Validate structure before keyframes exist")
    validate_parser.add_argument("--skip-probe", action="store_true", help="Do not inspect media with ffprobe")
    validate_parser.set_defaults(handler=command_validate)

    render_parser = subparsers.add_parser("render", help="Render and verify an MP4")
    render_parser.add_argument("manifest", type=Path)
    render_parser.add_argument("--output", type=Path)
    render_parser.add_argument("--interpolation", choices=sorted(INTERPOLATIONS), help="Override every shot")
    render_parser.add_argument("--preset", default="medium", choices=["ultrafast", "veryfast", "fast", "medium", "slow"])
    render_parser.add_argument("--crf", type=int, default=18, choices=range(0, 52), metavar="0-51")
    render_parser.add_argument("--strict", action="store_true", help="Fail instead of falling back from optical flow")
    render_parser.add_argument("--force", action="store_true", help="Replace an existing output file")
    render_parser.set_defaults(handler=command_render)

    probe_parser = subparsers.add_parser("probe", help="Inspect a video and optionally compare it to a manifest")
    probe_parser.add_argument("video", type=Path)
    probe_parser.add_argument("--manifest", type=Path)
    probe_parser.set_defaults(handler=command_probe)
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    try:
        return int(args.handler(args))
    except TimelineError as exc:
        eprint(f"ERROR: {exc}")
        return 2
    except subprocess.CalledProcessError as exc:
        eprint(f"ERROR: command failed with exit code {exc.returncode}")
        return exc.returncode or 1
    except KeyboardInterrupt:
        eprint("Interrupted")
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
