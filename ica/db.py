"""Persistance : modèles SQLAlchemy et dépôt (Repository) cloisonné par utilisateur.

Isolation des données : TOUTES les tables portent ``user_id`` et le seul point d'accès prévu est
``Repository(session, user_id)`` dont chaque requête filtre sur cet identifiant. Un utilisateur ne
peut donc ni lire ni écrire les données d'un autre, même en connaissant ses identifiants.
(En production PostgreSQL : ajouter des politiques Row-Level Security comme seconde barrière.)

Les extractions sont stockées en JSON versionné : chaque retraitement crée une nouvelle
version, l'historique est conservé.
"""
from __future__ import annotations

import hashlib
import uuid
from datetime import datetime, timezone
from typing import Optional, Type, TypeVar

from pydantic import BaseModel
from sqlalchemy import JSON, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, create_engine, select
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker


M = TypeVar("M", bound=BaseModel)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _id() -> str:
    return uuid.uuid4().hex


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_id)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class Account(Base):
    """Compte de connexion (e-mail + mot de passe). ``id`` = identifiant utilisateur de toutes les tables."""
    __tablename__ = "accounts"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_id)
    email: Mapped[str] = mapped_column(String(254), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(200))  # « scrypt$sel$empreinte » : jamais le mot de passe
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class AuthSession(Base):
    """Session ouverte. Seule l'empreinte SHA-256 du jeton est stockée (le jeton reste dans le cookie)."""
    __tablename__ = "auth_sessions"
    token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(32), index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class Contract(Base):
    __tablename__ = "contracts"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_id)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    label: Mapped[str] = mapped_column(String(200))
    insurer_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    product_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class Document(Base):
    __tablename__ = "documents"
    __table_args__ = (UniqueConstraint("user_id", "sha256", name="uq_user_doc_hash"),)
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_id)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    contract_id: Mapped[Optional[str]] = mapped_column(ForeignKey("contracts.id"), nullable=True, index=True)
    doc_type: Mapped[str] = mapped_column(String(20))
    filename: Mapped[str] = mapped_column(String(300))
    sha256: Mapped[str] = mapped_column(String(64))
    storage_path: Mapped[str] = mapped_column(Text)
    page_count: Mapped[int] = mapped_column(Integer, default=0)
    insurer_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    product_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    classification: Mapped[dict] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(20), default="INGESTED")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class ExtractionRow(Base):
    """Extraction versionnée (CP_EXTRACTION) liée à un document."""

    __tablename__ = "extractions"
    __table_args__ = (UniqueConstraint("document_id", "kind", "version", name="uq_extraction_version"),)
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_id)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    document_id: Mapped[str] = mapped_column(ForeignKey("documents.id"), index=True)
    kind: Mapped[str] = mapped_column(String(20))
    version: Mapped[int] = mapped_column(Integer)
    extractor_version: Mapped[str] = mapped_column(String(64))
    payload: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class ProcessingRun(Base):
    __tablename__ = "processing_runs"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_id)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    document_id: Mapped[Optional[str]] = mapped_column(ForeignKey("documents.id"), nullable=True, index=True)
    stage: Mapped[str] = mapped_column(String(40))
    status: Mapped[str] = mapped_column(String(20))
    attempts: Mapped[int] = mapped_column(Integer, default=1)
    error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    detail: Mapped[dict] = mapped_column(JSON, default=dict)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    finished_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)


def make_session_factory(url: str = "sqlite:///ica.db") -> sessionmaker[Session]:
    engine_options = {"connect_args": {"timeout": 30}} if url.startswith("sqlite") else {}
    engine = create_engine(url, future=True, **engine_options)
    Base.metadata.create_all(engine)
    return sessionmaker(engine, expire_on_commit=False)


class AccessDenied(PermissionError):
    pass


