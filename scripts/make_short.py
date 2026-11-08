#!/usr/bin/env python3
"""Turn a landscape clip into a 1080x1920 Short.

Default: sharp clip centered over a blurred, zoomed copy of itself.
--card:  dark card with a hook line above the clip (--layout picks title, center, profile with avatar, or bare).

usage: make_short.py clips/in.mp4 --start 12 --dur 30 [--text "hook"] [--card] [--subs eng] [--cuts cuts/x.txt] [--voice voices/x.mp3] [--music music/x.mp3] [-o out/name.mp4]
"""
import argparse
from bisect import bisect_left, bisect_right
import json
import re
import math
import subprocess
import sys
import tempfile
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

import clip_cache
import ffmpeg_env
import tracking
from color_grade import GRADE_DEFAULTS, GRADE_RANGES, grade_filter

FONT_IMPACT = "/System/Library/Fonts/Supplemental/Impact.ttf"
FONT_BOLD = "/System/Library/Fonts/Supplemental/Arial Bold.ttf"
FONT_REGULAR = "/System/Library/Fonts/Supplemental/Arial.ttf"
FONT_EMOJI = "/System/Library/Fonts/Apple Color Emoji.ttc"
EMOJI_BITMAP = 160
EMOJI_RUN = re.compile("([\U0001F000-\U0001FAFF\u2600-\u27BF\u2B00-\u2BFF][\uFE0F\u200D\U0001F000-\U0001FAFF\u2600-\u27BF]*)")
MAX_DUR = 180
W, H = 1080, 1920
PAD = 36
AVATAR = 112
GAP = 28
# The Shorts grid on a channel page crops the frame to about 4:5, losing roughly 190px at the top and bottom of a 1080x1920 Short, so the hook starts below that.
TOP_MIN = 250
BOTTOM_SAFE = 340
CARD_BG = (15, 15, 16)
BLUR_BG_DIM = -0.08
# The backdrop is shrunk this far before it is blown back up, so it is a wash of colour and no shape in it can be made out.
BLUR_BG_SHRINK = 120
HANDLE_GREY = (150, 150, 155)
LAYOUTS = {
    "title": {"header": False, "hook_px": 76, "align": "left"},
    "center": {"header": False, "hook_px": 80, "align": "center"},
    "profile": {"header": True, "hook_px": 52, "align": "left"},
    "bare": {"header": False, "hook_px": 0, "align": "left"},
}
DEFAULT_LAYOUT = "title"
FORMATS = {"9:16": (1080, 1920), "4:5": (1080, 1350), "1:1": (1080, 1080), "16:9": (1920, 1080)}
DEFAULT_FORMAT = "9:16"
TEMPLATES = ("full", "fill", "fit", "split", "three", "four")
# Lanes fill the frame in reading order; "bottom" is the second lane, so a Split Short keeps working when it grows to three or four.
# full leaves each clip's own Fit or Fill alone; fill and fit set it for every clip. split is two rows, three is one row on top
# and two below, four is a grid.
LANES = ("top", "bottom", "third", "fourth")
LANE_COUNT = {"full": 1, "fill": 1, "fit": 1, "split": 2, "three": 3, "four": 4}
LANE_ROWS = {"split": [[0], [1]], "three": [[0], [1, 2]], "four": [[0, 1], [2, 3]]}
# Every format runs the clip edge to edge, leaving room only for a hook line above it. Captions sit on the clip,
# a set distance up from its bottom edge; 9:16 lifts them higher so they clear the platform's buttons.
HOOK_TOP = {"9:16": TOP_MIN}
DEFAULT_HOOK_TOP = 40
CAPTION_INSET = {"9:16": BOTTOM_SAFE + 20}
DEFAULT_CAPTION_INSET = 70


def probe_size(clip):
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=width,height",
         "-of", "csv=p=0:s=x", clip],
        check=True, capture_output=True, text=True,
    ).stdout.strip()
    w, h = out.split("x")
    return int(w), int(h)


def blur_filter(text):
    chain = (
        "[0:v]split=2[bg][fg];"
        "[bg]scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,boxblur=30:5,eq=brightness=-0.1[b];"
        "[fg]scale=1080:-2[f];"
        "[b][f]overlay=(W-w)/2:(H-h)/2"
    )
    if text:
        safe = text.replace("\\", "\\\\").replace(":", "\\:").replace("'", "’").replace("%", "\\%")
        chain += (
            f",drawtext=fontfile={FONT_IMPACT}:text='{safe}':fontsize=64:fontcolor=white:"
            "borderw=5:bordercolor=black:x=(w-text_w)/2:y=h*0.14"
        )
    return chain + "[v]"


WATERMARK_SIZE = 0.042
WATERMARK_ALPHA = 0.14
WATERMARK_Y = 0.88
WATERMARK_CORNER_SIZE = 0.016
WATERMARK_CORNER_ALPHA = 0.35


def watermark_filter(text, clip_width, corner=False, box=None):
    """drawtext that lays a faint mark across the clip, centred sideways and low in the picture, or small in its bottom right corner."""
    safe = text.replace("\\", "\\\\").replace(":", "\\:").replace("'", "\u2019").replace("%", "\\%")
    if corner:
        size = max(14, round(clip_width * WATERMARK_CORNER_SIZE))
        return (f",drawtext=fontfile={FONT_BOLD}:text='{safe}':fontsize={size}:fontcolor=white@{WATERMARK_CORNER_ALPHA}:"
                f"shadowcolor=black@0.25:shadowx=1:shadowy=1:x=w-text_w-w*0.015:y=h-text_h-h*0.03")
    size = max(16, round(clip_width * WATERMARK_SIZE))
    y = f"{box[0]}+{box[1]}*{WATERMARK_Y}-text_h/2" if box else f"h*{WATERMARK_Y}-text_h/2"
    return (f",drawtext=fontfile={FONT_BOLD}:text='{safe}':fontsize={size}:fontcolor=white@{WATERMARK_ALPHA}:"
            f"shadowcolor=black@0.1:shadowx=2:shadowy=2:x=(w-text_w)/2:y={y}")


def hook_runs(line):
    """A hook line as (text, is_emoji) runs, since the letter font has no emoji and they come from the emoji font."""
    return [(r, bool(EMOJI_RUN.fullmatch(r))) for r in EMOJI_RUN.split(line) if r]


def line_width(font, line):
    """How wide a line draws: an emoji is as wide as the text is tall."""
    return sum(font.size if emoji else font.getlength(run) for run, emoji in hook_runs(line))


def draw_hook_line(card, draw, x, y, line, font):
    """Draw a hook line on the card, pasting each emoji from the colour emoji font scaled to the text size."""
    for run, emoji in hook_runs(line):
        if not emoji:
            draw.text((x, y), run, font=font, fill="white")
            x += font.getlength(run)
            continue
        glyph = Image.new("RGBA", (EMOJI_BITMAP + 20, EMOJI_BITMAP + 20), (0, 0, 0, 0))
        ImageDraw.Draw(glyph).text((0, 0), run, font=ImageFont.truetype(FONT_EMOJI, EMOJI_BITMAP), embedded_color=True)
        box = glyph.getbbox()
        if box:
            glyph = glyph.crop(box)
            scale = font.size * 0.95 / glyph.height
            glyph = glyph.resize((max(1, round(glyph.width * scale)), max(1, round(glyph.height * scale))), Image.LANCZOS)
            card.paste(glyph, (round(x + (font.size - glyph.width) / 2), round(y + font.size * 0.12)), glyph)
        x += font.size


def wrap(text, font, max_width):
    lines, line = [], ""
    for word in text.split():
        trial = f"{line} {word}".strip()
        if line_width(font, trial) <= max_width or not line:
            line = trial
        else:
            lines.append(line)
            line = word
    if line:
        lines.append(line)
    return lines


def circular_avatar(path, size):
    img = Image.open(path).convert("RGBA").resize((size, size), Image.LANCZOS)
    mask = Image.new("L", (size, size), 0)
    ImageDraw.Draw(mask).ellipse((0, 0, size - 1, size - 1), fill=255)
    img.putalpha(mask)
    return img


def card_geometry(canvas, hook, layout, fmt, clip_size=None):
    """Where the hook and clip sit on the card. Without clip_size the clip area takes all the room left."""
    spec = LAYOUTS[layout]
    hook_px = spec["hook_px"]
    width, height = canvas
    font_hook = ImageFont.truetype(FONT_BOLD, hook_px or 52)
    lines = wrap(hook, font_hook, width - 2 * PAD) if hook and hook_px else []
    line_h = int(hook_px * 1.25)
    top_min = HOOK_TOP.get(fmt, DEFAULT_HOOK_TOP) if lines or spec["header"] else 0
    bottom_safe = 0
    header_h = AVATAR + GAP if spec["header"] else 0
    text_block = len(lines) * line_h + GAP if lines else 0
    max_h = height - bottom_safe - top_min - header_h - text_block
    max_w = width
    if clip_size is None:
        clip_w, clip_h = max_w // 2 * 2, max_h // 2 * 2
    else:
        scale = min(max_w / clip_size[0], max_h / clip_size[1])
        clip_w, clip_h = int(clip_size[0] * scale) // 2 * 2, int(clip_size[1] * scale) // 2 * 2
    top = max(top_min, (height - bottom_safe - (header_h + text_block + clip_h)) // 2)
    return {"spec": spec, "font": font_hook, "lines": lines, "line_h": line_h, "header_h": header_h,
            "text_block": text_block, "clip_w": clip_w, "clip_h": clip_h, "top": top, "width": width, "height": height}


def render_card(geo, name, handle, avatar_path, dest, clear=False):
    """Draw the card background from card_geometry and return (clip_w, clip_h, clip_x, clip_y)."""
    spec, top, width = geo["spec"], geo["top"], geo["width"]
    card = Image.new("RGBA", (width, geo["height"]), (0, 0, 0, 0)) if clear else Image.new("RGB", (width, geo["height"]), CARD_BG)
    draw = ImageDraw.Draw(card)
    if spec["header"]:
        font_name = ImageFont.truetype(FONT_BOLD, 44)
        font_handle = ImageFont.truetype(FONT_REGULAR, 34)
        avatar = circular_avatar(avatar_path, AVATAR)
        card.paste(avatar, (PAD, top), avatar)
        text_x = PAD + AVATAR + 24
        draw.text((text_x, top + 8), name, font=font_name, fill="white")
        draw.text((text_x, top + 62), handle, font=font_handle, fill=HANDLE_GREY)
    y = top + geo["header_h"]
    for line in geo["lines"]:
        x = (width - line_width(geo["font"], line)) / 2 if spec["align"] == "center" else PAD
        draw_hook_line(card, draw, x, y, line, geo["font"])
        y += geo["line_h"]
    if clear:
        halo = card.getchannel("A").filter(ImageFilter.GaussianBlur(12)).point(lambda v: min(255, v * 2))
        card = Image.alpha_composite(Image.merge("RGBA", (*Image.new("RGB", card.size, (0, 0, 0)).split(), halo)), card)
    card.save(dest)
    return geo["clip_w"], geo["clip_h"], (width - geo["clip_w"]) // 2, top + geo["header_h"] + geo["text_block"]


def parse_time(value):
    """Seconds from '872', '14:20', '1:14:20' or '14:20.5'."""
    try:
        parts = [float(x) for x in str(value).split(":")]
    except ValueError:
        raise argparse.ArgumentTypeError(f"bad time: {value}")
    if not 1 <= len(parts) <= 3 or any(x < 0 for x in parts):
        raise argparse.ArgumentTypeError(f"bad time: {value}")
    seconds = 0.0
    for x in parts:
        seconds = seconds * 60 + x
    return seconds


SUB_FONT_SIZE = 50
CAPTION_SIZES = (24, 160)
SUB_GAP = 44
MIN_CUE_SECONDS = 0.35


def find_subtitle_ordinal(clip, language):
    """Position among the subtitle streams of the first track tagged with this language."""
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "s", "-show_entries", "stream_tags=language",
         "-of", "csv=p=0", clip],
        check=True, capture_output=True, text=True,
    ).stdout.split()
    for ordinal, lang in enumerate(out):
        if lang == language:
            return ordinal
    sys.exit(f"no {language} subtitle track in {clip}")


