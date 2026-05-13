"use client";

import { useActionState, useRef } from "react";
import { Upload } from "lucide-react";
import {
  uploadAndImportCamt053,
  type Camt053ImportResult,
} from "@/app/(poc)/bank/actions";

export function Camt053Upload({
  cabinetId,
  clientId,
}: {
  cabinetId: string;
  clientId: string;
}) {
  const [state, formAction, pending] = useActionState<
    Camt053ImportResult | undefined,
    FormData
  >(uploadAndImportCamt053, undefined);
  const fileRef = useRef<HTMLInputElement>(null);

  return (
    <form
      action={formAction}
      className="flex flex-wrap items-center gap-3 rounded-xl border border-[var(--color-border)] bg-[var(--color-bg-card)] p-4"
    >
      <input type="hidden" name="__cabinetId" value={cabinetId} />
      <input type="hidden" name="__clientId" value={clientId} />
      <div className="flex items-center gap-2 text-sm">
        <Upload size={16} className="text-[var(--color-text-dim)]" />
        <span className="font-medium">Importer un CAMT.053</span>
      </div>
      <input
        ref={fileRef}
        type="file"
        name="file"
        accept=".xml,.XML"
        required
        className="block w-full max-w-xs text-xs file:mr-3 file:rounded-md file:border-0 file:bg-white/5 file:px-3 file:py-2 file:text-xs file:text-[var(--color-text)] hover:file:bg-white/10 sm:w-auto"
      />
      <button
        type="submit"
        disabled={pending}
        className="rounded-md border border-emerald-500/30 bg-emerald-500/10 px-3 py-2 text-xs text-emerald-300 hover:bg-emerald-500/20 disabled:opacity-50"
      >
        {pending ? "Import…" : "Importer"}
      </button>

      {state?.ok === true && (
        <span className="text-xs text-emerald-300">
          ✓ {state.iban} · {state.transactions_inserted} nouvelles ·{" "}
          {state.transactions_duplicates} déjà présentes ·{" "}
          {state.transactions_total} total
        </span>
      )}
      {state?.ok === false && (
        <span className="text-xs text-red-300">✗ {state.error}</span>
      )}
    </form>
  );
}
