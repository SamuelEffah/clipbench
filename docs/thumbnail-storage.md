# Clip thumbnail storage

Project and Saved-list saves can replace embedded JPEG, PNG, and WebP thumbnails
with `/clip-thumb/<sha256>.<format>` references. Image files live in
`data/clip-thumbs/`, or the equivalent directory under `CLIPBENCH_DATA`.
Identical images share one file, published atomically before a reference is saved.

Existing projects, Saved clips, rendered snapshots, and undo states containing
data URLs remain supported. Projects migrate when saved through the app; original
legacy JSON files are not rewritten. Existing thumbnail URLs remain unchanged.
Malformed or unsupported embedded images remain embedded. If image-file storage
is unavailable, the save falls back to the original embedded thumbnails.

The save response contains image references and their paths in the submitted
payload. The browser applies these to matching images in the current project
without changing captions, newer edits, or undo snapshots. It keeps a bounded
reference lookup for older undo states (256 entries and four MiB of encoded image
characters). No image upload is required again when the current project already
uses references.

Shared Saved clips retain their ownership when only thumbnail storage changes.
Deleting a project does not delete image files that other projects, saved clips,
or snapshots might still reference.

Back up the entire data directory, including `clip-thumbs/`, alongside the SQLite
database. A database-only copy does not include externally stored thumbnail bytes.
