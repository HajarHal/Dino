"""Explications visuelles : codes et valeurs, jamais de phrases.

Chaque bloc existant de « Ma couverture » et « Mes documents » reçoit ici des données à afficher sous forme de
puces, chiffres, tuiles, étapes ou frise. Les textes viennent de copy/fr.json (clés construites à partir des codes)
et les extraits verbatim restent accessibles par leur source (« Lire le texte exact »).

Fonctions pures, sans IA : même contrat = même affichage.
"""
from __future__ import annotations

import re
from typing import Optional

from . import cg_library
from .codes import guarantee_code
from .domain import Deductible, SubscribedGuarantee
from .parsing import normalize

UNIT_HOURS = {"HOURS": 1, "DAYS": 24, "MONTHS": 24 * 30, "YEARS": 24 * 365}
STEP_DELAY = {"DECLARER": "DECLARATION_SINISTRE", "CERTIFICAT_MEDICAL": "CERTIFICAT_MEDICAL", "PLAINTE": "PLAINTE_VOL"}


# --------------------------------------------------------------------------------------------- valeurs


def franchise(d: Optional[Deductible]) -> Optional[dict]:
    """Franchise imprimée sur la CP, en code : {kind, percent, min, max, fixed, base}. Case vide -> None."""
    if d is None or not d.has_value:
        return None
    base = d.basis if d.basis in ("DAMAGE", "VEHICLE_VALUE", "INDEMNITY") else "UNKNOWN"
    out = {"kind": "NONE", "percent": None, "min": None, "max": None, "fixed": None, "base": base}
    if not d.percent and not d.fixed_mad and not d.minimum_mad:
        return out
    if d.percent:
        kind = ("PERCENT_MIN_MAX" if d.maximum_mad is not None else "PERCENT_MIN") if d.minimum_mad is not None else \
               ("PERCENT_MIN_MAX" if d.maximum_mad is not None else "PERCENT")
        return out | {"kind": kind, "percent": d.percent,
                      "min": d.minimum_mad if d.minimum_mad is not None else (0.0 if d.maximum_mad is not None else None),
                      "max": d.maximum_mad}
    return out | {"kind": "FIXED", "fixed": d.fixed_mad or d.minimum_mad}


def franchise_split(amount: float, f: dict, plafond: Optional[float]) -> tuple[int, int]:
    """(part de l'assuré, part de l'assureur) pour ``amount`` DH, franchise ``f``, plafond de la CP."""
    kind, p = f["kind"], (f.get("percent") or 0) / 100
    if kind == "NONE":
        you = 0.0
    elif kind == "FIXED":
        you = f.get("fixed") or 0.0
    else:
        you = amount * p
        if kind in ("PERCENT_MIN", "PERCENT_MIN_MAX") and f.get("min") is not None:
            you = max(you, f["min"])
        if kind == "PERCENT_MIN_MAX" and f.get("max") is not None:
            you = min(you, f["max"])
    you = min(you, amount)
    insurer = min(amount - you, plafond) if plafond else amount - you
    return round(you), round(insurer)


def amount_of(s: Optional[SubscribedGuarantee]) -> Optional[float]:
    v = s.insured_value.amount_mad if s and s.insured_value else None
    return v if v else None  # « ,00 » ou vide : non indiqué


# --------------------------------------------------------------------------------------------- sources


def source(cg, ref: Optional[str], texts: list[str], doc: str = "CG", page: Optional[int] = None,
           url: Optional[str] = None) -> dict:
    """Source d'un élément : {doc, ref, article, page, url, texts}. Le libellé est construit par l'interface."""
    texts = [t for t in texts if t]
    if doc == "CG":
        page = page or next((n for n in (cg_library.page_of(cg.pdf, t) for t in texts) if n), None)
        url = url or (f"/api/cg/{cg.insurer_id}/pdf" + (f"#page={page}" if page else "") if cg.pdf else None)
    m = re.match(r"^Art\.\s*(.+)$", ref or "")
    return {"doc": doc, "ref": ref or None, "article": m.group(1) if m else None, "page": page, "url": url, "texts": texts}


