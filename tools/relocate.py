"""Move an install laid out the old way, with clips/, shorts/, data/ and the rest beside the code, into workspace/.

Runs once and is safe to run again: folders already in place are left alone, a video's proxies, transcript and
suggestions are renamed to the id it has at its new place, and every stored path to a moved file is rewritten. The
database is copied aside before it is touched. Caches keyed by a clip range rather than a video are not carried over;
the bench makes them again when they are next needed.
"""
import hashlib
import shutil
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MEDIA = ("clips", "temp", "broll", "audio", "music")  # projects point at files in these by path
FOLDERS = MEDIA + ("projects", "shorts", "data", "cuts", "narration", "voices", "thumbs", "out")
LIBRARY = ("clips", "temp", "broll")  # where videos are listed from, so where ids come from
VIDEO_EXTS = {".mp4", ".mov", ".m4v", ".mkv", ".webm", ".avi"}
DB_NAME = "clipbench.db"
BACKUP_NAME = "clipbench.db.before-workspace"
PATH_COLUMNS = (("projects", "name", "data"), ("favorites", "id", "data"), ("video_owners", "rowid", "path"), ("extra_videos", "rowid", "path"))


def short_hash(text):
    return hashlib.sha1(text.encode()).hexdigest()[:12]


def relocate(root=ROOT, data_dirs=()):
    """Move the old folders under root/workspace and mend what pointed at them. Returns how much was moved, renamed and
    rewritten, all zero when there was nothing to do. `data_dirs` are extra data folders whose database points at the
    same media, such as one named by CLIPBENCH_DATA."""
    root, done = Path(root), {"moved": 0, "renamed": 0, "rewritten": 0}
    workspace = root / "workspace"
    for name in FOLDERS:
        done["moved"] += _move(root / name, workspace / name)
    done["moved"] += _move(root / "assets" / "channel", workspace / "channel")
    ids = _new_ids(root, workspace)
    for folder in (workspace / "clips" / ".proxy", workspace / "data" / "transcripts"):
        done["renamed"] += _rename_keyed(folder, ids)
    swaps = [(f"{root / name}/", f"{workspace / name}/") for name in MEDIA]
    databases = [workspace / "data" / DB_NAME] + [Path(d) / DB_NAME for d in data_dirs]
    for db_path in databases:
        if db_path.is_file():
            done["rewritten"] += _rewrite_db(db_path, swaps, ids)
    for snapshot in sorted((workspace / "data" / "rendered").glob("*.json")) if (workspace / "data" / "rendered").is_dir() else []:
        text = snapshot.read_text()
        if (new := _swap(text, swaps)) != text:
            snapshot.write_text(new)
            done["rewritten"] += 1
    return done


def _move(old, new):
    if not old.is_dir() or new.exists():
        return 0
    new.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(old), str(new))
    return 1


def _new_ids(root, workspace):
    """Old id to new id for every video now in the workspace library: the old id hashed its path beside the code, the
    new one hashes its place in the workspace."""
    ids = {}
    for name in LIBRARY:
        folder = workspace / name
        if not folder.is_dir():
            continue
        for p in sorted(folder.iterdir()):
            if p.is_file() and not p.name.startswith(".") and p.suffix.lower() in VIDEO_EXTS:
                ids[short_hash(str(root / name / p.name))] = short_hash(f"{name}/{p.name}")
    return ids


def _rename_keyed(folder, ids):
    if not folder.is_dir():
        return 0
    renamed = 0
    for f in sorted(folder.iterdir()):
        stem = f.name.split(".", 1)[0]
        target = folder / (ids[stem] + f.name[len(stem):]) if stem in ids else None
        if target and not target.exists():
            f.rename(target)
            renamed += 1
    return renamed


def _swap(text, swaps):
    for old, new in swaps:
        text = text.replace(old, new)
    return text


def _rewrite_db(path, swaps, ids):
    """Rewrite moved paths in the stored projects, favorites, owners and imports, and reviews to the videos' new ids.
    The database is copied aside the first time anything in it changes."""
    with sqlite3.connect(path) as db:
        rows, reviews = [], []
        try:
            for table, key, column in PATH_COLUMNS:
                for k, value in db.execute(f"SELECT {key}, {column} FROM {table}"):
                    if (new := _swap(value, swaps)) != value:
                        rows.append((table, key, column, k, new))
            reviews = [(ids[v], v) for (v,) in db.execute("SELECT DISTINCT video FROM suggestion_reviews") if v in ids]
        except sqlite3.OperationalError as err:
            print(f"relocate: {path}: {err}", file=sys.stderr)
            return 0
        if not rows and not reviews:
            return 0
        backup = path.with_name(BACKUP_NAME)
        if not backup.exists():
            shutil.copy2(path, backup)
        for table, key, column, k, new in rows:
            db.execute(f"UPDATE {table} SET {column} = ? WHERE {key} = ?", (new, k))
        for new, old in reviews:
            db.execute("UPDATE suggestion_reviews SET video = ? WHERE video = ?", (new, old))
    return len(rows) + len(reviews)


if __name__ == "__main__":
    result = relocate(ROOT, data_dirs=sys.argv[1:])
    print(f"workspace: {result['moved']} folders moved, {result['renamed']} cache files renamed, {result['rewritten']} records rewritten")
