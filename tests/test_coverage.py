"""Bibliothèque de CG intégrée, vues « Ma couverture » / « Mes documents », photos, API."""
from datetime import date
from pathlib import Path

import pytest

from ica import cars, cg_library
from ica.coverage_view import BODY, CASES, deductible_text, dossier, you_pay
from ica.domain import CPExtraction, Deductible, VehicleInfo
from ica.extraction.cp_extractor import cp_from_drafts
from ica.extraction.schemas import CPDraft

from .conftest import make_cp, sub

SAMPLE = Path(__file__).resolve().parent.parent / "samples" / "cp_atlantasanad_draft.json"
TODAY = date(2026, 6, 1)


@pytest.fixture(scope="module")
def sample_cp(tx) -> CPExtraction:
    d = CPDraft.model_validate_json(SAMPLE.read_text(encoding="utf-8"))
    return cp_from_drafts(d, d, document_id="cp", page=1, tx=tx)


# ---------------------------------------------------------------------------------------- bibliothèque


OFFICIAL = {"wafa_assurance", "rma", "axa_maroc", "sanlam_maroc", "atlantasanad", "mcma"}


def test_library_lists_insurers_and_their_integrated_general_conditions(tx):
    kinds = {i["id"]: i["cg_kind"] for i in cg_library.insurers()}
    assert {k for k, v in kinds.items() if v == "official"} == OFFICIAL
    assert kinds["allianz_maroc"] == "missing"  # le PDF fourni était celui d'Allianz France
    for iid in kinds:
        cg = cg_library.load(iid)
        for code, g in cg.guarantees.items():
            assert code in tx.guarantees, f"{iid}: code inconnu {code}"
            assert set(g.parts) <= set(BODY) | {"car"}, f"{iid}/{code}: partie inconnue"
        if iid in OFFICIAL:
            assert cg_library.pdf_path(iid) and cg.guarantees["RC"].plain and cg.sections["deadlines"]


def test_every_excerpt_is_found_word_for_word_in_the_insurer_pdf():
    """Aucune phrase inventée : chaque texte affiché d'un assureur figure dans son PDF."""
    for iid in cg_library.registry():
        assert cg_library.missing_excerpts(iid) == [], iid


def test_excerpt_check_rejects_a_sentence_not_in_the_pdf(monkeypatch):
    spec = {"source": {"pdf": "atlantasanad.pdf"},
            "guarantees": {"GLASS": {"title": "Bris de Glaces", "plain": "Le pare-brise est remplacé gratuitement à vie"}}}
    monkeypatch.setattr(cg_library, "_spec", lambda iid: spec)
    assert cg_library.missing_excerpts("atlantasanad") == ["GLASS.plain: « Le pare-brise est remplacé gratuitement à vie »"]


def test_insurer_without_pdf_shows_no_general_conditions_text():
    cg = cg_library.load("allianz_maroc")
    assert cg.kind == "missing" and cg.source()["pdf_url"] is None
    assert not cg.described()
    assert not any(g.plain or g.covers or g.not_covered or g.conditions or g.ref for g in cg.guarantees.values())
    assert not any(cg.sections[k] for k in ("deadlines", "claim_steps", "compensation", "contract_life", "common_exclusions"))
    assert not any(cg.sections["fault"].values())


def test_article_references_come_from_the_insurer_file():
    atl = cg_library.load("atlantasanad")
    assert atl.kind == "official" and atl.guarantees["ALL_ACCIDENTS"].ref == "Art. 6"
    assert atl.sections["deadlines"][0]["value"] == "cinq (5) jours"


def test_insurer_specific_clauses_differ():
    # AtlantaSanad couvre le bris causé par un vol ; Sanlam l'exclut et exclut aussi les feux du bris des glaces.
    assert "theft" in cg_library.load("atlantasanad").guarantees["GLASS"].cases
    sanlam = cg_library.load("sanlam_maroc").guarantees["GLASS"]
    assert "theft" not in sanlam.cases
    assert any("vol" in x.lower() for x in sanlam.not_covered) and any("feux" in x.lower() for x in sanlam.not_covered)
    assert cg_library.load("axa_maroc").sections["deadlines"][1]["value"] == "vingt-quatre (24) heures"


def test_unknown_insurer_falls_back_to_no_general_conditions():
    assert cg_library.load(None).insurer_id == "other"
    assert cg_library.load("inexistant").kind == "missing"


