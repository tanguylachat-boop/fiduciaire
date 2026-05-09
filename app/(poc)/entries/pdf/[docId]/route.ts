// Stream le PDF original d'un document, scope au mandant via accounting_entries.
// Sprint 0a : aucune auth user, mais isolation cross-tenant stricte.

import { NextRequest } from "next/server";
import { getDocumentArchivePathForEntry } from "@/lib/db-poc";
import fs from "node:fs";
import path from "node:path";

export const dynamic = "force-dynamic";

export async function GET(
  req: NextRequest,
  { params }: { params: Promise<{ docId: string }> },
) {
  const { docId } = await params;
  const id = Number(docId);
  if (!Number.isInteger(id) || id <= 0) {
    return new Response("Bad request", { status: 400 });
  }

  const clientId = req.nextUrl.searchParams.get("client");
  if (!clientId) {
    return new Response("client_id required", { status: 400 });
  }

  const archivePath = getDocumentArchivePathForEntry(id, clientId);
  if (!archivePath) {
    return new Response("Not found", { status: 404 });
  }

  // Resolve relative to repo root (DB stocke des chemins relatifs ou absolus selon le worker).
  const absPath = path.isAbsolute(archivePath)
    ? archivePath
    : path.join(process.cwd(), archivePath);

  // Sécurité : empêche path traversal hors de data/archive/.
  const allowedRoot = path.join(process.cwd(), "data", "archive");
  const resolved = path.resolve(absPath);
  if (!resolved.startsWith(path.resolve(allowedRoot))) {
    return new Response("Forbidden path", { status: 403 });
  }
  if (!fs.existsSync(resolved)) {
    return new Response("File missing on disk", { status: 410 });
  }

  const stat = fs.statSync(resolved);
  const stream = fs.createReadStream(resolved);
  return new Response(stream as unknown as ReadableStream, {
    status: 200,
    headers: {
      "Content-Type": "application/pdf",
      "Content-Length": String(stat.size),
      "Content-Disposition": `inline; filename="${path.basename(resolved)}"`,
      "Cache-Control": "private, max-age=0, must-revalidate",
    },
  });
}
