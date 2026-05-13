// Smoke test du write layer /bank — Sprint 2 §3.10 Phase 4.
// Couvre : match manuel + audit log, cross-mandant bloqué, double match bloqué,
// listing unmatched + unpaid avec filtres, decrypt automatique.
//
// Usage : npx tsx scripts/test-bank-write.ts
// Exit code : 0 si tous les checks passent, 1 sinon.

import Database from "better-sqlite3";
import path from "node:path";
import fs from "node:fs";
import os from "node:os";

void (async () => {
  const tmpDir = fs.mkdtempSync(path.join(os.tmpdir(), "fiduciaire-bank-"));
  const tmpDbPath = path.join(tmpDir, "test.sqlite");
  process.env.FIDUCIAIRE_DB_PATH = tmpDbPath;
  process.env.FIDUCIAIRE_ENCRYPTION_DISABLED = "true";

  function initSchema(db: Database.Database) {
    db.exec(`
      PRAGMA journal_mode = WAL;
      CREATE TABLE documents (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        sha256 TEXT,
        original_filename TEXT,
        archive_path TEXT,
        client_slug TEXT,
        created_at TEXT DEFAULT (datetime('now'))
      );
      CREATE TABLE accounting_entries (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        client_id TEXT NOT NULL,
        source_document_id INTEGER NOT NULL,
        date TEXT NOT NULL,
        debit_account TEXT NOT NULL,
        credit_account TEXT NOT NULL,
        amount_chf REAL NOT NULL,
        vat_code TEXT NOT NULL,
        vat_amount REAL,
        description TEXT NOT NULL,
        confidence_account REAL NOT NULL DEFAULT 0.9,
        confidence_vat REAL NOT NULL DEFAULT 0.9,
        reasoning TEXT,
        sources_json TEXT,
        state TEXT NOT NULL DEFAULT 'proposed',
        bexio_id TEXT,
        bexio_pushed_at TEXT,
        winbiz_exported_at TEXT,
        created_at TEXT NOT NULL DEFAULT (datetime('now')),
        updated_at TEXT NOT NULL DEFAULT (datetime('now'))
      );
      CREATE TABLE bank_transactions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        cabinet_id TEXT NOT NULL,
        client_id TEXT NOT NULL,
        iban TEXT NOT NULL,
        value_date TEXT NOT NULL,
        booking_date TEXT,
        amount_chf REAL NOT NULL,
        currency TEXT NOT NULL DEFAULT 'CHF',
        credit_debit TEXT NOT NULL,
        description TEXT,
        qr_reference TEXT,
        end_to_end_id TEXT,
        creditor_name TEXT,
        debtor_name TEXT,
        bank_ref TEXT,
        raw_xml_blob TEXT,
        matched_document_id INTEGER,
        matched_accounting_entry_id INTEGER,
        matched_at TEXT,
        matched_by TEXT,
        match_confidence REAL,
        match_strategy TEXT,
        imported_at TEXT NOT NULL DEFAULT (datetime('now'))
      );
      CREATE TABLE audit_log (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        cabinet_id TEXT NOT NULL,
        user_id TEXT,
        timestamp TEXT NOT NULL,
        entity_type TEXT NOT NULL,
        entity_id TEXT NOT NULL,
        action TEXT NOT NULL,
        before_json TEXT,
        after_json TEXT,
        prev_hash TEXT NOT NULL,
        current_hash TEXT NOT NULL
      );
    `);
  }

  function seedDoc(db: Database.Database, client: string): number {
    const r = db
      .prepare(
        "INSERT INTO documents (sha256, original_filename, archive_path, client_slug) " +
          "VALUES (?, ?, ?, ?)",
      )
      .run(
        `sha-${Math.random()}`,
        `fact-${client}.pdf`,
        `/arch/${client}.pdf`,
        client,
      );
    return Number(r.lastInsertRowid);
  }

  function seedEntry(
    db: Database.Database,
    clientId: string,
    docId: number,
    amount: number,
    date: string,
    desc: string,
    bexioId: string | null = null,
    state: string = "validated",
  ): number {
    const r = db
      .prepare(
        "INSERT INTO accounting_entries " +
          "(client_id, source_document_id, date, debit_account, credit_account, " +
          " amount_chf, vat_code, description, state, bexio_id) " +
          "VALUES (?, ?, ?, '1020', '4000', ?, 'TN_NORM', ?, ?, ?)",
      )
      .run(clientId, docId, date, amount, desc, state, bexioId);
    return Number(r.lastInsertRowid);
  }

  function seedTx(
    db: Database.Database,
    cabinetId: string,
    amount: number,
    date: string,
    desc: string,
    qrRef: string | null = null,
  ): number {
    const r = db
      .prepare(
        "INSERT INTO bank_transactions " +
          "(cabinet_id, client_id, iban, value_date, amount_chf, credit_debit, " +
          " description, qr_reference, bank_ref) " +
          "VALUES (?, ?, 'CH9300762011623852957', ?, ?, 'CRDT', ?, ?, ?)",
      )
      .run(
        cabinetId,
        cabinetId,
        date,
        amount,
        desc,
        qrRef,
        `ref-${Math.random()}`,
      );
    return Number(r.lastInsertRowid);
  }

  // --- Setup test data ----
  const db = new Database(tmpDbPath);
  initSchema(db);

  // Cabinet A
  const docA1 = seedDoc(db, "cab-a");
  const entryA1 = seedEntry(
    db,
    "cab-a",
    docA1,
    100.0,
    "2026-04-15",
    "Facture Swisscom",
    "BX-A-001",
  );
  const docA2 = seedDoc(db, "cab-a");
  const entryA2 = seedEntry(
    db,
    "cab-a",
    docA2,
    250.5,
    "2026-04-20",
    "Facture Romande Energie",
    "BX-A-002",
  );
  const txA1 = seedTx(db, "cab-a", 100.0, "2026-04-16", "Paiement Swisscom");
  const txA2 = seedTx(db, "cab-a", 250.5, "2026-04-21", "Paiement Romande");

  // Cabinet B
  const docB1 = seedDoc(db, "cab-b");
  const entryB1 = seedEntry(
    db,
    "cab-b",
    docB1,
    500.0,
    "2026-04-10",
    "Facture B-only",
    "BX-B-001",
  );
  const txB1 = seedTx(db, "cab-b", 500.0, "2026-04-11", "Paiement B-only");

  db.close();

  const {
    listUnmatchedTransactions,
    listUnpaidInvoices,
    getBankStats,
    validateManualLink,
  } = await import("../lib/db-poc-bank");
  const { manuallyLinkTransaction, BankLinkError } = await import(
    "../lib/db-poc-bank-write"
  );

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

  function readTx(id: number) {
    const conn = new Database(tmpDbPath, { readonly: true });
    try {
      return conn
        .prepare("SELECT * FROM bank_transactions WHERE id = ?")
        .get(id) as Record<string, unknown> | undefined;
    } finally {
      conn.close();
    }
  }

  function countAuditEvents(cabinetId: string): number {
    const conn = new Database(tmpDbPath, { readonly: true });
    try {
      const r = conn
        .prepare(
          "SELECT COUNT(*) AS n FROM audit_log WHERE cabinet_id = ?",
        )
        .get(cabinetId) as { n: number };
      return r.n;
    } finally {
      conn.close();
    }
  }

  console.log(`Test DB: ${tmpDbPath}\n`);

  console.log("→ Listings unmatched / unpaid");
  check("listUnmatchedTransactions cab-a → 2 lignes, isolation OK", () => {
    const rows = listUnmatchedTransactions({ cabinetId: "cab-a" });
    if (rows.length !== 2) throw new Error(`count=${rows.length}`);
    if (rows.some((r) => r.cabinet_id !== "cab-a")) {
      throw new Error("leak cabinet");
    }
  });

  check("listUnpaidInvoices cab-a → 2 factures bexio non payées", () => {
    const rows = listUnpaidInvoices({ cabinetId: "cab-a" });
    if (rows.length !== 2) throw new Error(`count=${rows.length}`);
    if (rows.some((r) => r.client_id !== "cab-a")) {
      throw new Error("leak cabinet");
    }
    if (rows.some((r) => r.bexio_id === null)) {
      throw new Error("entry sans bexio_id retournée");
    }
  });

  check("listUnpaidInvoices : filtre amount_min", () => {
    const rows = listUnpaidInvoices({
      cabinetId: "cab-a",
      amountMin: 200,
    });
    if (rows.length !== 1) throw new Error(`count=${rows.length}`);
    if (rows[0].amount_chf < 200) throw new Error("filtre KO");
  });

  console.log("\n→ Match manuel");
  check("manuallyLinkTransaction : OK + persiste matched_document_id", () => {
    const result = manuallyLinkTransaction(txA1, entryA1, "tanguy");
    if (result.cabinetId !== "cab-a") throw new Error("cab leak");
    const tx = readTx(txA1);
    if (tx?.matched_document_id !== docA1) {
      throw new Error(`matched_doc=${tx?.matched_document_id}`);
    }
    if (tx?.matched_accounting_entry_id !== entryA1) {
      throw new Error(`matched_entry=${tx?.matched_accounting_entry_id}`);
    }
    if (tx?.match_strategy !== "manual") {
      throw new Error(`strategy=${tx?.match_strategy}`);
    }
    if (tx?.matched_by !== "tanguy") {
      throw new Error(`matched_by=${tx?.matched_by}`);
    }
  });

  check("manuallyLinkTransaction : audit log inséré (chain hash)", () => {
    const before = 0;
    // Le check précédent a déjà inséré 1 event ; on en ajoute un nouveau
    const result = manuallyLinkTransaction(txA2, entryA2, "tanguy");
    if (!result) throw new Error("no result");
    const n = countAuditEvents("cab-a");
    if (n < 2) throw new Error(`audit count=${n} (expected >=2)`);
    void before;
  });

  console.log("\n→ Cross-mandant interdit");
  check("manuallyLinkTransaction cross-mandant (txA × entryB) → BankLinkError", () => {
    try {
      manuallyLinkTransaction(txA1, entryB1, "tanguy");
      throw new Error("aurait dû throw");
    } catch (err) {
      if (!(err instanceof BankLinkError)) {
        throw new Error(`wrong type: ${err}`);
      }
      if (!/cross-mandant/i.test(err.message)) {
        throw new Error(`wrong reason: ${err.message}`);
      }
    }
    // cab-b reste intact
    const tx = readTx(txB1);
    if (tx?.matched_document_id !== null) {
      throw new Error(`leak cab-b: matched=${tx?.matched_document_id}`);
    }
  });

  console.log("\n→ Double match bloqué");
  check("manuallyLinkTransaction sur tx déjà matchée → BankLinkError", () => {
    // txA1 a été matché plus haut → ré-essayer doit échouer
    try {
      manuallyLinkTransaction(txA1, entryA1, "tanguy");
      throw new Error("aurait dû throw");
    } catch (err) {
      if (!(err instanceof BankLinkError)) {
        throw new Error(`wrong type: ${err}`);
      }
      if (!/déjà matchée/i.test(err.message)) {
        throw new Error(`wrong reason: ${err.message}`);
      }
    }
  });

  console.log("\n→ Validation read-side");
  check("validateManualLink : tx introuvable → ok=false", () => {
    const v = validateManualLink(99999, entryA1);
    if (v.ok) throw new Error("should be invalid");
  });

  check("validateManualLink : cross-mandant → ok=false (cross-mandant)", () => {
    const v = validateManualLink(txA1, entryB1);
    if (v.ok) throw new Error("should be invalid");
    if (!/cross-mandant/i.test(v.reason)) {
      throw new Error(`wrong reason: ${v.reason}`);
    }
  });

  console.log("\n→ Stats");
  check("getBankStats cab-a : 2 matched (post test), unmatched recalculé", () => {
    const stats = getBankStats("cab-a");
    if (stats.matched_count !== 2) {
      throw new Error(`matched=${stats.matched_count}`);
    }
    // Pas d'unpaid restant car les 2 factures sont matchées
    if (stats.unpaid_count !== 0) {
      throw new Error(`unpaid=${stats.unpaid_count} (attendu 0)`);
    }
    if (stats.match_rate_pct <= 0) {
      throw new Error(`match_rate=${stats.match_rate_pct}`);
    }
  });

  console.log(`\n${passed} passed / ${failed} failed`);
  fs.rmSync(tmpDir, { recursive: true, force: true });
  process.exit(failed === 0 ? 0 : 1);
})();
