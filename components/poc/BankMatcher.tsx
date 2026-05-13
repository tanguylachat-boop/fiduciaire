"use client";

import { useActionState, useMemo, useState } from "react";
import {
  manuallyLinkTransactionAction,
  type ManualLinkResult,
} from "@/app/(poc)/bank/actions";
import { Card, CardBody, CardHeader, CardTitle } from "@/components/ui/Card";

type Tx = {
  id: number;
  value_date: string;
  amount_chf: number;
  currency: string;
  credit_debit: string;
  description: string;
  qr_reference: string | null;
  iban_last4: string;
  creditor_name: string | null;
  debtor_name: string | null;
};

type Inv = {
  id: number;
  date: string;
  amount_chf: number;
  description: string;
  bexio_id: string | null;
  doc_filename: string | null;
};

const fmtCHF = new Intl.NumberFormat("fr-CH", {
  style: "currency",
  currency: "CHF",
  minimumFractionDigits: 2,
});

const fmtDate = (iso: string) =>
  iso
    ? new Date(iso.slice(0, 10) + "T00:00:00").toLocaleDateString("fr-CH", {
        day: "2-digit",
        month: "2-digit",
        year: "numeric",
      })
    : "—";

export function BankMatcher({
  transactions,
  invoices,
}: {
  transactions: Tx[];
  invoices: Inv[];
}) {
  const [selectedTx, setSelectedTx] = useState<number | null>(null);
  const [selectedInv, setSelectedInv] = useState<number | null>(null);
  const [state, formAction, pending] = useActionState<
    ManualLinkResult | undefined,
    FormData
  >(manuallyLinkTransactionAction, undefined);

  const tx = useMemo(
    () => transactions.find((t) => t.id === selectedTx) ?? null,
    [transactions, selectedTx],
  );
  const inv = useMemo(
    () => invoices.find((i) => i.id === selectedInv) ?? null,
    [invoices, selectedInv],
  );

  const canSubmit =
    selectedTx !== null && selectedInv !== null && !pending;

  return (
    <div className="grid gap-4 md:grid-cols-[1fr_auto_1fr]">
      {/* LEFT — Bank transactions unmatched */}
      <Card>
        <CardHeader>
          <CardTitle>
            Transactions bancaires non matchées ({transactions.length})
          </CardTitle>
        </CardHeader>
        {transactions.length === 0 ? (
          <CardBody>
            <p className="text-sm text-[var(--color-text-dim)]">
              Aucune transaction non matchée. Importez un CAMT.053 ci-dessus.
            </p>
          </CardBody>
        ) : (
          <div className="max-h-[600px] overflow-y-auto">
            <table className="w-full text-xs">
              <thead className="sticky top-0 bg-[var(--color-bg-card)]">
                <tr className="border-b border-[var(--color-border)] text-left font-medium uppercase tracking-wider text-[var(--color-text-dim)]">
                  <th className="px-3 py-2 w-8"></th>
                  <th className="px-3 py-2">Date</th>
                  <th className="px-3 py-2 text-right">Montant</th>
                  <th className="px-3 py-2">IBAN</th>
                  <th className="px-3 py-2">Description</th>
                </tr>
              </thead>
              <tbody>
                {transactions.map((t) => (
                  <tr
                    key={t.id}
                    className={
                      "border-b border-[var(--color-border)]/60 cursor-pointer hover:bg-white/[0.03] " +
                      (selectedTx === t.id ? "bg-emerald-500/10" : "")
                    }
                    onClick={() => setSelectedTx(t.id)}
                  >
                    <td className="px-3 py-2">
                      <input
                        type="radio"
                        name="tx_select"
                        checked={selectedTx === t.id}
                        onChange={() => setSelectedTx(t.id)}
                        aria-label={`Sélectionner transaction ${t.id}`}
                      />
                    </td>
                    <td className="px-3 py-2 font-mono text-[var(--color-text-muted)]">
                      {fmtDate(t.value_date)}
                    </td>
                    <td
                      className={
                        "px-3 py-2 text-right font-mono tabular-nums " +
                        (t.credit_debit === "CRDT"
                          ? "text-emerald-400"
                          : "text-amber-400")
                      }
                    >
                      {fmtCHF.format(t.amount_chf)}
                    </td>
                    <td className="px-3 py-2 font-mono text-[var(--color-text-dim)]">
                      …{t.iban_last4}
                    </td>
                    <td className="px-3 py-2">
                      <div className="line-clamp-1 max-w-[220px]">
                        {t.description || "—"}
                      </div>
                      {t.qr_reference && (
                        <div className="font-mono text-[10px] text-[var(--color-text-dim)]">
                          QR: {t.qr_reference}
                        </div>
                      )}
                      {(t.creditor_name || t.debtor_name) && (
                        <div className="text-[10px] text-[var(--color-text-dim)]">
                          {t.credit_debit === "CRDT"
                            ? t.debtor_name
                            : t.creditor_name}
                        </div>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>

      {/* CENTER — Match button */}
      <div className="flex flex-col items-center justify-center gap-3 py-6 md:py-12">
        <form action={formAction}>
          <input
            type="hidden"
            name="__transactionId"
            value={selectedTx ?? ""}
          />
          <input
            type="hidden"
            name="__entryId"
            value={selectedInv ?? ""}
          />
          <button
            type="submit"
            disabled={!canSubmit}
            className="rounded-md border border-emerald-500/30 bg-emerald-500/10 px-4 py-3 text-sm font-medium text-emerald-300 hover:bg-emerald-500/20 disabled:cursor-not-allowed disabled:opacity-40"
          >
            {pending ? "Liaison en cours…" : "→ Lier ces 2 lignes ←"}
          </button>
        </form>

        {tx && inv && (
          <div className="text-center text-[11px] text-[var(--color-text-dim)]">
            <div className="font-mono">tx#{tx.id}</div>
            <div className="my-1">→</div>
            <div className="font-mono">entry#{inv.id}</div>
            {Math.abs(Math.abs(tx.amount_chf) - inv.amount_chf) >= 0.01 && (
              <div className="mt-2 text-amber-400">
                ⚠️ Montants différents
              </div>
            )}
          </div>
        )}

        {state?.ok === true && (
          <p className="rounded-md bg-emerald-500/10 px-3 py-2 text-xs text-emerald-300">
            ✓ {state.message}
          </p>
        )}
        {state?.ok === false && (
          <p className="rounded-md bg-red-500/10 px-3 py-2 text-xs text-red-300">
            ✗ {state.error}
          </p>
        )}
      </div>

      {/* RIGHT — Unpaid invoices */}
      <Card>
        <CardHeader>
          <CardTitle>Factures émises non payées ({invoices.length})</CardTitle>
        </CardHeader>
        {invoices.length === 0 ? (
          <CardBody>
            <p className="text-sm text-[var(--color-text-dim)]">
              Aucune facture non payée.
            </p>
          </CardBody>
        ) : (
          <div className="max-h-[600px] overflow-y-auto">
            <table className="w-full text-xs">
              <thead className="sticky top-0 bg-[var(--color-bg-card)]">
                <tr className="border-b border-[var(--color-border)] text-left font-medium uppercase tracking-wider text-[var(--color-text-dim)]">
                  <th className="px-3 py-2 w-8"></th>
                  <th className="px-3 py-2">Date</th>
                  <th className="px-3 py-2 text-right">Montant</th>
                  <th className="px-3 py-2">Bexio</th>
                  <th className="px-3 py-2">Description</th>
                </tr>
              </thead>
              <tbody>
                {invoices.map((i) => (
                  <tr
                    key={i.id}
                    className={
                      "border-b border-[var(--color-border)]/60 cursor-pointer hover:bg-white/[0.03] " +
                      (selectedInv === i.id ? "bg-emerald-500/10" : "")
                    }
                    onClick={() => setSelectedInv(i.id)}
                  >
                    <td className="px-3 py-2">
                      <input
                        type="radio"
                        name="inv_select"
                        checked={selectedInv === i.id}
                        onChange={() => setSelectedInv(i.id)}
                        aria-label={`Sélectionner écriture ${i.id}`}
                      />
                    </td>
                    <td className="px-3 py-2 font-mono text-[var(--color-text-muted)]">
                      {fmtDate(i.date)}
                    </td>
                    <td className="px-3 py-2 text-right font-mono tabular-nums">
                      {fmtCHF.format(i.amount_chf)}
                    </td>
                    <td className="px-3 py-2 font-mono text-[var(--color-text-dim)]">
                      {i.bexio_id ?? "—"}
                    </td>
                    <td className="px-3 py-2">
                      <div className="line-clamp-1 max-w-[220px]">
                        {i.description || "—"}
                      </div>
                      {i.doc_filename && (
                        <div className="font-mono text-[10px] text-[var(--color-text-dim)]">
                          {i.doc_filename}
                        </div>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>
    </div>
  );
}