def load_cues(spec, clip, tmp):
    """Cues as (start, end, text). spec is a subtitle file, or a language code like 'eng' for the video's own track."""
    if Path(spec).is_file():
        src = spec
    else:
        src = str(Path(tmp) / "subs.srt")
        ordinal = find_subtitle_ordinal(clip, spec)
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", clip, "-map", f"0:s:{ordinal}",
                        "-c:s", "srt", src], check=True)
    else_path = Path(src)
    if else_path.suffix.lower() != ".srt":
        converted = str(Path(tmp) / "converted.srt")
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", src, converted], check=True)
        src = converted
    cues = []
    for block in Path(src).read_text(encoding="utf-8-sig").replace("\r", "").strip().split("\n\n"):
        lines = block.splitlines()
        timing = next((n for n, line in enumerate(lines[:2]) if "-->" in line), None)
        if timing is None:
            continue
        a, b = (srt_seconds(x.split()[0]) for x in lines[timing].split("-->"))
        text = re.sub(r"<[^>]+>|\{[^}]*\}", "", " ".join(lines[timing + 1:])).strip()
        if text:
            cues.append((a, b, text))
    return cues


def srt_seconds(value):
    h, m, rest = value.split(":")
    return int(h) * 3600 + int(m) * 60 + float(rest.replace(",", "."))


def remap_cues(cues, ranges, overlaps=None):
    """Move cues onto the joined timeline; a cue is clipped to each range it overlaps. overlaps holds the seconds
    each range's transition overlaps the one before it."""
    out, offset = [], 0.0
    starts, ends = [c[0] for c in cues], [c[1] for c in cues]
    ordered = all(math.isfinite(a) and math.isfinite(b) and a <= b
                  and (i == 0 or starts[i - 1] <= a and ends[i - 1] <= b)
                  for i, (a, b) in enumerate(zip(starts, ends)))
    for (start, end), overlap in zip(ranges, overlaps or [0.0] * len(ranges)):
        offset -= overlap
        relevant = cues
        if ordered and math.isfinite(start) and math.isfinite(end):
            relevant = cues[bisect_right(ends, start):bisect_left(starts, end)]
        for a, b, text in relevant:
            lo, hi = max(a, start), min(b, end)
            if hi - lo >= MIN_CUE_SECONDS:
                out.append((lo - start + offset, hi - start + offset, text))
        offset += end - start
    return sorted(out)


def ass_time(t):
    cs = int(round(t * 100))
    return f"{cs // 360000}:{cs // 6000 % 60:02d}:{cs // 100 % 60:02d}.{cs % 100:02d}"


def caption_home(canvas, fmt, clip_bottom):
    """Where a caption sits when it hasn't been moved: centred, with its bottom edge a little above the clip's own."""
    inset = CAPTION_INSET.get(fmt, DEFAULT_CAPTION_INSET)
    return (0.5, max(0, clip_bottom - inset) / canvas[1], 2)


# How a caption can look. size scales the base text size, outline is the border as a fraction of the text size (the padding
# of the box for border 3), upper shows the text in capitals, and fill and edge are the RRGGBB of the letters and of their
# outline (or box). Keep the names and numbers in step with captions.js.
LOOKS = {
    "classic": {"font": "Arial", "bold": -1, "border": 1, "outline": 0.06, "shadow": 0, "size": 1.0, "upper": False, "fill": "FFFFFF", "edge": "000000"},
    "impact": {"font": "Impact", "bold": 0, "border": 1, "outline": 0.08, "shadow": 0, "size": 1.15, "upper": True, "fill": "FFFFFF", "edge": "000000"},
    "box": {"font": "Arial", "bold": -1, "border": 3, "outline": 0.2, "shadow": 0, "size": 0.9, "upper": False, "fill": "FFFFFF", "edge": "000000"},
    "clean": {"font": "Arial", "bold": -1, "border": 1, "outline": 0.03, "shadow": 3, "size": 1.0, "upper": False, "fill": "FFFFFF", "edge": "000000"},
    "pop": {"font": "Arial Black", "bold": 0, "border": 1, "outline": 0.065, "shadow": 0, "size": 1.5, "upper": True, "fill": "FFFFFF", "edge": "000000"},
    "marker": {"font": "Arial", "bold": -1, "border": 3, "outline": 0.2, "shadow": 0, "size": 0.9, "upper": False, "fill": "111111", "edge": "FFD84A"},
    "stamp": {"font": "Impact", "bold": 0, "border": 3, "outline": 0.18, "shadow": 0, "size": 1.05, "upper": True, "fill": "FFFFFF", "edge": "E5322D"},
    "neon": {"font": "Arial Rounded MT Bold", "bold": 0, "border": 1, "outline": 0.09, "shadow": 3, "size": 1.0, "upper": False, "fill": "7DF9FF", "edge": "10206B"},
    "bubble": {"font": "Arial Rounded MT Bold", "bold": 0, "border": 1, "outline": 0.15, "shadow": 0, "size": 1.0, "upper": False, "fill": "FFFFFF", "edge": "6A35E0"},
    "cinema": {"font": "Georgia", "bold": 0, "border": 1, "outline": 0.03, "shadow": 2, "size": 0.85, "upper": False, "fill": "FFFFFF", "edge": "000000"},
}
DEFAULT_LOOK = "classic"
DEFAULT_HIGHLIGHT = "FFD84A"
HEX_COLOUR = re.compile(r"^[0-9a-fA-F]{6}$")
POP_SCALE = 106
POP_MS = 70
POP_SETTLE_MS = 170


def ass_colour(rgb):
    """RRGGBB as the &HBBGGRR& an ASS override wants."""
    return ("&H%s%s%s&" % (rgb[4:6], rgb[2:4], rgb[0:2])).upper()


def ass_place(rest, canvas, size=None):
    """Override that pins a cue to a point given as fractions of the frame, centred on it unless the point names
    another anchor (2 is bottom centre), then sizes and turns it; nothing when the cue has no point."""
    if not rest or rest[0] is None:
        return ""
    x, y, *anchor = rest[0]
    tags = "\\an%d\\pos(%d,%d)" % (anchor[0] if anchor else 5, round(x * canvas[0]), round(y * canvas[1]))
    scale = rest[1] if len(rest) > 1 else 1.0
    look = LOOKS[rest[3] if len(rest) > 3 and rest[3] else DEFAULT_LOOK]
    if scale != 1.0:
        px = round((size or SUB_FONT_SIZE) * look["size"] * scale)
        tags += "\\fs%d\\bord%d" % (px, max(3, round(px * look["outline"])))
    if len(rest) > 2 and rest[2]:
        tags += "\\frz%g" % -rest[2]
    return "{%s}" % tags


def ass_text(text, highlight=DEFAULT_HIGHLIGHT, upper=False, fill="FFFFFF"):
    """Cue text as ASS: plain text is stripped of override characters; (words, lit index) lights that word and pops it."""
    clean = lambda t: (t.upper() if upper else t).replace(chr(92), "").replace("{", "").replace("}", "")
    if isinstance(text, str):
        return clean(text)
    words, lit = text
    colour = ass_colour(highlight)
    pop = "{\\1c%s\\t(0,%d,\\fscx%d\\fscy%d)\\t(%d,%d,\\fscx100\\fscy100)}%s{\\1c%s\\fscx100\\fscy100}"
    return " ".join((pop % (colour, POP_MS, POP_SCALE, POP_SCALE, POP_MS, POP_SETTLE_MS, clean(w), ass_colour(fill))) if i == lit else clean(w) for i, w in enumerate(words))


def ass_styles(size, top):
    rows = []
    for name, look in LOOKS.items():
        px = round(size * look["size"])
        edge = "&H00" + ass_colour(look["edge"])[2:-1]
        back = edge if look["border"] == 3 else "&H00000000"
        fill = "&H00" + ass_colour(look["fill"])[2:-1]
        rows.append("Style: %s,%s,%d,%s,%s,%s,%d,0,%d,%d,%d,8,%d,%d,%d,1"
                    % (name, look["font"], px, fill, edge, back, look["bold"], look["border"], max(3, round(px * look["outline"])), look["shadow"], PAD, PAD, top))
    return rows


def write_ass(cues, top, dest, canvas=(W, H), size=None):
    size = size or SUB_FONT_SIZE
    header = (
        "[Script Info]\nScriptType: v4.00+\nPlayResX: %d\nPlayResY: %d\nWrapStyle: 0\n\n"
        "[V4+ Styles]\nFormat: Name,Fontname,Fontsize,PrimaryColour,OutlineColour,BackColour,Bold,Italic,"
        "BorderStyle,Outline,Shadow,Alignment,MarginL,MarginR,MarginV,Encoding\n"
        + "\n".join(ass_styles(size, top)) +
        "\n\n[Events]\nFormat: Layer,Start,End,Style,Name,MarginL,MarginR,MarginV,Effect,Text\n"
    ) % (canvas[0], canvas[1])
    lines = []
    for a, b, text, *rest in cues:
        name = rest[3] if len(rest) > 3 and rest[3] else DEFAULT_LOOK
        highlight = rest[4] if len(rest) > 4 and rest[4] else DEFAULT_HIGHLIGHT
        lines.append(f"Dialogue: 0,{ass_time(a)},{ass_time(b)},{name},,0,0,0,,{ass_place(rest, canvas, size)}"
                     f"{ass_text(text, highlight, LOOKS[name]['upper'], LOOKS[name]['fill'])}")
    Path(dest).write_text(header + "\n".join(lines) + "\n", encoding="utf-8")


