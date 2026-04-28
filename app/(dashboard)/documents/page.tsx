import Link from "next/link";
import { Paperclip, Search } from "lucide-react";
import { PageHeader } from "@/components/PageHeader";
import { Card } from "@/components/ui/Card";
import { Badge } from "@/components/ui/Badge";
import { formatRelative } from "@/lib/utils";
import { MOCK_DOCUMENTS } from "@/lib/mock-data";
import {
  categoryLabel,
  urgencyLabel,
  urgencyVariant,
  statusLabel,
  statusVariant,
} from "@/lib/labels";

export default function DocumentsPage() {
  return (
    <>
      <PageHeader
        title="Documents"
        subtitle={`${MOCK_DOCUMENTS.length} documents reçus — triés et catégorisés par l'IA`}
      />

      <div className="p-8">
        <div className="mb-4 flex items-center gap-3">
          <div className="relative flex-1 max-w-md">
            <Search
              size={14}
              className="absolute left-3 top-1/2 -translate-y-1/2 text-[var(--color-text-dim)]"
            />
            <input
              type="text"
              placeholder="Rechercher par sujet, expéditeur, catégorie..."
              className="h-9 w-full rounded-md border border-[var(--color-border)] bg-[var(--color-bg-card)] pl-9 pr-3 text-sm placeholder:text-[var(--color-text-dim)] focus:border-[var(--color-accent)] focus:outline-none"
            />
          </div>
          <select className="h-9 rounded-md border border-[var(--color-border)] bg-[var(--color-bg-card)] px-3 text-sm focus:border-[var(--color-accent)] focus:outline-none">
            <option>Toutes catégories</option>
            <option>Facture fournisseur</option>
            <option>Note de frais</option>
            <option>Relevé bancaire</option>
            <option>Document fiscal</option>
            <option>Courrier</option>
            <option>Spam</option>
          </select>
          <select className="h-9 rounded-md border border-[var(--color-border)] bg-[var(--color-bg-card)] px-3 text-sm focus:border-[var(--color-accent)] focus:outline-none">
            <option>Tous statuts</option>
            <option>Nouveau</option>
            <option>Traité</option>
            <option>Validé</option>
            <option>Rejeté</option>
          </select>
        </div>

        <Card>
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-[var(--color-border)] text-left text-xs text-[var(--color-text-muted)]">
                <th className="px-5 py-3 font-medium">Sujet</th>
                <th className="px-5 py-3 font-medium">Expéditeur</th>
                <th className="px-5 py-3 font-medium">Catégorie</th>
                <th className="px-5 py-3 font-medium">Urgence</th>
                <th className="px-5 py-3 font-medium">Statut</th>
                <th className="px-5 py-3 font-medium">Confiance</th>
                <th className="px-5 py-3 font-medium">Reçu</th>
              </tr>
            </thead>
            <tbody>
              {MOCK_DOCUMENTS.map((d) => (
                <tr
                  key={d.id}
                  className="group border-b border-[var(--color-border)] last:border-b-0 hover:bg-white/[0.02]"
                >
                  <td className="px-5 py-3.5">
                    <Link
                      href={`/documents/${d.id}`}
                      className="flex items-start gap-2 group-hover:text-[var(--color-accent)]"
                    >
                      <div className="min-w-0">
                        <div className="truncate font-medium">{d.subject}</div>
                        <div className="mt-0.5 flex items-center gap-1.5 text-xs text-[var(--color-text-muted)]">
                          {d.attachments.length > 0 && (
                            <>
                              <Paperclip size={11} />
                              <span>{d.attachments.length}</span>
                              <span>·</span>
                            </>
                          )}
                          <span className="truncate">{d.body_preview.slice(0, 70)}…</span>
                        </div>
                      </div>
                    </Link>
                  </td>
                  <td className="px-5 py-3.5 text-[var(--color-text-muted)]">
                    {d.source_email}
                  </td>
                  <td className="px-5 py-3.5">
                    <Badge variant="muted">{categoryLabel[d.category]}</Badge>
                  </td>
                  <td className="px-5 py-3.5">
                    <Badge variant={urgencyVariant[d.urgency]}>
                      {urgencyLabel[d.urgency]}
                    </Badge>
                  </td>
                  <td className="px-5 py-3.5">
                    <Badge variant={statusVariant[d.status]}>
                      {statusLabel[d.status]}
                    </Badge>
                  </td>
                  <td className="px-5 py-3.5 text-[var(--color-text-muted)]">
                    {(d.ai_confidence * 100).toFixed(0)}%
                  </td>
                  <td className="px-5 py-3.5 text-[var(--color-text-muted)]">
                    {formatRelative(d.created_at)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </Card>
      </div>
    </>
  );
}
