"""Lecture des CP (LLM simulé), client LLM, dépôt cloisonné, photo du véhicule."""
import json
from datetime import date
from pathlib import Path

import pytest

from ica.db import AccessDenied, Repository, make_session_factory
from ica.domain import CPExtraction, DocType, VerificationStatus
from ica.extraction.cp_extractor import cp_from_drafts, extract_cp
from ica.extraction.llm import LLMError, MockLLM, OpenAICompatibleClient, call_validated, make_llm_from_env
from ica.extraction.schemas import CPDraft
from ica import cg_library
from ica.coverage_view import Policy
from ica.pipeline import Pipeline

SAMPLE = Path(__file__).resolve().parent.parent / "samples" / "cp_atlantasanad_draft.json"


def _jpeg(w=800, h=500):
    import io
    from PIL import Image
    buf = io.BytesIO()
    Image.new("RGB", (w, h), "orange").save(buf, "JPEG")
    return buf.getvalue()


def test_call_validated_repairs_then_fails_cleanly():
    good = SAMPLE.read_text(encoding="utf-8")
    llm = MockLLM(["pas du json", f"```json\n{good}\n```"])
    assert call_validated(llm, CPDraft, system="s", user="u").lines
    assert "n'est pas valide" in llm.calls[1]["user"]
    with pytest.raises(LLMError):
        call_validated(MockLLM(["x", "y", "z"]), CPDraft, system="s", user="u")


def test_openai_compatible_provider_uses_environment(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "openai_compatible")
    monkeypatch.setenv("LLM_API_KEY", "test-key")
    monkeypatch.setenv("LLM_MODEL", "openai/gpt-oss-120b")
    monkeypatch.setenv("LLM_VISION_MODEL", "google/gemini-2.5-flash")
    monkeypatch.setenv("LLM_MAX_TOKENS", "4096")
    monkeypatch.delenv("LLM_BASE_URL", raising=False)

    client = make_llm_from_env()

    assert isinstance(client, OpenAICompatibleClient)
    assert client.model == "openai/gpt-oss-120b"
    assert client.vision_model == "google/gemini-2.5-flash"
    assert client.max_tokens == 4096
    assert client.base_url == "https://openrouter.ai/api/v1"


def test_openai_compatible_client_sends_chat_and_image(monkeypatch):
    calls = []

    def fake_post_json(url, headers, payload, timeout, max_retries):
        calls.append((url, headers, payload))
        return {"choices": [{"message": {"content": [{"type": "text", "text": '{"ok": true}'}]}}]}

    monkeypatch.setattr("ica.extraction.llm._post_json", fake_post_json)
    client = OpenAICompatibleClient(api_key="test-key", model="text-model", vision_model="vision-model")

    result = client.generate(system="system prompt", user="user prompt", images=[b"image"])

    assert result == '{"ok": true}'
    url, headers, payload = calls[0]
    assert url == "https://openrouter.ai/api/v1/chat/completions"
    assert headers["Authorization"] == "Bearer test-key"
    assert payload["model"] == "vision-model"
    assert payload["max_tokens"] == 4096
    assert payload["messages"][0] == {"role": "system", "content": "system prompt"}
    image = payload["messages"][1]["content"][1]["image_url"]["url"]
    assert image.startswith("data:image/jpeg;base64,")
    client.generate(system="system prompt", user="text only")
    assert calls[1][2]["model"] == "text-model"


@pytest.mark.parametrize("value", ["invalid", "0", "-1"])
def test_openai_compatible_rejects_invalid_max_tokens(monkeypatch, value):
    monkeypatch.setenv("LLM_MAX_TOKENS", value)

    with pytest.raises(LLMError, match="LLM_MAX_TOKENS"):
        OpenAICompatibleClient(api_key="test-key", model="test-model")


def test_real_cp_sample_double_read_agreement(tx):
    d = CPDraft.model_validate_json(SAMPLE.read_text(encoding="utf-8"))
    cp = cp_from_drafts(d, d, document_id="cp", page=1, tx=tx)
    assert cp.insurer_id == "atlantasanad" and cp.product_id == "atlantasanad_multirisques_auto"
    assert cp.guarantee_list_complete and len(cp.subscribed) == 14
    assert all(s.canonical_code for s in cp.subscribed)
    dta = next(s for s in cp.subscribed if s.canonical_code == "ALL_ACCIDENTS")
    assert (dta.deductible.percent, dta.deductible.minimum_mad, dta.insured_value.amount_mad) == (5.0, 1500.0, 487000.0)
    assert next(s for s in cp.subscribed if s.canonical_code == "FIRE").deductible is None