def filter_path(path):
    return str(path).replace("\\", "\\\\").replace(":", "\\:").replace("'", "\\'")


DEFAULT_OPTIONS = {"caption": "", "capmode": "text", "words": None, "caplook": None, "caphi": None, "volume": 1.0, "speed": 1.0, "fit": "fit", "pan": 0.5, "effect": "none", "brightness": 1.0, "contrast": 1.0, "saturation": 1.0,
                   "ramp": "none", "freeze": 0.0, "zoom": 1.0, "zx": 0.5, "zy": 0.5, "track": None, "voice": None, "lane": "top",
                   "capx": None, "capy": None, "capscale": None, "caprot": None, "fadein": 0.0, "fadeout": 0.0, "transition": "none", "tlen": 0.3}
OPTION_RANGES = {"brightness": (0.0, 2.0), "contrast": (0.0, 2.0), "saturation": (0.0, 2.0), "volume": (0.0, 3.0), "speed": (0.25, 4.0), "pan": (0.0, 1.0), "freeze": (0.0, 3.0),
                 "zoom": (0.25, 4.0), "zx": (0.0, 1.0), "zy": (0.0, 1.0), "capx": (0.0, 1.0), "capy": (0.0, 1.0), "capscale": (0.3, 3.0), "caprot": (-180.0, 180.0),
                 "fadein": (0.0, 3.0), "fadeout": (0.0, 3.0), "tlen": (0.1, 1.5)}
DEFAULT_OPTIONS.update(GRADE_DEFAULTS)
OPTION_RANGES.update(GRADE_RANGES)
# Transitions that suit Shorts: quick and punchy, each mapped to the ffmpeg xfade it renders with.
# A transition sits on the seam before its clip. Keep in step with TRANSITIONS in clipper_ui/app.js.
TRANSITIONS = {"none": None, "flash": "fadewhite", "dip": "fadeblack", "swipe_left": "slideleft", "swipe_up": "slideup",
               "zoom": "zoomin", "whip": "hblur", "pixelize": "pixelize", "iris": "circleopen",
               "streak": "hlwind", "clock": "radial", "glitch": "custom",
               "zoom_in": "custom", "zoom_punch": "custom", "zoom_out": "custom"}
def zoom_away(shrink, settle):
    """xfade expression for a zoom out: the outgoing picture shrinks away toward the centre as it fades, showing the
    incoming one behind it, which starts zoomed in and settles to its normal size. Outside the shrinking picture
    only the incoming one shows. P counts down from 1 to 0."""
    sa = f"(1+{shrink}*(1-P))"
    sb = f"(1+{settle}*P)"
    xa, ya = f"(W/2+(X-W/2)*{sa})", f"(H/2+(Y-H/2)*{sa})"
    xb, yb = f"clip(W/2+(X-W/2)/{sb},0,W-1)", f"clip(H/2+(Y-H/2)/{sb},0,H-1)"

    def pixel(letter, x, y):
        cx, cy = f"clip({x},0,W-1)", f"clip({y},0,H-1)"
        return f"if(eq(PLANE,0),{letter}0({cx},{cy}),if(eq(PLANE,1),{letter}1({cx},{cy}),{letter}2({cx},{cy})))"
    weight = f"(P*between({xa},0,W-1)*between({ya},0,H-1))"
    return f"{weight}*{pixel('a', xa, ya)}+(1-{weight})*{pixel('b', xb, yb)}"


# The glitch transition flips random blocks of the picture from one clip to the next as it progresses,
# reshuffling the blocks nine times along the way so it flickers. xfade counts P down from 1 to 0, so A shows while P is high.
def zoom_through(strength, curve="P"):
    """xfade expression for a zoom that pushes through the cut: the outgoing picture grows toward the centre while it
    fades out, and the incoming picture settles from that same zoom down to its normal size. Each picture is sampled
    at its own zoomed coordinates, plane by plane. curve shapes the zoom over P, which counts down from 1 to 0."""
    grow = f"(1+{strength}*(1-({curve})))"
    settle = f"(1+{strength}*({curve}))"

    def pixel(letter, scale):
        x, y = f"clip(W/2+(X-W/2)/{scale},0,W-1)", f"clip(H/2+(Y-H/2)/{scale},0,H-1)"
        return f"if(eq(PLANE,0),{letter}0({x},{y}),if(eq(PLANE,1),{letter}1({x},{y}),{letter}2({x},{y})))"
    return f"P*{pixel('a', grow)}+(1-P)*{pixel('b', settle)}"


# The glitch transition flips random blocks of the picture from one clip to the next as it progresses,
# reshuffling the blocks nine times along the way so it flickers. xfade counts P down from 1 to 0, so A shows while P is high.
TRANSITION_EXPR = {"glitch": "if(gt(P,mod(abs(sin((floor(24*Y/H)+floor(8*X/W)*37+floor(P*9)*101)*12.9898)*43758.5453),1)),A,B)",
                   "zoom_in": zoom_through(0.6),
                   "zoom_punch": zoom_through(1.4, "P*P*P"),
                   "zoom_out": zoom_away(0.5, 0.25)}
# Speed ramps: (start, end, relative speed) over the clip's source time, as fractions 0 to 1.
# Keep in step with RAMPS in clipper_ui/app.js.
RAMPS = {
    "none": [(0.0, 1.0, 1.0)],
    "hero": [(0.0, 0.3, 1.0), (0.3, 0.4, 0.7), (0.4, 0.6, 0.35), (0.6, 0.7, 0.7), (0.7, 1.0, 1.0)],
    "slowdown": [(0.0, 0.4, 1.6), (0.4, 0.6, 1.1), (0.6, 0.8, 0.6), (0.8, 1.0, 0.35)],
    "speedup": [(0.0, 0.2, 0.35), (0.2, 0.4, 0.6), (0.4, 0.6, 1.1), (0.6, 1.0, 1.6)],
}
FITS = ("fit", "fill")
EFFECTS = ("none", "zoom_in", "zoom_out", "punch", "shake", "flash", "bw", "vignette", "glitch")
FRAMES = {"wide": (1920, 1080), "square": (1080, 1080), "tall": (1080, 1350)}
TARGET_LUFS = -16.0
MAX_GAIN_DB = 12.0
SILENT_LUFS = -60.0


def names_file(spec):
    """Whether spec is a path to a file; inline text too long to be a path is not one."""
    try:
        return Path(spec).is_file()
    except OSError:
        return False


def read_cuts(spec):
    """Cut list from a file path or inline text: lines or commas of 'start - end' (e.g. '14:20 - 14:34').

    A line may name its own source as 'path/to/video.mp4 | start - end'; those lines are joined in order
    with the others. Lines '@caption some words', '@volume 0.5', '@speed 1.5', '@fit fill' and '@pan 0.3'
    and '@effect zoom_in' apply to the next cut line. Returns (start, end, source, options) where source is None for the default
    clip and options holds caption, volume (1 = unchanged), speed (1 = unchanged), fit ('fit' keeps the
    whole picture, 'fill' crops to the frame) and pan (0 to 1, where a filled clip is cropped).
    """
    text = Path(spec).read_text() if names_file(spec) else spec
    cuts = []
    entries = []
    pending = {}
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            continue
        if stripped.startswith("@"):
            tag, _, value = stripped[1:].partition(" ")
            pending = {**pending, **parse_option(tag, value.strip())}
            continue
        parts = [line] if " | " in line else line.split(",")
        for i, part in enumerate(parts):
            entries.append((part, {**DEFAULT_OPTIONS, **pending} if i == 0 else dict(DEFAULT_OPTIONS)))
        if any(part.strip() for part in parts):
            pending = {}
    for raw, options in entries:
        raw = raw.strip()
        if not raw:
            continue
        source = None
        if " | " in raw:
            source, _, raw = raw.rpartition(" | ")
            source = source.strip()
            if not Path(source).is_file():
                sys.exit(f"cut source not found: {source}")
        if raw.count("-") != 1:
            sys.exit(f"bad cut (want 'start - end'): {raw}")
        start, end = (parse_time(x.strip()) for x in raw.split("-"))
        if end <= start:
            sys.exit(f"cut ends before it starts: {raw}")
        cuts.append((start, end, source, options))
    if not cuts:
        sys.exit("no cuts found")
    return cuts


CAPMODES = ("text", "phrase", "word")
MAX_WORDS = 400


def parse_words(value):
    """Spoken words as [text, start, end] in seconds from the clip's start, checked and rounded."""
    try:
        raw = json.loads(value)
    except ValueError:
        sys.exit("@words wants a JSON list of [text, start, end]")
    if not isinstance(raw, list) or len(raw) > MAX_WORDS:
        sys.exit(f"@words wants a list of at most {MAX_WORDS} words")
    words = []
    for item in raw:
        try:
            text, a, b = str(item[0]).strip(), float(item[1]), float(item[2])
        except (TypeError, ValueError, IndexError):
            sys.exit("@words wants entries of [text, start, end]")
        if not text or len(text) > 40 or not 0 <= a < b:
            sys.exit(f"@words has a bad entry: {item}")
        words.append((text, round(a, 3), round(b, 3)))
    return words


def parse_option(tag, value):
    if tag == "caption":
        return {"caption": value}
    if tag == "capmode":
        if value not in CAPMODES:
            sys.exit(f"@capmode must be one of {', '.join(CAPMODES)}, got '{value}'")
        return {"capmode": value}
    if tag == "words":
        return {"words": parse_words(value)}
    if tag == "caplook":
        if value not in LOOKS:
            sys.exit(f"@caplook must be one of {', '.join(LOOKS)}, got '{value}'")
        return {"caplook": value}
    if tag == "caphi":
        if not HEX_COLOUR.match(value):
            sys.exit(f"@caphi wants a colour like FFD84A, got '{value}'")
        return {"caphi": value.upper()}
    if tag == "fit":
        if value not in FITS:
            sys.exit(f"@fit must be one of {', '.join(FITS)}, got '{value}'")
        return {"fit": value}
    if tag == "lane":
        if value not in LANES:
            sys.exit(f"@lane must be one of {', '.join(LANES)}, got '{value}'")
        return {"lane": value}
    if tag == "track":
        try:
            return {"track": tracking.parse_track(value) or None}
        except ValueError as err:
            sys.exit(f"@track: {err}")
    if tag == "voice":
        if not Path(value).is_file():
            sys.exit(f"@voice wants the voice file, which isn't there: {value}")
        return {"voice": value}
    if tag == "ramp":
        if value not in RAMPS:
            sys.exit(f"@ramp must be one of {', '.join(RAMPS)}, got '{value}'")
        return {"ramp": value}
    if tag == "transition":
        if value not in TRANSITIONS:
            sys.exit(f"@transition must be one of {', '.join(TRANSITIONS)}, got '{value}'")
        return {"transition": value}
    if tag == "effect":
        if value not in EFFECTS:
            sys.exit(f"@effect must be one of {', '.join(EFFECTS)}, got '{value}'")
        return {"effect": value}
    if tag not in OPTION_RANGES:
        sys.exit(f"unknown cut option '@{tag}' (want @caption, @capmode, @words, @caplook, @caphi, @volume, @speed, @fit, @pan, @zoom, @zx, @zy, @track, @voice, @capx, @capy, @capscale, @caprot, @fadein, @fadeout, @transition, @tlen, @effect, @ramp, @freeze or @lane)")
    try:
        number = float(value)
    except ValueError:
        sys.exit(f"@{tag} wants a number, got '{value}'")
    low, high = OPTION_RANGES[tag]
    if not low <= number <= high:
        sys.exit(f"@{tag} must be between {low:g} and {high:g}, got {number:g}")
    return {tag: number}


