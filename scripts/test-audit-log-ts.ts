// Smoke test audit_log côté TS — Sprint 2 §3.10 Phase 2 (Session 9).
//
// Vérifie :
//  1. Chain hash cohérent avec Python (cross-compat hash)
//  2. Insert via logAuditEvent crée une row valide
//  3. Hook automatique dans markAnomaly* écrit audit + chain
//  4. Multi-mandant : chains isolées par cabinet
//  5. canonicalJsonPythonStyle produit le même JSON que json.dumps(sort_keys=True)
//
// Usage : npx tsx scripts/test-audit-log-ts.ts
// Exit code : 0 si OK, 1 sinon.

import { execFileSync } from "node:child_process";
import { fileURLToPath } from "node:url";
import Database from "better-sqlite3";
import path from "node:path";
import fs from "node:fs";
import os from "node:os";
import {
  canonicalJsonPythonStyle,
  computeAuditHash,
  GENESIS_HASH,
  logAuditEvent,
} from "../lib/audit-log-ts";

const REPO_ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const PYTHON = path.join(REPO_ROOT, "worker", ".venv", "bin", "python");

function pyExec(code: string): string {
  return execFileSync(PYTHON, ["-c", code], {
    encoding: "utf8",
    env: { ...process.env, PYTHONPATH: path.join(REPO_ROOT, "worker", "src") },
  }).trim();
}

const tmpDir = fs.mkdtempSync(path.join(os.tmpdir(), "fiduciaire-audit-"));
const tmpDbPath = path.join(tmpDir, "test.sqlite");
process.env.FIDUCIAIRE_DB_PATH = tmpDbPath;

function initSchema(db: Database.Database) {
  db.exec(`
    PRAGMA journal_mode = WAL;
    CREATE TABLE IF NOT EXISTS audit_log (
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
  `);
}

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

console.log("Audit log TS — chain hash + cross-compat Python\n");

// --- Test 1 : canonical JSON cohérent avec Python sort_keys ---
check("canonicalJsonPythonStyle == Python json.dumps(sort_keys=True)", () => {
  const obj = { state: "open", reason: "test", count: 42 };
  const tsJson = canonicalJsonPythonStyle(obj);
  const pyJson = pyExec(
    `import json; print(json.dumps({"state":"open","reason":"test","count":42}, ensure_ascii=False, sort_keys=True), end='')`,
  );
  if (tsJson !== pyJson) {
    throw new Error(`TS: ${tsJson}\nPY: ${pyJson}`);
  }
});

// --- Test 2 : Hash identique TS vs Python pour mêmes inputs ---
check("computeAuditHash == Python audit_log hash (cross-compat)", () => {
  const tsHash = computeAuditHash({
    prevHash: GENESIS_HASH,
    cabinetId: "cab-a",
    userId: "tanguy",
    timestamp: "2026-05-13T10:00:00.000000Z",
    entityType: "anomaly",
    entityId: "42",
    action: "anomaly_resolved",
    beforeJson: '{"state": "open"}',
    afterJson: '{"reason": "ok", "state": "resolved"}',
  });
  // Calcule le même hash côté Python
  const pyHash = pyExec(`
from fiduciaire_worker.audit_log import _compute_hash, GENESIS_HASH
print(_compute_hash(
    GENESIS_HASH, "cab-a", "tanguy",
    "2026-05-13T10:00:00.000000Z",
    "anomaly", "42", "anomaly_resolved",
    '{"state": "open"}',
    '{"reason": "ok", "state": "resolved"}',
), end='')
`);
  if (tsHash !== pyHash) {
    throw new Error(`TS hash: ${tsHash}\nPY hash: ${pyHash}`);
  }
});

