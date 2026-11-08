"""Connect a YouTube account and upload rendered Shorts in the background, recording each try in the store."""
import logging
import secrets
import threading
import time
from pathlib import Path

import youtube as yt

CONNECT_WINDOW = 600
CHANNEL_RETRY = 600  # seconds before asking YouTube for the channel's name again after a failed lookup
CALLBACK_PATH = "/api/youtube/callback"


class Publisher:
    channel_asked = float("-inf")  # when YouTube was last asked who the channel is

    def __init__(self, store, client_path, run=yt.curl_run, clock=time.time):
        self.store, self.client_path, self.run, self.clock = store, Path(client_path), run, clock
        self.lock = threading.Lock()
        self.pending = {}
        self.live = {}
        self.threads = {}

    def status(self):
        try:
            yt.load_client(self.client_path)
        except yt.YouTubeError as err:
            return {"configured": False, "connected": False, "message": str(err)}
        tokens = self.store.get_setting(yt.TOKEN_KEY)
        return {"configured": True, "connected": bool(tokens and tokens.get("refresh_token")), "message": "", "channel": self.channel()}

    def channel(self):
        """The connected channel's name and handle, {} when nothing is connected or YouTube has not said yet. Asked once
        and kept; after a failed lookup it is asked again at most every CHANNEL_RETRY seconds."""
        known = self.store.get_setting(yt.CHANNEL_KEY)
        if known:
            return dict(known)
        tokens = self.store.get_setting(yt.TOKEN_KEY)
        if not tokens or not tokens.get("refresh_token") or self.clock() - self.channel_asked < CHANNEL_RETRY:
            return {}
        try:
            return self._remember_channel(yt.access_token(self.store, yt.load_client(self.client_path), self.run, self.clock()))
        except yt.YouTubeError:
            return {}

    def _remember_channel(self, token):
        self.channel_asked = self.clock()
        try:
            found = yt.channel_identity(token, self.run)
        except yt.YouTubeError as err:
            logging.getLogger("clipbench.youtube").warning("channel lookup failed: %s", err)
            return {}
        if found:
            self.store.set_setting(yt.CHANNEL_KEY, found)
        return found

    def begin_connect(self, port):
        client = yt.load_client(self.client_path)
        verifier, challenge = yt.new_pkce()
        state, now = secrets.token_urlsafe(24), self.clock()
        with self.lock:
            self.pending = {s: p for s, p in self.pending.items() if p["expires"] > now}
            self.pending[state] = {"verifier": verifier, "expires": now + CONNECT_WINDOW}
        return yt.auth_url(client, self._redirect(port), state, challenge)

    def finish_connect(self, port, query):
        if query.get("error"):
            raise yt.YouTubeError("Access was not granted, so YouTube is still not connected")
        state, code = (query.get("state") or [""])[0], (query.get("code") or [""])[0]
        with self.lock:
            pending = self.pending.pop(state, None)
        if not pending or pending["expires"] <= self.clock() or not code:
            raise yt.YouTubeError("That sign-in link expired or didn't start here. Press Connect again.")
        client = yt.load_client(self.client_path)
        tokens = yt.exchange_code(client, code, pending["verifier"], self._redirect(port), self.run, self.clock())
        self.store.set_setting(yt.TOKEN_KEY, tokens)
        self.store.delete_setting(yt.CHANNEL_KEY)
        self._remember_channel(tokens["access_token"])

    def disconnect(self):
        self.store.delete_setting(yt.TOKEN_KEY)
        self.store.delete_setting(yt.CHANNEL_KEY)

    def start_upload(self, short, video_path, title, description):
        video_path = Path(video_path)
        if not video_path.is_file():
            raise yt.YouTubeError("Render the Short first")
        yt.validate_metadata(title, description)
        client = yt.load_client(self.client_path)
        token = yt.access_token(self.store, client, self.run, self.clock())
        with self.lock:
            if self.live.get(short, {}).get("state") == "uploading":
                return dict(self.live[short])
            upload_id = self.store.add_upload(short, title.strip(), yt.UPLOAD_PRIVACY)
            self.live[short] = {"state": "uploading", "pct": 0}
        thread = threading.Thread(target=self._run_upload, args=(short, upload_id, token, video_path, title, description), daemon=True)
        self.threads[short] = thread
        thread.start()
        return dict(self.live[short])

    def _run_upload(self, short, upload_id, token, video_path, title, description):
        def progress(pct):
            with self.lock:
                self.live[short] = {"state": "uploading", "pct": int(pct)}
        upload_log = logging.getLogger("clipbench.youtube")
        upload_log.info("%s: uploading %s", short, video_path)
        try:
            uploaded = yt.upload_video(token, video_path, title, description, self.run, progress)
            self.store.finish_upload(upload_id, uploaded.video_id, uploaded.privacy)
            upload_log.info("%s: uploaded as %s (%s)", short, uploaded.video_id, uploaded.privacy)
        except yt.YouTubeError as err:
            if isinstance(err, yt.YouTubeAuthError):
                self.store.delete_setting(yt.TOKEN_KEY)
            upload_log.warning("%s: upload failed: %s", short, err)
            self.store.fail_upload(upload_id, err)
        except Exception as err:
            upload_log.exception("%s: upload crashed", short)
            self.store.fail_upload(upload_id, f"Unexpected error: {err}")
        finally:
            with self.lock:
                self.live.pop(short, None)

    def wait(self, short, timeout=10):
        thread = self.threads.get(short)
        if thread:
            thread.join(timeout)

    def state(self, short):
        with self.lock:
            if short in self.live:
                return dict(self.live[short])
        row = self.store.latest_upload(short)
        if not row:
            return {"state": "none"}
        out = {"state": row["status"], "title": row["title"], "message": row["message"] or "", "finished_at": row["finished_at"], "privacy": row["privacy"]}
        if row["video_id"]:
            out.update({"video_id": row["video_id"], "studio_url": yt.studio_url(row["video_id"]),
                        "watch_url": f"https://www.youtube.com/shorts/{row['video_id']}"})
        return out

    @staticmethod
    def _redirect(port):
        return f"http://127.0.0.1:{port}{CALLBACK_PATH}"
