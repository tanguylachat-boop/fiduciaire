import {
  FileText,
  CheckCircle2,
  Send,
  Zap,
} from "lucide-react";
import { PageHeader } from "@/components/PageHeader";
import { Kpi } from "@/components/ui/Kpi";
import { Card, CardHeader, CardTitle, CardBody } from "@/components/ui/Card";
import { Badge } from "@/components/ui/Badge";
import { AgentLevelDot } from "@/components/ui/AgentLevelDot";
import { ActivityFeed } from "@/components/ActivityFeed";
import { VolumeChart } from "@/components/VolumeChart";
import {
  MOCK_DOCUMENTS,
  MOCK_EXTRACTIONS,
  MOCK_ACTIONS,
  MOCK_VOLUME_HISTORY,
  GLOBAL_ACCURACY,
  GLOBAL_LEVEL,
} from "@/lib/mock-data";

export default function DashboardPage() {
  const today = new Date();
  const todayIso = today.toISOString().slice(0, 10);
  const docsToday = MOCK_DOCUMENTS.filter((d) =>
    d.created_at.startsWith(todayIso),
  ).length;
  const pendingEntries = MOCK_EXTRACTIONS.filter(
    (e) => e.status === "en_attente",
  ).length;
  const remindersToday = MOCK_ACTIONS.filter(
    (a) =>
      a.action_type === "relance" && a.created_at.startsWith(todayIso),
  ).length;

  return (
    <>
      <PageHeader
        title="Tableau de bord"
        subtitle={`${today.toLocaleDateString("fr-CH", { weekday: "long", day: "numeric", month: "long", year: "numeric" })}`}
        actions={<AgentLevelDot level={GLOBAL_LEVEL} label={`Agent — ${GLOBAL_ACCURACY.toFixed(1)}%`} />}
      />

      <div className="p-8">
        <div className="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-4">
          <Kpi
            label="Documents traités aujourd'hui"
            value={String(docsToday)}
            hint="vs 6 hier"
            icon={FileText}
            trend={{ value: "+33%", direction: "up" }}
          />
          <Kpi
            label="Écritures en attente"
            value={String(pendingEntries)}
            hint="à valider"
            icon={CheckCircle2}
            accent="warning"
            trend={{ value: "3 urgentes", direction: "neutral" }}
          />
          <Kpi
            label="Relances envoyées"
            value={String(remindersToday)}
            hint="ce matin"
            icon={Send}
            trend={{ value: "2 auto", direction: "up" }}
          />
          <Kpi
            label="Précision agent"
            value={`${GLOBAL_ACCURACY.toFixed(1)}%`}
            hint={`niveau ${GLOBAL_LEVEL}`}
            icon={Zap}
            accent={GLOBAL_LEVEL === "vert" ? "success" : GLOBAL_LEVEL === "orange" ? "warning" : "danger"}
            trend={{ value: "+1.8 pts / 30j", direction: "up" }}
          />
        </div>

        <div className="mt-6 grid grid-cols-1 gap-4 lg:grid-cols-3">
          <Card className="lg:col-span-2">
            <CardHeader>
              <div>
                <CardTitle>Volume de documents traités</CardTitle>
                <p className="mt-0.5 text-xs text-[var(--color-text-muted)]">30 derniers jours</p>
              </div>
              <Badge variant="info">Temps réel</Badge>
            </CardHeader>
            <CardBody>
              <VolumeChart data={MOCK_VOLUME_HISTORY} />
            </CardBody>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle>Fil d'activité</CardTitle>
              <Badge variant="success">
                <span className="h-1.5 w-1.5 rounded-full bg-emerald-400" />
                Live
              </Badge>
            </CardHeader>
            <div className="max-h-[400px] overflow-y-auto">
              <ActivityFeed actions={MOCK_ACTIONS.slice(0, 8)} />
            </div>
          </Card>
        </div>
      </div>
    </>
  );
}
