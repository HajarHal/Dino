"""Extraction des Conditions Particulières (photos, scans ou PDF) et des attestations.

Fiabilité : les CP arrivent le plus souvent en photos de téléphone (reflets, pliures, masquage).
Une lecture unique par LLM peut halluciner un chiffre. Deux lectures INDEPENDANTES (consignes
différentes) sont donc comparées case par case : une ligne n'est « vérifiée » que si les deux
lectures concordent. Toute divergence marque la ligne, que le moteur de règles écartera.

Les nombres ne viennent jamais du LLM : il renvoie le texte imprimé, parsing.py calcule les valeurs.
"""
from __future__ import annotations

from datetime import date
from typing import Optional

from ..domain import (
    CPExtraction, SourceRef, SubscribedGuarantee, VehicleInfo, Verification, VerificationStatus,
)
from rapidfuzz import fuzz

from ..parsing import normalize, parse_amount, parse_deductible, parse_limit
from ..taxonomy import Taxonomy
from ..verification import verify_numbers, verify_quote
from .llm import LLMClient, LLMError, LLMFatalError, LLMInterrupted, call_validated
from .schemas import CP_SYSTEM, CP_USER_A, CP_USER_B, CP_USER_C, CPDraft, CPLineDraft, schema_hint

ATTESTATION_QUOTE = "Le présent document fait présumer que l'obligation d'assurance prévue à l'article 120 de la loi n° 17-99"


def _iso(value: Optional[str]) -> Optional[date]:
    try:
        return date.fromisoformat(value) if value else None
    except ValueError:
        return None


def _line_signature(line: CPLineDraft, tx: Taxonomy) -> tuple:
    code, _ = tx.match_guarantee(line.label)
    lim = parse_limit(line.insured_value_raw) if line.insured_value_raw else None
    ded = parse_deductible(line.deductible_raw) if line.deductible_raw else None
    return (code or line.label.strip().lower(), lim.amount_mad if lim else None, ded.signature() if ded else None)


def _numbers(line: CPLineDraft) -> list[Optional[float]]:
    lim = parse_limit(line.insured_value_raw) if line.insured_value_raw else None
    ded = parse_deductible(line.deductible_raw) if line.deductible_raw else None
    nums: list[Optional[float]] = [lim.amount_mad if lim else None]
    if ded:
        nums += [ded.percent, ded.minimum_mad, ded.maximum_mad, ded.fixed_mad]
    return nums


def _vehicle(d) -> VehicleInfo:
    return VehicleInfo(
        make=d.make, model=d.model, version=d.version, body_type=d.body_type, raw_designation=d.raw_designation,
        vin=d.vin, registration=d.registration, first_registration=_iso(d.first_registration_iso), energy=d.energy,
        fiscal_power=d.fiscal_power, seats=d.seats, usage=d.usage,
        new_value_mad=parse_amount(d.new_value_raw) if d.new_value_raw else None,
        market_value_mad=parse_amount(d.market_value_raw) if d.market_value_raw else None,
    )


