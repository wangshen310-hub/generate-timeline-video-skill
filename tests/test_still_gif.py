import importlib.util
import json
from pathlib import Path
import shutil
import subprocess
import struct
import tempfile
import unittest
import zlib
from unittest import mock

SCRIPT = Path(__file__).resolve().parents[1] / 'generate-timeline-video/scripts/still_gif.py'
spec = importlib.util.spec_from_file_location('still_gif', SCRIPT)
gif = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gif)


class GifTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.manifest = self.root / 'gif.json'
        self.data = {'version': 1, 'width': 32, 'height': 24, 'loop': True,
                     'frames': [{'image': '红.ppm', 'duration_ms': 70},
                                {'image': 'blue.ppm', 'duration_ms': 130},
                                {'image': '红.ppm', 'duration_ms': 210}]}
        for name, rgb in [('红.ppm', (255, 0, 0)), ('blue.ppm', (0, 0, 255))]:
            (self.root / name).write_bytes(b'P6\n32 24\n255\n' + bytes(rgb) * 32 * 24)
        self.save()

    def save(self):
        self.manifest.write_text(json.dumps(self.data), encoding='utf-8')

    def test_manifest_rejects_unrepresentable_and_browser_clamped_timing(self):
        for delay in (0, 10, 25, 99.0, True, 655360):
            self.data['frames'][0]['duration_ms'] = delay
            self.save()
            with self.subTest(delay=delay), self.assertRaises(ValueError):
                gif.load_manifest(self.manifest)

    def test_missing_assets_only_allowed_for_planning(self):
        self.data['frames'][0]['image'] = 'missing.png'
        self.save()
        gif.load_manifest(self.manifest, allow_missing=True)
        with self.assertRaises(ValueError):
            gif.load_manifest(self.manifest)

    def test_video_manifest_options_rejected(self):
        for key in ('interpolation', 'fps', 'shots', 'audio'):
            self.data[key] = None
            self.save()
            with self.assertRaises(ValueError):
                gif.load_manifest(self.manifest)
            del self.data[key]

    def test_malformed_gif_rejected(self):
        bad = self.root / 'bad.gif'
        for blob in (b'', b'GIF89a', b'notgif'):
            bad.write_bytes(blob)
            with self.assertRaises(ValueError):
                gif.inspect_gif(bad)

    def test_output_protects_sources_and_existing_files(self):
        source = self.root / 'source.gif'
        source.write_bytes(b'source')
        self.data['frames'][0]['image'] = 'source.gif'
        self.save()
        with self.assertRaises(ValueError):
            gif.render(self.manifest, source, force=True)
        target = self.root / 'output.gif'
        target.write_bytes(b'keep')
        with self.assertRaises(FileExistsError):
            gif.render(self.manifest, target)
        self.assertEqual(target.read_bytes(), b'keep')


@unittest.skipUnless(shutil.which('ffmpeg'), 'FFmpeg required')
class GifIntegrationTests(unittest.TestCase):
    setUp = GifTests.setUp
    save = GifTests.save
    def test_order_exact_timing_loop_and_decoded_pixels(self):
        target = self.root / "输出 ' space.gif"
        report = gif.render(self.manifest, target)
        self.assertEqual(report['durations_ms'], [70, 130, 210])
        self.assertEqual(report['loop_count'], 0)
        self.assertEqual(report['visual_status'], 'not_reviewed')
        decoded = subprocess.run(['ffmpeg', '-v', 'error', '-ignore_loop', '1', '-i', str(target),
                                  '-fps_mode', 'passthrough', '-f', 'rawvideo', '-pix_fmt', 'rgb24', '-'],
                                 capture_output=True, check=True).stdout
        self.assertEqual(len(decoded), 3 * 32 * 24 * 3)
        pixels = [tuple(decoded[i * 32 * 24 * 3:i * 32 * 24 * 3 + 3]) for i in range(3)]
        self.assertEqual(pixels, [(255, 0, 0), (0, 0, 255), (255, 0, 0)])

    @unittest.skipUnless(shutil.which('ffprobe'), 'FFprobe required')
    def test_independent_probe_timestamps(self):
        target = self.root / 'timed.gif'
        gif.render(self.manifest, target)
        result = subprocess.run(['ffprobe', '-v', 'error', '-ignore_loop', '1', '-show_frames',
                                 '-of', 'json', str(target)], capture_output=True, text=True, check=True)
        frames = json.loads(result.stdout)['frames']
        self.assertEqual([round(float(f['pts_time']), 2) for f in frames], [0, .07, .2])

    def test_transparency_and_aspect_ratio_flatten_to_white(self):
        def chunk(kind, body):
            return struct.pack('>I', len(body)) + kind + body + struct.pack('>I', zlib.crc32(kind + body))

        source = self.root / 'transparent.png'
        source.write_bytes(b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', 8, 24, 8, 6, 0, 0, 0))
                           + chunk(b'IDAT', zlib.compress((b'\0' + bytes((255, 0, 0, 0)) * 8) * 24))
                           + chunk(b'IEND', b''))
        self.data['frames'] = [{'image': source.name, 'duration_ms': 100}]
        self.save()
        target = self.root / 'white.gif'
        gif.render(self.manifest, target)
        decoded = subprocess.run(['ffmpeg', '-v', 'error', '-ignore_loop', '1', '-i', str(target),
                                  '-frames:v', '1', '-f', 'rawvideo', '-pix_fmt', 'rgb24', '-'],
                                 capture_output=True, check=True).stdout
        self.assertEqual(decoded, b'\xff' * 32 * 24 * 3)

    def test_one_frame_no_loop_and_repeated_frames(self):
        self.data['loop'] = False
        self.data['frames'] = [self.data['frames'][0]]
        self.save()
        target = self.root / 'once.gif'
        self.assertIsNone(gif.render(self.manifest, target)['loop_count'])
        self.data['frames'] *= 3
        self.save()
        self.assertEqual(gif.render(self.manifest, target, force=True)['durations_ms'], [70, 70, 70])

    def test_failed_validation_preserves_existing_output(self):
        target = self.root / 'safe.gif'
        target.write_bytes(b'original')
        with mock.patch.object(gif, 'verify', side_effect=ValueError('invalid')):
            with self.assertRaises(ValueError):
                gif.render(self.manifest, target, force=True)
        self.assertEqual(target.read_bytes(), b'original')

    def test_atomic_create_refuses_concurrent_output(self):
        target = self.root / 'race.gif'
        original = gif.verify

        def verify_and_race(*args):
            report = original(*args)
            target.write_bytes(b'other-writer')
            return report

        with mock.patch.object(gif, 'verify', side_effect=verify_and_race):
            with self.assertRaises(FileExistsError):
                gif.render(self.manifest, target)
        self.assertEqual(target.read_bytes(), b'other-writer')
