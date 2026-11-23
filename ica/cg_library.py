"""Bibliothèque intégrée des Conditions Générales auto des assureurs marocains.

L'assuré choisit son assureur : ses CG sont déjà dans l'application, il n'a jamais à les importer.

  config/cg_library/pdf/<id>.pdf    le document original de l'assureur (affiché tel quel dans l'application) ;
  config/cg_library/text/<id>.txt   son texte, extrait du PDF (régénéré automatiquement s'il manque) ;
  config/cg_library/<id>.yaml       des EXTRAITS MOT POUR MOT de ce PDF, rangés par garantie et par rubrique,
                                    chacun avec son article ;
  config/cg_library/base.yaml       la structure seule (cas et pièces de la voiture de chaque garantie), sans texte.

Règle : aucune phrase n'est écrite par l'application ou par un modèle. Chaque extrait doit se retrouver dans le
PDF de l'assureur (``missing_excerpts`` ; un test le vérifie pour toute la bibliothèque). Un extrait peut être
raccourci avec « … » : chaque morceau doit alors figurer dans le PDF. Un assureur sans PDF n'affiche aucun texte
de CG : seules les informations de la CP sont montrées.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Iterator, Optional

import yaml

from .codes import classify
from .parsing import normalize

LIB_DIR = Path(__file__).resolve().parent.parent / "config" / "cg_library"
PDF_DIR = LIB_DIR / "pdf"
TEXT_DIR = LIB_DIR / "text"

# Rubriques des CG affichées dans « Mes documents ».
LIST_SECTIONS = ("claim_steps", "documents_needed", "common_exclusions")
TABLE_SECTIONS = ("deadlines", "compensation", "contract_life")
FAULT_KEYS = ("at_fault", "not_at_fault", "needs")


@dataclass(frozen=True)
class Guarantee:
    code: str
    title: str
    plain: str
    covers: tuple[str, ...]
    not_covered: tuple[str, ...]
    conditions: tuple[str, ...]
    ref: str
    cases: tuple[str, ...]
    parts: tuple[str, ...] = ()
    part_notes: dict = field(default_factory=dict)  # pièce -> extrait des CG (exclusion ou condition)
    needs_third_party: bool = False
    parts_note: str = ""  # extrait des CG qui vaut pour toutes les pièces (ex. tiers identifié exigé)
    official: bool = False  # True : textes extraits des CG de l'assureur
    # Clauses classées (code, extrait) : cov.* couvert, ex.* exclu, cond.* condition, note.* bon à savoir.
    cover_codes: tuple[tuple[str, str], ...] = ()
    exclusion_codes: tuple[tuple[str, str], ...] = ()
    condition_codes: tuple[tuple[str, str], ...] = ()
    note_codes: tuple[tuple[str, str], ...] = ()
    unclassified: tuple[str, ...] = ()  # clauses qu'aucun code ne couvre : affichées telles quelles

    def to_dict(self) -> dict:
        return {"code": self.code, "title": self.title, "plain": self.plain, "covers": list(self.covers),
                "not_covered": list(self.not_covered), "conditions": list(self.conditions), "ref": self.ref,
                "official": self.official}


@dataclass
class InsurerCG:
    insurer_id: str
    label: str
    full_name: Optional[str]
    kind: str  # « official » : CG de l'assureur intégrées ; « missing » : pas encore de PDF
    document: Optional[str]
    version: Optional[str]
    product: Optional[str]
    pdf: Optional[str]  # nom du fichier dans config/cg_library/pdf/
    guarantees: dict[str, Guarantee]
    sections: dict
    bonus_malus: Optional[dict] = None  # coefficients chiffrés + extraits ; needs_review tant qu'un humain n'a pas validé
    territory: Optional[dict] = None  # {code (terr.*), text, ref}

    def g(self, code: Optional[str]) -> Optional[Guarantee]:
        return self.guarantees.get(code) if code else None

    def described(self) -> dict[str, Guarantee]:
        """Garanties pour lesquelles les CG de l'assureur fournissent un texte."""
        return {c: g for c, g in self.guarantees.items() if g.official}

    def source(self) -> dict:
        return {"kind": self.kind, "document": self.document, "version": self.version, "product": self.product,
                "pdf_url": f"/api/cg/{self.insurer_id}/pdf" if self.pdf else None}


