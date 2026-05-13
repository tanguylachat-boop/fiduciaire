// Driver SQLite READ + verify pour le dashboard /(poc)/audit — Sprint 2 §3.10 Phase 3.
//
// Vérifie la chain hash en pur TS via cross-compat avec audit_log.py.
// Filtres optionnels : entity_type, action, date range.

import Database from "better-sqlite3";
import path from "node:path";
import fs from "node:fs";
import { computeAuditHash, GENESIS_HASH } from "./audit-log-ts";

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
  const exists = fs.existsSync(DB_PATH);
  const conn = exists
    ? new Database(DB_PATH, { readonly: true, fileMustExist: true })
    : new Database(":memory:");
  try {
    return fn(conn);
  } finally {
    conn.close();
  }
}

function tableExists(db: Database.Database, name: string): boolean {
  try {
    const row = db
      .prepare("SELECT name FROM sqlite_master WHERE type='table' AND name=?")
      .get(name) as { name?: string } | undefined;
    return !!row?.name;
  } catch {
    return false;
  }
}

export type AuditEventRow = {
  id: number;
  cabinet_id: string;
  user_id: string | null;
  timestamp: string;
  entity_type: string;
  entity_id: string;
  action: string;
  before_json: string | null;
  after_json: string | null;
  prev_hash: string;
  current_hash: string;
};

export type AuditFilters = {
  cabinetId: string;
  entityType?: string;
  action?: string;
  dateFrom?: string;
  dateTo?: string;
  limit?: number;
  offset?: number;
};

export type AuditCabinetSummary = {
  cabinet_id: string;
  events_count: number;
};

export function listAuditCabinets(): AuditCabinetSummary[] {
  return withDb((db) => {
    if (!tableExists(db, "audit_log")) return [];
    return db
      .prepare(
        "SELECT cabinet_id, COUNT(*) AS events_count " +
          "FROM audit_log GROUP BY cabinet_id ORDER BY cabinet_id",
      )
      .all() as AuditCabinetSummary[];
  });
}

export function listAuditEvents(filters: AuditFilters): AuditEventRow[] {
  const limit = filters.limit ?? 50;
  const offset = filters.offset ?? 0;
  return withDb((db) => {
    if (!tableExists(db, "audit_log")) return [];
    const wheres: string[] = ["cabinet_id = ?"];
    const params: unknown[] = [filters.cabinetId];
    if (filters.entityType) {
      wheres.push("entity_type = ?");
      params.push(filters.entityType);
    }
    if (filters.action) {
      wheres.push("action = ?");
      params.push(filters.action);
    }
    if (filters.dateFrom) {
      wheres.push("timestamp >= ?");
      params.push(filters.dateFrom);
    }
    if (filters.dateTo) {
      wheres.push("timestamp <= ?");
      params.push(filters.dateTo);
    }
    params.push(limit, offset);
    return db
      .prepare(
        `SELECT * FROM audit_log WHERE ${wheres.join(" AND ")} ` +
          "ORDER BY id DESC LIMIT ? OFFSET ?",
      )
      .all(...params) as AuditEventRow[];
  });
}

export function countAuditEvents(filters: AuditFilters): number {
  return withDb((db) => {
    if (!tableExists(db, "audit_log")) return 0;
    const wheres: string[] = ["cabinet_id = ?"];
    const params: unknown[] = [filters.cabinetId];
    if (filters.entityType) {
      wheres.push("entity_type = ?");
      params.push(filters.entityType);
    }
    if (filters.action) {
      wheres.push("action = ?");
      params.push(filters.action);
    }
    const row = db
      .prepare(
        `SELECT COUNT(*) AS n FROM audit_log WHERE ${wheres.join(" AND ")}`,
      )
      .get(...params) as { n: number };
    return row.n;
  });
}

export type ChainVerificationResult = {
  cabinet_id: string;
  total_events: number;
  is_valid: boolean;
  first_invalid_id: number | null;
  first_invalid_reason: string | null;
};

/**
 * Recompute chaque hash de la chain et vérifie l'intégrité.
 * Détecte : prev_hash incohérent, current_hash recalculé != stocké.
 *
 * Note : pour pousser à grande échelle, paginer. Sprint 2 §3.10 Phase 3 :
 * on charge toute la chain du cabinet (typiquement ≤ quelques milliers
 * d'events pour Sprint 1 pilote — acceptable pour Server Component).
 */
export function verifyAuditChain(cabinetId: string): ChainVerificationResult {
  return withDb((db) => {
    if (!tableExists(db, "audit_log")) {
      return {
        cabinet_id: cabinetId,
        total_events: 0,
        is_valid: true,
        first_invalid_id: null,
        first_invalid_reason: null,
      };
    }
    const rows = db
      .prepare(
        "SELECT id, cabinet_id, user_id, timestamp, entity_type, entity_id, " +
          "       action, before_json, after_json, prev_hash, current_hash " +
          "FROM audit_log WHERE cabinet_id=? ORDER BY id ASC",
      )
      .all(cabinetId) as AuditEventRow[];

    let expectedPrev = GENESIS_HASH;
    for (const row of rows) {
      if (row.prev_hash !== expectedPrev) {
        return {
          cabinet_id: cabinetId,
          total_events: rows.length,
          is_valid: false,
          first_invalid_id: row.id,
          first_invalid_reason: `prev_hash mismatch (attendu ${expectedPrev.slice(0, 8)}..., reçu ${row.prev_hash.slice(0, 8)}...)`,
        };
      }
      const recomputed = computeAuditHash({
        prevHash: row.prev_hash,
        cabinetId: row.cabinet_id,
        userId: row.user_id,
        timestamp: row.timestamp,
        entityType: row.entity_type,
        entityId: row.entity_id,
        action: row.action,
        beforeJson: row.before_json,
        afterJson: row.after_json,
      });
      if (recomputed !== row.current_hash) {
        return {
          cabinet_id: cabinetId,
          total_events: rows.length,
          is_valid: false,
          first_invalid_id: row.id,
          first_invalid_reason: "current_hash mismatch (row data altered)",
        };
      }
      expectedPrev = row.current_hash;
    }

    return {
      cabinet_id: cabinetId,
      total_events: rows.length,
      is_valid: true,
      first_invalid_id: null,
      first_invalid_reason: null,
    };
  });
}