def cp_from_drafts(
    first: CPDraft, second: Optional[CPDraft], *, document_id: str, page: int, tx: Taxonomy,
    page_texts: Optional[dict[int, str]] = None, third: Optional[CPDraft] = None,
) -> CPExtraction:
    insurer = tx.detect_insurer(first.insurer_name or "") or tx.detect_insurer(first.product_name or "")
    product = tx.detect_product(f"{first.product_name or ''} {first.insurer_name or ''}", insurer)
    if product and not insurer:
        insurer = tx.products[product]["insurer"]
    cp = CPExtraction(
        document_id=document_id, insurer_id=insurer, product_id=product, policy_number=first.policy_number,
        period_start=_iso(first.period_start_iso), period_end=_iso(first.period_end_iso),
        vehicle=_vehicle(first.vehicle), assistance_formula=first.assistance_formula,
    )
    if first.total_premium_raw and first.total_premium_row_text:
        total = parse_amount(first.total_premium_raw)
        check = verify_numbers([total], first.total_premium_row_text)
        same = second is None or (second.total_premium_raw and parse_amount(second.total_premium_raw) == total)
        if total is not None and not check.failed and same:  # retenue seulement si les lectures concordent
            cp.total_premium_mad = total
            cp.total_premium_source = SourceRef(document_id=document_id, page=page, quote=first.total_premium_row_text.strip())
    if first.legibility_notes:
        cp.warnings.append(f"Lisibilité : {first.legibility_notes}")
    if first.document_kind == "OTHER":
        cp.warnings.append("Le document n'est ni une CP ni une attestation d'assurance.")
        return cp

    if first.document_kind == "ATTESTATION":
        cp.warnings.append(
            "Attestation d'assurance obligatoire : elle prouve la souscription de la responsabilité civile "
            "pour la période indiquée, pas les autres garanties."
        )
        cp.subscribed.append(SubscribedGuarantee(
            label_raw="Responsabilité civile (attestation d'assurance obligatoire)", canonical_code="RC", section="VEHICULE",
            source=SourceRef(document_id=document_id, page=page, quote=ATTESTATION_QUOTE),
            verification=Verification(status=VerificationStatus.NOT_CHECKED, detail="mention imprimée sur l'attestation"),
        ))
        return cp  # guarantee_list_complete reste False

    pairs = _pair_reads(first.lines, second.lines, tx) if second is not None else {}
    pairs3 = _pair_reads(first.lines, third.lines, tx) if third is not None else {}
    unresolved = 0

    def own_checks(line: CPLineDraft) -> Verification:
        checks: list[Verification] = [verify_numbers(_numbers(line), line.row_text)]
        if page_texts:  # CP au format PDF avec couche texte : la ligne doit exister dans le document
            checks.append(verify_quote(line.row_text, page_texts, page))
        return _merge_checks(checks)

    def add(line: CPLineDraft, ver: Verification) -> None:
        code, _score = tx.match_guarantee(line.label)
        cp.subscribed.append(SubscribedGuarantee(
            label_raw=line.label.strip(), canonical_code=code, section=line.section,
            insured_value=parse_limit(line.insured_value_raw) if line.insured_value_raw else None,
            deductible=parse_deductible(line.deductible_raw) if line.deductible_raw else None,
            annual_net_premium_mad=parse_amount(line.annual_net_premium_raw) if line.annual_net_premium_raw else None,
            source=SourceRef(document_id=document_id, page=page, quote=line.row_text.strip()), verification=ver,
        ))

    for idx, line in enumerate(first.lines):
        ver = own_checks(line)
        if second is not None and not ver.failed:
            other, arb = pairs.get(idx), pairs3.get(idx)
            if other is not None and _values(other) == _values(line):
                if ver.status == VerificationStatus.VERIFIED:
                    ver.detail = "double lecture concordante"
            elif arb is not None and _values(arb) == _values(line):
                if ver.status == VerificationStatus.VERIFIED:
                    ver.detail = "2 lectures sur 3 concordantes (arbitrage)"
            elif arb is not None and other is not None and _values(arb) == _values(other) and not own_checks(other).failed:
                line, ver = other, own_checks(other)  # la 1re lecture était isolée : on retient la majorité
                if ver.status == VerificationStatus.VERIFIED:
                    ver.detail = "2 lectures sur 3 concordantes (arbitrage)"
            elif other is None:
                ver = Verification(status=VerificationStatus.QUOTE_NOT_FOUND, detail="ligne absente de la seconde lecture")
                unresolved += 1
            else:
                ver = Verification(status=VerificationStatus.VALUE_MISMATCH, detail="les lectures divergent sur les valeurs")
                unresolved += 1
        elif second is None and ver.status == VerificationStatus.VERIFIED and not page_texts:
            ver = Verification(status=VerificationStatus.NOT_CHECKED, detail="lecture unique d'une image : à confirmer")
        add(line, ver)

    # Lignes vues par la 2de lecture seulement : retenues si l'arbitrage les confirme à l'identique.
    if second is not None:
        used = {id(v) for v in pairs.values()}
        extras = [l for l in second.lines if id(l) not in used]
        if third is not None and extras:
            used3 = {id(v) for v in pairs3.values()}
            remaining3 = [l for l in third.lines if id(l) not in used3]
            for j, arb in _pair_reads(extras, remaining3, tx).items():
                if _values(arb) == _values(extras[j]) and not own_checks(extras[j]).failed:
                    add(extras[j], Verification(status=VerificationStatus.VERIFIED, score=100.0,
                                                detail="2 lectures sur 3 concordantes (arbitrage)"))
                    extras[j] = None  # type: ignore[call-overload]
            extras = [l for l in extras if l is not None]
        unresolved += len(extras)

    complete = first.guarantee_table_fully_visible and bool(first.lines)
    if second is not None:
        complete = complete and second.guarantee_table_fully_visible and unresolved == 0
        if unresolved:
            cp.warnings.append("Les lectures ne listent pas exactement les mêmes garanties : liste non considérée comme complète.")
    cp.guarantee_list_complete = complete
    _check_vehicle_reads(first, second, cp, third)
    return cp