# --------------------------------------------------------------------------------------------- lecture


def _read(name: str) -> dict:
    p = LIB_DIR / f"{name}.yaml"
    return (yaml.safe_load(p.read_text(encoding="utf-8")) or {}) if p.exists() else {}


@lru_cache(maxsize=1)
def registry() -> dict[str, dict]:
    return _read("insurers")["insurers"]


def _spec(iid: str) -> dict:
    entry = registry().get(iid) or {}
    return _read(entry["cg"]) if entry.get("cg") else {}


def insurers() -> list[dict]:
    """Liste affichée au démarrage : l'assureur, et si ses Conditions Générales sont intégrées."""
    out = []
    for iid, v in registry().items():
        src = _spec(iid).get("source") or {}
        out.append({"id": iid, "label": v["label"], "full_name": v.get("full_name"),
                    "cg_kind": "official" if src.get("pdf") else "missing", "product": src.get("product")})
    return out


def match_insurer(text: Optional[str]) -> Optional[str]:
    """Identifiant d'assureur pour un nom lu sur une CP (alias en mots entiers)."""
    if not text:
        return None
    norm = f" {normalize(text)} "
    for iid, v in registry().items():
        if iid in norm.split() or any(a and f" {normalize(a)} " in norm for a in v.get("aliases", [])):
            return iid
    return None


def _items(v, ref: str = "", families: tuple[str, ...] = ()) -> list[dict]:
    """Liste d'extraits → [{text, ref, codes}]. Accepte {ref, items: [...]} ou une simple liste ; une entrée peut
    porter des codes ({code|codes, text}), validés par ica.codes (code inconnu -> aucun code)."""
    if not v:
        return []
    if isinstance(v, dict):
        ref, v = v.get("ref", ref), v.get("items", [])
    out = []
    for x in v:
        if families:
            _, codes, text = classify(x, families)
        else:
            codes, text = [], (x if isinstance(x, str) else x["text"])
        out.append({"text": text, "ref": (x.get("ref") if isinstance(x, dict) else None) or ref, "codes": codes})
    return out


def _sorted_codes(items, families) -> dict[str, list]:
    """Clauses d'une garantie rangées par famille de code ; les autres vont dans « unclassified »."""
    out: dict[str, list] = {f: [] for f in families}
    out["unclassified"] = []
    for x in items:
        fam, codes, text = classify(x, families)
        if fam:
            out[fam] += [(c, text) for c in codes]
        else:
            out["unclassified"].append(text)
    return out


def _texts(lst) -> tuple[str, ...]:
    return tuple(x if isinstance(x, str) else x["text"] for x in lst)


