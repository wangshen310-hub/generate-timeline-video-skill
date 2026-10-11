#!/usr/bin/env python3
"""Render a JSON timeline of still-image keyframes into an exact-fps MP4.

Requires ffmpeg and ffprobe. Uses only Python's standard library.
"""

from __future__ import annotations

import argparse
from contextlib import contextmanager
from contextvars import ContextVar
import hashlib
import html
import json
import math
import os
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any


SCHEMA_VERSION = 1
INTERPOLATIONS = {"hold", "blend", "optical-flow", "rife"}
RIFE_STRATEGIES = {"direct", "recursive"}
OPTICAL_FLOW_PROFILES = {
    "balanced": (
        "mi_mode=mci:mc_mode=aobmc:me_mode=bidir:me=epzs:"
        "mb_size=16:search_param=32:vsbmc=1:scd=none"
    ),
    "large-motion": (
        "mi_mode=mci:mc_mode=aobmc:me_mode=bidir:me=umh:"
        "mb_size=8:search_param=128:vsbmc=1:scd=none"
    ),
}
MOTIONS = {
    "static",
    "zoom-in",
    "zoom-out",
    "pan-left",
    "pan-right",
    "pan-up",
    "pan-down",
}
SUBJECT_MOTION_DEFAULT_GAPS = {
    "none": None,
    "slow": 1.0,
    "articulated": 0.25,
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
    print(message, file=sys.stderr, flush=True)


def require_tool(name: str) -> str:
    executable = shutil.which(name)
    if not executable:
        raise TimelineError(f"Required executable not found on PATH: {name}")
    return executable


_command_timeout: ContextVar[float] = ContextVar("command_timeout", default=300.0)


def run(
    command: list[str],
    *,
    capture: bool = False,
    cwd: Path | None = None,
) -> subprocess.CompletedProcess[str]:
    eprint(f"+ {shlex.join(command)}")
    try:
        return subprocess.run(
            command, check=True, text=True, cwd=cwd,
            stdout=subprocess.PIPE if capture else sys.stderr,
            stderr=subprocess.PIPE if capture else None,
            timeout=_command_timeout.get(),
        )
    except subprocess.TimeoutExpired as exc:
        raise TimelineError(f"Command timed out after {_command_timeout.get():g}s: {command[0]}") from exc


def is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def frame_count(seconds: float, fps: int) -> int:
    return int(math.floor(seconds * fps + 0.5))


def resolve_media(base: Path, value: str) -> Path:
    path = Path(value).expanduser()
    return path if path.is_absolute() else (base / path).resolve()


def file_digest(path: Path) -> bytes:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.digest()


def media_files_match(first: Path, second: Path) -> bool:
    """Return whether two media paths contain exactly the same bytes."""
    try:
        if first.samefile(second):
            return True
    except (FileNotFoundError, OSError):
        pass
    if not first.is_file() or not second.is_file():
        return False
    if first.stat().st_size != second.stat().st_size:
        return False
    return file_digest(first) == file_digest(second)


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

def intermediate_keyframes_for(shot: dict[str, Any]) -> list[tuple[str, float | None]]:
    values = shot.get("intermediate_images", [])
    if not isinstance(values, list):
        return []
    keyframes: list[tuple[str, float | None]] = []
    for value in values:
        if isinstance(value, str):
            keyframes.append((value, None))
        elif isinstance(value, dict) and isinstance(value.get("image"), str):
            at = value.get("at")
            keyframes.append((value["image"], float(at) if is_number(at) else None))
    return keyframes


def intermediate_images_for(shot: dict[str, Any]) -> list[str]:
    return [image for image, _ in intermediate_keyframes_for(shot)]


def intermediate_keyframes_are_timed(shot: dict[str, Any]) -> bool:
    keyframes = intermediate_keyframes_for(shot)
    return bool(keyframes) and all(at is not None for _, at in keyframes)


def keyframe_sequence_for(shot: dict[str, Any]) -> list[tuple[str, float]]:
    end_image = shot.get("end_image")
    duration = shot.get("duration")
    if not isinstance(shot.get("start_image"), str) or not isinstance(end_image, str):
        raise TimelineError(f"Shot {shot.get('id', '<unknown>')} needs start_image and end_image")
    if not is_number(duration) or duration <= 0:
        raise TimelineError(f"Shot {shot.get('id', '<unknown>')} needs a positive duration")

    intermediates = intermediate_keyframes_for(shot)
    if any(at is not None for _, at in intermediates) and not all(
        at is not None for _, at in intermediates
    ):
        raise TimelineError("intermediate_images cannot mix timed objects and path strings")
    if intermediates and all(at is not None for _, at in intermediates):
        times = [float(at) for _, at in intermediates if at is not None]
    else:
        divisor = len(intermediates) + 1
        times = [float(duration) * (index + 1) / divisor for index in range(len(intermediates))]
    return [
        (shot["start_image"], 0.0),
        *((image, at) for (image, _), at in zip(intermediates, times)),
        (end_image, float(duration)),
    ]


def subject_motion_for(shot: dict[str, Any]) -> str:
    return str(shot.get("subject_motion", "none"))


def max_keyframe_gap_for(shot: dict[str, Any], override: float | None = None) -> float | None:
    if override is not None:
        return float(override)
    value = shot.get("max_keyframe_gap")
    if is_number(value):
        return float(value)
    return SUBJECT_MOTION_DEFAULT_GAPS.get(subject_motion_for(shot))


def motion_for(shot: dict[str, Any]) -> str:
    return str(shot.get("motion", "static"))


def optical_flow_profile_for(shot: dict[str, Any], override: str | None = None) -> str:
    return str(override or shot.get("optical_flow_profile", "balanced"))


def rife_strategy_for(shot: dict[str, Any], override: str | None = None) -> str:
    return str(override or shot.get("rife_strategy", "recursive"))


def shared_cut_boundaries(
    data: dict[str, Any],
    manifest_dir: Path,
    interpolation_override: str | None = None,
) -> set[int]:
    """Find cut boundaries whose active endpoint images are byte-identical.

    The returned indices identify shots whose final interpolation sample should
    be excluded. The following shot supplies that exact boundary frame, which
    preserves the declared total frame count without a one-frame freeze.
    """
    matches: set[int] = set()
    shots = data["shots"]
    for index, shot in enumerate(shots[:-1]):
        transition_type, _ = transition_for(shot)
        interpolation = interpolation_override or interpolation_for(shot)
        end_value = shot.get("end_image")
        next_value = shots[index + 1].get("start_image")
        if (
            transition_type != "cut"
            or interpolation == "hold"
            or not isinstance(end_value, str)
            or not isinstance(next_value, str)
        ):
            continue
        first = resolve_media(manifest_dir, end_value)
        second = resolve_media(manifest_dir, next_value)
        if media_files_match(first, second):
            matches.add(index)
    return matches


def referenced_media_paths(data: dict[str, Any], manifest_dir: Path) -> set[Path]:
    """Return all source media paths referenced by a validated timeline."""
    paths: set[Path] = set()
    for shot in data["shots"]:
        for field in ("start_image", "end_image"):
            value = shot.get(field)
            if isinstance(value, str):
                paths.add(resolve_media(manifest_dir, value))
        for value in intermediate_images_for(shot):
            if isinstance(value, str):
                paths.add(resolve_media(manifest_dir, value))
    audio = data.get("audio")
    if isinstance(audio, dict) and isinstance(audio.get("file"), str):
        paths.add(resolve_media(manifest_dir, audio["file"]))
    return paths


def motion_plan_errors(shot: dict[str, Any]) -> list[str]:
    plan = shot.get("motion_plan")
    if plan is None:
        return []
    if not isinstance(plan, list) or not plan:
        return ["motion_plan must be a non-empty array"]
    errors = []
    for index, entry in enumerate(plan):
        prefix = f"motion_plan[{index}]"
        if not isinstance(entry, dict):
            errors.append(f"{prefix} must be an object")
            continue
        if not is_number(entry.get("at")) or not 0 <= entry["at"] <= float(shot["duration"]):
            errors.append(f"{prefix}.at must be within the shot")
        for field in ("image", "reference_image"):
            if not isinstance(entry.get(field), str) or not entry[field].strip():
                errors.append(f"{prefix}.{field} must be a non-empty path")
        if entry.get("review") not in {"pending", "pass", "revise"}:
            errors.append(f"{prefix}.review must be pending, pass or revise")
        keep = entry.get("keep")
        if not isinstance(keep, list) or not all(isinstance(v, str) and v.strip() for v in keep):
            errors.append(f"{prefix}.keep must be an array of non-empty strings")
        changes = entry.get("changes")
        if not isinstance(changes, list) or not all(
            isinstance(v, dict) and all(isinstance(v.get(k), str) and v[k].strip() for k in ("target", "state"))
            for v in changes
        ):
            errors.append(f"{prefix}.changes needs target/state objects (empty is allowed for a hold)")
    if not errors:
        expected = ([(shot["start_image"], 0.0)] if interpolation_for(shot) == "hold" else keyframe_sequence_for(shot))
        if [(e["image"], e["at"]) for e in plan] != expected:
            errors.append("motion_plan must match the ordered image/time slots in the timeline")
    return errors


def shot_timing(shot: dict[str, Any], fps: int, include_endpoint: bool = True) -> list[dict[str, Any]]:
    if interpolation_for(shot) == "hold":
        return [{"image": shot["start_image"], "declared_at": 0, "frame": 0, "actual_at": 0, "error_seconds": 0}]
    sequence = keyframe_sequence_for(shot)
    frames = frame_count(float(shot["duration"]), fps)
    total = frames - 1 if include_endpoint else frames
    minimum = 1 if include_endpoint else 2
    intervals = (distribute_timed_intervals(total, [at for _, at in sequence], float(shot["duration"]),
                                           last_minimum=minimum, fps=fps)
                 if intermediate_keyframes_are_timed(shot)
                 else distribute_intervals(total, len(sequence) - 1, last_minimum=minimum))
    position = 0
    result = []
    for index, (image, at) in enumerate(sequence):
        if index:
            position += intervals[index - 1]
        result.append({"image": image, "declared_at": at, "frame": position,
                       "actual_at": position / fps, "error_seconds": position / fps - at,
                       "endpoint": index == len(sequence) - 1})
    return result


def load_and_validate(
    manifest_path: Path,
    *,
    require_files: bool = True,
    probe_files: bool = False,
    interpolation_override: str | None = None,
    validate_motion: bool = True,
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

    if type(data.get("version")) is not int or data.get("version") != SCHEMA_VERSION:
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

        interpolation = interpolation_override or interpolation_for(shot)
        end_image = shot.get("end_image") if interpolation != "hold" else None
        if end_image is not None and (not isinstance(end_image, str) or not end_image.strip()):
            errors.append(f"{prefix}.end_image must be a non-empty path when present")
        elif isinstance(end_image, str):
            path = resolve_media(base, end_image)
            if require_files and not path.is_file():
                errors.append(f"{prefix}.end_image does not exist: {path}")
            elif path.is_file():
                expect_stream(path, "video")
        intermediate_images = shot.get("intermediate_images", []) if interpolation != "hold" else []
        intermediate_valid = True
        intermediate_formats: set[str] = set()
        timed_intermediate_times: list[float] = []
        if not isinstance(intermediate_images, list):
            errors.append(f"{prefix}.intermediate_images must be an array when present")
            intermediate_images = []
            intermediate_valid = False

        keyframe_paths: list[tuple[str, Path]] = []
        if isinstance(start_image, str) and start_image.strip():
            keyframe_paths.append(("start_image", resolve_media(base, start_image)))
        for keyframe_index, value in enumerate(intermediate_images):
            image_value: str | None = None
            if isinstance(value, str):
                intermediate_formats.add("path")
                image_value = value
            elif isinstance(value, dict):
                intermediate_formats.add("timed")
                image_value = value.get("image")
                at = value.get("at")
                if not is_number(at):
                    errors.append(
                        f"{prefix}.intermediate_images[{keyframe_index}].at must be a finite number"
                    )
                    intermediate_valid = False
                elif not is_number(duration) or not 0 < float(at) < float(duration):
                    errors.append(
                        f"{prefix}.intermediate_images[{keyframe_index}].at must be inside the shot"
                    )
                    intermediate_valid = False
                else:
                    timed_intermediate_times.append(float(at))
            else:
                errors.append(
                    f"{prefix}.intermediate_images[{keyframe_index}] must be a path string "
                    "or an object with image and at"
                )
                intermediate_valid = False
                continue

            if not isinstance(image_value, str) or not image_value.strip():
                errors.append(
                    f"{prefix}.intermediate_images[{keyframe_index}] needs a non-empty image path"
                )
                intermediate_valid = False
                continue
            path = resolve_media(base, image_value)
            keyframe_paths.append((f"intermediate_images[{keyframe_index}]", path))
            if require_files and not path.is_file():
                errors.append(
                    f"{prefix}.intermediate_images[{keyframe_index}] does not exist: {path}"
                )
            elif path.is_file():
                expect_stream(path, "video")

        if len(intermediate_formats) > 1:
            errors.append(
                f"{prefix}.intermediate_images cannot mix path strings and timed objects"
            )
            intermediate_valid = False
        if timed_intermediate_times != sorted(timed_intermediate_times) or len(
            timed_intermediate_times
        ) != len(set(timed_intermediate_times)):
            errors.append(f"{prefix}.intermediate_images at values must be strictly increasing")
            intermediate_valid = False
        if isinstance(end_image, str) and end_image.strip():
            keyframe_paths.append(("end_image", resolve_media(base, end_image)))

        if interpolation not in INTERPOLATIONS:
            errors.append(f"{prefix}.interpolation must be one of {sorted(INTERPOLATIONS)}")
        elif interpolation != "hold" and not isinstance(end_image, str):
            errors.append(f"{prefix}.end_image is required for {interpolation}")
        elif interpolation == "hold" and shot.get("intermediate_images"):
            warnings.append(f"{prefix}.intermediate_images is ignored because interpolation is hold")
        elif interpolation == "hold" and shot.get("end_image"):
            warnings.append(f"{prefix}.end_image is ignored because interpolation is hold")
        elif (
            interpolation in {"optical-flow", "rife"}
            and is_number(duration)
            and duration > 1.0
            and not intermediate_images
            and shot.get("subject_motion") is None
            and shot.get("max_keyframe_gap") is None
        ):
            warnings.append(
                f"{prefix} spans {float(duration):.3f}s with only two keyframes; "
                "large or articulated motion needs intermediate_images with distinct poses; add additional keyframes"
            )

        if interpolation != "hold" and intermediate_valid and intermediate_images:
            if len(intermediate_images) + 2 > frames:
                errors.append(f"{prefix} keyframes exceed the frame budget ({frames} frames)")
            elif frames >= 2 and isinstance(end_image, str) and is_number(duration) and duration > 0:
                try:
                    if intermediate_keyframes_are_timed(shot):
                        shot_timing(shot, fps)
                except TimelineError as exc:
                    errors.append(f"{prefix}: {exc}")

        if validate_motion and intermediate_valid and is_number(duration) and duration > 0 and isinstance(start_image, str):
            try:
                plan_shot = dict(shot, interpolation=interpolation)
                if interpolation == "hold" and interpolation_override == "hold":
                    plan_shot.pop("motion_plan", None)
                plan_errors = motion_plan_errors(plan_shot)
                errors.extend(f"{prefix}.{error}" for error in plan_errors)
                if not plan_errors and any(e.get("review") != "pass" for e in plan_shot.get("motion_plan", [])):
                    warnings.append(f"{prefix}.motion_plan still needs visual review; technical validation is not approval")
            except (TimelineError, KeyError, TypeError, ValueError):
                errors.append(f"{prefix}.motion_plan cannot be matched to invalid keyframe slots")

        if interpolation in {"optical-flow", "rife"}:
            for (first_label, first_path), (second_label, second_path) in zip(
                keyframe_paths, keyframe_paths[1:]
            ):
                if first_path.is_file() and second_path.is_file() and media_files_match(
                    first_path, second_path
                ):
                    warnings.append(
                        f"{prefix} {first_label} and {second_label} are byte-identical; "
                        "interpolation cannot create new motion between them"
                    )

        subject_motion = subject_motion_for(shot)
        if subject_motion not in SUBJECT_MOTION_DEFAULT_GAPS:
            errors.append(
                f"{prefix}.subject_motion must be one of {sorted(SUBJECT_MOTION_DEFAULT_GAPS)}"
            )
        gap_value = shot.get("max_keyframe_gap")
        if gap_value is not None and (not is_number(gap_value) or gap_value <= 0):
            errors.append(f"{prefix}.max_keyframe_gap must be a positive finite number")
        gap_limit = max_keyframe_gap_for(shot) if subject_motion in SUBJECT_MOTION_DEFAULT_GAPS else None
        if (
            interpolation in {"optical-flow", "rife"}
            and intermediate_valid
            and isinstance(start_image, str)
            and isinstance(end_image, str)
            and is_number(duration)
            and gap_limit is not None
            and gap_limit > 0
        ):
            sequence = keyframe_sequence_for(shot)
            actual_max_gap = max(
                right_at - left_at
                for (_, left_at), (_, right_at) in zip(sequence, sequence[1:])
            )
            if actual_max_gap > gap_limit + 1e-9:
                warnings.append(
                    f"{prefix} maximum keyframe gap is {actual_max_gap:.3f}s, "
                    f"above the {gap_limit:.3f}s motion limit; run plan-keyframes"
                )

        optical_flow_profile = optical_flow_profile_for(shot)
        if optical_flow_profile not in OPTICAL_FLOW_PROFILES:
            errors.append(
                f"{prefix}.optical_flow_profile must be one of {sorted(OPTICAL_FLOW_PROFILES)}"
            )

        rife_strategy = rife_strategy_for(shot)
        if rife_strategy not in RIFE_STRATEGIES:
            errors.append(f"{prefix}.rife_strategy must be one of {sorted(RIFE_STRATEGIES)}")

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

    if require_files and not errors:
        for index in sorted(shared_cut_boundaries(data, base)):
            warnings.append(
                f"shots[{index}] end_image matches shots[{index + 1}].start_image; "
                "render will de-duplicate the shared cut boundary"
            )

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


_image_cache: ContextVar[tuple[Path, dict] | None] = ContextVar("image_cache", default=None)
_segment_cache: ContextVar[tuple[Path, str, list] | None] = ContextVar("segment_cache", default=None)


@contextmanager
def render_context(cache_dir: Path | None, ffmpeg: str, rife_runtime, timeout: float):
    if not math.isfinite(timeout) or timeout <= 0:
        raise TimelineError("command-timeout must be a positive finite number")
    timeout_token = _command_timeout.set(timeout)
    token = None
    events: list[dict] = []
    try:
        if cache_dir is not None:
            directory = cache_dir.expanduser().resolve()
            directory.mkdir(parents=True, exist_ok=True)
            files = [Path(__file__), Path(ffmpeg), Path(require_tool("ffprobe"))]
            if rife_runtime:
                files.extend([rife_runtime[0], rife_runtime[1] / "flownet.param", rife_runtime[1] / "flownet.bin"])
            runtime_key = hashlib.sha256(b"".join(file_digest(p) for p in files)).hexdigest()
            token = _segment_cache.set((directory, runtime_key, events))
        yield events
    finally:
        if token is not None:
            _segment_cache.reset(token)
        _command_timeout.reset(timeout_token)


@contextmanager
def normalization_cache(directory: Path):
    """Scope cached normalized images to exactly one render, including fallbacks."""
    directory.mkdir()
    token = _image_cache.set((directory, {}))
    try:
        yield
    finally:
        _image_cache.reset(token)


def link_or_copy(source: Path, target: Path) -> None:
    try:
        os.link(source, target)
    except OSError:
        shutil.copyfile(source, target)


def normalize_image(ffmpeg: str, source: Path, target: Path, width: int, height: int) -> None:
    cache = _image_cache.get()
    if cache is not None:
        directory, images = cache
        key = (source.resolve(), width, height)
        if key not in images:
            cached = directory / f"image-{len(images):06d}.png"
            # The uncached operation cannot recursively enter the cache.
            token = _image_cache.set(None)
            try:
                normalize_image(ffmpeg, source, cached, width, height)
            finally:
                _image_cache.reset(token)
            images[key] = cached
        link_or_copy(images[key], target)
        return
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
    include_endpoint: bool,
    motion: str,
    preset: str,
    crf: int,
) -> None:
    first = motion_filter(motion, width, height, frames, fps)
    second = motion_filter(motion, width, height, frames, fps)
    denominator = max(frames - 1 if include_endpoint else frames, 1)
    graph = (
        f"[0:v]{first},fps={fps},trim=end_frame={frames},setpts=PTS-STARTPTS[a];"
        f"[1:v]{second},fps={fps},trim=end_frame={frames},setpts=PTS-STARTPTS[b];"
        f"[a][b]blend=all_expr='A*(1-(N-1)/{denominator})+B*(N-1)/{denominator}':shortest=1,"
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
    include_endpoint: bool,
    profile: str,
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
    link_or_copy(second, third)

    denominator = max(frames - 1 if include_endpoint else frames, 1)
    input_rate = f"{fps}/{denominator}"
    post_motion = motion_filter(motion, width, height, frames, fps, normalized=True)
    video_filter = (
        f"minterpolate=fps={fps}:{OPTICAL_FLOW_PROFILES[profile]},"
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


def resolve_rife_runtime(
    executable_value: Path | None,
    model_value: Path | None,
) -> tuple[Path, Path]:
    if executable_value is not None:
        executable = executable_value.expanduser().resolve()
        if not executable.is_file():
            raise TimelineError(f"RIFE executable does not exist: {executable}")
        if not os.access(executable, os.X_OK):
            raise TimelineError(f"RIFE executable is not executable: {executable}")
    else:
        discovered = shutil.which("rife-ncnn-vulkan") or shutil.which("rife-ncnn-vulkan.exe")
        if not discovered:
            raise TimelineError(
                "RIFE interpolation requires rife-ncnn-vulkan. "
                "Pass --rife-executable and --rife-model, or choose optical-flow."
            )
        executable = Path(discovered).resolve()

    if model_value is not None:
        model = model_value.expanduser().resolve()
    else:
        candidates = (
            executable.parent / "rife-v4.6",
            executable.parent / "models" / "rife-v4.6",
            executable.parent / "rife-v4",
            executable.parent / "models" / "rife-v4",
        )
        model = next((candidate for candidate in candidates if candidate.is_dir()), candidates[0])

    if not model.is_dir():
        raise TimelineError(
            f"RIFE v4 model directory does not exist: {model}. "
            "Pass --rife-model with a rife-v4 or rife-v4.6 directory."
        )
    if "rife-v4" not in model.name.lower():
        raise TimelineError("RIFE integration requires a rife-v4 model directory")
    required_model_files = ("flownet.param", "flownet.bin")
    missing_files = [name for name in required_model_files if not (model / name).is_file()]
    if missing_files:
        raise TimelineError(
            f"RIFE model directory is incomplete; missing {', '.join(missing_files)}: {model}"
        )
    return executable, model


def rife_command(
    executable: Path,
    model: Path,
    start_image: Path,
    end_image: Path,
    output: Path,
    timestep: float,
    gpu: int | None,
) -> list[str]:
    command = [
        str(executable),
        "-0",
        str(start_image),
        "-1",
        str(end_image),
        "-o",
        str(output),
        "-s",
        f"{timestep:.9f}",
        "-m",
        str(model),
    ]
    if gpu is not None:
        command.extend(["-g", str(gpu)])
    return command


def recursive_interval_count(denominator: int) -> int:
    """Return the smallest power-of-two interval count covering a shot."""
    return 1 << max(0, (denominator - 1).bit_length())


def render_rife(
    ffmpeg: str,
    rife_executable: Path,
    rife_model: Path,
    rife_gpu: int | None,
    start_image: Path,
    end_image: Path,
    output: Path,
    work_dir: Path,
    *,
    width: int,
    height: int,
    fps: int,
    frames: int,
    include_endpoint: bool,
    strategy: str,
    motion: str,
    preset: str,
    crf: int,
) -> None:
    if strategy not in RIFE_STRATEGIES:
        raise TimelineError(f"Unknown RIFE strategy: {strategy}")

    pair_dir = work_dir / f"rife-{output.stem}"
    pair_dir.mkdir(parents=True, exist_ok=False)
    first = pair_dir / "start.png"
    second = pair_dir / "end.png"
    sequence = pair_dir / "frames"
    sequence.mkdir()
    normalize_image(ffmpeg, start_image, first, width, height)
    normalize_image(ffmpeg, end_image, second, width, height)

    denominator = max(frames - 1 if include_endpoint else frames, 1)
    if strategy == "direct":
        link_or_copy(first, sequence / "frame000000.png")
        for index in range(1, frames):
            target = sequence / f"frame{index:06d}.png"
            if include_endpoint and index == frames - 1:
                link_or_copy(second, target)
                continue
            run(
                rife_command(
                    rife_executable,
                    rife_model,
                    first,
                    second,
                    target,
                    index / denominator,
                    rife_gpu,
                ),
                cwd=rife_executable.parent,
            )
        input_rate = str(fps)
    else:
        intervals = recursive_interval_count(denominator)
        grid = pair_dir / "midpoints"
        grid.mkdir()
        first_frame = grid / "frame000000.png"
        last_frame = grid / f"frame{intervals:06d}.png"
        link_or_copy(first, first_frame)
        link_or_copy(second, last_frame)

        def fill_midpoints(
            left_index: int,
            right_index: int,
            left_frame: Path,
            right_frame: Path,
        ) -> None:
            if right_index - left_index <= 1:
                return
            middle_index = (left_index + right_index) // 2
            middle_frame = grid / f"frame{middle_index:06d}.png"
            run(
                rife_command(
                    rife_executable,
                    rife_model,
                    left_frame,
                    right_frame,
                    middle_frame,
                    0.5,
                    rife_gpu,
                ),
                cwd=rife_executable.parent,
            )
            fill_midpoints(left_index, middle_index, left_frame, middle_frame)
            fill_midpoints(middle_index, right_index, middle_frame, right_frame)

        fill_midpoints(0, intervals, first_frame, last_frame)
        for index in range(frames):
            left, remainder = divmod(index * intervals, denominator)
            target = sequence / f"frame{index:06d}.png"
            left_frame = grid / f"frame{left:06d}.png"
            if remainder == 0:
                link_or_copy(left_frame, target)
            else:
                # Evaluate the requested time within its narrow midpoint bracket.
                # FFmpeg framerate would blend pixels here and reintroduce ghosts.
                run(rife_command(rife_executable, rife_model, left_frame,
                                 grid / f"frame{left + 1:06d}.png", target,
                                 remainder / denominator, rife_gpu),
                    cwd=rife_executable.parent)
        input_rate = str(fps)

    post_motion = motion_filter(motion, width, height, frames, fps, normalized=True)
    video_filters = [post_motion] if post_motion else []
    video_filters.extend([f"fps={fps}", "format=yuv420p"])
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
            str(sequence / "frame%06d.png"),
            "-vf",
            ",".join(video_filters),
            "-frames:v",
            str(frames),
            "-r",
            str(fps),
            *encoding_args(preset, crf),
            str(output),
        ]
    )


def render_shot_pair(
    data: dict[str, Any], shot: dict[str, Any], manifest_dir: Path,
    output: Path, work_dir: Path, **settings: Any,
) -> str:
    cache = _segment_cache.get()
    eprint(f"Rendering pair {shot['id']}")
    if cache is None:
        return render_shot_pair_uncached(data, shot, manifest_dir, output, work_dir, **settings)
    directory, runtime_key, events = cache
    effective = settings.get("interpolation_override") or interpolation_for(shot)
    images = [resolve_media(manifest_dir, shot["start_image"])]
    if effective != "hold":
        images.append(resolve_media(manifest_dir, shot["end_image"]))
    payload = {
        "runtime": runtime_key, "sources": [file_digest(p).hex() for p in images],
        "geometry": [data["width"], data["height"], data["fps"]],
        "frames": frame_count(float(shot["duration"]), int(data["fps"])),
        "motion": motion_for(shot), "interpolation": effective,
        "flow": optical_flow_profile_for(shot, settings.get("optical_flow_profile_override")),
        "rife_strategy": rife_strategy_for(shot, settings.get("rife_strategy_override")),
        "settings": {k: str(v) for k, v in settings.items()},
    }
    key = hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()
    video, metadata = directory / f"{key}.mp4", directory / f"{key}.json"
    try:
        record = json.loads(metadata.read_text(encoding="utf-8"))
        if record["digest"] == file_digest(video).hex() and record["key"] == key:
            link_or_copy(video, output)
            events.append({"pair": shot["id"], "cache": "hit", "key": key})
            eprint(f"Reusing pair {shot['id']}")
            return record["method"]
    except (OSError, ValueError, KeyError, TypeError):
        pass
    method = render_shot_pair_uncached(data, shot, manifest_dir, output, work_dir, **settings)
    events.append({"pair": shot["id"], "cache": "miss", "key": key})
    # Never let a degraded fallback mask recovery of the requested backend.
    if "fallback" not in method:
        probe = probe_video(output)
        expected = {"width": data["width"], "height": data["height"], "fps": data["fps"],
                    "shots": [{"duration": payload["frames"] / data["fps"]}]}
        failures = output_validation_failures(probe, expected)
        if failures:
            raise TimelineError("Invalid cache candidate: " + "; ".join(failures))
        run([settings["ffmpeg"], "-v", "error", "-xerror", "-i", str(output), "-f", "null", "-"])
        with tempfile.NamedTemporaryFile(dir=directory, suffix=".mp4", delete=False) as handle:
            temporary = Path(handle.name)
        try:
            shutil.copyfile(output, temporary)
            digest = file_digest(temporary).hex()
            os.replace(temporary, video)
            write_json_atomic(metadata, {"key": key, "digest": digest, "method": method})
        finally:
            temporary.unlink(missing_ok=True)
    return method


def render_shot_pair_uncached(
    data: dict[str, Any],
    shot: dict[str, Any],
    manifest_dir: Path,
    output: Path,
    work_dir: Path,
    *,
    ffmpeg: str,
    interpolation_override: str | None,
    optical_flow_profile_override: str | None,
    rife_strategy_override: str | None,
    include_endpoint: bool,
    rife_runtime: tuple[Path, Path] | None,
    rife_gpu: int | None,
    strict: bool,
    preset: str,
    crf: int,
) -> str:
    width = int(data["width"])
    height = int(data["height"])
    fps = int(data["fps"])
    frames = frame_count(float(shot["duration"]), fps)
    motion = motion_for(shot)
    optical_flow_profile = optical_flow_profile_for(shot, optical_flow_profile_override)
    rife_strategy = rife_strategy_for(shot, rife_strategy_override)
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
            include_endpoint=include_endpoint,
            motion=motion,
            preset=preset,
            crf=crf,
        )
        return "blend"

    rife_failed = False
    if interpolation == "rife":
        if rife_runtime is None:
            if strict:
                raise TimelineError("RIFE runtime was not resolved")
            rife_failed = True
        else:
            rife_executable, rife_model = rife_runtime
            try:
                render_rife(
                    ffmpeg,
                    rife_executable,
                    rife_model,
                    rife_gpu,
                    start_image,
                    end_image,
                    output,
                    work_dir,
                    width=width,
                    height=height,
                    fps=fps,
                    frames=frames,
                    include_endpoint=include_endpoint,
                    strategy=rife_strategy,
                    motion=motion,
                    preset=preset,
                    crf=crf,
                )
                return f"rife:{rife_strategy}"
            except subprocess.CalledProcessError:
                if strict:
                    raise
                rife_failed = True
                eprint(f"WARNING: RIFE failed for {shot['id']}; falling back to optical flow")

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
            include_endpoint=include_endpoint,
            profile=optical_flow_profile,
            motion=motion,
            preset=preset,
            crf=crf,
        )
        suffix = "-fallback" if rife_failed else ""
        return f"optical-flow:{optical_flow_profile}{suffix}"
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
            include_endpoint=include_endpoint,
            motion=motion,
            preset=preset,
            crf=crf,
        )
        return "blend-fallback-after-rife" if rife_failed else "blend-fallback"


