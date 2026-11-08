"""The renderer needs FFmpeg's drawtext and subtitles filters. Homebrew's plain ffmpeg
dropped them; ffmpeg-full has them but is keg-only, so the app must put it first itself."""
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import ffmpeg_env  # noqa: E402

FILTERS_SLIM = " .. scale  V->V  Scale\n .. overlay  VV->V  Overlay\n"
FILTERS_FULL = FILTERS_SLIM + " T. drawtext  V->V  Draw text\n .. subtitles  V->V  Render subtitles\n"


class PreferFullFfmpegTests(unittest.TestCase):
    def test_puts_an_installed_full_build_first(self):
        with tempfile.TemporaryDirectory() as tmp:
            full = Path(tmp) / "ffmpeg-full/bin"
            full.mkdir(parents=True)
            (full / "ffmpeg").write_text("")
            path = ffmpeg_env.prefer_full_ffmpeg({"PATH": "/usr/bin"}, builds=(full,))
        self.assertEqual(path.split(os.pathsep), [str(full), "/usr/bin"])

    def test_leaves_path_alone_without_a_full_build(self):
        with tempfile.TemporaryDirectory() as tmp:
            absent = Path(tmp) / "ffmpeg-full/bin"
            path = ffmpeg_env.prefer_full_ffmpeg({"PATH": "/usr/bin"}, builds=(absent,))
        self.assertEqual(path, "/usr/bin")

    def test_does_not_add_the_same_folder_twice(self):
        with tempfile.TemporaryDirectory() as tmp:
            full = Path(tmp) / "ffmpeg-full/bin"
            full.mkdir(parents=True)
            (full / "ffmpeg").write_text("")
            once = ffmpeg_env.prefer_full_ffmpeg({"PATH": "/usr/bin"}, builds=(full,))
            twice = ffmpeg_env.prefer_full_ffmpeg({"PATH": once}, builds=(full,))
        self.assertEqual(twice, once)

    def test_does_not_mutate_the_environment_it_reads(self):
        environ = {"PATH": "/usr/bin"}
        with tempfile.TemporaryDirectory() as tmp:
            full = Path(tmp) / "ffmpeg-full/bin"
            full.mkdir(parents=True)
            (full / "ffmpeg").write_text("")
            ffmpeg_env.prefer_full_ffmpeg(environ, builds=(full,))
        self.assertEqual(environ, {"PATH": "/usr/bin"})


class MissingFiltersTests(unittest.TestCase):
    def test_names_each_filter_the_renderer_needs_but_the_build_lacks(self):
        self.assertEqual(ffmpeg_env.missing_filters(FILTERS_SLIM), ["drawtext", "subtitles"])

    def test_reports_nothing_for_a_full_build(self):
        self.assertEqual(ffmpeg_env.missing_filters(FILTERS_FULL), [])

    def test_does_not_match_a_filter_by_prefix(self):
        self.assertEqual(ffmpeg_env.missing_filters(" .. drawtextish  V->V\n .. subtitles  V->V\n"), ["drawtext"])


if __name__ == "__main__":
    unittest.main()
