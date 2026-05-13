// Decrypt Fernet côté Node.js — Sprint 2 §3.10 Phase 2 (Session 9).
//
// Cross-compat avec `worker/src/fiduciaire_worker/encryption.py` (Sprint 1
// §3.4-bis Session 6). Format de stockage des colonnes texte sensibles :
//   "enc:v1:" + base64url(version || timestamp || iv || ciphertext || hmac)
//
// Spec Fernet (RFC informel) :
//   - version    : 1 byte = 0x80
//   - timestamp  : 8 bytes big-endian (Unix seconds)
//   - iv         : 16 bytes (AES-128-CBC IV, aléatoire par token)
//   - ciphertext : variable (PKCS7 padded, multiple de 16)
//   - hmac       : 32 bytes (HMAC-SHA256)
//
// Clé Fernet = 32 bytes base64url (44 chars) :
//   - bytes[0..16]  : signing_key (HMAC-SHA256)
//   - bytes[16..32] : encryption_key (AES-128-CBC)
//
// Résolution de la clé maître par cabinet (ordre) :
//   1. Keychain macOS : `security find-generic-password -s fiduciaire \
//                         -a encryption-key-<cabinet_id> -w`
//   2. Env var `FIDUCIAIRE_ENCRYPTION_KEY_<CABINET_NORMALIZED>`
//   3. Throw KeyNotFoundError
//
// Mode dev : `FIDUCIAIRE_ENCRYPTION_DISABLED=true` → no-op.

import { createDecipheriv, createHmac, timingSafeEqual } from "node:crypto";
import { execFileSync } from "node:child_process";

export const COLUMN_MARKER = "enc:v1:";
const FERNET_VERSION = 0x80;

export class EncryptionError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "EncryptionError";
  }
}

export class KeyNotFoundError extends EncryptionError {
  constructor(cabinetId: string) {
    super(`Clé encryption introuvable pour cabinet=${cabinetId}`);
    this.name = "KeyNotFoundError";
  }
}

// --- Disabled mode ---------------------------------------------------------

export function isEncryptionDisabled(): boolean {
  const v = process.env.FIDUCIAIRE_ENCRYPTION_DISABLED;
  return typeof v === "string" && v.toLowerCase() === "true";
}

// --- Marker detection ------------------------------------------------------

export function isEncryptedColumnValue(value: string | null | undefined): boolean {
  return typeof value === "string" && value.startsWith(COLUMN_MARKER);
}

// --- Key resolution --------------------------------------------------------

function normalizeCabinetForEnv(cabinetId: string): string {
  return cabinetId.replace(/-/g, "_").replace(/\./g, "_").toUpperCase();
}

const _keyCache = new Map<string, Buffer>();

function tryKeychain(cabinetId: string): Buffer | null {
  // macOS only ; sur autres OS, retourne null silencieusement.
  if (process.platform !== "darwin") return null;
  try {
    const out = execFileSync(
      "security",
      [
        "find-generic-password",
        "-s", "fiduciaire",
        "-a", `encryption-key-${cabinetId}`,
        "-w",
      ],
      { encoding: "utf8", stdio: ["ignore", "pipe", "ignore"] },
    );
    const trimmed = out.trim();
    if (!trimmed) return null;
    // La clé en Keychain est en base64url (44 chars ASCII), telle quelle
    return Buffer.from(trimmed, "ascii");
  } catch {
    // Keychain non accessible ou clé absente
    return null;
  }
}

function tryEnv(cabinetId: string): Buffer | null {
  const varName = `FIDUCIAIRE_ENCRYPTION_KEY_${normalizeCabinetForEnv(cabinetId)}`;
  const val = process.env[varName];
  if (!val) return null;
  return Buffer.from(val, "ascii");
}

/**
 * Résout la clé maître base64url ASCII pour un cabinet.
 * Throws KeyNotFoundError si introuvable.
 */
export function getMasterKey(cabinetId: string): Buffer {
  const cached = _keyCache.get(cabinetId);
  if (cached) return cached;
  const fromKc = tryKeychain(cabinetId);
  if (fromKc) {
    _keyCache.set(cabinetId, fromKc);
    return fromKc;
  }
  const fromEnv = tryEnv(cabinetId);
  if (fromEnv) {
    _keyCache.set(cabinetId, fromEnv);
    return fromEnv;
  }
  throw new KeyNotFoundError(cabinetId);
}

/** Reset cache (utile pour tests). */
export function _clearKeyCache(): void {
  _keyCache.clear();
}

// --- Fernet decrypt --------------------------------------------------------

function splitFernetKey(keyAscii: Buffer): { signing: Buffer; encryption: Buffer } {
  // keyAscii = "base64url-44-chars" → decode 32 bytes raw
  const raw = Buffer.from(keyAscii.toString("ascii"), "base64url");
  if (raw.length !== 32) {
    throw new EncryptionError(
      `clé Fernet invalide : attendu 32 bytes, reçu ${raw.length}`,
    );
  }
  return {
    signing: raw.subarray(0, 16),
    encryption: raw.subarray(16, 32),
  };
}

