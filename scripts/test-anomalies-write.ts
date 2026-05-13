// Smoke test du write layer Sprint 2 §3.10 — exécutable via tsx.
// Vérifie : isolation multi-mandant, transitions valides/invalides,
// resolved et false_positive workflow.
//
// Usage : npx tsx scripts/test-anomalies-write.ts
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
      CREATE TABLE anomalies (
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

  function seedAnomaly(
    db: Database.Database,
    clientId: string,
    type: string = "vat_no_evidence",
    subjectId: string = "1",
  ): number {
    const r = db
      .prepare(
        "INSERT INTO anomalies (cabinet_id, client_id, type, " +
          "subject_entity_type, subject_entity_id) " +
          "VALUES (?, ?, ?, 'accounting_entry', ?)",
      )
      .run(clientId, clientId, type, subjectId);
    return Number(r.lastInsertRowid);
  }

  const db = new Database(tmpDbPath);
  initSchema(db);
  const anoA1 = seedAnomaly(db, "cabinet-A", "vat_no_evidence", "1");
  const anoA2 = seedAnomaly(db, "cabinet-A", "potential_duplicate", "2");
  const anoB1 = seedAnomaly(db, "cabinet-B", "vat_no_evidence", "1");
  db.close();

  const {
    markAnomalyResolved,
    markAnomalyFalsePositive,
    AnomalyNotFoundError,
    AnomalyAlreadyClosedError,
  } = await import("../lib/db-poc-anomalies-write");

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

  function readAnomaly(id: number) {
    const conn = new Database(tmpDbPath, { readonly: true });
    try {
      return conn
        .prepare("SELECT * FROM anomalies WHERE id = ?")
        .get(id) as Record<string, unknown> | undefined;
    } finally {
      conn.close();
    }
  }

  console.log(`Test DB: ${tmpDbPath}`);

  console.log("\n→ Mark resolved");
  check("mark open anomaly resolved → state=resolved + resolved_by", () => {
    markAnomalyResolved(anoA1, "cabinet-A", "tanguy", "ajouté justif");
    const a = readAnomaly(anoA1);
    if (a?.state !== "resolved") throw new Error(`state=${a?.state}`);
    if (a?.resolved_by !== "tanguy")
      throw new Error(`resolved_by=${a?.resolved_by}`);
    if (a?.resolution_reason !== "ajouté justif")
      throw new Error(`reason=${a?.resolution_reason}`);
    if (!a?.resolved_at) throw new Error("resolved_at missing");
  });

  console.log("\n→ Mark false positive");
  check("mark open anomaly false_positive → state=false_positive", () => {
    markAnomalyFalsePositive(anoA2, "cabinet-A", "tanguy", "règle trop stricte");
    const a = readAnomaly(anoA2);
    if (a?.state !== "false_positive") throw new Error(`state=${a?.state}`);
  });

  console.log("\n→ Cross-tenant isolation");
  check("resolve anomaly of cabinet-B with cabinet-A id → AnomalyNotFoundError",
    () => {
      try {
        markAnomalyResolved(anoB1, "cabinet-A", "tanguy", null);
        throw new Error("aurait dû throw");
      } catch (err) {
        if (!(err instanceof AnomalyNotFoundError)) {
          throw new Error(`wrong error type: ${err}`);
        }
      }
      // anoB1 intact
      const a = readAnomaly(anoB1);
      if (a?.state !== "open") throw new Error(`B leaked: state=${a?.state}`);
    });

  console.log("\n→ Double resolve blocked");
  check("re-resolve already resolved → AnomalyAlreadyClosedError", () => {
    try {
      markAnomalyResolved(anoA1, "cabinet-A", "tanguy", null);
      throw new Error("aurait dû throw");
    } catch (err) {
      if (!(err instanceof AnomalyAlreadyClosedError)) {
        throw new Error(`wrong type: ${err}`);
      }
    }
  });

  console.log("\n→ Resolve unknown anomaly");
  check("resolve unknown id → AnomalyNotFoundError", () => {
    try {
      markAnomalyResolved(99999, "cabinet-A", "tanguy", null);
      throw new Error("aurait dû throw");
    } catch (err) {
      if (!(err instanceof AnomalyNotFoundError)) {
        throw new Error(`wrong type: ${err}`);
      }
    }
  });

  console.log(`\n${passed} passed / ${failed} failed`);
  fs.rmSync(tmpDir, { recursive: true, force: true });
  process.exit(failed === 0 ? 0 : 1);
})();
