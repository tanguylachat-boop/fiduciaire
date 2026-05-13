import Link from "next/link";
import {
  AlertTriangle,
  CheckCircle2,
  FileText,
  Landmark,
  Shield,
  XCircle,
} from "lucide-react";
import {
  getClientBankStats,
  getClientStats,
  listClientOpenAnomalies,
  listClientRecentAuditEvents,
  listClientRecentEntries,
} from "@/lib/db-poc-clients";
import { Card, CardBody, CardHeader, CardTitle } from "@/components/ui/Card";
import { Badge } from "@/components/ui/Badge";
import { AnomalyActions } from "@/components/poc/AnomalyActions";

export const dynamic = "force-dynamic";

const fmtCHF = new Intl.NumberFormat("fr-CH", {
  style: "currency",
  currency: "CHF",
  minimumFractionDigits: 2,
});

const fmtDate = (iso: string) =>
  iso
    ? new Date(iso.slice(0, 10) + "T00:00:00").toLocaleDateString("fr-CH", {
        day: "2-digit",
        month: "2-digit",
        year: "numeric",
      })
    : "—";

const fmtDateTime = (iso: string) =>
  iso
    ? new Date(iso).toLocaleString("fr-CH", {
        day: "2-digit",
        month: "2-digit",
        hour: "2-digit",
        minute: "2-digit",
      })
    : "—";

function severityBadge(sev: string) {
  if (sev === "error") return <Badge variant="danger">Erreur</Badge>;
  if (sev === "warning") return <Badge variant="warning">Warning</Badge>;
  return <Badge variant="info">Info</Badge>;
}

function stateBadge(state: string) {
  if (state === "validated") return <Badge variant="success">Validé</Badge>;
  if (state === "proposed") return <Badge variant="info">Proposé</Badge>;
  return <Badge variant="danger">Rejeté</Badge>;
}

function anomalyTypeLabel(type: string): string {
  const labels: Record<string, string> = {
    vat_no_evidence: "TVA sans justificatif",
    potential_duplicate: "Doublon possible",
    unpaid_invoice: "Facture impayée (proxy bexio_id)",
    unpaid_invoice_overdue: "Facture impayée > 60j",
    payment_without_invoice: "Paiement sans facture",
  };
  return labels[type] ?? type;
}

