"""Create the local workspace folders without touching existing media or projects."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
# Everything the bench downloads, makes or remembers lives under workspace/, so the code sits beside it untouched.
FOLDERS = (
    "workspace/clips/.proxy", "workspace/clips/.cuts", "workspace/temp", "workspace/broll", "workspace/audio",
    "workspace/music", "workspace/projects", "workspace/shorts", "workspace/data", "workspace/channel",
    "scripts/models",
)


def initialize(root=ROOT):
    for folder in FOLDERS:
        (root / folder).mkdir(parents=True, exist_ok=True)
    avatar = root / "workspace/channel/avatar.png"
    if not avatar.exists():
        from PIL import Image, ImageDraw
        image = Image.new("RGB", (256, 256), (25, 25, 28))
        draw = ImageDraw.Draw(image)
        draw.ellipse((88, 46, 168, 126), fill=(160, 160, 165))
        draw.ellipse((48, 136, 208, 296), fill=(160, 160, 165))
        # Exclusive creation protects an avatar supplied during setup.
        try:
            with avatar.open("xb") as target:
                image.save(target, format="PNG")
        except FileExistsError:
            pass


if __name__ == "__main__":
    initialize()
    print("Local workspace folders are ready.")
