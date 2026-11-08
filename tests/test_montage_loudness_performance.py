import contextlib
import io
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import make_short as ms


class MontageLoudnessPerformance(unittest.TestCase):
    def test_duplicate_ranges_share_measurements_including_voice_and_silence(self):
        cuts = [(0., 2., None), (0., 2., None), (2., 4., None), (7., 9., None)] * 30
        options = [{**ms.DEFAULT_OPTIONS, 'voice': 'voice.wav' if n % 4 == 3 else '', 'volume': .7} for n in range(120)]
        def loudness(src, start, length, track):
            return None if start == 2. else -20.
        with mock.patch.object(ms, 'has_audio', return_value=True), \
                mock.patch.object(ms, 'measure_loudness', side_effect=loudness) as measure, \
                mock.patch.object(ms.subprocess, 'run') as run, contextlib.redirect_stderr(io.StringIO()):
            length = ms.build_montage('source.mp4', cuts, 1, 'out.mp4', options, (1080, 1920), normalize=True)
        self.assertEqual(length, 240.)
        self.assertEqual(measure.call_args_list, [mock.call('source.mp4', 0., 2., 1),
                                                 mock.call('source.mp4', 2., 2., 1),
                                                 mock.call('voice.wav', 0., 2., 0)])
        graph = run.call_args.args[0][run.call_args.args[0].index('-filter_complex') + 1]
        self.assertEqual(graph.count('alimiter=limit=0.95'), 90)
        self.assertEqual(graph.count('volume=0.700'), 120)

    def test_measurements_are_fresh_for_each_export_and_disabled_when_not_requested(self):
        with mock.patch.object(ms, 'has_audio', return_value=True), \
                mock.patch.object(ms, 'measure_loudness', return_value=None) as measure, \
                mock.patch.object(ms.subprocess, 'run'):
            for track in [0, 1]:
                ms.build_montage('source.mp4', [(0., 2., None)] * 3, track, 'out.mp4', frame=(1080, 1920), normalize=True)
            self.assertEqual(measure.call_args_list, [mock.call('source.mp4', 0., 2., 0), mock.call('source.mp4', 0., 2., 1)])
            measure.reset_mock()
            ms.build_montage('source.mp4', [(0., 2., None)] * 3, 0, 'out.mp4', frame=(1080, 1920))
            measure.assert_not_called()
