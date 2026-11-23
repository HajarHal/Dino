"""Explications visuelles : bibliothèque de textes, calcul de franchise, codes des clauses, rendu, non-régression."""
import json
import re
from datetime import date
from pathlib import Path

import pytest

from ica import cg_library, explain
from ica.codes import classify, codes, guarantee_code
from ica.coverage_view import dossier
from ica.extraction.cp_extractor import cp_from_drafts
from ica.extraction.schemas import CPDraft

from .conftest import make_cp, sub

ROOT = Path(__file__).resolve().parent.parent
COPY = json.loads((ROOT / "copy" / "fr.json").read_text(encoding="utf-8"))
FORBIDDEN = ["permet de", "garantit", "afin de", "en cas de sinistre", "il est important", "notamment", "ledit",
             "susvisé", "sinistre", "tiers", "vétusté", "souscrit"]
# Variables passées par le code (frontend/src/components/visual.tsx, copy.ts, ica/explain.py) à chaque texte.
VARS = {
    "ui.source": {"doc", "article", "page"}, "ui.source.ref": {"doc", "ref", "page"}, "ui.source.nopage": {"doc", "ref"},
    "ui.jusqua": {"montant"}, "f.FIXED": {"fixed"}, "f.PERCENT": {"percent", "base"},
    "f.PERCENT_MIN": {"percent", "base", "min"}, "f.PERCENT_MIN_MAX": {"percent", "base", "min", "max"},
    "f.example": {"amount", "you", "insurer"}, "unit.HOURS": {"n"}, "unit.DAYS": {"n"}, "unit.MONTHS": {"n"},
    "unit.YEARS": {"n"}, "fault.MY_CAR_PAID.value": {"montant"}, "fault.ME_PAID.value": {"montant"},
    "fault.PREMIUM_UP.value": {"pct"}, "fault.PREMIUM_UP.sub": {"pct_corp", "max"}, "fault.RECOURS.value": {"montant"},
    "fault.PREMIUM_DOWN.value": {"pct_down"}, "fault.PREMIUM_DOWN.sub": {"months"}, "contract.ends": {"date"},
    "contract.days_left": {"n"},
}


@pytest.fixture(scope="module")
def sample(tx):
    d = CPDraft.model_validate_json((ROOT / "samples" / "cp_atlantasanad_draft.json").read_text(encoding="utf-8"))
    return dossier(cp_from_drafts(d, d, document_id="cp", page=1, tx=tx), cg_library.load("atlantasanad"), tx,
                   today=date(2026, 6, 1))


# ---------------------------------------------------------------------------------------- 1. textes


def test_copy_has_no_legal_or_ai_wording():
    for key, text in COPY.items():
        assert not [w for w in FORBIDDEN if w in text.lower()], f"{key}: {text}"


def test_copy_lengths():
    words = lambda k: len([w for w in COPY[k].split() if re.search(r"\w", w)])  # « : » n'est pas un mot  # noqa: E731
    for k in COPY:
        if re.match(r"^(cov|ex)\.", k):
            assert words(k) <= 4, k
        if re.match(r"^(g\.\w+\.title|fault\.\w+\.title|options\.title|step\.\w+)$", k):
            assert words(k) <= 8, k
        if k.startswith("note."):
            assert words(k) <= 20, k


def test_variables_used_by_the_code_match_the_texts():
    in_copy = {k: set(re.findall(r"\{(\w+)\}", v)) for k, v in COPY.items() if "{" in v}
    assert in_copy == VARS


def test_codes_come_from_the_copy_file():
    assert codes("ex")[:3] == ("ALCOOL", "STUPEFIANTS", "PERMIS_INVALIDE")
    assert "MAIN_OEUVRE" in codes("cov") and "TIERS_IDENTIFIE" in codes("cond") and "PRESCRIPTION" in codes("delay")
    assert "MY_CAR_PAID" in codes("fault") and len(codes("g")) == 15
    assert guarantee_code("ALL_ACCIDENTS") == "DTA" and guarantee_code("GLASS") == "BRIS_GLACE"


def test_every_code_in_the_library_has_a_text():
    for iid in cg_library.registry():
        cg = cg_library.load(iid)
        for g in cg.guarantees.values():
            for fam, pairs in (("cov", g.cover_codes), ("ex", g.exclusion_codes), ("cond", g.condition_codes),
                               ("note", g.note_codes)):
                assert all(f"{fam}.{c}" in COPY for c, _ in pairs), (iid, g.code)
        for x in cg.sections["claim_steps"]:
            assert all(f"step.{c}" in COPY and f"step.{c}.sub" in COPY for c in x["codes"])
        for x in cg.sections["deadlines"]:
            assert not x.get("code") or (f"delay.{x['code']}" in COPY and x["n"] and x["unit"]), (iid, x)


# ---------------------------------------------------------------------------------------- 2. franchise


DTA = {"kind": "PERCENT_MIN", "percent": 5, "min": 1500, "max": None, "fixed": None, "base": "DAMAGE"}


@pytest.mark.parametrize("amount,f,plafond,expected", [
    (10000, DTA, 487000, (1500, 8500)),
    (50000, DTA, 487000, (2500, 47500)),
    (800, DTA, 487000, (800, 0)),
    (10000, {**DTA, "kind": "NONE"}, 487000, (0, 10000)),
    (100000, {**DTA, "kind": "PERCENT_MIN_MAX", "percent": 10, "min": 1000, "max": 3000}, 50000, (3000, 50000)),
    (5000, {**DTA, "kind": "FIXED", "fixed": 1000}, None, (1000, 4000)),
])
def test_franchise_split(amount, f, plafond, expected):
    assert explain.franchise_split(amount, f, plafond) == expected


