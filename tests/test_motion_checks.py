"""Subject-independent plans and measurements, including actual encoded output."""
import copy
import io
import json
import shutil
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from test_timeline_video import timeline_video as tv
from test_renderer_regressions import manifest, ppm
from test_quality_workflow import pixels


def track(**overrides):
    data = {"id": "path", "target": "object", "property": "x", "space": "screen", "unit": "pixels",
            "behavior": "continuous", "tolerance": .1,
            "samples": [{"frame": n, "value": v} for n, v in ((0, 0), (4, 4), (7, 7))]}
    data.update(overrides)
    return data


def shot(check):
    return dict(manifest()["shots"][0], motion_checks=[check])


def snapshot(check):
    return dict(check, shot="one")


def measured(check, values=None):
    samples = copy.deepcopy(check["samples"])
    if values is not None:
        for sample, value in zip(samples, values):
            sample["value"] = value
    return {"video_sha256": "video", "tracks": [{"shot": "one", "id": check["id"], "samples": samples}]}


class MotionCheckTests(unittest.TestCase):
    def test_properties_are_not_dispatched_by_subject_keywords(self):
        for target, prop, unit in (("limb", "tip", "pixels"), ("product", "angle", "degrees"),
                                   ("landmark", "parallax", "pixels"), ("cloud", "radius", "pixels"),
                                   ("title", "opacity", "percent"), ("light", "intensity", "percent")):
            with self.subTest(target=target):
                check = track(target=target, property=prop, unit=unit, min_speed=7, max_speed=9, max_acceleration=.01)
                self.assertEqual(tv.motion_check_errors(shot(check), 8), [])
                self.assertEqual(tv.assess_motion_checks([snapshot(check)], measured(check), "video", 8)["status"], "pass")

    def test_nonuniform_times_and_vector_reversal_use_velocity_not_just_speed(self):
        samples = [{"frame": n, "value": [v, 0]} for n, v in ((0, 0), (2, 2), (6, -2))]
        rates = tv.motion_rates(samples, 8)
        self.assertEqual(rates["speeds"], [8, 8])
        self.assertAlmostEqual(rates["accelerations"][0], 16 / .375)
        check = track(samples=samples, max_acceleration=20)
        self.assertTrue(any("acceleration" in e for e in tv.motion_check_errors(shot(check), 8)))

    def test_sample_frequency_does_not_change_constant_velocity(self):
        for fps, samples in ((8, [(0, 0), (1, 1), (7, 7)]), (16, [(0, 0), (2, 1), (14, 7)])):
            rates = tv.motion_rates([{"frame": n, "value": v} for n, v in samples], fps)
            self.assertEqual(rates, {"speeds": [8, 8], "accelerations": [0]})

    def test_constant_event_and_intentional_stop_do_not_require_movement(self):
        for behavior, values in (("constant", [1, 1, 1]), ("event", [0, 1, 0]), ("continuous", [0, 0, 1])):
            check = track(behavior=behavior)
            for sample, value in zip(check["samples"], values):
                sample["value"] = value
            data = shot(check)
            if behavior == "constant":
                data.update(interpolation="hold", motion="static")
            self.assertEqual(tv.motion_check_errors(data, 8), [])
            self.assertEqual(tv.assess_motion_checks([snapshot(check)], measured(check), "video", 8)["status"], "pass")

    def test_conflicting_properties_and_static_hold_are_rejected(self):
        for data in (shot(track(behavior="constant")),
                     dict(shot(track()), interpolation="hold", motion="static"),
                     dict(shot(track()), motion_checks=[track(), track(id="other")])):
            self.assertTrue(tv.motion_check_errors(data, 8))
        # Different reference frames describe different properties; camera-only motion is valid.
        data = dict(shot(track()), interpolation="hold", motion="pan-right")
        data["motion_checks"].append(track(id="world", space="scene"))
        self.assertEqual(tv.motion_check_errors(data, 8), [])

    def test_invalid_numeric_plans_fail_validation_before_media_generation(self):
        mutations = [lambda c: c.update(samples=[]), lambda c: c.update(tolerance=-1),
                     lambda c: c.update(max_speed=float("nan")), lambda c: c.update(behavior="unknown"),
                     lambda c: c.update(min_speed=10, max_speed=2),
                     lambda c: c["samples"][1].update(frame=True),
                     lambda c: c["samples"][1].update(frame=0),
                     lambda c: c["samples"][1].update(frame=8),
                     lambda c: c["samples"][1].update(value=[1, 2]),
                     lambda c: c["samples"][1].update(value=float("inf")),
                     lambda c: c["samples"].__setitem__(1, None),
                     lambda c: c.update(samples=c["samples"][:2], max_acceleration=1),
                     lambda c: c.update(behavior="event", max_speed=9)]
        with tempfile.TemporaryDirectory() as name:
            path = Path(name) / "timeline.json"
            for mutate in mutations:
                check = track(); mutate(check)
                with self.subTest(check=check):
                    path.write_text(json.dumps(manifest(shot(check))))
                    with self.assertRaises(tv.TimelineError):
                        tv.load_and_validate(path, require_files=False)

    def test_observed_stall_and_jump_fail_despite_loose_value_tolerance(self):
        check = track(tolerance=10, min_speed=6, max_speed=10)
        result = tv.assess_motion_checks([snapshot(check)], measured(check, [0, 0, 7]), "video", 8)
        self.assertEqual(result["status"], "needs_revision")
        self.assertEqual(len(result["reasons"]), 2)

    def test_observed_geometry_drift_fails_without_rate_limits(self):
        check = track(behavior="constant", samples=[{"frame": 0, "value": [1, 1]}, {"frame": 7, "value": [1, 1]}])
        self.assertEqual(tv.assess_motion_checks([snapshot(check)], measured(check, [[1, 1], [1.5, 1]]), "video", 8)["status"], "needs_revision")

    def test_missing_stale_or_misaligned_observations_never_pass(self):
        check = track()
        variants = [None, {}, measured(check, [0, None, 7]), measured(check, [0, True, 7])]
        stale = measured(check); stale["video_sha256"] = "old"; variants.append(stale)
        reordered = measured(check); reordered["tracks"][0]["samples"].reverse(); variants.append(reordered)
        duplicate = measured(check); duplicate["tracks"] *= 2; variants.append(duplicate)
        unknown = measured(check); unknown["tracks"][0]["id"] = "unknown"; variants.append(unknown)
        for observations in variants:
            with self.subTest(observations=observations):
                self.assertEqual(tv.assess_motion_checks([snapshot(check)], observations, "video", 8)["status"], "needs_review")

    def test_measured_constraints_and_visual_evidence_both_matter(self):
        check = track()
        report = {"technical": "passed", "video_sha256": "video", "motion_checks": [snapshot(check)], "motion_fps": 8}
        review = {"source_pairs": "pass", "intermediate_frames": "pass", "normal_speed_playback": "pass", "issues": []}
        self.assertEqual(tv.assess_review(report, review, "video")["delivery_status"], "needs_review")
        self.assertEqual(tv.assess_review(report, review, "video", measured(check, [0, 0, 7]))["delivery_status"], "needs_revision")
        self.assertEqual(tv.assess_review(report, review, "video", measured(check))["delivery_status"], "ready_for_delivery")
        review["normal_speed_playback"] = "not_reviewed"
        self.assertEqual(tv.assess_review(report, review, "video", measured(check))["delivery_status"], "needs_review")


@unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "FFmpeg required")
class MotionOutputTests(unittest.TestCase):
    def render_inspect(self, root, data):
        path = root / "timeline.json"; path.write_text(json.dumps(data))
        with redirect_stdout(io.StringIO()):
            tv.command_render(tv.build_parser().parse_args(["render", str(path), "--output", str(root / "test.mp4"),
                                                           "--preset", "ultrafast", "--crf", "0"]))
            tv.command_inspect(tv.build_parser().parse_args(["inspect", str(root / "test.mp4"), "--manifest", str(path),
                                                            "--output-dir", str(root / "review")]))
        return json.loads((root / "review/report.json").read_text())

    def test_actual_encoded_brightness_detects_bad_timing_not_just_recorded_pass(self):
        for stalled in (False, True):
            with self.subTest(stalled=stalled), tempfile.TemporaryDirectory() as name:
                root = Path(name)
                ppm(root / "a.ppm", (0, 0, 0)); ppm(root / "b.ppm", (255, 255, 255))
                check = track(property="mean-luma", unit="gray8", tolerance=3, min_speed=270, max_speed=310,
                              samples=[{"frame": n, "value": n * 255 / 7} for n in (0, 3, 7)])
                data = manifest(shot(check))
                if stalled:
                    data["shots"][0]["intermediate_images"] = [{"at": 3 / 8, "image": "a.ppm"}]
                report = self.render_inspect(root, data)
                observations = json.loads((root / "review/motion-observations.json").read_text())
                self.assertTrue(all(s["value"] is None for s in observations["tracks"][0]["samples"]))
                raw = pixels(root / "test.mp4")
                for sample in observations["tracks"][0]["samples"]:
                    frame = sample["frame"]
                    sample["value"] = sum(raw[frame * 4096:(frame + 1) * 4096]) / 4096
                (root / "review/motion-observations.json").write_text(json.dumps(observations))
                # Fixture visual outcomes isolate the numeric gate; no claim of automated playback QA.
                review = {"source_pairs": "pass", "intermediate_frames": "pass", "normal_speed_playback": "pass", "issues": []}
                (root / "review/review.json").write_text(json.dumps(review))
                with redirect_stdout(io.StringIO()):
                    code = tv.command_review_status(tv.build_parser().parse_args(["review-status", str(root / "review"), "--write"]))
                self.assertEqual(code, 2 if stalled else 0)
                result = json.loads((root / "review/report.json").read_text())
                self.assertEqual(result["delivery_status"], "needs_revision" if stalled else "ready_for_delivery")
                self.assertTrue(set((0, 3, 7)).issubset(report["sample_frames"]))

    def test_inspection_maps_second_shot_measurements_through_transition_overlap(self):
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            ppm(root / "a.ppm", (0, 0, 0)); ppm(root / "b.ppm", (255, 255, 255))
            first = dict(manifest()["shots"][0], transition_to_next={"type": "fade", "duration": .25})
            # A static source can change on screen during its incoming fade.
            second = dict(shot(track()), id="second", interpolation="hold", start_image="b.ppm")
            data = manifest(); data["shots"] = [first, second]
            report = self.render_inspect(root, data)
            frames = [s["frame"] for s in report["motion_checks"][0]["samples"]]
            self.assertEqual(frames, [6, 10, 13])
            self.assertTrue(set(frames).issubset(report["sample_frames"]))
            self.assertEqual(report["motion_checks"][0]["shot"], "second")


if __name__ == "__main__":
    unittest.main()
