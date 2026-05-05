import {
  FileText,
  CheckCircle2,
  AlertTriangle,
  Timer,
} from "lucide-react";
import { PageHeader } from "@/components/PageHeader";
import { Kpi } from "@/components/ui/Kpi";
import { Card, CardHeader, CardTitle, CardBody } from "@/components/ui/Card";
import { Badge } from "@/components/ui/Badge";
import { VolumeChart } from "@/components/VolumeChart";
import { DocCard } from "@/components/poc/DocCard";
import { PocActivityFeed } from "@/components/poc/PocActivityFeed";
import { RefreshTimer } from "@/components/poc/RefreshTimer";
import {
  dbExists,
  getKpis,
  getVolumeLast7Days,
  listDocuments,
  listNeedsReview,
  listRecentActions,
} from "@/lib/db-poc";

// Pas de cache : on re-lit SQLite à chaque requête (RefreshTimer pousse 5s).
export const dynamic = "force-dynamic";
export const revalidate = 0;

export default async function ReviewPage() {
  const ready = dbExists();
  const kpis = ready
    ? getKpis()
    : { totalDocs: 0, routedDocs: 0, needsReviewCount: 0, failedCount: 0, precisionPct: 0, classifyLatencyMedianMs: null };
  const volume = getVolumeLast7Days();
  const allDocs = ready ? listDocuments(50) : [];
  const reviewDocs = ready ? listNeedsReview() : [];
  const actions = ready ? listRecentActions(24, 30) : [];

  const today = new Date();
  const subtitle = today.toLocaleDateString("fr-CH", {
    weekday: "long",
    day: "numeric",
    month: "long",
    year: "numeric",
  });

  const latencyLabel =
    kpis.classifyLatencyMedianMs != null
      ? `${(kpis.classifyLatencyMedianMs / 1000).toFixed(1)} s`
      : "—";

  return (
    <>
      <RefreshTimer intervalMs={5000} />
      <PageHeader
        title="Review POC — agent fiduciaire"
        subtitle={subtitle}
        actions={
          <Badge variant={ready ? "success" : "warning"}>
            <span
              className={`h-1.5 w-1.5 rounded-full ${ready ? "bg-emerald-400" : "bg-amber-400"}`}
            />
            {ready ? "DB connectée" : "DB vide — seed requise"}
          </Badge>
        }
      />

      <div className="p-8">
        {!ready && (
          <div className="mb-6 rounded-lg border border-amber-500/20 bg-amber-500/5 px-4 py-3 text-xs text-amber-200/80">
            La base SQLite{" "}
            <code className="rounded bg-black/30 px-1.5 py-0.5 font-mono">
              data/fiduciaire.sqlite
            </code>{" "}
            est vide. Lancez{" "}
            <code className="rounded bg-black/30 px-1.5 py-0.5 font-mono">
              cd worker && .venv/bin/python scripts/seed_db_from_bench.py
            </code>{" "}
            pour la peupler avec le dernier bench, ou démarrez le watcher.
          </div>
        )}

        <div className="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-4">
          <Kpi
            label="Documents traités"
            value={String(kpis.totalDocs)}
            hint="total cumulé"
            icon={FileText}
          />
          <Kpi
            label="Précision"
            value={`${kpis.precisionPct.toFixed(1)}%`}
            hint={`${kpis.routedDocs} classés / ${kpis.routedDocs + kpis.needsReviewCount + kpis.failedCount} décidés`}
            icon={CheckCircle2}
            accent={
              kpis.precisionPct >= 90
                ? "success"
                : kpis.precisionPct >= 80
                  ? "warning"
                  : "danger"
            }
          />
          <Kpi
            label="Latence médiane"
            value={latencyLabel}
            hint="classification LLM"
            icon={Timer}
          />
          <Kpi
            label="À valider"
            value={String(kpis.needsReviewCount)}
            hint={kpis.failedCount > 0 ? `${kpis.failedCount} en échec` : "queue review"}
            icon={AlertTriangle}
            accent={kpis.needsReviewCount > 0 ? "warning" : "default"}
          />
        </div>

        <div className="mt-6 grid grid-cols-1 gap-4 lg:grid-cols-3">
          <Card className="lg:col-span-2">
            <CardHeader>
              <div>
                <CardTitle>Volume 7 derniers jours</CardTitle>
                <p className="mt-0.5 text-xs text-[var(--color-text-muted)]">
                  Docs ingérés par jour
                </p>
              </div>
              <Badge variant="info">Refresh 5s</Badge>
            </CardHeader>
            <CardBody>
              <VolumeChart data={volume} />
            </CardBody>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle>Activité — 24h</CardTitle>
              <Badge variant="success">
                <span className="h-1.5 w-1.5 rounded-full bg-emerald-400" />
                Live
              </Badge>
            </CardHeader>
            <div className="max-h-[400px] overflow-y-auto">
              <PocActivityFeed actions={actions} />
            </div>
          </Card>
        </div>

        <Card className="mt-6">
          <CardHeader>
            <div>
              <CardTitle>Queue de validation</CardTitle>
              <p className="mt-0.5 text-xs text-[var(--color-text-muted)]">
                {reviewDocs.length} docs nécessitent une revue manuelle
              </p>
            </div>
            {reviewDocs.length > 0 && (
              <Badge variant="warning">{reviewDocs.length}</Badge>
            )}
          </CardHeader>
          <CardBody>
            {reviewDocs.length === 0 ? (
              <div className="py-8 text-center text-xs text-[var(--color-text-muted)]">
                {ready
                  ? "Aucun document en attente de review."
                  : "—"}
              </div>
            ) : (
              <div className="grid gap-3 lg:grid-cols-2">
                {reviewDocs.map((d) => (
                  <DocCard key={d.id} doc={d} />
                ))}
              </div>
            )}
          </CardBody>
        </Card>

        <Card className="mt-6">
          <CardHeader>
            <div>
              <CardTitle>Tous les documents récents</CardTitle>
              <p className="mt-0.5 text-xs text-[var(--color-text-muted)]">
                50 derniers ingérés
              </p>
            </div>
            <Badge variant="muted">{allDocs.length}</Badge>
          </CardHeader>
          <CardBody>
            {allDocs.length === 0 ? (
              <div className="py-8 text-center text-xs text-[var(--color-text-muted)]">
                {ready
                  ? "Aucun document. Démarrez le watcher ou seedez."
                  : "—"}
              </div>
            ) : (
              <div className="grid gap-3 lg:grid-cols-2">
                {allDocs.map((d) => (
                  <DocCard key={d.id} doc={d} />
                ))}
              </div>
            )}
          </CardBody>
        </Card>
      </div>
    </>
  );
}
