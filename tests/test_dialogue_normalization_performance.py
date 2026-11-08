import random
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import dialogue_search as ds


class DialogueNormalizationPerformance(unittest.TestCase):
    def test_each_cue_is_normalized_at_most_once_during_a_scan(self):
        cues = [(float(i), i + .5, 'An unrelated line!') for i in range(4000)]
        for query in ['missing', 'missing phrase']:
            with mock.patch.object(ds, 'normalize', wraps=ds.normalize) as normalize:
                self.assertEqual(ds.hits(cues, query), [])
            self.assertLessEqual(normalize.call_count, len(cues) + 1)

    def test_matches_original_search_for_split_lines_punctuation_and_gaps(self):
        def previous(cues, query):
            wanted = ds.normalize(query)
            if not wanted:
                return []
            found, last = [], -1
            for i, (a, b, text) in enumerate(cues):
                if i <= last:
                    continue
                if wanted in ds.normalize(text):
                    found.append((a, b, text))
                    continue
                nxt = cues[i + 1] if i + 1 < len(cues) else None
                if nxt and nxt[0] - b <= ds.SPLIT_GAP:
                    both = f'{text} {nxt[2]}'
                    if wanted in ds.normalize(both) and wanted not in ds.normalize(nxt[2]):
                        found.append((a, nxt[1], both))
                        last = i + 1
            return found
        rng = random.Random(31)
        texts = ['alpha', ' beta! ', "don't", 'run_away', 'ALPHA beta', '?!', '', 'İ Σ', 'a\nb\tc', 'alpha’beta']
        queries = ['alpha beta', 'beta', "don't run", 'runaway alpha', 'a b', 'Σ', 'i', '?!', '', 'phabeta']
        for _ in range(500):
            cues, at = [], 0.
            for _ in range(rng.randrange(60)):
                cues.append((at, at + .5, rng.choice(texts)))
                at += rng.choice([.2, .7, 1.5, 3.])
            for query in queries:
                self.assertEqual(ds.hits(cues, query), previous(cues, query))