@lru_cache(maxsize=32)
def load(insurer_id: Optional[str]) -> InsurerCG:
    reg = registry()
    iid = insurer_id if insurer_id in reg else "other"
    entry = reg[iid]
    base = _read("base")["guarantees"]
    spec = _spec(iid)
    src = spec.get("source") or {}
    official = bool(src.get("pdf"))
    own = spec.get("guarantees") or {} if official else {}

    guarantees: dict[str, Guarantee] = {}
    for code in dict.fromkeys([*base, *own]):
        b, d = base.get(code) or {}, own.get(code) or {}
        cov = _sorted_codes(d.get("covers", []), ("cov",))
        exc = _sorted_codes(d.get("not_covered", []), ("ex",))
        con = _sorted_codes(d.get("conditions", []), ("cond", "note"))
        guarantees[code] = Guarantee(
            code=code, title=d.get("title", ""), plain=d.get("plain", ""), covers=_texts(d.get("covers", [])),
            not_covered=_texts(d.get("not_covered", [])), conditions=_texts(d.get("conditions", [])),
            cover_codes=tuple(cov["cov"]), exclusion_codes=tuple(exc["ex"]), condition_codes=tuple(con["cond"]),
            note_codes=tuple(con["note"]),
            unclassified=tuple(cov["unclassified"] + exc["unclassified"] + con["unclassified"]),
            ref=d.get("ref", ""), cases=tuple(d.get("cases", b.get("cases", []))),
            parts=tuple(d.get("parts", b.get("parts", []))), part_notes=dict(d.get("part_notes") or {}),
            needs_third_party=bool(d.get("needs_third_party", b.get("needs_third_party"))),
            parts_note=d.get("parts_note", ""), official=bool(d),
        )

    sec = spec if official else {}
    families = {"claim_steps": ("step",), "documents_needed": ("cond",), "common_exclusions": ("ex",)}
    sections: dict = {k: _items(sec.get(k), families=families[k]) for k in LIST_SECTIONS}
    for k in TABLE_SECTIONS:
        sections[k] = [dict(x) for x in sec.get(k) or []]
    for x in sections["deadlines"]:  # délai chiffré : « cinq (5) jours » -> 5 DAYS
        x["n"], x["unit"] = parse_delay(x.get("value", ""))
    fault = sec.get("fault") or {}
    sections["fault"] = {k: _items(fault.get(k), fault.get("ref", ""), ("cond",) if k == "needs" else ("fault",))
                         for k in FAULT_KEYS}
    sections["contacts"] = sec.get("contacts") or []
    return InsurerCG(
        insurer_id=iid, label=entry["label"], full_name=entry.get("full_name"),
        kind="official" if official else "missing", document=src.get("document"), version=src.get("version"),
        product=src.get("product"), pdf=src.get("pdf") if official else None,
        guarantees=guarantees, sections=sections, bonus_malus=(sec.get("bonus_malus") or None),
        territory=(sec.get("territory") or None),
    )


def pdf_path(insurer_id: str) -> Optional[Path]:
    cg = load(insurer_id)
    p = PDF_DIR / cg.pdf if cg.pdf else None
    return p if p and p.exists() else None


# --------------------------------------------------------------------------------------------- vérification


def compact(s: str) -> str:
    """Texte réduit à ses lettres et chiffres : insensible aux accents, à la casse, à la ponctuation, aux
    retours à la ligne et aux césures du PDF (« ga-\\nrantie »)."""
    s = unicodedata.normalize("NFKD", s.replace("œ", "oe").replace("Œ", "oe").replace("æ", "ae"))
    s = "".join(c for c in s if not unicodedata.combining(c)).lower()
    return re.sub(r"[^a-z0-9]", "", s)


@lru_cache(maxsize=16)
def source_text(pdf_name: str) -> str:
    """Texte compacté du PDF (cache dans text/<nom>.txt)."""
    txt = TEXT_DIR / (Path(pdf_name).stem + ".txt")
    if not txt.exists():
        import pymupdf
        with pymupdf.open(PDF_DIR / pdf_name) as doc:
            body = "".join(f"\n\n=== Page {i + 1} ===\n" + p.get_text() for i, p in enumerate(doc))
        TEXT_DIR.mkdir(parents=True, exist_ok=True)
        txt.write_text(body, encoding="utf-8")
    body = re.sub(r"\n\n=== Page \d+ ===\n", " ", txt.read_text(encoding="utf-8"))
    return compact(body)


def excerpts(spec: dict) -> Iterator[tuple[str, str]]:
    """(où, extrait) pour chaque texte d'un fichier assureur qui doit venir du PDF."""
    for code, g in (spec.get("guarantees") or {}).items():
        for k in ("title", "plain", "parts_note"):
            if g.get(k):
                yield f"{code}.{k}", g[k]
        for k in ("covers", "not_covered", "conditions"):
            for x in g.get(k) or []:
                yield f"{code}.{k}", x if isinstance(x, str) else x.get("text")
        for z, x in (g.get("part_notes") or {}).items():
            yield f"{code}.part_notes.{z}", x
    for k in LIST_SECTIONS:
        for x in _items(spec.get(k)):
            yield k, x["text"]
    for k in FAULT_KEYS:
        for x in _items((spec.get("fault") or {}).get(k)):
            yield f"fault.{k}", x["text"]
    for k in TABLE_SECTIONS:
        for x in spec.get(k) or []:
            yield f"{k}.{x.get('title')}", x["text"]
    for x in (spec.get("bonus_malus") or {}).get("texts", []):
        yield "bonus_malus", x
    if spec.get("territory"):
        yield "territory", spec["territory"]["text"]


