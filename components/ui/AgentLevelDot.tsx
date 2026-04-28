import { cn, levelColor } from "@/lib/utils";
import type { AgentLevel } from "@/lib/types";

export function AgentLevelDot({
  level,
  label,
  size = "md",
}: {
  level: AgentLevel;
  label?: string;
  size?: "sm" | "md";
}) {
  const c = levelColor(level);
  const dotSize = size === "sm" ? "h-1.5 w-1.5" : "h-2 w-2";

  return (
    <span className="inline-flex items-center gap-2">
      <span className={cn("relative flex", dotSize)}>
        <span className={cn("pulse-dot absolute inline-flex h-full w-full rounded-full opacity-60", c.dot)} />
        <span className={cn("relative inline-flex rounded-full", dotSize, c.dot)} />
      </span>
      {label && <span className={cn("text-xs font-medium", c.text)}>{label}</span>}
    </span>
  );
}
