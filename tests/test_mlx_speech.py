import sys
import types
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import clipper  # noqa: E402
import mlx_speech  # noqa: E402

SPEECH = {"text": " hello", "start": 0, "end": 0.6, "no_speech_prob": 0.01, "avg_logprob": -0.3, "compression_ratio": 1.1,
          "words": [{"word": " hello", "start": 0.1, "end": 0.5}]}
SILENCE = {"text": " thanks for watching", "start": 1, "end": 2, "no_speech_prob": 0.9, "avg_logprob": -1.4, "compression_ratio": 1.0, "words": []}
LOOP = {"text": " la la la la", "start": 2, "end": 3, "no_speech_prob": 0.1, "avg_logprob": -0.5, "compression_ratio": 3.0, "words": []}


def fake_module(segments):
    return types.SimpleNamespace(transcribe=lambda *a, **k: {"language": "ja", "segments": segments})


class MlxSpeechTests(unittest.TestCase):
    def listen(self, segments):
        with mock.patch.dict(sys.modules, {"mlx_whisper": fake_module(segments)}):
            return mlx_speech.transcribe("a.wav", "translate", True)

    def test_silence_and_loops_are_dropped(self):
        out = self.listen([SPEECH, SILENCE, LOOP])
        self.assertEqual([s["text"] for s in out["segments"]], [" hello"])
        self.assertEqual(out["text"], "hello")

    def test_times_are_plain_floats(self):
        word = self.listen([SPEECH])["segments"][0]["words"][0]
        self.assertEqual((word["start"], word["end"]), (0.1, 0.5))

    def test_a_failing_engine_falls_back_to_the_next(self):
        with mock.patch.object(clipper.mlx_speech, "transcribe", side_effect=RuntimeError("boom")), \
                mock.patch.object(clipper.fast_speech, "available", return_value=True), \
                mock.patch.object(clipper.fast_speech, "transcribe", return_value={"segments": []}) as fast:
            data, problem = clipper.whisper_json("mlx", "a.wav", "/tmp", "translate", True)
        self.assertEqual((data, problem), ({"segments": []}, ""))
        fast.assert_called_once()

    def test_mlx_is_preferred_when_installed(self):
        with mock.patch.object(clipper.mlx_speech, "available", return_value=True):
            self.assertEqual(clipper.speech_engine(), "mlx")
