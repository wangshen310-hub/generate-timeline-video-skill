import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from test_timeline_video import timeline_video as tv


class ReviewAcceptanceTests(unittest.TestCase):
    def ready(self):
        return {'source_pairs': 'pass', 'intermediate_frames': 'pass',
                'normal_speed_playback': 'pass', 'issues': []}

    def test_unobserved_playback_cannot_pass_technical_success(self):
        review = self.ready(); review['normal_speed_playback'] = 'not_reviewed'
        result = tv.assess_review({'technical': 'passed', 'video_sha256': 'a'}, review, 'a')
        self.assertEqual(result['delivery_status'], 'needs_review')

    def test_reviewed_is_not_an_acceptance_decision(self):
        review = self.ready(); review['source_pairs'] = 'reviewed'
        self.assertEqual(tv.assess_review({'technical':'passed','video_sha256':'a'}, review, 'a')['delivery_status'], 'needs_review')

    def test_unresolved_issue_blocks_delivery_even_with_all_pass(self):
        review = self.ready(); review['issues'] = [{'frame': 6, 'description': 'unplanned cut', 'resolved': False}]
        self.assertEqual(tv.assess_review({'technical':'passed','video_sha256':'a'}, review, 'a')['delivery_status'], 'needs_revision')
        review['issues'][0]['resolved'] = True
        self.assertEqual(tv.assess_review({'technical':'passed','video_sha256':'a'}, review, 'a')['delivery_status'], 'ready_for_delivery')

    def test_stale_video_or_missing_hash_needs_fresh_inspection(self):
        for report in ({'technical':'passed','video_sha256':'old'}, {'technical':'passed'}):
            self.assertEqual(tv.assess_review(report, self.ready(), 'new')['delivery_status'], 'needs_review')

    def test_revision_outcome_and_failed_technical_check(self):
        review = self.ready(); review['normal_speed_playback'] = 'revise'
        self.assertEqual(tv.assess_review({'technical':'passed','video_sha256':'a'}, review, 'a')['delivery_status'], 'needs_revision')
        self.assertEqual(tv.assess_review({'technical':'failed','video_sha256':'a'}, self.ready(), 'a')['delivery_status'], 'needs_review')

    def test_command_writes_status_and_rejects_modified_preview(self):
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            (root/'preview.mp4').write_bytes(b'inspected content')
            (root/'report.json').write_text(json.dumps({'technical':'passed','video_sha256':tv.file_digest(root/'preview.mp4').hex()}))
            (root/'review.json').write_text(json.dumps(self.ready()))
            args = tv.build_parser().parse_args(['review-status',str(root),'--write'])
            with redirect_stdout(io.StringIO()):
                self.assertEqual(tv.command_review_status(args), 0)
            self.assertEqual(json.loads((root/'report.json').read_text())['delivery_status'], 'ready_for_delivery')
            (root/'preview.mp4').write_bytes(b'replaced content')
            with redirect_stdout(io.StringIO()):
                self.assertEqual(tv.command_review_status(args), 2)
            self.assertEqual(json.loads((root/'report.json').read_text())['delivery_status'], 'needs_review')
