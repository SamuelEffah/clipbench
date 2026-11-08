import tempfile
import unittest
from pathlib import Path
from unittest import mock

from scripts import clipper


class UploadTargetTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        patch = mock.patch.object(clipper, "DOWNLOAD_DIR", Path(self.dir.name))
        patch.start()
        self.addCleanup(patch.stop)
        self.addCleanup(self.dir.cleanup)

    def test_keeps_a_safe_name(self):
        self.assertEqual(clipper.upload_target("Street fight.MP4").name, "Street fight.mp4")

    def test_rejects_non_video_extensions(self):
        self.assertIsNone(clipper.upload_target("run.sh"))
        self.assertIsNone(clipper.upload_target("notes"))

    def test_strips_path_and_odd_characters(self):
        target = clipper.upload_target("../../etc/pass:wd?.mp4")
        self.assertEqual(target.parent, Path(self.dir.name))
        self.assertEqual(target.name, "pass_wd_.mp4")

    def test_never_overwrites_an_existing_file(self):
        (Path(self.dir.name) / "clip.mp4").write_bytes(b"x")
        self.assertEqual(clipper.upload_target("clip.mp4").name, "clip-2.mp4")


if __name__ == "__main__":
    unittest.main()
