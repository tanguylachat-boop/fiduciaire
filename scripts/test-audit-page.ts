// Smoke test verify chain côté lib db-poc-audit — Sprint 2 §3.10 Phase 3.
// Vérifie : chain VALID après inserts, BROKEN après tampering, isolation cabinet.

import Database from "better-sqlite3";
import path from "node:path";
import fs from "node:fs";
import os from "node:os";
import { logAuditEvent } from "../lib/audit-log-ts";

void (async () => {
const tmpDir = fs.mkdtempSync(path.join(os.tmpdir(), "fiduciaire-audit-page-"));
const tmpDbPath = path.join(tmpDir, "test.sqlite");
process.env.FIDUCIAIRE_DB_PATH = tmpDbPath;
const { verifyAuditChain, listAuditEvents } = await import(
  "../lib/db-poc-audit"
);

function initSchema(db: Database.Database) {
  db.exec(`
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

console.log("Audit page lib smoke tests\n");

check("verifyAuditChain : VALID après 5 inserts", () => {
  const db = new Database(tmpDbPath);
  initSchema(db);
  for (let i = 0; i < 5; i++) {
    logAuditEvent(db, {
      cabinetId: "cab-a", entityType: "x", entityId: i, action: "step",
    });
  }
  db.close();
  const result = verifyAuditChain("cab-a");
  if (!result.is_valid) throw new Error(`should be valid: ${result.first_invalid_reason}`);
  if (result.total_events !== 5) throw new Error(`count=${result.total_events}`);
});

check("verifyAuditChain : BROKEN après modification d'un event", () => {
  // Tampering : modifier action d'un event existant
  const db = new Database(tmpDbPath);
  db.prepare(
    "UPDATE audit_log SET action='hacked' " +
      "WHERE id=(SELECT MIN(id) FROM audit_log WHERE cabinet_id='cab-a')",
  ).run();
  db.close();
  const result = verifyAuditChain("cab-a");
  if (result.is_valid) throw new Error("should be invalid after tampering");
  if (!result.first_invalid_id) throw new Error("first_invalid_id should be set");
});

check("listAuditEvents avec filtres + pagination", () => {
  fs.unlinkSync(tmpDbPath);
  const db = new Database(tmpDbPath);
  initSchema(db);
  for (let i = 0; i < 60; i++) {
    logAuditEvent(db, {
      cabinetId: "cab-a", entityType: i % 2 === 0 ? "anomaly" : "entry",
      entityId: i, action: "step",
    });
  }
  db.close();

  // Page 1 : 50 events
  const page1 = listAuditEvents({ cabinetId: "cab-a", limit: 50, offset: 0 });
  if (page1.length !== 50) throw new Error(`page1=${page1.length}`);

  // Filter entity_type=anomaly → 30 events
  const filtered = listAuditEvents({
    cabinetId: "cab-a", entityType: "anomaly", limit: 100,
  });
  if (filtered.length !== 30) throw new Error(`filtered=${filtered.length}`);
});

check("verifyAuditChain : multi-mandant isolation", () => {
  const db = new Database(tmpDbPath);
  logAuditEvent(db, {
    cabinetId: "cab-b", entityType: "x", entityId: 1, action: "a",
  });
  // Tampering cab-a déjà fait. cab-b doit rester VALID.
  db.close();
  const resultB = verifyAuditChain("cab-b");
  if (!resultB.is_valid) {
    throw new Error(`cab-b should be valid despite cab-a tampering`);
  }
});

console.log(`\n${passed} passed / ${failed} failed`);
fs.rmSync(tmpDir, { recursive: true, force: true });
process.exit(failed === 0 ? 0 : 1);
})();
