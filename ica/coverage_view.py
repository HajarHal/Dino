"""Ce que voit l'assuré : « Ma couverture » et « Mes documents », calculés sans IA.

Entrées : la CP lue (garanties souscrites, plafonds, franchises) et les CG de son assureur (bibliothèque
intégrée). Les montants viennent TOUJOURS de la CP ; le sens de chaque garantie (ce qui est couvert, exclu,
les conditions) vient des CG. Rien n'est supposé : une valeur absente de la CP est « non indiquée ».

Aucune phrase n'est rédigée par l'application : les titres sont des valeurs de la CP, les explications des
extraits des CG de l'assureur (cg_library : extraits vérifiés dans le PDF).

Quatre statuts, partout les mêmes :
  covered      couvert ;
  partial      couvert sous condition (pièce citée dans une exclusion ou une condition des CG, tiers identifié…) ;
  not_covered  garantie non souscrite (liste de la CP complète) ;
  unknown      non trouvé sur une CP lue partiellement : à vérifier.
"""
from __future__ import annotations

from datetime import date
from typing import Optional

from . import explain
from .cg_library import Guarantee, InsurerCG
from .codes import guarantee_code
from .domain import CPExtraction, Deductible, Limit, SubscribedGuarantee
from .parsing import normalize
from .taxonomy import Taxonomy

# ---------------------------------------------------------------------------------------------- référentiels

PARTS: dict[str, str] = {
    "windshield": "Pare-brise", "side_windows": "Vitres", "rear_window": "Lunette arrière",
    "headlights": "Optiques", "mirrors": "Rétroviseurs", "front_bumper": "Pare-chocs",
    "bodywork": "Carrosserie", "wheels": "Roues", "engine_mechanics": "Moteur", "rear_bumper": "Pare-chocs arrière",
}
BODY = ["front_bumper", "bodywork", "headlights", "mirrors", "wheels", "engine_mechanics", "rear_bumper",
        "windshield", "side_windows", "rear_window"]

CASES: list[tuple[str, str]] = [
    ("police", "Ma police"), ("driver", "Conducteur"), ("glass", "Bris de glace"), ("theft", "Vol"),
    ("passengers", "Passagers"), ("fire", "Incendie"), ("nature", "Catastrophes"),
    ("assistance", "Assistance"), ("defense", "Défense et recours"),
]
DAMAGE = ["ALL_RISKS", "ALL_ACCIDENTS", "TIERCE", "ALL_ACCIDENTS_LIMITED", "COLLISION_EXTENDED", "COLLISION"]
# Capitaux d'un tableau « Personnes » (Décès, IPT, Frais médicaux…) : ils appartiennent au bloc Conducteur ou
# Passagers imprimé sur leur ligne de la CP (person_of).
BENEFITS = ["DEATH_BENEFIT", "DISABILITY_BENEFIT", "MEDICAL_COSTS", "HOSPITAL_COSTS", "FUNERAL_COSTS", "REPAIR_SURGERY", "DEATH_ALL_CAUSES"]
PERSON_CODES = {
    "driver": ["DRIVER_PROTECTION", "PERSONAL_INJURY", *BENEFITS],
    "passengers": ["PASSENGER_PROTECTION", "PERSONAL_INJURY", *BENEFITS],
}
PROTECTION = {"driver": ["DRIVER_PROTECTION", "PERSONAL_INJURY"], "passengers": ["PASSENGER_PROTECTION", "PERSONAL_INJURY"]}
_DRIVER_WORDS = {"conducteur", "conducteurs"}
_PASSENGER_WORDS = {"passager", "passagers", "transportees", "transportes", "occupants"}


def person_of(s: SubscribedGuarantee, code: Optional[str]) -> Optional[str]:
    """« driver », « passengers » ou None, d'après ce qui est imprimé : le libellé, puis la ligne du tableau
    (« Passagers 150 000,00 … ») ; à défaut, le code. Rien n'est deviné : les deux mots ou aucun -> None."""
    for text in (s.label_raw, s.source.quote or ""):
        words = set(normalize(text).split())
        d, pa = bool(words & _DRIVER_WORDS), bool(words & _PASSENGER_WORDS)
        if d != pa:
            return "driver" if d else "passengers"
    if code == "DRIVER_PROTECTION":
        return "driver"
    if code == "PASSENGER_PROTECTION":
        return "passengers"
    return None
# Garanties dont le résultat ne dépend pas de la responsabilité.
FAULT_NEUTRAL = {"glass", "theft", "fire", "nature", "assistance"}

