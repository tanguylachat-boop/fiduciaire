import { cn } from "@/lib/utils";
import type { ButtonHTMLAttributes } from "react";

type Variant = "primary" | "secondary" | "ghost" | "danger" | "success";
type Size = "sm" | "md" | "lg";

const variants: Record<Variant, string> = {
  primary:
    "bg-[var(--color-accent)] hover:bg-[var(--color-accent-hover)] text-white border-transparent",
  secondary:
    "bg-white/5 hover:bg-white/10 text-[var(--color-text)] border-[var(--color-border-strong)]",
  ghost:
    "bg-transparent hover:bg-white/5 text-[var(--color-text-muted)] hover:text-[var(--color-text)] border-transparent",
  danger:
    "bg-red-500/10 hover:bg-red-500/20 text-red-400 border-red-500/20",
  success:
    "bg-emerald-500/10 hover:bg-emerald-500/20 text-emerald-400 border-emerald-500/20",
};

const sizes: Record<Size, string> = {
  sm: "h-8 px-3 text-xs",
  md: "h-9 px-4 text-sm",
  lg: "h-10 px-5 text-sm",
};

interface Props extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: Variant;
  size?: Size;
}

export function Button({
  variant = "primary",
  size = "md",
  className,
  children,
  ...rest
}: Props) {
  return (
    <button
      className={cn(
        "inline-flex items-center justify-center gap-2 rounded-md border font-medium transition-colors disabled:cursor-not-allowed disabled:opacity-50",
        variants[variant],
        sizes[size],
        className,
      )}
      {...rest}
    >
      {children}
    </button>
  );
}
