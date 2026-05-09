// Driver SQLite local READ-ONLY pour le dashboard POC.
// Lit la base alimentée par worker/ (data/fiduciaire.sqlite).
// Sprint 0a /review : seules les lectures.
// Sprint 0a /entries : lectures ici, écritures dans `lib/db-poc-write.ts`.

import Database from "better-sqlite3";
import path from "node:path";
import fs from "node:fs";

// Résolution path robuste : env var override → cwd → resolve relatif au fichier.
// Next 16 + turbopack peut placer cwd ailleurs si plusieurs lockfiles existent.
function resolveDbPath(): string {
  const env = process.env.FIDUCIAIRE_DB_PATH;
  if (env) return path.resolve(env);
  const candidates = [
    path.join(process.cwd(), "data", "fiduciaire.sqlite"),
    // Quand cwd diverge (workspace root vs project), on remonte depuis ce fichier.
    path.resolve(__dirname, "..", "data", "fiduciaire.sqlite"),
    path.resolve(__dirname, "..", "..", "data", "fiduciaire.sqlite"),
  ];
  for (const c of candidates) {
    if (fs.existsSync(c)) return c;
  }
  return candidates[0];
}

const DB_PATH = resolveDbPath();

// Pas de mémoïsation : ouvrir/fermer à chaque query évite les caches stale
// quand le worker Python ré-écrit la DB. Coût ~1 ms par open sur SQLite local.
// Si la DB n'existe pas, ouvre une DB en mémoire vide pour que les
// `tableExists` retournent false sans planter.
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

export type DocStatus =
  | "ingested"
  | "classified"
  | "routed"
  | "needs_review"
  | "failed"
  | "duplicate";

export type DocRow = {
  id: number;
  sha256: string;
  original_filename: string;
  archive_path: string;
  type: string | null;
  client_slug: string | null;
  doc_date: string | null;
  montant_chf: number | null;
  status: DocStatus;
  needs_review_reason: string | null;
  final_path: string | null;
  created_at: string;
  updated_at: string;
  classification_json: string | null;
};

export type ActionRow = {
  id: number;
  document_id: number;
  action: string;
  duration_ms: number | null;
  ok: number;
  error: string | null;
  created_at: string;
};

export function listDocuments(limit = 200): DocRow[] {
  return withDb((db) => {
    if (!tableExists(db, "documents")) return [];
    return db
      .prepare(
        `SELECT id, sha256, original_filename, archive_path, type, client_slug,
                doc_date, montant_chf, status, needs_review_reason, final_path,
                created_at, updated_at, classification_json
         FROM documents
         ORDER BY datetime(created_at) DESC
         LIMIT ?`,
      )
      .all(limit) as DocRow[];
  });
}

export function listNeedsReview(): DocRow[] {
  return withDb((db) => {
    if (!tableExists(db, "documents")) return [];
    return db
      .prepare(
        `SELECT id, sha256, original_filename, archive_path, type, client_slug,
                doc_date, montant_chf, status, needs_review_reason, final_path,
                created_at, updated_at, classification_json
         FROM documents
         WHERE status='needs_review'
         ORDER BY datetime(created_at) DESC`,
      )
      .all() as DocRow[];
  });
}

export function listRecentActions(hoursBack = 24, limit = 30): ActionRow[] {
  return withDb((db) => {
    if (!tableExists(db, "actions")) return [];
    return db
      .prepare(
        `SELECT id, document_id, action, duration_ms, ok, error, created_at
         FROM actions
         WHERE datetime(created_at) >= datetime('now', ?)
         ORDER BY datetime(created_at) DESC
         LIMIT ?`,
      )
      .all(`-${hoursBack} hours`, limit) as ActionRow[];
  });
}

export type Kpis = {
  totalDocs: number;
  routedDocs: number;
  needsReviewCount: number;
  failedCount: number;
  precisionPct: number;
  classifyLatencyMedianMs: number | null;
};

