"use server";

import { revalidatePath } from "next/cache";
import path from "node:path";
import fs from "node:fs";
import { spawn } from "node:child_process";
import {
  approveReminder,
  skipReminder,
  editReminderDraft,
  ReminderNotFoundError,
  ReminderStateError,
} from "@/lib/db-poc-reminders-write";

// ── Script runner helpers (pattern from app/(poc)/bank/actions.ts) ─────────

function findRepoRoot(): string {
  let cur = process.cwd();
  for (let i = 0; i < 6; i++) {
    if (fs.existsSync(path.join(cur, "worker", "src", "fiduciaire_worker"))) {
      return cur;
    }
    const parent = path.dirname(cur);
    if (parent === cur) break;
    cur = parent;
  }
  return process.cwd();
}

function pickPython(repoRoot: string): string {
  const venv = path.join(repoRoot, "worker", ".venv", "bin", "python");
  if (fs.existsSync(venv)) return venv;
  return process.env.FIDUCIAIRE_PYTHON || "python3";
}

export interface SendResult {
  ok: boolean;
  reminder_id: number;
  status?: string;
  dry_run?: boolean;
  sent_at?: string | null;
  error?: string;
}

function runSendReminderScript(
  reminderId: number,
  cabinetId: string,
): Promise<SendResult> {
  return new Promise((resolve) => {
    const repoRoot = findRepoRoot();
    const python = pickPython(repoRoot);
    const scriptPath = path.join("worker", "scripts", "send_reminder.py");
    const args = [
      scriptPath,
      "--reminder-id",
      String(reminderId),
      "--cabinet-id",
      cabinetId,
    ];
    const child = spawn(python, args, {
      cwd: repoRoot,
      env: { ...process.env },
    });

    let stdout = "";
    let stderr = "";
    child.stdout.on("data", (d) => (stdout += d.toString()));
    child.stderr.on("data", (d) => (stderr += d.toString()));

    child.on("close", (code) => {
      const raw = stdout.trim();
      try {
        const parsed = JSON.parse(raw) as SendResult;
        resolve(parsed);
      } catch {
        // Le script n'a pas produit de JSON valide
        const tail = stderr.trim().split("\n").slice(-3).join(" | ");
        resolve({
          ok: false,
          reminder_id: reminderId,
          status: "failed",
          error: `Script exit ${code ?? -1} — stdout: ${raw.slice(-200)} stderr: ${tail}`,
        });
      }
    });
  });
}

// ── Server Actions ─────────────────────────────────────────────────────────

export async function approveAndSendReminder(
  formData: FormData
): Promise<{ ok: boolean; status?: string; dry_run?: boolean; error?: string }> {
  const id = Number(formData.get("id"));
  const cabinetId = String(formData.get("cabinet_id"));
  if (!id || !cabinetId) return { ok: false, error: "Paramètres manquants" };

  try {
    // 1. Approve in DB
    approveReminder(id, cabinetId);
  } catch (e) {
    if (e instanceof ReminderNotFoundError || e instanceof ReminderStateError) {
      return { ok: false, error: e.message };
    }
    return { ok: false, error: "Erreur inattendue lors de l'approbation" };
  }

  // 2. Exec Python worker to send via SMTP
  const result = await runSendReminderScript(id, cabinetId);

  revalidatePath("/reminders");

  if (result.ok) {
    return {
      ok: true,
      status: result.status,
      dry_run: result.dry_run,
    };
  } else {
    return { ok: false, error: result.error };
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

export interface BatchSendResult {
  ok: boolean;
  total: number;
  sent: number;
  failed: number;
  errors: { id: number; error: string }[];
}

export async function batchSendReminders(
  formData: FormData
): Promise<BatchSendResult> {
  const cabinetId = String(formData.get("cabinet_id"));
  const idsRaw = String(formData.get("ids") || "");
  if (!cabinetId || !idsRaw) {
    return { ok: false, total: 0, sent: 0, failed: 0, errors: [{ id: 0, error: "Paramètres manquants" }] };
  }

  const ids = idsRaw
    .split(",")
    .map(Number)
    .filter((n) => n > 0);

  let sent = 0;
  let failed = 0;
  const errors: { id: number; error: string }[] = [];

  for (const id of ids) {
    // Approve first
    try {
      approveReminder(id, cabinetId);
    } catch (e) {
      failed++;
      errors.push({ id, error: e instanceof Error ? e.message : String(e) });
      continue;
    }

    // Then send
    const result = await runSendReminderScript(id, cabinetId);
    if (result.ok) {
      sent++;
    } else {
      failed++;
      errors.push({ id, error: result.error ?? "Échec SMTP" });
    }
  }

  revalidatePath("/reminders");
  return {
    ok: failed === 0,
    total: ids.length,
    sent,
    failed,
    errors,
  };
}
