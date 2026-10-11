"""Output-level timing, temporal sampling, cache recovery and inspection tests."""
import io
import json
import shutil
import struct
import subprocess
import sys
import tempfile
import unittest
import zlib
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

from test_timeline_video import timeline_video as tv
from test_renderer_regressions import manifest, ppm


def png_bar(path, x, width=64):
    def chunk(kind, data):
        return struct.pack('!I', len(data)) + kind + data + struct.pack('!I', zlib.crc32(kind + data))
    row = bytes(255 if x <= n < x + 4 else 0 for n in range(width))
    raw = (b'\0' + row) * width
    path.write_bytes(b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('!2I5B', width, width, 8, 0, 0, 0, 0))
                     + chunk(b'IDAT', zlib.compress(raw)) + chunk(b'IEND', b''))


def pixels(path):
    return subprocess.run([tv.require_tool('ffmpeg'), '-v', 'error', '-i', str(path),
                           '-f', 'rawvideo', '-pix_fmt', 'gray', '-'], check=True, capture_output=True).stdout


class QualityUnitTests(unittest.TestCase):
    def test_explicit_times_do_not_shrink_in_later_half(self):
        shot = {'id': 'cat', 'duration': 2.5, 'start_image': 'a', 'end_image': 'z',
                'interpolation': 'blend', 'intermediate_images': [{'image': 'blink', 'at': 2.125}]}
        timing = tv.shot_timing(shot, 24)
        self.assertEqual(timing[1]['frame'], 51)
        self.assertEqual(timing[1]['error_seconds'], 0)
        self.assertEqual(timing[-1]['frame'], 59)
        self.assertAlmostEqual(timing[-1]['error_seconds'], -1/24)

    def test_colliding_events_fail_instead_of_silently_retiming(self):
        with self.assertRaises(tv.TimelineError):
            tv.distribute_timed_intervals(23, [0, .001, .002, 1], 1, fps=24)

    def test_timeout_reports_actionable_failure_and_resets_context(self):
        with tempfile.TemporaryDirectory() as name:
            with tv.render_context(None, 'unused', None, .05):
                with self.assertRaisesRegex(tv.TimelineError, 'timed out'):
                    tv.run([sys.executable, '-c', 'import time; time.sleep(3)'])
            self.assertEqual(tv._command_timeout.get(), 300)

    def test_motion_plan_is_idempotent_and_detects_stale_slots(self):
        with tempfile.TemporaryDirectory() as name:
            path = Path(name) / 'timeline.json'
            path.write_text(json.dumps(manifest()))
            args = tv.build_parser().parse_args(['plan-motion', str(path), '--write'])
            with redirect_stdout(io.StringIO()):
                tv.command_plan_motion(args)
            data = json.loads(path.read_text())
            data['shots'][0]['motion_plan'][0]['changes'] = [{'target': 'label', 'state': 'readable'}]
            path.write_text(json.dumps(data))
            with redirect_stdout(io.StringIO()):
                tv.command_plan_motion(args)
            self.assertEqual(json.loads(path.read_text()), data)
            tv.load_and_validate(path, require_files=False)
            data['shots'][0]['motion_plan'][1]['at'] = .5
            path.write_text(json.dumps(data))
            with self.assertRaisesRegex(tv.TimelineError, 'motion_plan'):
                tv.load_and_validate(path, require_files=False)
            with self.assertRaisesRegex(tv.TimelineError, 'obsolete'):
                tv.command_plan_motion(args)

    def test_model_content_change_invalidates_runtime_fingerprint(self):
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            for filename in ('ffmpeg', 'ffprobe', 'rife', 'flownet.param', 'flownet.bin'):
                (root/filename).write_bytes(b'v1')
            with mock.patch.object(tv, 'require_tool', return_value=str(root/'ffprobe')):
                with tv.render_context(root/'cache', str(root/'ffmpeg'), (root/'rife', root), 300):
                    first = tv._segment_cache.get()[1]
                (root/'flownet.bin').write_bytes(b'v2')
                with tv.render_context(root/'cache', str(root/'ffmpeg'), (root/'rife', root), 300):
                    self.assertNotEqual(first, tv._segment_cache.get()[1])
            self.assertIsNone(tv._segment_cache.get())


