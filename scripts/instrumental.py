"""Take the singing out of a song, keeping the band, using demucs. The result is a new mp3 beside the original, named
"<song> (instrumental)", so it shows up in the music list like any other file."""
import subprocess
import sys
import tempfile
from pathlib import Path

from voice_isolation import HINT, MODEL, available

SUFFIX = " (instrumental)"


def target_for(src):
    src = Path(src)
    return src.with_name(f"{src.stem}{SUFFIX}.mp3")


def make_instrumental(src):
    """The path of the instrumental of `src`, separating it if it is not there yet. Raises ValueError with a message for the page."""
    src = Path(src)
    if src.stem.endswith(SUFFIX.strip()):
        raise ValueError("This one is already an instrumental")
    target = target_for(src)
    if target.is_file():
        return target
    if not available():
        raise ValueError(HINT)
    with tempfile.TemporaryDirectory() as tmp:
        done = subprocess.run([sys.executable, "-m", "demucs", "--two-stems=vocals", "-n", MODEL, "-o", tmp, str(src)],
                              capture_output=True, text=True)
        stem = Path(tmp) / MODEL / src.stem / "no_vocals.wav"
        if done.returncode != 0 or not stem.is_file():
            tail = (done.stderr or "").strip().splitlines()
            raise ValueError(f"Couldn't take the singing out: {tail[-1] if tail else 'demucs stopped'}"[:300])
        part = target.with_suffix(".part.mp3")
        enc = subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(stem), "-codec:a", "libmp3lame", "-q:a", "2", str(part)],
                             capture_output=True, text=True)
        if enc.returncode != 0 or not part.is_file():
            raise ValueError("Couldn't save the instrumental")
        part.rename(target)
    return target
