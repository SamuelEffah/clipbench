"""Read-only checks; never starts the server or scans user media."""
import importlib.util
import os
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import ffmpeg_env  # noqa: E402

FFMPEG_FIX = "install the full build with: brew install ffmpeg-full"


def ffmpeg_problems(path):
    """Problems with the FFmpeg tools found on the given PATH value."""
    errors = [f"Missing command: {command}; rerun ./setup.sh"
              for command in ("ffmpeg", "ffprobe", "yt-dlp") if not shutil.which(command, path=path)]
    ffmpeg = shutil.which("ffmpeg", path=path)
    if ffmpeg:
        filters = subprocess.run([ffmpeg, "-hide_banner", "-filters"], capture_output=True, text=True, check=True).stdout
        missing = ffmpeg_env.missing_filters(filters)
        if missing:
            errors.append(f"{ffmpeg} has no {' or '.join(missing)} filter; {FFMPEG_FIX}")
    return errors


def problems():
    errors = []
    if sys.version_info < (3, 10):
        errors.append("Python 3.10 or newer is required.")
    for module in ("PIL", "numpy", "cv2"):
        if importlib.util.find_spec(module) is None:
            errors.append(f"Missing Python module: {module}; rerun ./setup.sh")
    errors += ffmpeg_problems(ffmpeg_env.prefer_full_ffmpeg(os.environ))
    fonts = Path("/System/Library/Fonts")
    for font in ("Supplemental/Impact.ttf", "Supplemental/Arial Bold.ttf", "Supplemental/Arial.ttf", "Apple Color Emoji.ttc"):
        if not (fonts / font).is_file():
            errors.append(f"Missing macOS font: {font}")
    return errors


if __name__ == "__main__":
    errors = problems()
    if errors:
        sys.exit("\n".join(errors))
    print("Core dependencies and rendering fonts are ready.")
