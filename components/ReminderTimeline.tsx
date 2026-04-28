import { cn } from "@/lib/utils";
import type { InvoiceStatus } from "@/lib/types";

const steps: { key: InvoiceStatus; label: string }[] = [
  { key: "en_attente", label: "Envoyée" },
  { key: "relancee_1", label: "Relance 1" },
  { key: "relancee_2", label: "Relance 2" },
  { key: "relancee_3", label: "Relance 3" },
  { key: "contentieux", label: "Contentieux" },
];

const order: Record<InvoiceStatus, number> = {
  payee: -1,
  en_attente: 0,
  relancee_1: 1,
  relancee_2: 2,
  relancee_3: 3,
  contentieux: 4,
};

export function ReminderTimeline({ status }: { status: InvoiceStatus }) {
  const current = order[status];

  if (status === "payee") {
    return (
      <div className="text-xs text-emerald-400">Facture payée ✓</div>
    );
  }

  return (
    <div className="flex items-center gap-1">
      {steps.map((step, i) => {
        const done = i <= current;
        const isContentieux = step.key === "contentieux";
        const active = i === current;
        return (
          <div key={step.key} className="flex items-center gap-1">
            <div
              className={cn(
                "flex items-center gap-1.5 rounded-md px-2 py-1 text-[10px] font-medium",
                done
                  ? isContentieux
                    ? "bg-red-500/15 text-red-400"
                    : active
                      ? "bg-amber-500/15 text-amber-400"
                      : "bg-emerald-500/10 text-emerald-400"
                  : "bg-white/5 text-[var(--color-text-dim)]",
              )}
            >
              <span
                className={cn(
                  "h-1.5 w-1.5 rounded-full",
                  done
                    ? isContentieux
                      ? "bg-red-400"
                      : active
                        ? "bg-amber-400"
                        : "bg-emerald-400"
                    : "bg-[var(--color-text-dim)]",
                )}
              />
              {step.label}
            </div>
            {i < steps.length - 1 && (
              <div
                className={cn(
                  "h-px w-3",
                  i < current ? "bg-emerald-500/30" : "bg-[var(--color-border)]",
                )}
              />
            )}
          </div>
        );
      })}
    </div>
  );
}
