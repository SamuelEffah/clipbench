import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import dialogue_search as ds  # noqa: E402

CUES = [(10.0, 12.0, "I am you."), (20.0, 21.0, "Why do you always"), (21.2, 23.0, "just assume it's your fault?"), (40.0, 42.0, "Don't run away!")]


class Hits(unittest.TestCase):
    def test_finds_a_line_ignoring_case_and_punctuation(self):
        self.assertEqual(ds.hits(CUES, "DON'T run away")[0][:2], (40.0, 42.0))
        self.assertEqual(ds.hits(CUES, "dont run away")[0][:2], (40.0, 42.0))

    def test_a_sentence_split_over_two_lines_is_one_hit_spanning_both(self):
        found = ds.hits(CUES, "you always just assume")
        self.assertEqual(found, [(20.0, 23.0, "Why do you always just assume it's your fault?")])

    def test_a_word_in_the_second_line_only_does_not_start_at_the_first(self):
        self.assertEqual([h[0] for h in ds.hits(CUES, "your fault")], [21.2])

    def test_empty_or_symbol_only_queries_find_nothing(self):
        self.assertEqual(ds.hits(CUES, ""), [])
        self.assertEqual(ds.hits(CUES, "?!"), [])

    def test_no_match(self):
        self.assertEqual(ds.hits(CUES, "pineapple"), [])


class Frame(unittest.TestCase):
    def test_pulls_both_ends_onto_nearby_scene_cuts(self):
        start, stop, cut = ds.frame(10.0, 12.0, [9.5, 12.8, 30.0], 100.0)
        self.assertEqual((start, stop, cut), (9.5, 12.8, True))

    def test_pads_when_no_cut_is_near(self):
        start, stop, cut = ds.frame(10.0, 12.0, [50.0], 100.0)
        self.assertEqual((start, stop, cut), (9.7, 12.5, False))

    def test_stays_inside_the_video(self):
        start, stop, _ = ds.frame(0.1, 99.9, [], 100.0)
        self.assertEqual((start, stop), (0.0, 100.0))


class Search(unittest.TestCase):
    def test_result_limit_stops_reading_the_rest_of_a_long_track(self):
        from unittest import mock
        cues = [(float(n), n + 0.5, "again") for n in range(2000)]
        with mock.patch.object(ds, "normalize", wraps=ds.normalize) as normalize:
            found = ds.search([("a" * 12, "e", "/e", 3000.0, cues, [])], "again", limit=5)
        self.assertEqual(len(found), 5)
        self.assertLess(normalize.call_count, 20)

    def test_searches_every_video_and_skips_ones_without_subtitles(self):
        videos = [("a" * 12, "ep1.mkv", "/x/ep1.mkv", 100.0, CUES, []), ("b" * 12, "ep2.mkv", "/x/ep2.mkv", 100.0, None, []),
                  ("c" * 12, "ep3.mkv", "/x/ep3.mkv", 100.0, [(5.0, 7.0, "I am you, Lain")], [])]
        found = ds.search(videos, "i am you")
        self.assertEqual([(r["name"], r["at"]) for r in found], [("ep1.mkv", 10.0), ("ep3.mkv", 5.0)])
        self.assertEqual(found[0]["path"], "/x/ep1.mkv")

    def test_stops_at_the_limit(self):
        cues = [(float(n), n + 0.5, "again") for n in range(0, 100, 2)]
        self.assertEqual(len(ds.search([("a" * 12, "e", "/e", 200.0, cues, [])], "again", limit=5)), 5)


if __name__ == "__main__":
    unittest.main()


class Scoped(unittest.TestCase):
    def test_only_the_projects_videos_are_searched(self):
        import tempfile
        from unittest import mock
        import clipper
        with tempfile.TemporaryDirectory() as tmp:
            names = ("a", "b", "c")
            for n in names:
                (Path(tmp) / f"{n}.mkv").touch()
            (Path(tmp) / "scenes.json").write_text("[]")
            registry = {n * 12: Path(tmp) / f"{n}.mkv" for n in names}
            library = [{"id": "a" * 12, "broll": False}, {"id": "c" * 12, "broll": True}]
            with mock.patch.object(clipper, "scan_library", return_value=library), mock.patch.object(clipper, "registry", registry), \
                    mock.patch.object(clipper.embedded_subs, "all_cues", return_value=[(5.0, 7.0, "I am you")]), \
                    mock.patch.object(clipper, "scene_path", return_value=Path(tmp) / "scenes.json"), \
                    mock.patch.object(clipper, "probe", return_value={"duration": 60.0}):
                found = clipper.search_dialogue("i am you", "demo")
        self.assertEqual([r["name"] for r in found["results"]], ["a.mkv"])
        self.assertEqual(found["videos"], 1)

    def test_a_short_query_searches_nothing(self):
        import clipper
        from unittest import mock
        with mock.patch.object(clipper, "scan_library", return_value=[]):
            self.assertEqual(clipper.search_dialogue(" a ", None), {"results": [], "videos": 0, "unheard": []})

    def test_opening_panel_skips_scene_files_but_keeps_video_and_unheard_counts(self):
        import tempfile
        from unittest import mock
        import clipper
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / 'episode.mkv'
            source.touch()
            scene = Path(tmp) / 'scenes.json'
            scene.write_text('[4.5, 7.5]')
            registry = {str(n): source for n in range(100)}
            registry['unheard'] = source
            library = [{'id': key, 'broll': False} for key in registry]
            cues = [[(5., 7., 'hello')]] * 100 + [None]
            original_read = Path.read_text
            with mock.patch.object(clipper, 'scan_library', return_value=library), \
                    mock.patch.object(clipper, 'registry', registry), \
                    mock.patch.object(clipper, 'dialogue_cues', side_effect=cues), \
                    mock.patch.object(clipper, 'scene_path', return_value=scene), \
                    mock.patch.object(clipper, 'probe', return_value={'duration': 60.}), \
                    mock.patch.object(Path, 'read_text', autospec=True, side_effect=original_read) as read:
                got = clipper.search_dialogue('')
            self.assertEqual(got['results'], [])
            self.assertEqual(got['videos'], 100)
            self.assertEqual(got['unheard'], [{'id': 'unheard', 'name': 'episode.mkv', 'working': False}])
            scene_reads = [call for call in read.call_args_list if call.args[0] == scene]
            self.assertEqual(scene_reads, [], "opening the panel must not read scene files")
