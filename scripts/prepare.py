"""Get a video ready for suggestions in the background: one video at a time, each step reported as it runs.

The work itself (scanning, listening, ranking) is passed in, so this only holds the queue and the status."""
import threading
from collections import deque


class Queue:
    def __init__(self, work):
        """`work(vid, step)` does one video's preparation and calls step("what it is doing") as it goes."""
        self.work = work
        self.lock = threading.Lock()
        self.pending = deque()
        self.status = {}
        self.running = False

    def add(self, vid):
        """Queue a video. One that is already queued or running is left alone; a finished one is prepared again."""
        with self.lock:
            if self.status.get(vid, {}).get("state") in ("queued", "working"):
                return dict(self.status[vid])
            self.status[vid] = {"state": "queued", "step": "Waiting"}
            self.pending.append(vid)
            start = not self.running
            self.running = True
            state = dict(self.status[vid])
        if start:
            threading.Thread(target=self._loop, daemon=True).start()
        return state

    def get(self, vid):
        with self.lock:
            return dict(self.status.get(vid) or {"state": "none"})

    def _set(self, vid, **fields):
        with self.lock:
            self.status[vid] = {**self.status.get(vid, {}), **fields}

    def _loop(self):
        while True:
            with self.lock:
                if not self.pending:
                    self.running = False
                    return
                vid = self.pending.popleft()
            self._set(vid, state="working", step="Starting")
            try:
                self.work(vid, lambda text: self._set(vid, step=text))
                self._set(vid, state="ready", step="")
            except Exception as err:
                print(f"prepare {vid} failed: {err!r}", flush=True)
                self._set(vid, state="error", step="", message="Couldn't get this video ready")