def fill_filter(width, height, options):
    """Scale a clip to cover the frame and crop it. A zoom below 1 shows more of the picture, shrinking
    the cover scale until black margins appear around it, placed by zx and zy."""
    pan, zoom = options["pan"], options["zoom"]
    if zoom >= 1.0:
        return (f",scale={width}:{height}:force_original_aspect_ratio=increase,"
                f"crop={width}:{height}:(iw-ow)*{pan:.3f}:(ih-oh)*{pan:.3f},setsar=1")
    cover = f"max({width}/iw,{height}/ih)*{zoom:.4f}"
    return (f",scale='trunc(iw*{cover}/2)*2':'trunc(ih*{cover}/2)*2',"
            f"pad='max(iw,{width})':'max(ih,{height})':'(ow-iw)*{options['zx']:.3f}':'(oh-ih)*{options['zy']:.3f}':color=black,"
            f"crop={width}:{height}:(iw-ow)*{pan:.3f}:(ih-oh)*{pan:.3f},setsar=1")


def zoom_filter(width, height, options, track=None):
    """Zoom the framed picture by the clip's zoom, around the point (zx, zy). Above 1 it crops in and scales back
    to the frame; below 1 it shrinks the picture and pads the margins black. A filled clip zooms out in fill_filter.
    `track` (keyframes in the finished clip's time) moves the crop over time when zoomed in."""
    zoom = options["zoom"]
    if zoom == 1.0 or (zoom < 1.0 and options["fit"] == "fill"):
        return ""
    if zoom < 1.0:
        return (f",scale=trunc(iw*{zoom:.4f}/2)*2:trunc(ih*{zoom:.4f}/2)*2,"
                f"pad={width}:{height}:(ow-iw)*{options['zx']:.3f}:(oh-ih)*{options['zy']:.3f}:color=black,setsar=1")
    if track:
        where = f"'(iw-ow)*({tracking.expression(track, 1)})':'(ih-oh)*({tracking.expression(track, 2)})'"
    else:
        where = f"(iw-ow)*{options['zx']:.3f}:(ih-oh)*{options['zy']:.3f}"
    return (f",crop=iw/{zoom:.4f}:ih/{zoom:.4f}:{where},"
            f"scale={width}:{height},setsar=1")


def parse_cuts(spec):
    return [(start, end, source) for start, end, source, _ in read_cuts(spec)]


def cut_options(spec):
    return [options for *_, options in read_cuts(spec)]


def speed_pieces(cut, options):
    """(source start, source end, speed) for each stretch of a cut; one stretch unless the clip has a ramp."""
    start, end = cut[0], cut[1]
    span = end - start
    return [(start + a * span, start + b * span, options["speed"] * rel) for a, b, rel in RAMPS[options["ramp"]]]


def out_length(cut, options):
    """Seconds the cut lasts in the Short: its stretches at their speeds plus any held last frame."""
    return sum((b - a) / speed for a, b, speed in speed_pieces(cut, options)) + options["freeze"]


def seam_overlaps(lengths, transitions):
    """Seconds each clip overlaps the one before it. A transition (name, seconds) on a clip eats into both neighbours,
    so it is held to half of the shorter one; the first clip never has one."""
    overlaps = [0.0]
    for i in range(1, len(lengths)):
        name, seconds = transitions[i]
        d = min(seconds, lengths[i] / 2, lengths[i - 1] / 2)
        overlaps.append(round(d, 3) if TRANSITIONS.get(name) and d >= 0.05 else 0.0)
    return overlaps


def intro_length(lengths, transitions):
    """Seconds the first clip takes to appear out of black, when it carries a transition. It starts with the Short,
    so it doesn't change the Short's length."""
    if not lengths:
        return 0.0
    name, seconds = transitions[0]
    d = min(seconds, lengths[0] / 2)
    return round(d, 3) if TRANSITIONS.get(name) and d >= 0.05 else 0.0


def joined_length(lengths, transitions):
    return sum(lengths) - sum(seam_overlaps(lengths, transitions))


def transitions_of(options):
    return [(o["transition"], o["tlen"]) for o in options]


PHRASE_WORDS = 3
PHRASE_CHARS = 22
PHRASE_GAP = 0.6
HOLD_AFTER = 0.35


def phrases_of(words):
    """Group spoken words into short on-screen phrases: a few words each, broken at pauses and sentence ends."""
    groups, current = [], []
    for word in words:
        if current:
            chars = sum(len(w[0]) + 1 for w in current) + len(word[0])
            if (len(current) >= PHRASE_WORDS or chars > PHRASE_CHARS or word[1] - current[-1][2] > PHRASE_GAP
                    or current[-1][0][-1] in ".,;:!?"):
                groups.append(current)
                current = []
        current.append(word)
    if current:
        groups.append(current)
    return groups


def rel_out_time(cut, options, rel, pieces=None):
    """Seconds into the clip, as the Short plays it, where `rel` seconds into its source range falls."""
    at, acc = cut[0] + rel, 0.0
    for a, b, speed in speed_pieces(cut, options) if pieces is None else pieces:
        if at <= a:
            break
        acc += (min(at, b) - a) / speed
    return acc


def word_cues(cut, options, offset, length):
    """Timed cues for a clip's spoken words: a phrase at a time, or in word mode the same phrase with the word being
    said lit. Each shows from its first word until the next one starts, held a moment past the last."""
    span = cut[1] - cut[0]
    words = [(t, a, min(b, span)) for t, a, b in options["words"] if a < span]
    pieces = speed_pieces(cut, options) if words else []
    marks = [(t, rel_out_time(cut, options, a, pieces), rel_out_time(cut, options, b, pieces)) for t, a, b in words]
    cues = []
    for group in phrases_of(marks):
        texts = [w[0] for w in group]
        if options["capmode"] == "phrase":
            steps = [(group[0][1], group[-1][2], " ".join(texts))]
        else:
            steps = [(w[1], group[i + 1][1] if i + 1 < len(group) else w[2], (texts, i)) for i, w in enumerate(group)]
        cues.extend((a, b, text) for a, b, text in steps)
    held = []
    for i, (a, b, text) in enumerate(cues):
        limit = cues[i + 1][0] if i + 1 < len(cues) else length
        held.append((a, max(b, min(b + HOLD_AFTER, limit)), text))
    return [(offset + a, offset + min(b, length), text) for a, b, text in held if a < length]


def has_captions(options):
    return any(o["caption"] or o["words"] for o in options)


def caption_cues(cuts, options, home=None):
    """One cue per captioned cut, spanning that cut on the joined timeline. A caption keeps the position, size and
    turn of the one before it until a clip sets its own."""
    cues, offset = [], 0.0
    lengths = [out_length(cut, opt) for cut, opt in zip(cuts, options)]
    overlaps = seam_overlaps(lengths, transitions_of(options))
    at, scale, turn, look, highlight = home, 1.0, 0.0, DEFAULT_LOOK, DEFAULT_HIGHLIGHT
    ahead = overlaps[1:] + [0.0]
    for cut, opt, length, overlap, next_overlap in zip(cuts, options, lengths, overlaps, ahead):
        offset -= overlap
        if opt["capx"] is not None and opt["capy"] is not None:
            at = (opt["capx"], opt["capy"])
        if opt["capscale"] is not None:
            scale = opt["capscale"]
        if opt["caprot"] is not None:
            turn = opt["caprot"]
        look = opt["caplook"] or look
        highlight = opt["caphi"] or highlight
        if opt["words"] and opt["capmode"] != "text":
            cues.extend((a, b, text, at, scale, turn, look, highlight) for a, b, text in word_cues(cut, opt, offset, length - next_overlap))
        elif opt["caption"]:
            cues.append((offset, offset + length, opt["caption"], at, scale, turn, look, highlight))
        offset += length
    return cues


def atempo_chain(speed):
    """atempo only takes 0.5 to 2 per stage, so split bigger changes into stages."""
    stages = []
    while speed > 2:
        stages.append(2.0)
        speed /= 2
    while speed < 0.5:
        stages.append(0.5)
        speed /= 0.5
    stages.append(speed)
    return ",".join(f"atempo={x:.4f}" for x in stages)


LOUDNESS_RE = re.compile(r"^\s*I:\s+(-?\d+(?:\.\d+)?)\s+LUFS", re.M)


def measure_loudness(src, start, length, track):
    """Integrated loudness (LUFS) of one range, or None when it is silent or has no audio."""
    proc = subprocess.run(
        ["ffmpeg", "-nostats", "-ss", f"{start:.3f}", "-t", f"{length:.3f}", "-i", src, "-map", f"0:a:{track}",
         "-af", "ebur128", "-f", "null", "-"], capture_output=True, text=True)
    found = LOUDNESS_RE.findall(proc.stderr)
    if proc.returncode != 0 or not found:
        return None
    lufs = float(found[-1])
    return lufs if lufs > SILENT_LUFS else None


def leveling_gain(lufs):
    """dB that brings a measured clip to TARGET_LUFS, kept within a sane range."""
    return round(max(-MAX_GAIN_DB, min(MAX_GAIN_DB, TARGET_LUFS - lufs)), 2)


# Glitch comes in short random bursts. Which 0.08 s slots burst, and how, comes from a hash of the slot number,
# so the preview can follow the same schedule. Keep glitch_rand and glitch_burst in step with clipper_ui/app.js.
GLITCH_SLOT = 0.08
GLITCH_ODDS = 0.22
GLITCH_MAX_SLOTS = 400


def glitch_rand(n, k):
    return abs(math.sin(n * 12.9898 + k * 78.233) * 43758.5453) % 1.0


def glitch_burst(n):
    """How slot n glitches, as fractions of the frame, or None when it is clean."""
    if glitch_rand(n, 0) >= GLITCH_ODDS:
        return None
    band_w = 0.2 + 0.3 * glitch_rand(n, 3)
    return {"split": 0.012 + 0.03 * glitch_rand(n, 1), "y": glitch_rand(n, 2) * 0.8, "h": 0.04 + 0.1 * glitch_rand(n, 4),
            "w": band_w, "x": glitch_rand(n, 5) * (1 - 2 * band_w)}


