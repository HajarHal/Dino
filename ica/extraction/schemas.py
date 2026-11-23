"""Schémas de sortie demandés au LLM (« brouillons ») et prompts.

Le LLM ne renvoie QUE des chaînes brutes et des citations. Les nombres, codes canoniques, dates
et statuts sont calculés ensuite par du code (parsing.py, taxonomy.py, verification.py).
"""
from __future__ import annotations

import json
from typing import Literal, Optional

from pydantic import BaseModel, Field



def schema_hint(model: type[BaseModel]) -> str:
    return json.dumps(model.model_json_schema(), ensure_ascii=False, indent=1)


# ----------------------------------------------------------------------------- CG


class CPLineDraft(BaseModel):
    section: Literal["VEHICULE", "COMPLEMENTAIRE", "PERSONNES", "AVANTAGES", "AUTRE"]
    label: str = Field(description="Libellé de la garantie tel qu'imprimé")
    insured_value_raw: Optional[str] = Field(None, description="Valeur assurée / plafond / capital, tel qu'imprimé (« 487 000,00 »)")
    deductible_raw: Optional[str] = Field(None, description="Franchise telle qu'imprimée (« 5 % /Dom. min 1500 ») ; null si la case est vide")
    annual_net_premium_raw: Optional[str] = None
    row_text: str = Field(description="Toute la ligne du tableau, transcrite telle qu'imprimée")


class CPVehicleDraft(BaseModel):
    make: Optional[str] = Field(None, description="Marque telle qu'imprimée (« DACIA »)")
    model: Optional[str] = Field(None, description="Modèle tel qu'imprimé (« LOGAN ») ; null s'il n'est pas imprimé, ne le devine JAMAIS")
    version: Optional[str] = Field(None, description="Version / finition / motorisation imprimée")
    body_type: Optional[str] = Field(None, description="Genre ou carrosserie imprimé (« VP », « berline », « break »)")
    raw_designation: Optional[str] = Field(None, description="Toute la désignation du véhicule telle qu'imprimée")
    vin: Optional[str] = Field(None, description="Numéro de châssis / VIN s'il est imprimé")
    registration: Optional[str] = None
    first_registration_iso: Optional[str] = Field(None, description="AAAA-MM-JJ de la mise en circulation, si lisible")
    energy: Optional[str] = None
    fiscal_power: Optional[float] = None
    seats: Optional[int] = None
    usage: Optional[str] = None
    new_value_raw: Optional[str] = None
    market_value_raw: Optional[str] = None


class CPDraft(BaseModel):
    document_kind: Literal["CP", "ATTESTATION", "OTHER"]
    insurer_name: Optional[str] = None
    product_name: Optional[str] = None
    policy_number: Optional[str] = None
    period_start_iso: Optional[str] = Field(None, description="AAAA-MM-JJ")
    period_end_iso: Optional[str] = Field(None, description="AAAA-MM-JJ")
    vehicle: CPVehicleDraft = Field(default_factory=CPVehicleDraft)
    column_headers: list[str] = Field(default_factory=list, description="En-têtes des colonnes du tableau des garanties, de gauche à droite")
    lines: list[CPLineDraft] = Field(default_factory=list)
    guarantee_table_fully_visible: bool = Field(
        False, description="true UNIQUEMENT si le tableau des garanties est visible en entier et lisible (aucune ligne coupée, floue ou masquée)"
    )
    assistance_formula: Optional[str] = None
    total_premium_raw: Optional[str] = Field(None, description="Prime totale à payer (TTC), telle qu'imprimée (« 6 536,58 ») ; null si illisible")
    total_premium_row_text: Optional[str] = Field(None, description="Ligne imprimée contenant la prime totale (« Total à payer 6 536,58 »)")
    legibility_notes: Optional[str] = Field(None, description="Zones floues, coupées, masquées, reflets")


