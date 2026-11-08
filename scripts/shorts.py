"""The Shorts that have been rendered: what's on disk in shorts/NNN_name/, with each one's upload state."""
import re
import stat
import subprocess
import threading
from concurrent.futures import Future
from pathlib import Path

FOLDER_RE = re.compile(r"^(\d{3})_([A-Za-z0-9_-]+)$")
THUMB_SECOND = 1.0
_pending_thumbnails = {}
_thumbnail_lock = threading.Lock()


def current_upload(upload, video_mtime):
    """The upload state that applies to the video as it is now. An upload that finished before the video was last rendered
    was of an earlier version, so the Short counts as not uploaded."""
    done_at = upload.get("finished_at")
    if upload.get("state") in ("done", "error") and done_at and done_at < video_mtime:
        return {"state": "none"}
    return upload


def list_shorts(short_dir, project_names, upload_state, duration_of):
    """Rendered Shorts, newest first. `upload_state(name)` and `duration_of(path)` are passed in so this stays pure."""
    short_dir = Path(short_dir)
    if not short_dir.is_dir():
        return []
    known = set(project_names)
    rows = []
    for folder in short_dir.iterdir():
        match = FOLDER_RE.match(folder.name)
        video = folder / "video.mp4"
        if not folder.is_dir() or not match:
            continue
        try:
            video_stat = video.stat()
        except OSError:
            continue
        if not stat.S_ISREG(video_stat.st_mode):
            continue
        title_file = folder / "title.txt"
        name = match.group(2)
        rows.append({
            "name": name, "folder": folder.name, "number": int(match.group(1)),
            "title": title_file.read_text().strip() if title_file.is_file() else "",
            "size": video_stat.st_size, "rendered_at": video_stat.st_mtime,
            "duration": duration_of(video), "has_project": name in known, "upload": current_upload(upload_state(name), video_stat.st_mtime),
        })
    return sorted(rows, key=lambda r: (r["rendered_at"], r["number"]), reverse=True)


def with_stats(rows, stats):
    """The rows with the last counts read for each one's uploaded video under `stats`, None when there are none."""
    return [{**row, "stats": stats.get(row["upload"].get("video_id"))} for row in rows]


def ffmpeg_thumb(src, dest):
    out = subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-ss", str(THUMB_SECOND), "-i", str(src), "-frames:v", "1",
                          "-vf", "scale=270:-2", "-q:v", "4", str(dest)], capture_output=True)
    return out.returncode == 0 and Path(dest).is_file()


def thumbnail(folder, make=ffmpeg_thumb):
    """Path to the Short's cover frame, built on demand and rebuilt when the video is newer. None if it can't be made."""
    folder = Path(folder)
    video, thumb = folder / "video.mp4", folder / "thumb.jpg"
    if not video.is_file():
        return None
    if thumb.is_file() and thumb.stat().st_mtime >= video.stat().st_mtime:
        return thumb
    key = str(thumb.absolute())
    with _thumbnail_lock:
        pending = _pending_thumbnails.get(key)
        owner = pending is None
        if owner:
            pending = _pending_thumbnails[key] = Future()
    if not owner:
        return thumb if pending.result() is not None else None
    try:
        # Another request may have published the cover before this one took ownership.
        if thumb.is_file() and thumb.stat().st_mtime >= video.stat().st_mtime:
            result = thumb
        else:
            result = thumb if make(video, thumb) else None
        pending.set_result(result)
        return result
    except BaseException as err:
        pending.set_exception(err)
        raise
    finally:
        with _thumbnail_lock:
            _pending_thumbnails.pop(key, None)
