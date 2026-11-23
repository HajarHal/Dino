"""Photo réelle du véhicule de l'assuré pour « Ma couverture ».

Ordre de choix : photo de SA voiture (importée) > modèle choisi par l'assuré > modèle lu sur la CP >
même marque > même type de carrosserie. Les photos du catalogue (config/car_photos.yaml) sont sous licence
libre, leur auteur est toujours affiché. Quand le modèle n'est pas certain, la photo est présentée comme
« photo d'illustration », jamais comme la voiture de l'assuré.
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Optional

import yaml

from .domain import VehicleInfo
from .parsing import normalize

ROOT = Path(__file__).resolve().parent.parent
CATALOG = ROOT / "config" / "car_photos.yaml"
PHOTO_DIR = ROOT / "assets" / "cars"

BODY_WORDS = {"suv": "suv", "4x4": "suv", "tout terrain": "suv", "berline": "berline", "ci": "berline",
              "break": "monospace", "monospace": "monospace", "citadine": "citadine", "hayon": "compacte"}


@lru_cache(maxsize=1)
def catalog() -> dict:
    return yaml.safe_load(CATALOG.read_text(encoding="utf-8"))


def models() -> list[dict]:
    return [{"key": k, "make": v["make"], "model": v["model"]} for k, v in catalog()["photos"].items()]


def _words(s: Optional[str]) -> str:
    return f" {normalize(s or '')} "


def match(v: Optional[VehicleInfo]) -> tuple[Optional[str], str]:
    """(clé du catalogue, précision) — précision : « model », « make », « body » ou « none »."""
    photos = catalog()["photos"]
    if v is None:
        return None, "none"
    make = _words(v.make)
    text = _words(" ".join(x for x in (v.model, v.version, v.raw_designation) if x))
    same_make = [k for k, p in photos.items() if normalize(p["make"]) in make or normalize(p["make"].split("-")[0]) in make]
    for k in same_make or photos:
        if any(f" {normalize(a)} " in text for a in photos[k]["aliases"]):
            return k, "model"
    if same_make:
        return same_make[0], "make"
    body = next((b for w, b in BODY_WORDS.items() if f" {w} " in _words(v.body_type)), None)
    if body:
        return catalog()["fallback_by_body"][body], "body"
    return None, "none"


def photo_for(v: Optional[VehicleInfo], chosen_key: Optional[str] = None) -> dict:
    photos = catalog()["photos"]
    if chosen_key in photos:
        key, how = chosen_key, "chosen"
    else:
        key, how = match(v)
    if key is None:
        key, how = catalog()["fallback_by_body"]["berline"], "none"
    p = photos[key]
    exact = how in ("chosen", "model")
    return {
        "source": "catalog", "key": key, "url": f"/api/cars/{key}.jpg", "anchors": p["anchors"],
        "credit": p["credit"], "credit_url": p["source"], "exact": exact,
        "label": f"{p['make']} {p['model']}" if exact else "Photo d'illustration",
    }
