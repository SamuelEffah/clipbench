import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import instrumental  # noqa: E402


class InstrumentalTests(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.dir, True)
        self.song = self.dir / "Cry.mp3"
        self.song.write_bytes(b"x")

    def test_the_copy_sits_beside_the_song(self):
        self.assertEqual(instrumental.target_for(self.song), self.dir / "Cry (instrumental).mp3")

    def test_an_instrumental_is_not_split_again(self):
        with self.assertRaises(ValueError):
            instrumental.make_instrumental(self.dir / "Cry (instrumental).mp3")

    def test_an_existing_copy_is_reused_without_demucs(self):
        made = instrumental.target_for(self.song)
        made.write_bytes(b"y")
        with mock.patch("instrumental.subprocess.run") as run:
            self.assertEqual(instrumental.make_instrumental(self.song), made)
        run.assert_not_called()

    def test_missing_demucs_gives_the_install_hint(self):
        with mock.patch("instrumental.available", return_value=False):
            with self.assertRaises(ValueError) as caught:
                instrumental.make_instrumental(self.song)
        self.assertIn("pip3 install demucs", str(caught.exception))


if __name__ == "__main__":
    unittest.main()