def test_cp_double_read_disagreement_blocks_the_line(tx):
    a = json.loads(SAMPLE.read_text(encoding="utf-8"))
    b = json.loads(json.dumps(a))
    b["lines"][2]["insured_value_raw"] = "478 000,00"  # la 2e lecture lit un autre montant pour le Vol
    b["lines"][2]["row_text"] = "Vol 478 000,00 5 % /Dom."
    cp = extract_cp([b"img"], llm=MockLLM([a, b]), taxonomy=tx, document_id="cp")
    theft = next(s for s in cp.subscribed if s.canonical_code == "THEFT")
    assert theft.verification.status == VerificationStatus.VALUE_MISMATCH
    # La ligne reste affichée, signalée « à vérifier » dans Mes documents.
    p = Policy(cp, cg_library.load("atlantasanad"), tx)
    assert p.row("THEFT")["to_check"] and not p.row("FIRE")["to_check"]


def test_cp_value_not_in_its_own_row_is_rejected(tx):
    a = json.loads(SAMPLE.read_text(encoding="utf-8"))
    a["lines"][2]["insured_value_raw"] = "999 000,00"
    cp = cp_from_drafts(CPDraft.model_validate(a), None, document_id="cp", page=1, tx=tx)
    assert next(s for s in cp.subscribed if s.canonical_code == "THEFT").verification.status == VerificationStatus.VALUE_MISMATCH


def test_attestation_proves_rc_only_and_list_is_never_complete(tx):
    d = CPDraft(document_kind="ATTESTATION", insurer_name="AXA Assurance Maroc", period_start_iso="2021-01-16", period_end_iso="2022-01-15")
    cp = cp_from_drafts(d, d, document_id="att", page=1, tx=tx)
    assert [s.canonical_code for s in cp.subscribed] == ["RC"] and not cp.guarantee_list_complete
    assert cp.insurer_id == "axa_maroc" and cp.product_id is None


def test_repository_isolates_users(tmp_path):
    Session = make_session_factory(f"sqlite:///{tmp_path/'t.db'}")
    with Session() as s:
        alice, bob = Repository(s, "alice"), Repository(s, "bob")
        contract = alice.create_contract("Audi")
        doc = alice.add_document(contract_id=contract.id, doc_type="CP", filename="cp.jpg", data=b"abc", storage_path="x", page_count=1,
                                 insurer_id=None, product_id=None, classification={})
        cp = CPExtraction(document_id=doc.id)
        assert alice.save_extraction(doc.id, "CP_EXTRACTION", cp, "v").version == 1
        assert alice.save_extraction(doc.id, "CP_EXTRACTION", cp, "v").version == 2
        assert alice.latest_extraction(doc.id, "CP_EXTRACTION", CPExtraction).document_id == doc.id
        for call in (lambda: bob.get_document(doc.id), lambda: bob.get_contract(contract.id), lambda: bob.list_documents(contract.id),
                     lambda: bob.latest_extraction(doc.id, "CP_EXTRACTION", CPExtraction), lambda: bob.delete_document(doc.id)):
            with pytest.raises(AccessDenied):
                call()


