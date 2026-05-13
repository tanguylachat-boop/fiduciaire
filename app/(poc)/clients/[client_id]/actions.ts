"use server";

import { revalidatePath } from "next/cache";
import {
  markAnomalyResolved as dbMarkResolved,
  markAnomalyFalsePositive as dbMarkFalse,
  AnomalyNotFoundError,
  AnomalyAlreadyClosedError,
} from "@/lib/db-poc-anomalies-write";

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

function readAnomalyId(formData: FormData): number {
  const id = formData.get("__anomalyId");
  if (typeof id !== "string") throw new Error("anomaly_id manquant");
  const n = Number(id);
  if (!Number.isInteger(n) || n <= 0) {
    throw new Error(`anomaly_id invalide: ${id}`);
  }
  return n;
}

function readReason(formData: FormData): string | null {
  const reason = formData.get("reason");
  if (typeof reason === "string" && reason.trim().length > 0) {
    return reason.trim();
  }
  return null;
}

export type AnomalyActionResult =
  | { ok: true; message: string }
  | { ok: false; error: string };

export async function markAnomalyResolvedAction(
  _prev: AnomalyActionResult | undefined,
  formData: FormData,
): Promise<AnomalyActionResult> {
  try {
    const id = readAnomalyId(formData);
    const clientId = readClientId(formData);
    const userId = readUserIdFromForm(formData);
    const reason = readReason(formData);
    dbMarkResolved(id, clientId, userId, reason);
    revalidatePath(`/(poc)/clients/${clientId}`);
    return { ok: true, message: "Anomalie marquée résolue" };
  } catch (err) {
    return { ok: false, error: formatError(err) };
  }
}

export async function markAnomalyFalsePositiveAction(
  _prev: AnomalyActionResult | undefined,
  formData: FormData,
): Promise<AnomalyActionResult> {
  try {
    const id = readAnomalyId(formData);
    const clientId = readClientId(formData);
    const userId = readUserIdFromForm(formData);
    const reason = readReason(formData);
    dbMarkFalse(id, clientId, userId, reason);
    revalidatePath(`/(poc)/clients/${clientId}`);
    return { ok: true, message: "Anomalie marquée faux positif" };
  } catch (err) {
    return { ok: false, error: formatError(err) };
  }
}

function formatError(err: unknown): string {
  if (err instanceof AnomalyNotFoundError) {
    return "Anomalie introuvable ou hors scope mandant";
  }
  if (err instanceof AnomalyAlreadyClosedError) {
    return err.message;
  }
  if (err instanceof Error) return err.message;
  return String(err);
}
