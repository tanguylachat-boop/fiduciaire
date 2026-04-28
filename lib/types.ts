export type DocumentCategory =
  | "facture_fournisseur"
  | "note_frais"
  | "releve_bancaire"
  | "document_fiscal"
  | "courrier"
  | "spam";

export type Urgency = "haute" | "normale" | "basse";

export type DocumentStatus = "nouveau" | "traite" | "valide" | "rejete";

export type ExtractionStatus = "en_attente" | "valide" | "corrige" | "rejete";

export type InvoiceStatus =
  | "payee"
  | "en_attente"
  | "relancee_1"
  | "relancee_2"
  | "relancee_3"
  | "contentieux";

export type ActionType =
  | "triage"
  | "extraction"
  | "relance"
  | "rapport"
  | "notification";

export type AgentLevel = "rouge" | "orange" | "vert";

export type TaskType = "triage" | "extraction" | "relance";

export interface Attachment {
  filename: string;
  url: string;
  type: string;
  size: number;
}

export interface AiDocument {
  id: string;
  client_id: string;
  source_email: string;
  subject: string;
  body_preview: string;
  category: DocumentCategory;
  urgency: Urgency;
  attachments: Attachment[];
  ai_confidence: number;
  status: DocumentStatus;
  created_at: string;
}

export interface ExtractedData {
  montant: number;
  date: string;
  fournisseur?: string;
  client?: string;
  numero_facture: string;
  tva: number;
  description: string;
}

export interface SuggestedEntry {
  compte_debit: string;
  compte_credit: string;
  montant: number;
  libelle: string;
}

export interface AiExtraction {
  id: string;
  document_id: string;
  client_id: string;
  extracted_data: ExtractedData;
  suggested_entry: SuggestedEntry;
  status: ExtractionStatus;
  validated_by: string | null;
  validated_at: string | null;
  created_at: string;
  ai_confidence: number;
}

export interface AiInvoice {
  id: string;
  client_id: string;
  invoice_number: string;
  client_name: string;
  amount: number;
  due_date: string;
  status: InvoiceStatus;
  last_reminder_at: string | null;
  created_at: string;
  next_reminder_preview?: string;
}

export interface AiAction {
  id: string;
  client_id: string;
  action_type: ActionType;
  description: string;
  confidence: number;
  status: "auto" | "valide" | "rejete";
  created_at: string;
}

export interface AiAgentPerformance {
  id: string;
  client_id: string;
  task_type: TaskType;
  total_actions: number;
  correct_actions: number;
  accuracy: number;
  level: AgentLevel;
  updated_at: string;
}
