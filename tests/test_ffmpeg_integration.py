from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "generate-timeline-video" / "scripts" / "timeline_video.py"


def write_ppm(path: Path, color: tuple[int, int, int]) -> None:
    width = 16
    height = 16
    header = f"P6\n{width} {height}\n255\n".encode("ascii")
    path.write_bytes(header + bytes(color) * width * height)


@unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "FFmpeg is not installed")
class FfmpegIntegrationTests(unittest.TestCase):
    def test_shared_cut_boundary_has_no_duplicate_encoded_frames(self) -> None:
        with tempfile.TemporaryDirectory() as temp_name:
            project = Path(temp_name)
            keyframes = project / "keyframes"
            output_dir = project / "output"
            keyframes.mkdir()
            output_dir.mkdir()
            write_ppm(keyframes / "start.ppm", (255, 0, 0))
            write_ppm(keyframes / "middle-a.ppm", (0, 255, 0))
            write_ppm(keyframes / "middle-b.ppm", (0, 255, 0))
            write_ppm(keyframes / "end.ppm", (0, 0, 255))
            manifest = project / "timeline.json"
            manifest.write_text(
                json.dumps(
                    {
                        "version": 1,
                        "title": "Boundary integration test",
                        "fps": 4,
                        "width": 16,
                        "height": 16,
                        "shots": [
                            {
                                "id": "shot-001",
                                "duration": 1.0,
                                "start_image": "keyframes/start.ppm",
                                "end_image": "keyframes/middle-a.ppm",
                                "interpolation": "blend",
                                "transition_to_next": {"type": "cut", "duration": 0},
                            },
                            {
                                "id": "shot-002",
                                "duration": 1.0,
                                "start_image": "keyframes/middle-b.ppm",
                                "end_image": "keyframes/end.ppm",
                                "interpolation": "blend",
                                "transition_to_next": {"type": "cut", "duration": 0},
                            },
                        ],
                    }
                ),
                encoding="utf-8",
            )
            output = output_dir / "result.mp4"
            render_command = [
                sys.executable,
                str(SCRIPT),
                "render",
                str(manifest),
                "--output",
                str(output),
                "--preset",
                "ultrafast",
            ]
            rendered = subprocess.run(
                render_command,
                check=True,
                text=True,
                capture_output=True,
            )
            self.assertIn('"frames": 8', rendered.stdout)
            self.assertIn('"deduplicated_cut_boundaries"', rendered.stdout)
            self.assertIn('"shot-001"', rendered.stdout)

            replaced = subprocess.run(
                [*render_command, "--force"],
                check=True,
                text=True,
                capture_output=True,
            )
            self.assertIn('"status": "rendered"', replaced.stdout)
            self.assertTrue(output.is_file())

            benchmarked = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "benchmark",
                    str(output),
                    "--baseline",
                    str(output),
                ],
                check=True,
                text=True,
                capture_output=True,
            )
            self.assertIn('"status": "benchmarked"', benchmarked.stdout)
            self.assertIn('"same_geometry": true', benchmarked.stdout)
            self.assertIn('"near_duplicate_pair_count_delta": 0', benchmarked.stdout)

            hashes_result = subprocess.run(
                [
                    "ffmpeg",
                    "-hide_banner",
                    "-loglevel",
                    "error",
                    "-i",
                    str(output),
                    "-f",
                    "framemd5",
                    "-",
                ],
                check=True,
                text=True,
                capture_output=True,
            )
            hashes = [
                line.rsplit(",", 1)[-1].strip()
                for line in hashes_result.stdout.splitlines()
                if line and not line.startswith("#")
            ]
            self.assertEqual(len(hashes), 8)
            self.assertNotEqual(hashes[3], hashes[4])

            fallback_output = output_dir / "rife-fallback.mp4"
            fallback = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "render",
                    str(manifest),
                    "--output",
                    str(fallback_output),
                    "--interpolation",
                    "rife",
                    "--rife-executable",
                    str(project / "missing-rife.exe"),
                    "--preset",
                    "ultrafast",
                ],
                check=True,
                text=True,
                capture_output=True,
            )
            self.assertIn("RIFE executable does not exist", fallback.stderr)
            self.assertIn("fallback-after-rife", fallback.stdout)
            self.assertTrue(fallback_output.is_file())

            protected_source = keyframes / "start.ppm"
            source_before = protected_source.read_bytes()
            unsafe = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "render",
                    str(manifest),
                    "--output",
                    str(protected_source),
                    "--force",
                ],
                check=False,
                text=True,
                capture_output=True,
            )
            self.assertEqual(unsafe.returncode, 2)
            self.assertIn("must not replace the timeline or source media", unsafe.stderr)
            self.assertEqual(protected_source.read_bytes(), source_before)


    def test_intermediate_keyframes_preserve_exact_frame_count(self) -> None:
        with tempfile.TemporaryDirectory() as temp_name:
            project = Path(temp_name)
            keyframes = project / "keyframes"
            output_dir = project / "output"
            keyframes.mkdir()
            output_dir.mkdir()
            write_ppm(keyframes / "start.ppm", (255, 0, 0))
            write_ppm(keyframes / "mid.ppm", (0, 255, 0))
            write_ppm(keyframes / "end.ppm", (0, 0, 255))
            manifest = project / "timeline.json"
            manifest.write_text(
                json.dumps(
                    {
                        "version": 1,
                        "title": "Intermediate keyframe integration test",
                        "fps": 4,
                        "width": 16,
                        "height": 16,
                        "shots": [
                            {
                                "id": "shot-001",
                                "duration": 1.25,
                                "start_image": "keyframes/start.ppm",
                                "intermediate_images": ["keyframes/mid.ppm"],
                                "end_image": "keyframes/end.ppm",
                                "interpolation": "blend",
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            output = output_dir / "result.mp4"
            rendered = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "render",
                    str(manifest),
                    "--output",
                    str(output),
                    "--preset",
                    "ultrafast",
                ],
                check=True,
                text=True,
                capture_output=True,
            )
            self.assertIn('"frames": 5', rendered.stdout)
            self.assertIn('"shot-001": 1', rendered.stdout)
            probed = subprocess.run(
                [sys.executable, str(SCRIPT), "probe", str(output), "--manifest", str(manifest)],
                check=True,
                text=True,
                capture_output=True,
            )
            self.assertIn('"nb_read_frames": "5"', probed.stdout)

if __name__ == "__main__":
    unittest.main()
