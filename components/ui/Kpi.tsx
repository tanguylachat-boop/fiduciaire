import { cn } from "@/lib/utils";
import type { LucideIcon } from "lucide-react";

export function Kpi({
  label,
  value,
  hint,
  icon: Icon,
  trend,
  accent = "default",
}: {
  label: string;
  value: string;
  hint?: string;
  icon?: LucideIcon;
  trend?: { value: string; direction: "up" | "down" | "neutral" };
  accent?: "default" | "success" | "warning" | "danger";
}) {
  const accentRing = {
    default: "ring-[var(--color-border)]",
    success: "ring-emerald-500/30",
    warning: "ring-amber-500/30",
    danger: "ring-red-500/30",
  }[accent];

  const trendColor = {
    up: "text-emerald-400",
    down: "text-red-400",
    neutral: "text-[var(--color-text-muted)]",
  }[trend?.direction ?? "neutral"];

  return (
    <div
      className={cn(
        "relative rounded-xl border border-[var(--color-border)] bg-[var(--color-bg-card)] p-5 ring-1",
        accentRing,
      )}
    >
      <div className="flex items-start justify-between">
        <div>
          <div className="text-xs font-medium text-[var(--color-text-muted)]">
            {label}
          </div>
          <div className="mt-2 text-2xl font-semibold tracking-tight">
            {value}
          </div>
        </div>
        {Icon && (
          <div className="rounded-lg bg-white/5 p-2 text-[var(--color-text-muted)]">
            <Icon size={16} />
          </div>
        )}
      </div>
      <div className="mt-3 flex items-center gap-2 text-xs">
        {trend && <span className={trendColor}>{trend.value}</span>}
        {hint && (
          <span className="text-[var(--color-text-dim)]">{hint}</span>
        )}
      </div>
    </div>
  );
}
