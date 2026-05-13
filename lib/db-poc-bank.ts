// Driver SQLite READ pour le dashboard /(poc)/bank — Sprint 2 §3.10 Phase 4.
//
// Liste les transactions bancaires non matchées (CAMT.053 importé) et les
// factures non payées du même cabinet, pour permettre le matching manuel.
//
// Multi-mandant strict : filtres `cabinet_id` côté bank_transactions et
// `client_id` côté accounting_entries. Le matching cross-mandant est bloqué
// par les Server Actions, pas ici.
//
// Decrypt automatique des colonnes chiffrées via decryptColumnValueSafe.

import Database from "better-sqlite3";
import path from "node:path";
import fs from "node:fs";
import { decryptColumnValueSafe } from "./encryption-ts";

function resolveDbPath(): string {
  const env = process.env.FIDUCIAIRE_DB_PATH;
  if (env) return path.resolve(env);
  const candidates = [
    path.join(process.cwd(), "data", "fiduciaire.sqlite"),
    path.resolve(__dirname, "..", "data", "fiduciaire.sqlite"),
    path.resolve(__dirname, "..", "..", "data", "fiduciaire.sqlite"),
  ];
  for (const c of candidates) {
    if (fs.existsSync(c)) return c;
  }
  return candidates[0];
}

const DB_PATH = resolveDbPath();

function withDb<T>(fn: (db: Database.Database) => T): T {
  const exists = fs.existsSync(DB_PATH);
  const conn = exists
    ? new Database(DB_PATH, { readonly: true, fileMustExist: true })
    : new Database(":memory:");
  try {
    return fn(conn);
  } finally {
    conn.close();
  }
}

function tableExists(db: Database.Database, name: string): boolean {
  try {
    const row = db
      .prepare("SELECT name FROM sqlite_master WHERE type='table' AND name=?")
      .get(name) as { name?: string } | undefined;
    return !!row?.name;
  } catch {
    return false;
  }
}

// --- Types -----------------------------------------------------------------

export type BankFilters = {
  cabinetId: string;
  dateFrom?: string;
  dateTo?: string;
  amountMin?: number;
  amountMax?: number;
  limit?: number;
};

export type UnmatchedTransactionRow = {
  id: number;
  cabinet_id: string;
  client_id: string;
  iban: string;
  iban_last4: string;
  value_date: string;
  amount_chf: number;
  currency: string;
  credit_debit: string;
  description: string;
  qr_reference: string | null;
  creditor_name: string | null;
  debtor_name: string | null;
};

export type UnpaidInvoiceRow = {
  id: number;
  client_id: string;
  date: string;
  debit_account: string;
  credit_account: string;
  amount_chf: number;
  vat_code: string;
  description: string;
  state: string;
  source_document_id: number;
  bexio_id: string | null;
  doc_filename: string | null;
};

export type BankStats = {
  unmatched_count: number;
  unmatched_amount_total: number;
  unpaid_count: number;
  unpaid_amount_total: number;
  matched_count: number;
  match_rate_pct: number; // 0..100, basé sur (matched / (matched + unmatched))
};

// --- Listings --------------------------------------------------------------

