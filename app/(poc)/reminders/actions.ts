"use server";

import { revalidatePath } from "next/cache";
import {
  approveReminder,
  skipReminder,
  editReminderDraft,
  ReminderNotFoundError,
  ReminderStateError,
} from "@/lib/db-poc-reminders-write";

export async function approveAndSendReminder(
  formData: FormData
): Promise<{ ok: boolean; error?: string }> {
  const id = Number(formData.get("id"));
  const cabinetId = String(formData.get("cabinet_id"));
  if (!id || !cabinetId) return { ok: false, error: "Paramètres manquants" };
  try {
    approveReminder(id, cabinetId);
    revalidatePath("/reminders");
    return { ok: true };
  } catch (e) {
    if (e instanceof ReminderNotFoundError || e instanceof ReminderStateError) {
      return { ok: false, error: e.message };
    }
    return { ok: false, error: "Erreur inattendue" };
  }
}

export async function skipReminderAction(
  formData: FormData
): Promise<{ ok: boolean; error?: string }> {
  const id = Number(formData.get("id"));
  const cabinetId = String(formData.get("cabinet_id"));
  const reason = String(formData.get("reason") || "Ignorée manuellement");
  if (!id || !cabinetId) return { ok: false, error: "Paramètres manquants" };
  try {
    skipReminder(id, cabinetId, reason);
    revalidatePath("/reminders");
    return { ok: true };
  } catch (e) {
    if (e instanceof ReminderNotFoundError || e instanceof ReminderStateError) {
      return { ok: false, error: e.message };
    }
    return { ok: false, error: "Erreur inattendue" };
  }
}

export async function editReminderDraftAction(
  formData: FormData
): Promise<{ ok: boolean; error?: string }> {
  const id = Number(formData.get("id"));
  const cabinetId = String(formData.get("cabinet_id"));
  const bodyFinal = String(formData.get("body_final") || "");
  if (!id || !cabinetId) return { ok: false, error: "Paramètres manquants" };
  if (!bodyFinal.trim()) return { ok: false, error: "Corps vide" };
  try {
    editReminderDraft(id, cabinetId, bodyFinal);
    revalidatePath("/reminders");
    return { ok: true };
  } catch (e) {
    if (e instanceof ReminderNotFoundError || e instanceof ReminderStateError) {
      return { ok: false, error: e.message };
    }
    return { ok: false, error: "Erreur inattendue" };
  }
}

export async function batchApproveReminders(
  formData: FormData
): Promise<{ ok: boolean; count: number; error?: string }> {
  const cabinetId = String(formData.get("cabinet_id"));
  const idsRaw = String(formData.get("ids") || "");
  if (!cabinetId || !idsRaw) return { ok: false, count: 0, error: "Paramètres manquants" };

  const ids = idsRaw
    .split(",")
    .map(Number)
    .filter((n) => n > 0);

  let count = 0;
  const errors: string[] = [];

  for (const id of ids) {
    try {
      approveReminder(id, cabinetId);
      count++;
    } catch (e) {
      errors.push(`${id}: ${e instanceof Error ? e.message : String(e)}`);
    }
  }

  revalidatePath("/reminders");
  return {
    ok: errors.length === 0,
    count,
    error: errors.length > 0 ? errors.join("; ") : undefined,
  };
}