def distribute_intervals(total: int, segments: int, last_minimum: int = 1) -> list[int]:
    if segments < 1 or total < segments - 1 + last_minimum:
        raise TimelineError(
            f"Cannot distribute {total} frame intervals across {segments} keyframe segments"
        )
    remaining = total - last_minimum
    base, remainder = divmod(remaining, segments)
    intervals = [base + (index < remainder) for index in range(segments)]
    intervals[-1] += last_minimum
    return intervals


def distribute_timed_intervals(
    total: int,
    times: list[float],
    duration: float,
    last_minimum: int = 1,
    fps: int | None = None,
) -> list[int]:
    """Map explicit keyframe times onto integer frame intervals."""
    segments = len(times) - 1
    if segments < 1 or duration <= 0:
        raise TimelineError("Timed keyframes need at least two points and a positive duration")
    if abs(times[0]) > 1e-9 or abs(times[-1] - duration) > 1e-9:
        raise TimelineError("Timed keyframes must begin at 0 and end at the shot duration")
    if any(right <= left for left, right in zip(times, times[1:])):
        raise TimelineError("Timed keyframes must be strictly increasing")

    minima = [1] * segments
    minima[-1] = last_minimum
    if total < sum(minima):
        raise TimelineError(
            f"Cannot distribute {total} frame intervals across {segments} timed keyframe segments"
        )

    boundaries = [0]
    for index, at in enumerate(times[1:-1], start=1):
        desired = int(math.floor(at * (fps if fps is not None else total / duration) + 0.5))
        minimum = boundaries[-1] + minima[index - 1]
        maximum = total - sum(minima[index:])
        if fps is not None and not minimum <= desired <= maximum:
            raise TimelineError(f"Keyframe at {at:g}s cannot occupy a distinct frame at {fps} fps; adjust timing or fps")
        boundaries.append(min(max(desired, minimum), maximum))
    boundaries.append(total)
    return [right - left for left, right in zip(boundaries, boundaries[1:])]


