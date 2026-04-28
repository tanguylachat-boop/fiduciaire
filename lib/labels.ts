import type {
  DocumentCategory,
  Urgency,
  DocumentStatus,
  ExtractionStatus,
  InvoiceStatus,
  AgentLevel,
  TaskType,
} from "./types";

export const categoryLabel: Record<DocumentCategory, string> = {
  facture_fournisseur: "Facture fournisseur",
  note_frais: "Note de frais",
  releve_bancaire: "Relevé bancaire",
  document_fiscal: "Document fiscal",
  courrier: "Courrier client",
  spam: "Spam",
};

export const urgencyLabel: Record<Urgency, string> = {
  haute: "Haute",
  normale: "Normale",
  basse: "Basse",
};

export const urgencyVariant: Record<Urgency, "danger" | "warning" | "muted"> = {
  haute: "danger",
  normale: "warning",
  basse: "muted",
};

export const statusLabel: Record<DocumentStatus, string> = {
  nouveau: "Nouveau",
  traite: "Traité",
  valide: "Validé",
  rejete: "Rejeté",
};

export const statusVariant: Record<
  DocumentStatus,
  "info" | "warning" | "success" | "danger"
> = {
  nouveau: "info",
  traite: "warning",
  valide: "success",
  rejete: "danger",
};

export const extractionStatusLabel: Record<ExtractionStatus, string> = {
  en_attente: "En attente",
  valide: "Validée",
  corrige: "Corrigée",
  rejete: "Rejetée",
};

export const extractionStatusVariant: Record<
  ExtractionStatus,
  "warning" | "success" | "info" | "danger"
> = {
  en_attente: "warning",
  valide: "success",
  corrige: "info",
  rejete: "danger",
};

export const invoiceStatusLabel: Record<InvoiceStatus, string> = {
  payee: "Payée",
  en_attente: "En attente",
  relancee_1: "Relance 1",
  relancee_2: "Relance 2",
  relancee_3: "Relance 3",
  contentieux: "Contentieux",
};

export const invoiceStatusVariant: Record<
  InvoiceStatus,
  "success" | "info" | "warning" | "danger"
> = {
  payee: "success",
  en_attente: "info",
  relancee_1: "warning",
  relancee_2: "warning",
  relancee_3: "danger",
  contentieux: "danger",
};

export const levelLabel: Record<AgentLevel, string> = {
  rouge: "Rouge",
  orange: "Orange",
  vert: "Vert",
};

export const taskLabel: Record<TaskType, string> = {
  triage: "Triage & catégorisation",
  extraction: "Extraction de données",
  relance: "Relances factures",
};
