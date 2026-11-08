"""How the published Shorts are doing: views, likes and comments read from YouTube about once an hour.

The pull runs in the background when the Shorts list is opened and the last counts are older than an hour. A sign-in
from before the read permission was asked for can still upload, so a refused read never signs out; it is reported so
the person can connect again.
"""
import sys
import threading
import time
import traceback
from datetime import datetime, timedelta, timezone
from pathlib import Path

import youtube as yt

FRESH_FOR = 3600  # seconds the last counts are good for
ANALYTICS_FRESH_FOR = 86400  # watch figures run about two days behind, so once a day is plenty
CHANNEL_FRESH_FOR = 86400  # how often the channel's own videos are listed again
PULLED_AT_KEY = "video_stats_pulled_at"
ANALYTICS_AT_KEY = "video_analytics_pulled_at"
CHANNEL_AT_KEY = "channel_videos_listed_at"
BEST_DAY_KEY = "best_weekday"
BEST_DAY_WINDOW = 90  # days of views the busiest weekday is worked out from
BEST_HOUR = "around 5 pm"  # YouTube's reports have no hour of day; this is when Shorts audiences are usually on
WEEKDAYS = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")
ANALYTICS_START = "2020-01-01"  # before the channel's first upload; the report covers everything since
RECONNECT_MESSAGE = "Connect YouTube again to see views"


def best_weekday(rows):
    """The weekday the channel gets most of its views, from [{day: YYYY-MM-DD, views}]. None without usable days."""
    totals = [0.0] * 7
    for row in rows:
        try:
            totals[datetime.strptime(str(row.get("day")), "%Y-%m-%d").weekday()] += float(row.get("views") or 0)
        except (TypeError, ValueError):
            continue
    if not any(totals):
        return None
    return WEEKDAYS[max(range(7), key=lambda i: totals[i])]


def best_time_text(day):
    """"Saturday around 5 pm", or "" when the best day is not known yet."""
    return f"{day} {BEST_HOUR}" if day else ""


