"use client";

import { useActionState, useState } from "react";
import { CheckCircle2, Edit3, XCircle, Save } from "lucide-react";
import { Button } from "@/components/ui/Button";
import { Badge } from "@/components/ui/Badge";
import {
  validateEntryAction,
  correctEntryAction,
  rejectEntryAction,
  type ActionResult,
} from "@/app/(poc)/entries/actions";

const VAT_CODES = ["TN_NORM", "TN_RED", "TN_HEB", "EXO", "EXP", "ACQ"];

export type EditorEntry = {
  id: number;
  client_id: string;
  state: "proposed" | "validated" | "rejected";
  date: string;
  debit_account: string;
  credit_account: string;
  amount_chf: number;
  vat_code: string;
  vat_amount: number | null;
  description: string;
  confidence_account: number;
  confidence_vat: number;
  reasoning: string | null;
  source_account?: string | null;
  source_vat?: string | null;
};

export function EntryEditor({ entry }: { entry: EditorEntry }) {
  const isLocked = entry.state !== "proposed";
  const [editing, setEditing] = useState(false);
  const [showRejectModal, setShowRejectModal] = useState(false);

  const [validateResult, validateAction, validatePending] = useActionState<
    ActionResult | undefined,
    FormData
  >(validateEntryAction, undefined);
  const [correctResult, correctAction, correctPending] = useActionState<
    ActionResult | undefined,
    FormData
  >(correctEntryAction, undefined);
  const [rejectResult, rejectAction, rejectPending] = useActionState<
    ActionResult | undefined,
    FormData
  >(rejectEntryAction, undefined);

  const lastResult = validateResult ?? correctResult ?? rejectResult;

  return (
    <div className="flex h-full flex-col gap-4">
      <Header entry={entry} />

      {lastResult && (
        <div
          className={
            lastResult.ok
              ? "rounded-md border border-emerald-500/30 bg-emerald-500/10 px-3 py-2 text-xs text-emerald-300"
              : "rounded-md border border-red-500/30 bg-red-500/10 px-3 py-2 text-xs text-red-300"
          }
        >
          {lastResult.ok ? lastResult.message : lastResult.error}
        </div>
      )}

      {/* Mode édition : un seul <form action={correctAction}> qui submit le payload. */}
      {editing && !isLocked ? (
        <form action={correctAction} className="flex flex-1 flex-col gap-3">
          <input type="hidden" name="__entryId" value={entry.id} />
          <input type="hidden" name="__clientId" value={entry.client_id} />
          <FieldsGrid entry={entry} editable />
          <Reasoning entry={entry} />
          <div className="mt-auto flex flex-wrap items-center justify-between gap-3 border-t border-[var(--color-border)] pt-3">
            <span className="text-[11px] text-[var(--color-text-dim)]">
              Sauvegarder applique les corrections et marque l'écriture comme
              validée.
            </span>
            <div className="flex items-center gap-2">
              <Button
                type="button"
                variant="ghost"
                size="md"
                onClick={() => setEditing(false)}
                disabled={correctPending}
              >
                Annuler
              </Button>
              <Button
                type="submit"
                variant="primary"
                size="md"
                disabled={correctPending}
              >
                <Save size={14} />
                Sauver et valider
              </Button>
            </div>
          </div>
        </form>
      ) : (
        // Mode lecture : pas de form. Les boutons Validate / Reject sont des forms isolées.
        <div className="flex flex-1 flex-col gap-3">
          <FieldsGrid entry={entry} editable={false} />
          <Reasoning entry={entry} />
          <div className="mt-auto flex flex-wrap items-center justify-between gap-3 border-t border-[var(--color-border)] pt-3">
            <span className="text-[11px] text-[var(--color-text-dim)]">
              {isLocked
                ? "Écriture verrouillée — seules les écritures proposées sont éditables."
                : "Lecture seule. Clique sur Corriger pour éditer."}
            </span>
            {!isLocked && (
              <div className="flex flex-wrap items-center gap-2">
                <form action={validateAction} className="contents">
                  <input type="hidden" name="__entryId" value={entry.id} />
                  <input
                    type="hidden"
                    name="__clientId"
                    value={entry.client_id}
                  />
                  <Button
                    type="submit"
                    variant="success"
                    size="md"
                    disabled={validatePending}
                  >
                    <CheckCircle2 size={14} />
                    Valider
                  </Button>
                </form>
                <Button
                  type="button"
                  variant="secondary"
                  size="md"
                  onClick={() => setEditing(true)}
                >
                  <Edit3 size={14} />
                  Corriger
                </Button>
                <Button
                  type="button"
                  variant="danger"
                  size="md"
                  onClick={() => setShowRejectModal(true)}
                >
                  <XCircle size={14} />
                  Rejeter
                </Button>
              </div>
            )}
          </div>
        </div>
      )}

      {showRejectModal && !isLocked && (
        <div
          className="fixed inset-0 z-40 flex items-center justify-center bg-black/60 p-4"
          onClick={() => !rejectPending && setShowRejectModal(false)}
        >
          <form
            action={rejectAction}
            onClick={(e) => e.stopPropagation()}
            className="w-full max-w-md rounded-xl border border-[var(--color-border)] bg-[var(--color-bg-card)] p-5"
          >
            <input type="hidden" name="__entryId" value={entry.id} />
            <input type="hidden" name="__clientId" value={entry.client_id} />
            <h3 className="mb-3 text-sm font-semibold">
              Rejeter l'écriture #{entry.id}
            </h3>
            <p className="mb-3 text-xs text-[var(--color-text-muted)]">
              Indique la raison du rejet — elle sera tracée dans l'audit.
            </p>
            <textarea
              name="reason"
              required
              rows={3}
              className="w-full rounded-md border border-[var(--color-border-strong)] bg-[var(--color-bg)] px-3 py-2 text-sm text-[var(--color-text)] focus:outline focus:outline-2 focus:outline-[var(--color-accent)]"
              placeholder="ex. Document hors périmètre fiduciaire, à reclasser…"
            />
            <div className="mt-3 flex justify-end gap-2">
              <Button
                type="button"
                variant="ghost"
                size="sm"
                onClick={() => setShowRejectModal(false)}
                disabled={rejectPending}
              >
                Annuler
              </Button>
              <Button
                type="submit"
                variant="danger"
                size="sm"
                disabled={rejectPending}
              >
                <XCircle size={14} />
                Confirmer le rejet
              </Button>
            </div>
          </form>
        </div>
      )}
    </div>
  );
}

