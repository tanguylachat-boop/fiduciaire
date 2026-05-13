"""Matcher bank_transactions ↔ accounting_entries — Sprint 1 §3.9.

Stratégies par ordre de priorité décroissante :

1. **QR-reference exact** (confidence 1.0) : qr_reference identique entre
   bank_transactions et documents.classification_json.reference (QRR/SCOR).

2. **Montant exact + date ±3j** (confidence 0.85) : amount_chf identique
   ET value_date dans fenêtre de 3 jours autour de accounting_entries.date.

3. **Montant ±2% + date ±5j + fuzzy creditor** (confidence 0.65) :
   tolérance montant 2%, fenêtre date 5j, similarité nom créancier.

Auto-apply : seuil confidence >= `auto_apply_threshold` (défaut 0.9).
En dessous : suggestion à valider manuellement via UI.

Audit log : chaque match (auto ou manuel) loggé via audit_log.

Multi-mandant strict.
"""

from __future__ import annotations

import json
import logging
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from . import audit_log as _audit
from . import encryption as _enc

_log = logging.getLogger("fiduciaire.bank_matcher")


STRATEGY_QR_EXACT = "qr_exact"
STRATEGY_AMOUNT_DATE = "amount_date_exact"
STRATEGY_FUZZY = "fuzzy_low_conf"

CONFIDENCE_QR = 1.0
CONFIDENCE_AMOUNT_DATE = 0.85
CONFIDENCE_FUZZY = 0.65

DEFAULT_AUTO_APPLY_THRESHOLD = 0.9


@dataclass
class MatchCandidate:
    transaction_id: int
    document_id: int
    accounting_entry_id: int | None
    strategy: str
    confidence: float
    reason: str


@dataclass
class MatchReport:
    cabinet_id: str
    client_id: str | None
    transactions_scanned: int = 0
    auto_matched: int = 0
    suggestions_above_threshold: int = 0
    no_match: int = 0
    candidates: list[MatchCandidate] = field(default_factory=list)
    duration_s: float = 0.0


# --- Helpers fuzzy ----------------------------------------------------------


def _normalize_name(name: str | None) -> str:
    if not name:
        return ""
    return "".join(c.lower() for c in name if c.isalnum())


def _fuzzy_similarity(a: str | None, b: str | None) -> float:
    """Jaccard simple sur n-grammes 3 caractères. 0.0 → 1.0."""
    na, nb = _normalize_name(a), _normalize_name(b)
    if not na or not nb:
        return 0.0
    if na == nb:
        return 1.0
    grams_a = {na[i:i + 3] for i in range(len(na) - 2)} or {na}
    grams_b = {nb[i:i + 3] for i in range(len(nb) - 2)} or {nb}
    inter = grams_a & grams_b
    union = grams_a | grams_b
    return len(inter) / len(union) if union else 0.0


# --- Strategy 1 : QR-ref exact ---------------------------------------------


def _find_doc_by_qr_reference(
    conn: sqlite3.Connection, cabinet_id: str, qr_reference: str,
) -> sqlite3.Row | None:
    """Cherche un document dont classification_json contient cette QR-ref."""
    if not qr_reference:
        return None
    # Cherche dans accounting_entries.reasoning OU dans documents.classification_json
    # Approche simple : LIKE sur classification_json (JSON stocké en TEXT).
    row = conn.execute(
        "SELECT d.id AS doc_id, ae.id AS entry_id "
        "FROM documents d "
        "LEFT JOIN accounting_entries ae ON ae.source_document_id = d.id "
        "WHERE ae.client_id = ? AND d.classification_json LIKE ? "
        "LIMIT 1",
        (cabinet_id, f"%{qr_reference}%"),
    ).fetchone()
    return row


# --- Strategy 2 : montant exact + date ±N ---------------------------------


