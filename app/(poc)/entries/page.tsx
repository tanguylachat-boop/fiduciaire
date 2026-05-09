import Link from "next/link";
import { CheckCircle2, FileText, AlertTriangle, XCircle } from "lucide-react";
import {
  countAccountingEntries,
  listAccountingEntries,
  listClients,
  type EntryFilters as DbFilters,
  type EntryRow,
  type EntryState,
} from "@/lib/db-poc";
import { Card, CardHeader, CardTitle } from "@/components/ui/Card";
import { Badge } from "@/components/ui/Badge";
import { EntryFilters } from "@/components/poc/EntryFilters";

export const dynamic = "force-dynamic";

const fmtCHF = new Intl.NumberFormat("fr-CH", {
  style: "currency",
  currency: "CHF",
  minimumFractionDigits: 2,
});

const fmtDate = (iso: string) =>
  iso
    ? new Date(iso + "T00:00:00").toLocaleDateString("fr-CH", {
        day: "2-digit",
        month: "2-digit",
        year: "numeric",
      })
    : "—";

function stateBadge(state: EntryState) {
  if (state === "proposed")
    return <Badge variant="info">Proposé</Badge>;
  if (state === "validated")
    return <Badge variant="success">Validé</Badge>;
  return <Badge variant="danger">Rejeté</Badge>;
}

function confidenceBadge(c: number) {
  const pct = Math.round(c * 100);
  if (c >= 0.85)
    return <Badge variant="success">{pct}%</Badge>;
  if (c >= 0.7)
    return <Badge variant="info">{pct}%</Badge>;
  return <Badge variant="warning">{pct}%</Badge>;
}