# ---------------------------------------------------------------------------------------- 3. extraction


def test_unknown_code_is_rejected_and_the_clause_stays_verbatim(monkeypatch):
    assert classify({"code": "ex.ALCOOL", "text": "x"}, ("ex",)) == ("ex", ["ALCOOL"], "x")
    assert classify({"code": "ex.PNEUS_CREVES", "text": "Les pneus"}, ("ex",)) == (None, [], "Les pneus")
    assert classify({"code": "cov.MAIN_OEUVRE", "text": "x"}, ("ex",)) == (None, [], "x")  # mauvaise famille
    spec = {"source": {"pdf": "atlantasanad.pdf"}, "guarantees": {"GLASS": {
        "title": "Bris de Glaces",
        "not_covered": [{"code": "ex.PNEUS_CREVES", "text": "Les rayures et ébréchures"},
                        {"code": "ex.RAYURE_SANS_BRIS", "text": "Les rayures"}]}}}
    monkeypatch.setattr(cg_library, "_spec", lambda iid: spec)
    cg_library.load.cache_clear()
    try:
        g = cg_library.load("atlantasanad").guarantees["GLASS"]
        assert g.exclusion_codes == (("RAYURE_SANS_BRIS", "Les rayures"),)
        assert g.unclassified == ("Les rayures et ébréchures",)
    finally:
        cg_library.load.cache_clear()


# ---------------------------------------------------------------------------------------- 4. rendu


def test_missing_values_hide_the_element(tx):
    assert explain._tile("RECOURS", "scale", None, montant=None) is None
    cp = make_cp([sub("RC", value=50_000_000), sub("DEFENSE_RECOURS", value=None), sub("GLASS", value=None)],
                 insurer="atlantasanad", product=None)
    d = dossier(cp, cg_library.load("atlantasanad"), tx, today=date(2026, 6, 1))
    nf = [x["code"] for x in d["views"]["police:not_at_fault"]["who_pays"]["tiles"]]
    assert "RECOURS" not in nf  # plafond non indiqué : pas de tuile
    assert d["views"]["glass:at_fault"]["headline"]["plafond_dh"] is None
    assert d["views"]["glass:at_fault"]["who_pays"] is None  # bloc « responsable ou non » masqué


def test_sample_contract_acceptance(sample):
    police = sample["views"]["police:at_fault"]
    wind = police["parts"]["windshield"]
    assert wind["plafond_dh"] == 20000 and wind["franchise"]["kind"] == "NONE"  # « Jusqu'à 20 000 DH · Vous ne payez rien »
    h = police["headline"]
    assert h["gcode"] == "DTA" and explain.franchise_split(10000, h["franchise"], h["plafond_dh"]) == (1500, 8500)
    tiles = police["who_pays"]["tiles"]
    assert [x["code"] for x in tiles] == ["OTHER_PAID", "MY_CAR_PAID", "ME_PAID", "PREMIUM_UP"]
    assert tiles[3]["review"] and tiles[3]["vars"] == {"pct": 20, "pct_corp": 30, "max": 2.5}
    assert not police["notes"] or all("coefficient" not in t.get("label_key", "") for t in tiles)
    cg = sample["documents"]["cg"]
    presc = next(x for x in cg["timeline"]["items"] if x["code"] == "PRESCRIPTION")
    assert (presc["n"], presc["unit"], presc["source"]["article"]) == (2, "YEARS", "29")
    assert [x["code"] for x in cg["timeline"]["items"]][0] == "DECLARATION_VOL"  # du plus court au plus long
    assert [s["code"] for s in cg["steps"]["items"]][:2] == ["DECLARER", "INFOS"]
    assert cg["steps"]["items"][0]["delay"] == {"n": 5, "unit": "DAYS"}
    glass = next(r for r in cg["mine"] if r["code"] == "GLASS")
    assert [c["code"] for c in glass["cover_codes"]] == ["MAIN_OEUVRE", "JOINTS_KITS", "BRIS_SUITE_VOL"]
    assert glass["source"]["article"] == "10 et 40" and glass["source"]["page"] == 11


# ---------------------------------------------------------------------------------------- 5. non-régression


def test_same_screens_and_sections(sample):
    """Mêmes onglets, mêmes vues, mêmes sections qu'avant : seuls des champs ont été ajoutés."""
    assert [c["id"] for c in sample["cases"]][:9] == ["police", "driver", "glass", "theft", "passengers", "fire",
                                                      "nature", "assistance", "defense"]
    assert len([k for k in sample["views"] if not k.startswith("cp")]) == 18
    for v in sample["views"].values():
        assert {"case", "fault", "fault_relevant", "headline", "notes", "needs", "parts", "car", "items"} <= set(v)
    assert {"source", "insurer", "mine", "others", "deadlines", "claim_steps", "documents_needed", "fault",
            "compensation", "contract_life", "common_exclusions", "contacts"} <= set(sample["documents"]["cg"])
    assert {"contract", "status", "vehicle", "lines", "damage_example", "warnings"} <= set(sample["documents"]["cp"])
