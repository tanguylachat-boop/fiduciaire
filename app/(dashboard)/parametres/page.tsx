import { Copy, Plus } from "lucide-react";
import { PageHeader } from "@/components/PageHeader";
import { Card, CardBody, CardHeader, CardTitle } from "@/components/ui/Card";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { CABINET } from "@/lib/mock-data";

const rules = [
  { id: 1, label: "Factures > 10'000 CHF", action: "Marquer en urgence haute", active: true },
  { id: 2, label: "Email de docs@afc.admin.ch", action: "Catégorie « Document fiscal »", active: true },
  { id: 3, label: "Note de frais > 500 CHF", action: "Demander validation manuelle", active: true },
  { id: 4, label: "Facture échue depuis 7 jours", action: "Relance 1 automatique si confiance ≥ 95%", active: true },
  { id: 5, label: "Email d'un domaine en liste noire", action: "Classer en spam", active: false },
];

export default function ParametresPage() {
  return (
    <>
      <PageHeader title="Paramètres" subtitle="Configuration du cabinet et de l'agent IA" />

      <div className="grid grid-cols-1 gap-6 p-8 lg:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle>Informations du cabinet</CardTitle>
          </CardHeader>
          <CardBody className="space-y-4">
            <Field label="Nom du cabinet" defaultValue={CABINET.name} />
            <Field label="Ville" defaultValue={CABINET.ville} />
            <Field label="Adresse" defaultValue="Rue du Bourg 22, 1003 Lausanne" />
            <Field label="IDE" defaultValue="CHE-123.456.789" />
            <div>
              <label className="text-xs font-medium text-[var(--color-text-muted)]">
                Logo
              </label>
              <div className="mt-1.5 flex h-24 items-center justify-center rounded-md border border-dashed border-[var(--color-border-strong)] bg-[var(--color-bg-elevated)] text-xs text-[var(--color-text-dim)]">
                Glissez un fichier ici (SVG, PNG, max 2MB)
              </div>
            </div>
          </CardBody>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>Adresse email de réception</CardTitle>
            <Badge variant="success">Active</Badge>
          </CardHeader>
          <CardBody className="space-y-4">
            <div>
              <label className="text-xs font-medium text-[var(--color-text-muted)]">
                Toutes les pièces envoyées à cette adresse sont traitées par l'agent
              </label>
              <div className="mt-1.5 flex items-center gap-2">
                <input
                  type="text"
                  value={CABINET.email}
                  readOnly
                  className="h-9 flex-1 rounded-md border border-[var(--color-border)] bg-[var(--color-bg-elevated)] px-3 font-mono text-sm"
                />
                <Button variant="secondary" size="md">
                  <Copy size={14} /> Copier
                </Button>
              </div>
            </div>
            <div className="rounded-md border border-blue-500/20 bg-blue-500/5 p-3 text-xs text-blue-300">
              💡 Donnez cette adresse à vos clients et à vos fournisseurs : l'agent
              tri, catégorise et extrait les données automatiquement.
            </div>
            <Field label="Domaine personnalisé (optionnel)" defaultValue="" placeholder="docs@moncabinet.ch" />
          </CardBody>
        </Card>

        <Card className="lg:col-span-2">
          <CardHeader>
            <div>
              <CardTitle>Règles personnalisées</CardTitle>
              <p className="mt-0.5 text-xs text-[var(--color-text-muted)]">
                L'agent applique ces règles avant le modèle IA
              </p>
            </div>
            <Button variant="secondary" size="sm">
              <Plus size={13} /> Ajouter une règle
            </Button>
          </CardHeader>
          <div className="divide-y divide-[var(--color-border)]">
            {rules.map((r) => (
              <div key={r.id} className="flex items-center justify-between px-5 py-3.5">
                <div>
                  <div className="text-sm font-medium">
                    Si : <span className="text-[var(--color-accent)]">{r.label}</span>
                  </div>
                  <div className="mt-0.5 text-xs text-[var(--color-text-muted)]">
                    Alors : {r.action}
                  </div>
                </div>
                <div className="flex items-center gap-3">
                  <Badge variant={r.active ? "success" : "muted"}>
                    {r.active ? "Active" : "Désactivée"}
                  </Badge>
                  <label className="relative inline-flex cursor-pointer items-center">
                    <input type="checkbox" defaultChecked={r.active} className="peer sr-only" />
                    <div className="h-5 w-9 rounded-full bg-[var(--color-border-strong)] peer-checked:bg-[var(--color-accent)] after:absolute after:left-0.5 after:top-0.5 after:h-4 after:w-4 after:rounded-full after:bg-white after:transition-all peer-checked:after:translate-x-4" />
                  </label>
                </div>
              </div>
            ))}
          </div>
        </Card>

        <Card className="lg:col-span-2">
          <CardHeader>
            <div>
              <CardTitle>Plan comptable</CardTitle>
              <p className="mt-0.5 text-xs text-[var(--color-text-muted)]">
                Plan utilisé par l'agent pour suggérer les écritures
              </p>
            </div>
            <Button variant="secondary" size="sm">Importer CSV</Button>
          </CardHeader>
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-[var(--color-border)] text-left text-xs text-[var(--color-text-muted)]">
                <th className="px-5 py-3 font-medium w-32">Compte</th>
                <th className="px-5 py-3 font-medium">Libellé</th>
              </tr>
            </thead>
            <tbody>
              {CABINET.plan_comptes.map((c) => (
                <tr key={c.code} className="border-b border-[var(--color-border)] last:border-b-0">
                  <td className="px-5 py-3 font-mono text-xs">{c.code}</td>
                  <td className="px-5 py-3">{c.label}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </Card>
      </div>
    </>
  );
}

function Field({
  label,
  defaultValue,
  placeholder,
}: {
  label: string;
  defaultValue?: string;
  placeholder?: string;
}) {
  return (
    <div>
      <label className="text-xs font-medium text-[var(--color-text-muted)]">{label}</label>
      <input
        type="text"
        defaultValue={defaultValue}
        placeholder={placeholder}
        className="mt-1.5 h-9 w-full rounded-md border border-[var(--color-border)] bg-[var(--color-bg-elevated)] px-3 text-sm placeholder:text-[var(--color-text-dim)] focus:border-[var(--color-accent)] focus:outline-none"
      />
    </div>
  );
}
