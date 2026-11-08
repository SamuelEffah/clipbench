"""Shared grading model: browser shader in clipper_ui/grade.js mirrors grade_rgb."""
import hashlib
import json
from pathlib import Path

GRADE_DEFAULTS = dict(brightness=1., contrast=1., saturation=1., exposure=0., vibrance=0., temperature=0., tint=0., shadows=0., highlights=0.)
GRADE_RANGES = {k: ((0., 2.) if k in ('brightness', 'contrast', 'saturation') else (-2., 2.) if k == 'exposure' else (-1., 1.)) for k in GRADE_DEFAULTS}


def grade_rgb(rgb, values):
    g = {**GRADE_DEFAULTS, **{k: values[k] for k in GRADE_DEFAULTS if k in values}}
    r, green, b = [(v * 2 ** g['exposure'] * g['brightness'] - .5) * g['contrast'] + .5 for v in rgb]
    r += .1 * g['temperature'] + .05 * g['tint']
    green -= .1 * g['tint']
    b += -.1 * g['temperature'] + .05 * g['tint']
    lum = max(0., min(1., .2126*r + .7152*green + .0722*b))
    tone = .25 * (g['shadows'] * (1-lum)**2 + g['highlights'] * lum**2)
    r, green, b = r+tone, green+tone, b+tone
    lum = .2126*r + .7152*green + .0722*b
    chroma = min(1., max(r, green, b)-min(r, green, b))
    sat = max(0., g['saturation'] + g['vibrance'] * (1-chroma))
    return tuple(max(0., min(1., lum+(v-lum)*sat)) for v in (r,green,b))


def grade_filter(values, directory):
    g = {k: values.get(k, v) for k, v in GRADE_DEFAULTS.items()}
    if g == GRADE_DEFAULTS:
        return ''
    digest = hashlib.sha256(json.dumps(g, sort_keys=True).encode()).hexdigest()[:20]
    path = Path(directory) / f'grade-{digest}.cube'
    if not path.exists():
        lines = ['LUT_3D_SIZE 33', 'DOMAIN_MIN 0 0 0', 'DOMAIN_MAX 1 1 1']
        for b in range(33):
            for green in range(33):
                for r in range(33):
                    lines.append(' '.join(f'{v:.7f}' for v in grade_rgb((r/32,green/32,b/32),g)))
        path.write_text('\n'.join(lines)+'\n')
    escaped = str(path).replace('\\', '/').replace(':', r'\:').replace("'", r"'\''")
    return f",lut3d=file='{escaped}':interp=tetrahedral"
