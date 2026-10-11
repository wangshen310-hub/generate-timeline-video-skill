"""Behavioral regressions for recovery of the timeline renderer optimization."""
from __future__ import annotations

import argparse
import copy
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

from test_timeline_video import timeline_video as tv

SCRIPT = Path(tv.__file__)


def manifest(shot=None):
    return {"version": 1, "title": "Regression", "fps": 8, "width": 64, "height": 64,
            "shots": [shot or {"id": "one", "duration": 1, "start_image": "a.ppm",
                               "end_image": "b.ppm", "interpolation": "blend"}]}


def ppm(path, color, size=64):
    path.write_bytes(f"P6\n{size} {size}\n255\n".encode() + bytes(color) * size * size)


class RecoveryUnitTests(unittest.TestCase):
    def test_invalid_candidate_never_replaces_existing_video(self):
        for failure in ("metadata", "decode"):
            with self.subTest(failure=failure), tempfile.TemporaryDirectory() as name:
                root = Path(name)
                output = root / "final.mp4"
                output.write_bytes(b"previous-video")
                path = root / "timeline.json"
                path.write_text(json.dumps(manifest()))
                args = tv.build_parser().parse_args(["render", str(path), "--output", str(output), "--force"])
                good = {"streams": [{"codec_type": "video", "width": 64, "height": 64,
                                     "nb_read_frames": "8", "avg_frame_rate": "8/1", "duration": "1"}],
                        "format": {"duration": "1"}}
                if failure == "metadata":
                    good["streams"][0]["width"] = 32
                def fake_assemble(_ffmpeg, _data, _clips, candidate, **kwargs):
                    candidate.write_bytes(b"invalid-video")
                    return 8
                with (mock.patch.object(tv, "require_tool", side_effect=lambda name: name),
                      mock.patch.object(tv, "load_and_validate", return_value=(manifest(), [])),
                      mock.patch.object(tv, "render_shot", return_value="blend"),
                      mock.patch.object(tv, "assemble_shots", side_effect=fake_assemble),
                      mock.patch.object(tv, "probe_video", return_value=good),
                      mock.patch.object(tv, "run", side_effect=subprocess.CalledProcessError(1, ["ffmpeg"])),
                      mock.patch.object(tv, "publish_video") as publish):
                    with self.assertRaises((tv.TimelineError, subprocess.CalledProcessError)):
                        tv.command_render(args)
                    publish.assert_not_called()
                self.assertEqual(output.read_bytes(), b"previous-video")
                self.assertEqual(list(root.glob(".timeline-video-*")), [])
                self.assertIsNone(tv._image_cache.get())

    def test_hold_ignores_unused_missing_and_malformed_keyframes(self):
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            ppm(root / "a.ppm", (255, 0, 0))
            data = manifest()
            data["shots"][0].update(interpolation="hold", end_image="absent.png",
                                     intermediate_images=[{"image": "absent2.png", "at": "unused"}])
            path = root / "timeline.json"
            path.write_text(json.dumps(data))
            loaded, _ = tv.load_and_validate(path)
            self.assertEqual(loaded, data)

    def test_override_controls_validation(self):
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            ppm(root / "a.ppm", (255, 0, 0))
            path = root / "timeline.json"
            path.write_text(json.dumps(manifest()))
            tv.load_and_validate(path, interpolation_override="hold")
            with self.assertRaises(tv.TimelineError):
                tv.load_and_validate(path, interpolation_override="blend")

    def test_hold_dispatches_one_pair(self):
        shot = manifest()["shots"][0]
        shot["intermediate_images"] = ["missing.ppm"]
        with mock.patch.object(tv, "render_shot_pair", return_value="hold") as pair, mock.patch.object(tv, "render_shot_keyframes") as multi:
            tv.render_shot(manifest(), shot, Path("."), Path("out.mp4"), Path("."),
                           ffmpeg="ffmpeg", interpolation_override="hold", optical_flow_profile_override=None,
                           rife_strategy_override=None, include_endpoint=True, rife_runtime=None,
                           rife_gpu=None, strict=True, preset="ultrafast", crf=18)
            pair.assert_called_once()
            multi.assert_not_called()

    def test_validation_rejects_impossible_keyframe_budget(self):
        with tempfile.TemporaryDirectory() as name:
            path = Path(name) / "timeline.json"
            data = manifest()
            data["shots"][0].update(duration=0.25, intermediate_images=["mid.ppm"])
            path.write_text(json.dumps(data))
            with self.assertRaisesRegex(tv.TimelineError, "frame budget"):
                tv.load_and_validate(path, require_files=False)

    def test_planning_rejects_budget_before_writing(self):
        with tempfile.TemporaryDirectory() as name:
            path = Path(name) / "timeline.json"
            path.write_text(json.dumps(manifest()))
            before = path.read_bytes()
            args = argparse.Namespace(manifest=path, max_gap=0.01, subject_motion=None, write=True)
            with self.assertRaisesRegex(tv.TimelineError, "frame budget"):
                tv.command_plan_keyframes(args)
            self.assertEqual(path.read_bytes(), before)

    def test_planning_full_precision_is_idempotent(self):
        with tempfile.TemporaryDirectory() as name:
            path = Path(name) / "timeline.json"
            path.write_text(json.dumps(manifest()))
            args = argparse.Namespace(manifest=path, max_gap=1/3, subject_motion=None, write=True)
            with redirect_stdout(io.StringIO()):
                tv.command_plan_keyframes(args)
                first = path.read_bytes()
                tv.command_plan_keyframes(args)
            self.assertEqual(first, path.read_bytes())
            at = json.loads(first)["shots"][0]["intermediate_images"][0]["at"]
            self.assertEqual(at, 1/3)

    def test_planning_names_do_not_alias_sources_or_existing_files(self):
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            (root / "keyframes").mkdir()
            occupied = root / "keyframes/one-dense-000500ms.png"
            occupied.write_bytes(b"unrelated")
            shot = manifest()["shots"][0]
            shot["start_image"] = str(occupied)
            plan = tv.plan_shot_keyframes(shot, root, 0.5, fps=8)
            self.assertNotEqual(tv.resolve_media(root, plan[1]["image"]), occupied)
            self.assertEqual(occupied.read_bytes(), b"unrelated")

    def test_submillisecond_names_are_unique(self):
        with tempfile.TemporaryDirectory() as name:
            shot = manifest()["shots"][0]
            shot["duration"] = 0.001
            plan = tv.plan_shot_keyframes(shot, Path(name), 0.0002)
            self.assertEqual(len({entry["image"] for entry in plan}), len(plan))

    def test_planner_respects_other_shots_reserved_paths(self):
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            occupied = root / "keyframes/one-dense-000500ms.png"
            plan = tv.plan_shot_keyframes(manifest()["shots"][0], root, 0.5, fps=8,
                                          reserved_paths={occupied})
            self.assertNotEqual(tv.resolve_media(root, plan[1]["image"]), occupied)
            shot = manifest()["shots"][0]
            shot["intermediate_images"] = [{"image": plan[1]["image"], "at": plan[1]["at"]}]
            repeated = tv.plan_shot_keyframes(shot, root, 0.5, fps=8)
            self.assertEqual(plan, repeated)

    def test_planning_extreme_gap_fails_without_overflow(self):
        with tempfile.TemporaryDirectory() as name:
            with self.assertRaisesRegex(tv.TimelineError, "frame budget"):
                tv.plan_shot_keyframes(manifest()["shots"][0], Path(name), 1e-320, fps=8)

    def test_normalization_cache_reuses_and_resets(self):
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            source = root / "a.ppm"
            ppm(source, (255, 0, 0))
            def fake_run(command, **kwargs):
                Path(command[-1]).write_bytes(b"normalized")
            with mock.patch.object(tv, "run", side_effect=fake_run) as run:
                with tv.normalization_cache(root / "cache"):
                    tv.normalize_image("ffmpeg", source, root / "one.png", 64, 64)
                    tv.normalize_image("ffmpeg", source.parent / "." / source.name, root / "two.png", 64, 64)
                    tv.normalize_image("ffmpeg", source, root / "three.png", 32, 32)
                self.assertEqual(run.call_count, 2)
                with tv.normalization_cache(root / "cache2"):
                    tv.normalize_image("ffmpeg", source, root / "four.png", 64, 64)
                self.assertEqual(run.call_count, 3)

    def test_publication_refuses_race_and_preserves_existing_output(self):
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            candidate, output = root / "candidate", root / "out"
            candidate.write_bytes(b"new")
            output.write_bytes(b"old")
            with self.assertRaises(tv.TimelineError):
                tv.publish_video(candidate, output, force=False)
            self.assertEqual(output.read_bytes(), b"old")
            with mock.patch.object(tv.os, "replace", side_effect=OSError("failure")):
                with self.assertRaises(OSError):
                    tv.publish_video(candidate, output, force=True)
            self.assertEqual(output.read_bytes(), b"old")
            tv.publish_video(candidate, output, force=True)
            self.assertEqual(output.read_bytes(), b"new")

    def test_output_validator_checks_all_properties(self):
        data = manifest()
        good = {"streams": [{"codec_type": "video", "width": 64, "height": 64,
                             "nb_read_frames": "8", "avg_frame_rate": "8/1", "duration": "1"}],
                "format": {"duration": "1"}}
        self.assertEqual(tv.output_validation_failures(good, data), [])
        for field, value in (("width", 32), ("height", 32), ("nb_read_frames", "7"),
                             ("avg_frame_rate", "7/1"), ("duration", "2"), ("duration", "nan")):
            with self.subTest(field=field, value=value):
                bad = copy.deepcopy(good)
                bad["streams"][0][field] = value
                self.assertTrue(tv.output_validation_failures(bad, data))
        bad = copy.deepcopy(good)
        bad["format"]["duration"] = "2"
        self.assertTrue(tv.output_validation_failures(bad, data))
        data["audio"] = {"file": "sound.wav"}
        self.assertTrue(tv.output_validation_failures(good, data))


@unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "FFmpeg is not installed")
class RecoveryFfmpegTests(unittest.TestCase):
    def test_optical_flow_cache_normalizes_each_unique_image_once(self):
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            ppm(root / "a.ppm", (255, 0, 0))
            ppm(root / "b.ppm", (0, 255, 0))
            ppm(root / "c.ppm", (0, 0, 255))
            data = manifest()
            data["shots"][0].update(end_image="c.ppm", interpolation="optical-flow",
                                     intermediate_images=["b.ppm"])
            result, log = self.render(root, data, "flow.mp4", "--strict")
            normalizations = [line for line in log.splitlines() if "-frames:v 1 " in line and "normalized" in line]
            self.assertEqual(len(normalizations), 3)
            self.assertEqual(result["frames"], 8)
            self.assertEqual(len(self.pixels(root / "flow.mp4")), 8)

    def render(self, root, data, output="result.mp4", *extra):
        path = root / "timeline.json"
        path.write_text(json.dumps(data))
        result = subprocess.run([sys.executable, str(SCRIPT), "render", str(path), "--output",
                                 str(root / output), "--preset", "ultrafast", "--force", *extra],
                                capture_output=True, text=True, check=True)
        return json.loads(result.stdout), result.stderr

    def pixels(self, output, width=64, height=64):
        result = subprocess.run(["ffmpeg", "-v", "error", "-xerror", "-i", str(output),
                                 "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
                                capture_output=True, check=True)
        size = width * height * 3
        return [result.stdout[i:i+size] for i in range(0, len(result.stdout), size)]

    def test_blend_pixel_endpoints_and_linear_weights(self):
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            ppm(root / "a.ppm", (255, 0, 0))
            ppm(root / "b.ppm", (0, 0, 255))
            data = manifest()
            result, _ = self.render(root, data)
            frames = self.pixels(root / "result.mp4")
            self.assertEqual(len(frames), 8)
            for i, frame in enumerate(frames):
                expected = (255*(1-i/7), 0, 255*i/7)
                self.assertTrue(all(abs(actual-value) < 9 for actual, value in zip(frame[:3], expected)), (i, frame[:3], expected))
            self.assertEqual(result["frames"], 8)

    def test_multikeyframe_camera_motion_matches_whole_shot(self):
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            # A textured gradient exposes crop/zoom resets despite lossy encoding.
            image = b"".join(bytes((x*4, y*4, (x+y)*2)) for y in range(64) for x in range(64))
            (root / "a.ppm").write_bytes(b"P6\n64 64\n255\n" + image)
            for motion in ("pan-right", "pan-left", "pan-up", "pan-down", "zoom-in", "zoom-out"):
                with self.subTest(motion=motion):
                    data = manifest()
                    data["shots"][0].update(end_image="a.ppm", motion=motion,
                                             intermediate_images=[{"image": "a.ppm", "at": 0.5}])
                    self.render(root, data, "multi.mp4")
                    data["shots"][0].update(interpolation="hold")
                    self.render(root, data, "hold.mp4")
                    multi, hold = self.pixels(root / "multi.mp4"), self.pixels(root / "hold.mp4")
                    self.assertEqual(len(multi), 8)
                    for actual, expected in zip(multi, hold):
                        self.assertLess(sum(abs(a-b) for a,b in zip(actual, expected))/len(actual), 3)

    def test_hold_override_ignores_unused_files(self):
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            ppm(root / "a.ppm", (255, 0, 0))
            data = manifest()
            data["shots"][0]["intermediate_images"] = ["missing.ppm"]
            result, _ = self.render(root, data, "hold.mp4", "--interpolation", "hold")
            frames = self.pixels(root / "hold.mp4")
            self.assertEqual(len(set(frames)), 1)
            self.assertEqual(result["interpolation_used"], {"one": "hold"})

    def test_cuts_use_stream_copy_with_quoted_paths(self):
        with tempfile.TemporaryDirectory(prefix="video's ") as name:
            root = Path(name)
            ppm(root / "a.ppm", (255, 0, 0))
            ppm(root / "b.ppm", (0, 0, 255))
            data = manifest()
            data["shots"] = [{"id": "one", "duration": 1, "start_image": "a.ppm", "interpolation": "hold"},
                             {"id": "two", "duration": 1, "start_image": "b.ppm", "interpolation": "hold"}]
            result, log = self.render(root, data)
            self.assertIn("-c:v copy", log)
            self.assertEqual(result["frames"], 16)
            frames = self.pixels(root / "result.mp4")
            self.assertEqual(len(frames), 16)
            self.assertGreater(frames[7][0], 240)
            self.assertGreater(frames[8][2], 240)

    def test_audio_and_transition_duration(self):
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            ppm(root / "a.ppm", (255, 0, 0))
            ppm(root / "b.ppm", (0, 0, 255))
            subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "sine=frequency=440:duration=0.1",
                            str(root / "audio.wav")], check=True)
            data = manifest()
            data["shots"] = [{"id": "one", "duration": 1, "start_image": "a.ppm", "interpolation": "hold",
                              "transition_to_next": {"type": "fade", "duration": 0.25}},
                             {"id": "two", "duration": 1, "start_image": "b.ppm", "interpolation": "hold"}]
            data["audio"] = {"file": "audio.wav", "loop": False}
            result, _ = self.render(root, data)
            self.assertEqual(result["frames"], 14)
            probe = tv.probe_video(root / "result.mp4")
            self.assertEqual(tv.output_validation_failures(probe, data), [])
            self.assertEqual(len(self.pixels(root / "result.mp4")), 14)


if __name__ == "__main__":
    unittest.main()
