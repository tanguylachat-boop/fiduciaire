"""Orchestration : prepare → qrbill → ocr → classify → route|review.

Une seule fonction `process_document` à appeler par le watcher ou par tests.
Idempotent par sha256 : un re-traitement n'écrase pas un doc déjà routé.
"""

from __future__ import annotations

import logging
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from . import classify as classify_mod
from . import db
from . import ocr as ocr_mod
from . import prepare as prepare_mod
from . import qrbill
from . import rename_route as route_mod
from . import review as review_mod
from .config import Config

log = logging.getLogger("fiduciaire.pipeline")


@dataclass
class PipelineOutcome:
    doc_id: int
    sha256: str
    status: str
    final_path: Path | None
    classification: classify_mod.Classification | None
    qr_used: bool
    duration_s: float
    review_reasons: list[str]
    skipped_reason: str | None = None


def _delete_inbox(path: Path) -> None:
    try:
        path.unlink(missing_ok=True)
    except Exception as e:
        log.warning("inbox cleanup failed for %s: %s", path, e)


def process_document(
    source: Path,
    config: Config,
    conn: sqlite3.Connection,
    delete_inbox: bool = True,
) -> PipelineOutcome:
    t0 = time.perf_counter()

    pr = prepare_mod.prepare(source, config.paths.archive, conn)
    if not pr.is_new:
        log.info("doublon ignoré: %s (sha256=%s)", source.name, pr.sha256[:10])
        if delete_inbox:
            _delete_inbox(source)
        return PipelineOutcome(
            doc_id=pr.doc_id,
            sha256=pr.sha256,
            status=db.STATUS_DUPLICATE,
            final_path=None,
            classification=None,
            qr_used=False,
            duration_s=time.perf_counter() - t0,
            review_reasons=[],
            skipped_reason="duplicate",
        )

    qr_data: Optional[qrbill.QRBillData] = None
    if config.qr_enabled:
        try:
            t_qr = time.perf_counter()
            qr_data = qrbill.detect_and_parse(pr.archive_path, dpi=config.ocr_dpi)
            db.log_action(
                conn,
                pr.doc_id,
                action="qrbill_scan",
                payload={"detected": qr_data is not None},
                duration_ms=int((time.perf_counter() - t_qr) * 1000),
            )
        except Exception as e:
            log.warning("qrbill scan failed: %s", e)
            db.log_action(conn, pr.doc_id, action="qrbill_scan", ok=False, error=str(e))

    try:
        t_ocr = time.perf_counter()
        ocr_res = ocr_mod.run_ocr(
            pr.archive_path,
            langs=config.langues_ocr,
            dpi=config.ocr_dpi,
            vision_model=config.llm.vision,
            vision_endpoint=config.llm.endpoint,
            vision_timeout_s=config.llm.timeout_s,
            ratio_threshold=config.vision_when_ratio_below,
        )
        db.update_document(conn, pr.doc_id, ocr_text=ocr_res.text, ocr_engine=ocr_res.engine)
        db.log_action(
            conn,
            pr.doc_id,
            action="ocr",
            payload={"engine": ocr_res.engine, "ratio": round(ocr_res.ratio_text, 3), "pages": ocr_res.pages, "chars": len(ocr_res.text)},
            duration_ms=int((time.perf_counter() - t_ocr) * 1000),
        )
    except Exception as e:
        db.update_document(conn, pr.doc_id, status=db.STATUS_FAILED, needs_review_reason=f"ocr_error:{e}")
        db.log_action(conn, pr.doc_id, action="ocr", ok=False, error=str(e))
        return PipelineOutcome(
            doc_id=pr.doc_id,
            sha256=pr.sha256,
            status=db.STATUS_FAILED,
            final_path=None,
            classification=None,
            qr_used=qr_data is not None,
            duration_s=time.perf_counter() - t0,
            review_reasons=[f"ocr_error:{e}"],
        )

    classification = classify_mod.classify(
        ocr_text=ocr_res.text,
        known_clients=config.known_clients,
        template_path=config.llm.prompt_file,
        endpoint=config.llm.endpoint,
        model=config.llm.primary,
        timeout_s=config.llm.timeout_s,
        num_predict=config.llm.num_predict,
        temperature=config.llm.temperature,
        num_ctx=config.llm.num_ctx,
    )
    db.log_action(
        conn,
        pr.doc_id,
        action="classify",
        payload={
            "type": classification.type,
            "client": classification.client,
            "date": classification.date,
            "montant": classification.montant_chf,
            "retries": classification.retries,
            "error": classification.error,
        },
        duration_ms=int(classification.latency_s * 1000),
        ok=classification.error is None,
        error=classification.error,
    )

    classification = classify_mod.merge_with_qr(classification, qr_data)
    db.update_document(
        conn,
        pr.doc_id,
        status=db.STATUS_CLASSIFIED,
        classification_json=classification.raw_response or "",
    )

    reasons = review_mod.evaluate_thresholds(classification, config.confidence_thresholds)
    if reasons:
        rr = review_mod.send_to_review(
            pr.archive_path, classification, pr.sha256, reasons, config, conn, pr.doc_id
        )
        if delete_inbox:
            _delete_inbox(source)
        return PipelineOutcome(
            doc_id=pr.doc_id,
            sha256=pr.sha256,
            status=db.STATUS_NEEDS_REVIEW,
            final_path=rr.path,
            classification=classification,
            qr_used=qr_data is not None,
            duration_s=time.perf_counter() - t0,
            review_reasons=reasons,
        )

    route_res = route_mod.route(
        pr.archive_path, classification, pr.sha256, config, conn, pr.doc_id
    )
    if delete_inbox:
        _delete_inbox(source)

    return PipelineOutcome(
        doc_id=pr.doc_id,
        sha256=pr.sha256,
        status=db.STATUS_ROUTED,
        final_path=route_res.final_path,
        classification=classification,
        qr_used=qr_data is not None,
        duration_s=time.perf_counter() - t0,
        review_reasons=[],
    )