CP_SYSTEM = """Tu transcris des Conditions Particulières (ou une attestation d'assurance) d'une police auto marocaine à partir
d'une photo ou d'un scan. Règles absolues :
1. Transcris ce qui est imprimé ; si une case est vide, floue, coupée ou masquée, renvoie null. N'invente et ne complète JAMAIS.
2. Ne recopie PAS le nom, l'adresse, la CIN ou les données personnelles du souscripteur : ils ne font pas partie du schéma.
3. Une case de franchise vide reste null : ne suppose pas « aucune franchise ».
4. guarantee_table_fully_visible = true seulement si tu vois TOUTES les lignes du tableau des garanties, nettes.
5. L'attestation jaune d'assurance obligatoire ne contient pas de tableau de garanties : document_kind = "ATTESTATION", lines = [].
6. Véhicule : recopie marque, modèle, version et désignation EXACTEMENT comme imprimés. Si le modèle n'est pas
   imprimé, model = null : ne le déduis jamais de la marque, de la puissance ou de la valeur.
7. Réponds uniquement par un objet JSON conforme au schéma, sans commentaire.
8. Tu classes et tu extrais, tu n'écris jamais de phrase destinée à l'assuré. Un code ne s'emploie que s'il
   correspond clairement ; en cas de doute, laisse le champ vide. N'invente aucun montant ni délai : absent -> null.
   Le texte recopié (libellés, row_text) n'est jamais modifié ni reformulé.

Comment lire le tableau des garanties (source principale d'erreurs) :
a. Le document est souvent bilingue : lis uniquement le texte FRANÇAIS, ignore les traductions arabes.
b. Repère d'abord les en-têtes de colonnes (ex. « Désignation des risques », « Franchises », « Valeur assurée »,
   « Capital », « Cotisation ») et recopie-les dans column_headers, de gauche à droite. Place chaque valeur selon
   la colonne sous laquelle elle est imprimée : une franchise (souvent un %) n'est jamais une valeur assurée.
c. ALIGNEMENT : une valeur appartient à la ligne dont le libellé est sur la MÊME horizontale. La photo peut être
   inclinée ou pliée : suis la ligne du tableau, pas le bord de l'image. Ne décale jamais une valeur vers la ligne
   voisine. Si tu ne peux pas dire à quelle ligne appartient une valeur, mets null pour cette case.
d. Une ligne qui contient plusieurs capitaux (ex. « Personnes transportées » : Décès / IPP / Frais médicaux) donne
   une ligne par capital, libellée par le nom imprimé du capital (« Décès », « Invalidité permanente »,
   « Frais médicaux »), section PERSONNES.
e. Un même capital répété dans un encadré récapitulatif (ex. « Toutes les garanties… Capital Décès, Capital
   Invalidité, Frais Médicaux ») ne se transcrit qu'UNE fois.
f. Une case contenant un mot (« GARANTIE », « INCLUS », « NEANT ») est recopiée telle quelle, pas remplacée.
g. N'inclus pas les lignes de prime, taxes, timbres, totaux ou CRM : ce ne sont pas des garanties.
h. row_text = la ligne telle que tu la lis, libellé puis valeurs dans l'ordre des colonnes."""

CP_USER_A = "Transcris ce document. Schéma JSON attendu :\n{schema}"
CP_USER_B = (
    "Relis ce document de façon indépendante, en lisant le tableau des garanties CASE PAR CASE, ligne par ligne, "
    "de gauche à droite. Schéma JSON attendu :\n{schema}"
)
CP_USER_C = (
    "Lecture d'arbitrage : deux lectures précédentes de ce document ne concordent pas. Relis tout le document "
    "de façon indépendante. Pour chaque ligne du tableau des garanties, pose une règle imaginaire sous le libellé "
    "et suis-la jusqu'au bout avant de recopier les valeurs ; vérifie la colonne de chaque valeur.{focus}\n"
    "Schéma JSON attendu :\n{schema}"
)