class Repository:
    """Accès aux données d'UN utilisateur. Toute lecture/écriture est filtrée par ``user_id``."""

    def __init__(self, session: Session, user_id: str):
        self.s, self.user_id = session, user_id
        if session.get(User, user_id) is None:
            session.add(User(id=user_id))
            session.flush()

    # ---- contrats / documents
    def create_contract(self, label: str) -> Contract:
        c = Contract(user_id=self.user_id, label=label)
        self.s.add(c)
        self.s.flush()
        return c

    def default_contract(self, label: str = "Mon contrat auto") -> Contract:
        c = self.s.scalar(select(Contract).where(Contract.user_id == self.user_id).order_by(Contract.created_at))
        return c or self.create_contract(label)

    def get_contract(self, contract_id: str) -> Contract:
        c = self.s.scalar(select(Contract).where(Contract.id == contract_id, Contract.user_id == self.user_id))
        if c is None:
            raise AccessDenied("contrat introuvable pour cet utilisateur")
        return c

    def add_document(
        self, *, contract_id: Optional[str], doc_type: str, filename: str, data: bytes, storage_path: str, page_count: int,
        insurer_id: Optional[str], product_id: Optional[str], classification: dict,
    ) -> Document:
        if contract_id:
            self.get_contract(contract_id)
        digest = hashlib.sha256(data).hexdigest()
        existing = self.s.scalar(select(Document).where(Document.user_id == self.user_id, Document.sha256 == digest))
        if existing:
            return existing
        d = Document(
            user_id=self.user_id, contract_id=contract_id, doc_type=doc_type, filename=filename, sha256=digest,
            storage_path=storage_path, page_count=page_count, insurer_id=insurer_id, product_id=product_id,
            classification=classification,
        )
        self.s.add(d)
        self.s.flush()
        return d

    def get_document(self, document_id: str) -> Document:
        d = self.s.scalar(select(Document).where(Document.id == document_id, Document.user_id == self.user_id))
        if d is None:
            raise AccessDenied("document introuvable pour cet utilisateur")
        return d

    def list_documents(self, contract_id: str) -> list[Document]:
        self.get_contract(contract_id)
        return list(self.s.scalars(select(Document).where(Document.user_id == self.user_id, Document.contract_id == contract_id)))

    def delete_document(self, document_id: str) -> None:
        """Supprime un document, ses lectures et son journal (le fichier stocké est supprimé par l'appelant)."""
        d = self.get_document(document_id)
        for model in (ExtractionRow, ProcessingRun):
            for row in self.s.scalars(select(model).where(model.user_id == self.user_id, model.document_id == document_id)):
                self.s.delete(row)
        self.s.flush()
        self.s.delete(d)
        self.s.flush()

    # ---- extractions versionnées
    def save_extraction(self, document_id: str, kind: str, model: BaseModel, extractor_version: str) -> ExtractionRow:
        self.get_document(document_id)
        last = self.s.scalar(
            select(ExtractionRow.version).where(
                ExtractionRow.user_id == self.user_id, ExtractionRow.document_id == document_id, ExtractionRow.kind == kind
            ).order_by(ExtractionRow.version.desc())
        )
        row = ExtractionRow(
            user_id=self.user_id, document_id=document_id, kind=kind, version=(last or 0) + 1,
            extractor_version=extractor_version, payload=model.model_dump(mode="json"),
        )
        self.s.add(row)
        self.s.flush()
        return row

    def latest_extraction(self, document_id: str, kind: str, model_cls: Type[M]) -> Optional[M]:
        self.get_document(document_id)
        row = self.s.scalar(
            select(ExtractionRow).where(
                ExtractionRow.user_id == self.user_id, ExtractionRow.document_id == document_id, ExtractionRow.kind == kind
            ).order_by(ExtractionRow.version.desc())
        )
        return model_cls.model_validate(row.payload) if row else None

    # ---- journal de traitement
    def start_run(self, stage: str, document_id: Optional[str] = None) -> ProcessingRun:
        run = ProcessingRun(user_id=self.user_id, document_id=document_id, stage=stage, status="RUNNING")
        self.s.add(run)
        self.s.flush()
        return run

    def finish_run(self, run: ProcessingRun, *, ok: bool, error: Optional[str] = None, attempts: int = 1, detail: Optional[dict] = None) -> None:
        run.status, run.error, run.attempts, run.finished_at = ("OK" if ok else "FAILED"), error, attempts, _now()
        run.detail = detail or {}
        self.s.flush()
