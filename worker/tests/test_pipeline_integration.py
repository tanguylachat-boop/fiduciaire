"""Tests d'intégration bout-en-bout du pipeline.

Skippés si Ollama n'est pas joignable. La fixture `pdf_*` génère un PDF
synthétique avec reportlab → reproductible et offline.

Cas couverts :
  1. PDF avec Swiss QR-bill → parser direct utilisé (montant/devise/fournisseur depuis QR).
  2. PDF sans QR (alias client) → OCR + LLM, classification correcte.
  3. PDF sans client connu (Migros, Pierre Müller) → review queue.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import httpx
import pytest

from fiduciaire_worker import db
from fiduciaire_worker.config import load_config
from fiduciaire_worker.pipeline import process_document


def _ollama_alive(endpoint: str) -> bool:
    try:
        r = httpx.get(f"{endpoint}/api/tags", timeout=2.0)
        return r.status_code == 200
    except Exception:
        return False


SKIP_NO_OLLAMA = pytest.mark.skipif(
    not _ollama_alive("http://localhost:11434"),
    reason="Ollama non joignable sur localhost:11434",
)


def _drop_in_inbox(src: Path, inbox: Path) -> Path:
    dest = inbox / src.name
    shutil.copy2(src, dest)
    return dest


@SKIP_NO_OLLAMA
def test_e2e_qr_bill(tmp_config, tmp_workspace, pdf_qrbill_swisscom):
    """Doc avec QR-bill → montant/devise/fournisseur viennent du QR (confidence 1.0)."""
    config = load_config(tmp_config)
    inbox_path = _drop_in_inbox(pdf_qrbill_swisscom, config.paths.inbox)

    conn = db.connect(config.paths.db)
    db.init_schema(conn)
    outcome = process_document(inbox_path, config, conn, delete_inbox=False)

    # QR détecté
    assert outcome.qr_used is True

    # Montant viennent du QR (confidence 1.0)
    assert outcome.classification is not None
    assert outcome.classification.montant_chf == 287.00
    assert outcome.classification.devise == "CHF"
    assert outcome.classification.sources.get("montant_chf") == "qr"

    # Doc soit routé soit en review (selon perf LLM sur date/type/client)
    assert outcome.status in (db.STATUS_ROUTED, db.STATUS_NEEDS_REVIEW)
    assert outcome.final_path is not None and outcome.final_path.exists()


@SKIP_NO_OLLAMA
def test_e2e_no_qr(tmp_config, tmp_workspace, pdf_no_qr_alias):
    """Doc sans QR → OCR + LLM. Pas d'assertion stricte sur classif (corpus synthétique)."""
    config = load_config(tmp_config)
    inbox_path = _drop_in_inbox(pdf_no_qr_alias, config.paths.inbox)

    conn = db.connect(config.paths.db)
    db.init_schema(conn)
    outcome = process_document(inbox_path, config, conn, delete_inbox=False)

    assert outcome.qr_used is False
    assert outcome.classification is not None
    assert outcome.final_path is not None

    # SQLite reflète la classification
    row = db.get_document(conn, outcome.doc_id)
    assert row["status"] in ("routed", "needs_review")
    assert row["ocr_text"] is not None and len(row["ocr_text"]) > 50


@SKIP_NO_OLLAMA
def test_e2e_review_queue(tmp_config, tmp_workspace, pdf_inconnu_low_conf):
    """Doc sans client connu → review queue (client_null)."""
    config = load_config(tmp_config)
    inbox_path = _drop_in_inbox(pdf_inconnu_low_conf, config.paths.inbox)

    conn = db.connect(config.paths.db)
    db.init_schema(conn)
    outcome = process_document(inbox_path, config, conn, delete_inbox=False)

    assert outcome.status == db.STATUS_NEEDS_REVIEW
    # raisons attendues : client_null OU client_conf<...
    assert any("client" in r for r in outcome.review_reasons)
    # le fichier final doit être dans data/needs-review/
    assert outcome.final_path is not None
    assert outcome.final_path.parent == config.paths.needs_review


def test_e2e_idempotent(tmp_config, tmp_workspace, pdf_inconnu_low_conf):
    """Même fichier déposé 2 fois → 2e passage = duplicate, pas de re-classif."""
    config = load_config(tmp_config)

    # Force une config sans LLM pour ce test (l'idempotence ne dépend pas de l'OCR/LLM)
    inbox = config.paths.inbox
    a = _drop_in_inbox(pdf_inconnu_low_conf, inbox)
    conn = db.connect(config.paths.db)
    db.init_schema(conn)

    if not _ollama_alive(config.llm.endpoint):
        pytest.skip("Ollama non joignable — l'idempotence se teste avec pipeline complet")

    o1 = process_document(a, config, conn, delete_inbox=False)
    a2 = _drop_in_inbox(pdf_inconnu_low_conf, inbox)
    o2 = process_document(a2, config, conn, delete_inbox=False)

    assert o1.doc_id == o2.doc_id
    assert o2.status == db.STATUS_DUPLICATE
    assert o2.skipped_reason == "duplicate"
