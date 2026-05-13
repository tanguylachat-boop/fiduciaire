"""Parser CAMT.053 ISO 20022 + import en table `bank_transactions` — Sprint 1 §3.9.

CAMT.053 = relevé bancaire standard suisse (et international ISO 20022).
Format XML imposé par toutes les banques CH : UBS, CS, PostFinance, Raiffeisen,
BCJ (Banque Cantonale du Jura — pilote), BCV, BCGE, etc.

Le namespace varie par version (camt.053.001.02 → .04 → .08 → .10) mais la
structure principale est stable. Notre parser strip les namespaces pour
robustesse multi-versions.

Champs extraits par transaction :
- IBAN du compte
- value_date (date valeur)
- amount + currency (signé : CRDT positif, DBIT négatif)
- description (concat Ustrd + AddtlTxInf)
- qr_reference (Strd/CdtrRefInf/Ref si QRR ou SCOR)
- creditor_name / debtor_name (RltdPties)
- end_to_end_id (Refs/EndToEndId)
- raw_xml_blob (Ntry XML brut pour audit/debug)

Multi-mandant strict : cabinet_id + client_id obligatoires à l'import.
"""

from __future__ import annotations

import logging
import re
import sqlite3
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path

_log = logging.getLogger("fiduciaire.bank_camt")


BANK_TRANSACTIONS_SCHEMA = """
CREATE TABLE IF NOT EXISTS bank_transactions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    cabinet_id TEXT NOT NULL,
    client_id TEXT NOT NULL,
    iban TEXT NOT NULL,
    value_date TEXT NOT NULL,
    booking_date TEXT,
    amount_chf REAL NOT NULL,
    currency TEXT NOT NULL DEFAULT 'CHF',
    credit_debit TEXT NOT NULL,  -- 'CRDT' | 'DBIT'
    description TEXT,
    qr_reference TEXT,
    end_to_end_id TEXT,
    creditor_name TEXT,
    debtor_name TEXT,
    bank_ref TEXT,
    raw_xml_blob TEXT,
    matched_document_id INTEGER REFERENCES documents(id),
    matched_accounting_entry_id INTEGER REFERENCES accounting_entries(id),
    matched_at TEXT,
    matched_by TEXT,
    match_confidence REAL,
    match_strategy TEXT,
    imported_at TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE (cabinet_id, client_id, iban, value_date, amount_chf, bank_ref)
);

CREATE INDEX IF NOT EXISTS idx_bank_tx_cabinet_client
  ON bank_transactions (cabinet_id, client_id);
CREATE INDEX IF NOT EXISTS idx_bank_tx_unmatched
  ON bank_transactions (matched_document_id) WHERE matched_document_id IS NULL;
CREATE INDEX IF NOT EXISTS idx_bank_tx_qr_ref
  ON bank_transactions (qr_reference);
CREATE INDEX IF NOT EXISTS idx_bank_tx_value_date
  ON bank_transactions (value_date);
"""


# --- Dataclasses ------------------------------------------------------------


@dataclass
class BankTransactionData:
    """Représente 1 Ntry CAMT.053 parsée (avant insert DB)."""
    iban: str
    value_date: str  # ISO YYYY-MM-DD
    booking_date: str | None
    amount_chf: float  # signé : + crédit, - débit
    currency: str
    credit_debit: str  # 'CRDT' | 'DBIT'
    description: str
    qr_reference: str | None
    end_to_end_id: str | None
    creditor_name: str | None
    debtor_name: str | None
    bank_ref: str | None
    raw_xml: str


@dataclass
class CamtImportSummary:
    cabinet_id: str
    client_id: str
    file_path: Path
    iban: str
    transactions_total: int = 0
    transactions_inserted: int = 0
    transactions_duplicates: int = 0
    duration_s: float = 0.0


@dataclass
class BankTransaction:
    """Représente une row bank_transactions de la DB."""
    id: int
    cabinet_id: str
    client_id: str
    iban: str
    value_date: str
    amount_chf: float
    currency: str
    credit_debit: str
    description: str | None
    qr_reference: str | None
    end_to_end_id: str | None
    creditor_name: str | None
    debtor_name: str | None
    bank_ref: str | None
    matched_document_id: int | None
    matched_accounting_entry_id: int | None
    match_confidence: float | None
    match_strategy: str | None
    imported_at: str


# --- Init schema ------------------------------------------------------------


def init_bank_schema(conn: sqlite3.Connection) -> None:
    """Idempotent : crée la table bank_transactions + indexes."""
    conn.executescript(BANK_TRANSACTIONS_SCHEMA)


# --- XML helpers (strip namespace) ------------------------------------------


_NS_STRIP_RE = re.compile(r"^\{[^}]+\}")


def _localname(tag: str) -> str:
    return _NS_STRIP_RE.sub("", tag)


def _find_local(elem: ET.Element, *path: str) -> ET.Element | None:
    """Find child by local name, descend path. None si absent."""
    current: ET.Element | None = elem
    for name in path:
        if current is None:
            return None
        found = None
        for child in current:
            if _localname(child.tag) == name:
                found = child
                break
        current = found
    return current