def glitch_filters(w, h, length):
    """Per burst: a strong red/blue split, a torn band swapped sideways, and grain."""
    even = lambda v: int(v) // 2 * 2
    out = []
    for n in range(min(int(length / GLITCH_SLOT) + 1, GLITCH_MAX_SLOTS)):
        g = glitch_burst(n)
        if not g:
            continue
        on = f"enable='between(t,{n * GLITCH_SLOT:.3f},{(n + 1) * GLITCH_SLOT:.3f})'"
        shift = max(4, round(g["split"] * w))
        bw, bh, x1, y = even(g["w"] * w), even(g["h"] * h), even(g["x"] * w), even(g["y"] * h)
        out.append(f",rgbashift=rh={shift}:bh=-{shift}:{on}")
        out.append(f",swaprect=w={bw}:h={bh}:x1={x1}:y1={y}:x2={x1 + bw}:y2={y}:{on}")
        out.append(f",noise=alls=22:allf=t:{on}")
    return out


def effect_filter(effect, w, h, length):
    """ffmpeg filters for one clip effect, written for a w x h frame that lasts `length` seconds."""
    def crop(zoom, dx="0", dy="0"):
        # crop reads iw and ih once from the link, not from each resized frame, so the centre is worked out from the zoom itself.
        return (f"scale=w='trunc({w}*({zoom})/2)*2':h='trunc({h}*({zoom})/2)*2':eval=frame,"
                f"crop={w}:{h}:'(trunc({w}*({zoom})/2)*2-{w})/2+({dx})':'(trunc({h}*({zoom})/2)*2-{h})/2+({dy})'")
    if effect == "zoom_in":
        return "," + crop(f"1+0.15*t/{length:.3f}")
    if effect == "zoom_out":
        return "," + crop(f"1.15-0.15*t/{length:.3f}")
    if effect == "punch":
        return "," + crop("1+0.2*pow(max(0,1-t/0.35),2)")
    if effect == "shake":
        return "," + crop("1.06", f"{w * 0.012:.1f}*sin(t*37)", f"{h * 0.008:.1f}*sin(t*41+1)")
    if effect == "flash":
        return ",fade=t=in:st=0:d=0.25:color=white"
    if effect == "bw":
        return ",hue=s=0"
    if effect == "vignette":
        return ",vignette=PI/4"
    if effect == "glitch":
        return "".join(glitch_filters(w, h, length))
    return ""


def clip_fades(options, length):
    """(fade in, fade out) seconds for one clip, each kept to half its length so they never overlap."""
    cap = length / 2
    return min(options["fadein"], cap), min(options["fadeout"], cap)


def video_fade(options, length):
    """fade to or from black at the clip's own edges"""
    fade_in, fade_out = clip_fades(options, length)
    out = ""
    if fade_in > 0:
        out += f",fade=t=in:st=0:d={fade_in:.3f}"
    if fade_out > 0:
        out += f",fade=t=out:st={length - fade_out:.3f}:d={fade_out:.3f}"
    return out


def audio_fade(options, length):
    fade_in, fade_out = clip_fades(options, length)
    out = ""
    if fade_in > 0:
        out += f",afade=t=in:d={fade_in:.3f}"
    if fade_out > 0:
        out += f",afade=t=out:st={length - fade_out:.3f}:d={fade_out:.3f}"
    return out


def ramp_video(i, start, pieces):
    """Filter lines that cut input i into its speed stretches, retime each, and join them as [vr{i}]."""
    n = len(pieces)
    lines = [f"[{i}:v]split={n}" + "".join(f"[rv{i}_{k}]" for k in range(n))]
    for k, (a, b, speed) in enumerate(pieces):
        lines.append(f"[rv{i}_{k}]trim=start={a - start:.3f}:end={b - start:.3f},setpts=(PTS-STARTPTS)/{speed:.4f}[qv{i}_{k}]")
    lines.append("".join(f"[qv{i}_{k}]" for k in range(n)) + f"concat=n={n}:v=1:a=0[vr{i}]")
    return lines


def ramp_audio(i, track, start, pieces, source=None):
    """The same stretches for the sound, each at its own tempo, joined as [ar{i}]. source names another input to take it from."""
    n = len(pieces)
    lines = [f"[{source or f'{i}:a:{track}'}]asplit={n}" + "".join(f"[ra{i}_{k}]" for k in range(n))]
    for k, (a, b, speed) in enumerate(pieces):
        lines.append(f"[ra{i}_{k}]atrim=start={a - start:.3f}:end={b - start:.3f},asetpts=PTS-STARTPTS,"
                     f"{atempo_chain(speed)}[qa{i}_{k}]")
    lines.append("".join(f"[qa{i}_{k}]" for k in range(n)) + f"concat=n={n}:v=0:a=1[ar{i}]")
    return lines


DRAFT_BITRATE = "12M"
FINAL_BITRATE = "20M"
draft_encode = False


def video_codec(preset, crf):
    """The H.264 encoder flags for the finished Short: the Mac's hardware encoder when there is one (a draft
    preview at a lower bitrate), else x264."""
    if draft_encode:
        return ["-c:v", "h264_videotoolbox", "-b:v", DRAFT_BITRATE]
    if hardware_h264():
        return ["-c:v", "h264_videotoolbox", "-b:v", FINAL_BITRATE]
    return ["-c:v", "libx264", "-preset", preset, "-crf", str(crf)]


SCRATCH_BITRATE = "40M"


def hardware_h264():
    """Whether this ffmpeg has the Mac's hardware H.264 encoder. Looked up once."""
    global _hardware_h264
    if _hardware_h264 is None:
        try:
            out = subprocess.run(["ffmpeg", "-hide_banner", "-encoders"], capture_output=True, text=True, timeout=20).stdout
        except (OSError, subprocess.SubprocessError):
            out = ""
        _hardware_h264 = "h264_videotoolbox" in out
    return _hardware_h264


_hardware_h264 = None


def scratch_codec():
    """Encoder flags for a file that is only read back and re-encoded: hardware at a high bitrate when there is one, else x264."""
    if hardware_h264():
        return ["-c:v", "h264_videotoolbox", "-b:v", SCRATCH_BITRATE]
    return ["-c:v", "libx264", "-preset", "fast", "-crf", "16"]


def montage_context(cuts, sources, options, frame, audio_track, normalize, fade_seconds, hold_last, lut_dir, cache):
    """What every clip of a montage shares: the frame, how clips are joined, and the memoised probes."""
    lengths = [out_length((start, end), opt) for (start, end, _), opt in zip(cuts, options)]
    overlaps = seam_overlaps(lengths, transitions_of(options))
    mixed = len(set(sources)) > 1
    framed = mixed or frame is not None or any(o["fit"] == "fill" or o["zoom"] != 1.0 for o in options)
    base = frame or probe_size(sources[0])
    return {"lengths": lengths, "overlaps": overlaps, "mixed": mixed, "framed": framed, "base": base,
            "width": base[0] if framed else None, "height": base[1] if framed else None, "has_overlaps": any(overlaps),
            "audio_track": audio_track, "normalize": normalize, "fade_seconds": fade_seconds,
            "hold_last": hold_last, "last": len(cuts) - 1, "lut_dir": lut_dir, "cache": cache,
            "audio_presence": {}, "loudness": {}, "effects": {}}


