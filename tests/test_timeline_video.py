from __future__ import annotations

import importlib.util
import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "generate-timeline-video" / "scripts" / "timeline_video.py"
SPEC = importlib.util.spec_from_file_location("timeline_video", SCRIPT)
assert SPEC and SPEC.loader
timeline_video = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(timeline_video)


def completed(command: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(command, 0, "", "")


class TimelineVideoTests(unittest.TestCase):
    def test_shared_cut_boundary_detects_byte_identical_images(self) -> None:
        with tempfile.TemporaryDirectory() as temp_name:
            root = Path(temp_name)
            (root / "first.png").write_bytes(b"same-image")
            (root / "second.png").write_bytes(b"same-image")
            data = {
                "shots": [
                    {
                        "end_image": "first.png",
                        "transition_to_next": {"type": "cut", "duration": 0},
                    },
                    {"start_image": "second.png"},
                ]
            }
            self.assertEqual(timeline_video.shared_cut_boundaries(data, root), {0})
            data["shots"][0]["interpolation"] = "hold"
            self.assertEqual(timeline_video.shared_cut_boundaries(data, root), set())
            self.assertEqual(
                timeline_video.shared_cut_boundaries(data, root, interpolation_override="blend"),
                {0},
            )
            (root / "second.png").write_bytes(b"different")
            self.assertEqual(
                timeline_video.shared_cut_boundaries(data, root, interpolation_override="blend"),
                set(),
            )

    def test_blend_uses_open_interval_for_shared_boundary(self) -> None:
        commands: list[list[str]] = []

        def fake_run(command: list[str], **_: object) -> subprocess.CompletedProcess[str]:
            commands.append(command)
            return completed(command)

        with mock.patch.object(timeline_video, "run", side_effect=fake_run):
            timeline_video.render_blend(
                "ffmpeg",
                Path("start.png"),
                Path("end.png"),
                Path("out.mp4"),
                width=64,
                height=64,
                fps=4,
                frames=4,
                include_endpoint=False,
                motion="static",
                preset="ultrafast",
                crf=18,
            )

        graph = commands[0][commands[0].index("-filter_complex") + 1]
        self.assertIn("N/4", graph)
        self.assertNotIn("N/3", graph)

    def test_optical_flow_input_rate_respects_endpoint_mode(self) -> None:
        commands: list[list[str]] = []

        def fake_normalize(
            _ffmpeg: str,
            _source: Path,
            target: Path,
            _width: int,
            _height: int,
        ) -> None:
            target.write_bytes(b"frame")

        def fake_run(command: list[str], **_: object) -> subprocess.CompletedProcess[str]:
            commands.append(command)
            return completed(command)

        with tempfile.TemporaryDirectory() as temp_name:
            root = Path(temp_name)
            with (
                mock.patch.object(timeline_video, "normalize_image", side_effect=fake_normalize),
                mock.patch.object(timeline_video, "run", side_effect=fake_run),
            ):
                timeline_video.render_optical_flow(
                    "ffmpeg",
                    Path("start.png"),
                    Path("end.png"),
                    root / "out.mp4",
                    root,
                    width=64,
                    height=64,
                    fps=4,
                    frames=4,
                    include_endpoint=False,
                    profile="balanced",
                    motion="static",
                    preset="ultrafast",
                    crf=18,
                )

        command = commands[0]
        self.assertEqual(command[command.index("-framerate") + 1], "4/4")
        video_filter = command[command.index("-vf") + 1]
        self.assertIn("me=epzs", video_filter)
        self.assertIn("search_param=32", video_filter)

    def test_recursive_interval_count_uses_power_of_two_grid(self) -> None:
        self.assertEqual(timeline_video.recursive_interval_count(1), 1)
        self.assertEqual(timeline_video.recursive_interval_count(35), 64)
        self.assertEqual(timeline_video.recursive_interval_count(36), 64)
        self.assertEqual(timeline_video.recursive_interval_count(65), 128)

    def test_recursive_rife_uses_midpoints_and_exact_target_rate(self) -> None:
        commands: list[list[str]] = []

        def fake_normalize(
            _ffmpeg: str,
            _source: Path,
            target: Path,
            _width: int,
            _height: int,
        ) -> None:
            target.write_bytes(b"frame")

        def fake_run(command: list[str], **_: object) -> subprocess.CompletedProcess[str]:
            commands.append(command)
            if command[0] == "rife":
                Path(command[command.index("-o") + 1]).write_bytes(b"midpoint")
            return completed(command)

        with tempfile.TemporaryDirectory() as temp_name:
            root = Path(temp_name)
            with (
                mock.patch.object(timeline_video, "normalize_image", side_effect=fake_normalize),
                mock.patch.object(timeline_video, "run", side_effect=fake_run),
            ):
                timeline_video.render_rife(
                    "ffmpeg",
                    Path("rife"),
                    Path("rife-v4.6"),
                    None,
                    Path("start.png"),
                    Path("end.png"),
                    root / "out.mp4",
                    root,
                    width=64,
                    height=64,
                    fps=4,
                    frames=4,
                    include_endpoint=True,
                    strategy="recursive",
                    motion="static",
                    preset="ultrafast",
                    crf=18,
                )

        rife_commands = [command for command in commands if command[0] == "rife"]
        self.assertEqual(len(rife_commands), 3)
        self.assertTrue(
            all(command[command.index("-s") + 1] == "0.500000000" for command in rife_commands)
        )
        encode_command = commands[-1]
        self.assertEqual(encode_command[encode_command.index("-framerate") + 1], "16/3")
        video_filter = encode_command[encode_command.index("-vf") + 1]
        self.assertIn("framerate=fps=4", video_filter)

    def test_rife_command_uses_arbitrary_timestep_and_gpu(self) -> None:
        command = timeline_video.rife_command(
            Path("rife.exe"),
            Path("rife-v4.6"),
            Path("start.png"),
            Path("end.png"),
            Path("middle.png"),
            1 / 3,
            -1,
        )
        self.assertIn("0.333333333", command)
        self.assertEqual(command[-2:], ["-g", "-1"])

    def test_rife_runtime_requires_v4_model(self) -> None:
        with tempfile.TemporaryDirectory() as temp_name:
            root = Path(temp_name)
            executable = root / "rife.exe"
            executable.write_bytes(b"exe")
            executable.chmod(0o755)
            good_model = root / "rife-v4.6"
    def test_distribute_intervals_keeps_final_open_interval(self) -> None:
        self.assertEqual(timeline_video.distribute_intervals(4, 2), [2, 2])
        self.assertEqual(timeline_video.distribute_intervals(5, 2, last_minimum=2), [2, 3])
        with self.assertRaises(timeline_video.TimelineError):
            timeline_video.distribute_intervals(2, 2, last_minimum=2)

            good_model.mkdir()
            for filename in ("flownet.param", "flownet.bin"):
                (good_model / filename).write_bytes(b"model")
            self.assertEqual(
                timeline_video.resolve_rife_runtime(executable, good_model),
                (executable.resolve(), good_model.resolve()),
            )
            bad_model = root / "rife-v2.3"
            bad_model.mkdir()
            with self.assertRaises(timeline_video.TimelineError):
                timeline_video.resolve_rife_runtime(executable, bad_model)
            incomplete_model = root / "rife-v4.5"
            incomplete_model.mkdir()
            with self.assertRaisesRegex(timeline_video.TimelineError, "incomplete"):
                timeline_video.resolve_rife_runtime(executable, incomplete_model)

    def test_rife_missing_runtime_falls_back_unless_strict(self) -> None:
        data = {"width": 64, "height": 64, "fps": 4}
        shot = {
            "id": "shot-001",
            "duration": 1.0,
            "start_image": "start.png",
            "end_image": "end.png",
            "interpolation": "rife",
        }
        with tempfile.TemporaryDirectory() as temp_name:
            root = Path(temp_name)
            with mock.patch.object(timeline_video, "render_optical_flow") as optical_flow:
                method = timeline_video.render_shot(
                    data,
                    shot,
                    root,
                    root / "out.mp4",
                    root,
                    ffmpeg="ffmpeg",
                    interpolation_override=None,
                    optical_flow_profile_override=None,
                    rife_strategy_override=None,
                    include_endpoint=True,
                    rife_runtime=None,
                    rife_gpu=None,
                    strict=False,
                    preset="ultrafast",
                    crf=18,
                )
            optical_flow.assert_called_once()
            self.assertEqual(method, "optical-flow:balanced-fallback")

            with self.assertRaises(timeline_video.TimelineError):
                timeline_video.render_shot(
                    data,
                    shot,
                    root,
                    root / "strict.mp4",
                    root,
                    ffmpeg="ffmpeg",
                    interpolation_override=None,
                    optical_flow_profile_override=None,
                    rife_strategy_override=None,
                    include_endpoint=True,
                    rife_runtime=None,
                    rife_gpu=None,
                    strict=True,
                    preset="ultrafast",
                    crf=18,
                )

    def test_rife_manifest_is_valid_but_warns_for_sparse_keyframes(self) -> None:
        with tempfile.TemporaryDirectory() as temp_name:
            root = Path(temp_name)
            manifest = root / "timeline.json"
            manifest.write_text(
                json.dumps(
                    {
                        "version": 1,
                        "title": "RIFE test",
                        "fps": 24,
                        "width": 64,
                        "height": 64,
                        "shots": [
                            {
                                "id": "shot-001",
                                "duration": 1.5,
                                "start_image": "start.png",
                                "end_image": "end.png",
                                "interpolation": "rife",
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            data, warnings = timeline_video.load_and_validate(manifest, require_files=False)
            self.assertEqual(data["shots"][0]["interpolation"], "rife")
            self.assertEqual(timeline_video.rife_strategy_for(data["shots"][0]), "recursive")
            self.assertTrue(any("additional keyframes" in warning for warning in warnings))

    def test_parse_signalstats_ignores_first_frame(self) -> None:
        output = "\n".join(
            [
                "frame:0    pts:0       pts_time:0",
                "lavfi.signalstats.YDIF=0",
                "frame:1    pts:1       pts_time:0.04",
                "lavfi.signalstats.YDIF=0.05",
                "frame:2    pts:2       pts_time:0.08",
                "lavfi.signalstats.YDIF=0.5",
            ]
        )
        self.assertEqual(timeline_video.parse_signalstats(output), [(1, 0.05), (2, 0.5)])

    def test_largest_temporal_jerks_reports_frame_location(self) -> None:
        events = timeline_video.largest_temporal_jerks(
            [(1, 0.1), (2, 0.2), (3, 1.2), (4, 1.1)],
            limit=2,
        )
        self.assertEqual(events[0]["frame"], 3)
        self.assertAlmostEqual(events[0]["absolute_change"], 1.0)
        self.assertEqual(len(events), 2)

    def test_compare_benchmarks_reports_metric_deltas(self) -> None:
        baseline = {
            "width": 64,
            "height": 64,
            "fps": 24.0,
            "frames": 10,
            "near_duplicate_pairs": [{}, {}],
            "temporal_luma_difference": {"median": 1.0, "p95": 2.0},
            "temporal_luma_jerk": {"p95": 0.8},
        }
        candidate = {
            "width": 64,
            "height": 64,
            "fps": 24.0,
            "frames": 10,
            "near_duplicate_pairs": [{}],
            "temporal_luma_difference": {"median": 1.2, "p95": 2.5},
            "temporal_luma_jerk": {"p95": 0.3},
        }
        comparison = timeline_video.compare_benchmarks(candidate, baseline)
        self.assertTrue(comparison["same_geometry"])
        self.assertEqual(comparison["near_duplicate_pair_count_delta"], -1)
        self.assertAlmostEqual(comparison["temporal_luma_jerk_p95_delta"], -0.5)


if __name__ == "__main__":
    def test_intermediate_keyframes_are_accepted_for_articulated_motion(self) -> None:
        with tempfile.TemporaryDirectory() as temp_name:
            root = Path(temp_name)
            manifest = root / "timeline.json"
            manifest.write_text(
                json.dumps(
                    {
                        "version": 1,
                        "title": "Motion keyframe test",
                        "fps": 24,
                        "width": 64,
                        "height": 64,
                        "shots": [
                            {
                                "id": "shot-001",
                                "duration": 1.5,
                                "start_image": "start.png",
                                "intermediate_images": ["mid.png"],
                                "end_image": "end.png",
                                "interpolation": "rife",
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            data, warnings = timeline_video.load_and_validate(manifest, require_files=False)
            self.assertEqual(data["shots"][0]["intermediate_images"], ["mid.png"])
            self.assertFalse(any("only two keyframes" in warning for warning in warnings))

    unittest.main()