SHORT: dict[str, str] = {
    "GLASS": "Bris de glace", "MIRROR_GLASS": "Bris", "MIRROR_THEFT": "Vol", "WHEEL_THEFT": "Vol des roues",
    "ALL_ACCIDENTS": "Tous accidents", "ALL_RISKS": "Tous risques", "TIERCE": "Tierce", "ALL_ACCIDENTS_LIMITED": "Dommages",
    "COLLISION": "Collision", "COLLISION_EXTENDED": "Collision", "FIRE": "Incendie", "THEFT": "Vol",
    "FLOOD": "Inondation", "NATURAL_EVENTS": "Climat", "CAT_EVENTS_DAMAGE": "Catastrophe", "VANDALISM": "Vandalisme",
    "MECHANICAL_BREAKDOWN": "Panne", "PANORAMIC_ROOF": "Toit vitré",
}

STATUS_RANK = {"covered": 3, "partial": 2, "unknown": 1, "not_covered": 0}

# ---------------------------------------------------------------------------------------------- formats


def dh(v: Optional[float]) -> str:
    return f"{v:,.0f} DH".replace(",", " ") if v is not None else "Non indiqué"


def _n(v: float) -> str:
    return f"{v:,.0f}".replace(",", " ") if float(v).is_integer() else f"{v:,.2f}".replace(",", " ").replace(".", ",")


def limit_text(l: Optional[Limit]) -> Optional[str]:
    if l is None:
        return None
    if l.amount_mad:
        return dh(l.amount_mad)
    raw = (l.raw or "").strip()
    if raw.upper() in ("GARANTIE", "INCLUS", "OUI", "ACQUISE"):
        return "Inclus"
    return None  # « ,00 », champs de formulaire non remplis… : rien d'exploitable


def deductible_text(d: Optional[Deductible]) -> Optional[str]:
    """« Aucune », « 5 % · min 1 500 DH », « 1 500 DH » ; None si la CP n'indique rien."""
    if d is None or not d.has_value:
        return None
    if d.fixed_mad == 0 and d.percent in (None, 0):
        return "Aucune"
    if d.percent == 0 and not d.minimum_mad and not d.fixed_mad:
        return "Aucune"
    parts = []
    if d.percent:
        parts.append(f"{_n(d.percent)} %")
    if d.minimum_mad:
        parts.append(f"min {_n(d.minimum_mad)} DH")
    if d.maximum_mad:
        parts.append(f"max {_n(d.maximum_mad)} DH")
    if d.fixed_mad:
        parts.append(dh(d.fixed_mad))
    return " · ".join(parts)


def you_pay(cost: float, d: Optional[Deductible]) -> Optional[float]:
    """Part à la charge de l'assuré pour un sinistre de ``cost`` DH (franchise seule, hors plafond)."""
    if d is None or not d.has_value:
        return None
    if d.fixed_mad is not None and not d.percent:
        v = d.fixed_mad
    else:
        v = cost * (d.percent or 0) / 100
        if d.minimum_mad:
            v = max(v, d.minimum_mad)
        if d.maximum_mad:
            v = min(v, d.maximum_mad)
    return min(v, cost)


def _iso(d: Optional[date]) -> Optional[str]:
    return d.isoformat() if d else None


# ---------------------------------------------------------------------------------------------- contrat


