"""Analyse des montants, taxonomie, vérification des citations."""
import pytest

from ica.domain import LimitBasis, VerificationStatus
from ica.parsing import all_amounts, normalize, parse_amount, parse_deductible, parse_limit
from ica.verification import verify_numbers, verify_quote


@pytest.mark.parametrize("raw,expected", [
    ("50 000 000,00", 50_000_000.0), ("487 000,00", 487_000.0), ("15.000", 15_000.0), ("3000", 3000.0),
    ("0,25", 0.25), ("pas de montant", None),
])
def test_parse_amount(raw, expected):
    assert parse_amount(raw) == expected


def test_deductible_percent_with_minimum():
    d = parse_deductible("5 % /Dom. min 1500")
    assert (d.percent, d.minimum_mad, d.fixed_mad, d.basis) == (5.0, 1500.0, None, "DAMAGE")


def test_deductible_explicit_zero_is_not_missing():
    d = parse_deductible("0 /Dom")
    assert d.fixed_mad == 0 and d.has_value


def test_deductible_referring_to_cp_has_no_value():
    assert not parse_deductible("Voir franchise aux Conditions Particulières").has_value
    assert not parse_deductible("").has_value


def test_limit_bases():
    assert parse_limit("Valeur vénale au jour du sinistre").basis == LimitBasis.MARKET_VALUE
    assert parse_limit("Plafond mentionné aux Conditions Particulières").basis == LimitBasis.SEE_CP
    lim = parse_limit("50 000 000 dhs")
    assert lim.basis == LimitBasis.FIXED and lim.amount_mad == 50_000_000


@pytest.mark.parametrize("label,code", [
    ("DTA (y compris vétusté)", "ALL_ACCIDENTS"), ("Bris de Glaces (Ann. Ass.)", "GLASS"), ("Ev. catastrophiques DOM *", "CAT_EVENTS_DAMAGE"),
    ("Ev. catastrophiques RC *", "CAT_EVENTS_LIABILITY"), ("La garantie Vol", "THEFT"), ("Vol des rétroviseurs & op", "MIRROR_THEFT"),
    ("Rachat de vétustés", "DEPRECIATION_BUYBACK"), ("La garantie Dommages tous accidents (DTA)", None),
    ("Responsabilité Civile", "RC"), ("Protection du Conducteur", "DRIVER_PROTECTION"),
])
def test_taxonomy_labels_from_real_documents(tx, label, code):
    got, _ = tx.match_guarantee(label)
    if code is not None:
        assert got == code


def test_taxonomy_unknown_label_is_not_guessed(tx):
    assert tx.match_guarantee("Garantie pneus neige premium")[0] is None
    assert tx.match_guarantee("Volant")[0] is None  # ne doit pas devenir « Vol »


def test_detect_insurer_and_product(tx):
    text = "Compagnie AXA Assurance Maroc - conditions générales Solution Auto"
    assert tx.detect_insurer(text) == "axa_maroc"
    assert tx.detect_product(text, "axa_maroc") == "axa_solution_auto"
    assert tx.detect_insurer("texte sans assureur") is None


PAGES = {1: "La garantie Vol couvre la disparition du véhicule assuré.", 2: "Sont exclus les vols commis par les préposés de l'assuré."}


def test_quote_verified_on_cited_page():
    v = verify_quote("couvre la disparition du véhicule assuré", PAGES, 1)
    assert v.status == VerificationStatus.VERIFIED and v.page_found == 1


def test_quote_found_on_other_page_is_relocated():
    v = verify_quote("vols commis par les préposés de l'assuré", PAGES, 1)
    assert v.status == VerificationStatus.VERIFIED and v.page_found == 2


def test_invented_quote_is_rejected():
    v = verify_quote("le vol est toujours remboursé intégralement sans franchise", PAGES, 1)
    assert v.status == VerificationStatus.QUOTE_NOT_FOUND


def test_numbers_must_appear_in_quote():
    assert verify_numbers([487000.0, 5.0], "Vol 487 000,00 5 % /Dom.").status == VerificationStatus.VERIFIED
    assert verify_numbers([478000.0], "Vol 487 000,00 5 % /Dom.").status == VerificationStatus.VALUE_MISMATCH


def test_normalize_and_amount_list():
    assert normalize("Défense & Recours (DR)") == "defense recours dr"
    assert all_amounts("DTA 487 000,00 5 % /Dom. min 1500") == [487000.0, 5.0, 1500.0]
