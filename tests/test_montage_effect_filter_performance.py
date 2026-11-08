import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import make_short as ms


class MontageEffectFilterPerformance(unittest.TestCase):
    def test_repeated_effects_and_lengths_reuse_identical_filter_text(self):
        cuts = [(0., 10., None)] * 100 + [(0., 5., None), (0., 10., None)]
        options = [{**ms.DEFAULT_OPTIONS, 'effect': 'glitch'} for _ in cuts]
        options[-1]['effect'] = 'bw'
        ten = ms.effect_filter('glitch', 1080, 1920, 10.)
        five = ms.effect_filter('glitch', 1080, 1920, 5.)
        with mock.patch.object(ms, 'effect_filter', wraps=ms.effect_filter) as effect, \
                mock.patch.object(ms, 'glitch_burst', wraps=ms.glitch_burst) as burst, \
                mock.patch.object(ms, 'has_audio', return_value=False), \
                mock.patch.object(ms.subprocess, 'run') as run:
            ms.build_montage('source.mp4', cuts, 0, 'out.mp4', options, (1080, 1920))
        self.assertEqual(effect.call_args_list, [mock.call('glitch', 1080, 1920, 10.),
                                               mock.call('glitch', 1080, 1920, 5.),
                                               mock.call('bw', 1080, 1920, 10.)])
        self.assertEqual(burst.call_count, int(10 / ms.GLITCH_SLOT) + int(5 / ms.GLITCH_SLOT) + 2)
        graph = run.call_args.args[0][run.call_args.args[0].index('-filter_complex') + 1]
        for i in range(100):
            self.assertIn(f'{ten},setsar=1[v{i}]', graph)
        self.assertIn(f'{five},setsar=1[v100]', graph)
        self.assertIn(',hue=s=0,setsar=1[v101]', graph)