class Policy:
    """CP + CG de l'assureur, lues une fois ; toutes les vues en dérivent."""

    def __init__(self, cp: CPExtraction, cg: InsurerCG, tx: Taxonomy, today: Optional[date] = None,
                 ai: Optional[dict[str, dict]] = None):
        self.cp, self.cg, self.tx = cp, cg, tx
        self.today = today or date.today()
        self.lines: dict[str, list[SubscribedGuarantee]] = {}
        self.unmapped: list[SubscribedGuarantee] = []
        self.rule_unmapped: list[str] = []  # libellés que les règles n'ont pas reconnus (avant l'IA)
        self.ai_lines: dict[int, dict] = {}  # id(ligne) -> classement IA vérifié (ica/ai_classifier.py)
        for s in cp.subscribed:
            code = s.canonical_code or tx.match_guarantee(s.label_raw)[0]
            if not code:
                self.rule_unmapped.append(s.label_raw)
                e = (ai or {}).get(normalize(s.label_raw))
                if e:
                    code = e["code"]
                    self.ai_lines[id(s)] = e
            if code:
                self.lines.setdefault(code, []).append(s)
            else:
                self.unmapped.append(s)
        # Conducteur / Passagers : les lignes de chaque bloc, dans l'ordre de la CP. Un capital sans bloc
        # identifiable (une seule ligne « Décès ») reste rattaché au conducteur, comme avant.
        self.persons: dict[str, list[tuple[Optional[str], SubscribedGuarantee]]] = {"driver": [], "passengers": []}
        for s in cp.subscribed:
            code = next((c for c, ls in self.lines.items() if any(x is s for x in ls)), None)
            who = person_of(s, code)
            if code == "PERSONAL_INJURY" and who is None:
                self.persons["driver"].append((code, s)); self.persons["passengers"].append((code, s))
            elif who and (code in PERSON_CODES[who] or (code is None and s.section == "PERSONNES")):
                self.persons[who].append((code, s))
            elif who is None and code in BENEFITS:
                self.persons["driver"].append((code, s))
        self.complete = cp.guarantee_list_complete

    # ---- garanties
    def has(self, code: str) -> bool:
        return code in self.lines

    def line(self, code: str) -> Optional[SubscribedGuarantee]:
        return self.lines.get(code, [None])[0]

    def missing_status(self) -> str:
        return "not_covered" if self.complete else "unknown"

    def g(self, code: str) -> Guarantee:
        g = self.cg.g(code)
        if g is None:  # libellé de CP connu de la taxonomie mais absent de la bibliothèque
            g = Guarantee(code=code, title="", plain="", covers=(), not_covered=(), conditions=(), ref="", cases=())
        return g

    def main_damage(self) -> Optional[str]:
        return next((c for c in DAMAGE if self.has(c)), None)

    # ---- contrat
    def status(self) -> str:
        s, e = self.cp.period_start, self.cp.period_end
        if not s and not e:
            return "unknown"
        if e and self.today > e:
            return "expired"
        if s and self.today < s:
            return "upcoming"
        return "active"

    def row(self, code: str) -> dict:
        """Une garantie telle que l'assuré la lit : souscrite ou non, plafond, franchise, sens."""
        g = self.g(code)
        ln = self.line(code)
        if ln is not None and id(ln) in self.ai_lines:
            return self.ai_row(code, ln)
        # Titre : celui des CG de l'assureur, sinon le libellé imprimé sur la CP.
        out = {"code": code, "title": g.title or (ln.label_raw if ln else self.tx.label_fr(code)), "plain": g.plain,
               "covers": list(g.covers),
               "not_covered": list(g.not_covered), "conditions": list(g.conditions), "ref": g.ref,
               "subscribed": ln is not None, "status": "covered" if ln else self.missing_status(),
               "limit": limit_text(ln.insured_value) if ln else None,
               "deductible": deductible_text(ln.deductible) if ln else None,
               "cp_label": ln.label_raw if ln else None,
               "to_check": bool(ln and ln.verification.confidence == "LOW")}
        more = [x for x in self.lines.get(code, [])[1:] if id(x) not in self.ai_lines]
        if more:  # même garantie sur plusieurs lignes (conducteur et passagers…)
            out["also"] = [{"label": x.label_raw, "limit": limit_text(x.insured_value)} for x in more]
        return out | explain.guarantee_fields(self, code, ln)

    def person_row(self, code: Optional[str], ln: SubscribedGuarantee) -> dict:
        """Une ligne du tableau Personnes : son libellé imprimé (« IPT à 100% ») et SON capital."""
        if code and id(ln) not in self.ai_lines:
            out = self.row(code) | {"title": ln.label_raw, "limit": limit_text(ln.insured_value),
                                    "deductible": deductible_text(ln.deductible), "cp_label": ln.label_raw,
                                    "to_check": ln.verification.confidence == "LOW",
                                    "plafond_dh": explain.amount_of(ln), "franchise": explain.franchise(ln.deductible)}
            out.pop("also", None)
            return out
        if code:
            return self.ai_row(code, ln)
        return {"code": f"line:{ln.label_raw}", "title": ln.label_raw, "plain": "", "covers": [], "not_covered": [],
                "conditions": [], "ref": "", "subscribed": True, "status": "unknown", "limit": limit_text(ln.insured_value),
                "deductible": deductible_text(ln.deductible), "cp_label": ln.label_raw,
                "to_check": ln.verification.confidence == "LOW", **_bare(ln)}

    def ai_row(self, code: str, ln: SubscribedGuarantee) -> dict:
        """Ligne classée par l'IA : libellé de la CP, et comme seul texte la citation des CG vérifiée dans le PDF."""
        e = self.ai_lines[id(ln)]
        return {"code": code, "title": ln.label_raw, "plain": e.get("quote") or "", "covers": [], "not_covered": [],
                "conditions": [], "ref": f"p. {e['page']}" if e.get("page") else "", "subscribed": True,
                "status": "covered" if e["status"] == "confirmed" else "unknown",
                "limit": limit_text(ln.insured_value), "deductible": deductible_text(ln.deductible),
                "cp_label": ln.label_raw, "to_check": ln.verification.confidence == "LOW",
                "ai": {"status": e["status"], "label": ln.label_raw,
                       "guarantee": self.g(code).title or self.tx.label_fr(code)}, **_bare(ln)}

    def ai_rows(self, codes: list[str]) -> list[dict]:
        """Lignes classées par l'IA sous un code déjà présent (elles ne sont pas la ligne principale)."""
        return [self.ai_row(c, x) for c in codes for x in self.lines.get(c, [])[1:] if id(x) in self.ai_lines]


