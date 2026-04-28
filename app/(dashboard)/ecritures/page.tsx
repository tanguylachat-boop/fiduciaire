import { Check, Edit3, X } from "lucide-react";
import { PageHeader } from "@/components/PageHeader";
import { Card } from "@/components/ui/Card";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { formatCHF, formatDate } from "@/lib/utils";
import { MOCK_EXTRACTIONS, CABINET } from "@/lib/mock-data";
import { extractionStatusLabel, extractionStatusVariant } from "@/lib/labels";

export default function EcrituresPage() {
  const pending = MOCK_EXTRACTIONS.filter((e) => e.status === "en_attente");
  const processed = MOCK_EXTRACTIONS.filter((e) => e.status !== "en_attente");

  const comptes = new Map(CABINET.plan_comptes.map((c) => [c.code, c]));

  return (
    <>
      <PageHeader
        title="Écritures comptables"
        subtitle={`${pending.length} en attente de validation · ${processed.length} traitées`}
        actions={
          <>
            <Button variant="secondary" size="sm">Exporter CSV</Button>
            <Button variant="primary" size="sm">Tout valider</Button>
          </>
        }
      />

      <div className="space-y-6 p-8">
        <Card>
          <div className="flex items-center justify-between border-b border-[var(--color-border)] px-5 py-4">
            <div className="flex items-center gap-2">
              <h2 className="text-sm font-semibold">En attente de validation</h2>
              <Badge variant="warning">{pending.length}</Badge>
            </div>
            <div className="text-xs text-[var(--color-text-muted)]">
              Chaque validation entraîne l'agent
            </div>
          </div>
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-[var(--color-border)] text-left text-xs text-[var(--color-text-muted)]">
                <th className="px-5 py-3 font-medium">Date</th>
                <th className="px-5 py-3 font-medium">Libellé</th>
                <th className="px-5 py-3 font-medium">Débit</th>
                <th className="px-5 py-3 font-medium">Crédit</th>
                <th className="px-5 py-3 text-right font-medium">Montant</th>
                <th className="px-5 py-3 font-medium">IA</th>
                <th className="px-5 py-3 text-right font-medium">Actions</th>
              </tr>
            </thead>
            <tbody>
              {pending.map((e) => {
                const deb = comptes.get(e.suggested_entry.compte_debit);
                const cre = comptes.get(e.suggested_entry.compte_credit);
                return (
                  <tr
                    key={e.id}
                    className="border-b border-[var(--color-border)] last:border-b-0 hover:bg-white/[0.02]"
                  >
                    <td className="px-5 py-3.5 text-[var(--color-text-muted)]">
                      {formatDate(e.extracted_data.date)}
                    </td>
                    <td className="px-5 py-3.5">
                      <div className="font-medium">{e.suggested_entry.libelle}</div>
                      <div className="mt-0.5 text-xs text-[var(--color-text-muted)]">
                        {e.extracted_data.numero_facture}
                      </div>
                    </td>
                    <td className="px-5 py-3.5">
                      <div className="font-mono text-xs">{e.suggested_entry.compte_debit}</div>
                      <div className="text-xs text-[var(--color-text-muted)]">
                        {deb?.label}
                      </div>
                    </td>
                    <td className="px-5 py-3.5">
                      <div className="font-mono text-xs">{e.suggested_entry.compte_credit}</div>
                      <div className="text-xs text-[var(--color-text-muted)]">
                        {cre?.label}
                      </div>
                    </td>
                    <td className="px-5 py-3.5 text-right font-medium">
                      {formatCHF(e.suggested_entry.montant)}
                    </td>
                    <td className="px-5 py-3.5">
                      <Badge
                        variant={
                          e.ai_confidence >= 0.95
                            ? "success"
                            : e.ai_confidence >= 0.85
                              ? "warning"
                              : "danger"
                        }
                      >
                        {(e.ai_confidence * 100).toFixed(0)}%
                      </Badge>
                    </td>
                    <td className="px-5 py-3.5">
                      <div className="flex justify-end gap-1">
                        <button className="rounded-md p-1.5 text-emerald-400 hover:bg-emerald-500/10">
                          <Check size={14} />
                        </button>
                        <button className="rounded-md p-1.5 text-[var(--color-text-muted)] hover:bg-white/5 hover:text-[var(--color-text)]">
                          <Edit3 size={14} />
                        </button>
                        <button className="rounded-md p-1.5 text-red-400 hover:bg-red-500/10">
                          <X size={14} />
                        </button>
                      </div>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </Card>

        <Card>
          <div className="flex items-center justify-between border-b border-[var(--color-border)] px-5 py-4">
            <div className="flex items-center gap-2">
              <h2 className="text-sm font-semibold">Historique</h2>
              <Badge variant="muted">{processed.length}</Badge>
            </div>
          </div>
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-[var(--color-border)] text-left text-xs text-[var(--color-text-muted)]">
                <th className="px-5 py-3 font-medium">Date</th>
                <th className="px-5 py-3 font-medium">Libellé</th>
                <th className="px-5 py-3 font-medium">Comptes</th>
                <th className="px-5 py-3 text-right font-medium">Montant</th>
                <th className="px-5 py-3 font-medium">Statut</th>
              </tr>
            </thead>
            <tbody>
              {processed.map((e) => (
                <tr
                  key={e.id}
                  className="border-b border-[var(--color-border)] last:border-b-0 hover:bg-white/[0.02]"
                >
                  <td className="px-5 py-3.5 text-[var(--color-text-muted)]">
                    {formatDate(e.extracted_data.date)}
                  </td>
                  <td className="px-5 py-3.5">{e.suggested_entry.libelle}</td>
                  <td className="px-5 py-3.5 font-mono text-xs text-[var(--color-text-muted)]">
                    {e.suggested_entry.compte_debit} → {e.suggested_entry.compte_credit}
                  </td>
                  <td className="px-5 py-3.5 text-right font-medium">
                    {formatCHF(e.suggested_entry.montant)}
                  </td>
                  <td className="px-5 py-3.5">
                    <Badge variant={extractionStatusVariant[e.status]}>
                      {extractionStatusLabel[e.status]}
                    </Badge>
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
