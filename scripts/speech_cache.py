"""Speech for clips, worked out ahead of time. Each clip is listened to once, in the background, a little wider than the
clip itself, and the timed words are kept on disk. A later request for the same clip, or the same clip trimmed a little,
is answered from there instead of running Whisper again."""
import hashlib
import json
import queue
import threading
import time
from pathlib import Path

PAD = 1.5
TOLERANCE = 0.05


def window(start, end):
    """The stretch that is listened to for a clip: the clip with PAD seconds either side, never before the start."""
    return max(0.0, start - PAD), end + PAD


def words_in(entry, start, end):
    """The words of a stored stretch that are mostly inside start to end, timed from `start` as the page expects."""
    shift, length = entry["a"] - start, end - start
    return [[w[0], round(w[1] + shift, 2), round(w[2] + shift, 2)] for w in entry["words"]
            if 0 <= (w[1] + w[2]) / 2 + shift <= length]


class SpeechCache:
    def __init__(self, directory, listen):
        """`listen(src, start, end)` returns the timed words [text, start, end] of that stretch (an empty list for no
        speech), or None when it could not listen and may be asked again later."""
        self.directory = Path(directory)
        self.listen = listen
        self.entries = {}
        self.pending = set()
        self.jobs = queue.Queue()
        self.lock = threading.Lock()
        self.worker = None
        self._load()

    def _load(self):
        if not self.directory.is_dir():
            return
        index_path = self.directory / ".index.json"
        try:
            saved = json.loads(index_path.read_text())
            saved = saved["files"] if saved.get("version") == 1 else {}
            if not isinstance(saved, dict):
                saved = {}
        except (OSError, ValueError, KeyError, TypeError, AttributeError):
            saved = {}
        index = {}
        for path in sorted(self.directory.glob("*.json")):
            if path == index_path:
                continue
            try:
                stamp = path.stat()
                meta = saved.get(path.name)
                if isinstance(meta, dict):
                    try:
                        float(meta["a"]), float(meta["b"])
                        if not isinstance(meta["src"], str):
                            meta = None
                    except (KeyError, TypeError, ValueError):
                        meta = None
                if (not isinstance(meta, dict) or meta.get("size") != stamp.st_size
                        or meta.get("mtime") != stamp.st_mtime_ns):
                    entry = json.loads(path.read_text())
                    meta = {"src": entry["src"], "a": float(entry["a"]), "b": float(entry["b"]),
                            "size": stamp.st_size, "mtime": stamp.st_mtime_ns}
                    # Missing word data is not a valid cache entry.
                    entry["words"]
                record = {"a": float(meta["a"]), "b": float(meta["b"]), "path": path}
                self.entries.setdefault(meta["src"], []).append(record)
                index[path.name] = meta
            except (OSError, ValueError, KeyError, TypeError):
                continue
        if index != saved:
            try:
                part = self.directory / ".index.json.part"
                part.write_text(json.dumps({"version": 1, "files": index}))
                part.replace(index_path)
            except OSError:
                pass  # A read-only cache can still serve its saved transcripts.

    def _covering(self, src, start, end):
        for entry in self.entries.get(src, []):
            if entry["a"] <= start + TOLERANCE and entry["b"] >= end - TOLERANCE:
                if "words" not in entry:
                    try:
                        entry["words"] = json.loads(entry["path"].read_text())["words"]
                    except (OSError, ValueError, KeyError, TypeError):
                        continue
                return entry
        return None

    def find(self, src, start, end):
        """The words for a clip when they are already known, else None. An empty list means it was heard and has no speech."""
        with self.lock:
            entry = self._covering(src, start, end)
        return None if entry is None else words_in(entry, start, end)

    def queue(self, src, start, end):
        """Listen to this clip in the background, unless it is already known or on its way. One clip at a time."""
        a, b = window(start, end)
        key = (src, round(a, 2), round(b, 2))
        with self.lock:
            if self._covering(src, start, end) is not None or key in self.pending:
                return False
            self.pending.add(key)
            self.jobs.put((key, src, a, b))
            if self.worker is None or not self.worker.is_alive():
                self.worker = threading.Thread(target=self._run, daemon=True)
                self.worker.start()
        return True

    def _run(self):
        while True:
            try:
                key, src, a, b = self.jobs.get(timeout=5)
            except queue.Empty:
                return
            try:
                words = self.listen(src, a, b)
                if words is not None:
                    self._store(src, a, b, words)
            except Exception:
                pass
            finally:
                with self.lock:
                    self.pending.discard(key)

    def _store(self, src, a, b, words):
        entry = {"src": src, "a": a, "b": b, "words": words}
        name = hashlib.sha1(f"{src}|{a:.2f}|{b:.2f}".encode()).hexdigest()[:16]
        self.directory.mkdir(parents=True, exist_ok=True)
        part = self.directory / f"{name}.json.part"
        part.write_text(json.dumps(entry))
        part.replace(self.directory / f"{name}.json")
        with self.lock:
            self.entries.setdefault(src, []).append({"a": a, "b": b, "words": words})

    def wait(self, timeout=5.0):
        """Block until the queued clips are done, or the timeout passes. For tests."""
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            with self.lock:
                if not self.pending:
                    return True
            time.sleep(0.01)
        return False