export default async function ClientPage({
  params,
}: {
  params: Promise<{ client_id: string }>;
}) {
  const { client_id } = await params;
  const clientId = decodeURIComponent(client_id);

  const stats = getClientStats(clientId);
  const entries = listClientRecentEntries(clientId, 10);
  const anomalies = listClientOpenAnomalies(clientId, 20);
  const auditEvents = listClientRecentAuditEvents(clientId, 5);
  const bankStats = getClientBankStats(clientId);

  return (
    <div className="mx-auto max-w-7xl px-6 py-8 lg:px-10 lg:py-10">
      {/* HEADER */}
      <header className="mb-6 flex items-start justify-between gap-4">
        <div>
          <div className="flex items-center gap-2 text-xs text-[var(--color-text-dim)]">
            <Link href="/entries" className="hover:text-[var(--color-text)]">
              Écritures
            </Link>
            <span>·</span>
            <span>Mandant</span>
          </div>
          <h1 className="mt-1 font-mono text-2xl font-semibold tracking-tight">
            {clientId}
          </h1>
          <p className="mt-1 text-xs text-[var(--color-text-dim)]">
            Vue par mandant — multi-tenant strict
          </p>
        </div>
        <div className="flex gap-2">
          <Link
            href={`/entries?client=${encodeURIComponent(clientId)}`}
            className="rounded-md border border-[var(--color-border)] px-3 py-1.5 text-xs hover:bg-white/[0.05]"
          >
            Voir toutes les écritures
          </Link>
        </div>
      </header>

      {/* STATS CARDS */}
      <div className="mb-6 grid grid-cols-2 gap-3 md:grid-cols-4">
        <StatCard
          label="Validées (mois)"
          value={`${stats.validated_count_month}`}
          sub={fmtCHF.format(stats.validated_amount_month)}
          icon={<CheckCircle2 size={14} />}
          tone="success"
        />
        <StatCard
          label="En attente"
          value={`${stats.proposed_count}`}
          sub={
            stats.rejected_count > 0
              ? `${stats.rejected_count} rejetées`
              : "à valider"
          }
          icon={<FileText size={14} />}
          tone="info"
        />
        <StatCard
          label="Anomalies"
          value={`${stats.anomalies_open_count}`}
          sub={stats.anomalies_open_count > 0 ? "open" : "aucune"}
          icon={<AlertTriangle size={14} />}
          tone={stats.anomalies_open_count > 0 ? "warning" : "muted"}
        />
        <StatCard
          label="Documents (mois)"
          value={`${stats.docs_count_month}`}
          sub="traités"
          icon={<FileText size={14} />}
          tone="muted"
        />
      </div>

      {/* ÉCRITURES RÉCENTES */}
      <Card className="mb-6">
        <CardHeader>
          <CardTitle>Écritures récentes (10 dernières)</CardTitle>
          <Link
            href={`/entries?client=${encodeURIComponent(clientId)}`}
            className="text-xs text-[var(--color-accent)] hover:underline"
          >
            Voir toutes →
          </Link>
        </CardHeader>
        {entries.length === 0 ? (
          <CardBody>
            <p className="text-sm text-[var(--color-text-dim)]">
              Aucune écriture pour ce mandant.
            </p>
          </CardBody>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-[var(--color-border)] text-left text-xs font-medium uppercase tracking-wider text-[var(--color-text-dim)]">
                  <th className="px-5 py-3">Date</th>
                  <th className="px-5 py-3">Document</th>
                  <th className="px-5 py-3">Description</th>
                  <th className="px-5 py-3 text-right">Montant CHF</th>
                  <th className="px-5 py-3">État</th>
                  <th className="px-5 py-3" />
                </tr>
              </thead>
              <tbody>
                {entries.map((e) => (
                  <tr
                    key={e.id}
                    className="border-b border-[var(--color-border)]/60 hover:bg-white/[0.02]"
                  >
                    <td className="px-5 py-3 font-mono text-xs text-[var(--color-text-muted)]">
                      {fmtDate(e.date)}
                    </td>
                    <td className="px-5 py-3 font-mono text-xs">
                      {e.doc_filename ?? `doc#${e.source_document_id}`}
                    </td>
                    <td className="px-5 py-3 text-xs">
                      {e.description}
                    </td>
                    <td className="px-5 py-3 text-right font-mono tabular-nums">
                      {fmtCHF.format(e.amount_chf)}
                    </td>
                    <td className="px-5 py-3">{stateBadge(e.state)}</td>
                    <td className="px-5 py-3">
                      <Link
                        href={`/entries/${e.id}?client=${encodeURIComponent(clientId)}`}
                        className="text-xs text-[var(--color-accent)] hover:underline"
                      >
                        ouvrir →
                      </Link>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>

      {/* ANOMALIES OPEN */}
      <Card className="mb-6">
        <CardHeader>
          <CardTitle>Anomalies à traiter ({anomalies.length})</CardTitle>
          <Badge variant={anomalies.length > 0 ? "warning" : "muted"}>
            <AlertTriangle size={12} />
            {anomalies.length} open
          </Badge>
        </CardHeader>
        {anomalies.length === 0 ? (
          <CardBody>
            <p className="text-sm text-[var(--color-text-dim)]">
              Aucune anomalie ouverte. 🎉
            </p>
          </CardBody>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-[var(--color-border)] text-left text-xs font-medium uppercase tracking-wider text-[var(--color-text-dim)]">
                  <th className="px-5 py-3">Détecté</th>
                  <th className="px-5 py-3">Type</th>
                  <th className="px-5 py-3">Sévérité</th>
                  <th className="px-5 py-3">Sujet</th>
                  <th className="px-5 py-3 text-right">Actions</th>
                </tr>
              </thead>
              <tbody>
                {anomalies.map((a) => (
                  <tr
                    key={a.id}
                    className="border-b border-[var(--color-border)]/60"
                  >
                    <td className="px-5 py-3 font-mono text-xs text-[var(--color-text-muted)]">
                      {fmtDateTime(a.detected_at)}
                    </td>
                    <td className="px-5 py-3 text-xs">
                      {anomalyTypeLabel(a.type)}
                    </td>
                    <td className="px-5 py-3">{severityBadge(a.severity)}</td>
                    <td className="px-5 py-3 font-mono text-xs">
                      {a.subject_entity_type}#{a.subject_entity_id}
                    </td>
                    <td className="px-5 py-3 text-right">
                      <AnomalyActions
                        anomalyId={a.id}
                        clientId={clientId}
                      />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>

      {/* RAPPROCHEMENT BANCAIRE + AUDIT */}
      <div className="grid gap-6 md:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle>Rapprochement bancaire</CardTitle>
            <Landmark size={14} className="text-[var(--color-text-dim)]" />
          </CardHeader>
          <CardBody>
            <div className="space-y-2 text-sm">
              <div className="flex justify-between">
                <span className="text-[var(--color-text-muted)]">
                  Transactions non matchées
                </span>
                <span className="font-mono">{bankStats.unmatched_count}</span>
              </div>
              <div className="flex justify-between">
                <span className="text-[var(--color-text-muted)]">
                  Montant total
                </span>
                <span className="font-mono">
                  {fmtCHF.format(bankStats.unmatched_amount_total)}
                </span>
              </div>
              <div className="flex justify-between">
                <span className="text-[var(--color-text-muted)]">
                  Déjà matchées
                </span>
                <span className="font-mono">{bankStats.matched_count}</span>
              </div>
            </div>
            <Link
              href={`/bank?client=${encodeURIComponent(clientId)}`}
              className="mt-4 inline-block text-xs text-[var(--color-accent)] hover:underline"
            >
              Voir détail rapprochement →
            </Link>
          </CardBody>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>Audit récent (5 derniers)</CardTitle>
            <Shield size={14} className="text-[var(--color-text-dim)]" />
          </CardHeader>
          {auditEvents.length === 0 ? (
            <CardBody>
              <p className="text-sm text-[var(--color-text-dim)]">
                Aucun événement.
              </p>
            </CardBody>
          ) : (
            <ul className="divide-y divide-[var(--color-border)]/60 px-5 py-2">
              {auditEvents.map((ev) => (
                <li key={ev.id} className="py-2 text-xs">
                  <div className="flex justify-between">
                    <span className="font-mono text-[var(--color-text-muted)]">
                      {fmtDateTime(ev.timestamp)}
                    </span>
                    <span className="text-[var(--color-text-dim)]">
                      {ev.user_id ?? "system"}
                    </span>
                  </div>
                  <div className="mt-1">
                    <Badge variant="muted">{ev.action}</Badge>
                    <span className="ml-2 font-mono text-[var(--color-text-muted)]">
                      {ev.entity_type}#{ev.entity_id}
                    </span>
                  </div>
                </li>
              ))}
            </ul>
          )}
          <div className="border-t border-[var(--color-border)] px-5 py-3">
            <Link
              href={`/audit?client=${encodeURIComponent(clientId)}`}
              className="text-xs text-[var(--color-accent)] hover:underline"
            >
              Voir tout l&apos;audit →
            </Link>
          </div>
        </Card>
      </div>

      <p className="mt-6 text-center text-[11px] text-[var(--color-text-dim)]">
        100 % local · Sprint 2 §3.10 · isolation multi-mandant stricte
      </p>
    </div>
  );
}

function StatCard({
  label,
  value,
  sub,
  icon,
  tone,
}: {
  label: string;
  value: string;
  sub?: string;
  icon: React.ReactNode;
  tone: "success" | "info" | "warning" | "muted";
}) {
  const toneClass = {
    success: "text-emerald-400",
    info: "text-sky-400",
    warning: "text-amber-400",
    muted: "text-[var(--color-text-dim)]",
  }[tone];
  return (
    <Card>
      <CardBody className="py-4">
        <div
          className={`mb-1 flex items-center gap-1.5 text-xs ${toneClass}`}
        >
          {icon}
          <span>{label}</span>
        </div>
        <p className="font-mono text-2xl font-semibold tabular-nums">
          {value}
        </p>
        {sub && (
          <p className="mt-1 text-xs text-[var(--color-text-dim)]">{sub}</p>
        )}
      </CardBody>
    </Card>
  );
}

void XCircle;
