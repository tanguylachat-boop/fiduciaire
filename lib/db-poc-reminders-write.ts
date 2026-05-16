// Driver SQLite WRITE pour le dashboard /reminders.
// Mutations : approve, skip, edit body_final.

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

export class ReminderNotFoundError extends Error {
  constructor(id: number) {
    super(`Relance ${id} introuvable`);
    this.name = "ReminderNotFoundError";
  }
}

export class ReminderStateError extends Error {
  constructor(msg: string) {
    super(msg);
    this.name = "ReminderStateError";
  }
}

function withWriteDb<T>(fn: (db: Database.Database) => T): T {
  if (!fs.existsSync(DB_PATH)) {
    throw new Error(
      `Base SQLite introuvable : ${DB_PATH}. Lance le worker Python d'abord.`
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

function assertReminder(
  db: Database.Database,
  id: number,
  cabinetId: string
): { status: string } {
  const row = db
    .prepare("SELECT status FROM reminders WHERE id = ? AND cabinet_id = ?")
    .get(id, cabinetId) as { status: string } | undefined;
  if (!row) throw new ReminderNotFoundError(id);
  return row;
}

export function approveReminder(id: number, cabinetId: string): void {
  withWriteDb((db) => {
    const row = assertReminder(db, id, cabinetId);
    if (row.status !== "pending") {
      throw new ReminderStateError(
        `Relance ${id} ne peut être approuvée (status=${row.status})`
      );
    }
    db.prepare(
      "UPDATE reminders SET status = 'approved' WHERE id = ?"
    ).run(id);
  });
}

export function skipReminder(
  id: number,
  cabinetId: string,
  skipReason: string
): void {
  withWriteDb((db) => {
    const row = assertReminder(db, id, cabinetId);
    if (!["pending", "approved"].includes(row.status)) {
      throw new ReminderStateError(
        `Relance ${id} ne peut être ignorée (status=${row.status})`
      );
    }
    db.prepare(
      "UPDATE reminders SET status = 'skipped', skip_reason = ? WHERE id = ?"
    ).run(skipReason || "Ignorée manuellement", id);
  });
}

export function editReminderDraft(
  id: number,
  cabinetId: string,
  bodyFinal: string
): void {
  withWriteDb((db) => {
    const row = assertReminder(db, id, cabinetId);
    if (!["pending", "approved"].includes(row.status)) {
      throw new ReminderStateError(
        `Relance ${id} ne peut être modifiée (status=${row.status})`
      );
    }
    db.prepare(
      "UPDATE reminders SET body_final = ?, status = 'approved' WHERE id = ?"
    ).run(bodyFinal, id);
  });
}
