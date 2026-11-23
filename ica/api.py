"""API HTTP (FastAPI) : aucune logique métier ici.

Lancement :  uvicorn ica.api:app --port 8000      (sert aussi l'interface construite dans frontend/dist)

Parcours : l'assuré choisit son assureur (ses Conditions Générales sont intégrées), ajoute sa CP (photo, scan
ou PDF, lue par le modèle de vision), puis consulte « Ma couverture » et « Mes documents », tous deux calculés
par ``GET /api/dossier`` sans aucun appel à l'IA.
"""
from __future__ import annotations

import contextvars
import json
import logging
import os
import threading
import time
import traceback
import uuid
from datetime import date
from pathlib import Path
from typing import Optional

from fastapi import Depends, FastAPI, File, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import ai_classifier, auth, cars, cg_library, unrecognised
from .coverage_view import dossier
from .db import AccessDenied, ProcessingRun, Repository, make_session_factory
from .domain import CPExtraction
from .extraction.cp_extractor import cp_from_drafts
from .extraction.llm import LLMError, make_llm_from_env, set_activity_reporter
from .extraction.schemas import CPDraft
from .media import cp_page_images, load_env, to_jpeg_pages
from .pipeline import Pipeline
from .taxonomy import load_taxonomy
from .vehicle_photo import DEFAULT_ANCHORS, PhotoStore, _clean, detect_anchors, normalize_photo

ROOT = Path(__file__).resolve().parent.parent
DATA = Path(os.environ.get("ICA_DATA_DIR") or ROOT / "data")  # dossier des données (base, fichiers, profil)
SAMPLE_CP = ROOT / "samples" / "cp_atlantasanad_draft.json"
DIST = ROOT / "frontend" / "dist"

load_env(ROOT / ".env")

_log = logging.getLogger("ica")
if not _log.handlers:
    _h = logging.StreamHandler()
    _h.setFormatter(logging.Formatter("%(asctime)s  %(message)s", "%H:%M:%S"))
    _log.addHandler(_h)
    _log.setLevel(logging.INFO)
DATA.mkdir(exist_ok=True)
Session = make_session_factory(f"sqlite:///{DATA / 'ica.db'}")
TX = load_taxonomy()

# Routes sans compte : liste des assureurs, connexion, photos du catalogue, PDF publics des CG.
PUBLIC = ("/api/meta", "/api/auth/", "/api/cars/", "/api/cg/")


async def _guard(request: Request) -> None:
    """Toute autre route /api exige une session : l'utilisateur connecté devient l'utilisateur courant."""
    path = request.url.path
    if not path.startswith("/api/") or path.startswith(PUBLIC):
        return
    with Session() as s:
        acc = auth.user_for(s, request.cookies.get(auth.COOKIE))
    if acc is None:
        raise HTTPException(401, "Connexion requise")
    auth.CURRENT_USER.set(acc.id)


app = FastAPI(title="Ma couverture auto", version="0.4", dependencies=[Depends(_guard)])


@app.on_event("startup")
def _on_startup() -> None:
    """Une lecture restée « RUNNING » a été interrompue par l'arrêt du serveur."""
    with Session() as s:
        s.query(ProcessingRun).filter(ProcessingRun.status == "RUNNING").update(
            {"status": "FAILED", "error": "interrompue : le serveur a été arrêté pendant la lecture"})
        s.commit()


# --------------------------------------------------------------------------- utilitaires


def _llm():
    try:
        return make_llm_from_env(), None
    except LLMError as e:
        return None, str(e)


def _uid() -> str:
    u = auth.CURRENT_USER.get()
    if not u:
        raise HTTPException(401, "Connexion requise")
    return u


def _thread(fn) -> None:
    """Tâche de fond qui garde l'utilisateur de la requête."""
    threading.Thread(target=contextvars.copy_context().run, args=(fn,), daemon=True).start()


