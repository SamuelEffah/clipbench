"""Read-only checks; never starts the server or scans user media."""
import importlib.util
import shutil
import subprocess
import sys
from pathlib import Path


def problems():
    errors = []
    if sys.version_info < (3, 10):
        errors.append("Python 3.10 or newer is required.")
    for module in ("PIL", "numpy", "cv2"):
        if importlib.util.find_spec(module) is None:
            errors.append(f"Missing Python module: {module}; rerun ./setup.sh")
    for command in ("ffmpeg", "ffprobe", "yt-dlp"):
        if not shutil.which(command):
            errors.append(f"Missing command: {command}; rerun ./setup.sh")
    if shutil.which("ffmpeg"):
        filters = subprocess.run(["ffmpeg", "-hide_banner", "-filters"], capture_output=True, text=True, check=True).stdout
        if " subtitles " not in filters:
            errors.append("FFmpeg needs the subtitles filter (libass).")
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
