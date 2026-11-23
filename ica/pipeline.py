"""Lecture des Conditions Particulières (photo, scan ou PDF) et enregistrement versionné.

Les Conditions Générales ne sont plus importées : elles sont intégrées à l'application (ica/cg_library.py).
Chaque étape est journalisée (ProcessingRun) ; un échec n'efface jamais une lecture précédente.
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from .db import Repository
from .domain import CPExtraction, DocType
from .extraction.cp_extractor import extract_cp
from .extraction.llm import LLMClient
from .taxonomy import Taxonomy

EXTRACTOR_VERSION = "ica-0.3"


class Pipeline:
    def __init__(self, repo: Repository, taxonomy: Taxonomy, storage_dir: str | Path, llm: Optional[LLMClient] = None):
        self.repo, self.tx, self.llm = repo, taxonomy, llm
        self.storage = Path(storage_dir) / repo.user_id
        self.storage.mkdir(parents=True, exist_ok=True)

    def process_cp_images(self, images: list[bytes], contract_id: str, filename: str = "cp.jpg", double_read: bool = True) -> tuple[str, CPExtraction]:
        """``images`` : une image JPEG par page ou photo de la CP. Lecture double par le modèle de vision."""
        assert self.llm is not None, "un client LLM est requis"
        doc = self._store_cp(images, contract_id, filename, {"source": "image"})
        run = self.repo.start_run("extract_cp", doc.id)
        self.repo.s.commit()  # libère le verrou d'écriture SQLite pendant la lecture (longue)
        try:
            cp = extract_cp(images, llm=self.llm, taxonomy=self.tx, document_id=doc.id, double_read=double_read)
            self.save_cp(doc.id, cp)
            self.repo.finish_run(run, ok=True, detail={"lines": len(cp.subscribed), "complete": cp.guarantee_list_complete})
            return doc.id, cp
        except Exception as e:
            self.repo.s.rollback()
            self.repo.finish_run(run, ok=False, error=str(e)[:500])
            self.repo.s.commit()
            raise

    def _store_cp(self, images: list[bytes], contract_id: str, filename: str, classification: dict):
        blob = b"".join(images)
        dest = self.storage / f"cp-{len(blob)}.bin"
        dest.write_bytes(blob)
        page_files = []
        for n, img in enumerate(images, start=1):
            p = self.storage / f"cp-{len(blob)}-p{n}.jpg"
            p.write_bytes(img)
            page_files.append(str(p))
        return self.repo.add_document(
            contract_id=contract_id, doc_type=DocType.CP.value, filename=filename, data=blob, storage_path=str(dest),
            page_count=len(images), insurer_id=None, product_id=None, classification={**classification, "page_files": page_files},
        )

    def save_cp(self, document_id: str, cp: CPExtraction) -> None:
        doc = self.repo.get_document(document_id)
        cp.document_id = document_id
        for s in cp.subscribed:
            s.source.document_id = document_id
        self.repo.save_extraction(document_id, "CP_EXTRACTION", cp, EXTRACTOR_VERSION)
        doc.insurer_id, doc.product_id = cp.insurer_id, cp.product_id

    def import_cp_extraction(self, cp: CPExtraction, contract_id: str, filename: str, origin: bytes) -> str:
        """Enregistre une CP déjà transcrite (exemple fourni)."""
        doc = self._store_cp([origin], contract_id, filename, {"source": "transcription"})
        self.save_cp(doc.id, cp)
        return doc.id