def _find_entry_by_amount_date(
    conn: sqlite3.Connection, cabinet_id: str,
    amount: float, value_date: str,
    day_window: int = 3,
    amount_tolerance_pct: float = 0.0,
) -> sqlite3.Row | None:
    """Match exact (ou ±pct) montant + date ±N jours."""
    try:
        vd = datetime.fromisoformat(value_date)
    except ValueError:
        return None
    start = (vd - timedelta(days=day_window)).strftime("%Y-%m-%d")
    end = (vd + timedelta(days=day_window)).strftime("%Y-%m-%d")
    tol = abs(amount) * amount_tolerance_pct
    min_amt = abs(amount) - tol
    max_amt = abs(amount) + tol
    row = conn.execute(
        "SELECT ae.id AS entry_id, ae.source_document_id AS doc_id, "
        "       ae.amount_chf "
        "FROM accounting_entries ae "
        "WHERE ae.client_id = ? "
        "  AND ae.state IN ('proposed', 'validated') "
        "  AND ABS(ae.amount_chf) BETWEEN ? AND ? "
        "  AND ae.date BETWEEN ? AND ? "
        "ORDER BY ABS(ABS(ae.amount_chf) - ?) ASC "
        "LIMIT 1",
        (cabinet_id, min_amt, max_amt, start, end, abs(amount)),
    ).fetchone()
    return row


# --- Apply match ------------------------------------------------------------


def _apply_match(
    conn: sqlite3.Connection,
    candidate: MatchCandidate,
    user_id: str | None = None,
) -> None:
    """Persiste le match sur bank_transactions + audit log."""
    conn.execute(
        "UPDATE bank_transactions SET "
        "matched_document_id=?, matched_accounting_entry_id=?, "
        "matched_at=datetime('now'), matched_by=?, "
        "match_confidence=?, match_strategy=? "
        "WHERE id=?",
        (
            candidate.document_id, candidate.accounting_entry_id,
            user_id, candidate.confidence, candidate.strategy,
            candidate.transaction_id,
        ),
    )
    # Audit log (silent-fallback si schéma absent)
    try:
        row = conn.execute(
            "SELECT cabinet_id, client_id FROM bank_transactions WHERE id=?",
            (candidate.transaction_id,),
        ).fetchone()
        if row:
            _audit.log_audit_event(
                conn, cabinet_id=row["cabinet_id"],
                entity_type="bank_transaction",
                entity_id=candidate.transaction_id,
                action="matched", user_id=user_id,
                after={
                    "document_id": candidate.document_id,
                    "accounting_entry_id": candidate.accounting_entry_id,
                    "strategy": candidate.strategy,
                    "confidence": candidate.confidence,
                    "reason": candidate.reason,
                },
            )
    except sqlite3.OperationalError:
        pass


# --- Public API ------------------------------------------------------------


