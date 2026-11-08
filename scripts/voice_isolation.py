"""Keep only the voice of a clip, with the music and effects taken out, using demucs. The result is a wav of the clip's range,
saved by its source, range and track so the same clip is only separated once."""
import hashlib
import importlib.util
import shutil
import subprocess
import sys
import tempfile
import threading
from concurrent.futures import Future
from pathlib import Path

HINT = "Voice isolation isn't installed. In Terminal run: pip3 install demucs"
MODEL = "htdemucs"
_pending = {}
_pending_lock = threading.Lock()


def available():
    return importlib.util.find_spec("demucs") is not None


def cached_path(folder, src, start, end, track=0):
    """Where the voice of this stretch is (or will be) saved. Seconds are rounded to the millisecond, as cuts are."""
    key = hashlib.sha1(f"{src}|{start:.3f}|{end:.3f}|{track}".encode()).hexdigest()[:16]
    return Path(folder) / f"{key}.wav"


def isolate(folder, src, start, end, track=0):
    """The wav holding only the voice of src from start to end, separating it if it is not saved yet. Raises ValueError with a
    message for the page when it can't. Concurrent requests share the same separation."""
    target = cached_path(folder, src, start, end, track)
    if target.is_file():
        return target
    key = str(target.absolute())
    with _pending_lock:
        pending = _pending.get(key)
        owner = pending is None
        if owner:
            pending = _pending[key] = Future()
    if not owner:
        pending.result()
        return target
    try:
        result = _isolate(src, start, end, track, target)
        pending.set_result(result)
        return result
    except BaseException as err:
        pending.set_exception(err)
        raise
    finally:
        with _pending_lock:
            _pending.pop(key, None)


def _isolate(src, start, end, track, target):
    if target.is_file():
        return target
    if not available():
        raise ValueError(HINT)
    target.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        wav = Path(tmp) / "clip.wav"
        cut = subprocess.run(["ffmpeg", "-y", "-v", "error", "-ss", f"{start:.3f}", "-t", f"{end - start:.3f}", "-i", src,
                              "-map", f"0:a:{track}", "-ac", "2", "-ar", "44100", str(wav)], capture_output=True, text=True)
        if cut.returncode != 0 or not wav.is_file():
            raise ValueError("This clip has no audio to take the voice from")
        done = subprocess.run([sys.executable, "-m", "demucs", "--two-stems=vocals", "-n", MODEL, "-o", tmp, str(wav)],
                              capture_output=True, text=True)
        voice = Path(tmp) / MODEL / "clip" / "vocals.wav"
        if done.returncode != 0 or not voice.is_file():
            tail = (done.stderr or "").strip().splitlines()
            raise ValueError(f"Couldn't isolate the voice: {tail[-1] if tail else 'demucs stopped'}"[:300])
        part = target.with_suffix(".part")
        shutil.copyfile(voice, part)
        part.rename(target)
    return target
