// Driver SQLite WRITE pour le dashboard /(poc)/entries.
// Sprint 0a : isolation multi-mandant stricte, transitions d'états atomiques,
// audit log dans entry_state_changes. Cohabite avec le worker Python via WAL
// mode (init_schema active PRAGMA journal_mode=WAL).
//
// Toutes les mutations sont :
//   1. Vérifiées (entry existe + appartient au client_id donné)
//   2. Transition state validée (cf workflow_states.py côté Python)
//   3. Transactionnelles (UPDATE entries + INSERT state_changes ou rollback)

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

// Cohérence avec workflow_states.py — mêmes transitions autorisées.
const ALLOWED_TRANSITIONS: Record<string, Set<string>> = {
  proposed: new Set(["validated", "rejected", "proposed"]),
  validated: new Set(["proposed"]),
  rejected: new Set(),
};

export class EntryNotFoundError extends Error {
  constructor(id: number) {
    super(`entry ${id} introuvable ou hors scope mandant`);
    this.name = "EntryNotFoundError";
  }
}

export class InvalidTransitionError extends Error {
  constructor(from: string, to: string) {
    super(`transition ${from} → ${to} non autorisée`);
    this.name = "InvalidTransitionError";
  }
}

export type CorrectionPayload = {
  debit_account?: string;
  credit_account?: string;
  amount_chf?: number;
  vat_code?: string;
  vat_amount?: number;
  description?: string;
};

const ALLOWED_CORRECTION_FIELDS = new Set([
  "debit_account",
  "credit_account",
  "amount_chf",
  "vat_code",
  "vat_amount",
  "description",
]);

function withWriteDb<T>(fn: (db: Database.Database) => T): T {
  if (!fs.existsSync(DB_PATH)) {
    throw new Error(
      `Base SQLite introuvable au chemin ${DB_PATH}. Lance le worker Python d'abord pour init le schéma.`,
    );
  }
  const conn = new Database(DB_PATH, { fileMustExist: true });
  // Cohabitation worker Python : WAL est déjà actif côté Python, on s'en assure
  // côté Node aussi pour autoriser lectures concurrentes pendant un write.
  conn.pragma("journal_mode = WAL");
  conn.pragma("foreign_keys = ON");
  try {
    return fn(conn);
  } finally {
    conn.close();
  }
}

type EntryStateRow = { id: number; state: string; client_id: string };

function fetchEntryState(
  db: Database.Database,
  id: number,
  clientId: string,
): EntryStateRow {
  const row = db
    .prepare(
      `SELECT id, state, client_id FROM accounting_entries
       WHERE id = ? AND client_id = ?`,
    )
    .get(id, clientId) as EntryStateRow | undefined;
  if (!row) throw new EntryNotFoundError(id);
  return row;
}

function logStateChange(
  db: Database.Database,
  entryId: number,
  fromState: string,
  toState: string,
  userId: string | null,
  reason: string | null,
): void {
  db.prepare(
    `INSERT INTO entry_state_changes
       (entry_id, from_state, to_state, user_id, reason)
     VALUES (?, ?, ?, ?, ?)`,
  ).run(entryId, fromState, toState, userId, reason);
}

function assertTransitionAllowed(from: string, to: string): void {
  const allowed = ALLOWED_TRANSITIONS[from];
  if (!allowed || !allowed.has(to)) {
    throw new InvalidTransitionError(from, to);
  }
}

export function validateEntry(
  id: number,
  clientId: string,
  userId: string | null,
): void {
  withWriteDb((db) => {
    const txn = db.transaction(() => {
      const cur = fetchEntryState(db, id, clientId);
      assertTransitionAllowed(cur.state, "validated");
      db.prepare(
        `UPDATE accounting_entries
           SET state = 'validated', updated_at = datetime('now')
         WHERE id = ? AND client_id = ?`,
      ).run(id, clientId);
      logStateChange(db, id, cur.state, "validated", userId, null);
    });
    txn();
  });
}

export function correctEntry(
  id: number,
  clientId: string,
  userId: string | null,
  payload: CorrectionPayload,
): { fieldsChanged: string[] } {
  return withWriteDb((db) => {
    return db.transaction((): { fieldsChanged: string[] } => {
      const cur = fetchEntryState(db, id, clientId);
      // Correction = transition vers 'validated' (l'humain a accepté avec retouches).
      assertTransitionAllowed(cur.state, "validated");

      const setClauses: string[] = [];
      const params: unknown[] = [];
      const changed: string[] = [];
      for (const [key, value] of Object.entries(payload)) {
        if (!ALLOWED_CORRECTION_FIELDS.has(key)) continue;
        if (value === undefined || value === null || value === "") continue;
        setClauses.push(`${key} = ?`);
        params.push(value);
        changed.push(key);
      }
      if (setClauses.length === 0) {
        // Pas de changement — équivaut à un validate sec.
        db.prepare(
          `UPDATE accounting_entries
             SET state = 'validated', updated_at = datetime('now')
           WHERE id = ? AND client_id = ?`,
        ).run(id, clientId);
        logStateChange(db, id, cur.state, "validated", userId, "validated as-is");
        return { fieldsChanged: [] };
      }
      setClauses.push("state = 'validated'");
      setClauses.push("updated_at = datetime('now')");
      params.push(id, clientId);
      db.prepare(
        `UPDATE accounting_entries
           SET ${setClauses.join(", ")}
         WHERE id = ? AND client_id = ?`,
      ).run(...params);
      logStateChange(
        db,
        id,
        cur.state,
        "validated",
        userId,
        `corrected: ${changed.join(", ")}`,
      );
      return { fieldsChanged: changed };
    })();
  });
}

export function rejectEntry(
  id: number,
  clientId: string,
  userId: string | null,
  reason: string,
): void {
  if (!reason || reason.trim().length === 0) {
    throw new Error("reason obligatoire pour rejeter une écriture");
  }
  withWriteDb((db) => {
    const txn = db.transaction(() => {
      const cur = fetchEntryState(db, id, clientId);
      assertTransitionAllowed(cur.state, "rejected");
      db.prepare(
        `UPDATE accounting_entries
           SET state = 'rejected', updated_at = datetime('now')
         WHERE id = ? AND client_id = ?`,
      ).run(id, clientId);
      logStateChange(db, id, cur.state, "rejected", userId, reason.trim());
    });
    txn();
  });
}

export function reopenEntry(
  id: number,
  clientId: string,
  userId: string | null,
): void {
  withWriteDb((db) => {
    const txn = db.transaction(() => {
      const cur = fetchEntryState(db, id, clientId);
      assertTransitionAllowed(cur.state, "proposed");
      db.prepare(
        `UPDATE accounting_entries
           SET state = 'proposed', updated_at = datetime('now')
         WHERE id = ? AND client_id = ?`,
      ).run(id, clientId);
      logStateChange(db, id, cur.state, "proposed", userId, "reopened for re-review");
    });
    txn();
  });
}
