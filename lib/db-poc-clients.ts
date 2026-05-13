// Driver SQLite READ pour le dashboard /(poc)/clients/[client_id].
// Sprint 2 §3.10 — vue par mandant : stats, anomalies, audit, bank.
//
// Multi-mandant strict : toutes les queries filtrent par client_id.
// Cohabite avec le worker Python via WAL mode.
//
// Sprint 2 ultérieur : decrypt côté TS des colonnes chiffrées (`enc:v1:`)
// via lib `fernet` npm + clé Keychain. Pour l'instant, en dev/test la DB
// est en clair (FIDUCIAIRE_ENCRYPTION_DISABLED=true côté worker Python).

import Database from "better-sqlite3";
import path from "node:path";
import fs from "node:fs";

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
  const dbExistsOnDisk = fs.existsSync(DB_PATH);
  const conn = dbExistsOnDisk
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

const ENC_MARKER = "enc:v1:";

/**
 * Sprint 2 §3.10 — affichage défensif des valeurs potentiellement chiffrées.
 * En dev/test : valeurs en clair → return as-is.
 * En prod chiffré : return `[chiffré]` (decrypt TS à venir Sprint 2 ultérieur).
 */
export function displayPossiblyEncrypted(
  value: string | null | undefined,
): string {
  if (!value) return "";
  if (typeof value === "string" && value.startsWith(ENC_MARKER)) {
    return "[chiffré]";
  }
  return value;
}

// --- Types -------------------------------------------------------------------

export type ClientStats = {
  client_id: string;
  validated_count_month: number;
  validated_amount_month: number;
  proposed_count: number;
  rejected_count: number;
  anomalies_open_count: number;
  docs_count_month: number;
};

export type ClientRecentEntry = {
  id: number;
  date: string;
  debit_account: string;
  credit_account: string;
  amount_chf: number;
  vat_code: string;
  description: string;
  state: string;
  source_document_id: number;
  doc_filename: string | null;
};

export type ClientAnomalyRow = {
  id: number;
  type: string;
  severity: string;
  state: string;
  subject_entity_type: string;
  subject_entity_id: string;
  details_json: string | null;
  detected_at: string;
};

export type ClientAuditEventRow = {
  id: number;
  timestamp: string;
  user_id: string | null;
  entity_type: string;
  entity_id: string;
  action: string;
};

export type ClientBankStats = {
  unmatched_count: number;
  unmatched_amount_total: number;
  matched_count: number;
};

// --- Stats -------------------------------------------------------------------

export function getClientStats(clientId: string): ClientStats {
  return withDb((db) => {
    const empty: ClientStats = {
      client_id: clientId,
      validated_count_month: 0,
      validated_amount_month: 0,
      proposed_count: 0,
      rejected_count: 0,
      anomalies_open_count: 0,
      docs_count_month: 0,
    };
    if (!tableExists(db, "accounting_entries")) return empty;

    // Premier jour du mois courant ISO
    const now = new Date();
    const firstOfMonth = new Date(now.getFullYear(), now.getMonth(), 1)
      .toISOString()
      .slice(0, 10);

    const entryStats = db
      .prepare(
        `SELECT
           SUM(CASE WHEN state='validated' AND date >= ? THEN 1 ELSE 0 END) AS v_count,
           COALESCE(SUM(CASE WHEN state='validated' AND date >= ?
                             THEN amount_chf ELSE 0 END), 0)              AS v_amount,
           SUM(CASE WHEN state='proposed'  THEN 1 ELSE 0 END) AS p_count,
           SUM(CASE WHEN state='rejected'  THEN 1 ELSE 0 END) AS r_count
         FROM accounting_entries
         WHERE client_id = ?`,
      )
      .get(firstOfMonth, firstOfMonth, clientId) as {
      v_count: number | null;
      v_amount: number | null;
      p_count: number | null;
      r_count: number | null;
    };

    const anomaliesOpen = tableExists(db, "anomalies")
      ? (db
          .prepare(
            "SELECT COUNT(*) AS n FROM anomalies WHERE client_id=? AND state='open'",
          )
          .get(clientId) as { n: number }).n
      : 0;

    const docsMonth = tableExists(db, "documents")
      ? (db
          .prepare(
            "SELECT COUNT(*) AS n FROM documents WHERE client_slug=? " +
              "AND date(created_at) >= ?",
          )
          .get(clientId, firstOfMonth) as { n: number }).n
      : 0;

    return {
      client_id: clientId,
      validated_count_month: entryStats.v_count ?? 0,
      validated_amount_month: entryStats.v_amount ?? 0,
      proposed_count: entryStats.p_count ?? 0,
      rejected_count: entryStats.r_count ?? 0,
      anomalies_open_count: anomaliesOpen,
      docs_count_month: docsMonth,
    };
  });
}

