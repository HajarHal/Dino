"""Étape 2 : classement par IA d'une garantie que les règles n'ont pas reconnue, sous contrôle.

Les règles passent toujours d'abord (alias, libellé proche, mots-clés : ica/taxonomy.py). Ce module ne traite
que les libellés restés inconnus, et seulement pour un assureur dont les CG sont intégrées :

1. Choix fermé : le modèle choisit un code dans la liste des garanties connues, ou « aucun ».
2. Preuve : il doit citer un passage des CG de l'assureur. Le passage est cherché mot pour mot dans le PDF
   (même contrôle que la bibliothèque) ; introuvable, trop court, ou confiance faible -> refusé, la ligne
   reste « À vérifier ».
3. Mémoire : la réponse est enregistrée (<données>/label_classifications.json). Un même libellé chez un même
   assureur reçoit toujours la même réponse ; le modèle n'est appelé qu'une fois.
4. Validation : l'assuré confirme ou refuse (« Correct ? ») ; un refus remet la ligne en « À vérifier ».
   Les classements confirmés sont à reporter dans config/taxonomy.yaml (python tools/unrecognised.py).

Seul le libellé de garantie et des pages des CG publiques sont envoyés au modèle : aucune donnée personnelle.
"""
from __future__ import annotations

import json
import re
import threading
from datetime import date
from pathlib import Path
from typing import Literal, Optional

import yaml
from pydantic import BaseModel

from . import cg_library
from .extraction.llm import LLMClient, LLMError, call_validated
from .parsing import normalize
from .taxonomy import Taxonomy

FILE = "label_classifications.json"
MIN_QUOTE = 25  # caractères (lettres et chiffres) : une citation plus courte ne prouve rien
MAX_PAGES = 3
STOP = {"garantie", "garanties", "assurance", "contrat", "les", "des", "du", "de", "la", "le", "et", "en", "aux", "au",
        "par", "pour", "avec", "sans", "sur", "dans", "plus", "auto", "automobile", "vehicule", "option"}
_lock = threading.Lock()


class Decision(BaseModel):
    code: Optional[str] = None
    quote: Optional[str] = None
    page: Optional[int] = None
    confidence: Literal["HIGH", "MEDIUM", "LOW"] = "LOW"


SYSTEM = """Tu classes UNE garantie lue sur des Conditions Particulières d'assurance auto marocaine.
Règles absolues :
1. Choisis un code dans la liste fournie, et uniquement dans cette liste. Si aucun ne correspond clairement,
   renvoie code = null. N'invente jamais de code.
2. Justifie ton choix par une citation EXACTE (copiée mot pour mot) des pages des Conditions Générales fournies,
   qui décrit cette garantie. Pas de citation exacte possible -> code = null.
3. page = numéro de la page d'où vient la citation.
4. confidence = HIGH seulement si la citation nomme clairement la même garantie ; sinon MEDIUM ou LOW.
5. Réponds uniquement par un objet JSON : {"code": ..., "quote": ..., "page": ..., "confidence": ...}."""


# --------------------------------------------------------------------------------------------- mémoire


def key(insurer_id: Optional[str], label: str) -> str:
    return f"{insurer_id or 'other'}|{normalize(label)}"


def load(folder: Path) -> dict:
    p = folder / FILE
    try:
        return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}
    except (OSError, ValueError):
        return {}


def _save(folder: Path, data: dict) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    (folder / FILE).write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")


def overrides(folder: Path, insurer_id: Optional[str]) -> dict[str, dict]:
    """Classements utilisables pour cet assureur : {libellé normalisé: décision}, hors refusés et inconnus."""
    prefix = f"{insurer_id or 'other'}|"
    return {k[len(prefix):]: v for k, v in load(folder).items()
            if k.startswith(prefix) and v.get("status") in ("suggested", "confirmed") and v.get("code")}


def set_decision(folder: Path, insurer_id: Optional[str], label: str, decision: Literal["confirm", "reject"]) -> dict:
    with _lock:
        data = load(folder)
        e = data.get(key(insurer_id, label))
        if not e or not e.get("code"):
            raise KeyError(label)
        e["status"] = "confirmed" if decision == "confirm" else "rejected"
        e["decided_on"] = date.today().isoformat()
        _save(folder, data)
        return e