def _bare(ln: SubscribedGuarantee) -> dict:
    """Champs visuels d'une ligne sans texte des CG : plafond et franchise de la CP seulement."""
    return {"gcode": None, "plafond_dh": explain.amount_of(ln), "franchise": explain.franchise(ln.deductible),
            "cover_codes": [], "exclusion_codes": [], "condition_codes": [], "note_codes": [], "unclassified": [],
            "source": None}


# ---------------------------------------------------------------------------------------------- parties du véhicule


def _entries(p: Policy, zone: str, codes: list[str]) -> list[dict]:
    """Garanties souscrites qui couvrent ``zone`` parmi ``codes`` (ordre = priorité), avec leur réserve.

    Une réserve (``conditional``) vient des CG : pièce citée dans une exclusion ou une condition
    (``part_notes``), ou garantie qui exige un tiers identifié. ``note`` est l'extrait des CG, s'il existe.
    """
    out = []
    for code in codes:
        if not p.has(code):
            continue
        g = p.g(code)
        if zone not in g.parts and zone not in g.part_notes:
            continue
        note = g.part_notes.get(zone) or (g.parts_note if g.needs_third_party else None)
        ln = p.line(code)
        if id(ln) in p.ai_lines:
            g = Guarantee(code=code, title=ln.label_raw, plain="", covers=(), not_covered=(), conditions=(), ref="",
                          cases=g.cases, parts=g.parts, part_notes={}, needs_third_party=g.needs_third_party)
        out.append({"code": code, "short": ln.label_raw if id(ln) in p.ai_lines else SHORT.get(code) or g.title or ln.label_raw, "title": g.title or ln.label_raw,
                    "note": note or None, "ref": g.ref or None,
                    "conditional": bool(zone in g.part_notes or g.needs_third_party),
                    "limit": limit_text(ln.insured_value), "amount": ln.insured_value.amount_mad if ln.insured_value else None,
                    "deductible": deductible_text(ln.deductible), "franchise": explain.franchise(ln.deductible)})
    return out


def _amount(entries: list[dict]) -> Optional[str]:
    vals = sorted({e["amount"] for e in entries if e["amount"]})
    if not vals:
        return next((e["limit"] for e in entries if e["limit"]), None)
    if len(vals) == 1:
        return dh(vals[0])
    return f"{_n(vals[0])} à {dh(vals[-1])}"


def _part(p: Policy, zone: str, codes: list[str]) -> dict:
    entries = _entries(p, zone, codes)
    full = [e for e in entries if not e["conditional"]]
    status = "covered" if full else "partial" if entries else p.missing_status()
    # Bulle : la garantie propre à la pièce (bris, vol des rétroviseurs…) plutôt que la garantie dommages
    # générale ; toutes restent listées dans le détail de la pièce.
    specific = [e for e in full if e["code"] not in DAMAGE]
    shown = specific or full or entries
    best = (shown or [None])[0]
    subtitle = " / ".join(dict.fromkeys(e["short"] for e in shown)) if shown else None
    cond = next((e for e in entries if e["conditional"]), None) if not full else None
    return {"zone": zone, "label": PARTS[zone], "status": status, "subtitle": subtitle,
            "amount": _amount(shown), "deductible": best["deductible"] if best else None,
            "note": cond["note"] if cond else None, "note_ref": cond["ref"] if cond else None,
            "entries": entries,
            "plafond_dh": max((e["amount"] for e in shown if e["amount"]), default=None),
            "franchise": best["franchise"] if best else None}


# ---------------------------------------------------------------------------------------------- vues par cas
#
# Aucune phrase n'est rédigée ici : les titres sont des valeurs de la CP (franchise, plafond, garantie
# souscrite ou non) ; les textes sont des extraits des CG de l'assureur, avec leur article.