def test_cp_extraction_releases_sqlite_write_lock(tmp_path, monkeypatch, tx):
    Session = make_session_factory(f"sqlite:///{tmp_path/'t.db'}")
    with Session() as session:
        repo = Repository(session, "alice")
        contract = repo.create_contract("Audi")
        session.commit()

        concurrent_write_completed = False

        def fake_extract_cp(images, *, llm, taxonomy, document_id, double_read):
            nonlocal concurrent_write_completed
            with Session() as concurrent_session:
                connection = concurrent_session.connection()
                assert connection.exec_driver_sql("PRAGMA busy_timeout").scalar_one() == 30000
                connection.exec_driver_sql("PRAGMA busy_timeout=1000")
                concurrent_repo = Repository(concurrent_session, "alice")
                concurrent_repo.add_document(
                    contract_id=contract.id, doc_type="CP", filename="other.jpg", data=b"other",
                    storage_path="other", page_count=1, insurer_id=None, product_id=None, classification={},
                )
                concurrent_session.commit()
            concurrent_write_completed = True
            return CPExtraction(document_id=document_id)

        monkeypatch.setattr("ica.pipeline.extract_cp", fake_extract_cp)
        pipeline = Pipeline(repo, tx, tmp_path, llm=MockLLM([]))
        document_id, _ = pipeline.process_cp_images([b"image"], contract.id)
        session.commit()

        assert concurrent_write_completed
        assert repo.get_document(document_id).filename == "cp.jpg"


def test_cp_third_read_arbitrates_a_disagreement(tx):
    a = json.loads(SAMPLE.read_text(encoding="utf-8"))
    b = json.loads(json.dumps(a))
    b["lines"][2]["insured_value_raw"] = "478 000,00"
    b["lines"][2]["row_text"] = "Vol 478 000,00 5 % /Dom."
    c = json.loads(json.dumps(a))  # la lecture d'arbitrage confirme la 1re lecture
    llm = MockLLM([a, b, c])
    cp = extract_cp([b"img"], llm=llm, taxonomy=tx, document_id="cp")
    assert len(llm.calls) == 3 and "Vol" in llm.calls[2]["user"]
    theft = next(s for s in cp.subscribed if s.canonical_code == "THEFT")
    assert theft.verification.status == VerificationStatus.VERIFIED and "2 lectures sur 3" in theft.verification.detail
    assert cp.guarantee_list_complete


def test_cp_third_read_can_side_with_the_second_read(tx):
    a = json.loads(SAMPLE.read_text(encoding="utf-8"))
    b = json.loads(json.dumps(a))
    a["lines"][2]["insured_value_raw"] = "478 000,00"  # la 1re lecture est isolée
    a["lines"][2]["row_text"] = "Vol 478 000,00 5 % /Dom."
    c = json.loads(json.dumps(b))
    cp = extract_cp([b"img"], llm=MockLLM([a, b, c]), taxonomy=tx, document_id="cp")
    theft = next(s for s in cp.subscribed if s.canonical_code == "THEFT")
    assert theft.verification.status == VerificationStatus.VERIFIED and theft.insured_value.amount_mad == 487000.0


def test_cp_three_different_reads_stay_flagged(tx):
    a = json.loads(SAMPLE.read_text(encoding="utf-8"))
    b, c = json.loads(json.dumps(a)), json.loads(json.dumps(a))
    b["lines"][2]["insured_value_raw"], b["lines"][2]["row_text"] = "478 000,00", "Vol 478 000,00"
    c["lines"][2]["insured_value_raw"], c["lines"][2]["row_text"] = "418 000,00", "Vol 418 000,00"
    cp = extract_cp([b"img"], llm=MockLLM([a, b, c]), taxonomy=tx, document_id="cp")
    theft = next(s for s in cp.subscribed if s.canonical_code == "THEFT")
    assert theft.verification.status == VerificationStatus.VALUE_MISMATCH and not cp.guarantee_list_complete


def test_photo_is_upscaled_and_reoriented():
    import io
    from PIL import Image
    from ica.media import to_jpeg_pages
    buf = io.BytesIO()
    img = Image.new("RGB", (720, 960), "white")
    exif = img.getexif(); exif[0x0112] = 6  # orientation : rotation de 90°
    img.save(buf, "JPEG", exif=exif)
    out = Image.open(io.BytesIO(to_jpeg_pages(buf.getvalue(), "cp.jpg")[0]))
    assert max(out.size) == 2400 and out.width > out.height


def test_daily_quota_429_fails_fast_but_minute_limit_is_retried():
    from ica.extraction.llm import _is_daily_quota
    assert _is_daily_quota('{"message": "Quota exceeded ... description: Generate content requests per day limit exceeded on Free Tier"}')
    assert not _is_daily_quota('{"message": "Resource exhausted: requests per minute"}')