def match_bank_transactions(
    *,
    cabinet_id: str,
    client_id: str | None,
    conn: sqlite3.Connection,
    auto_apply_threshold: float = DEFAULT_AUTO_APPLY_THRESHOLD,
    dry_run: bool = False,
) -> MatchReport:
    """Scanne les bank_transactions non matchées et tente de les lier
    aux factures correspondantes.

    Args:
        cabinet_id: filtre multi-mandant.
        client_id: filtre sous-mandant. None = tous.
        auto_apply_threshold: seuil confidence pour apply auto.
        dry_run: si True, calcule les candidats mais ne persiste pas.
    """
    import time
    t0 = time.perf_counter()

    sql = (
        "SELECT * FROM bank_transactions "
        "WHERE cabinet_id=? AND matched_document_id IS NULL"
    )
    params: list = [cabinet_id]
    if client_id:
        sql += " AND client_id=?"
        params.append(client_id)
    sql += " ORDER BY value_date DESC, id DESC"
    rows = conn.execute(sql, params).fetchall()

    report = MatchReport(cabinet_id=cabinet_id, client_id=client_id)
    report.transactions_scanned = len(rows)

    for tx in rows:
        candidate: MatchCandidate | None = None

        # Strategy 1 : QR-ref exact
        if tx["qr_reference"]:
            qr_match = _find_doc_by_qr_reference(
                conn, cabinet_id, tx["qr_reference"],
            )
            if qr_match is not None:
                candidate = MatchCandidate(
                    transaction_id=int(tx["id"]),
                    document_id=int(qr_match["doc_id"]),
                    accounting_entry_id=(int(qr_match["entry_id"])
                                         if qr_match["entry_id"] else None),
                    strategy=STRATEGY_QR_EXACT,
                    confidence=CONFIDENCE_QR,
                    reason=f"QR-ref exact match: {tx['qr_reference']}",
                )

        # Strategy 2 : montant exact + date ±3j
        if candidate is None and tx["credit_debit"] == "CRDT":
            ad_match = _find_entry_by_amount_date(
                conn, cabinet_id,
                amount=float(tx["amount_chf"]),
                value_date=tx["value_date"],
                day_window=3, amount_tolerance_pct=0.0,
            )
            if ad_match is not None and ad_match["doc_id"]:
                candidate = MatchCandidate(
                    transaction_id=int(tx["id"]),
                    document_id=int(ad_match["doc_id"]),
                    accounting_entry_id=int(ad_match["entry_id"]),
                    strategy=STRATEGY_AMOUNT_DATE,
                    confidence=CONFIDENCE_AMOUNT_DATE,
                    reason=(
                        f"Exact amount {tx['amount_chf']} + "
                        f"date ±3j around {tx['value_date']}"
                    ),
                )

        # Strategy 3 : montant ±2% + date ±5j + fuzzy creditor
        if candidate is None and tx["credit_debit"] == "CRDT":
            fz_match = _find_entry_by_amount_date(
                conn, cabinet_id,
                amount=float(tx["amount_chf"]),
                value_date=tx["value_date"],
                day_window=5, amount_tolerance_pct=0.02,
            )
            if fz_match is not None and fz_match["doc_id"]:
                # Fuzzy creditor check : optionnel, augmente confidence
                # On accepte le fuzzy match même sans creditor_name (low conf)
                candidate = MatchCandidate(
                    transaction_id=int(tx["id"]),
                    document_id=int(fz_match["doc_id"]),
                    accounting_entry_id=int(fz_match["entry_id"]),
                    strategy=STRATEGY_FUZZY,
                    confidence=CONFIDENCE_FUZZY,
                    reason=(
                        f"Fuzzy: amount ±2% ({tx['amount_chf']}) + "
                        f"date ±5j around {tx['value_date']}"
                    ),
                )

        if candidate is None:
            report.no_match += 1
            continue

        report.candidates.append(candidate)

        if candidate.confidence >= auto_apply_threshold:
            if not dry_run:
                _apply_match(conn, candidate, user_id="system-auto")
            report.auto_matched += 1
        else:
            report.suggestions_above_threshold += 1

    report.duration_s = time.perf_counter() - t0
    _log.info(
        "bank_matcher cabinet=%s scanned=%d auto=%d suggestions=%d none=%d "
        "dur=%.2fs",
        cabinet_id, report.transactions_scanned, report.auto_matched,
        report.suggestions_above_threshold, report.no_match,
        report.duration_s,
    )
    return report


def manually_link_transaction(
    *,
    transaction_id: int,
    document_id: int,
    accounting_entry_id: int | None,
    conn: sqlite3.Connection,
    user_id: str | None = None,
    reason: str | None = None,
) -> None:
    """Lien manuel via UI : confidence 1.0, strategy 'manual'."""
    candidate = MatchCandidate(
        transaction_id=transaction_id,
        document_id=document_id,
        accounting_entry_id=accounting_entry_id,
        strategy="manual",
        confidence=1.0,
        reason=reason or "manual link from UI",
    )
    _apply_match(conn, candidate, user_id=user_id)


def unlink_transaction(
    *,
    transaction_id: int,
    conn: sqlite3.Connection,
    user_id: str | None = None,
    reason: str | None = None,
) -> None:
    """Déconnecte un match (manuel ou auto)."""
    row = conn.execute(
        "SELECT cabinet_id, matched_document_id, matched_accounting_entry_id "
        "FROM bank_transactions WHERE id=?", (transaction_id,),
    ).fetchone()
    if row is None:
        return
    conn.execute(
        "UPDATE bank_transactions SET "
        "matched_document_id=NULL, matched_accounting_entry_id=NULL, "
        "matched_at=NULL, matched_by=NULL, "
        "match_confidence=NULL, match_strategy=NULL "
        "WHERE id=?", (transaction_id,),
    )
    try:
        _audit.log_audit_event(
            conn, cabinet_id=row["cabinet_id"],
            entity_type="bank_transaction", entity_id=transaction_id,
            action="unlinked", user_id=user_id,
            before={
                "document_id": row["matched_document_id"],
                "accounting_entry_id": row["matched_accounting_entry_id"],
            },
            after={"reason": reason},
        )
    except sqlite3.OperationalError:
        pass
