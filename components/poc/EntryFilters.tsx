"use client";

import { useRouter, useSearchParams } from "next/navigation";
import { useTransition } from "react";

export type FilterClient = { client_id: string; n_proposed: number };

const INPUT_CLS =
  "rounded-md border border-[var(--color-border-strong)] bg-[var(--color-bg)] px-3 py-1.5 text-sm text-[var(--color-text)] focus:outline focus:outline-2 focus:outline-[var(--color-accent)]";

export function EntryFilters({
  clients,
  activeClient,
  activeState,
  activeConfidenceMin,
  activeAmountMin,
  activeAmountMax,
}: {
  clients: FilterClient[];
  activeClient: string;
  activeState: string;
  activeConfidenceMin: string;
  activeAmountMin: string;
  activeAmountMax: string;
}) {
  const router = useRouter();
  const params = useSearchParams();
  const [pending, startTransition] = useTransition();

  function update(key: string, value: string) {
    const next = new URLSearchParams(params.toString());
    if (value && value !== "any") next.set(key, value);
    else next.delete(key);
    next.delete("offset"); // reset pagination on filter change
    startTransition(() => router.push(`/entries?${next.toString()}`));
  }

  return (
    <div className="flex flex-wrap items-end gap-3 rounded-lg border border-[var(--color-border)] bg-[var(--color-bg-card)] p-3">
      <Field label="Mandant">
        <select
          className={INPUT_CLS}
          value={activeClient}
          onChange={(e) => update("client", e.target.value)}
        >
          {clients.length === 0 && (
            <option value="">— aucun mandant —</option>
          )}
          {clients.map((c) => (
            <option key={c.client_id} value={c.client_id}>
              {c.client_id} ({c.n_proposed} en attente)
            </option>
          ))}
        </select>
      </Field>

      <Field label="État">
        <select
          className={INPUT_CLS}
          value={activeState}
          onChange={(e) => update("state", e.target.value)}
        >
          <option value="any">Tous</option>
          <option value="proposed">Proposé</option>
          <option value="validated">Validé</option>
          <option value="rejected">Rejeté</option>
        </select>
      </Field>

      <Field label="Confiance min">
        <select
          className={INPUT_CLS}
          value={activeConfidenceMin}
          onChange={(e) => update("conf", e.target.value)}
        >
          <option value="any">—</option>
          <option value="0.5">≥ 50%</option>
          <option value="0.7">≥ 70%</option>
          <option value="0.85">≥ 85%</option>
        </select>
      </Field>

      <Field label="Montant min">
        <input
          type="number"
          className={`${INPUT_CLS} w-24`}
          placeholder="0"
          defaultValue={activeAmountMin}
          onBlur={(e) => update("amount_min", e.target.value)}
        />
      </Field>

      <Field label="Montant max">
        <input
          type="number"
          className={`${INPUT_CLS} w-24`}
          placeholder="—"
          defaultValue={activeAmountMax}
          onBlur={(e) => update("amount_max", e.target.value)}
        />
      </Field>

      {pending && (
        <span className="text-xs text-[var(--color-text-dim)]">
          Mise à jour…
        </span>
      )}
    </div>
  );
}

function Field({
  label,
  children,
}: {
  label: string;
  children: React.ReactNode;
}) {
  return (
    <label className="flex flex-col gap-1">
      <span className="text-[10px] font-medium uppercase tracking-wider text-[var(--color-text-dim)]">
        {label}
      </span>
      {children}
    </label>
  );
}
