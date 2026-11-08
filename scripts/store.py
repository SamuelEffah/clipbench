"""SQLite store for the clip bench: projects, saved clips, extra videos, settings and upload history.

One file on disk (data/clipbench.db, owner-only). Every call opens its own short connection, so the
threaded HTTP server and the upload threads never share one.
"""
import json
import sqlite3
import time
from contextlib import closing
from pathlib import Path
from thumbnails import favorite_identity

SCHEMA = """
CREATE TABLE IF NOT EXISTS projects (name TEXT PRIMARY KEY, data TEXT NOT NULL, updated_at REAL NOT NULL);
CREATE TABLE IF NOT EXISTS favorites (id INTEGER PRIMARY KEY AUTOINCREMENT, data TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS video_owners (path TEXT NOT NULL, project TEXT NOT NULL, PRIMARY KEY (path, project));
CREATE TABLE IF NOT EXISTS extra_videos (path TEXT PRIMARY KEY, added_at REAL NOT NULL);
CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS uploads (
    id INTEGER PRIMARY KEY AUTOINCREMENT, short TEXT NOT NULL, title TEXT NOT NULL, privacy TEXT NOT NULL,
    status TEXT NOT NULL, video_id TEXT, message TEXT, started_at REAL NOT NULL, finished_at REAL
);
CREATE INDEX IF NOT EXISTS uploads_short ON uploads (short, id);
CREATE TABLE IF NOT EXISTS video_stats (
    video_id TEXT PRIMARY KEY, views INTEGER NOT NULL, likes INTEGER, comments INTEGER, fetched_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS channel_videos (video_id TEXT PRIMARY KEY, title TEXT NOT NULL, published_at TEXT NOT NULL, seen_at REAL NOT NULL);
CREATE TABLE IF NOT EXISTS suggestion_reviews (
    video TEXT NOT NULL, clip_in REAL NOT NULL, clip_out REAL NOT NULL, decision TEXT NOT NULL, moment TEXT NOT NULL,
    decided_at REAL NOT NULL, PRIMARY KEY (video, clip_in, clip_out)
);
"""
IMPORTED_FLAG = "legacy_imported"


def used_paths(data):
    """The video paths a project's timeline and bank cut from."""
    return {c["src"] for key in ("clips", "bank") for c in (data.get(key) or []) if isinstance(c, dict) and isinstance(c.get("src"), str)}


