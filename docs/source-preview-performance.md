# Source preview performance

The source preview must finish before Clip Station can load media that the browser
cannot play directly. Source waveform extraction and scene detection now start
after the preview media metadata loads, so those scans do not compete with its
initial preparation. Cached previews and directly playable sources still skip
conversion.

Saved-clip warm-up now submits one conversion at a time. The existing two-slot
conversion limit remains in place, allowing foreground clip requests to use the
other slot. Duplicate warm-up requests share the active batch. Progress includes
clips that have not started yet.

The browser requests `/api/proxy/<id>?wait=1` while preparing a source. The server
waits up to one second, waking immediately on success or failure. This retains
periodic progress updates and removes the browser's extra one-second sleep after
completion. Ordinary status requests remain immediate.

## Encoder benchmark

Run `python3 scripts/benchmark_source_preview.py --seconds 12 --runs 3`.
The harness creates a temporary 720p/30fps H.264/AAC source and compares copying
streams with the production 540p software conversion and a hardware alternative.
It leaves source files and app caches untouched. Hardware errors are reported as
unavailable rather than preventing the other measurements.

Measured on the development Mac, using the median of three runs:

| Path | Preparation | Output bytes | Video SSIM |
| --- | ---: | ---: | ---: |
| Stream copy | 0.0703 s | 11,342,587 | 1.000000 |
| Existing software encoder | 0.6573 s | 1,386,785 | 0.989104 |
| VideoToolbox, speed prioritized | 0.8633 s | 4,662,405 | 0.997096 |

Hardware encoding was about 31% slower for this fixture and produced a larger,
higher-quality file. It is **not enabled** for source proxies: this measurement
does not support a preparation-speed improvement. VideoToolbox results depend on
the machine and workload; rerun the benchmark before changing the default.
This decision does not change the separate rendered-draft encoder.

Stream copy is already used only for compatible 8-bit 4:2:0 H.264 sources with
AAC, MP3, or no audio. It retains original resolution and keyframe spacing, so its
output can be larger and seeking can cost more than with the small encoded proxy.
Failed copies fall back to the existing software conversion. Other codecs still
need conversion; these fixture timings do not establish speedups for those files.
