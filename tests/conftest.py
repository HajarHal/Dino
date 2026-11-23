from datetime import date

import pytest

from ica.domain import (
    CPExtraction, Deductible, Limit, LimitBasis, SourceRef, SubscribedGuarantee,
    VehicleInfo, Verification, VerificationStatus,
)
from ica.taxonomy import load_taxonomy

OK = Verification(status=VerificationStatus.VERIFIED, score=100)
BAD = Verification(status=VerificationStatus.QUOTE_NOT_FOUND, detail="citation introuvable")


@pytest.fixture(scope="session")
def tx():
    return load_taxonomy()


def src(doc="d", page=1, quote="citation de test", clause=None):
    return SourceRef(document_id=doc, page=page, quote=quote, clause_id=clause)


def sub(code, label=None, value=None, ded=None, ver=OK):
    return SubscribedGuarantee(
        label_raw=label or code, canonical_code=code, section="VEHICULE",
        insured_value=Limit(amount_mad=value, basis=LimitBasis.FIXED) if value is not None else None,
        deductible=ded, source=src("cp"), verification=ver,
    )


def make_cp(subscribed, complete=True, insurer="axa_maroc", product="axa_solution_auto", **vehicle):
    return CPExtraction(
        document_id="cp", insurer_id=insurer, product_id=product, period_start=date(2026, 1, 1), period_end=date(2026, 12, 31),
        vehicle=VehicleInfo(**vehicle), subscribed=subscribed, guarantee_list_complete=complete,
    )


@pytest.fixture(autouse=True)
def _no_real_llm_settings(monkeypatch):
    """Les tests ne lisent jamais la configuration réelle (.env chargé par ica.api)."""
    import os
    for k in list(os.environ):
        if k.startswith(("LLM_", "GEMINI_", "ANTHROPIC_", "PERPLEXITY_", "OPENAI_")):
            monkeypatch.delenv(k, raising=False)
