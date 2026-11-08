import random
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import clipper


class TranslationTimingPerformance(unittest.TestCase):
    def test_translation_reuses_prepared_speech_clock(self):
        class Word(list):
            reads = 0
            def __getitem__(self, key):
                if key in (1, 2):
                    type(self).reads += 1
                return super().__getitem__(key)
        heard = [Word(['word', float(i), i + 1.]) for i in range(400)]
        segments = [{'start': 0., 'end': 400., 'text': ' '.join(['word'] * 400)}]
        result = clipper.fit_translation(heard, segments)
        self.assertEqual(len(result), 400)
        self.assertLess(Word.reads, 10000)
        self.assertEqual(result[0], ['word', 0., 1.])
        self.assertEqual(result[-1], ['word', 399., 400.])

    def test_word_limit_stops_preparing_remaining_segments(self):
        heard = [['word', float(i), i + 1.] for i in range(1000)]
        segments = [{'start': float(i * 10), 'end': i * 10 + 10., 'text': ' '.join(['word'] * 10)} for i in range(100)]
        with mock.patch.object(clipper, '_speech_clock', wraps=clipper._speech_clock) as clock:
            words = clipper.fit_translation(heard, segments)
        self.assertEqual(len(words), clipper.MAX_WORDS)
        self.assertEqual(clock.call_count, 40)
        self.assertEqual(words[-1], ['word', 399., 400.])
        # Stopping partway through a segment must keep timings based on its full text.
        words = clipper.fit_translation([['a', 0., 399.], ['b', 400., 404.]], [
            {'start': 0., 'end': 399., 'text': ' '.join(['word'] * 399)},
            {'start': 400., 'end': 404., 'text': 'one two six ten'},
        ])
        self.assertEqual(len(words), 400)
        self.assertEqual(words[-1], ['one', 400., 401.])

    def test_clock_matches_original_at_boundaries_pauses_and_empty_words(self):
        rng = random.Random(83)
        for _ in range(300):
            at, heard = 0., []
            for _ in range(rng.randrange(1, 60)):
                end = at + (rng.random() * 3 if rng.random() > .1 else 0.)
                heard.append(['word', at, end])
                at = end + rng.random()
            clock = clipper._speech_clock(heard)
            lengths = [w[2] - w[1] for w in heard]
            total = sum(lengths)
            fractions = [-.1, 0., .2, .5, 1., 1.1, float('nan')]
            if total:
                run = 0.
                for length in lengths:
                    run += length
                    fractions.extend([(run - 1e-6) / total, run / total, (run + 1e-6) / total])
            for fraction in fractions:
                for ending in [False, True]:
                    self.assertEqual(clock(fraction, ending), clipper.time_at(heard, fraction, ending))
        heard = [['reverse', 2., 1.], ['forward', 4., 7.]]
        clock = clipper._speech_clock(heard)
        for fraction in [0., .5, 1.]:
            self.assertEqual(clock(fraction), clipper.time_at(heard, fraction))
