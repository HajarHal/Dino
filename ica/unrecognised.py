"""Journal des libellés de garantie lus sur des CP mais absents de config/taxonomy.yaml.

Fichier : <données>/unrecognised_labels.json, un enregistrement par libellé (comparé sans accents ni casse) :
le libellé tel qu'imprimé, l'assureur, le nombre de contrats où il apparaît, première et dernière date.
Seuls des noms de garanties y figurent, jamais de données personnelles.

Pour traiter un libellé : l'ajouter aux « aliases » de la bonne garantie dans config/taxonomy.yaml (et, si
c'est une nouvelle garantie, ajouter son extrait des CG dans config/cg_library/<assureur>.yaml).
Lister : python tools/unrecognised.py
"""
from __future__ import annotations

import json
import threading
from datetime import date
from pathlib import Path
from typing import Iterable, Optional

from .parsing import normalize

FILE = "unrecognised_labels.json"
_lock = threading.Lock()


def load(folder: Path) -> dict:
    p = folder / FILE
    try:
        return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}
    except (OSError, ValueError):
        return {}


def record(folder: Path, labels: Iterable[str], insurer_id: Optional[str], contract_id: str) -> None:
    """Ajoute les libellés non reconnus d'un contrat (un contrat n'est compté qu'une fois par libellé)."""
    labels = [l for l in labels if l and l.strip()]
    if not labels:
        return
    today = date.today().isoformat()
    with _lock:
        data = load(folder)
        changed = False
        for label in labels:
            key = normalize(label)
            e = data.setdefault(key, {"label": label.strip(), "insurers": [], "contracts": [], "first_seen": today})
            if insurer_id and insurer_id not in e["insurers"]:
                e["insurers"].append(insurer_id)
                changed = True
            if contract_id not in e["contracts"]:
                e["contracts"].append(contract_id)
                e["last_seen"] = today
                changed = True
        if changed:
            folder.mkdir(parents=True, exist_ok=True)
            (folder / FILE).write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
