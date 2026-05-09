// Smoke test du write layer Sprint 0a — exécutable via tsx.
// Vérifie : isolation multi-mandant, transitions valides/invalides, audit trail.
//
// Usage : npx tsx scripts/test-db-poc-write.ts
// Exit code : 0 si tous les checks passent, 1 sinon.

import Database from "better-sqlite3";
import path from "node:path";
import fs from "node:fs";
import os from "node:os";

void (async () => {
  const tmpDir = fs.mkdtempSync(path.join(os.tmpdir(), "fiduciaire-test-"));
  const tmpDbPath = path.join(tmpDir, "test.sqlite");
  process.env.FIDUCIAIRE_DB_PATH = tmpDbPath;

  function initSchema(db: Database.Database) {
    db.exec(`
      PRAGMA journal_mode = WAL;
      CREATE TABLE IF NOT EXISTS documents (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        sha256 TEXT UNIQUE NOT NULL,
        original_filename TEXT NOT NULL,
        archive_path TEXT NOT NULL,
        ocr_text TEXT, ocr_engine TEXT, classification_json TEXT,
        type TEXT, client_slug TEXT, doc_date TEXT, montant_chf REAL,
        status TEXT NOT NULL,
        needs_review_reason TEXT, final_path TEXT,
        created_at TEXT NOT NULL DEFAULT (datetime('now')),
        updated_at TEXT NOT NULL DEFAULT (datetime('now'))
      );
      CREATE TABLE IF NOT EXISTS accounting_entries (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        client_id TEXT NOT NULL,
        source_document_id INTEGER NOT NULL REFERENCES documents(id),
        date TEXT NOT NULL,
        debit_account TEXT NOT NULL,
        credit_account TEXT NOT NULL,
        amount_chf REAL NOT NULL,
        vat_code TEXT NOT NULL,
        vat_amount REAL,
        description TEXT NOT NULL,
        confidence_account REAL NOT NULL,
        confidence_vat REAL NOT NULL,
        reasoning TEXT,
        sources_json TEXT,
        state TEXT NOT NULL DEFAULT 'proposed',
        created_at TEXT NOT NULL DEFAULT (datetime('now')),
        updated_at TEXT NOT NULL DEFAULT (datetime('now'))
      );
      CREATE TABLE IF NOT EXISTS entry_state_changes (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        entry_id INTEGER NOT NULL REFERENCES accounting_entries(id),
        from_state TEXT NOT NULL,
        to_state TEXT NOT NULL,
        user_id TEXT,
        reason TEXT,
        changed_at TEXT NOT NULL DEFAULT (datetime('now'))
      );
    `);
  }

  function seedDoc(db: Database.Database, sha: string): number {
    const r = db
      .prepare(
        "INSERT INTO documents (sha256, original_filename, archive_path, status) VALUES (?, ?, ?, 'classified')",
      )
      .run(sha, `${sha}.pdf`, `data/archive/${sha}.pdf`);
    return Number(r.lastInsertRowid);
  }

  function seedEntry(
    db: Database.Database,
    clientId: string,
    docId: number,
  ): number {
    const r = db
      .prepare(
        `INSERT INTO accounting_entries
          (client_id, source_document_id, date, debit_account, credit_account,
           amount_chf, vat_code, vat_amount, description,
           confidence_account, confidence_vat, reasoning, sources_json, state)
         VALUES (?, ?, '2026-04-01', '6510', '2000', 287.00, 'TN_NORM', 21.93,
                 'Swisscom abonnement', 0.92, 0.85, 'vendor history match',
                 '{"account":"vendor_history","vat_code":"detector"}', 'proposed')`,
      )
      .run(clientId, docId);
    return Number(r.lastInsertRowid);
  }

  const db = new Database(tmpDbPath);
  initSchema(db);
  const docA = seedDoc(db, "a".repeat(64));
  const docB = seedDoc(db, "b".repeat(64));
  const entryA1 = seedEntry(db, "cabinet-A", docA);
  const entryA2 = seedEntry(db, "cabinet-A", docA);
  const entryA3 = seedEntry(db, "cabinet-A", docA);
  const entryB1 = seedEntry(db, "cabinet-B", docB);
  db.close();

  const {
    validateEntry,
    correctEntry,
    rejectEntry,
    EntryNotFoundError,
    InvalidTransitionError,
  } = await import("../lib/db-poc-write");

  let passed = 0;
  let failed = 0;

  function check(label: string, fn: () => void) {
    try {
      fn();
      console.log(`  OK  ${label}`);
      passed++;
    } catch (err) {
      console.error(`  KO  ${label}`);
      console.error("       →", err instanceof Error ? err.message : err);
      failed++;
    }
  }

  function readEntry(id: number) {
    const conn = new Database(tmpDbPath, { readonly: true });
    try {
      return conn
        .prepare("SELECT * FROM accounting_entries WHERE id = ?")
        .get(id) as Record<string, unknown> | undefined;
    } finally {
      conn.close();
    }
  }

  function readHistory(id: number) {
    const conn = new Database(tmpDbPath, { readonly: true });
    try {
      return conn
        .prepare("SELECT * FROM entry_state_changes WHERE entry_id = ? ORDER BY id")
        .all(id) as Array<Record<string, unknown>>;
    } finally {
      conn.close();
    }
  }

  console.log(`Test DB: ${tmpDbPath}`);
  console.log("\n→ Validate entry");
  check("validate proposed entry → state=validated + log entry", () => {
    validateEntry(entryA1, "cabinet-A", "user-poc");
    const e = readEntry(entryA1);
    if (e?.state !== "validated") throw new Error(`state=${e?.state}`);
    const h = readHistory(entryA1);
    if (h.length !== 1) throw new Error(`history len=${h.length}`);
    if (h[0].from_state !== "proposed" || h[0].to_state !== "validated") {
      throw new Error(`bad transition: ${JSON.stringify(h[0])}`);
    }
  });

  console.log("\n→ Cross-tenant isolation");
  check("validate entry of cabinet-B with cabinet-A id → EntryNotFoundError", () => {
    try {
      validateEntry(entryB1, "cabinet-A", "user-poc");
      throw new Error("aurait dû throw");
    } catch (err) {
      if (!(err instanceof EntryNotFoundError)) {
        throw new Error(`wrong error type: ${err}`);
      }
    }
    const e = readEntry(entryB1);
    if (e?.state !== "proposed") throw new Error(`B leaked: state=${e?.state}`);
  });

  console.log("\n→ Correct entry");
  check("correct entry with new debit_account → state=validated + fields updated", () => {
    correctEntry(entryA2, "cabinet-A", "user-poc", {
      debit_account: "6500",
      description: "Corrigé par humain",
    });
    const e = readEntry(entryA2);
    if (e?.debit_account !== "6500") throw new Error(`debit=${e?.debit_account}`);
    if (e?.description !== "Corrigé par humain") {
      throw new Error(`description=${e?.description}`);
    }
    if (e?.state !== "validated") throw new Error(`state=${e?.state}`);
    const h = readHistory(entryA2);
    if (h.length !== 1) throw new Error(`history len=${h.length}`);
    if (!String(h[0].reason).startsWith("corrected:")) {
      throw new Error(`reason=${h[0].reason}`);
    }
  });

  console.log("\n→ Reject entry");
  check("reject entry with reason → state=rejected + reason logged", () => {
    rejectEntry(entryA3, "cabinet-A", "user-poc", "Hors périmètre");
    const e = readEntry(entryA3);
    if (e?.state !== "rejected") throw new Error(`state=${e?.state}`);
    const h = readHistory(entryA3);
    if (h.length !== 1) throw new Error(`history len=${h.length}`);
    if (h[0].reason !== "Hors périmètre") throw new Error(`reason=${h[0].reason}`);
  });

  check("reject without reason → throws", () => {
    const conn = new Database(tmpDbPath);
    const r = conn
      .prepare(
        `INSERT INTO accounting_entries
          (client_id, source_document_id, date, debit_account, credit_account,
           amount_chf, vat_code, vat_amount, description,
           confidence_account, confidence_vat, reasoning, sources_json, state)
         VALUES ('cabinet-A', ?, '2026-04-01', '6510', '2000', 100, 'TN_NORM', 7.6,
                 'x', 0.5, 0.5, '', '{}', 'proposed')`,
      )
      .run(docA);
    conn.close();
    const id = Number(r.lastInsertRowid);
    try {
      rejectEntry(id, "cabinet-A", "user-poc", "  ");
      throw new Error("aurait dû throw");
    } catch (err) {
      if (
        !(err instanceof Error) ||
        !err.message.toLowerCase().includes("reason")
      ) {
        throw new Error(`wrong error: ${err}`);
      }
    }
  });

  console.log("\n→ Double validate blocked");
  check("re-validate already validated entry → InvalidTransitionError", () => {
    try {
      validateEntry(entryA1, "cabinet-A", "user-poc");
      throw new Error("aurait dû throw");
    } catch (err) {
      if (!(err instanceof InvalidTransitionError)) {
        throw new Error(`wrong type: ${err}`);
      }
    }
  });

  console.log("\n→ Validate rejected entry blocked");
  check("validate rejected entry → InvalidTransitionError (terminal)", () => {
    try {
      validateEntry(entryA3, "cabinet-A", "user-poc");
      throw new Error("aurait dû throw");
    } catch (err) {
      if (!(err instanceof InvalidTransitionError)) {
        throw new Error(`wrong type: ${err}`);
      }
    }
  });

  console.log(`\n${passed} passed / ${failed} failed`);
  fs.rmSync(tmpDir, { recursive: true, force: true });
  process.exit(failed === 0 ? 0 : 1);
})();
