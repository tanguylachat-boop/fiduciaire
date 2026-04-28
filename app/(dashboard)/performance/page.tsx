import { PageHeader } from "@/components/PageHeader";
import { Card, CardBody, CardHeader, CardTitle } from "@/components/ui/Card";
import { Badge } from "@/components/ui/Badge";
import { AgentLevelDot } from "@/components/ui/AgentLevelDot";
import { AccuracyChart } from "@/components/AccuracyChart";
import { cn, levelColor } from "@/lib/utils";
import {
  MOCK_PERFORMANCE,
  MOCK_ACCURACY_HISTORY,
  MOCK_ACTIONS,
  GLOBAL_ACCURACY,
  GLOBAL_LEVEL,
} from "@/lib/mock-data";
import { levelLabel, taskLabel } from "@/lib/labels";

const globalLevelDescription: Record<"rouge" | "orange" | "vert", string> = {
  rouge: "L'agent commet trop d'erreurs — supervision manuelle recommandée.",
  orange: "L'agent progresse — continuez à valider pour l'entraîner.",
  vert: "L'agent opère en quasi-autonomie — validation légère suffit.",
};

export default function PerformancePage() {
  const corrections = MOCK_ACTIONS.filter(
    (a) => a.status === "valide" || a.confidence < 0.9,
  ).slice(0, 6);

  return (
    <>
      <PageHeader
        title="Performance de l'agent"
        subtitle="Suivi du scoring et de l'apprentissage"
        actions={<AgentLevelDot level={GLOBAL_LEVEL} label={levelLabel[GLOBAL_LEVEL]} />}
      />

      <div className="space-y-6 p-8">
        <Card>
          <CardBody className="flex items-center justify-between gap-6">
            <div className="flex items-center gap-6">
              <div
                className={cn(
                  "flex h-24 w-24 items-center justify-center rounded-full text-2xl font-bold",
                  levelColor(GLOBAL_LEVEL).bg,
                  levelColor(GLOBAL_LEVEL).text,
                )}
              >
                {GLOBAL_ACCURACY.toFixed(0)}%
              </div>
              <div>
                <div className="text-xs uppercase tracking-wider text-[var(--color-text-muted)]">
                  Score global de l'agent
                </div>
                <div
                  className={cn(
                    "mt-1 text-lg font-semibold",
                    levelColor(GLOBAL_LEVEL).text,
                  )}
                >
                  Niveau {levelLabel[GLOBAL_LEVEL]}
                </div>
                <p className="mt-1 max-w-md text-sm text-[var(--color-text-muted)]">
                  {globalLevelDescription[GLOBAL_LEVEL]}
                </p>
              </div>
            </div>
            <div className="grid grid-cols-3 gap-4 text-right">
              <div className="min-w-[80px]">
                <div className="text-xs text-[var(--color-text-muted)]">Rouge</div>
                <div className="mt-0.5 text-sm text-[var(--color-text-dim)]">&lt; 50%</div>
              </div>
              <div className="min-w-[80px]">
                <div className="text-xs text-[var(--color-text-muted)]">Orange</div>
                <div className="mt-0.5 text-sm text-[var(--color-text-dim)]">50 – 95%</div>
              </div>
              <div className="min-w-[80px]">
                <div className="text-xs text-[var(--color-text-muted)]">Vert</div>
                <div className="mt-0.5 text-sm text-[var(--color-text-dim)]">≥ 95%</div>
              </div>
            </div>
          </CardBody>
        </Card>

        <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
          {MOCK_PERFORMANCE.map((p) => {
            const c = levelColor(p.level);
            return (
              <Card key={p.id}>
                <CardBody>
                  <div className="flex items-center justify-between">
                    <div className="text-xs font-medium text-[var(--color-text-muted)]">
                      {taskLabel[p.task_type]}
                    </div>
                    <AgentLevelDot level={p.level} label={levelLabel[p.level]} size="sm" />
                  </div>
                  <div className={cn("mt-3 text-3xl font-semibold tracking-tight", c.text)}>
                    {p.accuracy.toFixed(1)}%
                  </div>
                  <div className="mt-2 flex justify-between text-xs text-[var(--color-text-muted)]">
                    <span>{p.correct_actions} / {p.total_actions} actions</span>
                    <span>30 derniers jours</span>
                  </div>
                  <div className="mt-3 h-1.5 w-full rounded-full bg-white/5">
                    <div
                      className={cn("h-full rounded-full", c.dot)}
                      style={{ width: `${p.accuracy}%` }}
                    />
                  </div>
                </CardBody>
              </Card>
            );
          })}
        </div>

        <Card>
          <CardHeader>
            <div>
              <CardTitle>Courbe de progression</CardTitle>
              <p className="mt-0.5 text-xs text-[var(--color-text-muted)]">
                L'agent apprend de chaque correction du fiduciaire
              </p>
            </div>
            <Badge variant="info">30 jours</Badge>
          </CardHeader>
          <CardBody>
            <AccuracyChart data={MOCK_ACCURACY_HISTORY} />
          </CardBody>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>Apprentissage récent</CardTitle>
            <Badge variant="muted">{corrections.length} événements</Badge>
          </CardHeader>
          <div className="divide-y divide-[var(--color-border)]">
            {corrections.map((a) => (
              <div key={a.id} className="flex items-start justify-between gap-4 px-5 py-3.5">
                <div className="flex-1">
                  <div className="text-sm">{a.description}</div>
                  <div className="mt-0.5 text-xs text-[var(--color-text-muted)]">
                    {a.action_type} · confiance {(a.confidence * 100).toFixed(0)}%
                  </div>
                </div>
                <Badge variant={a.status === "valide" ? "success" : "info"}>
                  {a.status === "valide" ? "Corrigé par fiduciaire" : "Auto"}
                </Badge>
              </div>
            ))}
          </div>
        </Card>
      </div>
    </>
  );
}
