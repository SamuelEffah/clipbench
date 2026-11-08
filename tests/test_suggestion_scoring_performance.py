import random
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import suggest


class SuggestionScoringPerformance(unittest.TestCase):
    def test_candidate_wording_is_analyzed_once(self):
        for peaks in [[255] * 200, [20] * 200, []]:
            with mock.patch.object(suggest, 'wording', wraps=suggest.wording) as wording:
                suggest.heuristic({'in': 0, 'out': 10, 'text': 'What?! Stop!'}, peaks, 20)
            self.assertEqual(wording.call_count, 1)

    def test_scores_and_reasons_match_previous_calculations(self):
        rng = random.Random(66)
        texts = ['What?! Stop!', 'A quiet conversation about the weather.', '', 'Why are you here? No. Go!', 'One long sentence without any punctuation at all']
        for _ in range(500):
            peaks = [rng.randrange(256) for _ in range(rng.randrange(100))]
            item = {'in': rng.random() * 2, 'out': rng.random() * 10 + 2, 'text': rng.choice(texts)}
            mean, spread = suggest.loudness(peaks, 20, item['in'], item['out'])
            why = 'Loud and punchy' if mean + spread > .6 and suggest.wording(item['text']) > .4 else 'Loud moment' if mean + spread > .6 else 'Punchy lines' if suggest.wording(item['text']) > .4 else 'Dialogue'
            score = min(1., (mean * .5 + spread * .9 + suggest.wording(item['text']) * .8) / 1.6)
            self.assertEqual(suggest.heuristic(item, peaks, 20), score)
            self.assertEqual(item['why'], why)