class Ctx:
    def __init__(self, with_llm: bool = False):
        self.s = Session()
        self.repo = Repository(self.s, _uid())
        self.contract = self.repo.default_contract()
        self.s.commit()
        self.pipe = Pipeline(self.repo, TX, DATA / "files", _llm()[0] if with_llm else None)

    def __enter__(self) -> "Ctx":
        return self

    def __exit__(self, *exc) -> None:
        self.s.close()

    def cp(self, doc_id: str) -> Optional[CPExtraction]:
        try:
            return self.repo.latest_extraction(doc_id, "CP_EXTRACTION", CPExtraction)
        except AccessDenied:
            raise HTTPException(404, "document introuvable")

    def cps(self) -> list:
        docs = [d for d in self.repo.list_documents(self.contract.id) if d.doc_type == "CP"]
        return sorted(docs, key=lambda d: d.created_at, reverse=True)


# --------------------------------------------------------------------------- profil (assureur, CP active, modèle)

def _profile_path() -> Path:
    """Un profil par compte. Le profil d'avant les comptes (data/profile.json) revient au premier compte."""
    uid = _uid()
    path = DATA / "profiles" / f"{uid}.json"
    legacy = DATA / "profile.json"
    if uid == auth.LEGACY_USER and legacy.exists() and not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        legacy.replace(path)
    return path


def _profile() -> dict:
    try:
        return json.loads(_profile_path().read_text(encoding="utf-8"))
    except (FileNotFoundError, ValueError):
        return {}


def _save_profile(p: dict) -> dict:
    path = _profile_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(p, ensure_ascii=False), encoding="utf-8")
    return p


# --------------------------------------------------------------------------- comptes


class Credentials(BaseModel):
    email: str
    password: str


def _set_cookie(request: Request, response: Response, token: str) -> None:
    response.set_cookie(auth.COOKIE, token, max_age=auth.SESSION_DAYS * 86400, httponly=True, samesite="lax",
                        secure=request.url.scheme == "https", path="/")


@app.post("/api/auth/signup")
def signup(body: Credentials, request: Request, response: Response) -> dict:
    with Session() as s:
        try:
            acc = auth.signup(s, body.email, body.password)
        except auth.AuthError as e:
            raise HTTPException(400, str(e))
        _set_cookie(request, response, auth.open_session(s, acc.id))
        return {"email": acc.email}


@app.post("/api/auth/login")
def login(body: Credentials, request: Request, response: Response) -> dict:
    with Session() as s:
        try:
            acc = auth.login(s, body.email, body.password)
        except auth.AuthError as e:
            raise HTTPException(401, str(e))
        _set_cookie(request, response, auth.open_session(s, acc.id))
        return {"email": acc.email}


@app.post("/api/auth/logout")
def logout(request: Request, response: Response) -> dict:
    """« Quitter » : ferme la session. Les contrats restent enregistrés dans le compte."""
    with Session() as s:
        auth.close_session(s, request.cookies.get(auth.COOKIE))
    response.delete_cookie(auth.COOKIE, path="/")
    return {"ok": True}


@app.get("/api/auth/me")
def me(request: Request) -> dict:
    with Session() as s:
        acc = auth.user_for(s, request.cookies.get(auth.COOKIE))
    if acc is None:
        raise HTTPException(401, "Non connecté")
    return {"email": acc.email}


class ProfileBody(BaseModel):
    insurer_id: Optional[str] = None
    cp_id: Optional[str] = None
    car_key: Optional[str] = None


@app.get("/api/profile")
def get_profile() -> dict:
    return _profile()


@app.put("/api/profile")
def put_profile(body: ProfileBody) -> dict:
    p = _profile()
    changes = body.model_dump(exclude_unset=True)
    if "insurer_id" in changes and changes["insurer_id"] not in cg_library.registry():
        raise HTTPException(400, "assureur inconnu")
    if changes.get("car_key") and changes["car_key"] not in cars.catalog()["photos"]:
        raise HTTPException(400, "modèle inconnu")
    p.update(changes)
    return _save_profile(p)


# --------------------------------------------------------------------------- méta


@app.get("/api/meta")
def meta() -> dict:
    llm, err = _llm()
    return {"llm_available": llm is not None, "llm_error": err,
            "insurers": cg_library.insurers(), "car_models": cars.models()}


# --------------------------------------------------------------------------- tâches de fond

_JOBS: dict[str, dict] = {}
_LOCK = threading.Lock()