def needs_arbitration(first: CPDraft, second: CPDraft, tx: Taxonomy) -> list[str]:
    """Libellés sur lesquels deux lectures divergent (vide : accord complet)."""
    pairs = _pair_reads(first.lines, second.lines, tx)
    disputed = [l.label for i, l in enumerate(first.lines) if i not in pairs or _values(pairs[i]) != _values(l)]
    used = {id(v) for v in pairs.values()}
    disputed += [l.label for l in second.lines if id(l) not in used]
    for name in ("make", "model"):
        a, b = getattr(first.vehicle, name), getattr(second.vehicle, name)
        if a and b and normalize(a) != normalize(b):
            disputed.append(f"véhicule : {name}")
    return disputed


def _key(line: CPLineDraft, tx: Taxonomy) -> str:
    code, _ = tx.match_guarantee(line.label)
    return code or normalize(line.label)


def _values(line: CPLineDraft) -> tuple:
    lim = parse_limit(line.insured_value_raw) if line.insured_value_raw else None
    ded = parse_deductible(line.deductible_raw) if line.deductible_raw else None
    return (lim.amount_mad if lim else None, ded.signature() if ded else None)


LABEL_FUZZ = 85


def _pair_reads(first: list[CPLineDraft], second: list[CPLineDraft], tx: Taxonomy) -> dict[int, CPLineDraft]:
    """Apparie chaque ligne de la 1re lecture à une ligne de la 2de, une seule fois chacune.

    Ordre de préférence : même garantie ET mêmes valeurs ; même garantie ; libellés proches (≥ 85)
    dans la même section. Les VALEURS ne sont jamais assouplies : elles sont comparées ensuite.
    """
    free = list(range(len(second)))
    pairs: dict[int, CPLineDraft] = {}
    keys2 = [_key(l, tx) for l in second]

    def take(i: int, j: int) -> None:
        pairs[i] = second[j]
        free.remove(j)

    for strict in (True, False):
        for i, line in enumerate(first):
            if i in pairs:
                continue
            k = _key(line, tx)
            for j in free:
                if keys2[j] == k and (not strict or _values(second[j]) == _values(line)):
                    take(i, j)
                    break
    for i, line in enumerate(first):
        if i in pairs:
            continue
        a = normalize(line.label)
        cands = [(fuzz.ratio(a, normalize(second[j].label)), j) for j in free if second[j].section == line.section]
        if cands:
            score, j = max(cands)
            if score >= LABEL_FUZZ:
                take(i, j)
    return pairs