def test_openai_compatible_reads_reasoning_field_and_explains_empty_answer(monkeypatch):
    import ica.extraction.llm as llm_mod
    client = OpenAICompatibleClient(api_key="k", model="m", max_tokens=100)
    monkeypatch.setattr(llm_mod, "_post_json", lambda *a, **k: {"choices": [{"message": {"content": None, "reasoning_content": '{"a": 1}'}}]})
    assert client.generate(system="s", user="u") == '{"a": 1}'
    budgets = []
    def cut(url, headers, payload, *a):
        budgets.append(payload["max_tokens"])
        return {"choices": [{"message": {"content": '{"a": ['}, "finish_reason": "length"}]}
    monkeypatch.setattr(llm_mod, "_post_json", cut)
    with pytest.raises(LLMError, match="LLM_MAX_TOKENS"):
        client.generate(system="s", user="u")
    assert budgets == [100, 200]  # une relance avec budget doublé, puis échec explicite


def test_double_read_pairs_repeated_labels_and_tolerates_wording(tx):
    a = json.loads(SAMPLE.read_text(encoding="utf-8"))
    a["lines"].append({"section": "PERSONNES", "label": "Frais médicaux", "insured_value_raw": "20 000,00", "row_text": "Frais médicaux 20 000,00"})
    a["lines"].append({"section": "PERSONNES", "label": "Frais médicaux", "insured_value_raw": "30 000,00", "row_text": "Frais médicaux 30 000,00"})
    b = json.loads(json.dumps(a))
    b["lines"][-1], b["lines"][-2] = b["lines"][-2], b["lines"][-1]  # ordre différent
    b["lines"][0]["label"] = "Responsabilite civile."  # graphie différente, même valeur
    cp = cp_from_drafts(CPDraft.model_validate(a), CPDraft.model_validate(b), document_id="cp", page=1, tx=tx)
    assert all(not s.verification.failed for s in cp.subscribed) and cp.guarantee_list_complete


def test_vehicle_model_disagreement_between_reads_is_not_kept(tx):
    a = json.loads(SAMPLE.read_text(encoding="utf-8"))
    a["vehicle"]["model"] = "A3"
    b = json.loads(json.dumps(a))
    b["vehicle"]["model"] = "A4"
    cp = cp_from_drafts(CPDraft.model_validate(a), CPDraft.model_validate(b), document_id="cp", page=1, tx=tx)
    assert cp.vehicle.model is None and any("model" in w for w in cp.warnings)


def test_dropped_connection_is_retried_then_reported_as_llm_error(monkeypatch):
    import http.client

    import pytest

    from ica.extraction import llm as llm_mod

    calls = {"n": 0}

    class Resp:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self):
            calls["n"] += 1
            if calls["n"] == 1:
                raise http.client.IncompleteRead(b"{")
            return b'{"ok": true}'

    monkeypatch.setattr(llm_mod.urllib.request, "urlopen", lambda req, timeout: Resp())
    monkeypatch.setattr(llm_mod.time, "sleep", lambda s: None)
    assert llm_mod._post_json("http://x", {}, {}, 5, 3) == {"ok": True}
    calls["n"] = -100  # échecs persistants
    monkeypatch.setattr(Resp, "read", lambda self: (_ for _ in ()).throw(ConnectionResetError("reset")))
    with pytest.raises(llm_mod.LLMError):
        llm_mod._post_json("http://x", {}, {}, 5, 2)


def test_ai_anchor_detection_and_safe_fallback():
    from ica.extraction.llm import MockLLM
    from ica.vehicle_photo import detect_anchors
    good = {"visible": True, "points": {"windshield": [0.5, 0.3], "headlights": [0.2, 0.55], "wheels": [0.4, 0.8],
                                        "mirrors": [1.4, 0.2], "interior": None}}
    pts, origin = detect_anchors(_jpeg(), MockLLM([good]))
    assert origin == "ai" and pts["windshield"] == [0.5, 0.3]
    assert pts["mirrors"] is None and pts["rear_bumper"] is None  # hors image ou non visible : jamais placé au hasard
    pts, origin = detect_anchors(_jpeg(), MockLLM([{"visible": False, "points": {}}]))
    assert origin == "default" and pts["windshield"] is not None
    assert detect_anchors(_jpeg(), None)[1] == "default"