def _findall_local(elem: ET.Element, name: str) -> list[ET.Element]:
    """Find direct children by local name."""
    return [c for c in elem if _localname(c.tag) == name]


def _text(elem: ET.Element | None) -> str | None:
    if elem is None or elem.text is None:
        return None
    return elem.text.strip() or None


# --- Parse 1 Ntry -----------------------------------------------------------


def _parse_ntry(ntry: ET.Element, iban: str) -> BankTransactionData | None:
    """Parse 1 <Ntry> → BankTransactionData. None si malformé."""
    amount_el = _find_local(ntry, "Amt")
    if amount_el is None or amount_el.text is None:
        return None
    try:
        amount_raw = float(amount_el.text.strip())
    except ValueError:
        return None
    currency = amount_el.get("Ccy", "CHF")

    credit_debit = _text(_find_local(ntry, "CdtDbtInd")) or "CRDT"
    # Signed: DBIT négatif
    signed_amount = -amount_raw if credit_debit == "DBIT" else amount_raw

    val_dt = (_text(_find_local(ntry, "ValDt", "Dt"))
              or _text(_find_local(ntry, "ValDt", "DtTm"))
              or "")
    if not val_dt:
        return None
    # Normalize ISO date (drop time component si présent)
    val_dt = val_dt.split("T")[0]

    booking_dt = (_text(_find_local(ntry, "BookgDt", "Dt"))
                  or _text(_find_local(ntry, "BookgDt", "DtTm")))
    if booking_dt:
        booking_dt = booking_dt.split("T")[0]

    bank_ref = _text(_find_local(ntry, "AcctSvcrRef"))

    # NtryDtls/TxDtls — chercher en profondeur car structure imbriquée
    description_parts: list[str] = []
    qr_reference: str | None = None
    end_to_end_id: str | None = None
    creditor_name: str | None = None
    debtor_name: str | None = None

    ntry_dtls = _find_local(ntry, "NtryDtls")
    if ntry_dtls is not None:
        for tx_dtls in _findall_local(ntry_dtls, "TxDtls"):
            # Refs
            refs = _find_local(tx_dtls, "Refs")
            if refs is not None:
                e2e = _text(_find_local(refs, "EndToEndId"))
                if e2e:
                    end_to_end_id = e2e
            # RmtInf : structured OR unstructured
            rmt = _find_local(tx_dtls, "RmtInf")
            if rmt is not None:
                # Unstructured
                for ustrd in _findall_local(rmt, "Ustrd"):
                    if ustrd.text:
                        description_parts.append(ustrd.text.strip())
                # Structured (QRR/SCOR ref)
                strd = _find_local(rmt, "Strd")
                if strd is not None:
                    cdtr_ref = _find_local(strd, "CdtrRefInf", "Ref")
                    if cdtr_ref is not None and cdtr_ref.text:
                        qr_reference = cdtr_ref.text.strip()
                    # AddtlRmtInf
                    addl = _text(_find_local(strd, "AddtlRmtInf"))
                    if addl:
                        description_parts.append(addl)
            # RltdPties
            rltd = _find_local(tx_dtls, "RltdPties")
            if rltd is not None:
                cdtr = _text(_find_local(rltd, "Cdtr", "Nm"))
                if cdtr:
                    creditor_name = cdtr
                dbtr = _text(_find_local(rltd, "Dbtr", "Nm"))
                if dbtr:
                    debtor_name = dbtr
            # AddtlTxInf (texte libre additionnel)
            addl_tx = _text(_find_local(tx_dtls, "AddtlTxInf"))
            if addl_tx:
                description_parts.append(addl_tx)

    # AddtlNtryInf au niveau Ntry (fallback si pas de TxDtls)
    addl_ntry = _text(_find_local(ntry, "AddtlNtryInf"))
    if addl_ntry and not description_parts:
        description_parts.append(addl_ntry)

    description = " | ".join(description_parts)[:500] if description_parts else ""

    # raw_xml : sérialise le Ntry pour audit (debug "pourquoi ce parsing")
    raw_xml = ET.tostring(ntry, encoding="unicode")[:5000]

    return BankTransactionData(
        iban=iban,
        value_date=val_dt,
        booking_date=booking_dt,
        amount_chf=signed_amount,
        currency=currency,
        credit_debit=credit_debit,
        description=description,
        qr_reference=qr_reference,
        end_to_end_id=end_to_end_id,
        creditor_name=creditor_name,
        debtor_name=debtor_name,
        bank_ref=bank_ref,
        raw_xml=raw_xml,
    )


# --- Public parse_camt053 ---------------------------------------------------


