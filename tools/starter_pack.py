"""Export committed application files only, never local data or credentials."""
import argparse
from pathlib import Path, PurePosixPath
import subprocess
import zipfile

ROOT = Path(__file__).resolve().parents[1]
FILES = {
    "README.md", "requirements.txt", "requirements-ai.txt", "setup.sh", "start.sh",
    "scripts/clipper_ui/assets/planet-logo.svg", "scripts/clipper_ui/assets/mars.jpg", "scripts/clipper_ui/assets/mars-texture.jpg", "scripts/clipper_ui/assets/CREDITS.md",
}


def include(name):
    path = PurePosixPath(name)
    return (name in FILES or
            (path.parts[0] == "scripts" and path.suffix in {".py", ".js", ".css", ".html", ".xml"}) or
            (path.parts[0] == "tools" and path.suffix == ".py"))


def export(destination, root=ROOT):
    # Read HEAD, not the working tree: ignored files and uncommitted edits cannot leak.
    names = subprocess.check_output(["git", "ls-tree", "-r", "--name-only", "HEAD"], cwd=root, text=True).splitlines()
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(destination, "x", zipfile.ZIP_DEFLATED) as archive:
        for name in names:
            if include(name):
                data = subprocess.check_output(["git", "show", f"HEAD:{name}"], cwd=root)
                entry = zipfile.ZipInfo(f"clipbench/{name}")
                entry.compress_type = zipfile.ZIP_DEFLATED
                entry.external_attr = (0o100755 if name.endswith(".sh") else 0o100644) << 16
                archive.writestr(entry, data)
    return destination


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path, help="New zip file to create (will not overwrite)")
    print(export(parser.parse_args().output))
