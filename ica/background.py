"""Fond blanc derrière la voiture (photos du catalogue et photo de l'assuré).

Le détourage utilise ``rembg`` (modèle de segmentation local, sans envoi de la photo) s'il est installé :
    pip install "rembg[cpu]"
Sans lui, la photo reste telle quelle. L'image garde ses dimensions : les positions des pièces (anchors)
restent valables.
"""
from __future__ import annotations

from functools import lru_cache
from typing import Optional

from PIL import Image


@lru_cache(maxsize=1)
def _session():
    try:
        from rembg import new_session
    except ImportError:
        return None
    return new_session("isnet-general-use")


def available() -> bool:
    return _session() is not None


def on_white(img: Image.Image) -> Optional[Image.Image]:
    """La voiture détourée sur fond blanc, même taille ; None si le détourage n'est pas disponible."""
    session = _session()
    if session is None:
        return None
    from rembg import remove
    cut = remove(img.convert("RGB"), session=session, post_process_mask=True)
    white = Image.new("RGB", cut.size, (255, 255, 255))
    white.paste(cut, mask=cut.getchannel("A"))
    return white