class VideoStats:
    def __init__(self, store, client_path, run=yt.curl_run, clock=time.time):
        self.store, self.client_path, self.run, self.clock = store, Path(client_path), run, clock
        self.lock = threading.Lock()
        self.thread = None
        self.message = ""
        self.refused = None  # the sign-in YouTube refused to read with, until a different one is saved

    def _old(self, key, fresh_for):
        pulled = self.store.get_setting(key)
        return pulled is None or self.clock() - pulled >= fresh_for

    def stale(self):
        tokens = self.store.get_setting(yt.TOKEN_KEY)
        return (self._old(PULLED_AT_KEY, FRESH_FOR) or self._old(CHANNEL_AT_KEY, CHANNEL_FRESH_FOR)
                or (yt.can_analyze(tokens) and self._old(ANALYTICS_AT_KEY, ANALYTICS_FRESH_FOR)))

    def _blocked(self, tokens):
        """Nothing can be read with this sign-in: it lacks the read permission or YouTube refused it."""
        return bool(tokens and tokens.get("refresh_token")) and (not yt.can_read(tokens) or tokens.get("refresh_token") == self.refused)

    def _needs_reconnect(self, tokens):
        return self._blocked(tokens) or (bool(tokens and tokens.get("refresh_token")) and not yt.can_analyze(tokens))

    def status(self):
        return {"pulled_at": self.store.get_setting(PULLED_AT_KEY), "message": self.message,
                "needs_reconnect": self._needs_reconnect(self.store.get_setting(yt.TOKEN_KEY))}

    def best_day(self):
        return self.store.get_setting(BEST_DAY_KEY)

    def refresh_soon(self):
        """Start a pull in the background when the counts are stale and none is running. True when one was started."""
        with self.lock:
            if (self.thread and self.thread.is_alive()) or not self.stale() or self._blocked(self.store.get_setting(yt.TOKEN_KEY)):
                return False
            self.thread = threading.Thread(target=self.refresh, daemon=True)
            self.thread.start()
            return True

    def wait(self, timeout=10):
        if self.thread:
            self.thread.join(timeout)

    def refresh(self):
        """Read the counts of every published video now, and once a day how much of each was watched. Failures are kept
        as a message, never raised."""
        problems = []
        if self._old(CHANNEL_AT_KEY, CHANNEL_FRESH_FOR):
            problems.append(self._guarded(self._pull_channel, CHANNEL_AT_KEY))
        problems.append(self._guarded(self._pull_counts, PULLED_AT_KEY))
        tokens = self.store.get_setting(yt.TOKEN_KEY)
        if yt.can_analyze(tokens) and self._old(ANALYTICS_AT_KEY, ANALYTICS_FRESH_FOR):
            problems.append(self._guarded(self._pull_analytics, ANALYTICS_AT_KEY))
        self.message = next((p for p in problems if p), "")

    def _guarded(self, pull, key):
        """Run one pull; note when it was done. Returns the message to show, or "" when it went well."""
        try:
            if pull():
                self.store.set_setting(key, self.clock())
            return ""
        except yt.YouTubeScopeError as err:
            if key == PULLED_AT_KEY:
                self.refused = (self.store.get_setting(yt.TOKEN_KEY) or {}).get("refresh_token")
            return str(err)
        except yt.YouTubeError as err:
            return str(err)
        except Exception as err:
            traceback.print_exc(file=sys.stderr)
            return f"Unexpected error: {err}"

    def _ready(self):
        """The sign-in and the video ids to ask about, or None when there is nothing to do."""
        tokens = self.store.get_setting(yt.TOKEN_KEY)
        if not tokens or not tokens.get("refresh_token"):
            return None
        ids = self.store.tracked_video_ids()
        return (tokens, ids) if ids else None

    def _pull_channel(self):
        """List the channel's own videos, so what was posted by hand is followed too. False without a sign-in."""
        tokens = self.store.get_setting(yt.TOKEN_KEY)
        if not tokens or not tokens.get("refresh_token"):
            return False
        if not yt.can_read(tokens):
            raise yt.YouTubeScopeError(RECONNECT_MESSAGE)
        self.store.save_channel_videos(yt.channel_videos(self._token(), self.run), self.clock())
        return True

    def _token(self):
        return yt.access_token(self.store, yt.load_client(self.client_path), self.run, self.clock())

    def _pull_counts(self):
        """Read and save the counts. False when there was no sign-in or nothing published, so the next look tries again."""
        ready = self._ready()
        if not ready:
            return False
        tokens, ids = ready
        if not yt.can_read(tokens):
            raise yt.YouTubeScopeError(RECONNECT_MESSAGE)
        token, now = self._token(), self.clock()
        for start in range(0, len(ids), yt.STATS_BATCH):
            batch = ids[start:start + yt.STATS_BATCH]
            self.store.save_video_stats(yt.video_statistics(token, batch, self.run), now, asked=batch)
        return True

    def _pull_analytics(self):
        """Read and save how much of each video was watched, with the retention curve of each one YouTube reports on."""
        ready = self._ready()
        if not ready:
            return False
        token, now = self._token(), self.clock()
        end = datetime.fromtimestamp(now, timezone.utc).strftime("%Y-%m-%d")
        ids = ready[1]
        for start in range(0, len(ids), yt.STATS_BATCH):
            watched = yt.video_retention(token, ids[start:start + yt.STATS_BATCH], self.run, ANALYTICS_START, end)
            curves = {vid: yt.retention_curve(token, vid, self.run, ANALYTICS_START, end) for vid in watched}
            self.store.save_video_analytics({vid: {**figures, "retention": curves[vid]} for vid, figures in watched.items()}, now)
        since = (datetime.fromtimestamp(now, timezone.utc) - timedelta(days=BEST_DAY_WINDOW)).strftime("%Y-%m-%d")
        day = best_weekday(yt.views_by_day(token, self.run, since, end))
        if day:
            self.store.set_setting(BEST_DAY_KEY, day)
        return True