def concat_keyframe_segments(
    ffmpeg: str,
    clips: list[Path],
    output: Path,
    *,
    width: int,
    height: int,
    fps: int,
    frames: int,
    preset: str,
    crf: int,
    motion: str = "static",
) -> None:
    if len(clips) == 1:
        shutil.copyfile(clips[0], output)
        return

    command = [ffmpeg, "-hide_banner", "-loglevel", "error", "-y"]
    for clip in clips:
        command.extend(["-i", str(clip)])

    filters: list[str] = []
    for index in range(len(clips)):
        trim = "trim=start_frame=1," if index else ""
        filters.append(
            f"[{index}:v]fps={fps},scale={width}:{height},format=yuv420p,"
            f"{trim}settb=AVTB,setpts=PTS-STARTPTS[v{index}]"
        )
    labels = "".join(f"[v{index}]" for index in range(len(clips)))
    filters.append(f"{labels}concat=n={len(clips)}:v=1:a=0[joined]")
    filters.append(f"[joined]{motion_filter(motion, width, height, frames, fps, normalized=True)},fps={fps},format=yuv420p[out]")
    command.extend(
        [
            "-filter_complex",
            ";".join(filters),
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
    run(command)


def render_shot_keyframes(
    data: dict[str, Any],
    shot: dict[str, Any],
    manifest_dir: Path,
    output: Path,
    work_dir: Path,
    *,
    ffmpeg: str,
    interpolation_override: str | None,
    optical_flow_profile_override: str | None,
    rife_strategy_override: str | None,
    include_endpoint: bool,
    rife_runtime: tuple[Path, Path] | None,
    rife_gpu: int | None,
    strict: bool,
    preset: str,
    crf: int,
) -> str:
    end_value = shot.get("end_image")
    if not isinstance(end_value, str):
        raise TimelineError(f"Shot {shot['id']} needs end_image for intermediate_images")
    keyframes = keyframe_sequence_for(shot)
    image_values = [image for image, _ in keyframes]
    fps = int(data["fps"])
    frames = frame_count(float(shot["duration"]), fps)
    segment_count = len(image_values) - 1
    total_intervals = frames - 1 if include_endpoint else frames
    last_minimum = 1 if include_endpoint else 2
    if intermediate_keyframes_are_timed(shot):
        intervals = distribute_timed_intervals(
            total_intervals,
            [at for _, at in keyframes],
            float(shot["duration"]),
            last_minimum=last_minimum,
            fps=fps,
        )
    else:
        intervals = distribute_intervals(
            total_intervals,
            segment_count,
            last_minimum=last_minimum,
        )
    clips: list[Path] = []
    methods: list[str] = []
    for index, interval_count in enumerate(intervals):
        is_last = index == segment_count - 1
        segment_include_endpoint = include_endpoint or not is_last
        segment_frames = interval_count + 1 if segment_include_endpoint else interval_count
        segment_shot = dict(shot)
        segment_shot.update(
            {
                "id": f"{shot['id']}-segment-{index + 1}",
                "start_image": image_values[index],
                "end_image": image_values[index + 1],
                "duration": segment_frames / fps,
                "intermediate_images": [],
                "motion": "static",
            }
        )
        clip = work_dir / f"{output.stem}-segment-{index + 1:03d}.mp4"
        methods.append(
            render_shot_pair(
                data,
                segment_shot,
                manifest_dir,
                clip,
                work_dir,
                ffmpeg=ffmpeg,
                interpolation_override=interpolation_override,
                optical_flow_profile_override=optical_flow_profile_override,
                rife_strategy_override=rife_strategy_override,
                include_endpoint=segment_include_endpoint,
                rife_runtime=rife_runtime,
                rife_gpu=rife_gpu,
                strict=strict,
                preset=preset,
                crf=crf,
            )
        )
        clips.append(clip)

    concat_keyframe_segments(
        ffmpeg,
        clips,
        output,
        width=int(data["width"]),
        height=int(data["height"]),
        fps=fps,
        frames=frames,
        preset=preset,
        crf=crf,
        motion=motion_for(shot),
    )
    unique_methods = list(dict.fromkeys(methods))
    return "+".join(unique_methods) + f"+{len(image_values)}-keyframes"


def render_shot(
    data: dict[str, Any],
    shot: dict[str, Any],
    manifest_dir: Path,
    output: Path,
    work_dir: Path,
    *,
    ffmpeg: str,
    interpolation_override: str | None,
    optical_flow_profile_override: str | None,
    rife_strategy_override: str | None,
    include_endpoint: bool,
    rife_runtime: tuple[Path, Path] | None,
    rife_gpu: int | None,
    strict: bool,
    preset: str,
    crf: int,
) -> str:
    if (interpolation_override or interpolation_for(shot)) != "hold" and intermediate_images_for(shot):
        return render_shot_keyframes(
            data,
            shot,
            manifest_dir,
            output,
            work_dir,
            ffmpeg=ffmpeg,
            interpolation_override=interpolation_override,
            optical_flow_profile_override=optical_flow_profile_override,
            rife_strategy_override=rife_strategy_override,
            include_endpoint=include_endpoint,
            rife_runtime=rife_runtime,
            rife_gpu=rife_gpu,
            strict=strict,
            preset=preset,
            crf=crf,
        )
    return render_shot_pair(
        data,
        shot,
        manifest_dir,
        output,
        work_dir,
        ffmpeg=ffmpeg,
        interpolation_override=interpolation_override,
        optical_flow_profile_override=optical_flow_profile_override,
        rife_strategy_override=rife_strategy_override,
        include_endpoint=include_endpoint,
        rife_runtime=rife_runtime,
        rife_gpu=rife_gpu,
        strict=strict,
        preset=preset,
        crf=crf,
    )


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

    if all(transition_for(shot)[0] == "cut" for shot in shots[:-1]):
        # All clips are produced with the same codec, geometry and time base.
        listing = output.with_suffix(".ffconcat")
        lines = ["ffconcat version 1.0"]
        for clip in clips:
            escaped = clip.resolve().as_posix().replace("'", "'\\''")
            lines.append(f"file '{escaped}'")
        listing.write_text("\n".join(lines) + "\n", encoding="utf-8")
        run([ffmpeg, "-hide_banner", "-loglevel", "error", "-y", "-f", "concat",
             "-safe", "0", "-i", str(listing), "-map", "0:v:0", "-c:v", "copy",
             "-an", "-movflags", "+faststart", str(output)])
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


def percentile(values: list[float], fraction: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    position = (len(ordered) - 1) * fraction
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return float(ordered[lower])
    weight = position - lower
    return float(ordered[lower] * (1 - weight) + ordered[upper] * weight)


def number_summary(values: list[float]) -> dict[str, float]:
    if not values:
        return {"min": 0.0, "median": 0.0, "mean": 0.0, "p95": 0.0, "max": 0.0}
    return {
        "min": min(values),
        "median": percentile(values, 0.5),
        "mean": sum(values) / len(values),
        "p95": percentile(values, 0.95),
        "max": max(values),
    }


def parse_signalstats(output: str) -> list[tuple[int, float]]:
    current_frame: int | None = None
    differences: list[tuple[int, float]] = []
    for line in output.splitlines():
        frame_match = re.match(r"frame:(\d+)\s", line)
        if frame_match:
            current_frame = int(frame_match.group(1))
            continue
        if current_frame is None or current_frame == 0:
            continue
        if line.startswith("lavfi.signalstats.YDIF="):
            try:
                differences.append((current_frame, float(line.split("=", 1)[1])))
            except ValueError as exc:
                raise TimelineError(f"Invalid signalstats YDIF line: {line}") from exc
    return differences


def largest_temporal_jerks(
    pairs: list[tuple[int, float]],
    *,
    limit: int = 5,
) -> list[dict[str, float | int]]:
    """Locate the frame pairs with the largest change in adjacent-frame motion."""
    events = [
        {
            "frame": current_frame,
            "previous_ydif": previous_value,
            "current_ydif": current_value,
            "absolute_change": abs(current_value - previous_value),
        }
        for (_, previous_value), (current_frame, current_value) in zip(pairs, pairs[1:])
    ]
    return sorted(
        events,
        key=lambda event: (-float(event["absolute_change"]), int(event["frame"])),
    )[:limit]


def benchmark_video(ffmpeg: str, video: Path, duplicate_threshold: float) -> dict[str, Any]:
    video = video.expanduser().resolve()
    probe = probe_video(video)
    result = run(
        [
            ffmpeg,
            "-hide_banner",
            "-loglevel",
            "error",
            "-i",
            str(video),
            "-vf",
            "signalstats,metadata=print:file=-",
            "-f",
            "null",
            "-",
        ],
        capture=True,
    )
    pairs = parse_signalstats(result.stdout)
    if not pairs:
        raise TimelineError(f"FFmpeg did not return temporal signal statistics for {video}")
    differences = [value for _, value in pairs]
    jerk = [abs(current - previous) for previous, current in zip(differences, differences[1:])]
    streams = probe.get("streams") or []
    stream = next((item for item in streams if item.get("codec_type") == "video"), {})
    return {
        "video": str(video),
        "width": int(stream.get("width", -1)),
        "height": int(stream.get("height", -1)),
        "fps": rate_as_float(stream.get("avg_frame_rate", "0/1")),
        "frames": int(stream.get("nb_read_frames", -1)),
        "duration": float((probe.get("format") or {}).get("duration", 0)),
        "duplicate_threshold_ydif": duplicate_threshold,
        "near_duplicate_pairs": [
            {
                "previous_frame": frame - 1,
                "current_frame": frame,
                "ydif": value,
            }
            for frame, value in pairs
            if value < duplicate_threshold
        ],
        "temporal_luma_difference": number_summary(differences),
        "temporal_luma_jerk": number_summary(jerk),
        "largest_temporal_luma_jerks": largest_temporal_jerks(pairs),
    }


def compare_benchmarks(candidate: dict[str, Any], baseline: dict[str, Any]) -> dict[str, Any]:
    candidate_difference = candidate["temporal_luma_difference"]
    baseline_difference = baseline["temporal_luma_difference"]
    candidate_jerk = candidate["temporal_luma_jerk"]
    baseline_jerk = baseline["temporal_luma_jerk"]
    return {
        "same_geometry": (
            candidate["width"],
            candidate["height"],
            candidate["fps"],
            candidate["frames"],
        )
        == (
            baseline["width"],
            baseline["height"],
            baseline["fps"],
            baseline["frames"],
        ),
        "near_duplicate_pair_count_delta": (
            len(candidate["near_duplicate_pairs"]) - len(baseline["near_duplicate_pairs"])
        ),
        "temporal_luma_difference_median_delta": (
            candidate_difference["median"] - baseline_difference["median"]
        ),
        "temporal_luma_difference_p95_delta": (
            candidate_difference["p95"] - baseline_difference["p95"]
        ),
        "temporal_luma_jerk_p95_delta": candidate_jerk["p95"] - baseline_jerk["p95"],
    }


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
    if args.max_keyframe_gap is not None and (
        not is_number(args.max_keyframe_gap) or args.max_keyframe_gap <= 0
    ):
        raise TimelineError("max-keyframe-gap must be a positive finite number")
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
            "subject_motion": args.subject_motion,
            "transition_to_next": {
                "type": "fade" if index < args.shots - 1 else "cut",
                "duration": transition_duration if index < args.shots - 1 else 0,
            },
            "prompt": f"Describe the composition and action for {shot_id}",
            "continuity": "Repeat unchanged identity, wardrobe, palette, lens, lighting, and aspect ratio",
        }
        gap_limit = max_keyframe_gap_for(shot, args.max_keyframe_gap)
        if gap_limit is not None:
            shot["max_keyframe_gap"] = gap_limit
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


def plan_shot_keyframes(
    shot: dict[str, Any],
    manifest_dir: Path,
    max_gap: float,
    fps: int | None = None,
    reserved_paths: set[Path] | None = None,
) -> list[dict[str, Any]]:
    """Return existing and missing keyframes at a bounded temporal spacing."""
    if max_gap <= 0 or not math.isfinite(max_gap):
        raise TimelineError("max-gap must be a positive finite number")
    sequence = keyframe_sequence_for(shot)
    planned: list[dict[str, Any]] = []
    used_paths = {resolve_media(manifest_dir, image) for image, _ in sequence} | (reserved_paths or set())
    subdivisions_by_pair = []
    budget = frame_count(float(shot["duration"]), fps) if fps is not None else None
    for (_, left_at), (_, right_at) in zip(sequence, sequence[1:]):
        ratio = (right_at - left_at) / max_gap
        if not math.isfinite(ratio) or (budget is not None and ratio > budget):
            raise TimelineError(f"Shot {shot['id']} planned keyframes exceed the frame budget; increase duration/fps or max-gap")
        subdivisions_by_pair.append(max(1, math.ceil(ratio - 1e-9)))
    if fps is not None and sum(subdivisions_by_pair) + 1 > frame_count(float(shot["duration"]), fps):
        raise TimelineError(f"Shot {shot['id']} planned keyframes exceed the frame budget; increase duration/fps or max-gap")

    def entry(image: str, at: float, generated: bool) -> dict[str, Any]:
        path = resolve_media(manifest_dir, image)
        planned_stem = f"{shot['id']}-dense-{round(at * 1000):06d}ms"
        suffix = hashlib.sha256(float(at).hex().encode()).hexdigest()[:12]
        generated_name = re.fullmatch(re.escape(planned_stem) + rf"(?:-{suffix}(?:-[0-9]+)?)?\.png", Path(image).name)
        return {
            "image": image,
            "at": at,
            "status": "existing" if path.is_file() else "missing",
            "generated_slot": generated or generated_name is not None,
        }

    planned.append(entry(sequence[0][0], sequence[0][1], False))
    for ((left_image, left_at), (right_image, right_at)), subdivisions in zip(
        zip(sequence, sequence[1:]), subdivisions_by_pair
    ):
        for step in range(1, subdivisions):
            at = left_at + (right_at - left_at) * step / subdivisions
            image = f"keyframes/{shot['id']}-dense-{round(at * 1000):06d}ms.png"
            if resolve_media(manifest_dir, image) in used_paths or resolve_media(manifest_dir, image).exists():
                suffix = hashlib.sha256(float(at).hex().encode()).hexdigest()[:12]
                image = f"keyframes/{shot['id']}-dense-{round(at * 1000):06d}ms-{suffix}.png"
                serial = 1
                while resolve_media(manifest_dir, image) in used_paths or resolve_media(manifest_dir, image).exists():
                    image = f"keyframes/{shot['id']}-dense-{round(at * 1000):06d}ms-{suffix}-{serial}.png"
                    serial += 1
            used_paths.add(resolve_media(manifest_dir, image))
            planned.append(entry(image, at, True))
        planned.append(entry(right_image, right_at, False))
    return planned


def write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        newline="\n",
        dir=path.parent,
        prefix=f".{path.name}.",
        suffix=".tmp",
        delete=False,
    ) as handle:
        temporary = Path(handle.name)
        json.dump(payload, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    try:
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def command_plan_keyframes(args: argparse.Namespace) -> int:
    if args.max_gap is not None and (not is_number(args.max_gap) or args.max_gap <= 0):
        raise TimelineError("max-gap must be a positive finite number")
    manifest_path = args.manifest.expanduser().resolve()
    data, warnings = load_and_validate(manifest_path, require_files=False, probe_files=False)
    for warning in warnings:
        eprint(f"WARNING: {warning}")

    shot_plans: list[dict[str, Any]] = []
    changed = False
    reserved_paths = referenced_media_paths(data, manifest_path.parent)
    for shot in data["shots"]:
        if interpolation_for(shot) == "hold" or not isinstance(shot.get("end_image"), str):
            continue
        declared_motion = args.subject_motion or shot.get("subject_motion") or "articulated"
        if declared_motion not in SUBJECT_MOTION_DEFAULT_GAPS:
            raise TimelineError(
                f"Shot {shot['id']} has unsupported subject_motion: {declared_motion}"
            )
        default_gap = SUBJECT_MOTION_DEFAULT_GAPS[declared_motion]
        gap_limit = (
            args.max_gap
            if args.max_gap is not None
            else max_keyframe_gap_for(shot) or default_gap
        )
        if gap_limit is None:
            shot_plans.append(
                {"id": shot["id"], "subject_motion": declared_motion, "status": "not-required"}
            )
            continue
        planned = plan_shot_keyframes(shot, manifest_path.parent, float(gap_limit),
                                      fps=int(data["fps"]), reserved_paths=reserved_paths)
        reserved_paths.update(resolve_media(manifest_path.parent, entry["image"]) for entry in planned)
        intermediates = [
            {"image": item["image"], "at": item["at"]}
            for item in planned[1:-1]
        ]
        missing = [item["image"] for item in planned if item["status"] == "missing"]
        generated_missing = [
            item["image"]
            for item in planned
            if item["status"] == "missing" and item["generated_slot"]
        ]
        shot_plans.append(
            {
                "id": shot["id"],
                "subject_motion": declared_motion,
                "max_keyframe_gap": float(gap_limit),
                "keyframes": planned,
                "missing_images": missing,
                "generated_slots_missing": generated_missing,
            }
        )
        if args.write:
            updated = (
                shot.get("subject_motion") != declared_motion
                or shot.get("max_keyframe_gap") != float(gap_limit)
                or shot.get("intermediate_images", []) != intermediates
            )
            shot["subject_motion"] = declared_motion
            shot["max_keyframe_gap"] = float(gap_limit)
            shot["intermediate_images"] = intermediates
            changed = changed or updated

    if args.write and changed:
        write_json_atomic(manifest_path, data)
    print(
        json.dumps(
            {
                "status": "written" if args.write and changed else "planned",
                "manifest": str(manifest_path),
                "shots": shot_plans,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
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


def command_plan_motion(args: argparse.Namespace) -> int:
    data, warnings = load_and_validate(args.manifest, require_files=False, validate_motion=False)
    for shot in data["shots"]:
        sequence = ([(shot["start_image"], 0.0)] if interpolation_for(shot) == "hold" else keyframe_sequence_for(shot))
        previous = shot.get("motion_plan", [])
        previous = previous if isinstance(previous, list) else []
        old = {(e.get("image"), e.get("at")): e for e in previous if isinstance(e, dict)
               and isinstance(e.get("image"), str) and is_number(e.get("at"))}
        removed = [e for e in previous if isinstance(e, dict) and (e.get("image"), e.get("at")) not in sequence
                   and isinstance(e.get("image"), str) and is_number(e.get("at"))]
        if removed:
            raise TimelineError(f"Shot {shot['id']} has obsolete motion-plan entries; reconcile them before rebuilding the plan")
        shot["motion_plan"] = [old.get((image, at), {"image": image, "at": at,
            "reference_image": sequence[max(0, index - 1)][0], "changes": [], "keep": [], "review": "pending"})
            for index, (image, at) in enumerate(sequence)]
    if args.write:
        write_json_atomic(args.manifest.expanduser().resolve(), data)
    print(json.dumps({"status": "written" if args.write else "planned", "timeline": data,
                      "note": "Fill target/state changes and invariants, then visually review; empty plans do not imply approval."}, indent=2))
    return 0


def command_inspect(args: argparse.Namespace) -> int:
    ffmpeg = require_tool("ffmpeg")
    manifest = args.manifest.expanduser().resolve()
    data, warnings = load_and_validate(manifest, require_files=True, interpolation_override=args.interpolation)
    if args.interpolation:
        data = dict(data, shots=[dict(shot, interpolation=args.interpolation) for shot in data["shots"]])
    video = args.video.expanduser().resolve()
    probe = probe_video(video)
    failures = output_validation_failures(probe, data)
    if failures:
        raise TimelineError("Inspection video does not match manifest: " + "; ".join(failures))
    run([ffmpeg, "-v", "error", "-xerror", "-i", str(video), "-f", "null", "-"])
    benchmark = benchmark_video(ffmpeg, video, 0.1)
    directory = args.output_dir.expanduser().resolve()
    if directory.exists():
        raise TimelineError(f"Inspection directory already exists; choose a new directory: {directory}")
    directory.mkdir(parents=True)
    # Mark incomplete before generating assets; never leave a false 'passed' report.
    write_json_atomic(directory / "report.json", {"status": "incomplete"})
    fps, total = int(data["fps"]), total_output_frames(data)
    deduplicated = shared_cut_boundaries(data, manifest.parent)
    samples = {0, total - 1}
    pairs, timing, offset = [], {}, 0
    sources: dict[str, str] = {}
    for index, shot in enumerate(data["shots"]):
        points = shot_timing(shot, fps, index not in deduplicated)
        timing[shot["id"]] = points
        for point in points:
            frame = min(total - 1, offset + point["frame"])
            samples.update(n for n in (frame - 1, frame, frame + 1) if 0 <= n < total)
            source = str(resolve_media(manifest.parent, point["image"]))
            if source not in sources:
                name = f"source-{len(sources):04d}.png"
                run([ffmpeg, "-v", "error", "-i", source, "-vf", "scale=320:-2", "-frames:v", "1", str(directory / name)])
                sources[source] = name
        for left, right in zip(points, points[1:]):
            start, end = offset + left["frame"], offset + right["frame"]
            selected = sorted({min(total - 1, start + int((end - start) * fraction + 0.5))
                               for fraction in (0, .25, .5, .75, 1)})
            samples.update(selected)
            pairs.append({"shot": shot["id"], "from": left["image"], "to": right["image"],
                          "start_frame": start, "end_frame": end, "sample_frames": selected})
        shot_frames = frame_count(float(shot["duration"]), fps)
        transition, duration = transition_for(shot)
        overlap = frame_count(float(duration), fps) if index < len(data["shots"]) - 1 and transition != "cut" else 0
        # Include the middle of each shot, including intentional holds.
        samples.add(min(total - 1, offset + shot_frames // 2))
        offset += shot_frames - overlap
    for item in benchmark["largest_temporal_luma_jerks"]:
        samples.update(n for n in (item["frame"] - 1, item["frame"], item["frame"] + 1) if 0 <= n < total)
    ordered = sorted(samples)
    # Bounded batches support older and newer FFmpeg without deprecated script options
    # and stay below Windows command-line length limits.
    for first in range(0, len(ordered), 128):
        batch = ordered[first:first + 128]
        selection = "+".join(f"eq(n\\,{n})" for n in batch)
        run([ffmpeg, "-v", "error", "-i", str(video), "-vf", f"select={selection},scale=480:-2",
             "-fps_mode", "vfr", "-frames:v", str(len(batch)), "-start_number", str(first),
             str(directory / "sample-%06d.png")])
    shutil.copyfile(video, directory / "preview.mp4")
    review = {"source_pairs": "not_reviewed", "intermediate_frames": "not_reviewed",
              "normal_speed_playback": "not_reviewed", "issues": []}
    write_json_atomic(directory / "review.json", review)
    report = {"status": "ready_for_visual_review", "technical": "passed", "review": review,
              "video_sha256": file_digest(directory / "preview.mp4").hex(),
              "keyframe_timing": timing, "pairs": pairs, "sample_frames": ordered,
              "benchmark": benchmark, "warnings": warnings}
    write_json_atomic(directory / "report.json", report)
    source_html = "".join(f'<figure><img src="{name}"><figcaption>{html.escape(Path(source).name)}</figcaption></figure>'
                          for source, name in sources.items())
    pair_html = "".join(f'<li>{html.escape(p["shot"])}: {html.escape(p["from"])} → {html.escape(p["to"])}; '
                        f'frames {p["start_frame"]}–{p["end_frame"]}<div class="grid">'
                        f'<img src="{sources[str(resolve_media(manifest.parent, p["from"]))]}">'
                        f'<img src="{sources[str(resolve_media(manifest.parent, p["to"]))]}"></div></li>' for p in pairs)
    frame_html = "".join(f'<figure><img src="sample-{i:06d}.png"><figcaption>Frame {n} · {n/fps:.3f}s</figcaption></figure>'
                         for i, n in enumerate(ordered))
    page = ('<!doctype html><meta charset="utf-8"><title>Timeline review</title>'
            '<style>body{font:16px system-ui;background:#202124;color:#eee;margin:24px}video{width:min(100%,960px)}'
            '.grid{display:flex;flex-wrap:wrap}figure{margin:8px}img{width:320px}figcaption{max-width:320px;overflow-wrap:anywhere}</style>'
            '<h1>Timeline review</h1><p>Technical checks passed. Visual review is pending; images and metrics do not certify motion quality.</p>'
            '<video id="preview" src="preview.mp4" controls></video><p>Playback speed '
            '<select onchange="document.getElementById(\'preview\').playbackRate=Number(this.value)">'
            '<option value="1">1×</option><option value="0.5">0.5×</option><option value="0.25">0.25×</option></select></p>'
            '<p>Record source-pair, intermediate-frame and playback findings separately in review.json as not_reviewed/pass/revise, '
            'with frame numbers, remedies and resolved flags for issues. Run review-status before delivery.</p>'
            f'<h2>Source images</h2><div class="grid">{source_html}</div><h2>Adjacent pairs</h2><ol>{pair_html}</ol>'
            f'<h2>Rendered samples</h2><div class="grid">{frame_html}</div>')
    (directory / "index.html").write_text(page, encoding="utf-8")
    print(json.dumps({"status": report["status"], "report": str(directory / "report.json"),
                      "preview": str(directory / "index.html")}, indent=2))
    return 0


def assess_review(report: dict[str, Any], review: dict[str, Any], digest: str) -> dict[str, Any]:
    pending, revisions = [], []
    if report.get("technical") != "passed":
        pending.append("technical checks have not passed")
    if report.get("video_sha256") != digest:
        pending.append("video differs from the inspected copy or inspection hash is missing; rerun inspect")
    for field in ("source_pairs", "intermediate_frames", "normal_speed_playback"):
        value = review.get(field)
        if value == "revise":
            revisions.append(f"{field} requires revision")
        elif value != "pass":
            pending.append(f"{field} is {value!r}; explicit pass/revise is required after review")
    issues = review.get("issues")
    if not isinstance(issues, list):
        pending.append("issues must be an array")
    else:
        for index, issue in enumerate(issues):
            if not isinstance(issue, dict) or issue.get("resolved") is not True:
                revisions.append(f"issue {index + 1} remains unresolved")
    status = "needs_revision" if revisions else "needs_review" if pending else "ready_for_delivery"
    return {"delivery_status": status, "reasons": revisions + pending,
            "basis": "Recorded human/agent review of the inspected video; not automated visual certification"}


def command_review_status(args: argparse.Namespace) -> int:
    directory = args.directory.expanduser().resolve()
    try:
        report = json.loads((directory / "report.json").read_text(encoding="utf-8"))
        review = json.loads((directory / "review.json").read_text(encoding="utf-8"))
        digest = file_digest(directory / "preview.mp4").hex()
    except (OSError, ValueError) as exc:
        raise TimelineError(f"Cannot read inspection/review files: {exc}") from exc
    if not isinstance(report, dict) or not isinstance(review, dict):
        raise TimelineError("report.json and review.json must contain objects")
    result = assess_review(report, review, digest)
    if args.write:
        report.update(result, review=review)
        write_json_atomic(directory / "report.json", report)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["delivery_status"] == "ready_for_delivery" else 2


def command_render(args: argparse.Namespace) -> int:
    ffmpeg = require_tool("ffmpeg")
    require_tool("ffprobe")
    data, warnings = load_and_validate(args.manifest, require_files=True, probe_files=True,
                                       interpolation_override=args.interpolation)
    for warning in warnings:
        eprint(f"WARNING: {warning}")

    manifest_path = args.manifest.expanduser().resolve()
    manifest_dir = manifest_path.parent
    requested_interpolations = (
        {args.interpolation}
        if args.interpolation
        else {interpolation_for(shot) for shot in data["shots"]}
    )
    rife_runtime: tuple[Path, Path] | None = None
    if "rife" in requested_interpolations:
        try:
            rife_runtime = resolve_rife_runtime(args.rife_executable, args.rife_model)
        except TimelineError as exc:
            if args.strict:
                raise
            eprint(f"WARNING: {exc}; RIFE shots will fall back to optical flow")
    deduplicated_boundaries = shared_cut_boundaries(
        data,
        manifest_dir,
        interpolation_override=args.interpolation,
    )
    slug = re.sub(r"[^A-Za-z0-9._-]+", "-", data["title"].strip()).strip("-.") or "video"
    output = (args.output or (manifest_dir / "output" / f"{slug}.mp4")).expanduser().resolve()
    protected_inputs = referenced_media_paths(data, manifest_dir) | {manifest_path}
    if output in protected_inputs or (output.exists() and any(
        source.exists() and output.samefile(source) for source in protected_inputs
    )):
        raise TimelineError(f"Output must not replace the timeline or source media: {output}")
    if output.suffix.lower() != ".mp4":
        raise TimelineError("Output must have an .mp4 extension")
    if output.exists() and not args.force:
        raise TimelineError(f"Output exists; pass --force to replace it: {output}")
    output.parent.mkdir(parents=True, exist_ok=True)

    with render_context(getattr(args, "cache_dir", None), ffmpeg, rife_runtime,
                        getattr(args, "command_timeout", 300)) as cache_events, \
            tempfile.TemporaryDirectory(prefix=".timeline-video-", dir=output.parent) as temp_name, \
            normalization_cache(Path(temp_name) / "normalized"):
        work_dir = Path(temp_name)
        clips: list[Path] = []
        methods: dict[str, str] = {}
        for index, shot in enumerate(data["shots"]):
            clip = work_dir / f"shot-{index:04d}.mp4"
            eprint(f"Rendering {shot['id']} ({index + 1}/{len(data['shots'])})")
            methods[shot["id"]] = render_shot(
                data,
                shot,
                manifest_dir,
                clip,
                work_dir,
                ffmpeg=ffmpeg,
                interpolation_override=args.interpolation,
                optical_flow_profile_override=args.optical_flow_profile,
                rife_strategy_override=args.rife_strategy,
                include_endpoint=index not in deduplicated_boundaries,
                rife_runtime=rife_runtime,
                rife_gpu=args.rife_gpu,
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

        probe = probe_video(final_temp)
        failures = output_validation_failures(probe, data)
        if failures:
            raise TimelineError("Rendered output validation failed: " + "; ".join(failures))
        run([ffmpeg, "-hide_banner", "-loglevel", "error", "-xerror", "-i",
             str(final_temp), "-map", "0:v:0", "-map", "0:a?", "-f", "null", "-"])
        publish_video(final_temp, output, force=args.force)

    print(
        json.dumps(
            {
                "status": "rendered",
                "output": str(output),
                "frames": total_frames,
                "fps": data["fps"],
                "duration": total_frames / data["fps"],
                "interpolation_used": methods,
                "rife_sampling_policy": {
                    "recursive": "midpoint grid plus RIFE local-timestep refinement; no FFmpeg pixel blending",
                    "direct": "RIFE at target times with source endpoints preserved",
                },
                "keyframe_timing": {
                    shot["id"]: shot_timing(dict(shot, interpolation=args.interpolation or interpolation_for(shot)),
                                            data["fps"], index not in deduplicated_boundaries)
                    for index, shot in enumerate(data["shots"])
                },
                "segment_cache": cache_events,
                "intermediate_keyframes": {
                    shot["id"]: (0 if (args.interpolation or interpolation_for(shot)) == "hold"
                                 else len(intermediate_images_for(shot))) for shot in data["shots"]
                },
                "deduplicated_cut_boundaries": [
                    data["shots"][index]["id"] for index in sorted(deduplicated_boundaries)
                ],
                "render_settings": {
                    "interpolation_override": args.interpolation,
                    "optical_flow_profile_override": args.optical_flow_profile,
                    "rife_strategy_override": args.rife_strategy,
                    "rife_gpu": args.rife_gpu,
                    "strict": args.strict,
                    "preset": args.preset,
                    "crf": args.crf,
                },
                "runtime": {
                    "ffmpeg": str(Path(ffmpeg).resolve()),
                    "rife_executable": str(rife_runtime[0]) if rife_runtime else None,
                    "rife_model": str(rife_runtime[1]) if rife_runtime else None,
                },
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


def publish_video(candidate: Path, output: Path, *, force: bool) -> None:
    """Publish a validated candidate on the same filesystem without copying it.

    Hard-link creation is atomic and refuses races when overwrite is disabled.
    """
    if force:
        os.replace(candidate, output)
    else:
        try:
            os.link(candidate, output)
        except FileExistsError as exc:
            raise TimelineError(f"Output appeared during rendering: {output}") from exc


def output_validation_failures(payload: dict[str, Any], data: dict[str, Any]) -> list[str]:
    failures: list[str] = []
    streams = payload.get("streams") or []
    video = next((item for item in streams if item.get("codec_type") == "video"), None)
    if video is None:
        return ["video stream is missing"]
    expected_duration = total_output_frames(data) / data["fps"]
    try:
        for field, expected in (("width", data["width"]), ("height", data["height"]),
                                ("nb_read_frames", total_output_frames(data))):
            if int(video.get(field, -1)) != expected:
                failures.append(f"{field} does not match manifest")
        rate = rate_as_float(video.get("avg_frame_rate", "0/1"))
        if not math.isfinite(rate) or abs(rate - data["fps"]) > 1e-6:
            failures.append("frame rate does not match manifest")
        for label, actual in (("video", video.get("duration")),
                              ("container", (payload.get("format") or {}).get("duration"))):
            duration = float(actual)
            if not math.isfinite(duration) or abs(duration - expected_duration) > 1 / data["fps"] + 0.001:
                failures.append(f"{label} duration does not match manifest")
    except (TypeError, ValueError, OverflowError):
        failures.append("invalid numeric output metadata")
    audio = [item for item in streams if item.get("codec_type") == "audio"]
    if bool(audio) != bool(data.get("audio")):
        failures.append("audio streams do not match manifest")
    for stream in audio:
        try:
            duration = float(stream.get("duration"))
            if (not math.isfinite(duration) or abs(duration - expected_duration) > max(1 / data["fps"], 0.05)
                    or int(stream.get("sample_rate", 0)) <= 0 or int(stream.get("channels", 0)) <= 0):
                failures.append("invalid audio duration or geometry")
        except (TypeError, ValueError, OverflowError):
            failures.append("invalid audio metadata")
    return failures


def command_probe(args: argparse.Namespace) -> int:
    payload = probe_video(args.video)
    failures: list[str] = []
    if args.manifest:
        data, warnings = load_and_validate(args.manifest, require_files=False, probe_files=False)
        for warning in warnings:
            eprint(f"WARNING: {warning}")
        failures = output_validation_failures(payload, data)
        payload["manifest_check"] = "passed" if not failures else {"failed": failures}
    print(json.dumps(payload, indent=2))
    return 1 if failures else 0


def command_benchmark(args: argparse.Namespace) -> int:
    if not is_number(args.duplicate_threshold) or args.duplicate_threshold < 0:
        raise TimelineError("duplicate-threshold must be a finite non-negative number")
    ffmpeg = require_tool("ffmpeg")
    require_tool("ffprobe")
    candidate = benchmark_video(ffmpeg, args.video, args.duplicate_threshold)
    payload: dict[str, Any] = {
        "status": "benchmarked",
        "candidate": candidate,
    }
    if args.baseline:
        baseline = benchmark_video(ffmpeg, args.baseline, args.duplicate_threshold)
        payload["baseline"] = baseline
        payload["comparison"] = compare_benchmarks(candidate, baseline)
    print(json.dumps(payload, indent=2))
    return 0


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
    init_parser.add_argument(
        "--subject-motion",
        choices=sorted(SUBJECT_MOTION_DEFAULT_GAPS),
        default="none",
        help="Expected subject motion; articulated defaults to a 0.25s keyframe gap",
    )
    init_parser.add_argument("--max-keyframe-gap", type=float)
    init_parser.set_defaults(handler=command_init)

    plan_parser = subparsers.add_parser(
        "plan-keyframes",
        help="Plan dense timed keyframes and optionally update the timeline",
    )
    plan_parser.add_argument("manifest", type=Path)
    plan_parser.add_argument("--max-gap", type=float, help="Maximum seconds between semantic poses")
    plan_parser.add_argument(
        "--subject-motion",
        choices=sorted(SUBJECT_MOTION_DEFAULT_GAPS),
        help="Override the declared subject motion for planned shots",
    )
    plan_parser.add_argument(
        "--write",
        action="store_true",
        help="Atomically write timed intermediate_images placeholders to the manifest",
    )
    plan_parser.set_defaults(handler=command_plan_keyframes)

    validate_parser = subparsers.add_parser("validate", help="Validate a timeline and its media")
    validate_parser.add_argument("manifest", type=Path)
    validate_parser.add_argument(
        "--allow-missing",
        action="store_true",
        help="Validate structure before keyframes exist",
    )
    validate_parser.add_argument("--skip-probe", action="store_true", help="Do not inspect media with ffprobe")
    validate_parser.set_defaults(handler=command_validate)

    render_parser = subparsers.add_parser("render", help="Render and verify an MP4")
    render_parser.add_argument("manifest", type=Path)
    render_parser.add_argument("--output", type=Path)
    render_parser.add_argument("--interpolation", choices=sorted(INTERPOLATIONS), help="Override every shot")
    render_parser.add_argument(
        "--optical-flow-profile",
        choices=sorted(OPTICAL_FLOW_PROFILES),
        help="Override the FFmpeg optical-flow profile for every shot",
    )
    render_parser.add_argument("--rife-executable", type=Path, help="Path to rife-ncnn-vulkan executable")
    render_parser.add_argument("--rife-model", type=Path, help="Path to a rife-v4 model directory")
    render_parser.add_argument("--rife-gpu", type=int, help="RIFE GPU id; use -1 for CPU")
    render_parser.add_argument(
        "--rife-strategy",
        choices=sorted(RIFE_STRATEGIES),
        help="Override direct arbitrary-timestep or recursive midpoint interpolation",
    )
    render_parser.add_argument(
        "--preset",
        default="medium",
        choices=["ultrafast", "veryfast", "fast", "medium", "slow"],
    )
    render_parser.add_argument("--crf", type=int, default=18, choices=range(0, 52), metavar="0-51")
    render_parser.add_argument(
        "--strict",
        action="store_true",
        help="Fail instead of falling back from RIFE or optical flow",
    )
    render_parser.add_argument("--force", action="store_true", help="Replace an existing output file")
    render_parser.add_argument("--cache-dir", type=Path, help="Reuse verified content-addressed pair clips across renders")
    render_parser.add_argument("--command-timeout", type=float, default=300, help="Timeout per external command in seconds (default 300)")
    render_parser.set_defaults(handler=command_render)

    probe_parser = subparsers.add_parser("probe", help="Inspect a video and optionally compare it to a manifest")
    probe_parser.add_argument("video", type=Path)
    probe_parser.add_argument("--manifest", type=Path)
    probe_parser.set_defaults(handler=command_probe)

    motion_parser = subparsers.add_parser("plan-motion", help="Create reviewable motion-plan records for existing keyframe slots")
    motion_parser.add_argument("manifest", type=Path)
    motion_parser.add_argument("--write", action="store_true")
    motion_parser.set_defaults(handler=command_plan_motion)

    inspect_parser = subparsers.add_parser("inspect", help="Generate pair/sample review assets and a local playback page")
    inspect_parser.add_argument("video", type=Path)
    inspect_parser.add_argument("--manifest", type=Path, required=True)
    inspect_parser.add_argument("--output-dir", type=Path, required=True)
    inspect_parser.add_argument("--interpolation", choices=sorted(INTERPOLATIONS), help="Match an interpolation override used for rendering")
    inspect_parser.set_defaults(handler=command_inspect)

    review_parser = subparsers.add_parser("review-status", help="Check recorded acceptance and inspected video identity before delivery")
    review_parser.add_argument("directory", type=Path)
    review_parser.add_argument("--write", action="store_true", help="Record delivery status and review in report.json")
    review_parser.set_defaults(handler=command_review_status)

    benchmark_parser = subparsers.add_parser(
        "benchmark",
        help="Measure temporal continuity and optionally compare against a baseline",
    )
    benchmark_parser.add_argument("video", type=Path)
    benchmark_parser.add_argument("--baseline", type=Path)
    benchmark_parser.add_argument(
        "--duplicate-threshold",
        type=float,
        default=0.1,
        help="YDIF threshold below which adjacent frames are reported as near-duplicates",
    )
    benchmark_parser.set_defaults(handler=command_benchmark)
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
