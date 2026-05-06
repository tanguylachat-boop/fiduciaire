import {
  FileText,
  CheckCircle2,
  ShieldCheck,
  Cpu,
  Server,
  Lock,
  Inbox,
  ScanText,
  Sparkles,
  LayoutDashboard,
  ArrowRight,
} from "lucide-react";
import { Kpi } from "@/components/ui/Kpi";
import { Card, CardHeader, CardTitle, CardBody } from "@/components/ui/Card";
import { Badge } from "@/components/ui/Badge";

// Page de démo statique — données pré-chargées en dur, aucune dépendance runtime.
// Build full-static, pas de SQLite, pas de fetch, pas d'API. Sécurise la démo client.
export const dynamic = "force-static";

type Confidence = number;

type DemoDoc = {
  id: string;
  fichier: string;
  type: string;
  typeLabel: string;
  client: string | null;
  date: string;
  montant: number;
  confiance: Confidence;
};

const KPIS = [
  { label: "Type document", value: 95 },
  { label: "Client détecté", value: 92 },
  { label: "Date document", value: 88 },
  { label: "Montant CHF", value: 86 },
] as const;

const DOCS: DemoDoc[] = [
  {
    id: "01",
    fichier: "01_swisscom_qr.pdf",
    type: "facture_fournisseur",
    typeLabel: "Facture fournisseur",
    client: "Restaurant Le Rivage SA",
    date: "2024-03-12",
    montant: 287.0,
    confiance: 99,
  },
  {
    id: "02",
    fichier: "02_sig_alias.pdf",
    type: "charge_courante",
    typeLabel: "Charge courante",
    client: "Cabinet Tanguy Lachat",
    date: "2025-06-15",
    montant: 542.3,
    confiance: 96,
  },
  {
    id: "03",
    fichier: "03_fiscal_sarl.pdf",
    type: "bordereau_fiscal",
    typeLabel: "Bordereau fiscal",
    client: "Garage du Léman SARL",
    date: "2024-11-20",
    montant: 4250.0,
    confiance: 94,
  },
  {
    id: "04",
    fichier: "04_migros_inconnu.pdf",
    type: "inconnu",
    typeLabel: "Inconnu",
    client: null,
    date: "2025-01-08",
    montant: 87.4,
    confiance: 91,
  },
  {
    id: "05",
    fichier: "05_ubs_releve.pdf",
    type: "releve_bancaire",
    typeLabel: "Relevé bancaire",
    client: "Atelier Boillat",
    date: "2024-03-01",
    montant: 14250.0,
    confiance: 95,
  },
];

const fmtCHF = new Intl.NumberFormat("fr-CH", {
  style: "currency",
  currency: "CHF",
  minimumFractionDigits: 2,
});

const fmtDate = (iso: string) =>
  new Date(iso + "T00:00:00").toLocaleDateString("fr-CH", {
    day: "2-digit",
    month: "2-digit",
    year: "numeric",
  });

function confidenceTone(c: Confidence): "success" | "info" | "warning" {
  if (c >= 95) return "success";
  if (c >= 90) return "info";
  return "warning";
}

function typeTone(t: string): "success" | "info" | "warning" | "muted" {
  if (t === "inconnu") return "warning";
  if (t === "facture_fournisseur") return "info";
  if (t === "releve_bancaire") return "success";
  return "muted";
}

const PIPELINE_STEPS = [
  {
    icon: Inbox,
    title: "Drop folder",
    desc: "Watcher local sur dossier surveillé",
  },
  {
    icon: ScanText,
    title: "OCR + QR-bill",
    desc: "Extraction texte + lecture QR-facture suisse",
  },
  {
    icon: Sparkles,
    title: "Qwen 14B classify",
    desc: "Classification + extraction structurée",
  },
  {
    icon: LayoutDashboard,
    title: "Dashboard /review",
    desc: "Validation manuelle express comptable",
  },
] as const;