// --- Recent entries ----------------------------------------------------------

export function listClientRecentEntries(
  clientId: string,
  limit = 10,
): ClientRecentEntry[] {
  return withDb((db) => {
    if (!tableExists(db, "accounting_entries")) return [];
    return db
      .prepare(
        `SELECT e.id, e.date, e.debit_account, e.credit_account,
                e.amount_chf, e.vat_code, e.description, e.state,
                e.source_document_id,
                d.original_filename AS doc_filename
         FROM accounting_entries e
         LEFT JOIN documents d ON d.id = e.source_document_id
         WHERE e.client_id = ?
         ORDER BY datetime(e.created_at) DESC
         LIMIT ?`,
      )
      .all(clientId, limit) as ClientRecentEntry[];
  });
}

// --- Anomalies open ----------------------------------------------------------

export function listClientOpenAnomalies(
  clientId: string,
  limit = 20,
): ClientAnomalyRow[] {
  return withDb((db) => {
    if (!tableExists(db, "anomalies")) return [];
    return db
      .prepare(
        `SELECT id, type, severity, state, subject_entity_type,
                subject_entity_id, details_json, detected_at
         FROM anomalies
         WHERE client_id = ? AND state = 'open'
         ORDER BY detected_at DESC
         LIMIT ?`,
      )
      .all(clientId, limit) as ClientAnomalyRow[];
  });
}

// --- Audit récent ------------------------------------------------------------

export function listClientRecentAuditEvents(
  clientId: string,
  limit = 5,
): ClientAuditEventRow[] {
  return withDb((db) => {
    if (!tableExists(db, "audit_log")) return [];
    return db
      .prepare(
        `SELECT id, timestamp, user_id, entity_type, entity_id, action
         FROM audit_log
         WHERE cabinet_id = ?
         ORDER BY id DESC
         LIMIT ?`,
      )
      .all(clientId, limit) as ClientAuditEventRow[];
  });
}

// --- Bank stats --------------------------------------------------------------

export function getClientBankStats(clientId: string): ClientBankStats {
  return withDb((db) => {
    const empty: ClientBankStats = {
      unmatched_count: 0,
      unmatched_amount_total: 0,
      matched_count: 0,
    };
    if (!tableExists(db, "bank_transactions")) return empty;

    const unmatched = db
      .prepare(
        `SELECT COUNT(*) AS n,
                COALESCE(SUM(amount_chf), 0) AS total
         FROM bank_transactions
         WHERE cabinet_id = ? AND matched_document_id IS NULL`,
      )
      .get(clientId) as { n: number; total: number };
    const matched = db
      .prepare(
        "SELECT COUNT(*) AS n FROM bank_transactions " +
          "WHERE cabinet_id = ? AND matched_document_id IS NOT NULL",
      )
      .get(clientId) as { n: number };

    return {
      unmatched_count: unmatched.n,
      unmatched_amount_total: unmatched.total,
      matched_count: matched.n,
    };
  });
}