def clip_video_chain(i, cut, opt, ctx):
    """The filter line(s) that turn input i into the clip's picture [v{i}]."""
    start, end = cut[0], cut[1]
    width, height, framed = ctx["width"], ctx["height"], ctx["framed"]
    speed, hold = opt["speed"], opt["freeze"]
    pieces = speed_pieces((start, end), opt)
    ramped = len(pieces) > 1
    length = ctx["lengths"][i]
    moving = length - hold
    fade = clip_dip(ctx["fade_seconds"], length)
    if not framed:
        fit = ""
    elif opt["fit"] == "fill":
        fit = fill_filter(width, height, opt)
    else:
        fit = (f",scale={width}:{height}:force_original_aspect_ratio=decrease,"
               f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2:color=black,setsar=1")
    lines = []
    if ramped:
        vin, retime = f"[vr{i}]", "null"
        lines.extend(ramp_video(i, start, pieces))
    else:
        vin = f"[{i}:v]"
        retime = f"setpts=(PTS-STARTPTS)/{speed:.4f}" if speed != 1 else "setpts=PTS-STARTPTS"
    track = tracking.to_output_time(opt["track"], start, pieces) if opt["track"] else None
    fit += zoom_filter(width, height, opt, track) if framed else ""
    steady = ",fps=30" if ctx["mixed"] or ramped or hold or speed != 1 or opt["effect"] != "none" or ctx["has_overlaps"] else ""
    held = ctx["hold_last"] and i == ctx["last"]
    dip = (f",fade=t=in:st=0:d={fade:.3f}" + ("" if held else f",fade=t=out:st={length - fade:.3f}:d={fade:.3f}")) if ctx["fade_seconds"] else ""
    effect_key = (opt["effect"], moving)
    effects = ctx["effects"]
    if effect_key not in effects:
        effects[effect_key] = effect_filter(opt["effect"], ctx["base"][0], ctx["base"][1], moving)
    look = grade_filter(opt, ctx["lut_dir"]) + effects[effect_key]
    freeze = f",tpad=stop_mode=clone:stop_duration={hold:.3f}" if hold else ""
    lines.append(f"{vin}{retime}{fit}{steady}{look}{freeze}{video_fade(opt, length)}{dip},setsar=1[v{i}]")
    return lines


def clip_dip(fade_seconds, length):
    return min(fade_seconds, length / 3) if fade_seconds else min(0.03, length / 4)


def clip_is_heard(src, opt, ctx):
    """Whether the clip contributes sound. Muted clips skip the probe, so a soundtrack that cannot be heard is never read."""
    if opt["volume"] == 0:
        return False
    presence = ctx["audio_presence"]
    if src not in presence:
        presence[src] = has_audio(src)
    return presence[src]


def clip_loudness(measurement, ctx):
    """Integrated loudness of one range, measured once per render, or once per source version with a cache."""
    cache, memo = ctx["cache"], ctx["loudness"]
    if measurement not in memo:
        memo[measurement] = cache.loudness(*measurement, measure_loudness) if cache else measure_loudness(*measurement)
    return memo[measurement]


def clip_audio_chain(i, cut, src, opt, ctx, voice_in):
    """The filter line(s) that give the clip its sound [a{i}]: from input i, from its voice at input voice_in, or silence."""
    start, end = cut[0], cut[1]
    speed, volume, hold = opt["speed"], opt["volume"], opt["freeze"]
    length = ctx["lengths"][i]
    fade = clip_dip(ctx["fade_seconds"], length)
    if not clip_is_heard(src, opt, ctx):
        return [f"anullsrc=r=44100:cl=stereo,atrim=0:{length:.3f}[a{i}]"]
    track = ctx["audio_track"] if not ctx["mixed"] else 0
    voice = opt["voice"]
    heard = f"{voice_in}:a" if voice else f"{i}:a:{track}"
    pieces = speed_pieces((start, end), opt)
    lines = []
    if len(pieces) > 1:
        asrc, tempo = f"[ar{i}]", ""
        lines.extend(ramp_audio(i, track, start, pieces, heard if voice else None))
    else:
        asrc = f"[{heard}]"
        tempo = f",{atempo_chain(speed)}" if speed != 1 else ""
    pad = f",apad=pad_dur={hold:.3f}" if hold else ""
    level = f",volume={volume:.3f}" if volume != 1 else ""
    if ctx["normalize"]:
        measurement = (voice, 0.0, end - start, 0) if voice else (src, start, end - start, track)
        lufs = clip_loudness(measurement, ctx)
        if lufs is not None:
            gain = leveling_gain(lufs)
            print(f"clip {i + 1}: {lufs:.1f} LUFS, {gain:+.1f} dB", file=sys.stderr)
            level = f",volume={gain}dB{level},alimiter=limit=0.95"
    lines.append(
        f"{asrc}asetpts=PTS-STARTPTS{tempo},aresample=44100,aformat=channel_layouts=stereo{level}{pad},"
        f"afade=t=in:d={fade},afade=t=out:st={length - fade:.3f}:d={fade}{audio_fade(opt, length)}[a{i}]"
    )
    return lines


def clip_input(cut, src):
    start, end = cut[0], cut[1]
    return ["-ss", f"{start:.3f}", "-t", f"{end - start:.3f}", "-i", src]


def clip_spec(i, cut, src, opt, ctx):
    """How the clip is rendered on its own: (inputs, filter lines, encoder, frames), with the clip as input 0 and its voice as input 1."""
    own = {**ctx, "lengths": {0: ctx["lengths"][i]}, "last": 0 if i == ctx["last"] else -1}
    lines = clip_video_chain(0, cut, opt, own) + clip_audio_chain(0, cut, src, opt, own, 1)
    voiced = opt["voice"] and clip_is_heard(src, opt, ctx)
    inputs = clip_input(cut, src) + (["-i", opt["voice"]] if voiced else [])
    return (inputs, lines, scratch_codec(), clip_cache.frame_count(ctx["lengths"][i]))


def montage_plan(clip, cuts, options, frame, audio_track, normalize, fade_seconds, hold_last, cache, lut_dir=None):
    """The shared context and per-clip sources of a montage."""
    options = options or [dict(DEFAULT_OPTIONS) for _ in cuts]
    sources = [src or clip for _, _, src in cuts]
    ctx = montage_context(cuts, sources, options, frame, audio_track, normalize, fade_seconds, hold_last, cache.dir if cache else lut_dir, cache)
    return options, sources, ctx


def cached_clip_files(clip, cuts, audio_track, options, frame, normalize, fade_seconds, hold_last, cache):
    """Each clip rendered on its own and kept in the cache: the files, in order, and the clips' lengths."""
    options, sources, ctx = montage_plan(clip, cuts, options, frame, audio_track, normalize, fade_seconds, hold_last, cache)
    specs = [clip_spec(i, cut, src, opt, ctx) for i, (cut, src, opt) in enumerate(zip(cuts, sources, options))]
    return cache.clips(specs, clip_cache.render_clip), ctx["lengths"]


def plain_join(options, lengths):
    """Whether the clips simply follow each other, with no transition to blend across a seam."""
    transitions = transitions_of(options)
    return not any(seam_overlaps(lengths, transitions)) and not intro_length(lengths, transitions)


def build_montage(clip, cuts, audio_track, dest, options=None, frame=None, normalize=False, fade_seconds=0.0, hold_last=False, output_limit=None, cache=None):
    """Join the cut ranges into one clip. Each range is seeked on its own input so a long episode is not decoded end to end.

    When cuts come from several files, or a frame is given, or a clip is set to fill, every segment is fitted into
    one frame (the first segment's size unless frame is given) so they can be joined. With normalize, each clip is
    measured and brought to the same loudness before its own volume setting is applied. With fade_seconds, each
    clip dips to black and silence at both ends so cuts are soft. hold_last leaves the dip off the last clip's
    picture, for a lane whose last frame is held after it ends. output_limit caps
    encoding at the visible lane duration without changing clip/effect timing.
    With a cache, each clip is rendered on its own and kept, so the next render of the same clip reuses the file.
    """
    options, sources, ctx = montage_plan(clip, cuts, options, frame, audio_track, normalize, fade_seconds, hold_last, cache, Path(dest).parent)
    cmd = ["ffmpeg", "-y", "-loglevel", "error"]
    parts = []
    voices = []
    if cache:
        files, _ = cached_clip_files(clip, cuts, audio_track, options, frame, normalize, fade_seconds, hold_last, cache)
        for i, path in enumerate(files):
            cmd += ["-i", path]
            parts += [f"[{i}:v]null[v{i}]", f"[{i}:a]anull[a{i}]"]
    for i, (cut, src, opt) in enumerate(zip(cuts, sources, options) if not cache else ()):
        cmd += clip_input(cut, src)
        parts.extend(clip_video_chain(i, cut, opt, ctx))
        parts.extend(clip_audio_chain(i, cut, src, opt, ctx, len(cuts) + len(voices)))
        if opt["voice"] and clip_is_heard(src, opt, ctx):
            voices.append(opt["voice"])
    parts.extend(join_clips(options, ctx["lengths"], ctx["overlaps"]))
    for voice in voices:
        cmd += ["-i", voice]
    render_length = joined_length(ctx["lengths"], transitions_of(options))
    if output_limit is not None and render_length > output_limit:
        render_length = output_limit
        cmd += ["-t", f"{render_length:.3f}"]
    cmd += ["-filter_complex", ";".join(parts), "-map", "[v]", "-map", "[a]", "-map_chapters", "-1",
            *scratch_codec(), "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-b:a", "192k", dest]
    subprocess.run(cmd, check=True)
    return render_length


def join_clips(options, lengths, overlaps):
    """Filter lines that join clips [v0][a0]... into [v][a]: a plain concat, or with transitions, concat runs
    of hard cuts and xfade the runs into each other."""
    n = len(lengths)
    intro = intro_length(lengths, transitions_of(options))
    if not any(overlaps) and not intro:
        return ["".join(f"[v{i}][a{i}]" for i in range(n)) + f"concat=n={n}:v=1:a=1[v][a]"]
    runs, run_overlap = [], []
    for i in range(n):
        if overlaps[i]:
            runs.append([i])
            run_overlap.append(overlaps[i])
        elif runs:
            runs[-1].append(i)
        else:
            runs.append([i])
            run_overlap.append(0.0)
    lines = []
    for j, run in enumerate(runs):
        lines.append("".join(f"[v{i}][a{i}]" for i in run) + f"concat=n={len(run)}:v=1:a=1[cv{j}][ca{j}]")
        lines.append(f"[cv{j}]settb=AVTB,fps=30[rv{j}]")
    acc_v, acc_a, acc_len = "rv0", "ca0", sum(lengths[i] for i in runs[0])
    if intro:
        name = options[0]["transition"]
        kind = TRANSITIONS[name] + (f":expr='{TRANSITION_EXPR[name]}'" if name in TRANSITION_EXPR else "")
        last = len(runs) == 1
        lines.append(f"[rv0]split[ivs][ivb];[ivb]trim=end={intro:.3f},setpts=PTS-STARTPTS,drawbox=x=0:y=0:w=iw:h=ih:color=black:t=fill[ivk]")
        lines.append(f"[ivk][ivs]xfade=transition={kind}:duration={intro:.3f}:offset=0[{'v' if last else 'iv'}]")
        lines.append(f"anullsrc=r=44100:cl=stereo,atrim=0:{intro:.3f}[iak]")
        lines.append(f"[iak][ca0]acrossfade=d={intro:.3f}:c1=tri:c2=tri[{'a' if last else 'ia'}]")
        acc_v, acc_a = "iv", "ia"
    for j in range(1, len(runs)):
        d = run_overlap[j]
        name = options[runs[j][0]]["transition"]
        kind = TRANSITIONS[name] + (f":expr='{TRANSITION_EXPR[name]}'" if name in TRANSITION_EXPR else "")
        last = j == len(runs) - 1
        lines.append(f"[{acc_v}][rv{j}]xfade=transition={kind}:duration={d:.3f}:offset={acc_len - d:.3f}[{'v' if last else f'xv{j}'}]")
        lines.append(f"[{acc_a}][ca{j}]acrossfade=d={d:.3f}:c1=tri:c2=tri[{'a' if last else f'xa{j}'}]")
        acc_v, acc_a = f"xv{j}", f"xa{j}"
        acc_len += sum(lengths[i] for i in runs[j]) - d
    return lines


SPLIT_RANGE = (0.2, 0.8)


def clamp_split(frac):
    """A seam position kept inside the range where both sides stay watchable."""
    return min(SPLIT_RANGE[1], max(SPLIT_RANGE[0], float(frac)))


def halves(height, frac=0.5):
    """Heights of the top and bottom lanes of a frame, both even so they join cleanly. `frac` is the top's share."""
    top = (int(height * clamp_split(frac)) + 1) // 2 * 2
    return top, height - top


def lane_sizes(width, height, template, row=0.5, col=0.5):
    """The (width, height) of each lane for a layout, all even so the lanes join cleanly.

    `row` is the top row's share of the height (split and three); `col` is the left share of three's bottom pair.
    Four stays an equal grid.
    """
    if template == "four":
        row = col = 0.5
    top_h, bottom_h = halves(height, row)
    left_w = (int(width * clamp_split(col)) + 1) // 2 * 2
    right_w = width - left_w
    if template == "split":
        return [(width, top_h), (width, bottom_h)]
    if template == "three":
        return [(width, top_h), (left_w, bottom_h), (right_w, bottom_h)]
    if template == "four":
        return [(left_w, top_h), (right_w, top_h), (left_w, bottom_h), (right_w, bottom_h)]
    return [(width, height)]


def lane_split(cuts, options, count=2):
    """Split a cut list into its lanes, top first: (cuts, options) for each of `count` lanes."""
    lanes = []
    for lane in LANES[:count]:
        picked = [(c, o) for c, o in zip(cuts, options) if o["lane"] == lane]
        lanes.append(([c for c, _ in picked], [o for _, o in picked]))
    return lanes


def stack_lanes(files, length, sizes, template, dest):
    """Lay the lanes out as the template says, for the top lane's length.

    A lane that runs short holds its last frame (and goes silent), and one that runs long is cut off.
    A lane with no file stays black.
    """
    cmd = ["ffmpeg", "-y", "-loglevel", "error", "-i", files[0]]
    graph = ["[0:v]fps=30[v0]"]
    audio = ["[0:a]"]
    inputs = 0
    for k in range(1, len(sizes)):
        if files[k]:
            inputs += 1
            cmd += ["-i", files[k]]
            graph.append(f"[{inputs}:v]fps=30,tpad=stop_mode=clone:stop_duration={length:.3f},trim=duration={length:.3f},setpts=PTS-STARTPTS[v{k}]")
            graph.append(f"[{inputs}:a]apad,atrim=0:{length:.3f},asetpts=PTS-STARTPTS[a{k}]")
            audio.append(f"[a{k}]")
        else:
            w, h = sizes[k]
            graph.append(f"color=c=black:s={w}x{h}:r=30:d={length:.3f},format=yuv420p[v{k}]")
    rows = LANE_ROWS[template]
    for r, row in enumerate(rows):
        graph.append("".join(f"[v{k}]" for k in row) + (f"hstack=inputs={len(row)}[r{r}]" if len(row) > 1 else "null") + ("" if len(row) > 1 else f"[r{r}]"))
    graph.append("".join(f"[r{r}]" for r in range(len(rows))) + f"vstack=inputs={len(rows)}[v]")
    graph.append("".join(audio) + (f"amix=inputs={len(audio)}:normalize=0:duration=first[a]" if len(audio) > 1 else "anull[a]"))
    cmd += ["-filter_complex", ";".join(graph), "-map", "[v]", "-map", "[a]", "-t", f"{length:.3f}",
            *scratch_codec(), "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k", dest]
    subprocess.run(cmd, check=True)


MAX_AUDIO_ITEMS = 40
AUDIO_LIMITS = {"start": (0.0, 600.0), "in": (0.0, 36000.0), "dur": (0.05, 600.0), "volume": (0.0, 3.0), "fadein": (0.0, 30.0), "fadeout": (0.0, 30.0),
                "volumeend": (0.0, 3.0)}


def load_audio_items(spec):
    """Songs and sound effects to lay over the Short, from a JSON file: path, start (seconds into the Short), in
    (seconds into the sound), dur, volume, volumeend (the level it slides to by its end, default volume), fadein, fadeout."""
    try:
        items = json.loads(Path(spec).read_text())
    except (OSError, ValueError) as err:
        sys.exit(f"can't read the audio list: {err}")
    if not isinstance(items, list) or len(items) > MAX_AUDIO_ITEMS:
        sys.exit(f"the audio list must be a list of at most {MAX_AUDIO_ITEMS} sounds")
    loaded = []
    for n, item in enumerate(items, 1):
        if not isinstance(item, dict) or not Path(str(item.get("path", ""))).is_file():
            sys.exit(f"audio {n}: file not found")
        values = {"path": str(item["path"])}
        for key, (low, high) in AUDIO_LIMITS.items():
            try:
                fallback = values["volume"] if key == "volumeend" else 1.0 if key == "volume" else 0.0
                value = float(item.get(key) if item.get(key) is not None else fallback)
            except (TypeError, ValueError):
                sys.exit(f"audio {n}: {key} must be a number")
            if not low <= value <= high:
                sys.exit(f"audio {n}: {key} must be between {low:g} and {high:g}")
            values[key] = value
        loaded.append(values)
    return loaded


def sound_level(item):
    """The volume filter for a sound: one level, or a straight slide from its volume to volumeend over its length."""
    start = item["volume"]
    end = item.get("volumeend", start)
    if abs(end - start) < 0.0005:
        return f"volume={start:.3f}"
    return f"volume='{start:.3f}+({end:.3f}-{start:.3f})*t/{item['dur']:.3f}':eval=frame"


def audio_mix_graph(items, first=1):
    """Filter graph laying each sound over the Short's own audio [0:a]. Sound k is input first+k: trimmed, levelled,
    faded and delayed to its start; amix keeps the Short's length and the original levels."""
    parts, tags = [], ["[0:a]"]
    for k, item in enumerate(items):
        dur = item["dur"]
        fade_in, fade_out = min(item["fadein"], dur / 2), min(item["fadeout"], dur / 2)
        chain = [f"atrim=start={item['in']:.3f}:duration={dur:.3f}", "asetpts=PTS-STARTPTS",
                 "aresample=44100", "aformat=channel_layouts=stereo", sound_level(item)]
        if fade_in:
            chain.append(f"afade=t=in:d={fade_in:.3f}")
        if fade_out:
            chain.append(f"afade=t=out:st={dur - fade_out:.3f}:d={fade_out:.3f}")
        delay = round(item["start"] * 1000)
        chain.append(f"adelay=delays={delay}:all=1")
        parts.append(f"[{first + k}:a]{','.join(chain)}[m{k}]")
        tags.append(f"[m{k}]")
    parts.append(f"{''.join(tags)}amix=inputs={len(tags)}:normalize=0:duration=first:dropout_transition=0[a]")
    return ";".join(parts)


def mix_audio(video, items):
    """Replace the video's soundtrack with it mixed with the given sounds. The picture is copied, not re-encoded."""
    # A sound contributes nothing only when both ends of its level are zero.
    # Keep fades up from silence, and avoid a full AAC pass if all are muted.
    items = [item for item in (items or []) if item["volume"] != 0 or item.get("volumeend", item["volume"]) != 0]
    if not items:
        return
    tmp = str(Path(video).with_name(f".mix_{Path(video).name}"))
    cmd = ["ffmpeg", "-y", "-loglevel", "error", "-i", video]
    for item in items:
        cmd += ["-i", item["path"]]
    cmd += ["-filter_complex", audio_mix_graph(items), "-map", "0:v", "-map", "[a]", "-c:v", "copy", "-c:a", "aac",
            "-b:a", "192k", "-movflags", "+faststart", "-f", "mp4", tmp]
    subprocess.run(cmd, check=True)
    Path(tmp).replace(video)


def probe_duration(path):
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", path],
        check=True, capture_output=True, text=True,
    ).stdout.strip()
    return float(out)