export default function ReviewDemoPage() {
  return (
    <div className="mx-auto max-w-7xl px-6 py-10 lg:px-10 lg:py-14">
      {/* HERO */}
      <section className="rounded-2xl border border-[var(--color-border)] bg-gradient-to-br from-[var(--color-bg-card)] to-[var(--color-bg-elevated)] px-8 py-10 lg:px-12 lg:py-14">
        <div className="flex flex-col gap-6 lg:flex-row lg:items-center lg:justify-between">
          <div className="max-w-3xl">
            <Badge variant="info" className="mb-4">
              <ShieldCheck size={12} />
              Démo cabinet fiduciaire — 2026
            </Badge>
            <h1 className="text-3xl font-semibold tracking-tight lg:text-4xl">
              Pipeline IA Documentaire
              <span className="block text-[var(--color-text-muted)]">
                Validation cabinet fiduciaire
              </span>
            </h1>
            <p className="mt-4 max-w-2xl text-sm leading-relaxed text-[var(--color-text-muted)] lg:text-base">
              100% local, données souveraines suisses, aucune fuite cloud. Le
              modèle tourne sur un Mac Mini déployé chez vous — vos documents
              ne quittent jamais le cabinet.
            </p>
          </div>
          <div className="flex flex-col items-start gap-3 lg:items-end">
            <div className="rounded-xl border border-emerald-500/30 bg-emerald-500/10 px-6 py-5 ring-1 ring-emerald-500/20">
              <div className="text-xs font-medium uppercase tracking-wider text-emerald-400/80">
                Précision validée
              </div>
              <div className="mt-1 flex items-baseline gap-2">
                <span className="text-5xl font-semibold tracking-tight text-emerald-400">
                  95%
                </span>
                <span className="text-sm text-emerald-400/70">
                  sur 5 typologies
                </span>
              </div>
            </div>
            <div className="text-xs text-[var(--color-text-dim)]">
              Bench V2 — corpus 20 docs, Qwen 14B Q4
            </div>
          </div>
        </div>
      </section>

      {/* KPI CARDS */}
      <section className="mt-8">
        <div className="mb-4 flex items-center justify-between">
          <h2 className="text-sm font-semibold tracking-tight text-[var(--color-text-muted)]">
            Précision par champ extrait
          </h2>
          <Badge variant="muted">5 typologies × 4 champs</Badge>
        </div>
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
          {KPIS.map((kpi) => (
            <Kpi
              key={kpi.label}
              label={kpi.label}
              value={`${kpi.value}%`}
              hint="précision moyenne"
              icon={CheckCircle2}
              accent={
                kpi.value >= 90
                  ? "success"
                  : kpi.value >= 85
                    ? "warning"
                    : "danger"
              }
            />
          ))}
        </div>
      </section>

      {/* TABLE */}
      <section className="mt-8">
        <Card>
          <CardHeader>
            <div>
              <CardTitle>Échantillon — corpus de validation</CardTitle>
              <p className="mt-0.5 text-xs text-[var(--color-text-muted)]">
                5 documents représentatifs, classification + extraction
                structurée
              </p>
            </div>
            <Badge variant="success">
              <span className="h-1.5 w-1.5 rounded-full bg-emerald-400" />
              Pipeline validé
            </Badge>
          </CardHeader>
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-[var(--color-border)] text-left text-xs font-medium uppercase tracking-wider text-[var(--color-text-dim)]">
                  <th className="px-5 py-3">Fichier</th>
                  <th className="px-5 py-3">Type détecté</th>
                  <th className="px-5 py-3">Client</th>
                  <th className="px-5 py-3">Date</th>
                  <th className="px-5 py-3 text-right">Montant CHF</th>
                  <th className="px-5 py-3 text-right">Confiance</th>
                </tr>
              </thead>
              <tbody>
                {DOCS.map((d) => (
                  <tr
                    key={d.id}
                    className="border-b border-[var(--color-border)]/60 transition-colors hover:bg-white/[0.02]"
                  >
                    <td className="px-5 py-4">
                      <div className="flex items-center gap-2.5">
                        <FileText
                          size={14}
                          className="text-[var(--color-text-dim)]"
                        />
                        <span className="font-mono text-xs text-[var(--color-text)]">
                          {d.fichier}
                        </span>
                      </div>
                    </td>
                    <td className="px-5 py-4">
                      <Badge variant={typeTone(d.type)}>{d.typeLabel}</Badge>
                    </td>
                    <td className="px-5 py-4 text-[var(--color-text)]">
                      {d.client ?? (
                        <span className="italic text-[var(--color-text-dim)]">
                          —
                        </span>
                      )}
                    </td>
                    <td className="px-5 py-4 font-mono text-xs text-[var(--color-text-muted)]">
                      {fmtDate(d.date)}
                    </td>
                    <td className="px-5 py-4 text-right font-mono tabular-nums">
                      {fmtCHF.format(d.montant)}
                    </td>
                    <td className="px-5 py-4 text-right">
                      <Badge variant={confidenceTone(d.confiance)}>
                        {d.confiance}%
                      </Badge>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Card>
      </section>

      {/* PIPELINE */}
      <section className="mt-8">
        <Card>
          <CardHeader>
            <div>
              <CardTitle>Pipeline de bout en bout</CardTitle>
              <p className="mt-0.5 text-xs text-[var(--color-text-muted)]">
                Du dossier surveillé au tableau de validation
              </p>
            </div>
            <Badge variant="info">4 étapes — 100% local</Badge>
          </CardHeader>
          <CardBody>
            <ol className="grid grid-cols-1 gap-3 lg:grid-cols-4">
              {PIPELINE_STEPS.map((step, i) => {
                const Icon = step.icon;
                return (
                  <li key={step.title} className="relative">
                    <div className="rounded-xl border border-[var(--color-border)] bg-[var(--color-bg-elevated)] p-5">
                      <div className="flex items-center gap-3">
                        <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-[var(--color-accent-dim)] text-[var(--color-accent)]">
                          <Icon size={18} />
                        </div>
                        <div className="text-xs font-medium uppercase tracking-wider text-[var(--color-text-dim)]">
                          Étape {i + 1}
                        </div>
                      </div>
                      <h3 className="mt-3 text-sm font-semibold">
                        {step.title}
                      </h3>
                      <p className="mt-1 text-xs leading-relaxed text-[var(--color-text-muted)]">
                        {step.desc}
                      </p>
                    </div>
                    {i < PIPELINE_STEPS.length - 1 && (
                      <ArrowRight
                        size={18}
                        className="absolute -right-3 top-1/2 hidden -translate-y-1/2 text-[var(--color-text-dim)] lg:block"
                        aria-hidden
                      />
                    )}
                  </li>
                );
              })}
            </ol>
          </CardBody>
        </Card>
      </section>

      {/* ARCHITECTURE */}
      <section className="mt-8 grid grid-cols-1 gap-4 lg:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle>Architecture déployée</CardTitle>
            <Badge variant="muted">On-premise</Badge>
          </CardHeader>
          <CardBody className="space-y-4">
            <ArchRow
              icon={Server}
              title="Mac Mini M4 Pro · 64 GB"
              desc="Boîtier silencieux déployé chez le client, alimentation 24/7"
            />
            <ArchRow
              icon={Cpu}
              title="Qwen 14B Q4 — modèle local"
              desc="Inférence sur Apple Silicon, pas de GPU cloud nécessaire"
            />
            <ArchRow
              icon={Lock}
              title="Aucune sortie réseau"
              desc="Les documents et résultats restent dans le LAN du cabinet"
            />
            <ArchRow
              icon={ShieldCheck}
              title="Pipeline open source"
              desc="Pas de vendor lock-in, code et modèles auditables"
            />
          </CardBody>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>Garanties cabinet</CardTitle>
            <Badge variant="success">Souveraineté suisse</Badge>
          </CardHeader>
          <CardBody>
            <ul className="space-y-3 text-sm">
              <Guarantee>
                Conformité <strong>nLPD</strong> et secret professionnel
                fiduciaire — données en clair jamais transmises.
              </Guarantee>
              <Guarantee>
                Validation humaine express : le comptable garde la main sur
                chaque pièce avant écriture.
              </Guarantee>
              <Guarantee>
                Modèle <strong>Qwen 14B Q4</strong> figé par version — résultats
                reproductibles, traçabilité complète.
              </Guarantee>
              <Guarantee>
                Sauvegarde locale chiffrée + export CSV/PDF natif vers Bexio,
                Banana, Sage.
              </Guarantee>
            </ul>
          </CardBody>
        </Card>
      </section>

      {/* FOOTER */}
      <footer className="mt-12 flex flex-col items-center justify-between gap-3 border-t border-[var(--color-border)] pt-6 text-xs text-[var(--color-text-dim)] sm:flex-row">
        <div className="flex items-center gap-3">
          <span className="font-semibold text-[var(--color-text-muted)]">
            LX Studio
          </span>
          <span aria-hidden>·</span>
          <span>Tanguy Lachat</span>
        </div>
        <a
          href="mailto:contact@lxstudio.ch"
          className="font-mono text-[var(--color-text-muted)] hover:text-[var(--color-text)]"
        >
          contact@lxstudio.ch
        </a>
      </footer>
    </div>
  );
}

function ArchRow({
  icon: Icon,
  title,
  desc,
}: {
  icon: React.ComponentType<{ size?: number; className?: string }>;
  title: string;
  desc: string;
}) {
  return (
    <div className="flex items-start gap-3">
      <div className="mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-white/5 text-[var(--color-text-muted)]">
        <Icon size={16} />
      </div>
      <div>
        <div className="text-sm font-medium">{title}</div>
        <div className="mt-0.5 text-xs leading-relaxed text-[var(--color-text-muted)]">
          {desc}
        </div>
      </div>
    </div>
  );
}

function Guarantee({ children }: { children: React.ReactNode }) {
  return (
    <li className="flex items-start gap-2.5 text-[var(--color-text-muted)]">
      <CheckCircle2
        size={16}
        className="mt-0.5 shrink-0 text-emerald-400"
        aria-hidden
      />
      <span>{children}</span>
    </li>
  );
}
