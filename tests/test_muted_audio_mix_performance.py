import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import make_short as ms


def sound(path, volume, **extra):
    return {'path': path, 'start': 0., 'in': 0., 'dur': 2., 'volume': volume,
            'fadein': 0., 'fadeout': 0., **extra}


class MutedAudioMixPerformance(unittest.TestCase):
    def test_fully_muted_library_sounds_skip_the_entire_second_encoding_pass(self):
        with tempfile.TemporaryDirectory() as folder:
            video = Path(folder) / 'render.mp4'
            original = b'completed render must stay byte-for-byte unchanged'
            video.write_bytes(original)
            items = [sound(f'muted{i}.wav', 0., **({'volumeend': 0.} if i % 2 else {})) for i in range(ms.MAX_AUDIO_ITEMS)]
            with patch.object(ms.subprocess, 'run') as run, patch.object(Path, 'replace') as replace:
                ms.mix_audio(str(video), None)
                ms.mix_audio(str(video), [])
                ms.mix_audio(str(video), items)
            run.assert_not_called()
            replace.assert_not_called()
            self.assertEqual(video.read_bytes(), original)
            self.assertEqual(list(Path(folder).iterdir()), [video])

    def test_mixed_library_sounds_keep_both_directions_of_volume_ramps(self):
        items = [sound('muted.wav', 0.), sound('muted-end.wav', 0., volumeend=0.),
                 sound('rising.wav', 0., volumeend=.7), sound('falling.wav', .5, volumeend=0.)]
        with patch.object(ms.subprocess, 'run') as run, patch.object(Path, 'replace'):
            ms.mix_audio('render.mp4', items)
        cmd = run.call_args.args[0]
        self.assertEqual(cmd.count('-i'), 3, 'only the video and two audible sounds need inputs')
        self.assertNotIn('muted.wav', cmd)
        self.assertNotIn('muted-end.wav', cmd)
        self.assertIn('rising.wav', cmd)
        self.assertIn('falling.wav', cmd)
        graph = cmd[cmd.index('-filter_complex') + 1]
        self.assertIn('amix=inputs=3:normalize=0:duration=first', graph)
        self.assertIn("volume='0.000+(0.700-0.000)*t/2.000'", graph)
        self.assertIn("volume='0.500+(0.000-0.500)*t/2.000'", graph)
        self.assertEqual(len(items), 4, 'filtering must not modify the project sound list')