function pkcs7Unpad(buf: Buffer): Buffer {
  if (buf.length === 0) {
    throw new EncryptionError("pkcs7 unpad : buffer vide");
  }
  const pad = buf[buf.length - 1];
  if (pad === 0 || pad > 16 || pad > buf.length) {
    throw new EncryptionError(`pkcs7 unpad : pad byte invalide=${pad}`);
  }
  // Validate all padding bytes match (constant-time pas critique pour unpad)
  for (let i = buf.length - pad; i < buf.length; i++) {
    if (buf[i] !== pad) {
      throw new EncryptionError("pkcs7 unpad : padding mismatch");
    }
  }
  return buf.subarray(0, buf.length - pad);
}

/**
 * Decrypt un token Fernet brut (sans le préfixe "enc:v1:").
 * @param tokenB64url Base64url du token binaire complet
 * @param keyAscii    Clé Fernet base64url 44 chars (ASCII)
 */
function fernetDecrypt(tokenB64url: string, keyAscii: Buffer): string {
  const tok = Buffer.from(tokenB64url, "base64url");
  // 1 (version) + 8 (timestamp) + 16 (iv) + N (ciphertext, multiple 16) + 32 (hmac)
  // Min N = 16 (1 bloc AES)
  if (tok.length < 1 + 8 + 16 + 16 + 32) {
    throw new EncryptionError(
      `token Fernet trop court : ${tok.length} bytes (min 73)`,
    );
  }
  const version = tok[0];
  if (version !== FERNET_VERSION) {
    throw new EncryptionError(
      `version Fernet inattendue : 0x${version.toString(16)} (attendu 0x80)`,
    );
  }
  const ivStart = 1 + 8;
  const ivEnd = ivStart + 16;
  const hmacStart = tok.length - 32;
  const iv = tok.subarray(ivStart, ivEnd);
  const ciphertext = tok.subarray(ivEnd, hmacStart);
  const macStored = tok.subarray(hmacStart);

  if (ciphertext.length === 0 || ciphertext.length % 16 !== 0) {
    throw new EncryptionError(
      `ciphertext length non-multiple de 16 : ${ciphertext.length}`,
    );
  }

  const { signing, encryption } = splitFernetKey(keyAscii);

  // HMAC sur version || timestamp || iv || ciphertext
  const macInput = tok.subarray(0, hmacStart);
  const macComputed = createHmac("sha256", signing).update(macInput).digest();
  if (
    macComputed.length !== macStored.length ||
    !timingSafeEqual(macComputed, macStored)
  ) {
    throw new EncryptionError("HMAC Fernet invalide (mauvaise clé ou tampering)");
  }

  const decipher = createDecipheriv("aes-128-cbc", encryption, iv);
  decipher.setAutoPadding(false);
  const padded = Buffer.concat([decipher.update(ciphertext), decipher.final()]);
  return pkcs7Unpad(padded).toString("utf8");
}

// --- Public API ------------------------------------------------------------

/**
 * Décrypte une valeur de colonne. Retourne :
 * - `null` si value est null
 * - value tel quel si pas de préfixe `enc:v1:` (back-compat clair)
 * - value tel quel si `FIDUCIAIRE_ENCRYPTION_DISABLED=true`
 * - le texte clair sinon
 *
 * Throws EncryptionError si déchiffrement échoue (mauvaise clé, tampering).
 */
export function decryptColumnValue(
  value: string | null | undefined,
  cabinetId: string,
): string | null {
  if (value === null || value === undefined) return null;
  if (typeof value !== "string") return String(value);
  if (!isEncryptedColumnValue(value)) return value;
  if (isEncryptionDisabled()) {
    // Mode dev : on tente quand même de déchiffrer si la clé est dispo,
    // sinon on retourne tel quel
    try {
      const key = getMasterKey(cabinetId);
      const token = value.slice(COLUMN_MARKER.length);
      return fernetDecrypt(token, key);
    } catch {
      return value;
    }
  }
  const key = getMasterKey(cabinetId);
  const token = value.slice(COLUMN_MARKER.length);
  return fernetDecrypt(token, key);
}

/**
 * Variante safe : ne throw jamais. Retourne `[decrypt-error]` si KO en prod,
 * `[chiffré]` si la clé est absente. Utile pour Server Components qui ne
 * doivent pas crash sur une row corrompue.
 */
export function decryptColumnValueSafe(
  value: string | null | undefined,
  cabinetId: string,
): string {
  if (value === null || value === undefined) return "";
  if (typeof value !== "string") return String(value);
  if (!isEncryptedColumnValue(value)) return value;
  try {
    const result = decryptColumnValue(value, cabinetId);
    return result ?? "";
  } catch (err) {
    if (err instanceof KeyNotFoundError) return "[clé absente]";
    return "[chiffré]";
  }
}