def pending(folder: Path, insurer_id: Optional[str], labels: list[str]) -> list[str]:
    known = load(folder)
    return [l for l in dict.fromkeys(labels) if key(insurer_id, l) not in known]


# --------------------------------------------------------------------------------------------- classement


def allowed_codes(tx: Taxonomy) -> dict[str, str]:
    base = yaml.safe_load((cg_library.LIB_DIR / "base.yaml").read_text(encoding="utf-8"))["guarantees"]
    return {c: tx.label_fr(c) for c in base if c in tx.guarantees}


def _pages(pdf: str) -> dict[int, str]:
    cg_library.source_text(pdf)  # crée le texte s'il manque
    raw = (cg_library.TEXT_DIR / (Path(pdf).stem + ".txt")).read_text(encoding="utf-8")
    parts = re.split(r"\n\n=== Page (\d+) ===\n", raw)[1:]
    return {int(parts[i]): re.sub(r"\s+", " ", parts[i + 1]).strip() for i in range(0, len(parts), 2)}


def candidate_pages(pdf: str, label: str) -> dict[int, str]:
    """Pages des CG qui contiennent des mots du libellé (sans IA). Aucune -> on n'appelle pas le modèle."""
    words = {w for w in normalize(label).split() if len(w) >= 4 and w not in STOP}
    if not words:
        return {}
    scored = []
    for n, text in _pages(pdf).items():
        norm = f" {normalize(text)} "
        score = sum(norm.count(f" {w}") for w in words)
        if score:
            scored.append((score, n))
    top = sorted(scored, reverse=True)[:MAX_PAGES]
    pages = _pages(pdf)
    return {n: pages[n] for _, n in sorted(top, key=lambda x: x[1])}


def _quote_page(pdf: str, quote: str) -> Optional[int]:
    q = cg_library.compact(quote)
    return next((n for n, t in _pages(pdf).items() if q in cg_library.compact(t)), None)


def classify(llm: LLMClient, tx: Taxonomy, insurer_id: str, label: str) -> dict:
    """Décision vérifiée pour un libellé ; ne lève pas d'exception (une erreur donne « unknown »)."""
    cg = cg_library.load(insurer_id)
    base = {"label": label, "insurer": insurer_id, "on": date.today().isoformat(), "code": None,
            "quote": None, "page": None, "confidence": None}
    if not cg.pdf:
        return base | {"status": "unknown", "reason": "CG de l'assureur non intégrées"}
    pages = candidate_pages(cg.pdf, label)
    if not pages:
        return base | {"status": "unknown", "reason": "aucune page des CG ne mentionne ce libellé"}
    codes = allowed_codes(tx)
    user = (f"Libellé lu sur la CP : « {label} »\nAssureur : {cg.label}\n\nCodes autorisés :\n"
            + "\n".join(f"- {c} : {l}" for c, l in codes.items())
            + "\n\nPages des Conditions Générales :\n"
            + "\n\n".join(f"=== Page {n} ===\n{t}" for n, t in pages.items()))
    try:
        d = call_validated(llm, Decision, system=SYSTEM, user=user)
    except LLMError as e:
        return base | {"status": "unknown", "reason": f"modèle indisponible : {str(e)[:120]}"}
    out = base | {"code": d.code, "quote": d.quote, "confidence": d.confidence}
    if d.code is None:
        return out | {"status": "unknown", "reason": "le modèle n'a reconnu aucune garantie"}
    if d.code not in codes:
        return out | {"code": None, "status": "unknown", "reason": f"code hors liste : {d.code}"}
    if not d.quote or len(cg_library.compact(d.quote)) < MIN_QUOTE:
        return out | {"status": "unknown", "reason": "citation absente ou trop courte"}
    page = _quote_page(cg.pdf, d.quote)
    if page is None:
        return out | {"status": "unknown", "reason": "citation introuvable dans le PDF des CG"}
    if d.confidence == "LOW":
        return out | {"page": page, "status": "unknown", "reason": "confiance faible"}
    return out | {"page": page, "status": "suggested", "model_page": d.page}


def classify_and_store(folder: Path, llm: LLMClient, tx: Taxonomy, insurer_id: str, labels: list[str]) -> None:
    for label in pending(folder, insurer_id, labels):
        decision = classify(llm, tx, insurer_id, label)
        with _lock:
            data = load(folder)
            data.setdefault(key(insurer_id, label), decision)
            _save(folder, data)
