import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "LX Studio — Employé IA Fiduciaire",
  description: "Agent autonome pour fiduciaires suisses — triage, extraction, relances.",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="fr">
      <body>{children}</body>
    </html>
  );
}