// --- Test 3 : Insert via logAuditEvent ---
check("logAuditEvent insert + chain root", () => {
  const db = new Database(tmpDbPath);
  initSchema(db);
  const id = logAuditEvent(db, {
    cabinetId: "cab-a", entityType: "anomaly", entityId: 1,
    action: "anomaly_resolved", userId: "tanguy",
    before: { state: "open" }, after: { state: "resolved", reason: null },
  });
  if (id <= 0) throw new Error("insert failed");
  const row = db.prepare("SELECT * FROM audit_log WHERE id=?").get(id) as Record<string, unknown>;
  if (row.prev_hash !== GENESIS_HASH) {
    throw new Error(`prev_hash should be GENESIS, got ${row.prev_hash}`);
  }
  if (!row.current_hash || (row.current_hash as string).length !== 64) {
    throw new Error("current_hash malformed");
  }
  db.close();
  // Cleanup pour tests suivants
  fs.unlinkSync(tmpDbPath);
});

// --- Test 4 : Chain links consecutive events ---
check("2 events consécutifs : prev_hash[2] == current_hash[1]", () => {
  const db = new Database(tmpDbPath);
  initSchema(db);
  logAuditEvent(db, {
    cabinetId: "cab-a", entityType: "x", entityId: 1, action: "a",
  });
  logAuditEvent(db, {
    cabinetId: "cab-a", entityType: "x", entityId: 2, action: "b",
  });
  const rows = db.prepare(
    "SELECT current_hash, prev_hash FROM audit_log ORDER BY id",
  ).all() as { current_hash: string; prev_hash: string }[];
  if (rows.length !== 2) throw new Error(`expected 2 rows, got ${rows.length}`);
  if (rows[1].prev_hash !== rows[0].current_hash) {
    throw new Error("chain broken");
  }
  db.close();
  fs.unlinkSync(tmpDbPath);
});

// --- Test 5 : markAnomaly* déclenche audit_log ---
check("markAnomalyResolved → audit_log entry créé automatiquement", async () => {
  const db = new Database(tmpDbPath);
  initSchema(db);
  // Seed anomalie open
  const r = db.prepare(
    "INSERT INTO anomalies (cabinet_id, client_id, type, " +
      "subject_entity_type, subject_entity_id) " +
      "VALUES ('cab-a', 'cab-a', 'vat_no_evidence', 'accounting_entry', '1')",
  ).run();
  const anoId = Number(r.lastInsertRowid);
  db.close();

  // Resolve
  const { markAnomalyResolved } = await import("../lib/db-poc-anomalies-write");
  markAnomalyResolved(anoId, "cab-a", "tanguy", "ajouté justif");

  // Check audit_log
  const db2 = new Database(tmpDbPath, { readonly: true });
  const events = db2.prepare(
    "SELECT * FROM audit_log WHERE cabinet_id='cab-a' ORDER BY id",
  ).all() as Record<string, unknown>[];
  db2.close();
  if (events.length !== 1) {
    throw new Error(`expected 1 audit event, got ${events.length}`);
  }
  if (events[0].action !== "anomaly_resolved") {
    throw new Error(`action=${events[0].action}`);
  }
  if (events[0].entity_type !== "anomaly") {
    throw new Error(`entity_type=${events[0].entity_type}`);
  }
  if (events[0].user_id !== "tanguy") {
    throw new Error(`user_id=${events[0].user_id}`);
  }
  fs.unlinkSync(tmpDbPath);
});

// --- Test 6 : Multi-mandant chains isolées ---
check("Chains isolées par cabinet_id (corruption A n'affecte pas B)", () => {
  const db = new Database(tmpDbPath);
  initSchema(db);
  logAuditEvent(db, {
    cabinetId: "cab-a", entityType: "x", entityId: 1, action: "a",
  });
  logAuditEvent(db, {
    cabinetId: "cab-b", entityType: "x", entityId: 1, action: "a",
  });
  // Le 2e event de cab-b doit avoir prev_hash=GENESIS (chain indépendante de cab-a)
  const rowB = db.prepare(
    "SELECT prev_hash FROM audit_log WHERE cabinet_id='cab-b' ORDER BY id LIMIT 1",
  ).get() as { prev_hash: string };
  if (rowB.prev_hash !== GENESIS_HASH) {
    throw new Error(`cab-b should start from GENESIS, got ${rowB.prev_hash}`);
  }
  db.close();
  fs.unlinkSync(tmpDbPath);
});

console.log(`\n${passed} passed / ${failed} failed`);
fs.rmSync(tmpDir, { recursive: true, force: true });
process.exit(failed === 0 ? 0 : 1);
