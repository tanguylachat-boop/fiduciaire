import Link from "next/link";
import { Landmark, CheckCircle2, TrendingUp } from "lucide-react";
import {
  getBankStats,
  listUnmatchedTransactions,
  listUnpaidInvoices,
  listBankCabinets,
} from "@/lib/db-poc-bank";
import { Card, CardBody } from "@/components/ui/Card";
import { Badge } from "@/components/ui/Badge";
import { BankMatcher } from "@/components/poc/BankMatcher";
import { Camt053Upload } from "@/components/poc/Camt053Upload";

export const dynamic = "force-dynamic";

const fmtCHF = new Intl.NumberFormat("fr-CH", {
  style: "currency",
  currency: "CHF",
  minimumFractionDigits: 2,
});

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

export default async function BankPage({
  searchParams,
}: {
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}) {
  const sp = await searchParams;
  const cabinets = listBankCabinets();
  const activeCabinet =
    pickString(sp.client) || cabinets[0]?.cabinet_id || "pilote-jura-01";
  const dateFrom = pickString(sp.date_from);
  const dateTo = pickString(sp.date_to);
  const amountMin = pickNumber(sp.amount_min);
  const amountMax = pickNumber(sp.amount_max);

  const filters = {
    cabinetId: activeCabinet,
    dateFrom,
    dateTo,
    amountMin,
    amountMax,
    limit: 200,
  };

  const stats = getBankStats(activeCabinet);
  const transactions = listUnmatchedTransactions(filters);
  const invoices = listUnpaidInvoices(filters);

  return (
    <div className="mx-auto max-w-[1400px] px-6 py-8 lg:px-10 lg:py-10">
      <header className="mb-6 flex items-start justify-between gap-4">
        <div>
          <div className="flex items-center gap-2 text-xs text-[var(--color-text-dim)]">
            <Link href="/" className="hover:text-[var(--color-text)]">
              Dashboard
            </Link>
            <span>·</span>
            <span>Rapprochement bancaire</span>
          </div>
          <h1 className="mt-1 text-2xl font-semibold tracking-tight">
            <Landmark size={20} className="mr-2 inline text-[var(--color-text-dim)]" />
            Rapprochement bancaire
          </h1>
          <p className="mt-1 text-xs text-[var(--color-text-dim)]">
            CAMT.053 ISO 20022 · matching auto (Sprint 1 §3.9) + manuel ·
            multi-mandant strict
          </p>
        </div>
      </header>

      {/* STATS + UPLOAD */}
      <div className="mb-6 grid gap-3 md:grid-cols-3">
        <StatCard
          label="Transactions non matchées"
          value={`${stats.unmatched_count}`}
          sub={fmtCHF.format(stats.unmatched_amount_total)}
          tone="warning"
        />
        <StatCard
          label="Factures non payées"
          value={`${stats.unpaid_count}`}
          sub={fmtCHF.format(stats.unpaid_amount_total)}
          tone="info"
        />
        <StatCard
          label="Taux de matching"
          value={`${stats.match_rate_pct.toFixed(1)} %`}
          sub={`${stats.matched_count} matchées au total`}
          tone={stats.match_rate_pct >= 80 ? "success" : "muted"}
        />
      </div>

      <div className="mb-4">
        <Camt053Upload
          cabinetId={activeCabinet}
          clientId={activeCabinet}
        />
      </div>

      {/* FILTERS */}
      <Card className="mb-4">
        <CardBody>
          <form className="flex flex-wrap items-center gap-2 text-xs">
            <label className="flex items-center gap-1">
              <span className="text-[var(--color-text-dim)]">Mandant :</span>
              <select
                name="client"
                defaultValue={activeCabinet}
                className="rounded-md border border-[var(--color-border)] bg-[var(--color-bg-card)] px-2 py-1"
              >
                {cabinets.length === 0 && (
                  <option value={activeCabinet}>{activeCabinet}</option>
                )}
                {cabinets.map((c) => (
                  <option key={c.cabinet_id} value={c.cabinet_id}>
                    {c.cabinet_id} ({c.tx_count} tx)
                  </option>
                ))}
              </select>
            </label>
            <label className="flex items-center gap-1">
              <span className="text-[var(--color-text-dim)]">Du :</span>
              <input
                type="date"
                name="date_from"
                defaultValue={dateFrom ?? ""}
                className="rounded-md border border-[var(--color-border)] bg-[var(--color-bg-card)] px-2 py-1"
              />
            </label>
            <label className="flex items-center gap-1">
              <span className="text-[var(--color-text-dim)]">Au :</span>
              <input
                type="date"
                name="date_to"
                defaultValue={dateTo ?? ""}
                className="rounded-md border border-[var(--color-border)] bg-[var(--color-bg-card)] px-2 py-1"
              />
            </label>
            <label className="flex items-center gap-1">
              <span className="text-[var(--color-text-dim)]">Montant ≥</span>
              <input
                type="number"
                name="amount_min"
                step="0.01"
                defaultValue={amountMin ?? ""}
                className="w-24 rounded-md border border-[var(--color-border)] bg-[var(--color-bg-card)] px-2 py-1"
              />
            </label>
            <label className="flex items-center gap-1">
              <span className="text-[var(--color-text-dim)]">Montant ≤</span>
              <input
                type="number"
                name="amount_max"
                step="0.01"
                defaultValue={amountMax ?? ""}
                className="w-24 rounded-md border border-[var(--color-border)] bg-[var(--color-bg-card)] px-2 py-1"
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

      <BankMatcher transactions={transactions} invoices={invoices} />

      <p className="mt-6 text-center text-[11px] text-[var(--color-text-dim)]">
        Sprint 2 §3.10 Phase 4 · audit log automatique sur chaque match ·
        cross-mandant bloqué
      </p>
    </div>
  );
}

function StatCard({
  label,
  value,
  sub,
  tone,
}: {
  label: string;
  value: string;
  sub?: string;
  tone: "success" | "info" | "warning" | "muted";
}) {
  const Icon =
    tone === "success" ? CheckCircle2 : tone === "info" ? TrendingUp : Landmark;
  const toneClass = {
    success: "text-emerald-400",
    info: "text-sky-400",
    warning: "text-amber-400",
    muted: "text-[var(--color-text-dim)]",
  }[tone];
  const variant: "success" | "info" | "warning" | "muted" = tone;
  return (
    <Card>
      <CardBody className="py-4">
        <div className={`mb-1 flex items-center gap-1.5 text-xs ${toneClass}`}>
          <Icon size={14} />
          <span>{label}</span>
        </div>
        <p className="font-mono text-2xl font-semibold tabular-nums">
          {value}
        </p>
        {sub && (
          <p className="mt-1 text-xs text-[var(--color-text-dim)]">{sub}</p>
        )}
        <Badge variant={variant} className="mt-2">
          {tone === "success"
            ? "OK"
            : tone === "warning"
              ? "à traiter"
              : tone === "info"
                ? "actif"
                : "—"}
        </Badge>
      </CardBody>
    </Card>
  );
}
