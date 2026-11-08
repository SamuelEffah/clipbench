import random
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import embedded_subs


class SubtitleWordsPerformance(unittest.TestCase):
    def test_word_limit_stops_processing_remaining_lines(self):
        class CountedText(str):
            calls = 0
            def split(self):
                type(self).calls += 1
                return super().split()
        lines = [(float(i), i + 1., CountedText('one two three four five six seven eight nine ten')) for i in range(2000)]
        with mock.patch.object(embedded_subs, 'cues', return_value=lines):
            words = embedded_subs.words('video', 0, 2000)
        self.assertEqual(len(words), embedded_subs.MAX_WORDS)
        self.assertEqual(CountedText.calls, 40)
        self.assertEqual(words[-1], ['ten', 39.9, 40.0])

    def test_output_matches_previous_timing_clipping_and_truncation(self):
        def previous(lines, length):
            if lines is None:
                return None
            out = []
            for a, b, text in lines:
                parts = text.split()
                step = (b - a) / len(parts)
                for n, word in enumerate(parts):
                    lo, hi = a + n * step, a + (n + 1) * step
                    if hi > 0 and lo < length:
                        out.append([word[:40], round(max(lo, 0.), 2), round(min(hi, length), 2)])
            return out[:embedded_subs.MAX_WORDS]
        rng = random.Random(42)
        for _ in range(200):
            length = rng.uniform(.1, 50)
            lines = []
            for _ in range(rng.randrange(100)):
                a = rng.uniform(-3, length + 3)
                lines.append((a, a + rng.uniform(.01, 10), ' '.join(['x' * rng.randrange(1, 60)] * rng.randrange(1, 40))))
            with mock.patch.object(embedded_subs, 'cues', return_value=lines):
                self.assertEqual(embedded_subs.words('video', 0, length), previous(lines, length))
        for lines in [None, []]:
            with mock.patch.object(embedded_subs, 'cues', return_value=lines):
                self.assertEqual(embedded_subs.words('video', 0, 1), lines)