def has_audio(path):
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "a:0", "-show_entries", "stream=codec_type",
         "-of", "csv=p=0", path],
        check=True, capture_output=True, text=True,
    ).stdout.strip()
    return bool(out)


def voice_mix_graph(clip_idx, voice_idx, music_idx, voice_delay, music_vol, dur):
    """Narration over the clip: clip (and music) duck while the voice speaks. clip_idx/music_idx may be None."""
    stereo = "aresample=44100,aformat=channel_layouts=stereo"
    ducks = int(clip_idx is not None) + int(music_idx is not None)
    delay_ms = int(voice_delay * 1000)
    parts = [
        f"[{voice_idx}:a]{stereo},adelay={delay_ms}|{delay_ms},dynaudnorm=f=150:g=15,apad=whole_dur={dur},"
        f"asplit={ducks + 1}" + "".join(f"[vs{i}]" for i in range(ducks + 1))
    ]
    mix_labels = ["[vs0]"]
    n = 1
    if clip_idx is not None:
        parts.append(f"[{clip_idx}:a]{stereo}[ca]")
        parts.append(f"[ca][vs{n}]sidechaincompress=threshold=0.03:ratio=8:attack=20:release=300[cd]")
        mix_labels.append("[cd]")
        n += 1
    if music_idx is not None:
        parts.append(f"[{music_idx}:a]{stereo},volume={music_vol}[ma]")
        parts.append(f"[ma][vs{n}]sidechaincompress=threshold=0.03:ratio=6:attack=20:release=400[md]")
        mix_labels.append("[md]")
    parts.append("".join(mix_labels) + f"amix=inputs={len(mix_labels)}:normalize=0:duration=longest,alimiter=limit=0.95[a]")
    return ";".join(parts)


