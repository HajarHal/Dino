"""Chargement de config/taxonomy.yaml (garanties, produits) et config/cg_library/insurers.yaml (assureurs),
et rapprochement des libellés de CP vers les codes canoniques."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Optional

import yaml
from rapidfuzz import fuzz

from .parsing import normalize

DEFAULT_PATH = Path(__file__).resolve().parent.parent / "config" / "taxonomy.yaml"
INSURERS_PATH = DEFAULT_PATH.parent / "cg_library" / "insurers.yaml"
FUZZY_THRESHOLD = 92  # volontairement élevé : un libellé douteux reste « non mappé » et est signalé


@dataclass(frozen=True)
class GuaranteeDef:
    code: str
    label_fr: str
    category: str
    aliases: tuple[str, ...]
    keywords: tuple[tuple[str, ...], ...] = ()  # groupes de mots : tous présents dans le libellé (mots entiers)


@dataclass
class Taxonomy:
    guarantees: dict[str, GuaranteeDef]
    insurers: dict[str, dict]
    products: dict[str, dict]
    _alias_index: dict[str, str] = field(default_factory=dict, repr=False)
    KEYWORD_SCORE = 80.0

    def __post_init__(self) -> None:
        for code, g in self.guarantees.items():
            for alias in (g.label_fr, *g.aliases):
                key = normalize(alias)
                prev = self._alias_index.get(key)
                if prev and prev != code:
                    raise ValueError(f"Alias ambigu « {alias} » : {prev} et {code}")
                self._alias_index[key] = code

    # ---- garanties
    def match_guarantee(self, label: str) -> tuple[Optional[str], float]:
        """(code, score). Alias exact = 100 ; flou >= seuil ; sinon (None, meilleur score)."""
        if not normalize(label):
            return None, 0.0
        # essais successifs : libellé complet, puis sans parenthèse finale (« Incendie (Inc) »)
        variants = [label, re.sub(r"\([^)]*\)", " ", label)]
        key = ""
        for variant in variants:
            key = normalize(variant)
            key = re.sub(r"^(la |les |l )?garanties? ", "", key).strip() or key
            if key in self._alias_index:
                return self._alias_index[key], 100.0
        best_code, best = None, 0.0
        for alias, code in self._alias_index.items():
            if len(alias) <= 3:  # évite les faux positifs sur sigles (rc, dc, pt...)
                continue
            score = fuzz.ratio(key, alias)
            if score > best:
                best_code, best = code, score
        if best >= FUZZY_THRESHOLD:
            return best_code, best
        return self.match_keywords(label), best

    def match_keywords(self, label: str) -> Optional[str]:
        """Dernier recours, sans IA : mots-clés du libellé (« Incapacité » -> capital invalidité, cas Conducteur).

        Le groupe de mots le plus long l'emporte (« vol » + « roues » bat « vol »). Si deux garanties différentes
        restent à égalité, rien n'est choisi : la ligne reste non reconnue.
        """
        words = set(normalize(re.sub(r"\([^)]*\)", " ", label)).split()) | set(normalize(label).split())
        best: dict[str, int] = {}
        for code, g in self.guarantees.items():
            for group in g.keywords:
                if set(group) <= words:
                    best[code] = max(best.get(code, 0), len(group))
        if not best:
            return None
        top = max(best.values())
        winners = [c for c, n in best.items() if n == top]
        return winners[0] if len(winners) == 1 else None

    def label_fr(self, code: str) -> str:
        return self.guarantees[code].label_fr if code in self.guarantees else code

    def category(self, code: str) -> str:
        return self.guarantees[code].category if code in self.guarantees else "NON_PHYSICAL"

    # ---- assureurs / produits
    def detect_insurer(self, text: str) -> Optional[str]:
        """Assureur le plus fréquemment cité (mots entiers) dans le texte, ou None."""
        return self._detect(text, {k: v["aliases"] for k, v in self.insurers.items()})

    def detect_product(self, text: str, insurer_id: Optional[str] = None) -> Optional[str]:
        pool = {
            k: v["aliases"]
            for k, v in self.products.items()
            if insurer_id is None or v["insurer"] == insurer_id
        }
        return self._detect(text, pool)

    @staticmethod
    def _detect(text: str, pool: dict[str, list[str]]) -> Optional[str]:
        norm = " " + normalize(text) + " "
        scores: dict[str, int] = {}
        for key, aliases in pool.items():
            for alias in aliases:
                n = norm.count(f" {normalize(alias)} ")
                if n:
                    scores[key] = scores.get(key, 0) + n
        return max(scores, key=scores.get) if scores else None


@lru_cache(maxsize=4)
def load_taxonomy(path: str | Path = DEFAULT_PATH) -> Taxonomy:
    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    guarantees = {
        code: GuaranteeDef(code, g["label_fr"], g["category"], tuple(g.get("aliases", [])),
                           tuple(tuple(normalize(w) for w in k.split()) for k in g.get("keywords", [])))
        for code, g in raw["guarantees"].items()
    }
    insurers = {k: v for k, v in yaml.safe_load(INSURERS_PATH.read_text(encoding="utf-8"))["insurers"].items() if k != "other"}
    products = raw["products"]
    for pid, p in products.items():
        if p["insurer"] not in insurers:
            raise ValueError(f"Produit {pid} : assureur inconnu {p['insurer']}")
    return Taxonomy(guarantees, insurers, products)