def _start_job(kind: str, target) -> str:
    job_id = uuid.uuid4().hex
    with _LOCK:
        _JOBS[job_id] = {"id": job_id, "user": _uid(), "kind": kind, "status": "RUNNING", "message": "Lecture de votre contrat",
                         "result": None, "error": None, "activity": None, "started_at": time.time()}

    def activity(msg: str) -> None:
        with _LOCK:
            _JOBS[job_id]["activity"] = msg

    def run() -> None:
        set_activity_reporter(activity)
        try:
            result = target()
            with _LOCK:
                _JOBS[job_id].update(status="DONE", message="Terminé", result=result)
        except Exception as e:
            traceback.print_exc()
            with _LOCK:
                _JOBS[job_id].update(status="FAILED", error=str(e)[:600])
        finally:
            set_activity_reporter(None)

    _thread(run)
    return job_id


@app.get("/api/jobs/{job_id}")
def job(job_id: str) -> dict:
    with _LOCK:
        j = _JOBS.get(job_id)
        if j is None or j["user"] != _uid():
            raise HTTPException(404, "tâche inconnue")
        out = dict(j)
        out.pop("user")
    out["elapsed_s"] = round(time.time() - out.pop("started_at"))
    return out


# --------------------------------------------------------------------------- Conditions Particulières


def _summary(ctx: Ctx, d) -> dict:
    cp = ctx.cp(d.id)
    return {"id": d.id, "filename": d.filename, "created_at": d.created_at.isoformat() if d.created_at else None,
            "pages": d.page_count, "read": cp is not None,
            "insurer_id": cp.insurer_id if cp else None,
            "policy_number": cp.policy_number if cp else None,
            "period_end": cp.period_end.isoformat() if cp and cp.period_end else None,
            "vehicle": " ".join(x for x in (cp.vehicle.make, cp.vehicle.model) if x) if cp else None,
            "lines": len(cp.subscribed) if cp else 0}


@app.get("/api/documents")
def documents() -> list[dict]:
    with Ctx() as ctx:
        return [_summary(ctx, d) for d in ctx.cps()]


@app.post("/api/documents/cp")
async def upload_cp(files: list[UploadFile] = File(...)) -> dict:
    llm, err = _llm()
    if llm is None:
        raise HTTPException(400, f"La lecture d'une CP nécessite une clé API ({err}).")
    images: list[bytes] = []
    for f in files:
        try:
            images += to_jpeg_pages(await f.read(), f.filename or "cp.jpg")
        except Exception:
            raise HTTPException(400, f"Fichier illisible : {f.filename}. Utilisez une photo (JPEG, PNG) ou un PDF.")
    if not images:
        raise HTTPException(400, "Aucune page trouvée dans les fichiers envoyés.")
    name = files[0].filename or "cp.jpg"

    def target():
        with Ctx(with_llm=True) as c:
            doc_id, cp = c.pipe.process_cp_images(images, c.contract.id, filename=name)
            c.s.commit()
        p = _profile()
        p["cp_id"] = doc_id
        p.setdefault("insurer_id", cp.insurer_id)
        _save_profile(p)
        return {"document_id": doc_id, "lines": len(cp.subscribed), "detected_insurer": cp.insurer_id}

    return {"job_id": _start_job("read_cp", target)}


@app.post("/api/documents/cp/sample")
def load_sample() -> dict:
    with Ctx() as ctx:
        raw = SAMPLE_CP.read_bytes()
        draft = CPDraft.model_validate_json(raw)
        cp = cp_from_drafts(draft, draft, document_id="exemple", page=1, tx=TX)
        doc_id = ctx.pipe.import_cp_extraction(cp, ctx.contract.id, "CP AtlantaSanad (exemple)", raw)
        ctx.s.commit()
    _save_profile({**_profile(), "cp_id": doc_id, "insurer_id": cp.insurer_id})
    return {"document_id": doc_id}


