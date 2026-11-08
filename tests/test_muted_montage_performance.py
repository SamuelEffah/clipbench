import contextlib
import io
import shutil
import struct
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import make_short as ms


class MutedMontagePerformance(unittest.TestCase):
    def test_muted_clips_skip_audio_probes_normalization_and_voice_inputs(self):
        cuts = [(float(i), i + 2., None) for i in range(100)]
        options = [{**ms.DEFAULT_OPTIONS, 'volume': 0., 'voice': f'voice{i}.wav',
                    'ramp': next(k for k, v in ms.RAMPS.items() if len(v) > 1), 'freeze': .5} for i, _ in enumerate(cuts)]
        with patch.object(ms, 'has_audio', return_value=True) as probe, \
             patch.object(ms, 'measure_loudness', return_value=None) as measure, \
             patch.object(ms, 'ramp_audio', wraps=ms.ramp_audio) as ramp, \
             patch.object(ms.subprocess, 'run') as run:
            length = ms.build_montage('source.mp4', cuts, 0, 'out.mp4', options, (1080, 1920), normalize=True)
        probe.assert_not_called()
        measure.assert_not_called()
        ramp.assert_not_called()
        cmd = run.call_args.args[0]
        self.assertEqual(cmd.count('-i'), 100, 'muted voice files must not become encoder inputs')
        graph = cmd[cmd.index('-filter_complex') + 1]
        self.assertEqual(graph.count('anullsrc='), 100)
        self.assertGreater(length, 0)

    def test_muted_and_audible_clips_keep_input_numbering_and_normalization(self):
        options = [{**ms.DEFAULT_OPTIONS, 'volume': v, 'voice': voice}
                   for v, voice in [(0., 'muted.wav'), (1., 'audible.wav'), (0., None)]]
        with patch.object(ms, 'has_audio', return_value=True) as probe, \
             patch.object(ms, 'measure_loudness', return_value=-20.) as measure, \
             patch.object(ms.subprocess, 'run') as run, contextlib.redirect_stderr(io.StringIO()):
            ms.build_montage('source.mp4', [(0., 2., None)] * 3, 0, 'out.mp4', options, (64, 64), normalize=True)
        probe.assert_called_once_with('source.mp4')
        measure.assert_called_once_with('audible.wav', 0., 2., 0)
        cmd = run.call_args.args[0]
        self.assertNotIn('muted.wav', cmd)
        self.assertIn('audible.wav', cmd)
        graph = cmd[cmd.index('-filter_complex') + 1]
        self.assertEqual(graph.count('anullsrc='), 2)
        self.assertIn('[3:a]asetpts=', graph)

    @unittest.skipUnless(shutil.which('ffmpeg') and shutil.which('ffprobe'), 'FFmpeg required')
    def test_rendered_muted_audio_is_silent_and_preserves_retimed_duration(self):
        with tempfile.TemporaryDirectory() as folder:
            src, dest = str(Path(folder) / 'source.mp4'), str(Path(folder) / 'out.mp4')
            subprocess.run(['ffmpeg', '-y', '-v', 'error', '-f', 'lavfi', '-i',
                            'color=c=blue:s=64x64:r=30:d=2', '-f', 'lavfi', '-i',
                            'sine=frequency=440:sample_rate=44100:duration=2',
                            '-c:v', 'libx264', '-pix_fmt', 'yuv420p', '-c:a', 'aac', src], check=True)
            options = [{**ms.DEFAULT_OPTIONS, 'volume': 0., 'speed': 2., 'freeze': .25}]
            length = ms.build_montage(src, [(0., 2., None)], 0, dest, options, (64, 64), normalize=True)
            self.assertEqual(length, 1.25)
            self.assertAlmostEqual(ms.probe_duration(dest), length, delta=.06)
            pcm = subprocess.check_output(['ffmpeg', '-v', 'error', '-i', dest, '-map', '0:a', '-f', 'f32le', '-'])
            self.assertTrue(pcm)
            self.assertLessEqual(max(abs(v[0]) for v in struct.iter_unpack('<f', pcm)), 1e-7)