@pytest.mark.parametrize("text,expected", [("ATLANTASANAD ASSURANCE", "atlantasanad"), ("Wafa Assurance", "wafa_assurance"),
                                           ("SAHAM ASSURANCE", "sanlam_maroc"), ("Compagnie inconnue", None)])
def test_match_insurer(text, expected):
    assert cg_library.match_insurer(text) == expected


# ---------------------------------------------------------------------------------------- formats


def test_deductible_wording():
    assert deductible_text(Deductible(percent=5, minimum_mad=1500)) == "5 % · min 1 500 DH"
    assert deductible_text(Deductible(fixed_mad=0)) == "Aucune"
    assert deductible_text(None) is None  # jamais supposée nulle
    assert deductible_text(Deductible(raw="voir CP")) is None
    assert you_pay(10000, Deductible(percent=5, minimum_mad=1500)) == 1500
    assert you_pay(60000, Deductible(percent=5, minimum_mad=1500)) == 3000


# ---------------------------------------------------------------------------------------- Ma couverture


def test_sample_contract_views(sample_cp, tx):
    d = dossier(sample_cp, cg_library.load("atlantasanad"), tx, today=TODAY)
    assert d["policy"]["status"] == "active" and len(d["views"]) == 2 * len(CASES)
    police = d["views"]["police:at_fault"]
    assert police["headline"]["title"] == "Franchise 5 % · min 1 500 DH"
    assert police["parts"]["windshield"]["amount"] == "20 000 DH" and police["parts"]["windshield"]["subtitle"] == "Bris de glace"
    assert police["parts"]["mirrors"]["amount"] == "3 000 à 5 000 DH"  # bris 3 000, vol 5 000 (montants de la CP)
    wheels = police["parts"]["wheels"]
    assert wheels["status"] == "partial" and wheels["note"] == "Les dommages subis par les pneumatiques"
    assert wheels["note_ref"] == "Art. 6"
    assert police["headline"]["ref"] == "Art. 6" and police["headline"]["text"].startswith("cette garantie, souscrite en Valeur à Neuf")
    nf = d["views"]["police:not_at_fault"]
    assert nf["headline"]["title"] == "Défense et recours souscrite" and nf["needs"]
    assert nf["parts"] == police["parts"]  # mêmes garanties : rien n'est supposé sur l'assurance de l'autre conducteur
    assert [n["ref"] for n in nf["notes"]][:2] == ["Art. 11", "Art. 14"]
    theft = d["views"]["theft:at_fault"]
    assert theft["car"]["status"] == "covered" and theft["parts"]["wheels"]["status"] == "not_covered"  # liste complète
    assert not theft["fault_relevant"] and d["views"]["driver:at_fault"]["fault_relevant"]


def test_absent_guarantee_is_unknown_when_cp_list_is_incomplete(tx):
    cp = make_cp([sub("RC", value=50_000_000)], complete=False, insurer="atlantasanad", product=None)
    d = dossier(cp, cg_library.load("atlantasanad"), tx, today=TODAY)
    assert {c["id"]: c["status"] for c in d["cases"]}["glass"] == "unknown"
    head = d["views"]["police:at_fault"]["headline"]
    assert head["status"] == "unknown" and head["title"] == "Garantie dommages : non trouvée sur la CP"
    assert d["views"]["glass:at_fault"]["parts"]["windshield"]["status"] == "unknown"


def test_collision_needs_an_identified_third_party(tx):
    cp = make_cp([sub("COLLISION", value=30000, ded=Deductible(fixed_mad=1000))], insurer="atlantasanad", product=None)
    part = dossier(cp, cg_library.load("atlantasanad"), tx, today=TODAY)["views"]["police:at_fault"]["parts"]["bodywork"]
    assert part["status"] == "partial" and "identifié" in part["note"]


def test_cp_lines_without_a_situation_are_listed_not_hidden(tx):
    cp = make_cp([sub("RC", value=50_000_000), sub(None, label="Garantie Zénith Plus", value=12_000),
                  sub("GLASS", value=5000)], insurer="atlantasanad", product=None)
    other = dossier(cp, cg_library.load("atlantasanad"), tx, today=TODAY)["other_lines"]
    assert [(o["label"], o["recognized"], o["limit"], o["status"]) for o in other] ==         [("Garantie Zénith Plus", False, "12 000 DH", "unknown")]
    assert other[0]["title"] is None and other[0]["plain"] is None  # rien n'est supposé


