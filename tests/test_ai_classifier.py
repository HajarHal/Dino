"""Étape 2 : l'IA classe une garantie inconnue, sous contrôle (liste fermée, citation vérifiée, mémoire, validation)."""
from datetime import date

from ica import ai_classifier as ai, cg_library
from ica.coverage_view import dossier
from ica.extraction.llm import MockLLM

from .conftest import make_cp, sub

# Passage réel des CG AtlantaSanad (art. 8, extension « Vol isolé des roues »).
QUOTE = "à indemniser le vol des roues du véhicule assuré y compris la roue de secours"
LABEL = "Garantie Jantes Alu"  # aucun alias ni mot-clé : les règles ne le reconnaissent pas


def test_rules_do_not_know_the_label(tx):
    assert tx.match_guarantee(LABEL)[0] is None


def test_verified_suggestion_is_accepted(tx, monkeypatch):
    monkeypatch.setattr(ai, "candidate_pages", lambda pdf, label: {10: "…"})
    llm = MockLLM([{"code": "WHEEL_THEFT", "quote": QUOTE, "page": 10, "confidence": "HIGH"}])
    d = ai.classify(llm, tx, "atlantasanad", LABEL)
    assert d["status"] == "suggested" and d["code"] == "WHEEL_THEFT" and d["page"] == 10
    assert "Codes autorisés" in llm.calls[0]["user"] and LABEL in llm.calls[0]["user"]


def test_invented_quote_is_refused(tx, monkeypatch):
    monkeypatch.setattr(ai, "candidate_pages", lambda pdf, label: {10: "…"})
    llm = MockLLM([{"code": "WHEEL_THEFT", "quote": "Les jantes en aluminium sont toujours remboursées à neuf", "confidence": "HIGH"}])
    d = ai.classify(llm, tx, "atlantasanad", LABEL)
    assert d["status"] == "unknown" and d["reason"] == "citation introuvable dans le PDF des CG"


def test_code_outside_the_list_and_low_confidence_are_refused(tx, monkeypatch):
    monkeypatch.setattr(ai, "candidate_pages", lambda pdf, label: {10: "…"})
    assert ai.classify(MockLLM([{"code": "JANTES", "quote": QUOTE, "confidence": "HIGH"}]), tx, "atlantasanad", LABEL)["code"] is None
    low = ai.classify(MockLLM([{"code": "WHEEL_THEFT", "quote": QUOTE, "confidence": "LOW"}]), tx, "atlantasanad", LABEL)
    assert low["status"] == "unknown" and low["reason"] == "confiance faible"


def test_no_call_without_cg_or_without_a_matching_page(tx):
    llm = MockLLM([])
    assert ai.classify(llm, tx, "allianz_maroc", LABEL)["reason"] == "CG de l'assureur non intégrées"
    assert ai.classify(llm, tx, "atlantasanad", "Garantie Xyzzy Qwerty")["reason"] == "aucune page des CG ne mentionne ce libellé"
    assert llm.calls == []


def test_answer_is_stored_once_then_reused_and_user_decides(tx, tmp_path, monkeypatch):
    monkeypatch.setattr(ai, "candidate_pages", lambda pdf, label: {10: "…"})
    llm = MockLLM([{"code": "WHEEL_THEFT", "quote": QUOTE, "page": 10, "confidence": "HIGH"}])
    ai.classify_and_store(tmp_path, llm, tx, "atlantasanad", [LABEL, LABEL])
    ai.classify_and_store(tmp_path, llm, tx, "atlantasanad", [LABEL])  # déjà classé : pas de nouvel appel
    assert len(llm.calls) == 1 and ai.pending(tmp_path, "atlantasanad", [LABEL]) == []

    cp = make_cp([sub("RC", value=50_000_000), sub(None, label=LABEL, value=4000)], insurer="atlantasanad", product=None)
    d = dossier(cp, cg_library.load("atlantasanad"), tx, today=date(2026, 6, 1), ai=ai.overrides(tmp_path, "atlantasanad"))
    assert not d["other_lines"] and d["rule_unmapped"] == [LABEL]
    (row,) = [r for r in d["views"]["theft:at_fault"]["items"] if r.get("ai")]
    assert row["title"] == LABEL and row["plain"] == QUOTE and row["ref"] == "p. 10"
    assert row["ai"] == {"status": "suggested", "label": LABEL, "guarantee": "Vol isolé des roues"} and row["status"] == "unknown"
    assert d["views"]["theft:at_fault"]["parts"]["wheels"]["status"] == "covered"

    ai.set_decision(tmp_path, "atlantasanad", LABEL, "reject")
    d = dossier(cp, cg_library.load("atlantasanad"), tx, today=date(2026, 6, 1), ai=ai.overrides(tmp_path, "atlantasanad"))
    assert [o["label"] for o in d["other_lines"]] == [LABEL]  # refusé : redevient sa propre situation « À vérifier »
