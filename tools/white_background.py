"""Met les photos du catalogue (assets/cars/*.jpg) sur fond blanc.

    pip install "rembg[cpu]"          (une fois ; le modèle est téléchargé au premier lancement)
    python tools/white_background.py

Les originaux sont gardés dans assets/cars/original/ (relancer le script repart toujours des originaux).
Les dimensions ne changent pas : les positions des pièces dans config/car_photos.yaml restent valables.
"""
import shutil
import sys
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from ica.background import on_white  # noqa: E402

CARS = ROOT / "assets" / "cars"
ORIG = CARS / "original"

if on_white(Image.new("RGB", (8, 8))) is None:
    sys.exit('rembg n\'est pas installé : pip install "rembg[cpu]"')
ORIG.mkdir(exist_ok=True)
for jpg in sorted(CARS.glob("*.jpg")):
    src = ORIG / jpg.name
    if not src.exists():
        shutil.copy2(jpg, src)
    img = Image.open(src).convert("RGB")
    out = on_white(img)
    assert out.size == img.size
    out.save(jpg, "JPEG", quality=90, optimize=True)
    print("fond blanc :", jpg.name)