@unittest.skipUnless(shutil.which('ffmpeg') and shutil.which('ffprobe'), 'FFmpeg required')
class QualityIntegrationTests(unittest.TestCase):
    def render(self, root, data, output='result.mp4', cache=True):
        path = root / 'timeline.json'
        path.write_text(json.dumps(data))
        argv = ['render', str(path), '--output', str(root / output), '--force', '--preset', 'ultrafast', '--crf', '0']
        if cache:
            argv += ['--cache-dir', str(root / 'cache')]
        stream = io.StringIO()
        with redirect_stdout(stream):
            tv.command_render(tv.build_parser().parse_args(argv))
        return json.loads(stream.getvalue())

    def test_encoded_blink_peak_occurs_at_declared_frame(self):
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            ppm(root/'a.ppm', (0, 0, 0)); ppm(root/'b.ppm', (255, 255, 255))
            data = manifest({'id': 'blink', 'duration': 2.5, 'start_image': 'a.ppm', 'end_image': 'a.ppm',
                             'interpolation': 'blend', 'intermediate_images': [{'image': 'b.ppm', 'at': 2.125}]})
            data['fps'] = 24
            self.render(root, data)
            levels = pixels(root/'result.mp4')[::4096]
            self.assertEqual(len(levels), 60)
            self.assertEqual(max(range(len(levels)), key=levels.__getitem__), 51)

    def test_recursive_sampling_keeps_sharp_moving_edges_without_blend(self):
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            png_bar(root/'a.png', 4); png_bar(root/'b.png', 52)
            original_run = tv.run
            def oracle(command, **kwargs):
                if command[0] != 'rife-test':
                    return original_run(command, **kwargs)
                first = pixels(Path(command[command.index('-0')+1]))[:64]
                second = pixels(Path(command[command.index('-1')+1]))[:64]
                left = next(i for i, value in enumerate(first) if value > 200)
                right = next(i for i, value in enumerate(second) if value > 200)
                at = float(command[command.index('-s')+1])
                png_bar(Path(command[command.index('-o')+1]), int(left+(right-left)*at+.5))
                return subprocess.CompletedProcess(command, 0)
            with mock.patch.object(tv, 'run', side_effect=oracle):
                tv.render_rife(tv.require_tool('ffmpeg'), Path('rife-test'), root, 0, root/'a.png', root/'b.png',
                               root/'result.mp4', root, width=64, height=64, fps=24, frames=7,
                               include_endpoint=True, strategy='recursive', motion='static', preset='ultrafast', crf=0)
            raw = pixels(root/'result.mp4')
            self.assertEqual(len(raw), 7*4096)
            for index in range(7):
                row = raw[index*4096:index*4096+64]
                self.assertTrue(all(v < 4 or v > 251 for v in row), (index, list(row)))
                self.assertEqual(next(i for i, v in enumerate(row) if v > 200), 4+index*8)

    def test_cache_hits_source_invalidation_and_corruption_repair(self):
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            ppm(root/'a.ppm', (0, 0, 0)); ppm(root/'b.ppm', (255, 255, 255))
            first = self.render(root, manifest())
            self.assertEqual(first['segment_cache'][0]['cache'], 'miss')
            self.assertEqual(self.render(root, manifest())['segment_cache'][0]['cache'], 'hit')
            # A source edit invalidates despite using the same filename.
            ppm(root/'b.ppm', (200, 200, 200))
            changed = self.render(root, manifest())
            self.assertEqual(changed['segment_cache'][0]['cache'], 'miss')
            (root/'cache'/f"{changed['segment_cache'][0]['key']}.mp4").write_bytes(b'corrupt')
            self.assertEqual(self.render(root, manifest())['segment_cache'][0]['cache'], 'miss')

    def test_resume_only_renders_unfinished_pair(self):
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            for key, gray in [('a',0), ('b',128), ('c',255)]:
                ppm(root/f'{key}.ppm', (gray,gray,gray))
            data = manifest({'id':'one','duration':1,'start_image':'a.ppm','end_image':'c.ppm',
                             'interpolation':'blend','intermediate_images':[{'image':'b.ppm','at':.5}]})
            original = tv.render_shot_pair_uncached
            def interrupted(*args, **kwargs):
                if args[1]['id'].endswith('segment-2'):
                    raise tv.TimelineError('simulated interruption')
                return original(*args, **kwargs)
            with mock.patch.object(tv, 'render_shot_pair_uncached', side_effect=interrupted):
                with self.assertRaisesRegex(tv.TimelineError, 'interruption'):
                    self.render(root, data)
            result = self.render(root, data)
            self.assertEqual([e['cache'] for e in result['segment_cache']], ['hit','miss'])

    def test_fallback_is_not_cached_and_frame_rate_changes_invalidate(self):
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            ppm(root/'a.ppm', (0,0,0)); ppm(root/'b.ppm', (255,255,255))
            original = tv.render_shot_pair_uncached
            def fallback(*args, **kwargs):
                original(*args, **kwargs)
                return 'blend-fallback'
            with mock.patch.object(tv, 'render_shot_pair_uncached', side_effect=fallback):
                self.render(root, manifest())
            self.assertEqual(list((root/'cache').glob('*.mp4')), [])
            self.render(root, manifest())
            changed = manifest(); changed['fps'] = 12
            result = self.render(root, changed)
            self.assertEqual(result['segment_cache'][0]['cache'], 'miss')
            self.assertEqual(result['frames'], 12)

    def test_inspection_outputs_frames_without_claiming_visual_pass(self):
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            ppm(root/'a.ppm', (0,0,0)); ppm(root/'b.ppm', (255,255,255))
            self.render(root, manifest())
            args = tv.build_parser().parse_args(['inspect',str(root/'result.mp4'),'--manifest',str(root/'timeline.json'),
                                                '--output-dir',str(root/'review')])
            with redirect_stdout(io.StringIO()):
                tv.command_inspect(args)
            report = json.loads((root/'review/report.json').read_text())
            self.assertEqual(report['technical'], 'passed')
            self.assertEqual(report['review']['normal_speed_playback'], 'not_reviewed')
            self.assertEqual(len(list((root/'review').glob('sample-*.png'))), len(report['sample_frames']))
            self.assertTrue((root/'review/index.html').is_file())
            with self.assertRaisesRegex(tv.TimelineError, 'already exists'):
                tv.command_inspect(args)
