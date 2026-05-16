"use client";

import { useState, useTransition } from "react";
import {
  approveAndSendReminder,
  skipReminderAction,
  editReminderDraftAction,
  batchApproveReminders,
} from "@/app/(poc)/reminders/actions";
import { Badge } from "@/components/ui/Badge";
import type { ReminderRow } from "@/lib/db-poc-reminders";

const LEVEL_LABELS: Record<string, string> = {
  polite: "1ère relance",
  firm: "2ème relance",
  escalation: "Escalade",
};

const LEVEL_VARIANT: Record<
  string,
  "default" | "success" | "warning" | "danger" | "info" | "muted"
> = {
  polite: "info",
  firm: "warning",
  escalation: "danger",
};

const STATUS_VARIANT: Record<
  string,
  "default" | "success" | "warning" | "danger" | "info" | "muted"
> = {
  pending: "warning",
  approved: "info",
  sent: "success",
  skipped: "muted",
  failed: "danger",
};

const STATUS_LABELS: Record<string, string> = {
  pending: "En attente",
  approved: "Approuvée",
  sent: "Envoyée",
  skipped: "Ignorée",
  failed: "Échouée",
};

function ReminderRow({
  reminder,
  cabinetId,
  selected,
  onSelect,
}: {
  reminder: ReminderRow;
  cabinetId: string;
  selected: boolean;
  onSelect: (id: number, v: boolean) => void;
}) {
  const [expanded, setExpanded] = useState(false);
  const [editing, setEditing] = useState(false);
  const [editBody, setEditBody] = useState(reminder.body_final || reminder.body_draft);
  const [feedback, setFeedback] = useState<string | null>(null);
  const [isPending, startTransition] = useTransition();

  const isActionable = ["pending", "approved"].includes(reminder.status);

  function handleApprove() {
    const fd = new FormData();
    fd.set("id", String(reminder.id));
    fd.set("cabinet_id", cabinetId);
    startTransition(async () => {
      const res = await approveAndSendReminder(fd);
      setFeedback(res.ok ? "✓ Approuvée" : `✗ ${res.error}`);
    });
  }

  function handleSkip() {
    const fd = new FormData();
    fd.set("id", String(reminder.id));
    fd.set("cabinet_id", cabinetId);
    fd.set("reason", "Ignorée manuellement");
    startTransition(async () => {
      const res = await skipReminderAction(fd);
      setFeedback(res.ok ? "Ignorée" : `✗ ${res.error}`);
    });
  }

  function handleSaveEdit() {
    const fd = new FormData();
    fd.set("id", String(reminder.id));
    fd.set("cabinet_id", cabinetId);
    fd.set("body_final", editBody);
    startTransition(async () => {
      const res = await editReminderDraftAction(fd);
      if (res.ok) {
        setEditing(false);
        setFeedback("✓ Sauvegardé et approuvé");
      } else {
        setFeedback(`✗ ${res.error}`);
      }
    });
  }

  return (
    <div
      className={`border rounded-lg transition-colors ${
        selected
          ? "border-blue-500/40 bg-blue-500/5"
          : "border-[var(--color-border)] bg-[var(--color-surface)]"
      }`}
    >
      {/* Row header */}
      <div className="flex items-start gap-3 p-4">
        {isActionable && (
          <input
            type="checkbox"
            className="mt-1 shrink-0"
            checked={selected}
            onChange={(e) => onSelect(reminder.id, e.target.checked)}
          />
        )}
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 flex-wrap">
            <Badge variant={STATUS_VARIANT[reminder.status]}>
              {STATUS_LABELS[reminder.status]}
            </Badge>
            <Badge variant={LEVEL_VARIANT[reminder.level]}>
              {LEVEL_LABELS[reminder.level]}
            </Badge>
            {reminder.needs_contact_info === 1 && (
              <Badge variant="danger">Sans contact</Badge>
            )}
            <span className="text-xs text-[var(--color-text-muted)]">
              {reminder.client_id}
            </span>
          </div>
          <p className="mt-1.5 font-medium text-sm truncate">{reminder.subject}</p>
          {reminder.contact_email && (
            <p className="text-xs text-[var(--color-text-muted)] mt-0.5">
              → {reminder.contact_name || reminder.contact_email}{" "}
              <span className="opacity-60">({reminder.contact_email})</span>
            </p>
          )}
        </div>
        <div className="flex items-center gap-2 shrink-0">
          <button
            onClick={() => setExpanded((v) => !v)}
            className="text-xs text-[var(--color-text-muted)] hover:text-white px-2 py-1 rounded border border-white/10 hover:border-white/20"
          >
            {expanded ? "Réduire" : "Voir"}
          </button>
          {isActionable && (
            <>
              <button
                onClick={handleApprove}
                disabled={isPending}
                className="text-xs px-2 py-1 rounded border border-emerald-500/30 bg-emerald-500/10 text-emerald-300 hover:bg-emerald-500/20 disabled:opacity-50"
              >
                Approuver
              </button>
              <button
                onClick={handleSkip}
                disabled={isPending}
                className="text-xs px-2 py-1 rounded border border-white/10 text-[var(--color-text-muted)] hover:bg-white/5 disabled:opacity-50"
              >
                Ignorer
              </button>
            </>
          )}
        </div>
      </div>

      {/* Expanded body */}
      {expanded && (
        <div className="px-4 pb-4 border-t border-[var(--color-border)] pt-3 space-y-3">
          {editing ? (
            <div className="space-y-2">
              <textarea
                className="w-full bg-[var(--color-bg)] border border-[var(--color-border)] rounded p-3 text-sm font-mono resize-y min-h-[160px] focus:outline-none focus:border-blue-500/50"
                value={editBody}
                onChange={(e) => setEditBody(e.target.value)}
              />
              <div className="flex gap-2">
                <button
                  onClick={handleSaveEdit}
                  disabled={isPending}
                  className="text-xs px-3 py-1.5 rounded bg-blue-500/20 border border-blue-500/30 text-blue-300 hover:bg-blue-500/30 disabled:opacity-50"
                >
                  Sauvegarder & approuver
                </button>
                <button
                  onClick={() => setEditing(false)}
                  className="text-xs px-3 py-1.5 rounded border border-white/10 text-[var(--color-text-muted)] hover:bg-white/5"
                >
                  Annuler
                </button>
              </div>
            </div>
          ) : (
            <div className="space-y-2">
              <pre className="text-xs whitespace-pre-wrap font-mono bg-[var(--color-bg)] rounded p-3 border border-[var(--color-border)]">
                {reminder.body_final || reminder.body_draft}
              </pre>
              {isActionable && (
                <button
                  onClick={() => setEditing(true)}
                  className="text-xs px-2 py-1 rounded border border-white/10 text-[var(--color-text-muted)] hover:bg-white/5"
                >
                  Modifier le brouillon
                </button>
              )}
            </div>
          )}
          {feedback && (
            <p
              className={`text-xs ${
                feedback.startsWith("✗") ? "text-red-400" : "text-emerald-400"
              }`}
            >
              {feedback}
            </p>
          )}
          {reminder.error_message && (
            <p className="text-xs text-red-400">Erreur : {reminder.error_message}</p>
          )}
          {reminder.sent_at && (
            <p className="text-xs text-[var(--color-text-muted)]">
              Envoyée le {reminder.sent_at}
            </p>
          )}
        </div>
      )}
    </div>
  );
}

