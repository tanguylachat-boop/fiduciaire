import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

export function formatCHF(amount: number): string {
  return new Intl.NumberFormat("fr-CH", {
    style: "currency",
    currency: "CHF",
    minimumFractionDigits: 2,
  }).format(amount);
}

export function formatDate(date: Date | string, opts?: Intl.DateTimeFormatOptions): string {
  const d = typeof date === "string" ? new Date(date) : date;
  return new Intl.DateTimeFormat("fr-CH", opts ?? {
    day: "2-digit",
    month: "short",
    year: "numeric",
  }).format(d);
}

export function formatRelative(date: Date | string): string {
  const d = typeof date === "string" ? new Date(date) : date;
  const diffMs = Date.now() - d.getTime();
  const diffMin = Math.floor(diffMs / 60000);
  const diffH = Math.floor(diffMin / 60);
  const diffD = Math.floor(diffH / 24);

  if (diffMin < 1) return "à l'instant";
  if (diffMin < 60) return `il y a ${diffMin} min`;
  if (diffH < 24) return `il y a ${diffH}h`;
  if (diffD < 7) return `il y a ${diffD}j`;
  return formatDate(d);
}

export function scoreLevel(accuracy: number): "rouge" | "orange" | "vert" {
  if (accuracy < 50) return "rouge";
  if (accuracy < 95) return "orange";
  return "vert";
}

export function levelColor(level: "rouge" | "orange" | "vert") {
  return {
    rouge: { bg: "bg-red-500/10", text: "text-red-400", dot: "bg-red-500", ring: "ring-red-500/30" },
    orange: { bg: "bg-amber-500/10", text: "text-amber-400", dot: "bg-amber-500", ring: "ring-amber-500/30" },
    vert: { bg: "bg-emerald-500/10", text: "text-emerald-400", dot: "bg-emerald-500", ring: "ring-emerald-500/30" },
  }[level];
}
