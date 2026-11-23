"""Modèles de domaine, en deux couches :

1. Preuves : SourceRef (document, page, ligne lue) -> produites par la lecture de la CP.
2. Faits   : CPExtraction -> produite par le modèle de vision puis vérifiée (double lecture).
La couverture affichée est calculée sans IA par coverage_view.py à partir de la CP et des CG intégrées.

Minimisation des données : aucun nom, CIN ou adresse n'est extrait ; seuls les éléments
nécessaires à l'interprétation du contrat sont modélisés.
"""
from __future__ import annotations

from datetime import date
from enum import Enum
from typing import Literal, Optional, Union

from pydantic import BaseModel, Field, computed_field, model_validator


# --------------------------------------------------------------------------- documents


class DocType(str, Enum):
    CG = "CG"  # Conditions Générales
    CP = "CP"  # Conditions Particulières
    ATTESTATION = "ATTESTATION"  # attestation d'assurance obligatoire (jaune) : ne liste aucune garantie
    AVENANT = "AVENANT"
    ANNEXE = "ANNEXE"
    UNKNOWN = "UNKNOWN"


class SourceRef(BaseModel):
    """Lien indissociable entre une information extraite et sa source."""

    document_id: str
    page: int = Field(ge=1, description="Page 1-indexée du PDF / de l'image")
    clause_id: Optional[str] = None
    quote: str = Field(min_length=2, description="Citation exacte du texte source")
    bbox: Optional[tuple[float, float, float, float]] = None


class VerificationStatus(str, Enum):
    NOT_CHECKED = "NOT_CHECKED"
    VERIFIED = "VERIFIED"
    QUOTE_NOT_FOUND = "QUOTE_NOT_FOUND"
    VALUE_MISMATCH = "VALUE_MISMATCH"


class Verification(BaseModel):
    status: VerificationStatus = VerificationStatus.NOT_CHECKED
    score: Optional[float] = None
    page_found: Optional[int] = None
    detail: Optional[str] = None

    user_confirmed: bool = False  # valeur saisie ou confirmée par l'assuré

    @property
    def failed(self) -> bool:
        return self.status in (VerificationStatus.QUOTE_NOT_FOUND, VerificationStatus.VALUE_MISMATCH)

    @computed_field  # exposé dans l'API : seule source du niveau de fiabilité affiché par tous les écrans
    @property
    def confidence(self) -> Literal["HIGH", "MEDIUM", "LOW"]:
        """HIGH : vérifié (double lecture concordante, citation retrouvée, ou confirmé par l'assuré).
        MEDIUM : lu mais non recoupé (lecture unique). LOW : lectures divergentes ou citation introuvable."""
        if self.user_confirmed or self.status == VerificationStatus.VERIFIED:
            return "HIGH"
        return "LOW" if self.failed else "MEDIUM"


# --------------------------------------------------------------------------- valeurs


class LimitBasis(str, Enum):
    FIXED = "FIXED"
    INSURED_VALUE = "INSURED_VALUE"
    MARKET_VALUE = "MARKET_VALUE"
    NEW_VALUE = "NEW_VALUE"
    UNLIMITED = "UNLIMITED"
    SEE_CP = "SEE_CP"  # « plafond mentionné aux Conditions Particulières »
    OTHER = "OTHER"


class Limit(BaseModel):
    amount_mad: Optional[float] = Field(None, ge=0)
    basis: LimitBasis = LimitBasis.OTHER
    raw: str = ""


class Deductible(BaseModel):
    percent: Optional[float] = Field(None, ge=0, le=100)
    minimum_mad: Optional[float] = Field(None, ge=0)
    maximum_mad: Optional[float] = Field(None, ge=0)
    fixed_mad: Optional[float] = Field(None, ge=0)
    basis: Optional[str] = None
    raw: str = ""

    @property
    def has_value(self) -> bool:
        return any(v is not None for v in (self.percent, self.minimum_mad, self.maximum_mad, self.fixed_mad))

    def signature(self) -> tuple:
        return (self.percent, self.minimum_mad, self.maximum_mad, self.fixed_mad)

    def describe_fr(self) -> str:
        parts: list[str] = []
        if self.percent is not None:
            parts.append(f"{self.percent:g} % du dommage")
        if self.minimum_mad is not None:
            parts.append(f"minimum {self.minimum_mad:,.0f} MAD".replace(",", " "))
        if self.maximum_mad is not None:
            parts.append(f"maximum {self.maximum_mad:,.0f} MAD".replace(",", " "))
        if self.fixed_mad is not None:
            parts.append("aucune franchise" if self.fixed_mad == 0 else f"{self.fixed_mad:,.0f} MAD".replace(",", " "))
        return ", ".join(parts) if parts else (self.raw or "non précisée")


# --------------------------------------------------------------------------- Conditions Particulières


class VehicleInfo(BaseModel):
    make: Optional[str] = None
    model: Optional[str] = None  # tel qu'imprimé (« LOGAN », « 208 »)
    version: Optional[str] = None  # finition / motorisation (« 1.5 dCi Laureate »)
    body_type: Optional[str] = None  # carrosserie imprimée (« berline », « CI », « break »)
    raw_designation: Optional[str] = None  # désignation complète du véhicule telle qu'imprimée
    vin: Optional[str] = None  # numéro de châssis (identifie le véhicule, pas la personne)
    registration: Optional[str] = None
    first_registration: Optional[date] = None
    energy: Optional[str] = None
    fiscal_power: Optional[float] = None
    seats: Optional[int] = None
    usage: Optional[str] = None
    new_value_mad: Optional[float] = None
    market_value_mad: Optional[float] = None


class SubscribedGuarantee(BaseModel):
    label_raw: str
    canonical_code: Optional[str] = None
    section: Literal["VEHICULE", "COMPLEMENTAIRE", "PERSONNES", "AVANTAGES", "AUTRE"] = "AUTRE"
    insured_value: Optional[Limit] = None
    deductible: Optional[Deductible] = None
    annual_net_premium_mad: Optional[float] = None
    source: SourceRef
    verification: Verification = Field(default_factory=Verification)


class CPExtraction(BaseModel):
    document_id: str
    insurer_id: Optional[str] = None
    product_id: Optional[str] = None
    policy_number: Optional[str] = None
    period_start: Optional[date] = None
    period_end: Optional[date] = None
    vehicle: VehicleInfo = Field(default_factory=VehicleInfo)
    subscribed: list[SubscribedGuarantee] = Field(default_factory=list)
    # True uniquement si le document présente la LISTE COMPLÈTE des garanties souscrites
    # (tableau de garanties lisible en entier). Une attestation jaune ou une photo partielle = False.
    guarantee_list_complete: bool = False
    assistance_formula: Optional[str] = None
    total_premium_mad: Optional[float] = None  # prime totale TTC à payer, telle qu'imprimée sur la CP
    total_premium_source: Optional[SourceRef] = None
    warnings: list[str] = Field(default_factory=list)