def test_unrecognised_guarantee_becomes_its_own_situation(tx):
    cp = make_cp([sub("RC", value=50_000_000), sub(None, label="Garantie Zénith Plus", value=12_000)],
                 insurer="atlantasanad", product=None)
    d = dossier(cp, cg_library.load("atlantasanad"), tx, today=TODAY)
    assert d["cases"][-1] == {"id": "cp1", "label": "Garantie Zénith Plus", "status": "unknown", "extra": True}
    v = d["views"]["cp1:at_fault"]
    assert v["headline"]["title"] == "Garantie Zénith Plus" and v["headline"]["sub"] == "Plafond 12 000 DH"
    assert v["headline"]["text"] is None and v["items"][0]["status"] == "unknown"


@pytest.mark.parametrize("label,code", [("Incapacité", "DISABILITY_BENEFIT"), ("IPP conducteur", "DISABILITY_BENEFIT"),
                                        ("Frais d'hospitalisation", "HOSPITAL_COSTS"), ("Frais hospitalis.", "HOSPITAL_COSTS"),
                                        ("Frais Funéraires", "FUNERAL_COSTS"), ("Frais chirurgie réparatrice", "REPAIR_SURGERY"), ("Incapacité passagers", "PASSENGER_PROTECTION"),
                                        ("Vol des roues et pneus", "WHEEL_THEFT"), ("Dépannage 24h", "ASSISTANCE"),
                                        ("Bris de glace suite au vol", None), ("Garantie Zénith Plus", None)])
def test_keywords_place_known_words_without_guessing(tx, label, code):
    assert tx.match_guarantee(label)[0] == code


def test_incapacity_is_shown_in_the_driver_situation(tx):
    cp = make_cp([sub(None, label="Incapacité", value=100_000)], insurer="atlantasanad", product=None)
    d = dossier(cp, cg_library.load("atlantasanad"), tx, today=TODAY)
    assert {c["id"]: c["status"] for c in d["cases"]}["driver"] == "covered" and not d["other_lines"]
    assert [r["title"] for r in d["views"]["driver:at_fault"]["items"] if r["subscribed"]] == ["Incapacité"]


def test_unrecognised_labels_are_logged_once_per_contract(tmp_path):
    from ica import unrecognised
    unrecognised.record(tmp_path, ["Garantie Zénith Plus"], "rma", "cp1")
    unrecognised.record(tmp_path, ["GARANTIE ZENITH PLUS"], "rma", "cp1")  # même contrat, autre graphie
    unrecognised.record(tmp_path, ["Garantie Zénith Plus"], "axa_maroc", "cp2")
    (e,) = unrecognised.load(tmp_path).values()
    assert e["label"] == "Garantie Zénith Plus" and e["contracts"] == ["cp1", "cp2"] and e["insurers"] == ["rma", "axa_maroc"]


def test_expired_contract_and_insurer_mismatch(sample_cp, tx):
    d = dossier(sample_cp, cg_library.load("wafa_assurance"), tx, today=date(2027, 3, 1))
    assert d["policy"]["status"] == "expired"
    assert d["insurer_mismatch"] and d["detected_insurer"] == "atlantasanad"


def test_documents_views(sample_cp, tx):
    docs = dossier(sample_cp, cg_library.load("atlantasanad"), tx, today=TODAY)["documents"]
    mine = {g["code"] for g in docs["cg"]["mine"]}
    assert {"RC", "THEFT", "GLASS", "ALL_ACCIDENTS"} <= mine
    assert not mine & {g["code"] for g in docs["cg"]["others"]}
    assert docs["cg"]["deadlines"][0]["value"] == "cinq (5) jours" and docs["cg"]["deadlines"][0]["ref"] == "Art. 36"
    assert docs["cg"]["source"]["pdf_url"] == "/api/cg/atlantasanad/pdf"
    ex = docs["cp"]["damage_example"]
    assert ex and ex["rows"][0] == {"cost": "5 000 DH", "you": "1 500 DH", "insurer": "3 500 DH"}
    assert any(label == "Valeur à neuf" for label, _ in docs["cp"]["vehicle"])


