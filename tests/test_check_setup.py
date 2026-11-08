"""The setup check must catch an OpenCV that lost the face detector (OpenCV 5 dropped
the cascade classifier), which another package can pull in over the pinned 4.x."""
import sys
import types
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools import check_setup  # noqa: E402


class OpenCvProblemsTests(unittest.TestCase):
    def test_reports_an_opencv_without_the_face_detector(self):
        bare = types.SimpleNamespace(__version__="5.0.0")
        problems = check_setup.opencv_problems(bare)
        self.assertEqual(len(problems), 1)
        self.assertIn("5.0.0", problems[0])
        self.assertIn("./setup.sh", problems[0])

    def test_accepts_an_opencv_with_cascades(self):
        full = types.SimpleNamespace(__version__="4.14.0", CascadeClassifier=object)
        self.assertEqual(check_setup.opencv_problems(full), [])

    def test_accepts_no_opencv_at_all_here_since_the_module_check_reports_it(self):
        self.assertEqual(check_setup.opencv_problems(None), [])
