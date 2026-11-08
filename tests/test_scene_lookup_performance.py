import random
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import dialogue_search
import suggest


class SceneLookupPerformance(unittest.TestCase):
    def test_candidate_and_search_operations_read_scene_list_once(self):
        class CountedScenes(list):
            reads = 0
            def __iter__(self):
                for value in super().__iter__():
                    self.reads += 1
                    yield value
        scenes = CountedScenes(float(i) for i in range(4000))
        cues = [(float(i * 10), i * 10 + 9., 'Hello world.') for i in range(300)]
        self.assertTrue(suggest.candidates(cues, 4000, scenes))
        self.assertEqual(scenes.reads, len(scenes))
        scenes.reads = 0
        found = dialogue_search.search([('v', 'video', '/video', 4000, cues, scenes)], 'Hello', limit=40)
        self.assertEqual(len(found), 40)
        self.assertEqual(scenes.reads, len(scenes))
        # An unmatched video never pays for building a scene index.
        scenes.reads = 0
        self.assertEqual(dialogue_search.search([('v', 'video', '/video', 4000, cues, scenes)], 'missing'), [])
        self.assertEqual(scenes.reads, 0)

    def test_index_matches_original_nearest_cut_and_tie_order(self):
        rng = random.Random(28)
        for _ in range(500):
            scenes = [rng.randrange(100) / 2 for _ in range(rng.randrange(100))]
            index = suggest.SceneIndex(scenes)
            for _ in range(20):
                time, before, after = rng.randrange(120) / 2, rng.randrange(10) / 2, rng.randrange(10) / 2
                self.assertEqual(suggest.snap(time, index, before, after), suggest.snap(time, scenes, before, after))
        for scenes in [[4., 2.], [2., 4.], [4., 4., 2.], []]:
            self.assertEqual(suggest.snap(3., suggest.SceneIndex(scenes), 2., 2.), suggest.snap(3., scenes, 2., 2.))

    def test_candidate_output_matches_unindexed_snapping(self):
        cues = [(float(i), i + 2., 'A sentence ends.') for i in range(100)]
        scenes = [float(i) + .3 for i in reversed(range(100))]
        expected = suggest.candidates(cues, 110, scenes)
        original_snap = suggest.snap
        def linear_snap(time, indexed, before, after):
            return original_snap(time, scenes, before, after)
        with mock.patch.object(suggest, 'snap', side_effect=linear_snap):
            self.assertEqual(suggest.candidates(cues, 110, scenes), expected)
