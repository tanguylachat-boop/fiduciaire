import {
  MailCheck,
  FileSearch,
  Send,
  FileText,
  AlertCircle,
} from "lucide-react";
import { formatRelative } from "@/lib/utils";
import type { AiAction, ActionType } from "@/lib/types";

const iconMap: Record<ActionType, typeof MailCheck> = {
  triage: MailCheck,
  extraction: FileSearch,
  relance: Send,
  rapport: FileText,
  notification: AlertCircle,
};

const accentMap: Record<ActionType, string> = {
  triage: "text-blue-400 bg-blue-500/10",
  extraction: "text-purple-400 bg-purple-500/10",
  relance: "text-amber-400 bg-amber-500/10",
  rapport: "text-emerald-400 bg-emerald-500/10",
  notification: "text-red-400 bg-red-500/10",
};

export function ActivityFeed({ actions }: { actions: AiAction[] }) {
  return (
    <ul className="divide-y divide-[var(--color-border)]">
      {actions.map((a) => {
        const Icon = iconMap[a.action_type];
        const accent = accentMap[a.action_type];
        return (
          <li key={a.id} className="flex items-start gap-3 px-5 py-3.5 fade-in">
            <div className={`mt-0.5 rounded-md p-1.5 ${accent}`}>
              <Icon size={14} />
            </div>
            <div className="min-w-0 flex-1">
              <p className="text-sm text-[var(--color-text)]">{a.description}</p>
              <div className="mt-1 flex items-center gap-2 text-xs text-[var(--color-text-dim)]">
                <span>{formatRelative(a.created_at)}</span>
                <span>·</span>
                <span>Confiance {(a.confidence * 100).toFixed(0)}%</span>
              </div>
            </div>
          </li>
        );
      })}
    </ul>
  );
}
