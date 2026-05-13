// Audit log append-only côté TS — Sprint 2 §3.10 Phase 2 (Session 9).
//
// Cross-compat avec `worker/src/fiduciaire_worker/audit_log.py` (Session 5).
// Chain hash SHA-256 par cabinet :
//   current_hash = SHA-256(prev_hash || cabinet_id || user_id || timestamp
//                         || entity_type || entity_id || action
//                         || before_json || after_json)
// Séparateur : "\x1f" (Unit Separator).
//
// JSON canonique cohérent avec Python `json.dumps(sort_keys=True,
// ensure_ascii=False)` : keys triées, séparateurs `", "` et `": "`,
// pas d'échappement ASCII.

import Database from "better-sqlite3";
import { createHash } from "node:crypto";

export const GENESIS_HASH = "0".repeat(64);

// --- Canonical JSON (Python-compatible) ------------------------------------

/**
 * Produit un JSON équivalent à `json.dumps(obj, ensure_ascii=False, sort_keys=True)`.
 * - keys triées récursivement
 * - séparateurs `, ` et `: `
 * - utf-8 natif (pas d'échappement \uXXXX pour chars Unicode normaux)
 *
 * Note : ne gère que les types couramment présents dans nos snapshots audit
 * (string, number, boolean, null, plain object, array). Pas de Date, BigInt, etc.
 */
export function canonicalJsonPythonStyle(value: unknown): string {
  if (value === null || value === undefined) return "null";
  if (typeof value === "boolean") return value ? "true" : "false";
  if (typeof value === "number") {
    if (!Number.isFinite(value)) {
      throw new Error(`canonicalJson: NaN/Infinity non supportés`);
    }
    // Python json: int → "1", float → "1.5" ou "1.0".
    // JS : Number.isInteger(1.0) → true → "1" (≠ Python "1.0" pour 1.0).
    // En pratique, dans nos audits TS on n'a pas de floats. Si jamais
    // un float arrive avec partie entière exacte, on émet la forme JS.
    return String(value);
  }
  if (typeof value === "string") {
    // JSON.stringify échappe \" \\ \n \r \t etc. mais laisse les chars Unicode.
    return JSON.stringify(value);
  }
  if (Array.isArray(value)) {
    return "[" + value.map(canonicalJsonPythonStyle).join(", ") + "]";
  }
  if (typeof value === "object") {
    const obj = value as Record<string, unknown>;
    const keys = Object.keys(obj).sort();
    const parts = keys.map(
      (k) =>
        JSON.stringify(k) + ": " + canonicalJsonPythonStyle(obj[k]),
    );
    return "{" + parts.join(", ") + "}";
  }
  throw new Error(`canonicalJson: type non supporté ${typeof value}`);
}

// --- Hash --------------------------------------------------------------------

export function computeAuditHash(args: {
  prevHash: string;
  cabinetId: string;
  userId: string | null;
  timestamp: string;
  entityType: string;
  entityId: string;
  action: string;
  beforeJson: string | null;
  afterJson: string | null;
}): string {
  const parts = [
    args.prevHash,
    args.cabinetId,
    args.userId ?? "",
    args.timestamp,
    args.entityType,
    args.entityId,
    args.action,
    args.beforeJson ?? "",
    args.afterJson ?? "",
  ];
  const blob = parts.join("\x1f");
  return createHash("sha256").update(blob, "utf8").digest("hex");
}

// --- ISO timestamp Python-compat ---------------------------------------------

/**
 * Format identique à Python : `datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")`
 * Exemple : "2026-05-13T15:30:45.123456Z"
 * (Python utilise des microsecondes, JS Date n'en a pas → on rembourre avec "000")
 */
export function isoTimestampUtcMicro(d: Date = new Date()): string {
  const pad = (n: number, len = 2) => String(n).padStart(len, "0");
  const yyyy = d.getUTCFullYear();
  const mm = pad(d.getUTCMonth() + 1);
  const dd = pad(d.getUTCDate());
  const hh = pad(d.getUTCHours());
  const mi = pad(d.getUTCMinutes());
  const ss = pad(d.getUTCSeconds());
  const ms = pad(d.getUTCMilliseconds(), 3);
  return `${yyyy}-${mm}-${dd}T${hh}:${mi}:${ss}.${ms}000Z`;
}

// --- Append API ------------------------------------------------------------

export function logAuditEvent(
  db: Database.Database,
  args: {
    cabinetId: string;
    entityType: string;
    entityId: string | number;
    action: string;
    userId?: string | null;
    before?: Record<string, unknown> | null;
    after?: Record<string, unknown> | null;
    timestamp?: string;
  },
): number {
  // Skip silencieux si la table n'existe pas (back-compat)
  const tableRow = db
    .prepare(
      "SELECT name FROM sqlite_master WHERE type='table' AND name='audit_log'",
    )
    .get() as { name?: string } | undefined;
  if (!tableRow?.name) return -1;

  const ts = args.timestamp ?? isoTimestampUtcMicro();
  const userId = args.userId ?? null;
  const beforeJson =
    args.before !== undefined && args.before !== null
      ? canonicalJsonPythonStyle(args.before)
      : null;
  const afterJson =
    args.after !== undefined && args.after !== null
      ? canonicalJsonPythonStyle(args.after)
      : null;

  const prevRow = db
    .prepare(
      "SELECT current_hash FROM audit_log WHERE cabinet_id=? " +
        "ORDER BY id DESC LIMIT 1",
    )
    .get(args.cabinetId) as { current_hash?: string } | undefined;
  const prevHash = prevRow?.current_hash ?? GENESIS_HASH;

  const currentHash = computeAuditHash({
    prevHash,
    cabinetId: args.cabinetId,
    userId,
    timestamp: ts,
    entityType: args.entityType,
    entityId: String(args.entityId),
    action: args.action,
    beforeJson,
    afterJson,
  });

  const result = db
    .prepare(
      "INSERT INTO audit_log " +
        "(cabinet_id, user_id, timestamp, entity_type, entity_id, action, " +
        " before_json, after_json, prev_hash, current_hash) " +
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
    )
    .run(
      args.cabinetId,
      userId,
      ts,
      args.entityType,
      String(args.entityId),
      args.action,
      beforeJson,
      afterJson,
      prevHash,
      currentHash,
    );
  return Number(result.lastInsertRowid);
}
