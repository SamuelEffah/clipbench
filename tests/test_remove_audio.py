"""A song or sound can be taken out of the audio library: the file goes to the Trash, never deleted outright."""
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from scripts import clipper  # noqa: E402


class RemoveAudioTests(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self.addCleanup(lambda: shutil.rmtree(self.dir, ignore_errors=True))
        self.audio, self.trash = self.dir / "audio", self.dir / "trash"
        self.audio.mkdir()
        for name, value in (("AUDIO_DIRS", [self.audio]), ("TRASH_DIR", self.trash)):
            patch = mock.patch.object(clipper, name, value)
            patch.start()
            self.addCleanup(patch.stop)
        self.song = self.audio / "song.mp3"
        self.song.write_bytes(b"x")
        self.aid = clipper.video_id(self.song)
        clipper.audio_registry[self.aid] = self.song
        self.addCleanup(clipper.audio_registry.pop, self.aid, None)

    def test_the_file_goes_to_the_trash_and_leaves_the_registry(self):
        clipper.remove_audio(self.aid)
        self.assertFalse(self.song.exists())
        self.assertTrue((self.trash / "song.mp3").exists())
        self.assertNotIn(self.aid, clipper.audio_registry)

    def test_a_name_clash_in_the_trash_keeps_both_files(self):
        self.trash.mkdir()
        (self.trash / "song.mp3").write_bytes(b"old")
        clipper.remove_audio(self.aid)
        self.assertEqual(len(list(self.trash.iterdir())), 2)
        self.assertEqual((self.trash / "song.mp3").read_bytes(), b"old")

    def test_an_unknown_id_and_a_file_outside_the_audio_folders_are_refused(self):
        with self.assertRaises(ValueError):
            clipper.remove_audio("0" * 12)
        outside = self.dir / "other.mp3"
        outside.write_bytes(b"x")
        clipper.audio_registry["f" * 12] = outside
        self.addCleanup(clipper.audio_registry.pop, "f" * 12, None)
        with self.assertRaises(ValueError):
            clipper.remove_audio("f" * 12)
        self.assertTrue(outside.exists())


if __name__ == "__main__":
    unittest.main()
