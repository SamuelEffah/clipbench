import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import make_short as ms


class MontageOverlapScanPerformance(unittest.TestCase):
    def test_overlap_presence_is_scanned_once_for_all_clip_filters(self):
        class Overlaps(list):
            visits = 0
            def __iter__(self):
                for item in super().__iter__():
                    self.visits += 1
                    yield item
        for last_overlap in [0., .5]:
            overlaps = Overlaps([0.] * 200)
            overlaps[-1] = last_overlap
            with mock.patch.object(ms, 'seam_overlaps', return_value=overlaps), \
                    mock.patch.object(ms, 'join_clips', return_value=['join']), \
                    mock.patch.object(ms, 'has_audio', return_value=False), \
                    mock.patch.object(ms.subprocess, 'run') as run:
                length = ms.build_montage('source.mp4', [(0., 2., None)] * 200, 0, 'out.mp4', frame=(1080, 1920))
            self.assertEqual(length, 400. - last_overlap)
            graph = run.call_args.args[0][run.call_args.args[0].index('-filter_complex') + 1]
            self.assertEqual(graph.count(',fps=30'), 200 if last_overlap else 0)
            self.assertLessEqual(overlaps.visits, 600, f'{overlaps.visits} overlap visits for 200 clips')