def _case_codes(p: Policy, case: str) -> list[str]:
    if case in PERSON_CODES:
        return PERSON_CODES[case]
    codes = [c for c, g in p.cg.guarantees.items() if case in g.cases]
    if case == "police":  # vue d'ensemble : dommages d'abord, puis bris et vol des pièces
        extra = [c for c, g in p.cg.guarantees.items() if ("glass" in g.cases or "theft" in g.cases) and c != "THEFT"]
        codes = [c for c in DAMAGE if c in codes] + [c for c in codes if c not in DAMAGE] + extra
    return list(dict.fromkeys(codes))


def _person_codes(p: Policy, case: str) -> list[str]:
    return list(dict.fromkeys(c for c, _ in p.persons[case] if c))


def case_status(p: Policy, case: str) -> str:
    if case == "police":
        return "covered" if p.main_damage() else "partial"
    if case in PERSON_CODES:
        return "covered" if p.persons[case] else p.missing_status()
    if any(p.has(c) for c in _case_codes(p, case)):
        return "covered"
    return p.missing_status()


def _absent(p: Policy, label: str) -> str:
    return f"{label} : absente de la CP" if p.complete else f"{label} : non trouvée sur la CP"


def _headline(p: Policy, case: str, fault: str) -> dict:
    """Titre et sous-titre = valeurs de la CP ; texte = extrait des CG de l'assureur (ou rien)."""
    def head(status: str, title: str, code: Optional[str] = None, sub: Optional[str] = None) -> dict:
        g = p.cg.g(code) if code else None
        out = {"status": status, "title": title, "sub": sub,
               "text": (g.plain or None) if g else None, "ref": (g.ref or None) if g else None}
        # Valeurs de la carte : code d'affichage, souscrite ou non, plafond et franchise de la CP.
        about = code or _absent_code(p, case, fault)
        ln = p.line(about) if about else None
        persons = p.persons.get(case) if case in PERSON_CODES else None
        amounts = [a for a in (explain.amount_of(s) for _, s in persons or []) if a]
        return out | {
            "gcode": ({"driver": "PROTECTION_CONDUCTEUR", "passengers": "PROTECTION_PASSAGERS"}.get(case)
                      or guarantee_code(about)),
            "subscribed": bool(persons) if persons is not None else ln is not None,
            "plafond_dh": max(amounts) if amounts else explain.amount_of(ln),
            "franchise": explain.franchise(ln.deductible) if ln and persons is None else None,
            "source": explain.guarantee_source(p.cg, p.cg.g(about)) if about else None}

    def plafond(code: str) -> str:
        ln = p.line(code)
        return f"{p.g(code).title or ln.label_raw} · plafond {limit_text(ln.insured_value) or 'non indiqué'}"

    if case == "defense" or (case == "police" and fault == "not_at_fault"):
        ln = p.line("DEFENSE_RECOURS")
        if not ln:
            return head(p.missing_status(), _absent(p, "Défense et recours"))
        return head("covered", "Défense et recours souscrite", "DEFENSE_RECOURS", plafond("DEFENSE_RECOURS"))
    if case == "police":
        dmg = p.main_damage()
        if not dmg:
            return head("not_covered" if p.complete else "unknown", _absent(p, "Garantie dommages"), "RC")
        fr = deductible_text(p.line(dmg).deductible)
        return head("partial" if fr and fr != "Aucune" else "covered",
                    f"Franchise {fr}" if fr else "Franchise non indiquée sur la CP", dmg, plafond(dmg))
    if case in PERSON_CODES:
        lines = p.persons[case]
        label = "Garantie conducteur" if case == "driver" else "Garantie passagers"
        if not lines:
            return head(p.missing_status(), _absent(p, label))
        # Texte : l'extrait des CG de la garantie de protection correspondante, s'il existe.
        prot = next((c for c in PROTECTION[case] if p.cg.g(c) and p.cg.g(c).official), None)
        figures = [f"{s.label_raw} {limit_text(s.insured_value)}" for _, s in lines if limit_text(s.insured_value)]
        return head("covered", f"{label} souscrite", prot, " · ".join(figures) or None)
    if case == "assistance":
        ln, formula = p.line("ASSISTANCE"), p.cp.assistance_formula
        if not (ln or formula):
            return head(p.missing_status(), _absent(p, "Assistance"))
        return head("covered", f"Assistance {formula}" if formula else "Assistance souscrite", "ASSISTANCE")
    # bris de glace, vol, incendie, catastrophes : garantie principale du cas
    codes = [c for c in _case_codes(p, case) if p.has(c)]
    if not codes:
        return head(p.missing_status(), _absent(p, dict(CASES)[case]))
    fr = deductible_text(p.line(codes[0]).deductible)
    title = "Aucune franchise" if fr == "Aucune" else f"Franchise {fr}" if fr else "Franchise non indiquée sur la CP"
    return head("covered" if fr in (None, "Aucune") else "partial", title, codes[0], plafond(codes[0]))


