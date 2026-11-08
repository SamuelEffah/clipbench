"""Content-addressed clip thumbnails, with compatibility for embedded project images."""
import base64
import binascii
import hashlib
import tempfile
from pathlib import Path

FORMATS = {'data:image/jpeg;base64': 'jpg', 'data:image/png;base64': 'png', 'data:image/webp;base64': 'webp'}


def image_data(value):
    if not isinstance(value, str) or ',' not in value:
        return None
    header, encoded = value.split(',', 1)
    suffix = FORMATS.get(header)
    if not suffix:
        return None
    try:
        data = base64.b64decode(encoded, validate=True)
    except (binascii.Error, ValueError):
        return None
    valid = ((suffix == 'jpg' and data.startswith(b'\xff\xd8\xff'))
             or (suffix == 'png' and data.startswith(b'\x89PNG\r\n\x1a\n'))
             or (suffix == 'webp' and data.startswith(b'RIFF') and data[8:12] == b'WEBP'))
    return (data, suffix) if valid else None


def reference_for(value):
    image = image_data(value)
    if image is None:
        return value
    data, suffix = image
    return f'/clip-thumb/{hashlib.sha256(data).hexdigest()}.{suffix}'


def favorite_identity(data):
    """Changing only thumbnail storage must not change a shared Saved clip's owner."""
    thumb = data.get('thumb')
    ref = reference_for(thumb)
    return {**data, 'thumb': ref} if ref != thumb else data


class ThumbnailStore:
    def __init__(self, directory):
        self.directory = Path(directory)

    def externalize(self, value):
        references, known = [], {}
        def convert(items, prefix):
            if not isinstance(items, list):
                return items
            result = []
            changed = False
            for i, item in enumerate(items):
                thumb = item.get('thumb') if isinstance(item, dict) else None
                if not isinstance(thumb, str):
                    result.append(item)
                    continue
                ref = known.get(thumb)
                if ref is None:
                    image = image_data(thumb)
                    if image is None:
                        result.append(item)
                        continue
                    data, suffix = image
                    name = f'{hashlib.sha256(data).hexdigest()}.{suffix}'
                    target = self.directory / name
                    self.directory.mkdir(parents=True, exist_ok=True)
                    if not target.is_file() or target.stat().st_size != len(data):
                        temporary = None
                        try:
                            with tempfile.NamedTemporaryFile(dir=self.directory, suffix='.part', delete=False) as out:
                                temporary = Path(out.name)
                                out.write(data)
                            temporary.replace(target)
                        finally:
                            if temporary is not None:
                                temporary.unlink(missing_ok=True)
                    ref = known[thumb] = f'/clip-thumb/{name}'
                changed = True
                result.append({**item, 'thumb': ref})
                references.append({'path': [*prefix, i, 'thumb'], 'url': ref})
            return result if changed else items
        if isinstance(value, list):
            return convert(value, []), references
        if not isinstance(value, dict):
            return value, references
        result = value
        for field in ('clips', 'bank', 'other'):
            items = value.get(field)
            converted = convert(items, [field])
            if converted is not items:
                result = {**result, field: converted}
        return result, references
