import tempfile
import unittest
from pathlib import Path
from unittest import mock
import clipper
import make_short


class ClipGrade(unittest.TestCase):
    def test_grade_round_trips_into_render_options(self):
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / 'video.mp4'
            src.touch()
            project = {'clips': [{'src': str(src), 'in': 0, 'out': 4, 'brightness': 1.2, 'contrast': .8, 'saturation': 0}]}
            path = clipper.export_cuts('grade', project, directory=Path(tmp))
            options = make_short.cut_options(str(Path(tmp) / 'grade.cuts.txt'))[0]
            self.assertEqual([options[k] for k in ('brightness','contrast','saturation')], [1.2,.8,0])
            project['clips'][0]['brightness'] = float('nan')
            with self.assertRaises(ValueError):
                clipper.export_cuts('grade', project, directory=Path(tmp))

    def test_full_grade_model_and_lut(self):
        from color_grade import GRADE_DEFAULTS, grade_rgb, grade_filter
        self.assertEqual(grade_rgb((.2,.4,.6), {}), (.2,.4,.6))
        gray = grade_rgb((.2,.4,.6), {'saturation':0})
        self.assertAlmostEqual(gray[0],gray[1])
        self.assertAlmostEqual(gray[1],gray[2])
        self.assertGreater(grade_rgb((.2,.2,.2),{'exposure':1})[0],.2)
        for key,value in [('temperature',.5),('tint',.5),('shadows',.5),('highlights',-.5),('vibrance',.5)]:
            self.assertNotEqual(grade_rgb((.2,.4,.6),{key:value}),(.2,.4,.6))
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(grade_filter(GRADE_DEFAULTS,tmp),'')
            f = grade_filter({'exposure':.5,'temperature':.2},tmp)
            self.assertIn('lut3d',f)
            self.assertEqual(len(list(Path(tmp).glob('*.cube'))),1)
            self.assertEqual(grade_filter({'exposure':.5,'temperature':.2},tmp),f)
            import shutil,subprocess
            if shutil.which('ffmpeg'):
                result=subprocess.run(['ffmpeg','-v','error','-f','lavfi','-i','color=red:s=32x32:d=0.1','-vf',f[1:],'-frames:v','1','-f','null','-'],capture_output=True,text=True)
                self.assertEqual(result.returncode,0,result.stderr)
