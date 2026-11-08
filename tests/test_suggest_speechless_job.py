import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import clipper


class SpeechlessJob(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.src = self.root / 'source.mp4'
        self.src.write_bytes(b'video')
        self.vid = 'speechless'
        patches = [patch.object(clipper, 'PROXY_DIR', self.root / 'proxy'),
                   patch.object(clipper, 'registry', {self.vid: self.src}),
                   patch.object(clipper, 'suggest_jobs', {self.vid: {'state': 'working'}}),
                   patch.object(clipper, 'load_wave', return_value={}),
                   patch.object(clipper, 'get_scenes', return_value={'state': 'ready', 'scenes': []}),
                   patch.object(clipper, 'probe', return_value={'duration': 60}),
                   patch.object(clipper, 'load_motion', return_value={'per_sec': 4, 'values': [9] * 240}),
                   patch.object(clipper.suggest, 'ollama_models', return_value=[]),
                   patch.object(clipper.suggest, 'suggest', return_value=[])]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)

    def test_a_video_that_was_heard_and_has_no_speech_still_gets_suggestions(self):
        with patch.object(clipper.embedded_subs, 'all_cues', return_value=None), \
             patch.object(clipper.transcript_index, 'load', return_value=[]):
            clipper.run_suggest(self.vid)
        self.assertEqual(clipper.suggest_jobs[self.vid]['state'], 'ready')
        self.assertEqual(clipper.suggest.suggest.call_args.args[0], [])
        self.assertEqual(clipper.suggest.suggest.call_args.kwargs['motion']['per_sec'], 4)

    def test_a_video_never_listened_to_still_asks_to_be_listened_to(self):
        with patch.object(clipper.embedded_subs, 'all_cues', return_value=None), \
             patch.object(clipper.transcript_index, 'load', return_value=None):
            clipper.run_suggest(self.vid)
        self.assertEqual(clipper.suggest_jobs[self.vid]['state'], 'error')
        self.assertIn('Listen', clipper.suggest_jobs[self.vid]['message'])


if __name__ == '__main__':
    unittest.main()
