import json
import unittest
from unittest import mock
from tests.test_suggest import suggest


class SuggestQuality(unittest.TestCase):
    def test_long_setup_can_reach_its_payoff(self):
        cues = [(0, 9, 'I tried saving a minute every day.'),
                (9.2, 19, 'I spent a month building a machine to do it.'),
                (19.2, 29, 'Then I checked how much time I had actually saved.'),
                (29.2, 38, 'The machine took two hours to turn on.')]
        found = suggest.candidates(cues, 45, [])
        self.assertTrue(any(c['in'] == 0 and 'two hours' in c['text'] for c in found))

    def test_does_not_start_mid_sentence_or_snap_across_speech(self):
        cues = [(0, 4, 'The reason this works is'), (4.1, 9, 'that heat rises.'),
                (9.2, 18, 'Here is how to try it yourself.')]
        found = suggest.candidates(cues, 20, [0.2, 8.7, 17.8])
        self.assertFalse(any(c['text'].startswith('that heat') for c in found))
        complete = next(c for c in found if c['text'].startswith('The reason'))
        self.assertLessEqual(complete['in'], 0)
        self.assertGreaterEqual(complete['out'], 9)

    def test_quiet_sections_reach_model_even_if_one_section_is_loud(self):
        items = [{'in': i, 'out': i + 9, 'text': 'Loud!', 'score': 1} for i in range(100)]
        items += [{'in': 800, 'out': 812, 'text': 'A quiet reveal.', 'score': .1}]
        with mock.patch.object(suggest, 'candidates', return_value=items), mock.patch.object(suggest, 'heuristic', side_effect=lambda it, *_: it['score']), mock.patch.object(suggest, 'llm_scores', return_value={}) as rank:
            suggest.suggest([], 1000, [], [], 20, model='local')
        shortlist = rank.call_args.args[0]
        self.assertTrue(any('quiet reveal' in it['text'] for it in shortlist))
        self.assertLessEqual(len(shortlist), 60)

    def test_model_sees_surrounding_context_and_no_anime_assumption(self):
        captured = []
        class Response:
            def __enter__(self): return self
            def __exit__(self, *_): pass
            def read(self): return json.dumps({'message': {'content': '{"scores": []}'}}).encode()
        def respond(req, **kwargs):
            captured.append(json.loads(req.data)['messages'][0]['content'])
            return Response()
        with mock.patch('urllib.request.urlopen', side_effect=respond):
            suggest.ask('local', [{'text': 'It was empty.', 'before': 'I finally opened the box.', 'after': 'Everyone laughed.'}])
        self.assertIn('I finally opened the box.', captured[0])
        self.assertIn('Everyone laughed.', captured[0])
        self.assertNotIn('anime episode', captured[0])

    def test_all_model_failures_preserve_original_fallback(self):
        from tests.test_suggest import CUES
        plain = suggest.suggest(CUES, 100, [], [10] * 2000, 20)
        with mock.patch.object(suggest, 'llm_scores', return_value={}):
            ranked = suggest.suggest(CUES, 100, [], [10] * 2000, 20, model='local')
        self.assertEqual(plain, ranked)

    def test_unpunctuated_transcript_still_produces_candidates(self):
        cues = [(i * 4, i * 4 + 3.8, 'words without punctuation') for i in range(30)]
        found = suggest.candidates(cues, 120, [])
        self.assertTrue(found)
        self.assertTrue(all(0 <= c['in'] < c['out'] <= 120 for c in found))
        self.assertTrue(all(c['out'] - c['in'] <= suggest.MAX_LEN + 2 for c in found))

    def test_old_and_corrupt_suggestion_caches_are_rebuilt(self):
        import tempfile
        from pathlib import Path
        import clipper
        with tempfile.TemporaryDirectory() as folder:
            source, cache = Path(folder) / 'video.mp4', Path(folder) / 'suggest.json'
            source.write_bytes(b'video')
            with mock.patch.object(clipper, 'registry', {'v': str(source)}), mock.patch.object(clipper, 'suggest_jobs', {}), mock.patch.object(clipper, 'suggest_path', return_value=cache):
                cache.write_text(json.dumps({'state': 'ready', 'clips': []}))
                self.assertEqual(clipper.get_suggest('v'), {'state': 'none'})
                cache.write_text('bad json')
                self.assertEqual(clipper.get_suggest('v'), {'state': 'none'})
                expected = {'state': 'ready', 'clips': [], 'version': suggest.VERSION}
                cache.write_text(json.dumps(expected))
                self.assertEqual(clipper.get_suggest('v'), expected)