export function listUnmatchedTransactions(
  filters: BankFilters,
): UnmatchedTransactionRow[] {
  const limit = filters.limit ?? 200;
  return withDb((db) => {
    if (!tableExists(db, "bank_transactions")) return [];
    const wheres: string[] = ["cabinet_id = ?", "matched_document_id IS NULL"];
    const params: unknown[] = [filters.cabinetId];
    if (filters.dateFrom) {
      wheres.push("value_date >= ?");
      params.push(filters.dateFrom);
    }
    if (filters.dateTo) {
      wheres.push("value_date <= ?");
      params.push(filters.dateTo);
    }
    if (typeof filters.amountMin === "number") {
      wheres.push("amount_chf >= ?");
      params.push(filters.amountMin);
    }
    if (typeof filters.amountMax === "number") {
      wheres.push("amount_chf <= ?");
      params.push(filters.amountMax);
    }
    params.push(limit);
    const rows = db
      .prepare(
        `SELECT id, cabinet_id, client_id, iban, value_date, amount_chf,
                currency, credit_debit, description, qr_reference,
                creditor_name, debtor_name
         FROM bank_transactions
         WHERE ${wheres.join(" AND ")}
         ORDER BY value_date DESC, id DESC
         LIMIT ?`,
      )
      .all(...params) as Array<{
      id: number;
      cabinet_id: string;
      client_id: string;
      iban: string;
      value_date: string;
      amount_chf: number;
      currency: string;
      credit_debit: string;
      description: string | null;
      qr_reference: string | null;
      creditor_name: string | null;
      debtor_name: string | null;
    }>;
    return rows.map((r) => ({
      id: r.id,
      cabinet_id: r.cabinet_id,
      client_id: r.client_id,
      iban: r.iban,
      iban_last4: r.iban.slice(-4),
      value_date: r.value_date,
      amount_chf: r.amount_chf,
      currency: r.currency,
      credit_debit: r.credit_debit,
      description: decryptColumnValueSafe(r.description, filters.cabinetId),
      qr_reference: r.qr_reference,
      creditor_name: r.creditor_name
        ? decryptColumnValueSafe(r.creditor_name, filters.cabinetId)
        : null,
      debtor_name: r.debtor_name
        ? decryptColumnValueSafe(r.debtor_name, filters.cabinetId)
        : null,
    }));
  });
}

/**
 * Factures émises non payées : accounting_entries en state validated/published
 * avec bexio_id non null (proxy "facture émise") qui n'ont pas encore de
 * bank_transactions.matched_document_id pointant dessus.
 */
export function listUnpaidInvoices(filters: BankFilters): UnpaidInvoiceRow[] {
  const limit = filters.limit ?? 200;
  return withDb((db) => {
    if (!tableExists(db, "accounting_entries")) return [];
    const wheres: string[] = [
      "e.client_id = ?",
      "e.state IN ('validated', 'published')",
      "e.bexio_id IS NOT NULL",
      `NOT EXISTS (
         SELECT 1 FROM bank_transactions bt
         WHERE bt.matched_document_id = e.source_document_id
           AND bt.cabinet_id = e.client_id
       )`,
    ];
    const params: unknown[] = [filters.cabinetId];
    if (filters.dateFrom) {
      wheres.push("e.date >= ?");
      params.push(filters.dateFrom);
    }
    if (filters.dateTo) {
      wheres.push("e.date <= ?");
      params.push(filters.dateTo);
    }
    if (typeof filters.amountMin === "number") {
      wheres.push("e.amount_chf >= ?");
      params.push(filters.amountMin);
    }
    if (typeof filters.amountMax === "number") {
      wheres.push("e.amount_chf <= ?");
      params.push(filters.amountMax);
    }
    params.push(limit);
    const rows = db
      .prepare(
        `SELECT e.id, e.client_id, e.date, e.debit_account, e.credit_account,
                e.amount_chf, e.vat_code, e.description, e.state,
                e.source_document_id, e.bexio_id,
                d.original_filename AS doc_filename
         FROM accounting_entries e
         LEFT JOIN documents d ON d.id = e.source_document_id
         WHERE ${wheres.join(" AND ")}
         ORDER BY e.date DESC, e.id DESC
         LIMIT ?`,
      )
      .all(...params) as UnpaidInvoiceRow[];
    return rows.map((r) => ({
      ...r,
      description: decryptColumnValueSafe(r.description, filters.cabinetId),
    }));
  });
}

// --- Stats -----------------------------------------------------------------

