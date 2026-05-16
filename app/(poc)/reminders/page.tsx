import Link from "next/link";
import { Mail, AlertCircle, CheckCircle2, Send, UserX } from "lucide-react";
import {
  listReminders,
  getReminderStats,
  listReminderCabinets,
} from "@/lib/db-poc-reminders";
import { Card, CardBody } from "@/components/ui/Card";
import { Badge } from "@/components/ui/Badge";
import { ReminderList } from "@/components/poc/ReminderList";

export const dynamic = "force-dynamic";

function pickString(v: string | string[] | undefined): string | undefined {
  if (Array.isArray(v)) return v[0];
  return v && v.length > 0 ? v : undefined;
}

const LEVEL_LABELS: Record<string, string> = {
  polite: "1ère relance",
  firm: "2ème relance",
  escalation: "Escalade",
};

const STATUS_VARIANT: Record<
  string,
  "default" | "success" | "warning" | "danger" | "info" | "muted"
> = {
  pending: "warning",
  approved: "info",
  sent: "success",
  skipped: "muted",
  failed: "danger",
};

export default async function RemindersPage({
  searchParams,
}: {
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}) {
  const sp = await searchParams;
  const cabinets = listReminderCabinets();
  const activeCabinet =
    pickString(sp.client) || cabinets[0]?.cabinet_id || "pilote-jura-01";
  const filterStatus = pickString(sp.status) || "";

  const stats = getReminderStats(activeCabinet);
  const reminders = listReminders(activeCabinet, {
    status: filterStatus || undefined,
    limit: 200,
  });

  const pendingCount = stats.pending + stats.approved;

  return (
    <div className="p-6 space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-semibold flex items-center gap-2">
            <Mail className="h-6 w-6 text-blue-400" />
            Relances clients
          </h1>
          <p className="text-sm text-[var(--color-text-muted)] mt-1">
            Brouillons générés par IA · validation humaine obligatoire avant envoi
          </p>
        </div>
        {pendingCount > 0 && (
          <Badge variant="warning">{pendingCount} à traiter</Badge>
        )}
      </div>

      {/* Mandant tabs */}
      {cabinets.length > 1 && (
        <div className="flex gap-2 flex-wrap">
          {cabinets.map((c) => (
            <Link
              key={c.cabinet_id}
              href={`/reminders?client=${c.cabinet_id}`}
              className={`px-3 py-1.5 rounded-md text-sm border transition-colors ${
                c.cabinet_id === activeCabinet
                  ? "bg-blue-500/20 border-blue-500/40 text-blue-300"
                  : "border-white/10 text-[var(--color-text-muted)] hover:border-white/20"
              }`}
            >
              {c.cabinet_id}
            </Link>
          ))}
        </div>
      )}

      {/* Stats */}
      <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-3">
        {[
          { label: "En attente", value: stats.pending, icon: AlertCircle, variant: "warning" as const },
          { label: "Approuvées", value: stats.approved, icon: CheckCircle2, variant: "info" as const },
          { label: "Envoyées", value: stats.sent, icon: Send, variant: "success" as const },
          { label: "Ignorées", value: stats.skipped, icon: null, variant: "muted" as const },
          { label: "Échouées", value: stats.failed, icon: null, variant: "danger" as const },
          { label: "Sans contact", value: stats.needs_contact, icon: UserX, variant: "warning" as const },
        ].map(({ label, value, icon: Icon, variant }) => (
          <Card key={label} className="text-center">
            <CardBody className="py-3">
              {Icon && <Icon className="h-4 w-4 mx-auto mb-1 opacity-60" />}
              <div className="text-xl font-bold">{value}</div>
              <div className="text-xs text-[var(--color-text-muted)]">{label}</div>
            </CardBody>
          </Card>
        ))}
      </div>

      {/* Filters */}
      <div className="flex gap-2 flex-wrap text-sm">
        {["", "pending", "approved", "sent", "skipped", "failed"].map((s) => {
          const label =
            s === ""
              ? "Toutes"
              : s === "pending"
              ? "En attente"
              : s === "approved"
              ? "Approuvées"
              : s === "sent"
              ? "Envoyées"
              : s === "skipped"
              ? "Ignorées"
              : "Échouées";
          const active = filterStatus === s;
          return (
            <Link
              key={s}
              href={`/reminders?client=${activeCabinet}${s ? `&status=${s}` : ""}`}
              className={`px-3 py-1 rounded-full border transition-colors ${
                active
                  ? "bg-white/10 border-white/20 text-white"
                  : "border-white/10 text-[var(--color-text-muted)] hover:border-white/20"
              }`}
            >
              {label}
            </Link>
          );
        })}
      </div>

      {/* List */}
      {reminders.length === 0 ? (
        <div className="text-center py-16 text-[var(--color-text-muted)]">
          <Mail className="h-10 w-10 mx-auto mb-3 opacity-30" />
          <p>Aucune relance{filterStatus ? ` avec le filtre « ${filterStatus} »` : ""}.</p>
          <p className="text-xs mt-1">
            Lancez <code>generate_reminders()</code> depuis le worker Python pour en créer.
          </p>
        </div>
      ) : (
        <ReminderList
          reminders={reminders}
          cabinetId={activeCabinet}
        />
      )}
    </div>
  );
}
