# Performance review checkpoint

Preserve current theme and behavior. Demonstrate meaningful unnecessary work before editing; validate and commit each completed optimization. Do not push, publish, start the app against user data, or touch unrelated `audio/` files. Use temporary fixtures. The heartbeat task is active; report completions, failures, or required input only. The user runs `/compact` manually.

## Completed work

Git history and regression tests hold implementation details; these measurements describe fixtures, not universal app speedups.

| Commit | Improvement and evidence |
| --- | --- |
| `38a94e3` | Streamer checks share sweeps and stop between channels when hidden or streaming. |
| `4120d49` | Sound searches retain one active request and the newest waiting query; stale results/errors are ignored. |
| `e0d913b` | Sound search rows: 101,000 creations across initial render plus 100 unchanged paints become 1,000. |
| `fd9e0b0` | Music panel: 100 unchanged refreshes of 2,000 tracks avoid 600,000 element creations. |
| `6c8b09f` | Local audio rows/groups persist through playback changes, preserving folding state. |
| `982afa7` | Audio metadata drops obsolete versions and uses a 1,024-entry LRU; concurrency/failure caching preserved. |
| `1308a78` | Transcript working set: 240 JSON reads become 12 over 20 scans of 12 sources; fixture 0.150s → 0.025s. Bounded by 128 entries and 16 MiB estimated parsed data; oversized entries bypass retention. |
| `03e4924` | Early subtitle range visits six of 30,000 cues rather than all; overlap/boundary behavior preserved. Late ranges still inspect preceding cues. |
| `31f3889` | Library scan resolves shared roots per scan: 105 B-roll root resolutions become two. Symlink retargeting and removal classification preserved. |
| `e56ecb6` | Hidden Shorts tab/dialog fixture: 121 requests become zero. Visibility return refreshes status; server uploads continue. |
| `2100d5d` | Muted montage fixture: 100 loudness scans become zero; encoder inputs fall from 200 to 100. Real FFmpeg silence/duration verified. |
| `74152e9` | Fully muted music/effects skip the final AAC encoding pass; completed video remains byte-identical. Audible volume ramps preserved. |
| `b9e19b3` | Secondary lanes cap encoded duration at the top lane's duration: real fixture 240 intermediate frames → 60. Original effect timing and short-lane holding preserved. |
| `e0c9c4e` | Timeline markers, names, and locks no longer invalidate preview videos: 25 encoder runs become one; visual/audio invalidation preserved. |
| `e0e7268` | Open Shorts dialog owns polling instead of running both tab and dialog timers; active tab polling resumes on close. |
| `5d4f1cd` | Scoped Saved queries use a project index: 120,064 SQLite VM steps become 148 with 20,000 unrelated rows; legacy migration/order preserved. |
| `0929513` | Unchanged quantized framing patches skip project copies, edits, and autosave resets: 600 redundant edits become zero. |
| `3f999d3` | Marquee selection reuses stable gesture geometry: 240,000 clip-bound reads become 2,000; scroll/layout/content/animation changes refresh bounds. |
| `0eef44f` | Suggestions share the scene scan they start instead of decoding the same source twice; completion/error notification and fallback retry covered. |
| `13b04b6` | Fully muted preview music/effects avoid loading/playing media; mute/unmute synchronization and audible ramps remain intact. |
| `39f61e7` | Stable multi-lane playback indexes timing once per edit: 216,120 duration calculations become 4,000 over 120 frames; direct lookups remain fresh. |

## Current change

Roll trimming changes only DOM block widths until release, but recomputed the entire clip-start list and skipped-lane set on every pointer move. A 2,000-clip, 120-move regression reproduces 121 timing preparations. The gesture now reuses its initial positions and skipped indices, reducing preparation to one pass.

Clip-list replacement, count changes, and edit-count changes invalidate the preparation. Playhead, markers, sounds, snap reach, and bypass behavior remain evaluated by the existing snapping path. The regression verifies invalidation and committed trim values; existing snapping regressions, Node syntax, and whitespace checks pass. Full suite: 727 tests passed in 61.055 seconds.

## Further review

- Secondary lane output is capped, but filter preparation and normalization still cover the full lane. Measure that remaining cost before changing graph construction or clip timing.
- Stable visible Shorts tab/dialog polling now has one owner. If further request coalescing is considered, measure overlapping in-flight requests and preserve explicit full refreshes that arrive during progress-only requests.
- `Store.visible()` currently appears only in tests; do not optimize that unused helper without an actual caller. Review remaining media preparation, background jobs, storage, and UI paths without forcing speculative micro-optimizations. Do not claim all app hotspots are exhausted.

Run `python3 -m unittest discover -s tests` for the full suite. Some standalone tests importing `scripts.clipper` require `PYTHONPATH=scripts`. Expected mocked FFmpeg failures and existing ResourceWarnings are not test failures. Commit only owned files; leave untracked `audio/` untouched.
