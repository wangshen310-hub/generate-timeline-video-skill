import importlib.util
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

SCRIPT = Path(__file__).resolve().parents[1] / 'pic2gif/scripts/still_gif.py'
spec = importlib.util.spec_from_file_location('review_core', SCRIPT)
core = importlib.util.module_from_spec(spec)
spec.loader.exec_module(core)
review = core.workflow()


def plan(intent='motion'):
    return {'intent': intent, 'source_mode': 'provided', 'summary': 'Measured sequence',
            'measurements': [], 'fixed_regions': []}


def manifest():
    return {'version': 1, 'width': 32, 'height': 24, 'loop': True, 'plan': plan(),
            'frames': [{'image': 'a.ppm', 'duration_ms': 100, 'state': 'first'},
                       {'image': 'b.ppm', 'duration_ms': 200, 'state': 'second'},
                       {'image': 'c.ppm', 'duration_ms': 400, 'state': 'third'}]}


def measurement():
    return {'id': 'position', 'property': 'position', 'space': 'screen', 'unit': 'px',
            'expected': [0, 1, 3], 'tolerance': 3, 'max_speed': 20, 'max_acceleration': 100}


class PlanTests(unittest.TestCase):
    def test_loop_edges_use_outgoing_exposure_and_vector_acceleration(self):
        d, c = manifest(), measurement()
        errors, edges = review.measure(c, [0, 1, 3], d)
        self.assertEqual(errors, [])
        self.assertEqual([e['seconds'] for e in edges], [.1, .2, .4])
        self.assertEqual([e['velocity'] for e in edges], [[10], [10], [-7.5]])
        self.assertAlmostEqual(edges[-1]['acceleration_to_next_edge'], 70)
        errors, _ = review.measure(c, [0, 1, 6], d)
        self.assertTrue(any('speed' in e for e in errors))

    def test_one_way_has_no_artificial_closing_edge(self):
        d = manifest()
        d['loop'] = False
        _, edges = review.measure(measurement(), [0, 1, 3], d)
        self.assertEqual(len(edges), 2)

    def test_plan_rejects_empty_generated_state_and_inconsistent_limits(self):
        d = manifest()
        d['plan']['source_mode'] = 'generated'
        with self.assertRaises(ValueError):
            review.plan_check(d)
        d['plan']['source_mode'] = 'provided'
        c = measurement()
        c['max_speed'] = 1
        d['plan']['measurements'] = [c]
        with self.assertRaisesRegex(ValueError, 'contradict'):
            review.plan_check(d)

    def test_invalid_roi_nonfinite_and_dimension_mismatch(self):
        for rect in ([0, 0, 0, 1], [.8, 0, .5, 1], [0, float('nan'), 1, 1]):
            d = manifest()
            d['plan']['fixed_regions'] = [{'id': 'fixed', 'rect': rect, 'max_mae': 1}]
            with self.subTest(rect=rect), self.assertRaises(ValueError):
                review.plan_check(d)
        for values in ([0, True, 3], [0, float('inf'), 3], [0, [1, 2], 3]):
            with self.subTest(values=values), self.assertRaises(ValueError):
                review.measure(measurement(), values, manifest())

    def test_init_counts_existing_and_preserves_bytes(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / 'images').mkdir()
            old = root / 'images/frame-000.png'
            old.write_bytes(b'original-source')
            result = subprocess.run([sys.executable, str(SCRIPT), 'init', str(root), '--frames', '2'],
                                    text=True, capture_output=True, check=True)
            parsed = json.loads(result.stdout)
            self.assertEqual((parsed['missing_images'], parsed['existing_images']), (1, 1))
            self.assertEqual(parsed['existing_paths'], ['images/frame-000.png'])
            self.assertEqual(old.read_bytes(), b'original-source')


