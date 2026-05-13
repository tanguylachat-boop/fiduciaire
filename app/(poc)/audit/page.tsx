import Link from "next/link";
import { Shield, AlertTriangle, CheckCircle2 } from "lucide-react";
import {
  countAuditEvents,
  listAuditCabinets,
  listAuditEvents,
  verifyAuditChain,
  type AuditEventRow,
} from "@/lib/db-poc-audit";
import { Card, CardBody, CardHeader, CardTitle } from "@/components/ui/Card";
import { Badge } from "@/components/ui/Badge";

export const dynamic = "force-dynamic";

const fmtDateTime = (iso: string) =>
  iso
    ? new Date(iso).toLocaleString("fr-CH", {
        day: "2-digit",
        month: "2-digit",
        year: "numeric",
        hour: "2-digit",
        minute: "2-digit",
        second: "2-digit",
      })
    : "—";

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

export default async function AuditPage({
  searchParams,
}: {
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}) {
  const sp = await searchParams;
  const cabinets = listAuditCabinets();
  const activeClient =
    pickString(sp.client) || cabinets[0]?.cabinet_id || "pilote-jura-01";
  const entityType = pickString(sp.entity_type);
  const action = pickString(sp.action);
  const dateFrom = pickString(sp.date_from);
  const dateTo = pickString(sp.date_to);
  const offset = pickNumber(sp.offset) ?? 0;
  const limit = 50;

  const filters = {
    cabinetId: activeClient,
    entityType,
    action,
    dateFrom,
    dateTo,
    offset,
    limit,
  };

  const total = countAuditEvents(filters);
  const events = listAuditEvents(filters);
  const chain = verifyAuditChain(activeClient);

  return (
    <div className="mx-auto max-w-7xl px-6 py-8 lg:px-10 lg:py-10">
      <header className="mb-6 flex items-start justify-between gap-4">
        <div>
          <div className="flex items-center gap-2 text-xs text-[var(--color-text-dim)]">
            <Link href="/" className="hover:text-[var(--color-text)]">
              Dashboard
            </Link>
            <span>·</span>
            <span>Audit trail</span>
          </div>
          <h1 className="mt-1 text-2xl font-semibold tracking-tight">
            Audit trail (chain hash SHA-256)
          </h1>
          <p className="mt-1 text-xs text-[var(--color-text-dim)]">
            Append-only · multi-mandant strict · vérification cross-compat
            Python/TS
          </p>
        </div>
      </header>

      {/* CHAIN STATUS */}
      <Card className="mb-6">
        <CardBody className="flex items-center justify-between">
          <div className="flex items-center gap-3">
            {chain.is_valid ? (
              <>
                <CheckCircle2 size={20} className="text-emerald-400" />
                <div>
                  <p className="text-sm font-semibold text-emerald-400">
                    Chain intacte
                  </p>
                  <p className="text-xs text-[var(--color-text-dim)]">
                    {chain.total_events} événements vérifiés pour{" "}
                    <span className="font-mono">{activeClient}</span>
                  </p>
                </div>
              </>
            ) : (
              <>
                <AlertTriangle size={20} className="text-red-400" />
                <div>
                  <p className="text-sm font-semibold text-red-400">
                    Tampering détecté ⚠️
                  </p>
                  <p className="text-xs text-[var(--color-text-dim)]">
                    Anomalie à partir de l&apos;event #
                    {chain.first_invalid_id} : {chain.first_invalid_reason}
                  </p>
                </div>
              </>
            )}
          </div>
          <Badge variant={chain.is_valid ? "success" : "danger"}>
            <Shield size={12} />
            {chain.is_valid ? "VALID" : "BROKEN"}
          </Badge>
        </CardBody>
      </Card>

      {/* FILTERS */}
      <Card className="mb-4">
        <CardBody>
          <form className="flex flex-wrap items-center gap-2 text-xs">
            <label className="flex items-center gap-1">
              <span className="text-[var(--color-text-dim)]">Mandant :</span>
              <select
                name="client"
                defaultValue={activeClient}
                className="rounded-md border border-[var(--color-border)] bg-[var(--color-bg-card)] px-2 py-1"
              >
                {cabinets.length === 0 && (
                  <option value={activeClient}>{activeClient}</option>
                )}
                {cabinets.map((c) => (
                  <option key={c.cabinet_id} value={c.cabinet_id}>
                    {c.cabinet_id} ({c.events_count})
                  </option>
                ))}
              </select>
            </label>
            <label className="flex items-center gap-1">
              <span className="text-[var(--color-text-dim)]">Entité :</span>
              <input
                type="text"
                name="entity_type"
                defaultValue={entityType ?? ""}
                placeholder="ex: anomaly"
                className="rounded-md border border-[var(--color-border)] bg-[var(--color-bg-card)] px-2 py-1"
              />
            </label>
            <label className="flex items-center gap-1">
              <span className="text-[var(--color-text-dim)]">Action :</span>
              <input
                type="text"
                name="action"
                defaultValue={action ?? ""}
                placeholder="ex: validated"
                className="rounded-md border border-[var(--color-border)] bg-[var(--color-bg-card)] px-2 py-1"
              />
            </label>
            <button
              type="submit"
              className="rounded-md border border-[var(--color-border)] px-3 py-1 hover:bg-white/[0.05]"
            >
              Filtrer
            </button>
          </form>
        </CardBody>
      </Card>

      {/* EVENTS LIST */}
      <Card>
        <CardHeader>
          <CardTitle>
            {events.length} / {total} événements —{" "}
            <span className="font-mono text-[var(--color-text-muted)]">
              {activeClient}
            </span>
          </CardTitle>
          <div className="flex gap-2 text-xs text-[var(--color-text-dim)]">
            {offset > 0 && (
              <Link
                href={`/audit?${rebuildQuery(sp, "offset", String(Math.max(0, offset - limit)))}`}
                className="hover:text-[var(--color-text)]"
              >
                ← précédent
              </Link>
            )}
            {events.length === limit && (
              <Link
                href={`/audit?${rebuildQuery(sp, "offset", String(offset + limit))}`}
                className="hover:text-[var(--color-text)]"
              >
                suivant →
              </Link>
            )}
          </div>
        </CardHeader>
        {events.length === 0 ? (
          <CardBody>
            <p className="text-sm text-[var(--color-text-dim)]">
              Aucun événement pour ces filtres.
            </p>
          </CardBody>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-xs">
              <thead>
                <tr className="border-b border-[var(--color-border)] text-left font-medium uppercase tracking-wider text-[var(--color-text-dim)]">
                  <th className="px-5 py-3">Timestamp</th>
                  <th className="px-5 py-3">User</th>
                  <th className="px-5 py-3">Entité</th>
                  <th className="px-5 py-3">Action</th>
                  <th className="px-5 py-3">Hash</th>
                </tr>
              </thead>
              <tbody>
                {events.map((e: AuditEventRow) => (
                  <tr
                    key={e.id}
                    className="border-b border-[var(--color-border)]/60 hover:bg-white/[0.02]"
                  >
                    <td className="px-5 py-3 font-mono text-[var(--color-text-muted)]">
                      {fmtDateTime(e.timestamp)}
                    </td>
                    <td className="px-5 py-3">
                      {e.user_id ?? (
                        <span className="text-[var(--color-text-dim)]">
                          system
                        </span>
                      )}
                    </td>
                    <td className="px-5 py-3 font-mono">
                      {e.entity_type}#{e.entity_id}
                    </td>
                    <td className="px-5 py-3">
                      <Badge variant="muted">{e.action}</Badge>
                    </td>
                    <td className="px-5 py-3 font-mono text-[var(--color-text-dim)]">
                      {e.current_hash.slice(0, 12)}...
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>

      <p className="mt-6 text-center text-[11px] text-[var(--color-text-dim)]">
        Sprint 2 §3.10 Phase 3 · chain SHA-256 cross-compat Python/TS ·
        verify on-page-load
      </p>
    </div>
  );
}