export function ReminderList({
  reminders,
  cabinetId,
}: {
  reminders: ReminderRow[];
  cabinetId: string;
}) {
  const [selected, setSelected] = useState<Set<number>>(new Set());
  const [batchFeedback, setBatchFeedback] = useState<string | null>(null);
  const [isPending, startTransition] = useTransition();

  const actionable = reminders.filter((r) =>
    ["pending", "approved"].includes(r.status)
  );

  function toggleSelect(id: number, v: boolean) {
    setSelected((prev) => {
      const next = new Set(prev);
      v ? next.add(id) : next.delete(id);
      return next;
    });
  }

  function selectAll() {
    setSelected(new Set(actionable.map((r) => r.id)));
  }

  function clearSelection() {
    setSelected(new Set());
  }

  function handleBatchApprove() {
    const ids = [...selected].join(",");
    const fd = new FormData();
    fd.set("cabinet_id", cabinetId);
    fd.set("ids", ids);
    startTransition(async () => {
      const res = await batchApproveReminders(fd);
      setBatchFeedback(
        res.ok
          ? `✓ ${res.count} relance(s) approuvée(s)`
          : `✓ ${res.count} approuvées — ✗ ${res.error}`
      );
      clearSelection();
    });
  }

  return (
    <div className="space-y-3">
      {/* Batch toolbar */}
      {actionable.length > 0 && (
        <div className="flex items-center gap-3 text-sm">
          <button
            onClick={selectAll}
            className="text-[var(--color-text-muted)] hover:text-white"
          >
            Tout sélectionner ({actionable.length})
          </button>
          {selected.size > 0 && (
            <>
              <span className="text-[var(--color-text-muted)]">|</span>
              <span className="text-white">{selected.size} sélectionné(s)</span>
              <button
                onClick={handleBatchApprove}
                disabled={isPending}
                className="px-3 py-1 rounded bg-emerald-500/20 border border-emerald-500/30 text-emerald-300 text-xs hover:bg-emerald-500/30 disabled:opacity-50"
              >
                Approuver la sélection
              </button>
              <button
                onClick={clearSelection}
                className="text-xs text-[var(--color-text-muted)] hover:text-white"
              >
                Annuler
              </button>
            </>
          )}
          {batchFeedback && (
            <span
              className={`text-xs ${
                batchFeedback.startsWith("✗") ? "text-red-400" : "text-emerald-400"
              }`}
            >
              {batchFeedback}
            </span>
          )}
        </div>
      )}

      {/* Reminder rows */}
      {reminders.map((r) => (
        <ReminderRow
          key={r.id}
          reminder={r}
          cabinetId={cabinetId}
          selected={selected.has(r.id)}
          onSelect={toggleSelect}
        />
      ))}
    </div>
  );
}