def guarantee_source(cg, g) -> Optional[dict]:
    if not g or not g.official:
        return None
    return source(cg, g.ref, [g.plain, *g.covers, *g.not_covered, *g.conditions])


def coded(cg, g, pairs) -> list[dict]:
    """[(code, extrait)] -> [{code, source}] sans doublon de code (le premier extrait sert de source)."""
    seen, out = set(), []
    for code, text in pairs:
        if code not in seen:
            seen.add(code)
            out.append({"code": code, "source": source(cg, g.ref, [text])})
    return out


def guarantee_fields(p, code: str, ln: Optional[SubscribedGuarantee]) -> dict:
    """Champs visuels d'une garantie : code d'affichage, plafond, franchise, puces et clauses non classées."""
    g = p.cg.g(code)
    official = bool(g and g.official)
    return {
        "gcode": guarantee_code(code), "plafond_dh": amount_of(ln), "franchise": franchise(ln.deductible) if ln else None,
        "cover_codes": coded(p.cg, g, g.cover_codes) if official else [],
        "exclusion_codes": coded(p.cg, g, g.exclusion_codes) if official else [],
        "condition_codes": coded(p.cg, g, g.condition_codes) if official else [],
        "note_codes": coded(p.cg, g, g.note_codes) if official else [],
        "unclassified": [{"text": t, "source": source(p.cg, g.ref, [t])} for t in g.unclassified] if official else [],
        "source": guarantee_source(p.cg, g),
    }


# --------------------------------------------------------------------------------------------- qui paie quoi


def bonus(cg) -> Optional[dict]:
    bm = cg.bonus_malus
    if not bm:
        return None
    pct = lambda v: round(v * 100) if v is not None else None  # noqa: E731
    return {"pct": pct(bm.get("material_fault_increase")), "pct_corp": pct(bm.get("bodily_fault_increase")),
            "max": bm.get("max_coefficient"),
            "pct_down": round((1 - bm["no_claim_coefficient"]) * 100) if bm.get("no_claim_coefficient") else None,
            "months": bm.get("no_claim_months"), "needs_review": bool(bm.get("needs_review", True)),
            "source": source(cg, bm.get("ref"), list(bm.get("texts") or []))}


def _tile(code: str, icon: str, src: Optional[dict], value_key: Optional[str] = None, review: bool = False,
          sub: bool = False, label_key: Optional[str] = None, **vars_) -> Optional[dict]:
    """Tuile « qui paie quoi ». Une variable manquante masque la tuile (jamais de valeur vide affichée)."""
    if any(v is None for v in vars_.values()):
        return None
    return {"code": code, "icon": icon, "label_key": label_key or f"fault.{code}",
            "value_key": value_key or f"fault.{code}.value", "sub_key": f"fault.{code}.sub" if sub else None,
            "vars": vars_, "review": review, "source": src}


