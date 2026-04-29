"""Étape 5' — Review queue.

Si un champ critique est sous le seuil, ou si la classification a échoué,
le fichier va dans data/needs-review/ avec un suffixe explicite.
"""

from __future__ import annotations

import shutil
import sqlite3
from dataclasses import dataclass
from pathlib import Path

from . import db
from .classify import Classification
from .config import Config


@dataclass
class ReviewResult:
    path: Path
    reasons: list[str]


def evaluate_thresholds(c: Classification, thresholds: dict[str, float]) -> list[str]:
    """Retourne la liste des raisons de mise en review (vide si tout OK)."""
    reasons: list[str] = []
    if c.error:
        reasons.append(f"classification_error:{c.error}")
        return reasons
    if c.type is None:
        reasons.append("type_null")
    elif c.type_confidence < thresholds.get("type", 0.85):
        reasons.append(f"type_conf<{thresholds.get('type', 0.85):.2f}")
    if c.client is None:
        reasons.append("client_null")
    elif c.client_confidence < thresholds.get("client", 0.80):
        reasons.append(f"client_conf<{thresholds.get('client', 0.80):.2f}")
    if c.date is None:
        reasons.append("date_null")
    elif c.date_confidence < thresholds.get("date", 0.75):
        reasons.append(f"date_conf<{thresholds.get('date', 0.75):.2f}")
    if c.montant_chf is None and c.type not in ("courrier", "autre"):
        reasons.append("montant_null")
    elif c.montant_confidence < thresholds.get("montant", 0.75) and c.type not in (
        "courrier",
        "autre",
    ):
        reasons.append(f"montant_conf<{thresholds.get('montant', 0.75):.2f}")
    return reasons


def send_to_review(
    archive_path: Path,
    classification: Classification,
    sha256: str,
    reasons: list[str],
    config: Config,
    conn: sqlite3.Connection,
    doc_id: int,
) -> ReviewResult:
    config.paths.needs_review.mkdir(parents=True, exist_ok=True)
    suffix = archive_path.suffix.lower()
    name = f"{sha256[:10]}_{(classification.type or 'autre')}{suffix}"
    target = config.paths.needs_review / name
    if target.exists():
        i = 1
        while (config.paths.needs_review / f"{sha256[:10]}-{i}_{(classification.type or 'autre')}{suffix}").exists():
            i += 1
        target = config.paths.needs_review / f"{sha256[:10]}-{i}_{(classification.type or 'autre')}{suffix}"
    shutil.copy2(archive_path, target)

    reason_str = ",".join(reasons)
    db.update_document(
        conn,
        doc_id,
        status=db.STATUS_NEEDS_REVIEW,
        needs_review_reason=reason_str,
        final_path=str(target),
        type=classification.type,
        doc_date=classification.date,
        montant_chf=classification.montant_chf,
    )
    db.log_action(
        conn,
        doc_id,
        action="needs_review",
        payload={"reasons": reasons, "path": str(target)},
    )
    return ReviewResult(path=target, reasons=reasons)
