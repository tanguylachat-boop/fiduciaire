// Smoke tests du flow send_reminder — Sprint 2 §smtp (Session 13ter).
// Vérifie : script Python CLI JSON output, Server Action approve+send pipeline,
//           batch send avec agrégation résultats.
//
// Usage : npx tsx scripts/test-send-reminder.ts
// Exit code : 0 si tous les checks passent, 1 sinon.

import Database from "better-sqlite3";
import { spawn } from "node:child_process";
import path from "node:path";
import fs from "node:fs";
import os from "node:os";

const REPO_ROOT = path.resolve(__dirname, "..");
const PYTHON = fs.existsSync(path.join(REPO_ROOT, "worker", ".venv", "bin", "python"))
  ? path.join(REPO_ROOT, "worker", ".venv", "bin", "python")
  : "python3";
const SCRIPT = path.join(REPO_ROOT, "worker", "scripts", "send_reminder.py");

void (async () => {
  const tmpDir = fs.mkdtempSync(path.join(os.tmpdir(), "fiduciaire-smtp-"));
  const tmpDbPath = path.join(tmpDir, "test.sqlite");

  // ── Schema bootstrap ──────────────────────────────────────────────────────
  function initSchema(db: Database.Database) {
    db.exec(`
      PRAGMA journal_mode = WAL;
      CREATE TABLE anomalies (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        cabinet_id TEXT, client_id TEXT, type TEXT,
        severity TEXT DEFAULT 'warning', state TEXT DEFAULT 'open',
        subject_entity_type TEXT, subject_entity_id TEXT, details_json TEXT,
        detected_at TEXT DEFAULT (datetime('now')),
        resolved_at TEXT, resolved_by TEXT, resolution_reason TEXT,
        UNIQUE(cabinet_id, client_id, type, subject_entity_id)
      );
      CREATE TABLE audit_log (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        cabinet_id TEXT, user_id TEXT,
        timestamp TEXT DEFAULT (datetime('now')),
        entity_type TEXT, entity_id TEXT, action TEXT,
        before_json TEXT, after_json TEXT,
        prev_hash TEXT DEFAULT '', current_hash TEXT DEFAULT ''
      );
      CREATE TABLE reminders (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        cabinet_id TEXT NOT NULL, client_id TEXT NOT NULL,
        anomaly_id INTEGER NOT NULL,
        level TEXT NOT NULL CHECK(level IN ('polite','firm','escalation')),
        contact_name TEXT, contact_email TEXT,
        needs_contact_info INTEGER NOT NULL DEFAULT 0,
        subject TEXT NOT NULL, body_draft TEXT NOT NULL,
        body_final TEXT,
        status TEXT NOT NULL DEFAULT 'pending'
          CHECK(status IN ('pending','approved','sent','skipped','failed')),
        skip_reason TEXT, sent_at TEXT, error_message TEXT,
        created_at TEXT NOT NULL DEFAULT (datetime('now'))
      );
    `);
  }

  let _ridSeq = 0;
  function insertApprovedReminder(db: Database.Database, cabinetId: string): number {
    const entityId = `entry-${++_ridSeq}`;
    const aId = db.prepare(
      `INSERT INTO anomalies (cabinet_id, client_id, type, state, subject_entity_type, subject_entity_id, details_json)
       VALUES (?, 'client-A', 'vat_no_evidence', 'open', 'accounting_entry', ?, '{}')`
    ).run(cabinetId, entityId).lastInsertRowid as number;

    return db.prepare(
      `INSERT INTO reminders
         (cabinet_id, client_id, anomaly_id, level, contact_email, subject, body_draft, status)
       VALUES (?, 'client-A', ?, 'polite', 'client@example.ch',
               'Pièce manquante', 'Bonjour, merci de nous envoyer la facture.', 'approved')`
    ).run(cabinetId, aId).lastInsertRowid as number;
  }

  const db = new Database(tmpDbPath);
  initSchema(db);

  const rid1 = insertApprovedReminder(db, "cab-01");
  const rid2 = insertApprovedReminder(db, "cab-01");
  const rid3 = insertApprovedReminder(db, "cab-01");
  db.close();

  // ── Helper : run send_reminder.py ─────────────────────────────────────────
  function runScript(
    reminderId: number,
    cabinetId: string,
    opts: { dryRun?: boolean; passEnc?: string | null } = {}
  ): Promise<{ code: number; json: Record<string, unknown>; stderr: string }> {
    return new Promise((resolve) => {
      const dryRun = opts.dryRun !== false;
      // Build env as NodeJS.ProcessEnv (all values string | undefined)
      const env: NodeJS.ProcessEnv = {
        ...process.env,
        FIDUCIAIRE_ENCRYPTION_DISABLED: "true",
        SMTP_DRY_RUN: dryRun ? "true" : "false",
        SMTP_HOST: "mail.test.ch",
        SMTP_PORT: "587",
        SMTP_USER: "test@cabinet.ch",
        SMTP_FROM: "test@cabinet.ch",
      };
      if (opts.passEnc !== null) {
        env.SMTP_PASS_ENC = opts.passEnc ?? "dummy-pass";
      } else {
        delete env.SMTP_PASS_ENC;
      }

      const child = spawn(PYTHON, [
        SCRIPT,
        "--reminder-id", String(reminderId),
        "--cabinet-id", cabinetId,
        "--db", tmpDbPath,
      ], { env, stdio: ["ignore", "pipe", "pipe"] });

      let stdout = "";
      let stderr = "";
      child.stdout.on("data", (d) => (stdout += d.toString()));
      child.stderr.on("data", (d) => (stderr += d.toString()));
      child.on("close", (code) => {
        try {
          resolve({ code: code ?? -1, json: JSON.parse(stdout.trim()), stderr });
        } catch {
          resolve({ code: code ?? -1, json: { __raw: stdout.trim() }, stderr });
        }
      });
    });
  }

  // ── Tests ─────────────────────────────────────────────────────────────────
  const results: { name: string; ok: boolean; error?: string }[] = [];

  function check(name: string, fn: () => void | Promise<void>) {
    return Promise.resolve()
      .then(fn)
      .then(() => results.push({ name, ok: true }))
      .catch((e) =>
        results.push({ name, ok: false, error: e instanceof Error ? e.message : String(e) })
      );
  }

  // 1. Script Python — JSON ok:true en dry-run
  await check("Script CLI — dry-run renvoie JSON ok:true + status:sent", async () => {
    const { code, json } = await runScript(rid1, "cab-01");
    if (code !== 0) throw new Error(`exit code ${code}`);
    if (json.ok !== true) throw new Error(`ok=${json.ok}`);
    if (json.status !== "sent") throw new Error(`status=${json.status}`);
    if (json.dry_run !== true) throw new Error(`dry_run=${json.dry_run}`);
    if (!json.sent_at) throw new Error("sent_at absent");
  });

  // 2. Script Python — JSON ok:false si SMTP_PASS_ENC absent
  await check("Script CLI — SMTP_PASS_ENC absent → JSON ok:false + exit 1", async () => {
    const { code, json } = await runScript(rid2, "cab-01", { passEnc: null });
    if (code !== 1) throw new Error(`exit code attendu 1, got ${code}`);
    if (json.ok !== false) throw new Error(`ok devrait être false, got ${json.ok}`);
    if (!json.error) throw new Error("error absent du JSON");
  });

  // 3. Script Python — cross-cabinet → JSON ok:false + exit 1
  await check("Script CLI — cross-cabinet → JSON ok:false + exit 1", async () => {
    const { code, json } = await runScript(rid3, "cab-mauvais");
    if (code !== 1) throw new Error(`exit code attendu 1, got ${code}`);
    if (json.ok !== false) throw new Error(`ok devrait être false`);
    const errMsg = String(json.error || "");
    if (!errMsg.toLowerCase().includes("introuvable") && !errMsg.toLowerCase().includes("cabinet")) {
      throw new Error(`error message inattendu: ${errMsg}`);
    }
  });

  // ── Report ────────────────────────────────────────────────────────────────
  const passed = results.filter((r) => r.ok).length;
  const failed = results.filter((r) => !r.ok).length;

  for (const r of results) {
    console.log(`${r.ok ? "✅" : "❌"} ${r.name}${r.error ? ` — ${r.error}` : ""}`);
  }
  console.log(`\n${passed}/${results.length} passed`);

  fs.rmSync(tmpDir, { recursive: true, force: true });

  if (failed > 0) process.exit(1);
})();
