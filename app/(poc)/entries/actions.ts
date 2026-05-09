"use server";

import { revalidatePath } from "next/cache";
import {
  validateEntry as dbValidate,
  correctEntry as dbCorrect,
  rejectEntry as dbReject,
  EntryNotFoundError,
  InvalidTransitionError,
  type CorrectionPayload,
} from "@/lib/db-poc-write";

// Sprint 0a : pas d'auth, on lit le user_id depuis un header X-User-Id provisoire
// (à remplacer par un vrai middleware auth en Sprint 1).
function readUserIdFromForm(formData: FormData): string | null {
  const userId = formData.get("__userId");
  return typeof userId === "string" && userId.length > 0 ? userId : "poc-user";
}

function readClientId(formData: FormData): string {
  const clientId = formData.get("__clientId");
  if (typeof clientId !== "string" || clientId.length === 0) {
    throw new Error("client_id manquant — multi-mandant requis");
  }
  return clientId;
}

function readEntryId(formData: FormData): number {
  const id = formData.get("__entryId");
  if (typeof id !== "string") throw new Error("entry_id manquant");
  const n = Number(id);
  if (!Number.isInteger(n) || n <= 0) {
    throw new Error(`entry_id invalide: ${id}`);
  }
  return n;
}

export type ActionResult =
  | { ok: true; message: string; redirectTo?: string }
  | { ok: false; error: string };

export async function validateEntryAction(
  _prev: ActionResult | undefined,
  formData: FormData,
): Promise<ActionResult> {
  try {
    const id = readEntryId(formData);
    const clientId = readClientId(formData);
    const userId = readUserIdFromForm(formData);
    dbValidate(id, clientId, userId);
    revalidatePath("/(poc)/entries");
    revalidatePath(`/(poc)/entries/${id}`);
    return { ok: true, message: "Écriture validée" };
  } catch (err) {
    return { ok: false, error: formatError(err) };
  }
}

export async function correctEntryAction(
  _prev: ActionResult | undefined,
  formData: FormData,
): Promise<ActionResult> {
  try {
    const id = readEntryId(formData);
    const clientId = readClientId(formData);
    const userId = readUserIdFromForm(formData);
    const payload: CorrectionPayload = {};

    const debit = formData.get("debit_account");
    if (typeof debit === "string" && debit.trim()) {
      payload.debit_account = debit.trim();
    }
    const credit = formData.get("credit_account");
    if (typeof credit === "string" && credit.trim()) {
      payload.credit_account = credit.trim();
    }
    const amount = formData.get("amount_chf");
    if (typeof amount === "string" && amount.trim()) {
      const n = Number(amount);
      if (Number.isFinite(n)) payload.amount_chf = n;
    }
    const vatCode = formData.get("vat_code");
    if (typeof vatCode === "string" && vatCode.trim()) {
      payload.vat_code = vatCode.trim();
    }
    const vatAmount = formData.get("vat_amount");
    if (typeof vatAmount === "string" && vatAmount.trim()) {
      const n = Number(vatAmount);
      if (Number.isFinite(n)) payload.vat_amount = n;
    }
    const description = formData.get("description");
    if (typeof description === "string" && description.trim()) {
      payload.description = description.trim();
    }

    const { fieldsChanged } = dbCorrect(id, clientId, userId, payload);
    revalidatePath("/(poc)/entries");
    revalidatePath(`/(poc)/entries/${id}`);
    return {
      ok: true,
      message:
        fieldsChanged.length > 0
          ? `Écriture corrigée et validée (${fieldsChanged.join(", ")})`
          : "Écriture validée",
    };
  } catch (err) {
    return { ok: false, error: formatError(err) };
  }
}

export async function rejectEntryAction(
  _prev: ActionResult | undefined,
  formData: FormData,
): Promise<ActionResult> {
  try {
    const id = readEntryId(formData);
    const clientId = readClientId(formData);
    const userId = readUserIdFromForm(formData);
    const reason = formData.get("reason");
    if (typeof reason !== "string" || reason.trim().length === 0) {
      return { ok: false, error: "Raison du rejet obligatoire" };
    }
    dbReject(id, clientId, userId, reason);
    revalidatePath("/(poc)/entries");
    revalidatePath(`/(poc)/entries/${id}`);
    return { ok: true, message: "Écriture rejetée" };
  } catch (err) {
    return { ok: false, error: formatError(err) };
  }
}

function formatError(err: unknown): string {
  if (err instanceof EntryNotFoundError) {
    return "Écriture introuvable ou hors scope mandant";
  }
  if (err instanceof InvalidTransitionError) {
    return err.message;
  }
  if (err instanceof Error) return err.message;
  return String(err);
}
