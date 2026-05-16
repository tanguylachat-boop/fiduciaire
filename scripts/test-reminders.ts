// Smoke tests /reminders — Sprint 2 §reminder (Session 13bis).
// Couvre : lecture reminders DB, stats, write approve/skip/edit,
//          cross-mandant isolation, reminder-write error handling.
//
// Usage : npx tsx scripts/test-reminders.ts
// Exit code : 0 si tous les checks passent, 1 sinon.

import Database from "better-sqlite3";
import path from "node:path";
import fs from "node:fs";
import os from "node:os";

void (async () => {
  const tmpDir = fs.mkdtempSync(path.join(os.tmpdir(), "fiduciaire-reminders-"));
  const tmpDbPath = path.join(tmpDir, "test.sqlite");
  process.env.FIDUCIAIRE_DB_PATH = tmpDbPath;
  process.env.FIDUCIAIRE_ENCRYPTION_DISABLED = "true";

  // ── Schema bootstrap ────────────────────────────────────────────────────────
  function initSchema(db: Database.Database) {
    db.exec(`
      PRAGMA journal_mode = WAL;
      CREATE TABLE IF NOT EXISTS anomalies (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        cabinet_id TEXT NOT NULL,
        client_id TEXT NOT NULL,
        type TEXT NOT NULL,
        severity TEXT NOT NULL DEFAULT 'warning',
        state TEXT NOT NULL DEFAULT 'open',
        subject_entity_type TEXT NOT NULL,
        subject_entity_id TEXT NOT NULL,
        details_json TEXT,
        detected_at TEXT NOT NULL DEFAULT (datetime('now')),
        resolved_at TEXT,
        resolved_by TEXT,
        resolution_reason TEXT,
        UNIQUE (cabinet_id, client_id, type, subject_entity_id)
      );
      CREATE TABLE IF NOT EXISTS reminders (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        cabinet_id TEXT NOT NULL,
        client_id TEXT NOT NULL,
        anomaly_id INTEGER NOT NULL,
        level TEXT NOT NULL CHECK(level IN ('polite', 'firm', 'escalation')),
        contact_name TEXT,
        contact_email TEXT,
        needs_contact_info INTEGER NOT NULL DEFAULT 0,
        subject TEXT NOT NULL,
        body_draft TEXT NOT NULL,
        body_final TEXT,
        status TEXT NOT NULL DEFAULT 'pending'
          CHECK(status IN ('pending', 'approved', 'sent', 'skipped', 'failed')),
        skip_reason TEXT,
        sent_at TEXT,
        error_message TEXT,
        created_at TEXT NOT NULL DEFAULT (datetime('now'))
      );
      CREATE TABLE IF NOT EXISTS audit_log (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        cabinet_id TEXT NOT NULL,
        user_id TEXT,
        timestamp TEXT NOT NULL DEFAULT (datetime('now')),
        entity_type TEXT NOT NULL,
        entity_id TEXT NOT NULL,
        action TEXT NOT NULL,
        before_json TEXT,
        after_json TEXT,
        prev_hash TEXT NOT NULL DEFAULT '',
        current_hash TEXT NOT NULL DEFAULT ''
      );
    `);
  }

  function insertAnomaly(db: Database.Database, cabinetId: string, clientId: string, entityId = "entry-1") {
    const r = db.prepare(`
      INSERT OR IGNORE INTO anomalies
        (cabinet_id, client_id, type, state, subject_entity_type, subject_entity_id, details_json)
      VALUES (?, ?, 'vat_no_evidence', 'open', 'accounting_entry', ?, '{}')
    `).run(cabinetId, clientId, entityId);
    return r.lastInsertRowid as number;
  }

  function insertReminder(
    db: Database.Database,
    cabinetId: string,
    clientId: string,
    anomalyId: number,
    opts: { status?: string; level?: string; email?: string } = {}
  ) {
    const r = db.prepare(`
      INSERT INTO reminders
        (cabinet_id, client_id, anomaly_id, level, contact_email,
         subject, body_draft, status)
      VALUES (?, ?, ?, ?, ?, 'Objet test', 'Corps test', ?)
    `).run(
      cabinetId, clientId, anomalyId,
      opts.level ?? "polite",
      opts.email ?? "client@example.ch",
      opts.status ?? "pending"
    );
    return r.lastInsertRowid as number;
  }

  // ── Re-import modules with fresh DB path ────────────────────────────────────
  const { listReminders, getReminderStats, getReminderById } = await import(
    "../lib/db-poc-reminders"
  );
  const {
    approveReminder,
    skipReminder,
    editReminderDraft,
    ReminderNotFoundError,
    ReminderStateError,
  } = await import("../lib/db-poc-reminders-write");

  // ── Setup DB ────────────────────────────────────────────────────────────────
  const db = new Database(tmpDbPath);
  initSchema(db);

  const anomId1 = insertAnomaly(db, "cab-01", "client-A");
  const anomId2 = insertAnomaly(db, "cab-01", "client-A", "entry-2");
  const anomId3 = insertAnomaly(db, "cab-02", "client-B"); // other cabinet

  const rid1 = insertReminder(db, "cab-01", "client-A", anomId1);
  const rid2 = insertReminder(db, "cab-01", "client-A", anomId2, { status: "sent" });
  const rid3 = insertReminder(db, "cab-02", "client-B", anomId3);
  db.close();

  // ── Tests ────────────────────────────────────────────────────────────────────
  const results: { name: string; ok: boolean; error?: string }[] = [];

  function check(name: string, fn: () => void) {
    try {
      fn();
      results.push({ name, ok: true });
    } catch (e) {
      results.push({ name, ok: false, error: e instanceof Error ? e.message : String(e) });
    }
  }

  // 1. listReminders returns only cab-01
  check("listReminders — filtre cabinet_id strict", () => {
    const rows = listReminders("cab-01");
    if (rows.length !== 2) throw new Error(`attendu 2, got ${rows.length}`);
    if (rows.some((r) => r.cabinet_id !== "cab-01")) throw new Error("fuite cross-mandant");
  });

  // 2. getReminderStats
  check("getReminderStats — pending+sent comptés", () => {
    const stats = getReminderStats("cab-01");
    if (stats.pending !== 1) throw new Error(`pending attendu 1, got ${stats.pending}`);
    if (stats.sent !== 1) throw new Error(`sent attendu 1, got ${stats.sent}`);
  });

  // 3. getReminderById returns correct row
  check("getReminderById — lecture par id", () => {
    const row = getReminderById(rid1);
    if (!row) throw new Error("row null");
    if (row.cabinet_id !== "cab-01") throw new Error("cabinet_id incorrect");
    if (row.status !== "pending") throw new Error(`status attendu pending, got ${row.status}`);
  });

  // 4. approveReminder — pending → approved
  check("approveReminder — pending → approved", () => {
    approveReminder(rid1, "cab-01");
    const row = getReminderById(rid1);
    if (row?.status !== "approved") throw new Error(`status attendu approved, got ${row?.status}`);
  });

  // 5. approveReminder cross-cabinet → ReminderNotFoundError
  check("approveReminder cross-cabinet → NotFound", () => {
    try {
      approveReminder(rid3, "cab-01"); // rid3 appartient à cab-02
      throw new Error("aurait dû lever");
    } catch (e) {
      if (!(e instanceof ReminderNotFoundError)) throw new Error(`mauvais type: ${e}`);
    }
  });

  // 6. skipReminder — approved → skipped avec raison
  check("skipReminder — approved → skipped", () => {
    skipReminder(rid1, "cab-01", "Client hors périmètre");
    const row = getReminderById(rid1);
    if (row?.status !== "skipped") throw new Error(`attendu skipped, got ${row?.status}`);
    if (!row?.skip_reason?.includes("périmètre")) throw new Error("skip_reason manquant");
  });

  // 7. editReminderDraft — met à jour body_final + approuve
  check("editReminderDraft — body_final + approved", () => {
    // Re-insert a fresh pending reminder
    const db2 = new Database(tmpDbPath);
    const aId = db2.prepare(`
      INSERT INTO anomalies (cabinet_id, client_id, type, state, subject_entity_type, subject_entity_id, details_json)
      VALUES ('cab-01', 'client-A', 'vat_no_evidence', 'open', 'accounting_entry', 'entry-edit', '{}')
    `).run().lastInsertRowid as number;
    const rid = db2.prepare(`
      INSERT INTO reminders (cabinet_id, client_id, anomaly_id, level, subject, body_draft, status)
      VALUES ('cab-01', 'client-A', ?, 'polite', 'Objet', 'Brouillon original', 'pending')
    `).run(aId).lastInsertRowid as number;
    db2.close();

    editReminderDraft(rid, "cab-01", "Corps personnalisé par le cabinet");
    const row = getReminderById(rid);
    if (row?.body_final !== "Corps personnalisé par le cabinet") throw new Error("body_final non mis à jour");
    if (row?.status !== "approved") throw new Error(`status attendu approved, got ${row?.status}`);
  });

  // 8. ReminderStateError sur approve d'une relance sent
  check("approveReminder sent → ReminderStateError", () => {
    try {
      approveReminder(rid2, "cab-01"); // rid2 est status=sent
      throw new Error("aurait dû lever");
    } catch (e) {
      if (!(e instanceof ReminderStateError)) throw new Error(`mauvais type: ${e}`);
    }
  });

  // ── Report ──────────────────────────────────────────────────────────────────
  const passed = results.filter((r) => r.ok).length;
  const failed = results.filter((r) => !r.ok).length;

  for (const r of results) {
    console.log(`${r.ok ? "✅" : "❌"} ${r.name}${r.error ? ` — ${r.error}` : ""}`);
  }
  console.log(`\n${passed}/${results.length} passed`);

  // Cleanup
  fs.rmSync(tmpDir, { recursive: true, force: true });

  if (failed > 0) process.exit(1);
})();