export function getKpis(): Kpis {
  const empty: Kpis = {
    totalDocs: 0,
    routedDocs: 0,
    needsReviewCount: 0,
    failedCount: 0,
    precisionPct: 0,
    classifyLatencyMedianMs: null,
  };
  return withDb((db) => {
    if (!tableExists(db, "documents")) return empty;

    const counts = db
      .prepare(
        `SELECT
           COUNT(*) AS total,
           SUM(CASE WHEN status='routed' THEN 1 ELSE 0 END) AS routed,
           SUM(CASE WHEN status='needs_review' THEN 1 ELSE 0 END) AS review,
           SUM(CASE WHEN status='failed' THEN 1 ELSE 0 END) AS failed
         FROM documents`,
      )
      .get() as {
      total: number;
      routed: number | null;
      review: number | null;
      failed: number | null;
    };

    const routed = counts.routed ?? 0;
    const review = counts.review ?? 0;
    const failed = counts.failed ?? 0;
    const decided = routed + review + failed;
    const precisionPct = decided > 0 ? (routed / decided) * 100 : 0;

    let medianMs: number | null = null;
    if (tableExists(db, "actions")) {
      const rows = db
        .prepare(
          `SELECT duration_ms FROM actions
           WHERE action='classify' AND duration_ms IS NOT NULL AND ok=1
           ORDER BY duration_ms`,
        )
        .all() as { duration_ms: number }[];
      if (rows.length > 0) {
        const mid = Math.floor(rows.length / 2);
        medianMs =
          rows.length % 2
            ? rows[mid].duration_ms
            : Math.round((rows[mid - 1].duration_ms + rows[mid].duration_ms) / 2);
      }
    }

    return {
      totalDocs: counts.total ?? 0,
      routedDocs: routed,
      needsReviewCount: review,
      failedCount: failed,
      precisionPct,
      classifyLatencyMedianMs: medianMs,
    };
  });
}

export type VolumePoint = { date: string; volume: number };

export function getVolumeLast7Days(): VolumePoint[] {
  const emptyPoints = (): VolumePoint[] =>
    Array.from({ length: 7 }, (_, i) => {
      const d = new Date();
      d.setDate(d.getDate() - (6 - i));
      return { date: d.toISOString().slice(0, 10), volume: 0 };
    });

  return withDb((db) => {
    if (!tableExists(db, "documents")) return emptyPoints();
    const rows = db
      .prepare(
        `SELECT date(created_at) AS day, COUNT(*) AS n
         FROM documents
         WHERE date(created_at) >= date('now', '-6 days')
         GROUP BY day
         ORDER BY day ASC`,
      )
      .all() as { day: string; n: number }[];
    const byDay = new Map(rows.map((r) => [r.day, r.n]));
    const out: VolumePoint[] = [];
    for (let i = 6; i >= 0; i--) {
      const d = new Date();
      d.setDate(d.getDate() - i);
      const iso = d.toISOString().slice(0, 10);
      out.push({ date: iso, volume: byDay.get(iso) ?? 0 });
    }
    return out;
  });
}

export function dbExists(): boolean {
  if (!fs.existsSync(DB_PATH)) return false;
  return withDb((db) => tableExists(db, "documents"));
}

// --- Sprint 0a /entries — lectures accounting_entries ----------------------

export type EntryState = "proposed" | "validated" | "rejected";

export type EntryRow = {
  id: number;
  client_id: string;
  source_document_id: number;
  date: string;
  debit_account: string;
  credit_account: string;
  amount_chf: number;
  vat_code: string;
  vat_amount: number | null;
  description: string;
  confidence_account: number;
  confidence_vat: number;
  reasoning: string | null;
  sources_json: string | null;
  state: EntryState;
  created_at: string;
  updated_at: string;
  // Joined depuis documents (lecture seule)
  doc_filename: string | null;
  doc_archive_path: string | null;
  doc_montant_chf: number | null;
};

export type EntryStateChange = {
  id: number;
  entry_id: number;
  from_state: string;
  to_state: string;
  user_id: string | null;
  reason: string | null;
  changed_at: string;
};

export type ClientSummary = {
  client_id: string;
  n_proposed: number;
  n_validated: number;
  n_rejected: number;
};

export type EntryFilters = {
  clientId: string;
  state?: EntryState;
  confidenceMin?: number;
  dateFrom?: string;
  dateTo?: string;
  amountMin?: number;
  amountMax?: number;
  limit?: number;
  offset?: number;
};