class Store:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fresh = not self.path.exists()
        with self._db() as db:
            db.executescript(SCHEMA)
            if "project" not in {r["name"] for r in db.execute("PRAGMA table_info(favorites)")}:
                db.execute("ALTER TABLE favorites ADD COLUMN project TEXT")
            db.execute("CREATE INDEX IF NOT EXISTS favorites_project ON favorites (project, id)")
            have = {r["name"] for r in db.execute("PRAGMA table_info(video_stats)")}
            for column, kind in (("gone", "INTEGER NOT NULL DEFAULT 0"), ("avg_duration", "REAL"), ("avg_percent", "REAL"), ("retention", "TEXT"), ("analytics_at", "REAL")):
                if column not in have:
                    db.execute(f"ALTER TABLE video_stats ADD COLUMN {column} {kind}")
            db.execute(
                "UPDATE uploads SET status='error', message='The app stopped before the upload finished', finished_at=? "
                "WHERE status='uploading'", (time.time(),))
        if fresh:
            self.path.chmod(0o600)

    def _db(self):
        conn = sqlite3.connect(self.path, timeout=10)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        return _Session(conn)

    def list_projects(self):
        with self._db() as db:
            return [r["name"] for r in db.execute("SELECT name FROM projects ORDER BY name")]

    def home_project(self, preferred=None):
        """Only load the last opened project, or the most recently edited fallback."""
        with self._db() as db:
            row = db.execute("SELECT name,data,updated_at FROM projects WHERE name=?", (preferred,)).fetchone() if preferred else None
            if row is None:
                row = db.execute("SELECT name,data,updated_at FROM projects ORDER BY updated_at DESC,name LIMIT 1").fetchone()
        if row is None:
            return None
        data = json.loads(row["data"])
        clips = data.get("clips") or data.get("bank") or []
        thumb = next((c.get("thumb") for c in clips if isinstance(c, dict) and isinstance(c.get("thumb"), str) and c["thumb"].startswith("/clip-thumb/")), None)
        return {"name": row["name"], "updated_at": row["updated_at"], "thumb": thumb}

    def recent_projects(self, limit=3):
        """The most recently edited projects (all of them when limit is None), each with its thumbnail and clip count."""
        with self._db() as db:
            rows = db.execute("SELECT name,data,updated_at FROM projects ORDER BY updated_at DESC,name LIMIT ?", (-1 if limit is None else limit,)).fetchall()
        out = []
        for row in rows:
            data = json.loads(row["data"])
            clips = [c for c in (data.get("clips") or data.get("bank") or []) if isinstance(c, dict)]
            thumb = next((c["thumb"] for c in clips if isinstance(c.get("thumb"), str) and c["thumb"].startswith("/clip-thumb/")), None)
            src = next((c["src"] for c in clips if isinstance(c.get("src"), str)), None)
            out.append({"name": row["name"], "updated_at": row["updated_at"], "thumb": thumb, "clips": len(clips), "src": src})
        return out

    def iter_projects(self):
        """Project data in name order, streamed through one database connection."""
        with self._db() as db:
            for row in db.execute("SELECT data FROM projects ORDER BY name"):
                yield json.loads(row["data"])

    def get_project(self, name):
        with self._db() as db:
            row = db.execute("SELECT data FROM projects WHERE name=?", (name,)).fetchone()
        return json.loads(row["data"]) if row else None

    def put_project(self, name, data):
        with self._db() as db:
            db.execute("INSERT INTO projects (name, data, updated_at) VALUES (?, ?, ?) "
                       "ON CONFLICT(name) DO UPDATE SET data=excluded.data, updated_at=excluded.updated_at",
                       (name, json.dumps(data), time.time()))

    def create_project(self, name, data):
        """Create once without replacing another project's edits."""
        with self._db() as db:
            result = db.execute("INSERT OR IGNORE INTO projects (name,data,updated_at) VALUES (?,?,?)", (name, json.dumps(data), time.time()))
            return result.rowcount == 1

    def delete_project(self, name):
        """Forget a project: its edits, its Saved clips, and which videos it claimed. Files on disk are never touched."""
        with self._db() as db:
            db.execute("DELETE FROM projects WHERE name=?", (name,))
            db.execute("DELETE FROM favorites WHERE project=?", (name,))
            db.execute("DELETE FROM video_owners WHERE project=?", (name,))
            db.execute("DELETE FROM settings WHERE key=?", (f"own_media:{name}",))

    def mark_own_media(self, name):
        """A project made after videos had owners starts with only what it adds, not the shared library."""
        self.set_setting(f"own_media:{name}", True)

    def mark_existing_projects_own_media(self):
        """Once: every project that exists now keeps what it uses and owns, and stops inheriting the shared library."""
        if self.get_setting("own_media_migrated"):
            return 0
        names = self.list_projects()
        for name in names:
            self.mark_own_media(name)
        self.set_setting("own_media_migrated", True)
        return len(names)

    def own_media(self, name):
        return bool(self.get_setting(f"own_media:{name}"))

    def list_favorites(self, project=None):
        """Every Saved clip, or with a project, the ones it can see: its own and, unless it keeps its own media, the shared ones saved before projects owned theirs."""
        with self._db() as db:
            if project is None:
                rows = db.execute("SELECT data FROM favorites ORDER BY id")
            elif self.own_media(project):
                rows = db.execute("SELECT data FROM favorites WHERE project=? ORDER BY id", (project,))
            else:
                rows = db.execute("SELECT data FROM favorites WHERE project IS NULL OR project=? ORDER BY id", (project,))
            return [json.loads(r["data"]) for r in rows]

    def replace_favorites(self, items):
        with self._db() as db:
            db.execute("DELETE FROM favorites")
            db.executemany("INSERT INTO favorites (data) VALUES (?)", [(json.dumps(i),) for i in items])

    def replace_favorites_for(self, project, items):
        """Make this project's Saved list exactly items, leaving every other project's alone. A clip that was already
        shared stays shared; anything new belongs to the project."""
        with self._db() as db:
            visible = db.execute("SELECT id, data, project FROM favorites WHERE project IS NULL OR project=?", (project,)).fetchall()
            shared = {}
            for r in visible:
                identity = json.dumps(favorite_identity(json.loads(r["data"])))
                shared.setdefault(identity, []).append(r["project"])
            db.executemany("DELETE FROM favorites WHERE id=?", [(r["id"],) for r in visible])
            for item in items:
                data = json.dumps(item)
                identity = json.dumps(favorite_identity(item))
                owner = shared[identity].pop(0) if shared.get(identity) else project
                db.execute("INSERT INTO favorites (data, project) VALUES (?, ?)", (data, owner))

    def claim_video(self, path, project):
        with self._db() as db:
            db.execute("INSERT OR IGNORE INTO video_owners (path, project) VALUES (?, ?)", (str(path), project))

    def unclaim_video(self, path):
        with self._db() as db:
            db.execute("DELETE FROM video_owners WHERE path=?", (str(path),))

    def video_owners(self):
        """{path: {projects}} for every video a project has claimed. A video missing here belongs to nobody and is shared."""
        owners = {}
        with self._db() as db:
            for r in db.execute("SELECT path, project FROM video_owners"):
                owners.setdefault(r["path"], set()).add(r["project"])
        return owners

    def claim_used_videos(self, saved=None, name=None):
        """Give each video nobody owns to the projects whose clips or bank use it, so a project made later does not inherit it.

        Videos no project uses stay shared. With `saved` (the project data just written) and its `name`, the project also
        claims any video it uses that other projects own, as a draft or copy cut from its parent's download does; beyond
        that a save does nothing unless it uses a video nobody owns, so ordinary saves stay cheap. Returns how many
        videos were claimed.
        """
        owners = self.video_owners()
        borrowed = 0
        if saved is not None:
            used = set(used_paths(saved))
            lent = [p for p in used if name and p in owners and name not in owners[p]]
            for path in lent:
                self.claim_video(path, name)
            borrowed = len(lent)
            if all(p in owners for p in used):
                return borrowed
        users = {}
        with self._db() as db:
            for row in db.execute("SELECT name, data FROM projects").fetchall():
                for path in used_paths(json.loads(row["data"])):
                    if path not in owners:
                        users.setdefault(path, set()).add(row["name"])
            for path, names in users.items():
                for user in names:
                    db.execute("INSERT OR IGNORE INTO video_owners (path, project) VALUES (?, ?)", (path, user))
        return len(users) + borrowed

    def visible(self, path, project):
        owners = self.video_owners().get(str(path))
        return owners is None or project in owners

    def copy_assets(self, source, target):
        """Give target the videos and Saved clips that source has, so a copied project keeps working."""
        with self._db() as db:
            db.execute("INSERT OR IGNORE INTO video_owners (path, project) SELECT path, ? FROM video_owners WHERE project=?", (target, source))
            db.execute("INSERT INTO favorites (data, project) SELECT data, ? FROM favorites WHERE project=?", (target, source))

    def list_extra_videos(self):
        with self._db() as db:
            return [r["path"] for r in db.execute("SELECT path FROM extra_videos ORDER BY added_at, path")]

    def add_extra_video(self, path):
        with self._db() as db:
            db.execute("INSERT OR IGNORE INTO extra_videos (path, added_at) VALUES (?, ?)", (str(path), time.time()))

    def remove_extra_video(self, path):
        with self._db() as db:
            db.execute("DELETE FROM extra_videos WHERE path=?", (str(path),))

    def get_setting(self, key):
        with self._db() as db:
            row = db.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
        return json.loads(row["value"]) if row else None

    def set_setting(self, key, value):
        with self._db() as db:
            db.execute("INSERT INTO settings (key, value) VALUES (?, ?) "
                       "ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, json.dumps(value)))

    def delete_setting(self, key):
        with self._db() as db:
            db.execute("DELETE FROM settings WHERE key=?", (key,))

    def add_upload(self, short, title, privacy):
        with self._db() as db:
            cur = db.execute("INSERT INTO uploads (short, title, privacy, status, started_at) VALUES (?, ?, ?, 'uploading', ?)",
                             (short, title, privacy, time.time()))
            return cur.lastrowid

    def finish_upload(self, upload_id, video_id, privacy=None):
        """Record the upload done, with the privacy YouTube gave the video when that is known."""
        with self._db() as db:
            db.execute("UPDATE uploads SET status='done', video_id=?, finished_at=?, privacy=COALESCE(?, privacy) WHERE id=?",
                       (video_id, time.time(), privacy, upload_id))

    def fail_upload(self, upload_id, message):
        with self._db() as db:
            db.execute("UPDATE uploads SET status='error', message=?, finished_at=? WHERE id=?",
                       (str(message)[:500], time.time(), upload_id))

    def list_uploads(self, short):
        with self._db() as db:
            return [dict(r) for r in db.execute("SELECT * FROM uploads WHERE short=? ORDER BY id DESC", (short,))]

    def latest_upload(self, short):
        with self._db() as db:
            row = db.execute("SELECT * FROM uploads WHERE short=? ORDER BY id DESC LIMIT 1", (short,)).fetchone()
        return dict(row) if row else None

    def uploaded_video_ids(self):
        """The YouTube ids of every upload that finished, oldest first."""
        with self._db() as db:
            rows = db.execute("SELECT video_id FROM uploads WHERE status='done' AND video_id IS NOT NULL ORDER BY id").fetchall()
        return list(dict.fromkeys(r["video_id"] for r in rows))

    def save_channel_videos(self, videos, at):
        """Replace the list of the channel's videos ({video_id, title, published_at}) as seen at `at`."""
        with self._db() as db:
            db.execute("DELETE FROM channel_videos")
            db.executemany("INSERT OR REPLACE INTO channel_videos (video_id, title, published_at, seen_at) VALUES (?, ?, ?, ?)",
                           [(v["video_id"], v.get("title") or "", v.get("published_at") or "", at) for v in videos])

    def channel_videos(self):
        """The channel's videos as last listed, oldest first."""
        with self._db() as db:
            rows = db.execute("SELECT * FROM channel_videos ORDER BY published_at, video_id").fetchall()
        return [dict(r) for r in rows]

    def tracked_video_ids(self):
        """Every video whose figures are pulled: the app's finished uploads, then the rest of the channel, without doubles."""
        return list(dict.fromkeys(self.uploaded_video_ids() + [v["video_id"] for v in self.channel_videos()]))

    def save_video_stats(self, stats, at, asked=None):
        """Replace the counts of each video in `stats` ({video_id: {views, likes, comments}}) as read at `at`. A video in
        `asked` that YouTube did not list is marked gone, with its last counts kept, until a later read lists it again."""
        rows = [(vid, int(s.get("views") or 0), s.get("likes"), s.get("comments"), at, 0) for vid, s in stats.items()]
        gone = [(vid, 0, None, None, at, 1) for vid in (asked or []) if vid not in stats]
        with self._db() as db:
            db.executemany(
                "INSERT INTO video_stats (video_id, views, likes, comments, fetched_at, gone) VALUES (?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(video_id) DO UPDATE SET views=excluded.views, likes=excluded.likes, comments=excluded.comments, fetched_at=excluded.fetched_at, gone=excluded.gone",
                rows)
            db.executemany(
                "INSERT INTO video_stats (video_id, views, likes, comments, fetched_at, gone) VALUES (?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(video_id) DO UPDATE SET fetched_at=excluded.fetched_at, gone=1", gone)

    def save_video_analytics(self, analytics, at):
        """Keep how much of each video was watched ({video_id: {avg_duration, avg_percent, retention}}) as read at `at`."""
        with self._db() as db:
            db.executemany(
                "INSERT INTO video_stats (video_id, views, likes, comments, fetched_at, gone, avg_duration, avg_percent, retention, analytics_at) "
                "VALUES (?, 0, NULL, NULL, ?, 0, ?, ?, ?, ?) ON CONFLICT(video_id) DO UPDATE SET avg_duration=excluded.avg_duration, "
                "avg_percent=excluded.avg_percent, retention=excluded.retention, analytics_at=excluded.analytics_at",
                [(vid, at, a.get("avg_duration"), a.get("avg_percent"), json.dumps(a.get("retention") or []), at) for vid, a in analytics.items()])

    def video_stats(self):
        """The last counts and watch figures read for every video, keyed by YouTube id, with whether YouTube still lists it."""
        with self._db() as db:
            rows = db.execute("SELECT * FROM video_stats").fetchall()
        return {r["video_id"]: {"views": r["views"], "likes": r["likes"], "comments": r["comments"], "fetched_at": r["fetched_at"], "gone": bool(r["gone"]),
                                "avg_duration": r["avg_duration"], "avg_percent": r["avg_percent"],
                                "retention": json.loads(r["retention"]) if r["retention"] else None, "analytics_at": r["analytics_at"]} for r in rows}

    def review_suggestion(self, video, start, end, decision, moment):
        """What was decided about a suggested moment of a video: 'keep', 'skip', or None to forget the decision.
        `moment` is what the suggestion looked like at the time, kept so the ranking can learn from the decision later."""
        with self._db() as db:
            if decision is None:
                db.execute("DELETE FROM suggestion_reviews WHERE video=? AND clip_in=? AND clip_out=?", (video, start, end))
                return
            db.execute("INSERT INTO suggestion_reviews (video, clip_in, clip_out, decision, moment, decided_at) VALUES (?, ?, ?, ?, ?, ?) "
                       "ON CONFLICT(video, clip_in, clip_out) DO UPDATE SET decision=excluded.decision, moment=excluded.moment, decided_at=excluded.decided_at",
                       (video, start, end, decision, json.dumps(moment), time.time()))

    def suggestion_reviews(self, video=None):
        """The decisions on a video's suggested moments in time order, or on every video's when none is given."""
        where, args = ("WHERE video=?", (video,)) if video is not None else ("", ())
        with self._db() as db:
            rows = db.execute(f"SELECT * FROM suggestion_reviews {where} ORDER BY video, clip_in, clip_out", args).fetchall()
        return [{"video": r["video"], "in": r["clip_in"], "out": r["clip_out"], "decision": r["decision"], "moment": json.loads(r["moment"]), "decided_at": r["decided_at"]} for r in rows]

    def import_legacy(self, folder):
        """Copy the old projects/*.json files in once. Returns how many projects were imported."""
        if self.get_setting(IMPORTED_FLAG):
            return 0
        folder, count = Path(folder), 0
        for f in sorted(folder.glob("*.json")) if folder.is_dir() else []:
            if f.name.startswith("_"):
                continue
            try:
                data = json.loads(f.read_text())
            except (OSError, ValueError):
                continue
            if isinstance(data, dict) and self.get_project(f.stem) is None:
                self.put_project(f.stem, data)
                count += 1
        for name, apply in (("_favorites.json", self._import_favorites), ("_extra_videos.json", self._import_videos)):
            try:
                apply(json.loads((folder / name).read_text()))
            except (OSError, ValueError):
                pass
        self.set_setting(IMPORTED_FLAG, True)
        return count

    def _import_favorites(self, items):
        if isinstance(items, list) and not self.list_favorites():
            self.replace_favorites([i for i in items if isinstance(i, dict)])

    def _import_videos(self, paths):
        for p in paths if isinstance(paths, list) else []:
            if isinstance(p, str):
                self.add_extra_video(p)


class _Session:
    """Commit on success, roll back on error, always close."""

    def __init__(self, conn):
        self.conn = conn

    def __enter__(self):
        return self.conn

    def __exit__(self, exc_type, exc, tb):
        with closing(self.conn):
            if exc_type is None:
                self.conn.commit()
            else:
                self.conn.rollback()
        return False
