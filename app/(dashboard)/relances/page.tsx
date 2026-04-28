import { Send, Edit3, X } from "lucide-react";
import { PageHeader } from "@/components/PageHeader";
import { Card, CardBody, CardHeader, CardTitle } from "@/components/ui/Card";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { ReminderTimeline } from "@/components/ReminderTimeline";
import { formatCHF, formatDate } from "@/lib/utils";
import { MOCK_INVOICES } from "@/lib/mock-data";
import { invoiceStatusLabel, invoiceStatusVariant } from "@/lib/labels";

export default function RelancesPage() {
  const active = MOCK_INVOICES.filter(
    (i) => i.status !== "payee" && i.status !== "contentieux",
  );
  const archived = MOCK_INVOICES.filter(
    (i) => i.status === "payee" || i.status === "contentieux",
  );

  const nextReminder = active.find((i) => i.next_reminder_preview);

  const today = new Date().toISOString().slice(0, 10);
  const overdue = (due: string) => due < today;
  const daysDiff = (due: string) => {
    const ms = new Date(today).getTime() - new Date(due).getTime();
    return Math.floor(ms / (1000 * 60 * 60 * 24));
  };

  const totalPending = active.reduce((sum, i) => sum + i.amount, 0);

  return (
    <>
      <PageHeader
        title="Relances factures"
        subtitle={`${active.length} factures à suivre · ${formatCHF(totalPending)} en attente`}
      />

      <div className="grid grid-cols-1 gap-6 p-8 lg:grid-cols-3">
        <div className="space-y-6 lg:col-span-2">
          <Card>
            <CardHeader>
              <div className="flex items-center gap-2">
                <CardTitle>Factures en cours</CardTitle>
                <Badge variant="warning">{active.length}</Badge>
              </div>
              <Button variant="secondary" size="sm">Nouvelle facture</Button>
            </CardHeader>
            <div className="divide-y divide-[var(--color-border)]">
              {active.map((inv) => {
                const late = overdue(inv.due_date);
                const days = daysDiff(inv.due_date);
                return (
                  <div key={inv.id} className="px-5 py-4">
                    <div className="flex items-start justify-between gap-4">
                      <div className="min-w-0 flex-1">
                        <div className="flex items-center gap-2">
                          <span className="font-medium">{inv.client_name}</span>
                          <Badge variant={invoiceStatusVariant[inv.status]}>
                            {invoiceStatusLabel[inv.status]}
                          </Badge>
                        </div>
                        <div className="mt-0.5 flex items-center gap-3 text-xs text-[var(--color-text-muted)]">
                          <span className="font-mono">{inv.invoice_number}</span>
                          <span>·</span>
                          <span>
                            Échéance {formatDate(inv.due_date)}
                            {late && (
                              <span className="ml-1.5 text-red-400">
                                (+{days}j de retard)
                              </span>
                            )}
                          </span>
                        </div>
                      </div>
                      <div className="text-right">
                        <div className="text-lg font-semibold tracking-tight">
                          {formatCHF(inv.amount)}
                        </div>
                        {inv.last_reminder_at && (
                          <div className="mt-0.5 text-xs text-[var(--color-text-dim)]">
                            Dernière relance : {formatDate(inv.last_reminder_at)}
                          </div>
                        )}
                      </div>
                    </div>
                    <div className="mt-3">
                      <ReminderTimeline status={inv.status} />
                    </div>
                  </div>
                );
              })}
            </div>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle>Archives</CardTitle>
              <Badge variant="muted">{archived.length}</Badge>
            </CardHeader>
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-[var(--color-border)] text-left text-xs text-[var(--color-text-muted)]">
                  <th className="px-5 py-3 font-medium">Client</th>
                  <th className="px-5 py-3 font-medium">Facture</th>
                  <th className="px-5 py-3 text-right font-medium">Montant</th>
                  <th className="px-5 py-3 font-medium">Statut</th>
                </tr>
              </thead>
              <tbody>
                {archived.map((inv) => (
                  <tr key={inv.id} className="border-b border-[var(--color-border)] last:border-b-0">
                    <td className="px-5 py-3 font-medium">{inv.client_name}</td>
                    <td className="px-5 py-3 font-mono text-xs text-[var(--color-text-muted)]">
                      {inv.invoice_number}
                    </td>
                    <td className="px-5 py-3 text-right">{formatCHF(inv.amount)}</td>
                    <td className="px-5 py-3">
                      <Badge variant={invoiceStatusVariant[inv.status]}>
                        {invoiceStatusLabel[inv.status]}
                      </Badge>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </Card>
        </div>

        <div className="space-y-4">
          {nextReminder && (
            <Card>
              <CardHeader>
                <CardTitle>Prochaine relance</CardTitle>
                <Badge variant="info">IA</Badge>
              </CardHeader>
              <CardBody className="space-y-4">
                <div>
                  <div className="text-xs text-[var(--color-text-muted)]">Destinataire</div>
                  <div className="mt-0.5 font-medium">{nextReminder.client_name}</div>
                  <div className="mt-0.5 text-xs text-[var(--color-text-muted)]">
                    Facture {nextReminder.invoice_number} ·{" "}
                    {formatCHF(nextReminder.amount)}
                  </div>
                </div>

                <div>
                  <div className="text-xs text-[var(--color-text-muted)]">
                    Aperçu de l'email
                  </div>
                  <div className="mt-1 rounded-md border border-[var(--color-border)] bg-[var(--color-bg-elevated)] p-3 text-xs leading-relaxed whitespace-pre-wrap text-[var(--color-text-muted)]">
                    {nextReminder.next_reminder_preview}
                  </div>
                </div>

                <div className="space-y-2">
                  <Button variant="primary" className="w-full justify-center">
                    <Send size={14} /> Envoyer maintenant
                  </Button>
                  <Button variant="secondary" className="w-full justify-center">
                    <Edit3 size={14} /> Modifier
                  </Button>
                  <Button variant="ghost" className="w-full justify-center">
                    <X size={14} /> Annuler
                  </Button>
                </div>
              </CardBody>
            </Card>
          )}

          <Card>
            <CardHeader>
              <CardTitle>Automatisation</CardTitle>
            </CardHeader>
            <CardBody className="space-y-3 text-xs text-[var(--color-text-muted)]">
              <div className="flex items-center justify-between">
                <span>Relance 1 (auto si confiance ≥ 95%)</span>
                <Badge variant="success">Activée</Badge>
              </div>
              <div className="flex items-center justify-between">
                <span>Relance 2 (validation requise)</span>
                <Badge variant="info">Semi-auto</Badge>
              </div>
              <div className="flex items-center justify-between">
                <span>Relance 3 / Contentieux</span>
                <Badge variant="warning">Manuelle</Badge>
              </div>
            </CardBody>
          </Card>
        </div>
      </div>
    </>
  );
}
