"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import {
  LayoutDashboard,
  FileText,
  BookOpen,
  Mail,
  Activity,
  Settings,
  Sparkles,
} from "lucide-react";
import { cn, levelColor } from "@/lib/utils";
import type { AgentLevel } from "@/lib/types";

const nav = [
  { href: "/", label: "Tableau de bord", icon: LayoutDashboard },
  { href: "/documents", label: "Documents", icon: FileText },
  { href: "/ecritures", label: "Écritures", icon: BookOpen },
  { href: "/relances", label: "Relances", icon: Mail },
  { href: "/performance", label: "Performance", icon: Activity },
  { href: "/parametres", label: "Paramètres", icon: Settings },
];

export function Sidebar({
  cabinet,
  agentLevel,
  agentAccuracy,
}: {
  cabinet: string;
  agentLevel: AgentLevel;
  agentAccuracy: number;
}) {
  const pathname = usePathname();
  const c = levelColor(agentLevel);

  return (
    <aside className="flex h-screen w-64 flex-col border-r border-[var(--color-border)] bg-[var(--color-bg-elevated)]">
      <div className="border-b border-[var(--color-border)] px-5 py-5">
        <div className="flex items-center gap-2 text-[11px] font-semibold uppercase tracking-[0.18em] text-[var(--color-accent)]">
          <div className="h-5 w-5 rounded bg-gradient-to-br from-blue-500 to-blue-700" />
          LX Studio
        </div>
        <div className="mt-3 text-sm font-medium">{cabinet}</div>
        <div className="mt-0.5 text-xs text-[var(--color-text-muted)]">
          Employé IA · Fiduciaire
        </div>
      </div>

      <div className="px-3 py-3">
        <div
          className={cn(
            "flex items-center justify-between rounded-lg border px-3 py-2.5",
            c.bg,
            "border-" + "[var(--color-border)]",
          )}
        >
          <div className="flex items-center gap-2">
            <span className={cn("relative flex h-2 w-2")}>
              <span className={cn("pulse-dot absolute inline-flex h-full w-full rounded-full opacity-60", c.dot)} />
              <span className={cn("relative inline-flex h-2 w-2 rounded-full", c.dot)} />
            </span>
            <div>
              <div className={cn("text-xs font-medium", c.text)}>IA active</div>
              <div className="text-[10px] text-[var(--color-text-muted)]">
                Précision {agentAccuracy.toFixed(1)}%
              </div>
            </div>
          </div>
          <Sparkles size={14} className={c.text} />
        </div>
      </div>

      <nav className="flex-1 overflow-y-auto px-3 pb-3">
        <ul className="space-y-0.5">
          {nav.map(({ href, label, icon: Icon }) => {
            const active =
              href === "/"
                ? pathname === "/"
                : pathname.startsWith(href);
            return (
              <li key={href}>
                <Link
                  href={href}
                  className={cn(
                    "flex items-center gap-3 rounded-md px-3 py-2 text-sm transition-colors",
                    active
                      ? "bg-[var(--color-accent-dim)] text-[var(--color-accent)]"
                      : "text-[var(--color-text-muted)] hover:bg-white/5 hover:text-[var(--color-text)]",
                  )}
                >
                  <Icon size={16} />
                  {label}
                </Link>
              </li>
            );
          })}
        </ul>
      </nav>

      <div className="border-t border-[var(--color-border)] px-5 py-4">
        <div className="text-[10px] uppercase tracking-wider text-[var(--color-text-dim)]">
          Powered by
        </div>
        <div className="mt-1 text-xs text-[var(--color-text-muted)]">
          Claude Sonnet 4.6 · Hébergé 🇨🇭
        </div>
      </div>
    </aside>
  );
}