def who_pays(p) -> dict:
    """Grilles « qui paie quoi » (2 à 4 tuiles) et liste « pour être payé, il faut » (cond.*)."""
    cg = p.cg
    fault = cg.sections["fault"]
    clause = {c: x for k in ("at_fault", "not_at_fault") for x in fault[k] for c in x.get("codes", [])}
    csrc = lambda c: source(cg, clause[c]["ref"], [clause[c]["text"]]) if c in clause else None  # noqa: E731
    gsrc = lambda code: guarantee_source(cg, cg.g(code))  # noqa: E731
    bm = bonus(cg)
    at: list[Optional[dict]] = []
    if p.has("RC"):
        at.append(_tile("OTHER_PAID", "users", gsrc("RC")))
    dmg = p.main_damage()
    if dmg:
        at.append(_tile("MY_CAR_PAID", "car", gsrc(dmg), montant=amount_of(p.line(dmg))))
    elif p.complete:
        at.append(_tile("MY_CAR_PAID", "car", None, value_key="fault.MY_CAR_NOT_PAID.value"))
    me = [a for a in (amount_of(s) for _, s in p.persons["driver"]) if a]
    if me:
        at.append(_tile("ME_PAID", "user", csrc("ME_PAID") or gsrc("DRIVER_PROTECTION"), montant=max(me)))
    if bm and bm["pct"] is not None:
        at.append(_tile("PREMIUM_UP", "trend", bm["source"], review=bm["needs_review"], sub=bm["pct_corp"] is not None
                        and bm["max"] is not None, pct=bm["pct"], pct_corp=bm["pct_corp"], max=bm["max"]))
    nf: list[Optional[dict]] = []
    if "RECOURS" in clause:
        nf.append(_tile("OTHER_INSURER_PAYS", "car", csrc("RECOURS")))
    dr = p.line("DEFENSE_RECOURS")
    if dr and amount_of(dr):
        nf.append(_tile("RECOURS", "scale", csrc("RECOURS") or gsrc("DEFENSE_RECOURS"), montant=amount_of(dr)))
    if "VETUSTE_PAID" in clause and p.has("DEPRECIATION_BUYBACK"):
        nf.append(_tile("VETUSTE_PAID", "wallet", csrc("VETUSTE_PAID")))
    if bm and bm["pct_down"] is not None:
        nf.append(_tile("PREMIUM_DOWN", "trend", bm["source"], review=bm["needs_review"], sub=bm["months"] is not None,
                        pct_down=bm["pct_down"], months=bm["months"]))
    elif "PREMIUM_REFUND" in clause:
        nf.append(_tile("PREMIUM_REFUND", "wallet", csrc("PREMIUM_REFUND")))
    needs, seen = [], set()
    for x in fault["needs"]:
        for c in x.get("codes", []):
            if c not in seen:
                seen.add(c)
                needs.append({"code": c, "source": source(cg, x["ref"], [x["text"]])})
    return {"at_fault": [t for t in at if t][:4], "not_at_fault": [t for t in nf if t][:4], "needs": needs}


# --------------------------------------------------------------------------------------------- Mes documents


def timeline(cg) -> dict:
    """Délais codés, du plus court au plus long ; les délais sans code restent en verbatim."""
    coded_, other = [], []
    for x in cg.sections["deadlines"]:
        src = source(cg, x.get("ref"), [x["text"]])
        if x.get("code") and x.get("n") and x.get("unit"):
            coded_.append({"code": x["code"], "n": x["n"], "unit": x["unit"], "source": src})
        else:
            other.append({"text": x["text"], "source": src})
    coded_.sort(key=lambda d: d["n"] * UNIT_HOURS[d["unit"]])
    return {"items": coded_, "other": other}


def steps(cg, delays: list[dict]) -> dict:
    """Étapes numérotées dans l'ordre du contrat ; un délai correspondant s'affiche à côté."""
    by_code = {d["code"]: d for d in delays}
    out, other, seen = [], [], set()
    for x in cg.sections["claim_steps"]:
        src = source(cg, x.get("ref"), [x["text"]])
        if not x.get("codes"):
            other.append({"text": x["text"], "source": src})
            continue
        for c in x["codes"]:
            if c in seen:
                continue
            seen.add(c)
            d = by_code.get(STEP_DELAY.get(c, ""))
            out.append({"code": c, "delay": {"n": d["n"], "unit": d["unit"]} if d else None, "source": src})
    return {"items": out, "other": other}


def checks(cp, lines: list[dict]) -> list[str]:
    """Points à vérifier sur la CP, en codes (check.*) : rien n'est rédigé par le modèle qui lit la CP."""
    out = []
    notes = normalize(" ".join(cp.warnings))
    if re.search(r"flou|peu net|pas net|illisib", notes):
        out.append("PHOTO_FLOUE")
    if re.search(r"inclin|pench|rotat|travers", notes):
        out.append("PHOTO_INCLINEE")
    if re.search(r"masqu|cach|occult", notes):
        out.append("DONNEES_MASQUEES")
    if any(x["to_check"] for x in lines) or re.search(r"montant", notes):
        out.append("MONTANT_ILLISIBLE")
    if not cp.period_start or not cp.period_end:
        out.append("DATE_ILLISIBLE")
    return list(dict.fromkeys(out))
