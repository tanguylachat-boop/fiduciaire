"use client";

import { useActionState } from "react";
import {
  markAnomalyFalsePositiveAction,
  markAnomalyResolvedAction,
  type AnomalyActionResult,
} from "@/app/(poc)/clients/[client_id]/actions";

export function AnomalyActions({
  anomalyId,
  clientId,
}: {
  anomalyId: number;
  clientId: string;
}) {
  const [resolveState, resolveFormAction, resolvePending] = useActionState<
    AnomalyActionResult | undefined,
    FormData
  >(markAnomalyResolvedAction, undefined);
  const [fpState, fpFormAction, fpPending] = useActionState<
    AnomalyActionResult | undefined,
    FormData
  >(markAnomalyFalsePositiveAction, undefined);

  const pending = resolvePending || fpPending;

  return (
    <div className="flex items-center gap-2">
      <form action={resolveFormAction}>
        <input type="hidden" name="__anomalyId" value={anomalyId} />
        <input type="hidden" name="__clientId" value={clientId} />
        <button
          type="submit"
          disabled={pending}
          className="rounded-md border border-emerald-500/30 bg-emerald-500/10 px-2 py-1 text-xs text-emerald-300 hover:bg-emerald-500/20 disabled:opacity-50"
        >
          Résoudre
        </button>
      </form>
      <form action={fpFormAction}>
        <input type="hidden" name="__anomalyId" value={anomalyId} />
        <input type="hidden" name="__clientId" value={clientId} />
        <button
          type="submit"
          disabled={pending}
          className="rounded-md border border-[var(--color-border)] px-2 py-1 text-xs text-[var(--color-text-muted)] hover:bg-white/[0.05] disabled:opacity-50"
        >
          Faux positif
        </button>
      </form>
      {(resolveState?.ok === false || fpState?.ok === false) && (
        <span className="ml-2 text-xs text-red-400">
          {resolveState?.ok === false
            ? resolveState.error
            : fpState?.ok === false
              ? fpState.error
              : ""}
        </span>
      )}
    </div>
  );
}