function Header({ entry }: { entry: EditorEntry }) {
  return (
    <div>
      <div className="flex items-center gap-2">
        <h2 className="text-base font-semibold tracking-tight">
          Écriture #{entry.id}
        </h2>
        {entry.state === "proposed" && (
          <Badge variant="info">Proposée</Badge>
        )}
        {entry.state === "validated" && (
          <Badge variant="success">Validée</Badge>
        )}
        {entry.state === "rejected" && (
          <Badge variant="danger">Rejetée</Badge>
        )}
      </div>
      <p className="mt-1 text-xs text-[var(--color-text-muted)]">
        Mandant{" "}
        <span className="font-mono">{entry.client_id}</span> · confiance compte{" "}
        {Math.round(entry.confidence_account * 100)}% · confiance TVA{" "}
        {Math.round(entry.confidence_vat * 100)}%
      </p>
    </div>
  );
}

function FieldsGrid({
  entry,
  editable,
}: {
  entry: EditorEntry;
  editable: boolean;
}) {
  return (
    <>
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
        <FieldText
          label="Compte débit"
          name="debit_account"
          defaultValue={entry.debit_account}
          disabled={!editable}
          mono
        />
        <FieldText
          label="Compte crédit"
          name="credit_account"
          defaultValue={entry.credit_account}
          disabled={!editable}
          mono
        />
        <FieldNumber
          label="Montant CHF"
          name="amount_chf"
          defaultValue={entry.amount_chf}
          step="0.05"
          disabled={!editable}
        />
        <FieldSelect
          label="Code TVA"
          name="vat_code"
          defaultValue={entry.vat_code}
          options={VAT_CODES}
          disabled={!editable}
        />
        <FieldNumber
          label="Montant TVA CHF"
          name="vat_amount"
          defaultValue={entry.vat_amount ?? 0}
          step="0.05"
          disabled={!editable}
        />
        <FieldText
          label="Date document"
          name="date_display"
          defaultValue={entry.date}
          disabled
        />
      </div>
      <FieldArea
        label="Libellé"
        name="description"
        defaultValue={entry.description}
        disabled={!editable}
      />
    </>
  );
}

