"""Porte de vérification : aucun fait extrait n'est « vérifié » sans preuve dans le document.

Deux contrôles indépendants du LLM :
1. la citation doit exister dans le texte de la page citée (ou à défaut ailleurs dans le document) ;
2. chaque valeur numérique extraite (montant, pourcentage) doit figurer dans cette citation.

Un échec ne supprime ni ne « corrige » jamais le fait : il le marque, et le moteur de règles décide.
"""
from __future__ import annotations

from typing import Iterable, Optional

from rapidfuzz import fuzz

from .domain import Verification, VerificationStatus
from .parsing import all_amounts, normalize

QUOTE_THRESHOLD = 90.0


def _score(needle: str, haystack: str) -> float:
    if not needle or not haystack:
        return 0.0
    if needle in haystack:
        return 100.0
    return float(fuzz.partial_ratio(needle, haystack))


def verify_quote(quote: str, page_texts: dict[int, str], cited_page: int, threshold: float = QUOTE_THRESHOLD) -> Verification:
    """Cherche ``quote`` sur ``cited_page`` puis sur les pages voisines, puis dans tout le document."""
    needle = normalize(quote)
    if len(needle) < 8:
        return Verification(status=VerificationStatus.QUOTE_NOT_FOUND, score=0.0, detail="citation trop courte pour être vérifiée")
    norm_pages = {p: normalize(t) for p, t in page_texts.items()}

    def found(page: int) -> Optional[float]:
        s = _score(needle, norm_pages.get(page, ""))
        return s if s >= threshold else None

    s = found(cited_page)
    if s is not None:
        return Verification(status=VerificationStatus.VERIFIED, score=s, page_found=cited_page)
    best_page, best_score = None, 0.0
    ordered = [cited_page - 1, cited_page + 1] + [p for p in norm_pages if abs(p - cited_page) > 1]
    for p in ordered:
        sc = _score(needle, norm_pages.get(p, ""))
        if sc > best_score:
            best_page, best_score = p, sc
        if sc >= threshold:
            break
    if best_page is not None and best_score >= threshold:
        return Verification(
            status=VerificationStatus.VERIFIED, score=best_score, page_found=best_page,
            detail=f"citation trouvée page {best_page} et non page {cited_page}",
        )
    return Verification(
        status=VerificationStatus.QUOTE_NOT_FOUND, score=best_score,
        detail="citation introuvable dans le document : fait non confirmé",
    )


def verify_numbers(values: Iterable[Optional[float]], quote: str) -> Verification:
    """Chaque valeur non nulle doit apparaître (montant ou pourcentage) dans la citation."""
    wanted = [v for v in values if v is not None and v != 0]
    if not wanted:
        return Verification(status=VerificationStatus.VERIFIED, score=100.0, detail="aucune valeur numérique à contrôler")
    present = set(all_amounts(quote))
    missing = [v for v in wanted if float(v) not in present]
    if missing:
        return Verification(
            status=VerificationStatus.VALUE_MISMATCH, score=0.0,
            detail=f"valeur(s) {missing} absente(s) de la citation",
        )
    return Verification(status=VerificationStatus.VERIFIED, score=100.0)


def combine(*checks: Verification) -> Verification:
    """Le pire résultat l'emporte."""
    for status in (VerificationStatus.VALUE_MISMATCH, VerificationStatus.QUOTE_NOT_FOUND):
        for c in checks:
            if c.status == status:
                return c
    verified = [c for c in checks if c.status == VerificationStatus.VERIFIED]
    if verified and len(verified) == len(checks):
        return next((c for c in verified if c.page_found is not None), verified[0])
    return Verification(status=VerificationStatus.NOT_CHECKED)
