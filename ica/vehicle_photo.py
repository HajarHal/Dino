"""Photo réelle du véhicule de l'assuré, avec les repères des parties (pare-brise, optiques…).

Sources, par ordre de préférence :
1. la photo de SA voiture, importée par l'assuré (aucun problème de droits, et c'est le vrai véhicule) ;
2. une photographie sous licence du fournisseur d'images configuré (imagin.studio, vue avant 3/4) ;
3. sinon, l'illustration paramétrique (gérée par l'interface).

Les repères sont des points normalisés (0..1, origine en haut à gauche) par partie du véhicule. Ils viennent
d'une détection par le modèle de vision, ou de positions par défaut pour une vue avant 3/4, et l'assuré peut
les déplacer. Un repère absent (partie non visible) n'est pas affiché : rien n'est placé au hasard.
"""
from __future__ import annotations

import io
import json
from pathlib import Path
from typing import Optional

from PIL import Image, ImageOps
from pydantic import BaseModel, Field, ValidationError

from .extraction.llm import LLMClient, LLMError, LLMFatalError, call_validated

# Parties qui peuvent porter une bulle sur une photo (le vol, protection globale, reste une pastille à part).
PHOTO_ZONES = ["windshield", "headlights", "mirrors", "front_bumper", "bodywork", "wheels", "side_windows",
               "engine_mechanics", "rear_window", "rear_bumper"]

# Vue avant 3/4 (avant à gauche) : moyenne des repères des photos du catalogue, utilisée si la détection échoue.
DEFAULT_ANCHORS: dict[str, Optional[list[float]]] = {
    "windshield": [0.44, 0.22], "headlights": [0.39, 0.52], "mirrors": [0.67, 0.32], "front_bumper": [0.17, 0.74],
    "bodywork": [0.75, 0.52], "wheels": [0.54, 0.76], "side_windows": [0.73, 0.22], "engine_mechanics": [0.26, 0.40],
}

MAX_SIDE = 1600


class _Detected(BaseModel):
    visible: bool = Field(description="true si l'image montre bien une voiture")
    points: dict[str, Optional[list[float]]] = Field(
        default_factory=dict, description="pour chaque identifiant de partie : [x, y] entre 0 et 1, ou null si non visible")


DETECT_SYSTEM = """Tu repères les parties visibles d'une voiture sur une photo. Pour chaque partie demandée, donne le point
le plus représentatif de cette partie, en coordonnées normalisées [x, y] (0 à 1, origine en haut à gauche de l'image).
Si une partie n'est pas visible sur la photo, renvoie null pour elle : ne devine jamais une position.
Réponds uniquement par un objet JSON conforme au schéma."""

LABELS = {
    "windshield": "pare-brise", "headlights": "phare avant (optique)", "mirrors": "rétroviseur extérieur",
    "bodywork": "carrosserie (portière ou aile)", "wheels": "roue", "front_bumper": "pare-chocs avant",
    "side_windows": "vitre latérale", "rear_window": "lunette arrière", "rear_bumper": "pare-chocs arrière",
    "engine_mechanics": "capot (moteur)",
}


def _clean(points: dict[str, Optional[list[float]]]) -> dict[str, Optional[list[float]]]:
    out: dict[str, Optional[list[float]]] = {}
    for z in PHOTO_ZONES:
        p = points.get(z)
        if isinstance(p, (list, tuple)) and len(p) == 2 and all(isinstance(v, (int, float)) and 0 <= v <= 1 for v in p):
            out[z] = [round(float(p[0]), 4), round(float(p[1]), 4)]
        else:
            out[z] = None
    return out


def detect_anchors(image: bytes, llm: Optional[LLMClient]) -> tuple[dict[str, Optional[list[float]]], str]:
    """(repères, origine) : « ai » si le modèle a répondu, sinon « default » (positions d'une vue avant 3/4)."""
    if llm is not None:
        wanted = "\n".join(f"- {z} : {LABELS[z]}" for z in PHOTO_ZONES)
        user = f"Parties à repérer (identifiant : description) :\n{wanted}\n\nSchéma JSON : {{\"visible\": bool, \"points\": {{\"<identifiant>\": [x, y] | null}}}}"
        try:
            d = call_validated(llm, _Detected, system=DETECT_SYSTEM, user=user, images=[image])
            pts = _clean(d.points)
            if d.visible and sum(p is not None for p in pts.values()) >= 3:
                return pts, "ai"
        except LLMFatalError:
            raise
        except (LLMError, ValidationError):
            pass
    return _clean(DEFAULT_ANCHORS), "default"


def normalize_photo(data: bytes) -> bytes:
    """Redresse selon l'EXIF, réduit à 1600 px, met la voiture sur fond blanc (si ``rembg`` est installé) et
    ré-encode en JPEG (supprime les métadonnées, dont la position GPS)."""
    from .background import on_white
    img = ImageOps.exif_transpose(Image.open(io.BytesIO(data))).convert("RGB")
    img.thumbnail((MAX_SIDE, MAX_SIDE), Image.LANCZOS)
    img = on_white(img) or img
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=88, optimize=True)
    return buf.getvalue()


class PhotoStore:
    """Une photo par CP : <dossier>/vehicle-<cp>.jpg + .json (repères et leur origine)."""

    def __init__(self, folder: Path):
        self.folder = folder
        folder.mkdir(parents=True, exist_ok=True)

    def _paths(self, cp_id: str) -> tuple[Path, Path]:
        safe = "".join(c for c in cp_id if c.isalnum())
        return self.folder / f"vehicle-{safe}.jpg", self.folder / f"vehicle-{safe}.json"

    def save(self, cp_id: str, jpeg: bytes, anchors: dict, detected_by: str) -> dict:
        img, meta = self._paths(cp_id)
        img.write_bytes(jpeg)
        info = {"anchors": anchors, "detected_by": detected_by}
        meta.write_text(json.dumps(info), encoding="utf-8")
        return info

    def load(self, cp_id: str) -> Optional[dict]:
        img, meta = self._paths(cp_id)
        if not img.exists():
            return None
        info = json.loads(meta.read_text(encoding="utf-8")) if meta.exists() else {"anchors": _clean(DEFAULT_ANCHORS), "detected_by": "default"}
        info["anchors"] = _clean(info.get("anchors", {}))
        return info

    def image(self, cp_id: str) -> Optional[bytes]:
        img, _ = self._paths(cp_id)
        return img.read_bytes() if img.exists() else None

    def set_anchors(self, cp_id: str, anchors: dict) -> Optional[dict]:
        info = self.load(cp_id)
        if info is None:
            return None
        info = {"anchors": _clean({**info["anchors"], **anchors}), "detected_by": "user"}
        self._paths(cp_id)[1].write_text(json.dumps(info), encoding="utf-8")
        return info

    def delete(self, cp_id: str) -> None:
        for p in self._paths(cp_id):
            p.unlink(missing_ok=True)