export function listClients(): ClientSummary[] {
  return withDb((db) => {
    if (!tableExists(db, "accounting_entries")) return [];
    return db
      .prepare(
        `SELECT
           client_id,
           SUM(CASE WHEN state='proposed'  THEN 1 ELSE 0 END) AS n_proposed,
           SUM(CASE WHEN state='validated' THEN 1 ELSE 0 END) AS n_validated,
           SUM(CASE WHEN state='rejected'  THEN 1 ELSE 0 END) AS n_rejected
         FROM accounting_entries
         GROUP BY client_id
         ORDER BY client_id ASC`,
      )
      .all() as ClientSummary[];
  });
}

export function listAccountingEntries(filters: EntryFilters): EntryRow[] {
  const limit = filters.limit ?? 100;
  const offset = filters.offset ?? 0;
  return withDb((db) => {
    if (!tableExists(db, "accounting_entries")) return [];
    const wheres: string[] = ["e.client_id = ?"];
    const params: unknown[] = [filters.clientId];
    if (filters.state) {
      wheres.push("e.state = ?");
      params.push(filters.state);
    }
    if (typeof filters.confidenceMin === "number") {
      wheres.push("MIN(e.confidence_account, e.confidence_vat) >= ?");
      params.push(filters.confidenceMin);
    }
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
    params.push(limit, offset);
    return db
      .prepare(
        `SELECT e.*,
                d.original_filename AS doc_filename,
                d.archive_path      AS doc_archive_path,
                d.montant_chf       AS doc_montant_chf
         FROM accounting_entries e
         LEFT JOIN documents d ON d.id = e.source_document_id
         WHERE ${wheres.join(" AND ")}
         ORDER BY datetime(e.created_at) DESC
         LIMIT ? OFFSET ?`,
      )
      .all(...params) as EntryRow[];
  });
}

export function countAccountingEntries(filters: EntryFilters): number {
  return withDb((db) => {
    if (!tableExists(db, "accounting_entries")) return 0;
    const wheres: string[] = ["client_id = ?"];
    const params: unknown[] = [filters.clientId];
    if (filters.state) {
      wheres.push("state = ?");
      params.push(filters.state);
    }
    const row = db
      .prepare(
        `SELECT COUNT(*) AS n FROM accounting_entries WHERE ${wheres.join(" AND ")}`,
      )
      .get(...params) as { n: number };
    return row.n;
  });
}

export function getAccountingEntry(
  id: number,
  clientId: string,
): EntryRow | null {
  return withDb((db) => {
    if (!tableExists(db, "accounting_entries")) return null;
    const row = db
      .prepare(
        `SELECT e.*,
                d.original_filename AS doc_filename,
                d.archive_path      AS doc_archive_path,
                d.montant_chf       AS doc_montant_chf
         FROM accounting_entries e
         LEFT JOIN documents d ON d.id = e.source_document_id
         WHERE e.id = ? AND e.client_id = ?`,
      )
      .get(id, clientId) as EntryRow | undefined;
    return row ?? null;
  });
}

export function listEntryHistory(
  entryId: number,
  clientId: string,
): EntryStateChange[] {
  return withDb((db) => {
    if (!tableExists(db, "entry_state_changes")) return [];
    // Cross-tenant : on rejoint accounting_entries pour vérifier le client_id.
    return db
      .prepare(
        `SELECT esc.*
         FROM entry_state_changes esc
         JOIN accounting_entries e ON e.id = esc.entry_id
         WHERE esc.entry_id = ? AND e.client_id = ?
         ORDER BY esc.id ASC`,
      )
      .all(entryId, clientId) as EntryStateChange[];
  });
}

export function getDocumentArchivePathForEntry(
  documentId: number,
  clientId: string,
): string | null {
  return withDb((db) => {
    if (!tableExists(db, "accounting_entries")) return null;
    const row = db
      .prepare(
        `SELECT d.archive_path
         FROM documents d
         JOIN accounting_entries e ON e.source_document_id = d.id
         WHERE d.id = ? AND e.client_id = ?
         LIMIT 1`,
      )
      .get(documentId, clientId) as { archive_path?: string } | undefined;
    return row?.archive_path ?? null;
  });
}

export function getDbPath(): string {
  return DB_PATH;
}
