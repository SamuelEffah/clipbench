#!/usr/bin/env python3
"""Place narration lines at their timestamps and write one audio track.

Manifest, one line per narration clip (blank lines and # comments are ignored):

    START | END | FILE | TEXT
    0:00  | 0:08 | narration/lines/01.mp3 | Ram just got her horn back.

END is the end of the gap the line has to fit in (leave it empty if there is none); TEXT is only a note.
Times are seconds or [h:]mm:ss on the Short's timeline.

usage: assemble_voice.py narration/ram_s04e18.lines -o narration/ram_s04e18_track.wav [--dur 2:44]
Then:  make_short.py ... --voice narration/ram_s04e18_track.wav
"""
import argparse
import subprocess
import sys
from pathlib import Path

from make_short import parse_time, probe_duration

SAMPLE_RATE = 44100


def parse_manifest(path):
    base = Path(path).parent
    lines = []
    for number, raw in enumerate(Path(path).read_text().splitlines(), 1):
        raw = raw.strip()
        if not raw or raw.startswith("#"):
            continue
        fields = [f.strip() for f in raw.split("|")]
        if len(fields) < 3:
            sys.exit(f"{path}:{number}: want 'START | END | FILE | TEXT', got: {raw}")
        try:
            start = parse_time(fields[0])
            end = parse_time(fields[1]) if fields[1] else None
        except argparse.ArgumentTypeError as err:
            sys.exit(f"{path}:{number}: {err}")
        audio = next((c for c in (Path(fields[2]), base / fields[2]) if c.is_file()), Path(fields[2]))
        lines.append({"number": number, "start": start, "end": end, "file": audio,
                      "text": fields[3] if len(fields) > 3 else ""})
    if not lines:
        sys.exit(f"{path}: no lines")
    return sorted(lines, key=lambda l: l["start"])


def check(lines):
    """Return (problems, finish_time). Missing files are fatal; overruns are warnings."""
    missing = [str(l["file"]) for l in lines if not l["file"].is_file()]
    if missing:
        sys.exit("audio not found:\n  " + "\n  ".join(missing))
    warnings = []
    for i, line in enumerate(lines):
        line["length"] = probe_duration(str(line["file"]))
        line["finish"] = line["start"] + line["length"]
        if line["end"] is not None and line["finish"] > line["end"] + 0.05:
            warnings.append(f"line {line['number']} runs {line['finish'] - line['end']:.1f}s past its gap "
                            f"({line['length']:.1f}s of audio, {line['end'] - line['start']:.1f}s of room)")
        if i + 1 < len(lines) and line["finish"] > lines[i + 1]["start"]:
            warnings.append(f"line {line['number']} overlaps line {lines[i + 1]['number']} by "
                            f"{line['finish'] - lines[i + 1]['start']:.1f}s")
    return warnings, max(l["finish"] for l in lines)


def build_track(lines, total, dest):
    cmd = ["ffmpeg", "-y", "-loglevel", "error"]
    parts = []
    for i, line in enumerate(lines):
        cmd += ["-i", str(line["file"])]
        ms = int(round(line["start"] * 1000))
        parts.append(f"[{i}:a:0]aresample={SAMPLE_RATE},aformat=channel_layouts=stereo,adelay={ms}|{ms}[l{i}]")
    mix = "".join(f"[l{i}]" for i in range(len(lines)))
    parts.append(f"{mix}amix=inputs={len(lines)}:normalize=0:duration=longest,apad=whole_dur={total:.3f},"
                 f"atrim=0:{total:.3f}[a]")
    cmd += ["-filter_complex", ";".join(parts), "-map", "[a]", "-c:a", "pcm_s16le", dest]
    subprocess.run(cmd, check=True)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("manifest")
    p.add_argument("-o", "--out")
    p.add_argument("--dur", type=parse_time, help="length of the track; defaults to the end of the last line")
    a = p.parse_args()

    lines = parse_manifest(a.manifest)
    warnings, finish = check(lines)
    total = a.dur or finish
    if finish > total:
        warnings.append(f"last line ends at {finish:.1f}s, past --dur {total:g}s, so it will be cut off")
    for w in warnings:
        print(f"warning: {w}", file=sys.stderr)

    out = a.out or str(Path(a.manifest).with_suffix(".wav"))
    Path(out).parent.mkdir(parents=True, exist_ok=True)
    build_track(lines, total, out)
    print(f"{out} ({len(lines)} lines, {total:g}s)")


if __name__ == "__main__":
    main()
