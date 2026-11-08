import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import clipper  # noqa: E402


class TranscribeJobTests(unittest.TestCase):
    def setUp(self):
        self.addCleanup(clipper.transcripts.pop, "job", None)
        clipper.transcripts["job"] = {"id": "job", "state": "working"}

    def test_a_translation_with_no_segments_gives_no_words(self):
        self.assertEqual(clipper.fit_translation([["a", 0.0, 1.0]], []), [])

    def test_an_unexpected_failure_ends_the_job_instead_of_leaving_it_working(self):
        with mock.patch.object(clipper.subprocess, "run", side_effect=OSError("no ffmpeg")):
            clipper.run_transcribe("job", "whisper", "/x/a.mp4", 0.0, 2.0)
        self.assertEqual(clipper.transcripts["job"]["state"], "error")
        self.assertIn("no ffmpeg", clipper.transcripts["job"]["message"])

    def test_subtitles_with_nothing_said_in_the_range_still_let_the_speech_be_heard(self):
        spoken = [["wait", 0.0, 0.5]]
        with mock.patch.object(clipper.embedded_subs, "words", return_value=[]), \
                mock.patch.object(clipper.subprocess, "run", return_value=mock.Mock(returncode=0)), \
                mock.patch.object(clipper, "whisper_json", return_value=({"language": "en", "segments": []}, "")), \
                mock.patch.object(clipper, "spoken_words", return_value=spoken), \
                mock.patch.object(clipper.Path, "is_file", return_value=True):
            clipper.listen("job", "whisper", "/x/a.mkv", 0.0, 2.0, True, "translate")
        self.assertEqual(clipper.transcripts["job"]["state"], "done")
        self.assertEqual(clipper.transcripts["job"]["words"], spoken)


if __name__ == "__main__":
    unittest.main()