def parse_camt053(xml_bytes: bytes) -> tuple[str, list[BankTransactionData]]:
    """Parse un fichier CAMT.053 → (iban, transactions).

    Raises:
        ET.ParseError: si XML invalide.
        ValueError: si structure CAMT inattendue (pas de Stmt ou pas d'IBAN).
    """
    root = ET.fromstring(xml_bytes)
    # Document/BkToCstmrStmt/Stmt
    stmt = _find_local(root, "BkToCstmrStmt", "Stmt")
    if stmt is None:
        # Tolérance : parfois Document est strippé / root = BkToCstmrStmt directement
        stmt = _find_local(root, "Stmt")
    if stmt is None:
        raise ValueError("CAMT.053 invalide : pas de Stmt trouvé")

    iban_el = _find_local(stmt, "Acct", "Id", "IBAN")
    if iban_el is None or not iban_el.text:
        # Other Id (numéro de compte non-IBAN, ex. comptes anciens)
        other_id = _find_local(stmt, "Acct", "Id", "Othr", "Id")
        if other_id is None or not other_id.text:
            raise ValueError("CAMT.053 invalide : pas d'IBAN ni Othr/Id")
        iban = other_id.text.strip()
    else:
        iban = iban_el.text.strip()

    transactions: list[BankTransactionData] = []
    for ntry in _findall_local(stmt, "Ntry"):
        parsed = _parse_ntry(ntry, iban)
        if parsed is not None:
            transactions.append(parsed)

    return iban, transactions


# --- Import + persist -------------------------------------------------------


def import_camt053_file(
    *,
    path: Path,
    cabinet_id: str,
    client_id: str,
    conn: sqlite3.Connection,
) -> CamtImportSummary:
    """Parse un fichier CAMT.053 et persiste les transactions en DB.

    Idempotent via UNIQUE (cabinet_id, client_id, iban, value_date,
    amount_chf, bank_ref) : ré-import = 0 nouveaux.

    Multi-mandant strict : `cabinet_id` et `client_id` obligatoires.

    Returns:
        CamtImportSummary avec compteurs.
    """
    import time
    t0 = time.perf_counter()
    init_bank_schema(conn)

    xml_bytes = Path(path).read_bytes()
    iban, transactions = parse_camt053(xml_bytes)

    summary = CamtImportSummary(
        cabinet_id=cabinet_id, client_id=client_id, file_path=Path(path),
        iban=iban,
    )
    summary.transactions_total = len(transactions)

    for tx in transactions:
        cur = conn.execute(
            """
            INSERT OR IGNORE INTO bank_transactions
              (cabinet_id, client_id, iban, value_date, booking_date,
               amount_chf, currency, credit_debit, description,
               qr_reference, end_to_end_id, creditor_name, debtor_name,
               bank_ref, raw_xml_blob)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                cabinet_id, client_id, tx.iban, tx.value_date, tx.booking_date,
                tx.amount_chf, tx.currency, tx.credit_debit, tx.description,
                tx.qr_reference, tx.end_to_end_id, tx.creditor_name,
                tx.debtor_name, tx.bank_ref, tx.raw_xml,
            ),
        )
        if cur.rowcount == 1:
            summary.transactions_inserted += 1
        else:
            summary.transactions_duplicates += 1

    summary.duration_s = time.perf_counter() - t0
    _log.info(
        "CAMT.053 imported cabinet=%s client=%s iban=%s "
        "total=%d new=%d dup=%d dur=%.2fs",
        cabinet_id, client_id, iban, summary.transactions_total,
        summary.transactions_inserted, summary.transactions_duplicates,
        summary.duration_s,
    )
    return summary


# --- Query helpers ----------------------------------------------------------


def _row_to_bank_tx(row: sqlite3.Row) -> BankTransaction:
    return BankTransaction(
        id=int(row["id"]),
        cabinet_id=row["cabinet_id"], client_id=row["client_id"],
        iban=row["iban"], value_date=row["value_date"],
        amount_chf=float(row["amount_chf"]), currency=row["currency"],
        credit_debit=row["credit_debit"],
        description=row["description"], qr_reference=row["qr_reference"],
        end_to_end_id=row["end_to_end_id"],
        creditor_name=row["creditor_name"], debtor_name=row["debtor_name"],
        bank_ref=row["bank_ref"],
        matched_document_id=row["matched_document_id"],
        matched_accounting_entry_id=row["matched_accounting_entry_id"],
        match_confidence=row["match_confidence"],
        match_strategy=row["match_strategy"],
        imported_at=row["imported_at"],
    )


def get_unmatched_transactions(
    *,
    cabinet_id: str,
    client_id: str | None,
    conn: sqlite3.Connection,
    limit: int | None = None,
    only_credits: bool = False,
) -> list[BankTransaction]:
    """Liste les transactions non encore matchées à une facture."""
    sql = (
        "SELECT * FROM bank_transactions "
        "WHERE cabinet_id=? AND matched_document_id IS NULL"
    )
    params: list = [cabinet_id]
    if client_id:
        sql += " AND client_id=?"
        params.append(client_id)
    if only_credits:
        sql += " AND credit_debit='CRDT'"
    sql += " ORDER BY value_date DESC, id DESC"
    if limit:
        sql += " LIMIT ?"
        params.append(limit)
    rows = conn.execute(sql, params).fetchall()
    return [_row_to_bank_tx(r) for r in rows]


def get_transaction(
    conn: sqlite3.Connection, transaction_id: int,
) -> BankTransaction | None:
    row = conn.execute(
        "SELECT * FROM bank_transactions WHERE id=?", (transaction_id,),
    ).fetchone()
    return _row_to_bank_tx(row) if row else None
