// Lectures SQLite pour le dashboard /reminders.
// Multi-mandant : chaque query filtre cabinet_id.

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

export interface ReminderRow {
  id: number;
  cabinet_id: string;
  client_id: string;
  anomaly_id: number;
  level: "polite" | "firm" | "escalation";
  contact_name: string | null;
  contact_email: string | null;
  needs_contact_info: number;
  subject: string;
  body_draft: string;
  body_final: string | null;
  status: "pending" | "approved" | "sent" | "skipped" | "failed";
  skip_reason: string | null;
  sent_at: string | null;
  error_message: string | null;
  created_at: string;
}

export interface ReminderStats {
  pending: number;
  approved: number;
  sent: number;
  skipped: number;
  failed: number;
  needs_contact: number;
}

function tableExists(db: Database.Database): boolean {
  const row = db
    .prepare(
      "SELECT name FROM sqlite_master WHERE type='table' AND name='reminders'"
    )
    .get();
  return !!row;
}

export function listReminders(
  cabinetId: string,
  opts: {
    clientId?: string;
    status?: string;
    limit?: number;
  } = {}
): ReminderRow[] {
  return withDb((db) => {
    if (!tableExists(db)) return [];
    let sql =
      "SELECT * FROM reminders WHERE cabinet_id = ?";
    const params: (string | number)[] = [cabinetId];
    if (opts.clientId) {
      sql += " AND client_id = ?";
      params.push(opts.clientId);
    }
    if (opts.status) {
      sql += " AND status = ?";
      params.push(opts.status);
    }
    sql += " ORDER BY created_at DESC LIMIT ?";
    params.push(opts.limit ?? 200);
    return db.prepare(sql).all(...params) as ReminderRow[];
  });
}

export function getReminderStats(cabinetId: string): ReminderStats {
  return withDb((db) => {
    if (!tableExists(db)) {
      return { pending: 0, approved: 0, sent: 0, skipped: 0, failed: 0, needs_contact: 0 };
    }
    const rows = db
      .prepare(
        `SELECT status, COUNT(*) as cnt
         FROM reminders
         WHERE cabinet_id = ?
         GROUP BY status`
      )
      .all(cabinetId) as { status: string; cnt: number }[];

    const stats: ReminderStats = {
      pending: 0,
      approved: 0,
      sent: 0,
      skipped: 0,
      failed: 0,
      needs_contact: 0,
    };
    for (const r of rows) {
      const k = r.status as keyof ReminderStats;
      if (k in stats) stats[k] = r.cnt;
    }

    const ncRow = db
      .prepare(
        `SELECT COUNT(*) as cnt FROM reminders
         WHERE cabinet_id = ? AND needs_contact_info = 1 AND status = 'pending'`
      )
      .get(cabinetId) as { cnt: number };
    stats.needs_contact = ncRow.cnt;

    return stats;
  });
}

export function listReminderCabinets(): { cabinet_id: string }[] {
  return withDb((db) => {
    if (!tableExists(db)) return [];
    return db
      .prepare(
        "SELECT DISTINCT cabinet_id FROM reminders ORDER BY cabinet_id"
      )
      .all() as { cabinet_id: string }[];
  });
}

export function getReminderById(id: number): ReminderRow | null {
  return withDb((db) => {
    if (!tableExists(db)) return null;
    return (
      (db.prepare("SELECT * FROM reminders WHERE id = ?").get(id) as ReminderRow) ??
      null
    );
  });
}