def _absent_code(p: Policy, case: str, fault: str) -> Optional[str]:
    """Garantie dont parle la carte quand elle n'est pas souscrite (pour son nom et « Vous ne l'avez pas »)."""
    if case == "defense" or (case == "police" and fault == "not_at_fault"):
        return "DEFENSE_RECOURS"
    if case == "police":
        return p.main_damage() or "ALL_ACCIDENTS"
    if case == "assistance":
        return "ASSISTANCE"
    if case in PERSON_CODES:
        return None
    return next((c for c in _case_codes(p, case) if p.has(c)), next(iter(_case_codes(p, case)), None))


def _fault_notes(p: Policy, case: str, fault: str) -> list[dict]:
    """Extraits des CG sur la responsabilité (bonus-malus, recours, vétusté…), avec leur article."""
    if case not in ("police", "driver", "passengers", "defense"):
        return []
    return list(p.cg.sections["fault"][fault])


def view(p: Policy, case: str, fault: str) -> dict:
    codes = _case_codes(p, case)
    parts: dict[str, dict] = {}
    if case in ("police", "glass", "theft", "fire", "nature"):
        zones = _zones_of(p, codes)
        for z in BODY:
            own = _part(p, z, codes)
            if case != "police" and own["status"] in ("not_covered", "unknown") and z not in zones:
                own = {**own, "status": "none"}  # partie que ce cas ne concerne pas : estompée
            parts[z] = own
    car = None
    if case == "theft":
        ln = p.line("THEFT")
        car = {"status": "covered" if ln else p.missing_status(), "label": "Vol du véhicule",
               "amount": limit_text(ln.insured_value) if ln else None, "deductible": deductible_text(ln.deductible) if ln else None}
    item_codes = codes if case != "police" else list(dict.fromkeys([c for c in p.lines] + [c for c in DAMAGE if c in codes]))
    # Garanties non souscrites : listées seulement si les CG de l'assureur les décrivent.
    if case in PERSON_CODES:  # une ligne par capital imprimé, dans l'ordre de la CP
        items = [p.person_row(c, s) for c, s in p.persons[case]]
    else:
        items = [p.row(c) for c in item_codes if c in p.lines or (case != "police" and p.cg.g(c) and p.cg.g(c).official)]
        items += p.ai_rows([c for c in item_codes if c in p.lines])
    if case != "police":
        items.sort(key=lambda r: not r["subscribed"])
    return {"case": case, "fault": fault, "fault_relevant": case not in FAULT_NEUTRAL,
            "headline": _headline(p, case, fault), "notes": _fault_notes(p, case, fault),
            "who_pays": _who_pays(p, case, fault),
            "needs": p.cg.sections["fault"]["needs"] if fault == "not_at_fault" and case in ("police", "defense") else [],
            "parts": parts, "car": car, "items": items}


def other_lines(p: Policy) -> list[dict]:
    """Lignes de la CP qu'aucune situation n'affiche : libellé non reconnu, ou garantie reconnue mais sans cas.

    Rien n'est supposé : libellé tel qu'imprimé, plafond et franchise de la CP, statut « à vérifier ». Un texte
    des CG n'est ajouté que si la garantie est reconnue et décrite par les CG de l'assureur.
    """
    shown = {c for case, _ in CASES for c in _case_codes(p, case)}
    in_person = {id(s) for ls in p.persons.values() for _, s in ls}
    lines = [(None, s) for s in p.unmapped if id(s) not in in_person]
    lines += [(code, s) for code, ls in p.lines.items() if code not in shown for s in ls]
    out = []
    for code, s in lines:
        g = p.cg.g(code) if code else None
        out.append({"label": s.label_raw, "code": code, "recognized": code is not None,
                    "title": (g.title or None) if g else None, "plain": (g.plain or None) if g else None,
                    "ref": (g.ref or None) if g else None, "status": "unknown",
                    "limit": limit_text(s.insured_value), "deductible": deductible_text(s.deductible),
                    "to_check": s.verification.confidence == "LOW"})
    return out


