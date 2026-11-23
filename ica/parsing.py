"""Normalisation de texte et analyse déterministe des montants / franchises / plafonds.

Principe : le LLM ne renvoie que des chaînes brutes (« 5 % /Dom. min 1500 »). Les nombres sont
extraits ici, par du code, ce qui permet aussi de re-vérifier une valeur à partir de sa citation.
"""
from __future__ import annotations

import re
import unicodedata
from typing import Optional

from .domain import Deductible, Limit, LimitBasis


def normalize(text: str) -> str:
    """Minuscules, sans accents, ponctuation -> espaces, espaces compactés."""
    text = unicodedata.normalize("NFKD", text)
    text = "".join(c for c in text if not unicodedata.combining(c))
    text = text.lower()
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


# Montant français : « 50 000 000,00 », « 487 000,00 », « 15.000 », « 3000 », « 5 000 »
_AMOUNT = r"(\d{1,3}(?:[ \u00a0\u202f.]\d{3})+(?:,\d+)?|\d+(?:,\d+)?)"
_AMOUNT_RE = re.compile(_AMOUNT)


def _to_float(token: str) -> float:
    token = token.replace("\u00a0", "").replace("\u202f", "").replace(" ", "")
    if "," in token:
        token = token.replace(".", "").replace(",", ".")
    elif re.fullmatch(r"\d{1,3}(\.\d{3})+", token):
        token = token.replace(".", "")
    return float(token)


def parse_amount(text: str) -> Optional[float]:
    """Premier montant trouvé dans le texte, ou None."""
    m = _AMOUNT_RE.search(text or "")
    return _to_float(m.group(1)) if m else None


def all_amounts(text: str) -> list[float]:
    return [_to_float(m.group(1)) for m in _AMOUNT_RE.finditer(text or "")]


_PERCENT_RE = re.compile(r"(\d+(?:[.,]\d+)?)\s*%")
_MIN_RE = re.compile(r"\bmin(?:imum)?\b\.?\s*:?\s*" + _AMOUNT, re.I)
_MAX_RE = re.compile(r"\bmax(?:imum)?\b\.?\s*:?\s*" + _AMOUNT, re.I)


def parse_deductible(raw: str) -> Deductible:
    """« 5 % /Dom. min 1500 » -> percent=5, minimum_mad=1500 ; « 0 /Dom » -> fixed_mad=0.

    Une franchise dont le texte renvoie ailleurs (« Voir franchise aux Conditions Particulières »)
    produit un objet sans valeur numérique : elle n'est jamais devinée.
    """
    text = (raw or "").strip()
    d = Deductible(raw=text)
    if not text:
        return d
    pm = _PERCENT_RE.search(text)
    if pm:
        d.percent = float(pm.group(1).replace(",", "."))
    mn = _MIN_RE.search(text)
    if mn:
        d.minimum_mad = _to_float(mn.group(1))
    mx = _MAX_RE.search(text)
    if mx:
        d.maximum_mad = _to_float(mx.group(1))
    if not pm and not mn and not mx:
        low = normalize(text)
        if "voir franchise" in low or "conditions particulieres" in low:
            return d
        amount = parse_amount(text)
        if amount is not None:
            d.fixed_mad = amount
    if "dom" in normalize(text).split():
        d.basis = "DAMAGE"
    return d


_BASIS_PATTERNS: list[tuple[str, LimitBasis]] = [
    ("valeur venale", LimitBasis.MARKET_VALUE),
    ("valeur a neuf", LimitBasis.NEW_VALUE),
    ("valeur assuree", LimitBasis.INSURED_VALUE),
    ("capital assure", LimitBasis.INSURED_VALUE),
    ("illimite", LimitBasis.UNLIMITED),
    ("conditions particulieres", LimitBasis.SEE_CP),
]


def parse_limit(raw: str) -> Limit:
    """Plafond / valeur assurée à partir d'un texte brut. Ne devine jamais un montant absent."""
    text = (raw or "").strip()
    lim = Limit(raw=text)
    low = normalize(text)
    amount = parse_amount(text)
    if amount is not None:
        lim.amount_mad = amount
        lim.basis = LimitBasis.FIXED
        return lim
    for needle, basis in _BASIS_PATTERNS:
        if needle in low:
            lim.basis = basis
            return lim
    lim.basis = LimitBasis.OTHER
    return lim
