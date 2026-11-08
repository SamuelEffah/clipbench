"""Rendered clips kept between Short renders.

Each clip of a Short is cut, retimed, framed and graded on its own before the clips are joined. That work
depends only on the clip's source and settings, so its result is kept in a folder keyed by them: the next
render of the Short only redoes the clips that changed. Loudness measurements are kept the same way.

Clips are .mov files with PCM sound, so a list of them concatenates exactly, with no encoder padding at
the seams.
"""
import hashlib
import json
import os
import subprocess
import tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

VERSION = 2
DEFAULT_LIMIT = 6 * 1024 ** 3
LOUDNESS_FILE = "loudness.json"
PARALLEL = 4
SUFFIX = ".mov"
FPS = 30
TIMESCALE = 15360


def file_stamp(path):
    """What identifies a file's content cheaply: its path, size and modification time."""
    try:
        st = os.stat(path)
    except OSError:
        return (str(path), None, None)
    return (str(path), st.st_size, st.st_mtime_ns)


def clip_key(inputs, filters, codec, frames=None):
    """Digest of everything that shapes one rendered clip: the input files and ranges, the filter lines, the encoder, the frame count."""
    stamped = [file_stamp(arg) if i and inputs[i - 1] == "-i" else arg for i, arg in enumerate(inputs)]
    text = json.dumps({"v": VERSION, "inputs": stamped, "filters": filters, "codec": codec, "frames": frames}, sort_keys=True)
    return hashlib.sha256(text.encode()).hexdigest()[:24]


class ClipCache:
    def __init__(self, directory, limit=DEFAULT_LIMIT):
        self.dir = Path(directory)
        self.limit = limit
        self.dir.mkdir(parents=True, exist_ok=True)
        self.hits = self.misses = 0

    def path(self, key):
        return self.dir / f"clip-{key}{SUFFIX}"

    def get(self, key):
        """The kept clip for a key, or None."""
        dest = self.path(key)
        if dest.is_file() and dest.stat().st_size > 0:
            os.utime(dest)
            return str(dest)
        return None

    def put(self, key, render):
        """Make the clip with `render(dest)` and keep it; nothing is kept when the render fails."""
        dest = self.path(key)
        fd, temp = tempfile.mkstemp(dir=self.dir, prefix="part-", suffix=SUFFIX)
        os.close(fd)
        try:
            render(temp)
            os.replace(temp, dest)
        finally:
            Path(temp).unlink(missing_ok=True)
        return str(dest)

    def clips(self, specs, render):
        """The kept clip for each (inputs, filters, codec, frames) spec, rendering the missing ones a few at a time."""
        keys = [clip_key(*spec) for spec in specs]
        found = [self.get(key) for key in keys]
        missing = [(key, spec) for key, spec, path in zip(keys, specs, found) if path is None]
        self.hits += len(specs) - len(missing)
        self.misses += len(missing)
        with ThreadPoolExecutor(max_workers=PARALLEL) as pool:
            made = list(pool.map(lambda item: self.put(item[0], lambda dest: render(*item[1], dest)), missing))
        rendered = dict(zip([key for key, _ in missing], made))
        return [path or rendered[key] for key, path in zip(keys, found)]

    def loudness(self, src, start, length, track, measure):
        """A clip range's measured loudness, measured once per source file version."""
        stamp = file_stamp(src)
        key = json.dumps([stamp, round(start, 3), round(length, 3), track])
        table = self._loudness_table()
        if key in table:
            return table[key]
        value = measure(src, start, length, track)
        self._write_loudness({**table, key: value})
        return value

    def _loudness_table(self):
        try:
            table = json.loads((self.dir / LOUDNESS_FILE).read_text())
        except (OSError, ValueError):
            return {}
        return table if isinstance(table, dict) else {}

    def _write_loudness(self, table):
        target = self.dir / LOUDNESS_FILE
        fd, temp = tempfile.mkstemp(dir=self.dir, prefix="loud-", suffix=".json")
        with os.fdopen(fd, "w") as out:
            json.dump(table, out)
        os.replace(temp, target)

    def prune(self):
        """Drop the least recently used clips until the folder fits its size limit; forget stray part files."""
        clips = []
        for entry in self.dir.glob(f"*{SUFFIX}"):
            try:
                st = entry.stat()
            except OSError:
                continue
            if entry.name.startswith("part-"):
                entry.unlink(missing_ok=True)
                continue
            clips.append((st.st_mtime_ns, st.st_size, entry))
        total = sum(size for _, size, _ in clips)
        for _, size, entry in sorted(clips):
            if total <= self.limit:
                break
            entry.unlink(missing_ok=True)
            total -= size


def frame_count(length):
    """How many frames a clip of `length` seconds takes at the Short's frame rate."""
    return max(1, round(length * FPS))


def render_clip(inputs, filters, codec, frames, dest):
    """Encode one clip: its inputs through its filter lines into dest, with the scratch encoder and PCM sound.

    Every clip is written at the Short's frame rate on one clock and cut to its own frame count, so a list of
    clips reads as one steady stream with each cut on the frame the cut list puts it."""
    cmd = ["ffmpeg", "-y", "-loglevel", "error", *inputs, "-filter_complex", ";".join(filters + [f"[v0]fps={FPS}[vf]"]),
           "-map", "[vf]", "-map", "[a0]", "-map_chapters", "-1", *codec, "-pix_fmt", "yuv420p", "-frames:v", str(frames),
           "-video_track_timescale", str(TIMESCALE), "-c:a", "pcm_s16le", "-f", "mov", dest]
    subprocess.run(cmd, check=True)


def write_list(files, dest):
    """A concat demuxer list of the files, for ffmpeg to read them as one stream."""
    lines = ["ffconcat version 1.0"] + ["file '" + str(Path(f).resolve()).replace("'", r"'\''") + "'" for f in files]
    Path(dest).write_text("\n".join(lines) + "\n")
    return str(dest)


def list_input(path):
    """ffmpeg input arguments that read a concat list as one stream."""
    return ["-f", "concat", "-safe", "0", "-i", str(path)]