export function getBankStats(cabinetId: string): BankStats {
  return withDb((db) => {
    const empty: BankStats = {
      unmatched_count: 0,
      unmatched_amount_total: 0,
      unpaid_count: 0,
      unpaid_amount_total: 0,
      matched_count: 0,
      match_rate_pct: 0,
    };
    const hasBank = tableExists(db, "bank_transactions");
    const hasEntries = tableExists(db, "accounting_entries");

    let unmatched = { n: 0, total: 0 };
    let matched = { n: 0 };
    if (hasBank) {
      unmatched = db
        .prepare(
          `SELECT COUNT(*) AS n,
                  COALESCE(SUM(amount_chf), 0) AS total
           FROM bank_transactions
           WHERE cabinet_id = ? AND matched_document_id IS NULL`,
        )
        .get(cabinetId) as { n: number; total: number };
      matched = db
        .prepare(
          `SELECT COUNT(*) AS n FROM bank_transactions
           WHERE cabinet_id = ? AND matched_document_id IS NOT NULL`,
        )
        .get(cabinetId) as { n: number };
    }

    let unpaid = { n: 0, total: 0 };
    if (hasEntries) {
      unpaid = db
        .prepare(
          `SELECT COUNT(*) AS n,
                  COALESCE(SUM(e.amount_chf), 0) AS total
           FROM accounting_entries e
           WHERE e.client_id = ?
             AND e.state IN ('validated', 'published')
             AND e.bexio_id IS NOT NULL
             AND NOT EXISTS (
               SELECT 1 FROM bank_transactions bt
               WHERE bt.matched_document_id = e.source_document_id
                 AND bt.cabinet_id = e.client_id
             )`,
        )
        .get(cabinetId) as { n: number; total: number };
    }

    const totalScanned = matched.n + unmatched.n;
    const matchRate =
      totalScanned > 0 ? (matched.n / totalScanned) * 100 : 0;

    return {
      unmatched_count: unmatched.n,
      unmatched_amount_total: unmatched.total,
      unpaid_count: unpaid.n,
      unpaid_amount_total: unpaid.total,
      matched_count: matched.n,
      match_rate_pct: matchRate,
    };
  });
}

// --- Cabinet list (réutilisé pour le sélecteur mandant) --------------------

export type BankCabinetSummary = { cabinet_id: string; tx_count: number };

export function listBankCabinets(): BankCabinetSummary[] {
  return withDb((db) => {
    if (!tableExists(db, "bank_transactions")) return [];
    return db
      .prepare(
        `SELECT cabinet_id, COUNT(*) AS tx_count
         FROM bank_transactions
         GROUP BY cabinet_id
         ORDER BY cabinet_id`,
      )
      .all() as BankCabinetSummary[];
  });
}

// --- Validation cross-mandant ---------------------------------------------

export type LinkValidation =
  | {
      ok: true;
      cabinetId: string;
      documentId: number;
      accountingEntryId: number | null;
    }
  | { ok: false; reason: string };

/**
 * Vérifie qu'une transaction et une écriture appartiennent au même cabinet
 * (= multi-mandant strict). Renvoie aussi le document_id et accounting_entry_id
 * à persister via `manuallyLinkTransaction`.
 *
 * Open in read mode for validation, the actual mutation runs in
 * `lib/db-poc-bank-write.ts`.
 */
export function validateManualLink(
  transactionId: number,
  entryId: number,
): LinkValidation {
  return withDb((db) => {
    if (
      !tableExists(db, "bank_transactions") ||
      !tableExists(db, "accounting_entries")
    ) {
      return { ok: false, reason: "schéma incomplet" };
    }
    const tx = db
      .prepare(
        "SELECT id, cabinet_id, client_id FROM bank_transactions WHERE id = ?",
      )
      .get(transactionId) as
      | { id: number; cabinet_id: string; client_id: string }
      | undefined;
    if (!tx) return { ok: false, reason: "transaction introuvable" };
    const entry = db
      .prepare(
        "SELECT id, client_id, source_document_id FROM accounting_entries " +
          "WHERE id = ?",
      )
      .get(entryId) as
      | { id: number; client_id: string; source_document_id: number }
      | undefined;
    if (!entry) return { ok: false, reason: "écriture introuvable" };
    if (tx.cabinet_id !== entry.client_id) {
      return {
        ok: false,
        reason:
          `cross-mandant interdit : tx cabinet=${tx.cabinet_id} ` +
          `entry client=${entry.client_id}`,
      };
    }
    return {
      ok: true,
      cabinetId: tx.cabinet_id,
      documentId: entry.source_document_id,
      accountingEntryId: entry.id,
    };
  });
}
