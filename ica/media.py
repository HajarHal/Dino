"""Fichiers : variables d'environnement, préparation des photos et scans de CP pour la lecture."""
from __future__ import annotations

import io
import os
import re
from pathlib import Path
from typing import Optional

import pymupdf
from PIL import Image


def load_env(path: str | Path = ".env") -> None:
    """Charge un fichier .env minimal (CLE=valeur) sans dépendance externe."""
    p = Path(path)
    if not p.exists():
        return
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


TARGET_SIDE = 2400  # côté long visé : les modèles de vision lisent mieux les petits caractères d'un tableau agrandi
MAX_UPSCALE = 3.0


def enhance_for_reading(img: "Image.Image", target_side: int = TARGET_SIDE) -> "Image.Image":
    """Prépare une photo ou un scan de CP pour la lecture.

    Les CP arrivent souvent compressées par WhatsApp (≈ 720 × 960 px), de travers, ombrées.
    On redresse selon l'EXIF, on agrandit (Lanczos) jusqu'à ``target_side``, on étire le contraste
    et on renforce légèrement la netteté. Aucun pixel n'est inventé au sens du contenu : c'est un
    simple rééchantillonnage, qui donne plus de « tuiles » au modèle pour les petits chiffres.
    """
    from PIL import ImageFilter, ImageOps

    img = ImageOps.exif_transpose(img).convert("RGB")
    long_side = max(img.size)
    scale = min(MAX_UPSCALE, target_side / long_side)
    if abs(scale - 1.0) > 0.05:
        img = img.resize((round(img.width * scale), round(img.height * scale)), Image.LANCZOS)
    img = ImageOps.autocontrast(img, cutoff=1)
    return img.filter(ImageFilter.UnsharpMask(radius=2, percent=70, threshold=3))


def to_jpeg_pages(data: bytes, filename: str, max_side: int = TARGET_SIDE) -> list[bytes]:
    """Convertit une image (jpg/png/heic lisible par Pillow) ou un PDF en JPEG améliorés, un par page."""
    ext = Path(filename).suffix.lower().lstrip(".") or "jpg"
    pil_pages: list[Image.Image] = []
    if ext == "pdf":
        doc = pymupdf.open(stream=data, filetype="pdf")
        for pg in doc:  # scans PDF : rendu haute définition (≈ 290 dpi pour un A4)
            scale = max_side / max(pg.rect.width, pg.rect.height)
            pix = pg.get_pixmap(matrix=pymupdf.Matrix(scale, scale))
            pil_pages.append(Image.open(io.BytesIO(pix.tobytes("png"))))
        doc.close()
    else:
        try:
            pil_pages.append(Image.open(io.BytesIO(data)))
        except Exception:  # format inconnu de Pillow : repli sur PyMuPDF
            doc = pymupdf.open(stream=data, filetype=ext)
            pil_pages += [Image.open(io.BytesIO(pg.get_pixmap().tobytes("png"))) for pg in doc]
            doc.close()
    out: list[bytes] = []
    for img in pil_pages:
        buf = io.BytesIO()
        enhance_for_reading(img, max_side).save(buf, "JPEG", quality=92, optimize=True)
        out.append(buf.getvalue())
    return out


def cp_page_images(storage_path: str | Path, page_files: Optional[list[str]] = None) -> list[bytes]:
    """Images des pages d'une CP. Les anciens imports stockaient les JPEG concaténés dans un .bin :
    ils sont redécoupés sur les marqueurs de début d'image JPEG."""
    if page_files:
        return [Path(p).read_bytes() for p in page_files if Path(p).exists()]
    p = Path(storage_path)
    if not p.exists():
        return []
    blob = p.read_bytes()
    if not blob.startswith(b"\xff\xd8\xff"):
        return []
    starts = [m.start() for m in re.finditer(rb"\xff\xd8\xff[\xe0-\xef\xdb]", blob)]
    parts = [blob[a:b] for a, b in zip(starts, starts[1:] + [len(blob)])]
    out = [x for x in parts if x.rstrip(b"\x00").endswith(b"\xff\xd9")]
    return out or [blob]
