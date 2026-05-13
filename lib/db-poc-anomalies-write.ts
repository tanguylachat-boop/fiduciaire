// Driver SQLite WRITE pour les actions sur anomalies — Sprint 2 §3.10.
// Mutations transitionnelles open → resolved | false_positive.
// Multi-mandant strict : vérifie que l'anomalie appartient au client_id donné.

import Database from "better-sqlite3";
import path from "node:path";
import fs from "node:fs";
import { logAuditEvent } from "./audit-log-ts";

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

export class AnomalyNotFoundError extends Error {
  constructor(id: number) {
    super(`anomalie ${id} introuvable ou hors scope mandant`);
    this.name = "AnomalyNotFoundError";
  }
}

export class AnomalyAlreadyClosedError extends Error {
  constructor(id: number, currentState: string) {
    super(`anomalie ${id} déjà à l'état '${currentState}'`);
    this.name = "AnomalyAlreadyClosedError";
  }
}

function withWriteDb<T>(fn: (db: Database.Database) => T): T {
  if (!fs.existsSync(DB_PATH)) {
    throw new Error(
      `Base SQLite introuvable au chemin ${DB_PATH}. ` +
        "Lance le worker Python d'abord pour init le schéma.",
    );
  }
  const conn = new Database(DB_PATH, { fileMustExist: true });
  conn.pragma("journal_mode = WAL");
  conn.pragma("foreign_keys = ON");
  try {
    return fn(conn);
  } finally {
    conn.close();
  }
}

type AnomalyRow = { id: number; client_id: string; state: string };

function fetchAnomaly(
  db: Database.Database,
  id: number,
  clientId: string,
): AnomalyRow {
  const row = db
    .prepare(
      "SELECT id, client_id, state FROM anomalies " +
        "WHERE id = ? AND client_id = ?",
    )
    .get(id, clientId) as AnomalyRow | undefined;
  if (!row) throw new AnomalyNotFoundError(id);
  return row;
}

function transitionAnomaly(
  id: number,
  clientId: string,
  userId: string | null,
  reason: string | null,
  toState: "resolved" | "false_positive",
): void {
  withWriteDb((db) => {
    const txn = db.transaction(() => {
      const cur = fetchAnomaly(db, id, clientId);
      if (cur.state !== "open") {
        throw new AnomalyAlreadyClosedError(id, cur.state);
      }
      db.prepare(
        `UPDATE anomalies SET state=?, ` +
          `resolved_at=datetime('now'), resolved_by=?, ` +
          `resolution_reason=? WHERE id = ?`,
      ).run(toState, userId, reason, id);
      // Sprint 2 §3.10 Phase 2 (Session 9) — audit log hook avec chain hash
      logAuditEvent(db, {
        cabinetId: clientId,
        entityType: "anomaly",
        entityId: id,
        action: toState === "resolved" ? "anomaly_resolved" : "anomaly_false_positive",
        userId,
        before: { state: cur.state },
        after: { state: toState, reason: reason },
      });
    });
    txn();
  });
}

export function markAnomalyResolved(
  id: number,
  clientId: string,
  userId: string | null,
  reason: string | null,
): void {
  transitionAnomaly(id, clientId, userId, reason, "resolved");
}

export function markAnomalyFalsePositive(
  id: number,
  clientId: string,
  userId: string | null,
  reason: string | null,
): void {
  transitionAnomaly(id, clientId, userId, reason, "false_positive");
}
