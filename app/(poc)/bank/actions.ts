"use server";

import { revalidatePath } from "next/cache";
import path from "node:path";
import os from "node:os";
import fs from "node:fs";
import { spawn } from "node:child_process";
import {
  manuallyLinkTransaction,
  BankLinkError,
} from "@/lib/db-poc-bank-write";

export type ManualLinkResult =
  | { ok: true; message: string }
  | { ok: false; error: string };

export type Camt053ImportResult =
  | {
      ok: true;
      cabinet_id: string;
      client_id: string;
      iban: string;
      transactions_total: number;
      transactions_inserted: number;
      transactions_duplicates: number;
    }
  | { ok: false; error: string };

function readUserId(formData: FormData): string | null {
  const v = formData.get("__userId");
  return typeof v === "string" && v.length > 0 ? v : "poc-user";
}

function readNumber(formData: FormData, key: string): number {
  const v = formData.get(key);
  if (typeof v !== "string" || v.length === 0) {
    throw new Error(`${key} manquant`);
  }
  const n = Number(v);
  if (!Number.isInteger(n) || n <= 0) {
    throw new Error(`${key} invalide : ${v}`);
  }
  return n;
}

function readNonEmpty(formData: FormData, key: string): string {
  const v = formData.get(key);
  if (typeof v !== "string" || v.length === 0) {
    throw new Error(`${key} manquant`);
  }
  return v;
}

// --- Match manuel ----------------------------------------------------------

export async function manuallyLinkTransactionAction(
  _prev: ManualLinkResult | undefined,
  formData: FormData,
): Promise<ManualLinkResult> {
  try {
    const transactionId = readNumber(formData, "__transactionId");
    const entryId = readNumber(formData, "__entryId");
    const userId = readUserId(formData);
    const result = manuallyLinkTransaction(
      transactionId,
      entryId,
      userId,
      "manual link from /bank dashboard",
    );
    revalidatePath("/bank");
    revalidatePath(`/clients/${result.cabinetId}`);
    return {
      ok: true,
      message: `Lien créé tx#${result.transactionId} ↔ doc#${result.documentId}`,
    };
  } catch (err) {
    if (err instanceof BankLinkError) return { ok: false, error: err.message };
    if (err instanceof Error) return { ok: false, error: err.message };
    return { ok: false, error: String(err) };
  }
}

// --- Upload CAMT.053 -------------------------------------------------------

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

function runImportCamt(
  repoRoot: string,
  xmlPath: string,
  cabinetId: string,
  clientId: string,
): Promise<{ stdout: string; stderr: string; code: number }> {
  return new Promise((resolve) => {
    const python = pickPython(repoRoot);
    // Le CLI worker/scripts/import_camt.py utilise --client-id pour le cabinet
    // et --mandant pour le sous-mandant (cf signature CLI Sprint 1).
    const args = [
      path.join("worker", "scripts", "import_camt.py"),
      "--client-id",
      cabinetId,
      "--mandant",
      clientId,
      "--file",
      xmlPath,
    ];
    const child = spawn(python, args, {
      cwd: repoRoot,
      env: { ...process.env },
    });
    let stdout = "";
    let stderr = "";
    child.stdout.on("data", (d) => {
      stdout += d.toString();
    });
    child.stderr.on("data", (d) => {
      stderr += d.toString();
    });
    child.on("close", (code) => {
      resolve({ stdout, stderr, code: code ?? -1 });
    });
  });
}

function parseImportSummary(stdout: string): {
  iban: string;
  total: number;
  inserted: number;
  duplicates: number;
} | null {
  // Le script import_camt.py imprime sur stdout au format :
  //   IBAN          : CHxxx
  //   transactions  : N
  //   ↳ inserted    : M
  //   ↳ duplicates  : K
  const ibanM = stdout.match(/IBAN\s*:\s*([A-Z0-9]+)/);
  const totalM = stdout.match(/transactions\s*:\s*(\d+)/);
  const insM = stdout.match(/inserted\s*:\s*(\d+)/);
  const dupM = stdout.match(/duplicates\s*:\s*(\d+)/);
  if (!totalM || !insM || !dupM) return null;
  return {
    iban: ibanM?.[1] ?? "?",
    total: Number(totalM[1]),
    inserted: Number(insM[1]),
    duplicates: Number(dupM[1]),
  };
}

export async function uploadAndImportCamt053(
  _prev: Camt053ImportResult | undefined,
  formData: FormData,
): Promise<Camt053ImportResult> {
  let tempFilePath: string | null = null;
  try {
    const cabinetId = readNonEmpty(formData, "__cabinetId");
    const clientId = (formData.get("__clientId") as string) || cabinetId;
    const file = formData.get("file");
    if (!(file instanceof File)) {
      throw new Error("fichier manquant (clé 'file')");
    }
    if (file.size === 0) {
      throw new Error("fichier vide");
    }

    const repoRoot = findRepoRoot();
    const tmpDir = fs.mkdtempSync(path.join(os.tmpdir(), "fiduciaire-camt-"));
    tempFilePath = path.join(tmpDir, file.name || "camt.xml");
    const buffer = Buffer.from(await file.arrayBuffer());
    fs.writeFileSync(tempFilePath, buffer);

    const result = await runImportCamt(
      repoRoot,
      tempFilePath,
      cabinetId,
      clientId,
    );

    if (result.code !== 0) {
      const tail = result.stderr.trim().split("\n").slice(-3).join("\n");
      throw new Error(`import_camt.py exit ${result.code} : ${tail}`);
    }

    const summary = parseImportSummary(result.stdout);
    if (!summary) {
      throw new Error(
        `summary illisible (stdout=${result.stdout.slice(-200)})`,
      );
    }

    revalidatePath("/bank");
    revalidatePath(`/clients/${cabinetId}`);

    return {
      ok: true,
      cabinet_id: cabinetId,
      client_id: clientId,
      iban: summary.iban,
      transactions_total: summary.total,
      transactions_inserted: summary.inserted,
      transactions_duplicates: summary.duplicates,
    };
  } catch (err) {
    if (err instanceof Error) return { ok: false, error: err.message };
    return { ok: false, error: String(err) };
  } finally {
    if (tempFilePath) {
      try {
        fs.rmSync(path.dirname(tempFilePath), {
          recursive: true,
          force: true,
        });
      } catch {
        // ignore cleanup errors
      }
    }
  }
}
