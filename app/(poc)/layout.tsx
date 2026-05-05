// Route group (poc) — dashboard local SQLite, isolé du dashboard Phase 2/3.
// Pas de Sidebar mock, pas de Supabase, pas de mock-data.
// Lit uniquement data/fiduciaire.sqlite (worker Python).

import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "Fiduciaire AI — POC review",
};

export default function PocLayout({ children }: { children: React.ReactNode }) {
  return (
    <div className="min-h-screen bg-[var(--color-bg)] text-[var(--color-text)]">
      {children}
    </div>
  );
}