@app.delete("/api/documents/{doc_id}")
def delete_document(doc_id: str) -> dict:
    with Ctx() as ctx:
        try:
            d = ctx.repo.get_document(doc_id)
        except AccessDenied:
            raise HTTPException(404, "document introuvable")
        files = [Path(d.storage_path), *[Path(x) for x in (d.classification or {}).get("page_files", [])]]
        ctx.repo.delete_document(doc_id)
        ctx.s.commit()
    for f in files:
        f.unlink(missing_ok=True)
    _photos().delete(doc_id)
    p = _profile()
    if p.get("cp_id") == doc_id:
        p.pop("cp_id")
        _save_profile(p)
    return {"ok": True}


@app.get("/api/documents/{doc_id}/pages/{page}")
def page_image(doc_id: str, page: int) -> Response:
    with Ctx() as ctx:
        try:
            d = ctx.repo.get_document(doc_id)
        except AccessDenied:
            raise HTTPException(404, "document introuvable")
        imgs = cp_page_images(d.storage_path, (d.classification or {}).get("page_files"))
    if not 1 <= page <= len(imgs):
        raise HTTPException(404, "page non disponible")
    return Response(imgs[page - 1], media_type="image/jpeg")


# --------------------------------------------------------------------------- dossier : « Ma couverture » + « Mes documents »


@app.get("/api/dossier")
def get_dossier(cp: Optional[str] = None, as_of: Optional[date] = None) -> dict:
    prof = _profile()
    with Ctx() as ctx:
        docs = ctx.cps()
        ids = [d.id for d in docs]
        cp_id = cp or (prof.get("cp_id") if prof.get("cp_id") in ids else None) or next(
            (d.id for d in docs if ctx.cp(d.id) is not None), None)
        if cp_id is None:
            raise HTTPException(404, "Aucune Conditions Particulières lue pour l'instant.")
        doc = ctx.repo.get_document(cp_id) if cp_id in ids else None
        cp_ext = ctx.cp(cp_id)
        if cp_ext is None or doc is None:
            raise HTTPException(404, "Cette CP n'a pas encore été lue.")
        pages = len(cp_page_images(doc.storage_path, (doc.classification or {}).get("page_files")))
    insurer = prof.get("insurer_id") or cp_ext.insurer_id
    cg = cg_library.load(insurer)
    out = dossier(cp_ext, cg, TX, today=as_of, ai=ai_classifier.overrides(DATA, cg.insurer_id))
    unrecognised.record(DATA, out["rule_unmapped"], insurer, cp_id)
    out["ai_pending"] = _classify_in_background(cg.insurer_id, out["rule_unmapped"]) if cg.pdf else []
    out["photo"] = _photo_info(cp_id, cp_ext, prof.get("car_key"))
    out["policy"]["pages"] = pages
    return out


_classifying: set[str] = set()
_classifying_lock = threading.Lock()


def _classify_in_background(insurer_id: str, labels: list[str]) -> list[str]:
    """Libellés non reconnus par les règles et jamais soumis à l'IA : classement lancé en tâche de fond.
    Renvoie ceux en cours (l'interface recharge le dossier tant que la liste n'est pas vide)."""
    todo = ai_classifier.pending(DATA, insurer_id, labels)
    if not todo:
        return []
    llm, _ = _llm()
    if llm is None:
        return []  # sans modèle : les lignes restent « À vérifier »
    with _classifying_lock:
        new = [l for l in todo if ai_classifier.key(insurer_id, l) not in _classifying]
        _classifying.update(ai_classifier.key(insurer_id, l) for l in new)
    if new:
        def run() -> None:
            try:
                ai_classifier.classify_and_store(DATA, llm, TX, insurer_id, new)
            except Exception:  # noqa: BLE001 — un échec laisse la ligne « À vérifier »
                logging.exception("classement IA")
            finally:
                with _classifying_lock:
                    _classifying.difference_update(ai_classifier.key(insurer_id, l) for l in new)
        _thread(run)
    return todo


class ClassificationIn(BaseModel):
    label: str
    decision: str  # « confirm » ou « reject »
    insurer_id: Optional[str] = None


