import re
import unittest
from pathlib import Path

UI = Path(__file__).resolve().parent.parent / "scripts" / "clipper_ui"
LEXICAL = re.compile(r"^(?:const|let|class)\s+([A-Za-z_$][\w$]*)", re.M)
ANY = re.compile(r"^(?:async\s+)?(?:const|let|var|function\*?|class)\s+([A-Za-z_$][\w$]*)", re.M)


class PageScripts(unittest.TestCase):
    def test_no_const_let_or_class_name_is_declared_twice_across_the_page_scripts(self):
        """The page loads every script into one scope, and a const, let or class name that another script also
        declares is a syntax error that stops the later script from loading."""
        html = (UI / "index.html").read_text()
        scripts = re.findall(r'<script src="/([\w.-]+\.js)"', html)
        self.assertTrue(scripts)
        owners = {}
        for name in scripts:
            text = (UI / name).read_text()
            for found in set(ANY.findall(text)):
                owners.setdefault(found, []).append((name, found in LEXICAL.findall(text)))
        clashes = [f"{n} ({', '.join(f for f, _ in o)})" for n, o in owners.items() if len(o) > 1 and any(lex for _, lex in o)]
        self.assertEqual(clashes, [])

    def test_every_script_the_page_loads_is_one_the_server_serves(self):
        served = (UI.parent / "clipper.py").read_text()
        scripts = re.findall(r'<script src="/([\w.-]+\.js)"', (UI / "index.html").read_text())
        self.assertEqual([n for n in scripts if f'"/{n}": ("{n}"' not in served], [])


if __name__ == "__main__":
    unittest.main()
