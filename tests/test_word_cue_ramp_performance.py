import random
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import make_short as ms


def legacy_time(cut, options, rel, *unused):
    at, acc = cut[0] + rel, 0.
    for a, b, speed in ms.speed_pieces(cut, options):
        if at <= a:
            break
        acc += (min(at, b) - a) / speed
    return acc


class WordCueRampPerformance(unittest.TestCase):
    def test_clip_ramp_is_prepared_once_for_all_word_boundaries(self):
        options = {'speed': 1., 'ramp': 'none', 'capmode': 'word',
                   'words': [(f'word{i}', i / 20, (i + 1) / 20) for i in range(400)]}
        with mock.patch.object(ms, 'speed_pieces', wraps=ms.speed_pieces) as pieces:
            cues = ms.word_cues((10., 30.), options, 3., 20.)
        self.assertEqual(len(cues), 400)
        self.assertEqual(pieces.call_count, 1)
        self.assertEqual(cues[0][0], 3.)
        self.assertEqual(cues[-1][1], 23.)

    def test_all_ramps_preserve_word_and_phrase_timing(self):
        rng = random.Random(43)
        for ramp in ms.RAMPS:
            for mode in ['word', 'phrase']:
                for _ in range(20):
                    start, span = rng.random() * 100, rng.random() * 20 + 1
                    words = [(f'word{i}', rng.random() * span * 1.2, rng.random() * span * 1.2) for i in range(40)]
                    options = {'speed': rng.choice([.5, 1., 1.5, 2.]), 'ramp': ramp, 'capmode': mode, 'words': words}
                    args = ((start, start + span), options, 2., span * 2)
                    with mock.patch.object(ms, 'rel_out_time', side_effect=legacy_time):
                        expected = ms.word_cues(*args)
                    self.assertEqual(ms.word_cues(*args), expected)
        with mock.patch.object(ms, 'speed_pieces') as pieces:
            self.assertEqual(ms.word_cues((0., 10.), {'words': []}, 0., 10.), [])
            pieces.assert_not_called()
