import Link from "next/link";
import { notFound } from "next/navigation";
import { ChevronLeft } from "lucide-react";
import {
  getAccountingEntry,
  listEntryHistory,
  listClients,
  type EntryRow,
} from "@/lib/db-poc";
import { EntryEditor, type EditorEntry } from "@/components/poc/EntryEditor";
import { Card, CardHeader, CardTitle } from "@/components/ui/Card";
import { Badge } from "@/components/ui/Badge";

export const dynamic = "force-dynamic";

export default async function EntryDetailPage({
  params,
  searchParams,
}: {
  params: Promise<{ id: string }>;
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}) {
  const { id: idStr } = await params;
  const sp = await searchParams;
  const id = Number(idStr);
  if (!Number.isInteger(id) || id <= 0) notFound();

  const clients = listClients();
  const clientId =
    pickString(sp.client) ||
    clients[0]?.client_id ||
    "cabinet-pilote-01";

  const entry = getAccountingEntry(id, clientId);
  if (!entry) notFound();

  const history = listEntryHistory(id, clientId);
  const sources = parseSources(entry.sources_json);

  const editorEntry: EditorEntry = {
    id: entry.id,
    client_id: entry.client_id,
    state: entry.state,
    date: entry.date,
    debit_account: entry.debit_account,
    credit_account: entry.credit_account,
    amount_chf: entry.amount_chf,
    vat_code: entry.vat_code,
    vat_amount: entry.vat_amount,
    description: entry.description,
    confidence_account: entry.confidence_account,
    confidence_vat: entry.confidence_vat,
    reasoning: entry.reasoning,
    source_account: sources.account,
    source_vat: sources.vat_code,
  };

  return (
    <div className="mx-auto max-w-[1600px] px-4 py-6 lg:px-6 lg:py-8">
      <header className="mb-4 flex items-center justify-between">
        <Link
          href={`/entries?client=${encodeURIComponent(clientId)}`}
          className="inline-flex items-center gap-1 text-xs text-[var(--color-text-muted)] hover:text-[var(--color-text)]"
        >
          <ChevronLeft size={14} />
          Retour à la liste
        </Link>
        <div className="text-[11px] text-[var(--color-text-dim)]">
          Mandant{" "}
          <span className="font-mono text-[var(--color-text-muted)]">
            {clientId}
          </span>
        </div>
      </header>

      {/* 2 colonnes responsive : PDF gauche, éditeur droite. */}
      <div className="grid h-[calc(100vh-12rem)] grid-cols-1 gap-4 lg:grid-cols-2">
        <Card className="flex flex-col overflow-hidden">
          <CardHeader>
            <CardTitle>Document source</CardTitle>
            <Badge variant="muted">
              {entry.doc_filename ?? `doc#${entry.source_document_id}`}
            </Badge>
          </CardHeader>
          <div className="flex-1 bg-[var(--color-bg)]">
            <PdfPane
              docId={entry.source_document_id}
              clientId={clientId}
              filename={entry.doc_filename}
            />
          </div>
        </Card>

        <Card className="flex flex-col overflow-hidden">
          <CardHeader>
            <CardTitle>Proposition d'écriture</CardTitle>
            <Badge variant="info">Sprint 0a · cache local</Badge>
          </CardHeader>
          <div className="flex-1 overflow-y-auto p-5">
            <EntryEditor entry={editorEntry} />
          </div>
        </Card>
      </div>

      {history.length > 0 && (
        <section className="mt-6">
          <Card>
            <CardHeader>
              <CardTitle>Historique des transitions</CardTitle>
              <Badge variant="muted">{history.length} entrées</Badge>
            </CardHeader>
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-[var(--color-border)] text-left text-xs font-medium uppercase tracking-wider text-[var(--color-text-dim)]">
                    <th className="px-5 py-3">Quand</th>
                    <th className="px-5 py-3">De</th>
                    <th className="px-5 py-3">Vers</th>
                    <th className="px-5 py-3">Utilisateur</th>
                    <th className="px-5 py-3">Raison</th>
                  </tr>
                </thead>
                <tbody>
                  {history.map((h) => (
                    <tr
                      key={h.id}
                      className="border-b border-[var(--color-border)]/60"
                    >
                      <td className="px-5 py-3 font-mono text-xs text-[var(--color-text-muted)]">
                        {h.changed_at}
                      </td>
                      <td className="px-5 py-3 font-mono text-xs">
                        {h.from_state}
                      </td>
                      <td className="px-5 py-3 font-mono text-xs">
                        {h.to_state}
                      </td>
                      <td className="px-5 py-3 text-xs">
                        {h.user_id ?? "—"}
                      </td>
                      <td className="px-5 py-3 text-xs text-[var(--color-text-muted)]">
                        {h.reason ?? "—"}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </Card>
        </section>
      )}
    </div>
  );
}

function PdfPane({
  docId,
  clientId,
  filename,
}: {
  docId: number;
  clientId: string;
  filename: string | null;
}) {
  const isPdf =
    filename === null || filename.toLowerCase().endsWith(".pdf");
  const pdfUrl = `/entries/pdf/${docId}?client=${encodeURIComponent(clientId)}`;
  if (!isPdf) {
    return (
      <div className="flex h-full items-center justify-center px-5 py-10 text-center">
        <p className="text-sm text-[var(--color-text-muted)]">
          Ce document n'est pas un PDF — viewer non disponible en Sprint 0a.
          <br />
          <span className="font-mono text-xs text-[var(--color-text-dim)]">
            {filename}
          </span>
        </p>
      </div>
    );
  }
  return (
    <iframe
      src={pdfUrl}
      title={`Document ${docId}`}
      className="h-full w-full border-0"
    />
  );
}

function pickString(v: string | string[] | undefined): string | undefined {
  if (Array.isArray(v)) return v[0];
  return v && v.length > 0 ? v : undefined;
}

function parseSources(json: string | null): {
  account?: string;
  vat_code?: string;
} {
  if (!json) return {};
  try {
    const parsed = JSON.parse(json) as Record<string, string>;
    return {
      account: parsed.account,
      vat_code: parsed.vat_code,
    };
  } catch {
    return {};
  }
}