def extra_cases(others: list[dict]) -> list[dict]:
    """Une situation de plus par ligne de CP que les situations habituelles n'affichent pas (« cp1 », « cp2 »…)."""
    return [{"id": f"cp{i}", "label": o["title"] or o["label"], "status": "unknown", "extra": True}
            for i, o in enumerate(others, 1)]


def extra_view(case_id: str, fault: str, o: dict) -> dict:
    """Vue d'une ligne de CP sans situation : libellé, plafond et franchise de la CP ; extrait des CG s'il existe."""
    figures = [f"Plafond {o['limit']}" if o["limit"] else None, f"Franchise {o['deductible']}" if o["deductible"] else None]
    row = {"code": case_id, "title": o["title"] or o["label"], "plain": o["plain"] or "", "covers": [], "not_covered": [],
           "conditions": [], "ref": o["ref"] or "", "subscribed": True, "status": "unknown", "limit": o["limit"],
           "deductible": o["deductible"], "cp_label": o["label"], "to_check": o["to_check"]}
    return {"case": case_id, "fault": fault, "fault_relevant": False,
            "headline": {"status": "unknown", "title": o["title"] or o["label"],
                         "sub": " · ".join(x for x in figures if x) or "Plafond et franchise non indiqués sur la CP",
                         "text": o["plain"], "ref": o["ref"]},
            "notes": [], "needs": [], "parts": {}, "car": None, "items": [row], "extra": True}


def _zones_of(p: Policy, codes: list[str]) -> set[str]:
    return {z for c in codes for z in (*p.g(c).parts, *p.g(c).part_notes)}


# ---------------------------------------------------------------------------------------------- Mes documents


def _who_pays(p: Policy, case: str, fault: str) -> Optional[dict]:
    """Tuiles « qui paie quoi » du scénario affiché (cas où la responsabilité compte), et conditions à remplir."""
    if case not in ("police", "driver", "passengers", "defense"):
        return None
    grid = explain.who_pays(p)
    return {"tiles": grid[fault], "needs": grid["needs"] if fault == "not_at_fault" else []}


def cg_document(p: Policy) -> dict:
    cg = p.cg
    mine = [p.row(c) for c in p.lines]
    others = [{"code": c, "title": g.title, "plain": g.plain, "ref": g.ref, "gcode": guarantee_code(c),
               "source": explain.guarantee_source(cg, g)}
              for c, g in cg.described().items() if c not in p.lines]
    s = cg.sections
    timeline = explain.timeline(cg)
    src = lambda x: explain.source(cg, x.get("ref"), [x["text"]])  # noqa: E731
    return {"source": cg.source(), "insurer": cg.label, "mine": mine, "others": others,
            "deadlines": s["deadlines"], "claim_steps": s["claim_steps"], "documents_needed": s["documents_needed"],
            "fault": s["fault"], "compensation": [x | {"src": src(x)} for x in s["compensation"]],
            "contract_life": [x | {"src": src(x)} for x in s["contract_life"]],
            "common_exclusions": [x | {"src": src(x)} for x in s["common_exclusions"]], "contacts": s["contacts"],
            "timeline": timeline, "steps": explain.steps(cg, timeline["items"]),
            "who_pays": explain.who_pays(p) if cg.kind == "official" else None,
            "territory": ({"code": cg.territory["code"], "source": src(cg.territory)} if cg.territory else None)}