function Reasoning({ entry }: { entry: EditorEntry }) {
  if (!entry.reasoning) return null;
  return (
    <details className="rounded-md border border-[var(--color-border)] bg-[var(--color-bg)]/40 px-3 py-2">
      <summary className="cursor-pointer text-xs font-medium text-[var(--color-text-muted)]">
        Raisonnement IA
        {entry.source_account && (
          <span className="ml-2 font-mono text-[10px] text-[var(--color-text-dim)]">
            source compte: {entry.source_account}
            {entry.source_vat && ` · source tva: ${entry.source_vat}`}
          </span>
        )}
      </summary>
      <p className="mt-2 text-xs leading-relaxed text-[var(--color-text-muted)]">
        {entry.reasoning}
      </p>
    </details>
  );
}

function FieldText({
  label,
  name,
  defaultValue,
  disabled,
  mono,
}: {
  label: string;
  name: string;
  defaultValue: string;
  disabled?: boolean;
  mono?: boolean;
}) {
  return (
    <label className="flex flex-col gap-1">
      <span className="text-[10px] font-medium uppercase tracking-wider text-[var(--color-text-dim)]">
        {label}
      </span>
      <input
        type="text"
        name={name}
        defaultValue={defaultValue}
        disabled={disabled}
        className={`rounded-md border border-[var(--color-border-strong)] bg-[var(--color-bg)] px-3 py-2 text-sm text-[var(--color-text)] disabled:opacity-60 focus:outline focus:outline-2 focus:outline-[var(--color-accent)] ${mono ? "font-mono" : ""}`}
      />
    </label>
  );
}

function FieldArea({
  label,
  name,
  defaultValue,
  disabled,
}: {
  label: string;
  name: string;
  defaultValue: string;
  disabled?: boolean;
}) {
  return (
    <label className="flex flex-col gap-1">
      <span className="text-[10px] font-medium uppercase tracking-wider text-[var(--color-text-dim)]">
        {label}
      </span>
      <textarea
        name={name}
        defaultValue={defaultValue}
        disabled={disabled}
        rows={2}
        className="rounded-md border border-[var(--color-border-strong)] bg-[var(--color-bg)] px-3 py-2 text-sm text-[var(--color-text)] disabled:opacity-60 focus:outline focus:outline-2 focus:outline-[var(--color-accent)]"
      />
    </label>
  );
}

function FieldNumber({
  label,
  name,
  defaultValue,
  step,
  disabled,
}: {
  label: string;
  name: string;
  defaultValue: number;
  step: string;
  disabled?: boolean;
}) {
  return (
    <label className="flex flex-col gap-1">
      <span className="text-[10px] font-medium uppercase tracking-wider text-[var(--color-text-dim)]">
        {label}
      </span>
      <input
        type="number"
        name={name}
        step={step}
        defaultValue={defaultValue}
        disabled={disabled}
        className="rounded-md border border-[var(--color-border-strong)] bg-[var(--color-bg)] px-3 py-2 text-right font-mono text-sm tabular-nums text-[var(--color-text)] disabled:opacity-60 focus:outline focus:outline-2 focus:outline-[var(--color-accent)]"
      />
    </label>
  );
}

function FieldSelect({
  label,
  name,
  defaultValue,
  options,
  disabled,
}: {
  label: string;
  name: string;
  defaultValue: string;
  options: string[];
  disabled?: boolean;
}) {
  return (
    <label className="flex flex-col gap-1">
      <span className="text-[10px] font-medium uppercase tracking-wider text-[var(--color-text-dim)]">
        {label}
      </span>
      <select
        name={name}
        defaultValue={defaultValue}
        disabled={disabled}
        className="rounded-md border border-[var(--color-border-strong)] bg-[var(--color-bg)] px-3 py-2 text-sm text-[var(--color-text)] disabled:opacity-60 focus:outline focus:outline-2 focus:outline-[var(--color-accent)]"
      >
        {options.map((o) => (
          <option key={o} value={o}>
            {o}
          </option>
        ))}
      </select>
    </label>
  );
}