def _texts(d: dict):
    """Tous les textes explicatifs que l'application affiche (hors valeurs de la CP et intitulés)."""
    for v in d["views"].values():
        yield v["headline"]["text"]
        yield from (n["text"] for n in (*v["notes"], *v["needs"]))
        yield from (p["note"] for p in v["parts"].values())
        for r in v["items"]:
            yield from (r["plain"], *r["covers"], *r["not_covered"], *r["conditions"])
    cg = d["documents"]["cg"]
    for r in cg["mine"]:
        yield from (r["plain"], *r["covers"], *r["not_covered"], *r["conditions"])
    yield from (g["plain"] for g in cg["others"])
    for k in ("claim_steps", "documents_needed", "common_exclusions"):
        yield from (x["text"] for x in cg[k])
    for k in ("deadlines", "compensation", "contract_life"):
        yield from (x["text"] for x in cg[k])
    yield from (x["text"] for k in ("at_fault", "not_at_fault", "needs") for x in cg["fault"][k])
    yield from (line["plain"] for line in d["documents"]["cp"]["lines"])
    yield from (line["plain"] for line in d["other_lines"])


@pytest.mark.parametrize("insurer", sorted(cg_library.registry()))
def test_every_displayed_explanation_is_an_excerpt_of_the_insurer_cg(sample_cp, tx, insurer):
    """L'application ne rédige rien : chaque explication affichée est un extrait des CG de l'assureur choisi."""
    allowed = {x for _, x in cg_library.excerpts(cg_library._spec(insurer))} if cg_library.load(insurer).kind == "official" else set()
    d = dossier(sample_cp, cg_library.load(insurer), tx, today=TODAY)
    shown = {t for t in _texts(d) if t}
    assert shown <= allowed, shown - allowed
    if insurer == "allianz_maroc":
        assert not shown


# ---------------------------------------------------------------------------------------- photos


@pytest.mark.parametrize("make,model,body,key,how", [
    ("DACIA", "SANDERO STEPWAY", None, "dacia_sandero", "model"),
    ("PEUGEOT", "208", None, "peugeot_208", "model"),
    ("AUDI", None, None, "audi_a3", "make"),
    ("LADA", None, "SUV", "dacia_duster", "body"),
    (None, None, None, None, "none"),
])
def test_car_photo_matching(make, model, body, key, how):
    assert cars.match(VehicleInfo(make=make, model=model, body_type=body)) == (key, how)


def test_uncertain_model_is_labelled_as_illustration():
    assert cars.photo_for(VehicleInfo(make="AUDI"))["label"] == "Photo d'illustration"
    chosen = cars.photo_for(VehicleInfo(make="AUDI"), "audi_q3")
    assert chosen["exact"] and chosen["label"] == "Audi Q3"
    for key, p in cars.catalog()["photos"].items():
        assert (cars.PHOTO_DIR / f"{key}.jpg").exists() and p["credit"].startswith("Photo : ")
        assert all(0 <= v <= 1 for xy in p["anchors"].values() for v in xy)


# ---------------------------------------------------------------------------------------- API


