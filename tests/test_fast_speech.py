import sys
import unittest
from pathlib import Path
from types import SimpleNamespace as NS
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import clipper  # noqa: E402
import fast_speech  # noqa: E402


class FakeModel:
    def transcribe(self, path, **options):
        words = [NS(word="hello", start=0.1, end=0.5)]
        return iter([NS(text=" hello", start=0.0, end=0.6, words=words)]), NS(language="ja")


class FastSpeechTests(unittest.TestCase):
    def listen(self):
        with mock.patch.object(fast_speech, "_load", return_value=FakeModel()):
            return fast_speech.transcribe("a.wav", "translate", True)

    def test_segments_carry_their_own_times(self):
        seg = self.listen()["segments"][0]
        self.assertEqual((seg["start"], seg["end"]), (0.0, 0.6))

    def test_a_translation_can_be_laid_along_the_heard_words(self):
        heard = [["こんにちは", 0.1, 0.5]]
        words = clipper.fit_translation(heard, self.listen()["segments"])
        self.assertEqual([w[0] for w in words], ["hello"])


if __name__ == "__main__":
    unittest.main()