def cp_document(p: Policy, vehicle_title: str) -> dict:
    cp, v = p.cp, p.cp.vehicle
    lines = []
    for s in cp.subscribed:
        code = s.canonical_code or p.tx.match_guarantee(s.label_raw)[0]
        g = p.cg.g(code)
        lines.append({"label": s.label_raw, "code": code, "gcode": guarantee_code(code),
                      "plafond_dh": explain.amount_of(s), "franchise": explain.franchise(s.deductible),
                      "title": (g.title or None) if g else None,
                      "plain": (g.plain or None) if g else None, "ref": (g.ref or None) if g else None,
                      "section": s.section, "limit": limit_text(s.insured_value), "deductible": deductible_text(s.deductible),
                      "premium": dh(s.annual_net_premium_mad) if s.annual_net_premium_mad else None,
                      "to_check": s.verification.confidence == "LOW"})
    examples = []
    dmg = p.main_damage()
    if dmg and p.line(dmg).deductible and p.line(dmg).deductible.has_value:
        for cost in (5000, 20000, 60000):
            y = you_pay(cost, p.line(dmg).deductible)
            if y is not None:
                examples.append({"cost": dh(cost), "you": dh(y), "insurer": dh(cost - y)})
    warnings = list(cp.warnings)
    if not p.complete:
        warnings.append("La liste des garanties n'a pas pu être lue en entier : une garantie absente ici n'est pas forcément absente du contrat.")
    if any(x["to_check"] for x in lines):
        warnings.append("Certaines valeurs ont été lues différemment lors des deux lectures : comparez-les avec votre document.")
    return {
        "contract": [r for r in [
            ("Assureur", p.cg.label), ("Produit", p.cg.product), ("N° de police", cp.policy_number),
            ("Début", _iso(cp.period_start)), ("Fin", _iso(cp.period_end)),
            ("Prime totale", dh(cp.total_premium_mad) if cp.total_premium_mad else None),
            ("Formule d'assistance", cp.assistance_formula)] if r[1]],
        "status": p.status(),
        "vehicle": [r for r in [
            ("Véhicule", vehicle_title), ("Immatriculation", v.registration),
            ("Mise en circulation", _iso(v.first_registration)), ("Énergie", (v.energy or "").capitalize() or None),
            ("Puissance fiscale", f"{_n(v.fiscal_power)} CV" if v.fiscal_power else None),
            ("Places", str(v.seats) if v.seats else None), ("Usage", v.usage),
            ("Valeur à neuf", dh(v.new_value_mad) if v.new_value_mad else None),
            ("Valeur vénale", dh(v.market_value_mad) if v.market_value_mad else None)] if r[1]],
        "lines": lines,
        "damage_example": {"guarantee": p.g(dmg).title, "deductible": deductible_text(p.line(dmg).deductible), "rows": examples,
                           "gcode": guarantee_code(dmg), "franchise": explain.franchise(p.line(dmg).deductible),
                           "plafond_dh": explain.amount_of(p.line(dmg))} if examples else None,
        "warnings": warnings,
        # Points à vérifier en codes (check.*) ; seule l'alerte « liste incomplète » de l'application reste en clair.
        "checks": explain.checks(cp, lines),
        "app_warnings": [w for w in warnings if w.startswith("La liste des garanties")],
        "period": {"start": _iso(cp.period_start), "end": _iso(cp.period_end)},
        "usage_code": "TOURISME" if (v.usage or "").strip().lower().startswith("tourisme") else None,
    }


# ---------------------------------------------------------------------------------------------- réponse complète


def vehicle_title(cp: CPExtraction) -> str:
    v = cp.vehicle
    name = " ".join(x.title() if x and x.isupper() else x for x in (v.make, v.model) if x)
    return name or "Mon véhicule"


def dossier(cp: CPExtraction, cg: InsurerCG, tx: Taxonomy, today: Optional[date] = None,
            ai: Optional[dict[str, dict]] = None) -> dict:
    """``ai`` : classements IA vérifiés pour cet assureur ({libellé normalisé: décision}, ica/ai_classifier.py)."""
    p = Policy(cp, cg, tx, today, ai)
    v = cp.vehicle
    title = vehicle_title(cp)
    views = {f"{c}:{f}": view(p, c, f) for c, _ in CASES for f in ("at_fault", "not_at_fault")}
    others = other_lines(p)
    extra = extra_cases(others)
    for c, o in zip(extra, others):
        for f in ("at_fault", "not_at_fault"):
            views[f"{c['id']}:{f}"] = extra_view(c["id"], f, o)
    detected = cp.insurer_id
    return {
        "insurer": {"id": cg.insurer_id, "label": cg.label, "source": cg.source()},
        "insurer_mismatch": bool(detected and detected != cg.insurer_id and cg.insurer_id != "other"),
        "detected_insurer": detected,
        "policy": {"document_id": cp.document_id, "number": cp.policy_number, "status": p.status(),
                   "period_start": _iso(cp.period_start), "period_end": _iso(cp.period_end),
                   "complete": p.complete, "rc_limit": limit_text(p.line("RC").insured_value) if p.has("RC") else None},
        "vehicle": {"title": title, "registration": v.registration,
                    "year": v.first_registration.year if v.first_registration else None,
                    "energy": (v.energy or "").capitalize() or None, "model_known": bool(v.model)},
        "cases": [{"id": c, "label": label, "status": case_status(p, c)} for c, label in CASES] + extra,
        "views": views,
        "other_lines": others,
        "rule_unmapped": p.rule_unmapped,
        "documents": {"cg": cg_document(p), "cp": cp_document(p, title)},
    }
