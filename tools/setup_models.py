"""Fetch the optional person-tracking model without overwriting an existing model."""
import shutil
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def install():
    target = ROOT / "scripts/models/yolo11n.pt"
    if target.is_file():
        print("Keeping existing person-tracking model.")
        return
    from ultralytics.utils.downloads import attempt_download_asset
    target.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        downloaded = Path(attempt_download_asset(str(Path(tmp) / target.name)))
        if not downloaded.is_file():
            raise RuntimeError("Person-tracking model download failed; rerun ./setup.sh --ai")
        try:
            with target.open("xb") as output, downloaded.open("rb") as source:
                shutil.copyfileobj(source, output)
        except FileExistsError:
            pass
    print("Person-tracking model is ready.")


if __name__ == "__main__":
    install()
