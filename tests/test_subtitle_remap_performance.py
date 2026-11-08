import random
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import make_short


def previous(cues, ranges, overlaps=None):
    out, offset = [], 0.
    for (start, end), overlap in zip(ranges, overlaps or [0.] * len(ranges)):
        offset -= overlap
        for a, b, text in cues:
            lo, hi = max(a, start), min(b, end)
            if hi - lo >= make_short.MIN_CUE_SECONDS:
                out.append((lo - start + offset, hi - start + offset, text))
        offset += end - start
    return sorted(out)


class SubtitleRemapPerformance(unittest.TestCase):
    def test_many_ranges_read_only_relevant_ordered_cues(self):
        class Cue(tuple):
            reads = 0
            def __iter__(self):
                Cue.reads += 1
                return super().__iter__()
            def __getitem__(self, key):
                Cue.reads += 1
                return super().__getitem__(key)
        cues = [Cue((float(n), n + .8, f'line{n}')) for n in range(2000)]
        ranges = [(float(n * 20), n * 20 + 2.) for n in range(100)]
        expected = previous(cues, ranges)
        Cue.reads = 0
        self.assertEqual(make_short.remap_cues(cues, ranges), expected)
        self.assertLessEqual(Cue.reads, 6000, f'{Cue.reads} cue accesses for 100 ranges')

    def test_remapping_preserves_clipping_sorting_and_transition_offsets(self):
        rng = random.Random(41)
        for n in range(500):
            cues = [(rng.randrange(30) / 2, rng.randrange(30) / 2, str(i)) for i in range(40)]
            if n % 2:
                cues = sorted((a, a + .8, text) for a, _, text in cues)
            ranges = [(rng.randrange(30) / 2, rng.randrange(30) / 2) for _ in range(10)]
            overlaps = [rng.random() for _ in ranges]
            self.assertEqual(make_short.remap_cues(cues, ranges, overlaps), previous(cues, ranges, overlaps))
        for cues in [[], [(0., 5., 'long'), (1., 2., 'nested')], [(0., float('inf'), 'open')]]:
            for ranges in [[], [(0., 3.)], [(float('nan'), 3.)]]:
                self.assertEqual(repr(make_short.remap_cues(cues, ranges)), repr(previous(cues, ranges)))
