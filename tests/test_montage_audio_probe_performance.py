import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import make_short as ms


class MontageAudioProbePerformance(unittest.TestCase):
    def test_repeated_sources_probe_once_per_export_and_keep_silent_segments(self):
        calls = []
        def run(cmd, **kwargs):
            calls.append(cmd)
            return SimpleNamespace(stdout='' if cmd[-1] == 'silent.mp4' else 'audio\n')
        sources = ['episode.mp4', 'other.mp4', 'silent.mp4']
        cuts = [(0., 2., sources[n % 3]) for n in range(300)]
        with mock.patch.object(ms.subprocess, 'run', side_effect=run):
            length = ms.build_montage('episode.mp4', cuts, 0, 'out.mp4', frame=(1080, 1920))
        probes = [cmd for cmd in calls if cmd[0] == 'ffprobe']
        self.assertEqual([cmd[-1] for cmd in probes], sources)
        self.assertEqual(length, 600.)
        graph = calls[-1][calls[-1].index('-filter_complex') + 1]
        self.assertEqual(graph.count('anullsrc='), 100)
        self.assertEqual(graph.count('aformat=channel_layouts=stereo'), 200)

    def test_next_export_probes_again_including_after_failure(self):
        with mock.patch.object(ms, 'has_audio', side_effect=[False, True, OSError('probe failed'), False]) as probe, \
                mock.patch.object(ms.subprocess, 'run'):
            for audible in [False, True]:
                ms.build_montage('source.mp4', [(0., 2., None)] * 3, 0, 'out.mp4', frame=(1080, 1920))
            with self.assertRaisesRegex(OSError, 'probe failed'):
                ms.build_montage('source.mp4', [(0., 2., None)], 0, 'out.mp4', frame=(1080, 1920))
            ms.build_montage('source.mp4', [(0., 2., None)], 0, 'out.mp4', frame=(1080, 1920))
            self.assertEqual(probe.call_count, 4)