@pytest.fixture()
def client(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from ica import api
    from ica.db import make_session_factory
    monkeypatch.setattr(api, "Session", make_session_factory(f"sqlite:///{tmp_path / 't.db'}"))
    monkeypatch.setattr(api, "DATA", tmp_path)
    c = TestClient(api.app)
    assert c.post("/api/auth/signup", json={"email": "test@example.com", "password": "motdepasse1"}).status_code == 200
    return c


def test_api_onboarding_and_dossier(client):
    meta = client.get("/api/meta").json()
    assert any(i["id"] == "sanlam_maroc" and i["cg_kind"] == "official" for i in meta["insurers"])
    pdf = client.get("/api/cg/sanlam_maroc/pdf")
    assert pdf.status_code == 200 and pdf.content[:4] == b"%PDF"
    assert client.get("/api/cg/allianz_maroc/pdf").status_code == 404
    assert client.put("/api/profile", json={"insurer_id": "nope"}).status_code == 400
    assert client.put("/api/profile", json={"insurer_id": "atlantasanad"}).json()["insurer_id"] == "atlantasanad"
    assert client.get("/api/dossier").status_code == 404  # pas encore de CP
    doc_id = client.post("/api/documents/cp/sample").json()["document_id"]
    d = client.get("/api/dossier").json()
    assert d["policy"]["document_id"] == doc_id and d["insurer"]["id"] == "atlantasanad"
    assert d["photo"]["source"] == "catalog" and client.get(d["photo"]["url"]).status_code == 200
    assert client.put("/api/profile", json={"car_key": "vw_golf"}).status_code == 200
    assert client.get("/api/dossier").json()["photo"]["key"] == "vw_golf"
    assert client.delete(f"/api/documents/{doc_id}").json()["ok"]
    assert client.get("/api/documents").json() == []
    assert "cp_id" not in client.get("/api/profile").json()


def test_person_table_is_split_between_driver_and_passengers(tx):
    """Tableau Personnes : chaque capital va dans le bloc imprimé sur sa ligne (« Passagers … » / « Conducteur … »)."""
    from ica.domain import SourceRef
    def cap(label, value, row):
        s = sub(None, label=label, value=value)
        return s.model_copy(update={"section": "PERSONNES", "source": SourceRef(document_id="cp", page=1, quote=row)})
    pa, co = "Passagers 150 000,00 200 000,00 30 000,00", "Conducteur 200 000,00 200 000,00 20 000,00"
    cp = make_cp([sub("RC", value=50_000_000),
                  cap("Décès", 150_000, pa), cap("IPT à 100%", 200_000, pa), cap("Frais Médicaux", 30_000, pa),
                  cap("Frais Funéraires", 0, pa),
                  cap("Décès", 200_000, co), cap("IPT à 100%", 200_000, co), cap("Frais Médicaux", 20_000, co),
                  cap("Frais hospitalis.", 0, co)], insurer="atlantasanad", product=None)
    d = dossier(cp, cg_library.load("atlantasanad"), tx, today=TODAY)
    status = {c["id"]: c["status"] for c in d["cases"]}
    assert status["driver"] == status["passengers"] == "covered" and not d["other_lines"]
    rows = lambda case: [(r["title"], r["limit"]) for r in d["views"][f"{case}:at_fault"]["items"]]
    assert rows("passengers") == [("Décès", "150 000 DH"), ("IPT à 100%", "200 000 DH"), ("Frais Médicaux", "30 000 DH"),
                                  ("Frais Funéraires", None)]
    assert rows("driver") == [("Décès", "200 000 DH"), ("IPT à 100%", "200 000 DH"), ("Frais Médicaux", "20 000 DH"),
                              ("Frais hospitalis.", None)]
    head = d["views"]["driver:at_fault"]["headline"]
    assert head["title"] == "Garantie conducteur souscrite"
    assert head["sub"] == "Décès 200 000 DH · IPT à 100% 200 000 DH · Frais Médicaux 20 000 DH"


def test_quit_locks_the_account_and_keeps_the_contracts(client):
    doc_id = client.post("/api/documents/cp/sample").json()["document_id"]
    assert client.post("/api/auth/logout").json() == {"ok": True}
    for url in ("/api/dossier", "/api/documents", "/api/profile"):
        assert client.get(url).status_code == 401  # verrouillé
    assert client.get("/api/meta").status_code == 200  # écran de connexion
    assert client.post("/api/auth/login", json={"email": "test@example.com", "password": "faux-mot-de-passe"}).status_code == 401
    assert client.post("/api/auth/login", json={"email": "TEST@example.com", "password": "motdepasse1"}).json() == {"email": "test@example.com"}
    assert [d["id"] for d in client.get("/api/documents").json()] == [doc_id]  # rien n'a été effacé


def test_accounts_are_isolated(client):
    from fastapi.testclient import TestClient
    from ica import api
    client.post("/api/documents/cp/sample")
    other = TestClient(api.app)
    assert other.post("/api/auth/signup", json={"email": "b@example.com", "password": "autremotdepasse"}).status_code == 200
    assert other.get("/api/documents").json() == [] and other.get("/api/dossier").status_code == 404
    assert other.post("/api/auth/signup", json={"email": "test@example.com", "password": "motdepasse1"}).status_code == 400
    assert other.post("/api/auth/signup", json={"email": "c@example.com", "password": "court"}).status_code == 400


def test_password_is_never_stored_and_logins_are_throttled(client):
    from ica import api, auth
    from ica.db import Account
    with api.Session() as s:
        stored = s.query(Account).one().password_hash
    assert "motdepasse1" not in stored and stored.startswith("scrypt$") and auth.check_password("motdepasse1", stored)
    client.post("/api/auth/logout")
    for _ in range(auth.MAX_FAILS):
        client.post("/api/auth/login", json={"email": "test@example.com", "password": "mauvais"})
    r = client.post("/api/auth/login", json={"email": "test@example.com", "password": "motdepasse1"})
    assert r.status_code == 401 and "Trop d'essais" in r.json()["detail"]
    auth._fails.clear()
