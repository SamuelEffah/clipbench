import tempfile
import unittest
from pathlib import Path
from unittest import mock

from scripts import clipper, make_short


class ZoomFilterTests(unittest.TestCase):
    def test_no_filter_at_one_x(self):
        self.assertEqual(make_short.zoom_filter(1080, 1080, dict(make_short.DEFAULT_OPTIONS)), "")

    def test_crops_around_the_chosen_point_and_scales_back(self):
        opt = {**make_short.DEFAULT_OPTIONS, "zoom": 2.0, "zx": 0.25, "zy": 1.0}
        self.assertEqual(make_short.zoom_filter(1080, 1080, opt),
                         ",crop=iw/2.0000:ih/2.0000:(iw-ow)*0.250:(ih-oh)*1.000,scale=1080:1080,setsar=1")

    def test_zooming_out_a_fit_clip_shrinks_it_and_pads_the_margins(self):
        opt = {**make_short.DEFAULT_OPTIONS, "zoom": 0.5, "zx": 0.0, "zy": 0.5}
        self.assertEqual(make_short.zoom_filter(1080, 1080, opt),
                         ",scale=trunc(iw*0.5000/2)*2:trunc(ih*0.5000/2)*2,pad=1080:1080:(ow-iw)*0.000:(oh-ih)*0.500:color=black,setsar=1")

    def test_zooming_out_a_filled_clip_happens_in_the_fill_step(self):
        opt = {**make_short.DEFAULT_OPTIONS, "fit": "fill", "zoom": 0.5}
        self.assertEqual(make_short.zoom_filter(1080, 1920, opt), "")
        fill = make_short.fill_filter(1080, 1920, opt)
        self.assertIn("max(1080/iw,1920/ih)*0.5000", fill)
        self.assertIn("pad='max(iw,1080)':'max(ih,1920)'", fill)

    def test_a_filled_clip_at_full_size_still_just_covers_and_crops(self):
        fill = make_short.fill_filter(1080, 1920, {**make_short.DEFAULT_OPTIONS, "fit": "fill"})
        self.assertEqual(fill, ",scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920:(iw-ow)*0.500:(ih-oh)*0.500,setsar=1")

    def test_cut_list_reads_the_zoom_directives(self):
        cuts = make_short.read_cuts("@zoom 1.5\n@zx 0.2\n0:01 - 0:03")
        self.assertEqual((cuts[0][3]["zoom"], cuts[0][3]["zx"], cuts[0][3]["zy"]), (1.5, 0.2, 0.5))

    def test_cut_list_rejects_a_zoom_out_of_range(self):
        with self.assertRaises(SystemExit):
            make_short.read_cuts("@zoom 9\n0:01 - 0:03")
        with self.assertRaises(SystemExit):
            make_short.read_cuts("@zoom 0.1\n0:01 - 0:03")
        self.assertEqual(make_short.read_cuts("@zoom 0.5\n0:01 - 0:03")[0][3]["zoom"], 0.5)


class ZoomExportTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        self.video = Path(self.dir.name) / "a.mp4"
        self.video.write_bytes(b"x")
        patch = mock.patch.object(clipper, "PROJECT_DIR", Path(self.dir.name))
        patch.start()
        self.addCleanup(patch.stop)

    def export(self, clips):
        return clipper.export_cuts("zt", {"clips": clips})[0]

    def clip(self, **extra):
        return {"src": str(self.video), "in": 1, "out": 3, **extra}

    def test_writes_zoom_and_position_only_when_changed(self):
        self.assertNotIn("@zoom", self.export([self.clip()]))
        text = self.export([self.clip(zoom=2, zx=0.3, zy=0.5)])
        self.assertIn("@zoom 2", text)
        self.assertIn("@zx 0.3", text)
        self.assertNotIn("@zy", text)

    def test_rejects_bad_zoom(self):
        with self.assertRaises(ValueError):
            self.export([self.clip(zoom=5)])


if __name__ == "__main__":
    unittest.main()
