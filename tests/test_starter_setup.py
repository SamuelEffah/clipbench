"""Starter initialization and export must preserve and exclude private data."""
import subprocess
import tempfile
import unittest
import zipfile
from pathlib import Path
from tools.workspace import FOLDERS, initialize
from tools.starter_pack import export


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
