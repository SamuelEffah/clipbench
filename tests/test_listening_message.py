"""The listening status must say when the slow command-line fallback is doing the work,
so a person waiting minutes knows why and how to get the fast engine."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import clipper  # noqa: E402


class ListeningMessageTests(unittest.TestCase):
    def test_in_process_engines_just_listen(self):
        self.assertEqual(clipper.listening_message("mlx", first_run=False), "Listening")
        self.assertEqual(clipper.listening_message("fast", first_run=False), "Listening")

    def test_the_command_line_fallback_warns_that_it_is_slow_and_names_the_fix(self):
        message = clipper.listening_message("/usr/local/bin/whisper", first_run=False)
        self.assertIn("CPU", message)
        self.assertIn("./setup.sh --ai", message)

    def test_first_run_of_the_fallback_mentions_the_model_download(self):
        message = clipper.listening_message("/usr/local/bin/whisper", first_run=True)
        self.assertIn("Downloading the speech model", message)
        self.assertIn("./setup.sh --ai", message)

    def test_the_missing_engine_hint_points_at_setup(self):
        self.assertIn("./setup.sh --ai", clipper.WHISPER_HINT)
