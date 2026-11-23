"""Codes fermés des explications : chaque liste est lue dans copy/fr.json (source unique des textes).

  cov.X   ce qui est couvert          ex.X    ce qui n'est pas couvert     cond.X  condition pour être payé
  note.X  « bon à savoir »            delay.X délai                        step.X  étape après un accident
  fault.X ligne « qui paie quoi »     terr.X  pays couverts                check.X point à vérifier sur la CP
  g.X     garantie (GuaranteeCode)

Une clause des CG classée sous un code inconnu est rejetée par la validation (``classify``) : elle est alors
affichée telle quelle, sous « Autres conditions à lire ».
"""
from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Optional

import yaml
from pydantic import BaseModel, ValidationError, field_validator

ROOT = Path(__file__).resolve().parent.parent
COPY = ROOT / "copy" / "fr.json"
GUARANTEE_TABLE = ROOT / "config" / "guarantee_codes.yaml"


@lru_cache(maxsize=1)
def copy_texts() -> dict[str, str]:
    return json.loads(COPY.read_text(encoding="utf-8"))


@lru_cache(maxsize=16)
def codes(prefix: str) -> tuple[str, ...]:
    """Codes d'une famille, dans l'ordre de copy/fr.json (« ex » -> ALCOOL, STUPEFIANTS…)."""
    out = []
    for k in copy_texts():
        m = re.match(rf"^{re.escape(prefix)}\.([A-Z][A-Z0-9_]*)(\.title)?$", k)
        if m and (prefix != "g" or m.group(2)):
            out.append(m.group(1))
    return tuple(dict.fromkeys(out))


@lru_cache(maxsize=1)
def guarantee_table() -> dict[str, str]:
    """Garantie reconnue (taxonomie) -> GuaranteeCode."""
    raw = yaml.safe_load(GUARANTEE_TABLE.read_text(encoding="utf-8"))
    out: dict[str, str] = {}
    for gc, tax in raw.items():
        assert gc in codes("g"), f"GuaranteeCode inconnu dans {GUARANTEE_TABLE.name} : {gc}"
        for t in tax:
            out.setdefault(t, gc)
    return out


def guarantee_code(tax_code: Optional[str]) -> Optional[str]:
    return guarantee_table().get(tax_code or "")


class Classified(BaseModel):
    """Clause classée : un ou plusieurs codes d'UNE famille, et le texte verbatim."""
    family: str
    codes: list[str]
    text: str

    @field_validator("codes")
    @classmethod
    def _known(cls, v, info):
        fam = info.data.get("family", "")
        allowed = set(codes(fam))
        bad = [c for c in v if c not in allowed]
        if bad or not v:
            raise ValueError(f"code hors énumération {fam}: {bad}")
        return v


def classify(item, families: tuple[str, ...]) -> tuple[Optional[str], list[str], str]:
    """(famille, codes, texte). Entrée YAML : « texte », ou {code|codes, text}. Le code peut porter sa famille
    (« note.VALEUR_A_NEUF ») ; sinon la première famille de ``families`` est utilisée. Code inconnu -> (None, [], texte)."""
    if isinstance(item, str):
        return None, [], item
    text = str(item.get("text", ""))
    raw = item.get("codes") or ([item["code"]] if item.get("code") else [])
    fam = families[0]
    names = []
    for c in raw:
        if "." in str(c):
            fam, c = str(c).split(".", 1)
        names.append(str(c))
    if fam not in families:
        return None, [], text
    try:
        c = Classified(family=fam, codes=names, text=text)
    except ValidationError:
        return None, [], text
    return c.family, c.codes, c.text
