"""Starter initialization and export must preserve and exclude private data."""
import os
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from tools.workspace import FOLDERS, initialize
from tools.starter_pack import export

ROOT = Path(__file__).resolve().parents[1]
PICKER = ROOT / "tools/pick_python.sh"


def pick(*candidates):
    return subprocess.run([str(PICKER), *candidates], capture_output=True, text=True)


def fake_python(folder, name, body):
    """A stand-in interpreter: a shell script that answers like Python would."""
    path = Path(folder) / name
    path.write_text("#!/bin/sh\n" + body)
    path.chmod(0o755)
    return str(path)


class PickPythonTests(unittest.TestCase):
    """setup.sh must not trust the Python it just installed: a Homebrew bottle can be
    broken on the machine (pyexpat unloadable, so venv creation dies in ensurepip)."""

    def test_skips_interpreters_that_cannot_import_the_standard_library(self):
        with tempfile.TemporaryDirectory() as tmp:
            broken = fake_python(tmp, "python3.11", "echo 'ImportError: dlopen pyexpat' >&2\nexit 1\n")
            missing = os.path.join(tmp, "python3.12")
            result = pick(broken, missing, sys.executable)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), sys.executable)

    def test_skips_interpreters_older_than_3_10(self):
        with tempfile.TemporaryDirectory() as tmp:
            old = fake_python(tmp, "python3", 'if [ "$1" = -c ]; then exit 1; fi\n')
            result = pick(old, sys.executable)
        self.assertEqual(result.stdout.strip(), sys.executable)

    def test_fails_clearly_when_nothing_works(self):
        with tempfile.TemporaryDirectory() as tmp:
            broken = fake_python(tmp, "python3.11", "exit 1\n")
            result = pick(broken)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(result.stdout, "")
        self.assertIn("No working Python", result.stderr)
        self.assertIn(broken, result.stderr)


class StarterTests(unittest.TestCase):
    def test_initialization_preserves_existing_data(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            initialize(root)
            avatar = root / "workspace/channel/avatar.png"
            avatar.write_bytes(b"personal avatar")
            project = root / "workspace/projects/personal.json"
            project.write_text("private")
            initialize(root)
            self.assertTrue(all((root / folder).is_dir() for folder in FOLDERS))
            self.assertEqual(avatar.read_bytes(), b"personal avatar")
            self.assertEqual(project.read_text(), "private")

    def test_export_only_committed_application_content(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            def git(*args):
                return subprocess.run(["git", *args], cwd=root, check=True, capture_output=True)
            git("init")
            files = {"README.md": "readme", "start.sh": "#!/bin/bash\n",
                     "scripts/app.py": "code", "data/secret.json": "secret",
                     "audio/private.wav": "sound", "tests/test_private.py": "test",
                     "scripts/models/private.pt": "weights",
                     "scripts/clipper_ui/assets/mars.jpg": "public image",
                     "scripts/clipper_ui/assets/mars-texture.jpg": "public texture",
                     "scripts/clipper_ui/assets/CREDITS.md": "image credit",
                     "scripts/clipper_ui/assets/private.jpg": "private image"}
            for name, content in files.items():
                path = root / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(content)
            git("add", ".")
            git("-c", "user.name=Test", "-c", "user.email=test@example.invalid", "commit", "-m", "fixture")
            (root / "scripts/app.py").write_text("uncommitted secret")
            destination = root / "starter.zip"
            export(destination, root)
            with zipfile.ZipFile(destination) as archive:
                self.assertEqual(set(archive.namelist()), {"clipbench/README.md", "clipbench/start.sh", "clipbench/scripts/app.py", "clipbench/scripts/clipper_ui/assets/mars.jpg", "clipbench/scripts/clipper_ui/assets/mars-texture.jpg", "clipbench/scripts/clipper_ui/assets/CREDITS.md"})
                self.assertEqual(archive.read("clipbench/scripts/app.py"), b"code")
                self.assertTrue(archive.getinfo("clipbench/start.sh").external_attr >> 16 & 0o111)
            with self.assertRaises(FileExistsError):
                export(destination, root)
