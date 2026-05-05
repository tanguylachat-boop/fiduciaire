import { Badge } from "@/components/ui/Badge";
import { formatCHF, formatDate } from "@/lib/utils";
import type { DocRow } from "@/lib/db-poc";
import { FileText, AlertTriangle, CheckCircle2 } from "lucide-react";

const typeLabel: Record<string, { label: string; variant: "info" | "muted" | "warning" | "success" }> = {
  facture_fournisseur: { label: "Facture fourn.", variant: "info" },
  note_frais: { label: "Note de frais", variant: "muted" },
  releve_bancaire: { label: "Relevé bancaire", variant: "muted" },
  document_fiscal: { label: "Document fiscal", variant: "warning" },
  contrat: { label: "Contrat", variant: "info" },
  courrier: { label: "Courrier", variant: "muted" },
  autre: { label: "Autre", variant: "muted" },
};

export function DocCard({ doc }: { doc: DocRow }) {
  const t = doc.type ? typeLabel[doc.type] ?? { label: doc.type, variant: "muted" as const } : null;
  const isOk = doc.status === "routed";
  const isReview = doc.status === "needs_review";
  const isFailed = doc.status === "failed";

  let parsed: { raisonnement?: string; model?: string } = {};
  try {
    if (doc.classification_json) parsed = JSON.parse(doc.classification_json);
  } catch {}

  return (
    <div className="rounded-lg border border-[var(--color-border)] bg-[var(--color-bg-card)] p-4">
      <div className="flex items-start justify-between gap-3">
        <div className="flex min-w-0 items-start gap-3">
          <div className="mt-0.5 rounded-md bg-white/5 p-2 text-[var(--color-text-muted)]">
            <FileText size={14} />
          </div>
          <div className="min-w-0">
            <p className="truncate text-sm font-medium text-[var(--color-text)]">
              {doc.original_filename}
            </p>
            <p className="mt-0.5 text-xs text-[var(--color-text-dim)]">
              ID #{doc.id} · {formatDate(doc.created_at)}
            </p>
          </div>
        </div>
        <div>
          {isOk && (
            <Badge variant="success">
              <CheckCircle2 size={11} /> Classé
            </Badge>
          )}
          {isReview && (
            <Badge variant="warning">
              <AlertTriangle size={11} /> Review
            </Badge>
          )}
          {isFailed && <Badge variant="danger">Échec</Badge>}
        </div>
      </div>

      <div className="mt-3 grid grid-cols-2 gap-x-4 gap-y-2 text-xs lg:grid-cols-4">
        <div>
          <div className="text-[var(--color-text-dim)]">Type</div>
          <div className="mt-0.5">
            {t ? <Badge variant={t.variant}>{t.label}</Badge> : <span className="text-[var(--color-text-muted)]">—</span>}
          </div>
        </div>
        <div>
          <div className="text-[var(--color-text-dim)]">Client</div>
          <div className="mt-0.5 truncate text-[var(--color-text)]">
            {doc.client_slug ?? <span className="text-[var(--color-text-muted)]">—</span>}
          </div>
        </div>
        <div>
          <div className="text-[var(--color-text-dim)]">Date</div>
          <div className="mt-0.5 text-[var(--color-text)]">
            {doc.doc_date ?? <span className="text-[var(--color-text-muted)]">—</span>}
          </div>
        </div>
        <div>
          <div className="text-[var(--color-text-dim)]">Montant</div>
          <div className="mt-0.5 font-medium text-[var(--color-text)]">
            {doc.montant_chf != null ? formatCHF(doc.montant_chf) : (
              <span className="text-[var(--color-text-muted)]">—</span>
            )}
          </div>
        </div>
      </div>

      {(isReview || isFailed) && doc.needs_review_reason && (
        <p className="mt-3 rounded-md border border-amber-500/20 bg-amber-500/5 px-3 py-2 text-xs text-amber-200/80">
          {doc.needs_review_reason}
        </p>
      )}

      {parsed.raisonnement && (
        <p className="mt-2 text-xs italic text-[var(--color-text-dim)]">
          “{parsed.raisonnement}”
        </p>
      )}
    </div>
  );
}
