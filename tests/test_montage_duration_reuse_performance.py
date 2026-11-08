import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import make_short as ms


class MontageDurationReusePerformance(unittest.TestCase):
    def test_filter_building_reuses_prepared_output_lengths(self):
        ramps = list(ms.RAMPS)
        cuts = [(float(n), n + 4., None) for n in range(200)]
        options = [{**ms.DEFAULT_OPTIONS, 'ramp': ramps[n % len(ramps)], 'speed': [.5, 1., 2.][n % 3], 'freeze': .5} for n in range(200)]
        expected = ms.joined_length([ms.out_length(cut, opt) for cut, opt in zip(cuts, options)], ms.transitions_of(options))
        with mock.patch.object(ms, 'out_length', wraps=ms.out_length) as duration, \
                mock.patch.object(ms, 'speed_pieces', wraps=ms.speed_pieces) as pieces, \
                mock.patch.object(ms, 'has_audio', return_value=False), \
                mock.patch.object(ms.subprocess, 'run') as run:
            length = ms.build_montage('source.mp4', cuts, 0, 'out.mp4', options, (1080, 1920))
        self.assertEqual(length, expected)
        self.assertEqual(duration.call_count, 200)
        self.assertEqual(pieces.call_count, 400)
        graph = run.call_args.args[0][run.call_args.args[0].index('-filter_complex') + 1]
        self.assertEqual(graph.count('tpad=stop_mode=clone:stop_duration=0.500'), 200)
        self.assertEqual(graph.count('anullsrc='), 200)
