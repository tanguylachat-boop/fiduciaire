// Driver SQLite WRITE pour le matching manuel bank ↔ facture — Sprint 2 §3.10 Phase 4.
//
// Persiste matched_document_id + matched_accounting_entry_id + audit log.
// Multi-mandant strict : validation cross-mandant via validateManualLink.

import Database from "better-sqlite3";
import path from "node:path";
import fs from "node:fs";
import { logAuditEvent } from "./audit-log-ts";
import { validateManualLink } from "./db-poc-bank";

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

export class BankLinkError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "BankLinkError";
  }
}

function withWriteDb<T>(fn: (db: Database.Database) => T): T {
  if (!fs.existsSync(DB_PATH)) {
    throw new BankLinkError(
      `Base SQLite introuvable au chemin ${DB_PATH}. ` +
        "Lance le worker Python d'abord pour init le schéma.",
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

export type ManualLinkResult = {
  transactionId: number;
  documentId: number;
  accountingEntryId: number | null;
  cabinetId: string;
};

/**
 * Lien manuel d'une transaction bancaire à une écriture comptable validée.
 *
 * - Vérifie multi-mandant (tx.cabinet_id === entry.client_id) en read d'abord
 *   via `validateManualLink`, puis re-vérifie côté write pour éviter une
 *   race entre les 2 connexions (paranoïa raisonnable sur SQLite WAL).
 * - Persiste matched_document_id, matched_accounting_entry_id, matched_at,
 *   matched_by, match_confidence=1.0, match_strategy='manual'.
 * - Audit log via chain hash SHA-256.
 *
 * Si la transaction est déjà matchée, raise BankLinkError (idempotence
 * stricte côté UI : si tu veux re-matcher, unlink d'abord).
 */
export function manuallyLinkTransaction(
  transactionId: number,
  entryId: number,
  userId: string | null,
  reason: string | null = null,
): ManualLinkResult {
  const validation = validateManualLink(transactionId, entryId);
  if (!validation.ok) {
    throw new BankLinkError(validation.reason);
  }
  const { cabinetId, documentId, accountingEntryId } = validation;

  return withWriteDb((db) => {
    const txn = db.transaction(() => {
      const tx = db
        .prepare(
          "SELECT id, cabinet_id, matched_document_id " +
            "FROM bank_transactions WHERE id = ?",
        )
        .get(transactionId) as
        | {
            id: number;
            cabinet_id: string;
            matched_document_id: number | null;
          }
        | undefined;
      if (!tx) throw new BankLinkError("transaction introuvable (write)");
      if (tx.cabinet_id !== cabinetId) {
        throw new BankLinkError(
          "cross-mandant détecté entre validation et write",
        );
      }
      if (tx.matched_document_id !== null) {
        throw new BankLinkError(
          `transaction ${transactionId} déjà matchée ` +
            `(document=${tx.matched_document_id}) — unlink d'abord`,
        );
      }

      db.prepare(
        `UPDATE bank_transactions SET
           matched_document_id = ?,
           matched_accounting_entry_id = ?,
           matched_at = datetime('now'),
           matched_by = ?,
           match_confidence = 1.0,
           match_strategy = 'manual'
         WHERE id = ?`,
      ).run(documentId, accountingEntryId, userId, transactionId);

      logAuditEvent(db, {
        cabinetId,
        entityType: "bank_transaction",
        entityId: transactionId,
        action: "matched",
        userId,
        after: {
          document_id: documentId,
          accounting_entry_id: accountingEntryId,
          strategy: "manual",
          confidence: 1.0,
          reason: reason ?? "manual link from /bank dashboard",
        },
      });
    });
    txn();
    return {
      transactionId,
      documentId,
      accountingEntryId,
      cabinetId,
    };
  });
}