def _check_vehicle_reads(first: CPDraft, second: Optional[CPDraft], cp: CPExtraction, third: Optional[CPDraft] = None) -> None:
    """Marque et neutralise une marque/un modèle lus différemment (majorité 2 sur 3 si arbitrage)."""
    if second is None:
        return
    for name in ("make", "model"):
        a, b = getattr(first.vehicle, name), getattr(second.vehicle, name)
        c = getattr(third.vehicle, name) if third is not None else None
        if a and b and normalize(a) != normalize(b) and c and normalize(c) in (normalize(a), normalize(b)):
            setattr(cp.vehicle, name, c)
            cp.warnings.append(f"Véhicule : « {name} » retenu à la majorité de trois lectures (« {c} »).")
        elif a and b and normalize(a) != normalize(b):
            setattr(cp.vehicle, name, None)
            cp.warnings.append(f"Véhicule : les deux lectures divergent sur le champ « {name} » (« {a} » / « {b} ») : valeur non retenue.")
        elif a and not b:
            cp.warnings.append(f"Véhicule : « {name} » lu une seule fois (« {a} ») : à confirmer.")


def _merge_checks(checks: list[Verification]) -> Verification:
    for c in checks:
        if c.failed:
            return c
    return checks[0] if checks else Verification()


def extract_cp(
    images: list[bytes], *, llm: LLMClient, taxonomy: Taxonomy, document_id: str, double_read: bool = True,
    page_texts: Optional[dict[int, str]] = None,
) -> CPExtraction:
    """``images`` : une image JPEG par page/photo. Plusieurs images sont fusionnées en une seule CP."""
    parts: list[CPExtraction] = []
    hint = schema_hint(CPDraft)
    for idx, img in enumerate(images, start=1):
        a = call_validated(llm, CPDraft, system=CP_SYSTEM, user=CP_USER_A.format(schema=hint), images=[img])
        b = call_validated(llm, CPDraft, system=CP_SYSTEM, user=CP_USER_B.format(schema=hint), images=[img]) if double_read else None
        c, note = None, None
        disputed = needs_arbitration(a, b, taxonomy) if b is not None else []
        if disputed:
            focus = " Lignes à lire avec une attention particulière : " + ", ".join(dict.fromkeys(disputed)) + "."
            try:
                c = call_validated(llm, CPDraft, system=CP_SYSTEM, user=CP_USER_C.format(schema=hint, focus=focus), images=[img])
            except (LLMFatalError, LLMInterrupted):
                raise
            except LLMError as e:  # l'arbitrage est un bonus : son échec laisse les lignes divergentes marquées
                note = f"Lecture d'arbitrage impossible ({str(e)[:120]}) : lignes divergentes laissées à vérifier."
        part = cp_from_drafts(a, b, document_id=document_id, page=idx, tx=taxonomy, page_texts=page_texts, third=c)
        if note:
            part.warnings.append(note)
        parts.append(part)
    return merge_cp_parts(parts)


def merge_cp_parts(parts: list[CPExtraction]) -> CPExtraction:
    if len(parts) == 1:
        return parts[0]
    base = parts[0].model_copy(deep=True)
    for p in parts[1:]:
        base.insurer_id = base.insurer_id or p.insurer_id
        base.product_id = base.product_id or p.product_id
        base.policy_number = base.policy_number or p.policy_number
        base.period_start = base.period_start or p.period_start
        base.period_end = base.period_end or p.period_end
        if base.total_premium_mad is None and p.total_premium_mad is not None:
            base.total_premium_mad, base.total_premium_source = p.total_premium_mad, p.total_premium_source
        for field_name in VehicleInfo.model_fields:
            if getattr(base.vehicle, field_name) is None:
                setattr(base.vehicle, field_name, getattr(p.vehicle, field_name))
        base.subscribed += p.subscribed
        base.warnings += p.warnings
        base.guarantee_list_complete = base.guarantee_list_complete or p.guarantee_list_complete
    return base