def main():
    ffmpeg_env.activate()
    p = argparse.ArgumentParser()
    p.add_argument("clip", nargs="?", help="default source; optional when every cut names its own file")
    p.add_argument("--start", type=parse_time, default=0, help="seconds or [h:]mm:ss")
    p.add_argument("--dur", type=parse_time, default=30, help="seconds or [h:]mm:ss")
    p.add_argument("--cuts", help="file or text of 'start - end' ranges, joined in order (replaces --start/--dur)")
    p.add_argument("--frame", choices=sorted(FRAMES), help="shape of the clip area on the card: wide (16:9), square or tall (4:5); default follows the first clip")
    p.add_argument("--format", choices=list(FORMATS), default=DEFAULT_FORMAT, help="size of the finished video: 9:16 (1080x1920), 4:5, 1:1 or 16:9 (1920x1080); needs --card")
    p.add_argument("--template", choices=TEMPLATES, default="full", help="full: one clip fills the frame; split, three, four: that many lanes stacked (cuts marked @lane bottom, third or fourth)")
    p.add_argument("--row-split", type=float, default=0.5, help="share of the height the top row takes in split and three (%g to %g)" % SPLIT_RANGE)
    p.add_argument("--col-split", type=float, default=0.5, help="share of the width the left lane takes in three's bottom pair (%g to %g)" % SPLIT_RANGE)
    p.add_argument("--normalize", action="store_true", help="bring every clip to the same loudness before joining")
    p.add_argument("--fade", type=float, default=0.0, help="seconds each clip dips to black at both ends (0 = hard cuts, try 0.15)")
    p.add_argument("--audio-track", type=int, default=0, help="audio stream for --cuts (0 = first, e.g. Japanese; 1 = English)")
    p.add_argument("--subs", help="burn subtitles under the clip (card mode): a language code such as 'eng' for the video's own track, or an .srt/.ass file")
    p.add_argument("--text", help="caption (blur mode) or hook line (card mode)")
    p.add_argument("--card", action="store_true", help="dark card layout around the clip")
    p.add_argument("--layout", choices=sorted(LAYOUTS), default=DEFAULT_LAYOUT, help="card layout: title (hook above, left), center (hook above, centred), profile (avatar and handle above the hook), bare (clip only)")
    p.add_argument("--caption-size", type=int, default=SUB_FONT_SIZE, help="caption and subtitle text size in pixels on the finished frame (%d to %d)" % CAPTION_SIZES)
    p.add_argument("--blur-bg", action="store_true", help="card mode: fill the space around the clip with a blurred, darkened copy of it")
    p.add_argument("--watermark", help="faint text centred over the clip (card mode), e.g. your channel handle")
    p.add_argument("--name", default="", help="channel name on the title card; the bench passes the connected YouTube channel's")
    p.add_argument("--handle", default="", help="channel handle on the title card, e.g. @channel; blank draws none")
    p.add_argument("--avatar", default="workspace/channel/avatar.png")
    p.add_argument("--draft", action="store_true", help="encode with the hardware encoder: faster, larger, for previews")
    p.add_argument("--audio-mix", help="JSON list of songs and sound effects laid over the finished Short")
    p.add_argument("--music")
    p.add_argument("--voice", help="narration audio (or video) mixed over the clip; clip audio ducks while it speaks")
    p.add_argument("--voice-delay", type=float, default=0.0, help="seconds before the narration starts")
    p.add_argument("--music-vol", type=float, default=0.15, help="music level when used with --voice")
    p.add_argument("--cache", help="folder where rendered clips are kept, so the next render only redoes the clips that changed")
    p.add_argument("-o", "--out")
    a = p.parse_args()
    global draft_encode
    draft_encode = a.draft

    cuts = parse_cuts(a.cuts) if a.cuts else None
    if not a.clip:
        if not cuts or any(src is None for _, _, src in cuts):
            sys.exit("give a clip, or name a source on every cut line")
        a.clip = cuts[0][2]
    if not Path(a.clip).is_file():
        sys.exit(f"clip not found: {a.clip}")
    if a.subs and cuts and len({src or a.clip for _, _, src in cuts}) > 1:
        sys.exit("--subs reads one video's subtitle track, so it can't be used when cuts come from several files")
    if a.voice and not Path(a.voice).is_file():
        sys.exit(f"voice not found: {a.voice}")
    if a.music and not Path(a.music).is_file():
        sys.exit(f"music not found: {a.music}")
    audio_items = load_audio_items(a.audio_mix) if a.audio_mix else []
    options = cut_options(a.cuts) if a.cuts else []
    lane_count = LANE_COUNT[a.template]
    lane_cuts = lane_split(cuts, options, 4) if cuts else [([], [])] * 4
    top_cuts, top_opts = lane_cuts[0]
    if any(c for c, _ in lane_cuts[lane_count:]):
        sys.exit(f"the cut list has clips in lanes that --template {a.template} doesn't have, so use a template with more lanes")
    if lane_count > 1 and not (cuts and top_cuts):
        sys.exit(f"--template {a.template} needs a cut list with at least one top lane clip")
    if (a.template != "full" or a.format != DEFAULT_FORMAT) and not a.card:
        sys.exit("--format and --template shape the card, so they need --card")
    if lane_count > 1 and a.subs:
        sys.exit(f"--subs follows one video's timing, so it can't be used with --template {a.template}")
    cuts, options = (top_cuts, top_opts) if cuts else (cuts, options)
    if a.template in ("fill", "fit"):
        options = [{**o, "fit": a.template} for o in options]
    captions = [o["caption"] or o["words"] for o in options]
    if any(captions) and a.subs:
        sys.exit("the cut list has captions and --subs is set, and both sit on the clip; use one")
    if any(captions) and not a.card:
        print("warning: captions are only drawn in card mode (--card), so they are ignored", file=sys.stderr)
        options = [{**o, "caption": "", "words": None} for o in options]
    if a.subs and any(o["speed"] != 1 or o["ramp"] != "none" or o["freeze"] for o in options):
        sys.exit("--subs follows the video's own timing, so it can't be used with speed, ramp or freeze changes")
    if a.subs and not a.card:
        sys.exit("--subs needs --card (the subtitles sit in the space under the clip)")
    if (a.frame or a.normalize or a.fade) and not cuts:
        sys.exit("--frame, --normalize and --fade work on a cut list, so give --cuts")
    if not CAPTION_SIZES[0] <= a.caption_size <= CAPTION_SIZES[1]:
        sys.exit("--caption-size must be between %d and %d" % CAPTION_SIZES)
    if not 0 <= a.fade <= 1:
        sys.exit("--fade must be between 0 and 1 second")
    if a.watermark and not a.card:
        print("warning: the watermark is only drawn in card mode (--card), so it is ignored", file=sys.stderr)
    if a.card and LAYOUTS[a.layout]["header"] and not Path(a.avatar).is_file():
        sys.exit(f"avatar not found: {a.avatar}")
    total = joined_length([out_length(c, o) for c, o in zip(cuts, options)], transitions_of(options)) if cuts else a.dur
    if not 1 <= total <= MAX_DUR:
        sys.exit(f"length must be 1-{MAX_DUR}s, got {total:g}s")
    out = a.out or f"out/{Path(a.clip).stem}_short.mp4"
    Path(out).parent.mkdir(parents=True, exist_ok=True)

    canvas = FORMATS[a.format]
    geo = card_geometry(canvas, a.text, a.layout, a.format) if a.card else None
    cache = clip_cache.ClipCache(a.cache) if a.cache else None
    with tempfile.TemporaryDirectory() as tmp:
        source, start, dur = a.clip, a.start, a.dur
        source_input = None
        if cuts:
            source = str(Path(tmp) / "montage.mp4")
            frame = (geo["clip_w"], geo["clip_h"]) if geo else FRAMES.get(a.frame)
            if lane_count > 1:
                sizes = lane_sizes(frame[0], frame[1], a.template, a.row_split, a.col_split)
                files = []
                dur = 0
                for k, (lane_c, lane_o) in enumerate(lane_cuts[:lane_count]):
                    if not lane_c:
                        files.append(None)
                        continue
                    lane_file = str(Path(tmp) / f"lane_{k}.mp4")
                    length = build_montage(a.clip, lane_c, a.audio_track, lane_file, lane_o, sizes[k], a.normalize, a.fade, hold_last=k > 0,
                                           output_limit=dur if k > 0 else None, cache=cache)
                    dur = length if k == 0 else dur
                    files.append(lane_file)
                stack_lanes(files, dur, sizes, a.template, source)
            elif cache and plain_join(options, [out_length(c, o) for c, o in zip(cuts, options)]):
                files, lengths = cached_clip_files(a.clip, cuts, a.audio_track, options, frame, a.normalize, a.fade, False, cache)
                source_input = clip_cache.list_input(clip_cache.write_list(files, Path(tmp) / "montage.txt"))
                source, dur = files[0], sum(lengths)
            else:
                dur = build_montage(a.clip, cuts, a.audio_track, source, options, frame, a.normalize, a.fade, cache=cache)
            start = 0
        cmd = ["ffmpeg", "-y"]
        if a.card:
            bg = str(Path(tmp) / "card.png")
            geo = geo or card_geometry(canvas, a.text, a.layout, a.format, probe_size(source))
            cw, ch, cx, cy = render_card(geo, a.name, a.handle, a.avatar, bg, clear=a.blur_bg)
            cmd += ["-loop", "1", "-framerate", "30", "-i", bg,
                    "-ss", str(start), "-t", str(dur), *(source_input or ["-i", source])]
            home = caption_home(canvas, a.format, cy + ch)
            mark = watermark_filter(a.watermark, cw, corner=a.format == "16:9") if a.watermark else ""
            if a.blur_bg:
                ox = oy = 0
                pw, ph = cw, ch
                if cuts:
                    sw, sh = probe_size(cuts[0][2] or a.clip)
                    k = min(cw / sw, ch / sh)
                    pw, ph = int(sw * k) // 2 * 2, int(sh * k) // 2 * 2
                    ox, oy = (cw - pw) // 2, (ch - ph) // 2
                trim = f"crop={pw}:{ph}:{ox}:{oy}"
                low = watermark_filter(a.watermark, cw, box=(cy, ch)) if a.watermark and a.format != "16:9" else ""
                graph = (f"[1:v]split=2[s1][s2];[s2]{trim},scale={canvas[0] // BLUR_BG_SHRINK}:{canvas[1] // BLUR_BG_SHRINK}:flags=area,"
                         f"scale={canvas[0]}:{canvas[1]}:flags=bicubic,gblur=sigma=40,"
                         f"eq=contrast=0.7:brightness={BLUR_BG_DIM}:saturation=1.1,setsar=1[b];"
                         f"[b][0:v]overlay=0:0[t];[s1]scale={cw}:{ch},{trim}[c];[t][c]overlay={cx + ox}:{cy + oy}:shortest=1,setsar=1{low}")
            else:
                graph = f"[1:v]scale={cw}:{ch}{mark}[c];[0:v][c]overlay={cx}:{cy}:shortest=1"
            if a.subs:
                ranges = [(c[0], c[1]) for c in cuts] if cuts else [(a.start, a.start + a.dur)]
                overlaps = seam_overlaps([c[1] - c[0] for c in cuts], transitions_of(options)) if cuts else None
                cues = [(lo, hi, text, home) for lo, hi, text in remap_cues(load_cues(a.subs, a.clip, tmp), ranges, overlaps)]
                ass = str(Path(tmp) / "subs.ass")
                write_ass(cues, cy + ch + SUB_GAP, ass, canvas, a.caption_size)
                graph += f"[o];[o]subtitles=filename='{filter_path(ass)}'"
                print(f"{len(cues)} subtitle lines", file=sys.stderr)
            if has_captions(options):
                ass = str(Path(tmp) / "captions.ass")
                write_ass(caption_cues(cuts, options, home), cy + ch + SUB_GAP, ass, canvas, a.caption_size)
                graph += f"[o];[o]subtitles=filename='{filter_path(ass)}'"
                print(f"{sum(1 for o in options if o['caption'] or o['words'])} captions", file=sys.stderr)
            graph += "[v]"
            audio_in = 1
            music_idx = 2
        else:
            cmd += ["-ss", str(start), "-t", str(dur), *(source_input or ["-i", source])]
            graph = blur_filter(a.text)
            audio_in = 0
            music_idx = 1
        next_idx = music_idx
        voice_idx = None
        if a.voice:
            voice_idx = next_idx
            cmd += ["-i", a.voice]
            next_idx += 1
            narration = probe_duration(a.voice) + a.voice_delay
            if narration > dur:
                print(f"warning: narration runs {narration:.1f}s but the Short is {dur:g}s, so it will be cut off",
                      file=sys.stderr)
        music_in = None
        if a.music:
            music_in = next_idx
            cmd += ["-stream_loop", "-1", "-i", a.music]
        if a.voice:
            clip_in = audio_in if has_audio(source) else None
            graph += ";" + voice_mix_graph(clip_in, voice_idx, music_in, a.voice_delay, a.music_vol, dur)
            cmd += ["-filter_complex", graph, "-map", "[v]", "-map", "[a]"]
        else:
            cmd += ["-filter_complex", graph, "-map", "[v]"]
            cmd += ["-map", f"{music_in}:a", "-shortest"] if a.music else ["-map", f"{audio_in}:a?"]
        cmd += ["-t", str(dur), "-sn", "-dn", "-map_chapters", "-1", *video_codec("medium", 18),
                "-pix_fmt", "yuv420p", "-r", "30", "-c:a", "aac", "-b:a", "192k",
                "-movflags", "+faststart", out]
        subprocess.run(cmd, check=True)
    mix_audio(out, audio_items)
    if cache:
        print(f"clips kept: {cache.hits} reused, {cache.misses} rendered", file=sys.stderr)
        cache.prune()
    print(out)


if __name__ == "__main__":
    main()