BONUS_FIELDS = ("material_fault_increase", "bodily_fault_increase", "max_coefficient", "no_claim_coefficient")
_NUMBERS = {"un": 1, "deux": 2, "trois": 3, "quatre": 4, "cinq": 5, "six": 6, "sept": 7, "huit": 8, "dix": 10,
            "quinze": 15, "vingt": 20, "trente": 30, "soixante": 60}
_UNITS = {"heure": "HOURS", "heures": "HOURS", "jour": "DAYS", "jours": "DAYS", "mois": "MONTHS", "an": "YEARS",
          "ans": "YEARS", "annee": "YEARS", "annees": "YEARS"}


def parse_delay(value: str) -> tuple[Optional[int], Optional[str]]:
    """« cinq (5) jours » -> (5, DAYS) ; « quarante huit (48) heures » -> (48, HOURS) ; illisible -> (None, None)."""
    words = normalize(value).split()
    unit = next((_UNITS[w] for w in words if w in _UNITS), None)
    m = re.search(r"\((\d+)\)|\b(\d+)\b", value)
    n = int(m.group(1) or m.group(2)) if m else next((_NUMBERS[w] for w in words if w in _NUMBERS), None)
    return (n, unit) if n and unit else (None, None)


def _fr_number(v: float) -> list[str]:
    """Écritures possibles d'un coefficient dans les CG : 0.2 -> « 0,20 », « 0,2 »."""
    return [f"{v:.2f}".replace(".", ","), f"{v:g}".replace(".", ",")]


def missing_excerpts(insurer_id: str) -> list[str]:
    """Extraits du fichier de l'assureur introuvables dans son PDF (doit rester vide)."""
    spec = _spec(insurer_id)
    pdf = (spec.get("source") or {}).get("pdf")
    if not pdf:
        return []
    text = source_text(pdf)
    bad = []
    for where, x in excerpts(spec):
        if not isinstance(x, str):
            bad.append(f"{where}: pas une phrase ({x!r})")
            continue
        for frag in (f for f in re.split(r"…|\.\.\.", x) if compact(f)):
            if compact(frag) not in text:
                bad.append(f"{where}: « {frag.strip()[:90]} »")
    bm = spec.get("bonus_malus") or {}
    joined = " ".join(bm.get("texts", []))
    for f in BONUS_FIELDS:  # chaque coefficient chiffré doit être écrit dans un extrait
        if bm.get(f) is not None and not any(n in joined for n in _fr_number(bm[f])):
            bad.append(f"bonus_malus.{f}: {bm[f]} absent des extraits")
    if bm.get("no_claim_months") and f"({bm['no_claim_months']})" not in joined:
        bad.append(f"bonus_malus.no_claim_months: {bm['no_claim_months']} absent des extraits")
    for k in TABLE_SECTIONS:  # la valeur mise en avant (« cinq (5) jours ») doit être dans son extrait
        for x in spec.get(k) or []:
            if x.get("value") and compact(x["value"]) not in compact(x["text"]):
                bad.append(f"{k}.{x.get('title')}: valeur « {x['value']} » absente de l'extrait")
    return bad



@lru_cache(maxsize=16)
def _pages(pdf_name: str) -> dict[int, str]:
    source_text(pdf_name)  # crée le texte s'il manque
    raw = (TEXT_DIR / (Path(pdf_name).stem + ".txt")).read_text(encoding="utf-8")
    parts = re.split(r"\n\n=== Page (\d+) ===\n", raw)[1:]
    return {int(parts[i]): compact(parts[i + 1]) for i in range(0, len(parts), 2)}


@lru_cache(maxsize=4096)
def page_of(pdf_name: Optional[str], excerpt: str) -> Optional[int]:
    """Page du PDF où se trouve un extrait (premier morceau avant « … ») ; None si introuvable."""
    if not pdf_name or not excerpt:
        return None
    frag = compact(re.split(r"…|\.\.\.", excerpt)[0])
    if len(frag) < 8:
        return None
    return next((n for n, t in _pages(pdf_name).items() if frag in t), None)
