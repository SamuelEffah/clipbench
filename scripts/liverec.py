"""Records a live stream that keeps almost no history of its own (Twitch holds about 6 seconds), so clips can be cut from
what was recorded while you watched."""
import os
import signal
import subprocess
import threading
import time
from pathlib import Path

RECORD_LIMIT = 7200
SETTLE = 2
STREAM_FORMAT = "best[height<=1080][protocol*=m3u8]/best[protocol*=m3u8]/best"


def window(started, wall_start, wall_end, now):
    """Where a stretch sits in a recording that began at wall-clock time `started`, as (offset, length) in seconds.
    The end is held to what has been recorded so far."""
    end = min(wall_end, now)
    if wall_end <= wall_start:
        raise ValueError("Mark the out after the in")
    if wall_start < started:
        raise ValueError("That moment is from before the recording started. Mark one from after it")
    if end <= wall_start:
        raise ValueError("That moment hasn't been recorded yet")
    return wall_start - started, end - wall_start


class Recorder:
    """One recording at a time, into a file in `folder`. The file stays after it stops, so a cut that is still running
    can finish; it goes when the next recording starts, or on clear()."""

    def __init__(self, folder, settle=SETTLE):
        self.folder, self.settle = Path(folder), settle
        self._lock = threading.Lock()
        self._proc = self._url = self._path = self._started = None

    def clear(self):
        for old in self.folder.glob("rec-*.ts"):
            old.unlink(missing_ok=True)

    def reap(self):
        """Stops a recorder left running by a server that died without cleaning up, then clears its files."""
        pidfile = self.folder / "rec.pid"
        try:
            pid = int(pidfile.read_text())
            command = subprocess.run(["ps", "-p", str(pid), "-o", "command="], capture_output=True, text=True, timeout=10).stdout
            if "rec-" in command and "-c copy" in command:
                os.kill(pid, signal.SIGTERM)
        except (OSError, ValueError, subprocess.SubprocessError):
            pass
        pidfile.unlink(missing_ok=True)
        self.clear()

    def start(self, exe, ffmpeg, url):
        """Begins recording the stream at `url` and returns the wall-clock time it began. Raises ValueError if it can't."""
        with self._lock:
            self._stop()
            self.clear()
            self.folder.mkdir(parents=True, exist_ok=True)
            try:
                got = subprocess.run([exe, "--no-warnings", "--no-playlist", "-g", "-f", STREAM_FORMAT, "--", url],
                                     capture_output=True, text=True, timeout=60)
            except (OSError, subprocess.SubprocessError):
                raise ValueError("Couldn't open the stream to record it")
            lines = got.stdout.split()
            if got.returncode or not lines:
                raise ValueError("Couldn't open the stream to record it. Is the channel live?")
            path = self.folder / f"rec-{int(time.time())}.ts"
            proc = subprocess.Popen([ffmpeg, "-v", "error", "-y", "-i", lines[0], "-t", str(RECORD_LIMIT), "-c", "copy", "-f", "mpegts", str(path)],
                                    stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)
            started = time.time()
            (self.folder / "rec.pid").write_text(str(proc.pid))
            time.sleep(self.settle)
            if proc.poll() is not None:
                detail = (proc.stderr.read() or "").strip().splitlines()
                raise ValueError(f"Recording stopped straight away: {detail[-1][:200]}" if detail else "Recording stopped straight away")
            self._proc, self._url, self._path, self._started = proc, url, path, started
            return started

    def _stop(self):
        proc, self._proc = self._proc, None
        self._url = None
        if proc and proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.SubprocessError:
                pass

    def stop(self):
        with self._lock:
            self._stop()

    def active(self, url):
        """(file, started) while `url` is being recorded, else None."""
        with self._lock:
            if self._proc and self._url == url and self._proc.poll() is None:
                return self._path, self._started
        return None
