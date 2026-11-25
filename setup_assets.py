"""One-time download of free assets: Inter + Inter Display and Instrument Serif fonts (OFL) and the
YuNet face detector (Apache-2.0)."""
from __future__ import annotations

import io
import sys
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
FONTS = ROOT / "assets" / "fonts"
MODELS = ROOT / "assets" / "models"

INTER_ZIP = "https://github.com/rsms/inter/releases/download/v4.1/Inter-4.1.zip"
WANTED = ["Inter-Bold.ttf", "Inter-SemiBold.ttf", "Inter-Medium.ttf", "Inter-Black.ttf",
          "InterDisplay-Medium.ttf", "InterDisplay-SemiBold.ttf", "InterDisplay-Bold.ttf"]
# From the Google Fonts repo: Instrument Serif (headlines on the Engine A / B "paper" slides),
# Newsreader (Engine A's paragraph slides) and Bricolage Grotesque (Engine D / E quiz slides).
GF = "https://github.com/google/fonts/raw/main/ofl/"
SERIF = {"InstrumentSerif-Regular.ttf": "instrumentserif/InstrumentSerif-Regular.ttf",
         "InstrumentSerif-Italic.ttf": "instrumentserif/InstrumentSerif-Italic.ttf",
         "InstrumentSerif-OFL.txt": "instrumentserif/OFL.txt",
         "Newsreader.ttf": "newsreader/Newsreader%5Bopsz,wght%5D.ttf",
         "Newsreader-OFL.txt": "newsreader/OFL.txt",
         "BricolageGrotesque.ttf": "bricolagegrotesque/BricolageGrotesque%5Bopsz,wdth,wght%5D.ttf",
         "BricolageGrotesque-OFL.txt": "bricolagegrotesque/OFL.txt"}
YUNET_URLS = [
    "https://media.githubusercontent.com/media/opencv/opencv_zoo/main/models/face_detection_yunet/face_detection_yunet_2023mar.onnx",
    "https://github.com/opencv/opencv_zoo/raw/main/models/face_detection_yunet/face_detection_yunet_2023mar.onnx",
]
YUNET_FILE = MODELS / "face_detection_yunet_2023mar.onnx"


def fetch(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "synergia-setup"})
    with urllib.request.urlopen(req, timeout=120) as r:
        return r.read()


def setup_fonts() -> None:
    FONTS.mkdir(parents=True, exist_ok=True)
    for name, remote in SERIF.items():
        if not (FONTS / name).exists():
            print(f"↓ {name}")
            (FONTS / name).write_bytes(fetch(GF + remote))
    if all((FONTS / f).exists() for f in WANTED):
        print("✓ fonts already present")
        return
    print("↓ downloading Inter font family…")
    data = fetch(INTER_ZIP)
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        names = z.namelist()
        for want in WANTED:
            match = next((n for n in names if n.endswith("/" + want) and "ttf" in n.lower()), None)
            if not match:
                print(f"  ! {want} not found in archive")
                continue
            (FONTS / want).write_bytes(z.read(match))
            print(f"  ✓ {want}")
        lic = next((n for n in names if n.upper().endswith("LICENSE.TXT")), None)
        if lic:
            (FONTS / "Inter-LICENSE.txt").write_bytes(z.read(lic))


def setup_yunet() -> None:
    MODELS.mkdir(parents=True, exist_ok=True)
    if YUNET_FILE.exists() and YUNET_FILE.stat().st_size > 100_000:
        print("✓ YuNet model already present")
        return
    for url in YUNET_URLS:
        try:
            print("↓ downloading YuNet face detector…")
            data = fetch(url)
            if len(data) > 100_000:  # not an LFS pointer
                YUNET_FILE.write_bytes(data)
                print("  ✓ face_detection_yunet_2023mar.onnx")
                return
        except Exception as e:  # noqa: BLE001
            print(f"  ! {url}: {e}")
    print("  ✗ could not download YuNet; Engine C will fall back to centre crop.")


if __name__ == "__main__":
    try:
        setup_fonts()
        setup_yunet()
    except Exception as e:  # noqa: BLE001
        print(f"Setup failed: {e}")
        sys.exit(1)
    print("Done.")
