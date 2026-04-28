import { Sidebar } from "@/components/Sidebar";
import { CABINET, GLOBAL_ACCURACY, GLOBAL_LEVEL } from "@/lib/mock-data";

export default function DashboardLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <div className="flex h-screen bg-[var(--color-bg)]">
      <Sidebar
        cabinet={CABINET.name}
        agentLevel={GLOBAL_LEVEL}
        agentAccuracy={GLOBAL_ACCURACY}
      />
      <main className="flex-1 overflow-y-auto">{children}</main>
    </div>
  );
}
