import {
  CheckCircle2,
  AlertTriangle,
  FileSearch,
  XCircle,
} from "lucide-react";
import { formatRelative } from "@/lib/utils";
import type { ActionRow } from "@/lib/db-poc";

const labels: Record<string, string> = {
  classify: "Classification",
  ocr: "OCR",
  qrbill: "Lecture QR-bill",
  ingest: "Ingestion",
  route: "Classement",
  rename: "Renommage",
};

export function PocActivityFeed({ actions }: { actions: ActionRow[] }) {
  if (actions.length === 0) {
    return (
      <div className="px-5 py-8 text-center text-xs text-[var(--color-text-muted)]">
        Aucune activité enregistrée. Lancez le worker ou seedez la DB depuis un bench.
      </div>
    );
  }
  return (
    <ul className="divide-y divide-[var(--color-border)]">
      {actions.map((a) => {
        const ok = a.ok === 1;
        const Icon = ok ? CheckCircle2 : a.error ? XCircle : AlertTriangle;
        const accent = ok
          ? "text-emerald-400 bg-emerald-500/10"
          : "text-red-400 bg-red-500/10";
        const labelTxt = labels[a.action] ?? a.action;
        const dur =
          a.duration_ms != null ? ` · ${(a.duration_ms / 1000).toFixed(1)} s` : "";
        return (
          <li
            key={a.id}
            className="flex items-start gap-3 px-5 py-3.5 fade-in"
          >
            <div className={`mt-0.5 rounded-md p-1.5 ${accent}`}>
              {ok ? <Icon size={14} /> : <FileSearch size={14} />}
            </div>
            <div className="min-w-0 flex-1">
              <p className="text-sm text-[var(--color-text)]">
                {labelTxt} doc #{a.document_id}
                {a.error ? ` — ${a.error.slice(0, 80)}` : ""}
              </p>
              <div className="mt-1 flex items-center gap-2 text-xs text-[var(--color-text-dim)]">
                <span>{formatRelative(a.created_at)}</span>
                <span>{dur}</span>
              </div>
            </div>
          </li>
        );
      })}
    </ul>
  );
}
