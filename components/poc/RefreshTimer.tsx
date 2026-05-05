"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";

// Polling 5s : déclenche un router.refresh() qui re-render le Server Component
// parent et re-lit SQLite. Aucun fetch, pas d'API route — juste re-execution
// côté serveur sur la même URL.
export function RefreshTimer({ intervalMs = 5000 }: { intervalMs?: number }) {
  const router = useRouter();
  useEffect(() => {
    const id = setInterval(() => router.refresh(), intervalMs);
    return () => clearInterval(id);
  }, [router, intervalMs]);
  return null;
}
