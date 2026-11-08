import tempfile
import unittest
from pathlib import Path
from unittest import mock

from scripts import clipper


class BrollTests(unittest.TestCase):
    def test_only_files_in_the_broll_folder_count(self):
        with tempfile.TemporaryDirectory() as d:
            broll = Path(d) / "broll"
            broll.mkdir()
            with mock.patch.object(clipper, "BROLL_DIR", broll):
                self.assertTrue(clipper.is_broll(broll / "a.mp4"))
                self.assertFalse(clipper.is_broll(Path(d) / "clips" / "a.mp4"))

    def test_uploads_land_in_the_chosen_folder(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(clipper.upload_target("x.mp4", None, Path(d)).parent, Path(d))


if __name__ == "__main__":
    unittest.main()
