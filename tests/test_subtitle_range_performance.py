import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import embedded_subs as subs


class CountingCues(list):
    visited = 0

    def __iter__(self):
        for cue in super().__iter__():
            self.visited += 1
            yield cue


class SubtitleRangePerformance(unittest.TestCase):
    def test_early_clip_does_not_scan_the_rest_of_a_long_track(self):
        track = CountingCues((i * 2, i * 2 + 1, 'spoken words') for i in range(30000))
        with patch.object(subs, 'all_cues', return_value=track):
            self.assertEqual(subs.cues('video', 0, 10),
                             [(i * 2, i * 2 + 1, 'spoken words') for i in range(5)])
        self.assertLessEqual(track.visited, 6, 'cues after the clip cannot overlap it')

    def test_overlaps_long_cues_and_exact_boundaries_keep_existing_behavior(self):
        track = [(0, 30, 'long'), (2, 3, 'early'), (4, 7, 'overlap'),
                 (6, 8, 'inside'), (8, 10, 'boundary')]
        with patch.object(subs, 'all_cues', return_value=track):
            for start, end in [(3, 8), (0, 2), (30, 40), (-2, 0), (5, 5), (8, 3)]:
                expected = [(a-start, b-start, text) for a,b,text in track if b > start and a < end]
                self.assertEqual(subs.cues('video', start, end), expected)
        with patch.object(subs, 'all_cues', return_value=None):
            self.assertIsNone(subs.cues('video', 0, 10))
        with patch.object(subs, 'all_cues', return_value=[]):
            self.assertEqual(subs.cues('video', 0, 10), [])