@unittest.skipUnless(shutil.which('ffmpeg'), 'FFmpeg required')
class ReviewIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.d = manifest()
        self.manifest = self.root / 'gif.json'
        self.output = self.root / 'preview.gif'
        self.directory = self.root / 'review'
        for name, rgb in [('a', (255, 0, 0)), ('b', (0, 0, 255)), ('c', (0, 255, 0))]:
            (self.root / (name + '.ppm')).write_bytes(b'P6\n32 24\n255\n' + bytes(rgb) * 32 * 24)

    def render_inspect(self):
        self.manifest.write_text(json.dumps(self.d), encoding='utf-8')
        core.render(self.manifest, self.output)
        review.inspect(self.manifest, self.output, self.directory, core.api())

    def record_acceptance(self):
        path = self.directory / 'review.json'
        r = json.loads(path.read_text(encoding='utf-8'))
        for item in r['checks'].values():
            item.update(status='pass', note='Synthetic fixture assertion; no claim of creative quality')
        path.write_text(json.dumps(r), encoding='utf-8')
        return r

    def test_pending_blocked_and_recorded_acceptance_publishes_same_bytes(self):
        self.render_inspect()
        self.assertEqual(review.review_status(self.directory, core.api())['status'], 'pending')
        with self.assertRaisesRegex(ValueError, 'pending'):
            review.publish(self.directory, self.root / 'final.gif', False, core.api())
        self.record_acceptance()
        result = review.publish(self.directory, self.root / 'final.gif', False, core.api())
        self.assertEqual(result['delivery_status'], 'published')
        self.assertEqual((self.root / 'final.gif').read_bytes(), self.output.read_bytes())

    def test_deleted_checks_and_revise_cannot_be_accepted(self):
        self.render_inspect()
        r = self.record_acceptance()
        path = self.directory / 'review.json'
        del r['checks']['normal_speed_playback']
        path.write_text(json.dumps(r))
        self.assertEqual(review.review_status(self.directory, core.api())['status'], 'pending')
        r['checks']['timing_and_events']['status'] = 'revise'
        path.write_text(json.dumps(r))
        self.assertEqual(review.review_status(self.directory, core.api())['status'], 'revise')

    def test_changed_source_manifest_output_and_snapshots_invalidate_acceptance(self):
        self.render_inspect()
        self.record_acceptance()
        for path in (self.root / 'a.ppm', self.manifest, self.output, self.directory / 'frames/frame-000001.png'):
            original = path.read_bytes()
            # Valid JSON whitespace keeps loading possible while changing the binding.
            path.write_bytes(original + b' ')
            with self.subTest(path=path):
                self.assertEqual(review.review_status(self.directory, core.api())['status'], 'stale')
            path.write_bytes(original)
        self.assertEqual(review.review_status(self.directory, core.api())['status'], 'pass')

    def test_fixed_region_drift_is_blocking_despite_manual_pass(self):
        self.d['plan']['fixed_regions'] = [{'id': 'background', 'rect': [0, 0, .5, .5], 'max_mae': 1}]
        self.render_inspect()
        self.record_acceptance()
        status = review.review_status(self.directory, core.api())
        self.assertEqual(status['status'], 'revise')
        self.assertTrue(any('Fixed region' in x for x in status['issues']))

    def test_identical_motion_rejected_but_intentional_still_allowed(self):
        self.d['frames'] = [dict(self.d['frames'][0]) for _ in range(3)]
        self.render_inspect()
        self.record_acceptance()
        self.assertEqual(review.review_status(self.directory, core.api())['status'], 'revise')
        self.d['plan']['intent'] = 'still'
        self.manifest.write_text(json.dumps(self.d))
        second = self.root / 'review-still'
        review.inspect(self.manifest, self.output, second, core.api())
        self.directory = second
        self.record_acceptance()
        self.assertEqual(review.review_status(second, core.api())['status'], 'pass')

    def test_missing_and_violating_observations_never_inherit_expectations(self):
        self.d['plan']['measurements'] = [measurement()]
        self.render_inspect()
        r = self.record_acceptance()
        self.assertEqual(r['observations']['position']['values'], [None, None, None])
        self.assertEqual(review.review_status(self.directory, core.api())['status'], 'pending')
        r['observations']['position'] = {'values': [0, 1, 6], 'evidence': 'Explicit numeric test observations'}
        (self.directory / 'review.json').write_text(json.dumps(r))
        self.assertEqual(review.review_status(self.directory, core.api())['status'], 'revise')

    def test_one_shot_page_escaping_and_budget(self):
        self.d['loop'] = False
        self.d['plan']['summary'] = '</script><img onerror=alert(1)>'
        self.d['frames'][0]['state'] = '</script><script>alert(1)</script>__SUMMARY__'
        self.d['plan']['max_bytes'] = 1
        self.render_inspect()
        r = self.record_acceptance()
        self.assertNotIn('loop_join', r['checks'])
        page = (self.directory / 'index.html').read_text(encoding='utf-8')
        self.assertNotIn(self.d['frames'][0]['state'], page)
        self.assertNotIn('<img onerror', page)
        self.assertIn('__SUMMARY__', page)
        self.assertEqual(review.review_status(self.directory, core.api())['status'], 'revise')

    def test_publication_failure_preserves_delivery_and_rejects_source_alias(self):
        self.render_inspect()
        self.record_acceptance()
        delivery = self.root / 'final.gif'
        delivery.write_bytes(b'keep')
        with mock.patch.object(core, 'verify', side_effect=ValueError('invalid')):
            with self.assertRaises(ValueError):
                review.publish(self.directory, delivery, True, core.api())
        self.assertEqual(delivery.read_bytes(), b'keep')
        with self.assertRaises(ValueError):
            review.publish(self.directory, self.output, True, core.api())

    def test_optional_encoding_and_existing_review_directory(self):
        self.d['encoding'] = {'colors': 16, 'dither': 'none'}
        self.render_inspect()
        with self.assertRaises(FileExistsError):
            review.inspect(self.manifest, self.output, self.directory, core.api())
        self.assertEqual(core.inspect_gif(self.output)['durations_ms'], [100, 200, 400])

    def test_edited_diagnostics_with_updated_declared_hash_cannot_bypass_budget(self):
        self.d['plan']['max_bytes'] = 1
        self.render_inspect()
        r = self.record_acceptance()
        analysis_path = self.directory / 'analysis.json'
        altered = json.loads(analysis_path.read_text())
        altered['output_bytes'] = 0
        analysis_path.write_text(json.dumps(altered))
        for asset in r['review_assets']:
            if asset['path'] == 'analysis.json':
                asset['sha256'] = review.digest(analysis_path)
        (self.directory / 'review.json').write_text(json.dumps(r))
        self.assertEqual(review.review_status(self.directory, core.api())['status'], 'stale')
        with self.assertRaises(ValueError):
            review.publish(self.directory, self.root / 'final.gif', False, core.api())

    def test_review_changed_during_publication_preserves_delivery(self):
        self.render_inspect()
        self.record_acceptance()
        delivery = self.root / 'final.gif'
        delivery.write_bytes(b'original')
        original_verify = core.verify

        def mutate_record(*args):
            result = original_verify(*args)
            path = self.directory / 'review.json'
            r = json.loads(path.read_text())
            r['checks']['source_sequence']['note'] = 'Changed during publication'
            path.write_text(json.dumps(r))
            return result

        with mock.patch.object(core, 'verify', side_effect=mutate_record):
            with self.assertRaisesRegex(ValueError, 'changed'):
                review.publish(self.directory, delivery, True, core.api())
        self.assertEqual(delivery.read_bytes(), b'original')
