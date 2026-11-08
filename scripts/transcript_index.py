"""What is said in a whole video, listened to once and kept on disk, so videos with no subtitle track can be searched
like the ones that have one. A transcript belongs to the file it was made from and is dropped when the file changes."""
import hashlib
import json
from collections import OrderedDict
import sys
import threading
from pathlib import Path


def path_for(data_dir, src):
    return Path(data_dir) / "transcripts" / f"{hashlib.sha1(str(src).encode()).hexdigest()[:12]}.json"


def _stamp(src):
    stat = Path(src).stat()
    return [stat.st_size, int(stat.st_mtime)]


def cues_from(result):
    """[(from, to, text)] for each line Whisper heard; blank and zero-length lines are left out."""
    out = []
    for seg in (result or {}).get("segments", []):
        text = " ".join(str(seg.get("text", "")).split())
        a, b = float(seg.get("start", 0)), float(seg.get("end", 0))
        if text and b > a:
            out.append((a, b, text))
    return out


CACHE_ENTRY_LIMIT = 128
CACHE_BYTE_LIMIT = 16 * 1024 * 1024
_line_cache = OrderedDict()
_line_cache_bytes = 0
_line_cache_lock = threading.Lock()


def clear_cache():
    global _line_cache_bytes
    with _line_cache_lock:
        _line_cache.clear()
        _line_cache_bytes = 0


def _saved_lines(path, version):
    """Retain a library working set, bounded by parsed data size and entry count."""
    global _line_cache_bytes
    with _line_cache_lock:
        cached = _line_cache.get(path)
        if cached and cached[0] == version:
            _line_cache.move_to_end(path)
            return cached[1]
        if cached:
            _line_cache_bytes -= _line_cache.pop(path)[2]
    # File I/O and parsing do not block readers of other transcripts.
    saved = json.loads(path.read_text())
    cues = tuple((float(a), float(b), str(text)) for a, b, text in saved["cues"])
    result = (saved["stamp"], cues)
    # Conservatively count each reference, even if Python shares its object.
    weight = (sys.getsizeof(path) + sys.getsizeof(version) + sys.getsizeof(result)
              + sys.getsizeof(result[0]) + sum(sys.getsizeof(v) for v in result[0])
              + sys.getsizeof(cues) + sum(sys.getsizeof(cue) + sum(sys.getsizeof(v) for v in cue) for cue in cues))
    if weight <= CACHE_BYTE_LIMIT:
        with _line_cache_lock:
            previous = _line_cache.pop(path, None)
            if previous:
                _line_cache_bytes -= previous[2]
            _line_cache[path] = (version, result, weight)
            _line_cache_bytes += weight
            while len(_line_cache) > CACHE_ENTRY_LIMIT or _line_cache_bytes > CACHE_BYTE_LIMIT:
                _, removed = _line_cache.popitem(last=False)
                _line_cache_bytes -= removed[2]
    return result


def load(data_dir, src):
    """The saved lines of a video, [] when it was heard and has no speech, None when it was never listened to or the file has changed since."""
    try:
        path = path_for(data_dir, src).absolute()
        stat = path.stat()
        version = (stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns, stat.st_ino)
        stamp, cues = _saved_lines(path, version)
        if stamp != _stamp(src):
            return None
        return list(cues)
    except (OSError, ValueError, KeyError, TypeError):
        return None


def save(data_dir, src, cues):
    target = path_for(data_dir, src)
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix(".tmp")
    tmp.write_text(json.dumps({"src": str(src), "stamp": _stamp(src), "cues": [list(c) for c in cues]}))
    tmp.replace(target)


def build(data_dir, src, listen):
    """Listen to the whole video with `listen(src)`, which returns Whisper's result and raises when it cannot, and keep the lines."""
    cues = cues_from(listen(src))
    save(data_dir, src, cues)
    return cues
