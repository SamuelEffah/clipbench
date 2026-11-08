"""Find an FFmpeg that can draw text and burn captions.

The renderer uses the drawtext and subtitles filters, which need freetype and libass.
Homebrew's plain `ffmpeg` formula no longer builds with either; `ffmpeg-full` does, but
it is keg-only, so Homebrew never links it into PATH. The server and the renderer put an
installed ffmpeg-full first themselves, so it works however the app was started.
"""
import os
from pathlib import Path

FULL_BUILDS = (Path("/opt/homebrew/opt/ffmpeg-full/bin"), Path("/usr/local/opt/ffmpeg-full/bin"))
NEEDED_FILTERS = ("drawtext", "subtitles")


def prefer_full_ffmpeg(environ=os.environ, builds=FULL_BUILDS):
    """The PATH value with an installed ffmpeg-full in front; the environment given is not changed."""
    path = environ.get("PATH", "")
    folders = path.split(os.pathsep) if path else []
    for folder in builds:
        if (folder / "ffmpeg").is_file():
            return path if str(folder) in folders else os.pathsep.join([str(folder), *folders])
    return path


def activate(environ=os.environ):
    """Apply prefer_full_ffmpeg to this process, and so to every FFmpeg it starts."""
    environ["PATH"] = prefer_full_ffmpeg(environ)


def missing_filters(filters_output):
    """Which of the filters the renderer needs are absent from `ffmpeg -filters` output."""
    names = {line.split()[1] for line in filters_output.splitlines() if len(line.split()) > 1}
    return [name for name in NEEDED_FILTERS if name not in names]