export default async function EntriesListPage({
  searchParams,
}: {
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}) {
  const sp = await searchParams;
  const clients = listClients();
  const activeClient =
    pickString(sp.client) ||
    clients[0]?.client_id ||
    "cabinet-pilote-01";

  const stateRaw = pickString(sp.state);
  const state: EntryState | undefined =
    stateRaw === "proposed" || stateRaw === "validated" || stateRaw === "rejected"
      ? stateRaw
      : undefined;
  const confidenceMin = pickNumber(sp.conf);
  const amountMin = pickNumber(sp.amount_min);
  const amountMax = pickNumber(sp.amount_max);
  const offset = pickNumber(sp.offset) ?? 0;
  const limit = 50;

  const filters: DbFilters = {
    clientId: activeClient,
    state,
    confidenceMin,
    amountMin,
    amountMax,
    offset,
    limit,
  };

  const total = countAccountingEntries({ clientId: activeClient, state });
  const entries = listAccountingEntries(filters);

  // KPI mandant courant
  const summary = clients.find((c) => c.client_id === activeClient);

  return (
    <div className="mx-auto max-w-7xl px-6 py-8 lg:px-10 lg:py-10">
      <header className="mb-6 flex items-center justify-between">
        <div>
          <div className="flex items-center gap-2 text-xs text-[var(--color-text-dim)]">
            <Link href="/review" className="hover:text-[var(--color-text)]">
              Review
            </Link>
            <span>·</span>
            <span>Écritures comptables</span>
          </div>
          <h1 className="mt-1 text-2xl font-semibold tracking-tight">
            Validation des écritures
          </h1>
        </div>
        <div className="flex items-center gap-2">
          <Badge variant="muted">
            <FileText size={12} />
            {total} en {state ?? "tous états"}
          </Badge>
          {summary && (
            <>
              <Badge variant="info">{summary.n_proposed} proposées</Badge>
              <Badge variant="success">{summary.n_validated} validées</Badge>
              {summary.n_rejected > 0 && (
                <Badge variant="danger">{summary.n_rejected} rejetées</Badge>
              )}
            </>
          )}
        </div>
      </header>

      <div className="mb-4">
        <EntryFilters
          clients={clients}
          activeClient={activeClient}
          activeState={state ?? "any"}
          activeConfidenceMin={confidenceMin?.toString() ?? "any"}
          activeAmountMin={amountMin?.toString() ?? ""}
          activeAmountMax={amountMax?.toString() ?? ""}
        />
      </div>

      <Card>
        <CardHeader>
          <CardTitle>
            {entries.length} écritures —{" "}
            <span className="font-mono text-[var(--color-text-muted)]">
              {activeClient}
            </span>
          </CardTitle>
          <div className="flex items-center gap-2 text-xs text-[var(--color-text-dim)]">
            {offset > 0 && (
              <Link
                href={`/entries?${rebuildQuery(sp, "offset", String(Math.max(0, offset - limit)))}`}
                className="hover:text-[var(--color-text)]"
              >
                ← précédent
              </Link>
            )}
            {entries.length === limit && (
              <Link
                href={`/entries?${rebuildQuery(sp, "offset", String(offset + limit))}`}
                className="hover:text-[var(--color-text)]"
              >
                suivant →
              </Link>
            )}
          </div>
        </CardHeader>

        {entries.length === 0 ? (
          <div className="flex flex-col items-center gap-3 px-5 py-12 text-center">
            <AlertTriangle
              size={28}
              className="text-[var(--color-text-dim)]"
            />
            <p className="text-sm text-[var(--color-text-muted)]">
              Aucune écriture pour ces filtres.
            </p>
            <p className="text-xs text-[var(--color-text-dim)]">
              Lance le pipeline POC sur les docs de{" "}
              <code>data/inbox/</code> puis le proposer pour générer des
              écritures.
            </p>
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-[var(--color-border)] text-left text-xs font-medium uppercase tracking-wider text-[var(--color-text-dim)]">
                  <th className="px-5 py-3">Date</th>
                  <th className="px-5 py-3">Document</th>
                  <th className="px-5 py-3">Compte débit</th>
                  <th className="px-5 py-3">Compte crédit</th>
                  <th className="px-5 py-3">TVA</th>
                  <th className="px-5 py-3 text-right">Montant CHF</th>
                  <th className="px-5 py-3 text-right">Confiance</th>
                  <th className="px-5 py-3">État</th>
                  <th className="px-5 py-3" />
                </tr>
              </thead>
              <tbody>
                {entries.map((e: EntryRow) => (
                  <tr
                    key={e.id}
                    className="border-b border-[var(--color-border)]/60 transition-colors hover:bg-white/[0.02]"
                  >
                    <td className="px-5 py-3 font-mono text-xs text-[var(--color-text-muted)]">
                      {fmtDate(e.date)}
                    </td>
                    <td className="px-5 py-3">
                      <span className="font-mono text-xs text-[var(--color-text)]">
                        {e.doc_filename ?? `doc#${e.source_document_id}`}
                      </span>
                    </td>
                    <td className="px-5 py-3 font-mono">{e.debit_account}</td>
                    <td className="px-5 py-3 font-mono">{e.credit_account}</td>
                    <td className="px-5 py-3">
                      <Badge variant="muted">{e.vat_code}</Badge>
                    </td>
                    <td className="px-5 py-3 text-right font-mono tabular-nums">
                      {fmtCHF.format(e.amount_chf)}
                    </td>
                    <td className="px-5 py-3 text-right">
                      {confidenceBadge(
                        Math.min(e.confidence_account, e.confidence_vat),
                      )}
                    </td>
                    <td className="px-5 py-3">{stateBadge(e.state)}</td>
                    <td className="px-5 py-3">
                      <Link
                        href={`/entries/${e.id}?client=${encodeURIComponent(activeClient)}`}
                        className="inline-flex items-center gap-1 text-xs text-[var(--color-accent)] hover:underline"
                      >
                        ouvrir
                        <CheckCircle2 size={12} />
                      </Link>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>

      <p className="mt-6 text-center text-[11px] text-[var(--color-text-dim)]">
        100 % local · Sprint 0a · pas de push Bexio · isolation multi-mandant
        stricte
      </p>
    </div>
  );
}

function pickString(v: string | string[] | undefined): string | undefined {
  if (Array.isArray(v)) return v[0];
  return v && v.length > 0 ? v : undefined;
}

function pickNumber(v: string | string[] | undefined): number | undefined {
  const s = pickString(v);
  if (s === undefined) return undefined;
  const n = Number(s);
  return Number.isFinite(n) ? n : undefined;
}

function rebuildQuery(
  sp: Record<string, string | string[] | undefined>,
  key: string,
  value: string,
): string {
  const out = new URLSearchParams();
  for (const [k, v] of Object.entries(sp)) {
    const s = pickString(v);
    if (s !== undefined) out.set(k, s);
  }
  out.set(key, value);
  return out.toString();
}

// Suppress unused import for icon if eslint complains.
void XCircle;
