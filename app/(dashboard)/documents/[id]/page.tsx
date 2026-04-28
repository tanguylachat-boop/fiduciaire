import { notFound } from "next/navigation";
import Link from "next/link";
import {
  ArrowLeft,
  Check,
  Edit3,
  X,
  Paperclip,
  Mail,
  Calendar,
} from "lucide-react";
import { PageHeader } from "@/components/PageHeader";
import { Card, CardBody, CardHeader, CardTitle } from "@/components/ui/Card";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { formatCHF, formatDate } from "@/lib/utils";
import { MOCK_DOCUMENTS, MOCK_EXTRACTIONS, CABINET } from "@/lib/mock-data";
import {
  categoryLabel,
  urgencyLabel,
  urgencyVariant,
  statusLabel,
  statusVariant,
} from "@/lib/labels";

export default async function DocumentDetailPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  const doc = MOCK_DOCUMENTS.find((d) => d.id === id);
  if (!doc) return notFound();

  const extraction = MOCK_EXTRACTIONS.find((e) => e.document_id === id);
  const compteDebit = extraction
    ? CABINET.plan_comptes.find((c) => c.code === extraction.suggested_entry.compte_debit)
    : null;
  const compteCredit = extraction
    ? CABINET.plan_comptes.find((c) => c.code === extraction.suggested_entry.compte_credit)
    : null;

  return (
    <>
      <PageHeader
        title={doc.subject}
        subtitle={`Document ${doc.id}`}
        actions={
          <Link
            href="/documents"
            className="flex items-center gap-1.5 text-xs text-[var(--color-text-muted)] hover:text-[var(--color-text)]"
          >
            <ArrowLeft size={14} /> Retour
          </Link>
        }
      />

      <div className="grid grid-cols-1 gap-6 p-8 lg:grid-cols-3">
        <div className="space-y-4 lg:col-span-2">
          <Card>
            <CardHeader>
              <CardTitle>Email reçu</CardTitle>
              <div className="flex gap-2">
                <Badge variant="muted">{categoryLabel[doc.category]}</Badge>
                <Badge variant={urgencyVariant[doc.urgency]}>
                  Urgence {urgencyLabel[doc.urgency]}
                </Badge>
                <Badge variant={statusVariant[doc.status]}>
                  {statusLabel[doc.status]}
                </Badge>
              </div>
            </CardHeader>
            <CardBody className="space-y-4">
              <div className="grid grid-cols-2 gap-4 text-sm">
                <div>
                  <div className="flex items-center gap-1.5 text-xs text-[var(--color-text-muted)]">
                    <Mail size={12} /> Expéditeur
                  </div>
                  <div className="mt-1">{doc.source_email}</div>
                </div>
                <div>
                  <div className="flex items-center gap-1.5 text-xs text-[var(--color-text-muted)]">
                    <Calendar size={12} /> Reçu le
                  </div>
                  <div className="mt-1">
                    {formatDate(doc.created_at, {
                      day: "2-digit",
                      month: "long",
                      year: "numeric",
                      hour: "2-digit",
                      minute: "2-digit",
                    })}
                  </div>
                </div>
              </div>

              <div>
                <div className="text-xs text-[var(--color-text-muted)]">Aperçu</div>
                <p className="mt-1 text-sm leading-relaxed">{doc.body_preview}</p>
              </div>

              {doc.attachments.length > 0 && (
                <div>
                  <div className="text-xs text-[var(--color-text-muted)]">
                    Pièces jointes ({doc.attachments.length})
                  </div>
                  <ul className="mt-2 space-y-1.5">
                    {doc.attachments.map((a, i) => (
                      <li
                        key={i}
                        className="flex items-center justify-between rounded-md border border-[var(--color-border)] bg-[var(--color-bg-elevated)] px-3 py-2 text-sm"
                      >
                        <div className="flex items-center gap-2">
                          <Paperclip size={13} className="text-[var(--color-text-muted)]" />
                          <span>{a.filename}</span>
                        </div>
                        <span className="text-xs text-[var(--color-text-muted)]">
                          {(a.size / 1024).toFixed(0)} KB
                        </span>
                      </li>
                    ))}
                  </ul>
                </div>
              )}
            </CardBody>
          </Card>

          {extraction && (
            <Card>
              <CardHeader>
                <CardTitle>Données extraites par l'IA</CardTitle>
                <Badge variant="info">
                  Confiance {(extraction.ai_confidence * 100).toFixed(0)}%
                </Badge>
              </CardHeader>
              <CardBody>
                <dl className="grid grid-cols-2 gap-x-6 gap-y-3 text-sm">
                  <div>
                    <dt className="text-xs text-[var(--color-text-muted)]">Montant</dt>
                    <dd className="mt-0.5 font-medium">
                      {formatCHF(extraction.extracted_data.montant)}
                    </dd>
                  </div>
                  <div>
                    <dt className="text-xs text-[var(--color-text-muted)]">Date</dt>
                    <dd className="mt-0.5">{formatDate(extraction.extracted_data.date)}</dd>
                  </div>
                  <div>
                    <dt className="text-xs text-[var(--color-text-muted)]">
                      {extraction.extracted_data.fournisseur ? "Fournisseur" : "Client"}
                    </dt>
                    <dd className="mt-0.5">
                      {extraction.extracted_data.fournisseur ??
                        extraction.extracted_data.client}
                    </dd>
                  </div>
                  <div>
                    <dt className="text-xs text-[var(--color-text-muted)]">
                      N° de facture
                    </dt>
                    <dd className="mt-0.5 font-mono text-xs">
                      {extraction.extracted_data.numero_facture}
                    </dd>
                  </div>
                  <div>
                    <dt className="text-xs text-[var(--color-text-muted)]">TVA</dt>
                    <dd className="mt-0.5">{extraction.extracted_data.tva}%</dd>
                  </div>
                  <div className="col-span-2">
                    <dt className="text-xs text-[var(--color-text-muted)]">
                      Description
                    </dt>
                    <dd className="mt-0.5">{extraction.extracted_data.description}</dd>
                  </div>
                </dl>
              </CardBody>
            </Card>
          )}

          {extraction && compteDebit && compteCredit && (
            <Card>
              <CardHeader>
                <CardTitle>Écriture comptable suggérée</CardTitle>
                <Badge variant="warning">En attente de validation</Badge>
              </CardHeader>
              <CardBody>
                <table className="w-full text-sm">
                  <thead>
                    <tr className="border-b border-[var(--color-border)] text-left text-xs text-[var(--color-text-muted)]">
                      <th className="pb-2 font-medium">Compte</th>
                      <th className="pb-2 font-medium">Libellé</th>
                      <th className="pb-2 text-right font-medium">Débit</th>
                      <th className="pb-2 text-right font-medium">Crédit</th>
                    </tr>
                  </thead>
                  <tbody>
                    <tr className="border-b border-[var(--color-border)]">
                      <td className="py-3">
                        <div className="font-mono text-xs font-medium">{compteDebit.code}</div>
                        <div className="text-xs text-[var(--color-text-muted)]">{compteDebit.label}</div>
                      </td>
                      <td className="py-3">{extraction.suggested_entry.libelle}</td>
                      <td className="py-3 text-right font-medium">
                        {formatCHF(extraction.suggested_entry.montant)}
                      </td>
                      <td className="py-3 text-right text-[var(--color-text-dim)]">—</td>
                    </tr>
                    <tr>
                      <td className="py-3">
                        <div className="font-mono text-xs font-medium">{compteCredit.code}</div>
                        <div className="text-xs text-[var(--color-text-muted)]">{compteCredit.label}</div>
                      </td>
                      <td className="py-3">{extraction.suggested_entry.libelle}</td>
                      <td className="py-3 text-right text-[var(--color-text-dim)]">—</td>
                      <td className="py-3 text-right font-medium">
                        {formatCHF(extraction.suggested_entry.montant)}
                      </td>
                    </tr>
                  </tbody>
                </table>
              </CardBody>
            </Card>
          )}
        </div>

        <div className="space-y-4">
          <Card>
            <CardHeader>
              <CardTitle>Actions</CardTitle>
            </CardHeader>
            <CardBody className="space-y-2">
              <Button variant="success" className="w-full justify-start">
                <Check size={14} /> Valider l'extraction
              </Button>
              <Button variant="secondary" className="w-full justify-start">
                <Edit3 size={14} /> Corriger
              </Button>
              <Button variant="danger" className="w-full justify-start">
                <X size={14} /> Rejeter
              </Button>
            </CardBody>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle>Analyse IA</CardTitle>
            </CardHeader>
            <CardBody>
              <div className="space-y-2 text-xs text-[var(--color-text-muted)]">
                <div className="flex justify-between">
                  <span>Confiance triage</span>
                  <span className="text-[var(--color-text)]">
                    {(doc.ai_confidence * 100).toFixed(0)}%
                  </span>
                </div>
                {extraction && (
                  <div className="flex justify-between">
                    <span>Confiance extraction</span>
                    <span className="text-[var(--color-text)]">
                      {(extraction.ai_confidence * 100).toFixed(0)}%
                    </span>
                  </div>
                )}
                <div className="flex justify-between">
                  <span>Modèle</span>
                  <span className="text-[var(--color-text)]">Claude Sonnet 4.6</span>
                </div>
                <div className="flex justify-between">
                  <span>Latence</span>
                  <span className="text-[var(--color-text)]">1.8s</span>
                </div>
              </div>
            </CardBody>
          </Card>
        </div>
      </div>
    </>
  );
}