@app.put("/api/classifications")
def decide_classification(body: ClassificationIn) -> dict:
    """L'assuré confirme ou refuse le classement proposé par l'IA pour une garantie de sa CP."""
    if body.decision not in ("confirm", "reject"):
        raise HTTPException(400, "decision : confirm ou reject")
    insurer = cg_library.load(body.insurer_id or _profile().get("insurer_id")).insurer_id
    try:
        e = ai_classifier.set_decision(DATA, insurer, body.label, body.decision)  # type: ignore[arg-type]
    except KeyError:
        raise HTTPException(404, "Aucun classement pour ce libellé")
    return {"ok": True, "status": e["status"]}


# --------------------------------------------------------------------------- photos du véhicule


def _photos() -> PhotoStore:
    return PhotoStore(DATA / "files" / _uid())


def _photo_info(cp_id: str, cp: CPExtraction, car_key: Optional[str]) -> dict:
    own = _photos().load(cp_id)
    if own is not None:
        return {"source": "upload", "url": f"/api/documents/{cp_id}/vehicle-photo/image?v={int(time.time())}",
                "anchors": own["anchors"], "credit": "Votre photo", "exact": True, "label": "Votre voiture",
                "detected_by": own.get("detected_by")}
    return cars.photo_for(cp.vehicle, car_key)


@app.get("/api/cars/{key}.jpg")
def car_image(key: str) -> FileResponse:
    if key not in cars.catalog()["photos"]:
        raise HTTPException(404, "photo inconnue")
    return FileResponse(cars.PHOTO_DIR / f"{key}.jpg", media_type="image/jpeg",
                        headers={"Cache-Control": "public, max-age=604800"})


@app.get("/api/cg/{insurer_id}/pdf")
def cg_pdf(insurer_id: str) -> FileResponse:
    """Le document original des Conditions Générales de l'assureur (celui dont viennent les extraits)."""
    if insurer_id not in cg_library.registry() or not (path := cg_library.pdf_path(insurer_id)):
        raise HTTPException(404, "Conditions Générales non intégrées pour cet assureur")
    return FileResponse(path, media_type="application/pdf", filename=f"CG_{insurer_id}.pdf",
                        content_disposition_type="inline")


@app.post("/api/documents/{doc_id}/vehicle-photo")
async def upload_vehicle_photo(doc_id: str, file: UploadFile = File(...)) -> dict:
    """Photo de SA voiture : redressée, réduite, sans métadonnées (GPS compris) ; parties repérées si possible."""
    with Ctx() as ctx:
        try:
            ctx.repo.get_document(doc_id)
        except AccessDenied:
            raise HTTPException(404, "document introuvable")
    try:
        jpeg = normalize_photo(await file.read())
    except Exception:
        raise HTTPException(400, "Image illisible : utilisez une photo JPEG ou PNG.")
    llm, _ = _llm()
    try:
        anchors, origin = detect_anchors(jpeg, llm)
    except LLMError:
        anchors, origin = _clean(DEFAULT_ANCHORS), "default"
    return _photos().save(doc_id, jpeg, anchors, origin)


@app.get("/api/documents/{doc_id}/vehicle-photo/image")
def vehicle_photo_image(doc_id: str) -> Response:
    data = _photos().image(doc_id)
    if data is None:
        raise HTTPException(404, "aucune photo")
    return Response(data, media_type="image/jpeg", headers={"Cache-Control": "no-cache"})


class AnchorsBody(BaseModel):
    anchors: dict[str, Optional[list[float]]]


@app.put("/api/documents/{doc_id}/vehicle-photo/anchors")
def set_vehicle_photo_anchors(doc_id: str, body: AnchorsBody) -> dict:
    info = _photos().set_anchors(doc_id, body.anchors)
    if info is None:
        raise HTTPException(404, "aucune photo")
    return info


@app.delete("/api/documents/{doc_id}/vehicle-photo")
def delete_vehicle_photo(doc_id: str) -> dict:
    _photos().delete(doc_id)
    return {"ok": True}


# --------------------------------------------------------------------------- interface construite

if DIST.exists():
    app.mount("/assets", StaticFiles(directory=DIST / "assets"), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    def spa(path: str):
        target = DIST / path
        if path and target.is_file() and DIST in target.resolve().parents:
            return FileResponse(target)
        return FileResponse(DIST / "index.html")
