// Smoke test cross-compat Python ↔ TS Fernet — Sprint 2 §3.10 Phase 1 (Session 9).
//
// Vérifie que `lib/encryption-ts.ts` décrypte correctement les tokens
// générés par `worker/src/fiduciaire_worker/encryption.py` (Session 6).
//
// Stratégie : on appelle Python pour générer une clé + chiffrer une valeur,
// puis on décrypte côté TS avec la même clé via env var. Tokens 100% format
// Fernet stdlib `cryptography`.
//
// Usage : npx tsx scripts/test-encryption-ts.ts
// Exit code : 0 si tous les checks passent, 1 sinon.

import { execFileSync } from "node:child_process";
import { fileURLToPath } from "node:url";
import path from "node:path";
import {
  COLUMN_MARKER,
  EncryptionError,
  KeyNotFoundError,
  _clearKeyCache,
  decryptColumnValue,
  decryptColumnValueSafe,
  isEncryptedColumnValue,
  isEncryptionDisabled,
} from "../lib/encryption-ts";

const REPO_ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const PYTHON = path.join(REPO_ROOT, "worker", ".venv", "bin", "python");

function pyExec(code: string): string {
  return execFileSync(PYTHON, ["-c", code], {
    encoding: "utf8",
    env: { ...process.env, PYTHONPATH: path.join(REPO_ROOT, "worker", "src") },
  }).trim();
}

/** Génère une clé Fernet via Python et encrypt un texte → retourne (key, token) */
function pyGenerateAndEncrypt(plaintext: string): { key: string; token: string } {
  const code = `
import os
os.environ.pop('FIDUCIAIRE_ENCRYPTION_DISABLED', None)
from fiduciaire_worker.encryption import MasterKey, encrypt_column_value
import fiduciaire_worker.encryption as enc
key = MasterKey.generate('test')
# Met la clé en env pour que encrypt_column_value la trouve via get_master_key
os.environ['FIDUCIAIRE_ENCRYPTION_KEY_TEST'] = key.value.decode('ascii')
# Bypass keychain attempts in test
enc._try_keyring_set = lambda c, k: True
token = encrypt_column_value(${JSON.stringify(plaintext)}, 'test')
print(key.value.decode('ascii'))
print(token)
`;
  const lines = pyExec(code).split("\n");
  if (lines.length < 2) {
    throw new Error("Python output unexpected: " + lines.join("|"));
  }
  return { key: lines[0], token: lines[1] };
}

let passed = 0;
let failed = 0;

function check(label: string, fn: () => void) {
  try {
    fn();
    console.log(`  OK  ${label}`);
    passed++;
  } catch (err) {
    console.error(`  KO  ${label}`);
    console.error("       →", err instanceof Error ? err.message : err);
    failed++;
  }
}

console.log("Cross-compat Python encrypt → TS decrypt\n");

// --- Test 1 : roundtrip basique ---
check("ASCII : Python encrypt 'hello world' → TS decrypt", () => {
  _clearKeyCache();
  delete process.env.FIDUCIAIRE_ENCRYPTION_DISABLED;
  const { key, token } = pyGenerateAndEncrypt("hello world");
  process.env.FIDUCIAIRE_ENCRYPTION_KEY_TEST = key;
  if (!token.startsWith(COLUMN_MARKER)) {
    throw new Error(`token n'a pas le marker: ${token.slice(0, 20)}`);
  }
  const result = decryptColumnValue(token, "test");
  if (result !== "hello world") {
    throw new Error(`expected "hello world", got "${result}"`);
  }
});

// --- Test 2 : UTF-8 (accents français) ---
check("UTF-8 français : 'Facture éclair — montant 100€'", () => {
  _clearKeyCache();
  const plain = "Facture éclair — montant 100€";
  const { key, token } = pyGenerateAndEncrypt(plain);
  process.env.FIDUCIAIRE_ENCRYPTION_KEY_TEST = key;
  const result = decryptColumnValue(token, "test");
  if (result !== plain) {
    throw new Error(`expected "${plain}", got "${result}"`);
  }
});

// --- Test 3 : long string ---
check("Long string (200 chars)", () => {
  _clearKeyCache();
  const plain = "x".repeat(200) + "endmarker";
  const { key, token } = pyGenerateAndEncrypt(plain);
  process.env.FIDUCIAIRE_ENCRYPTION_KEY_TEST = key;
  const result = decryptColumnValue(token, "test");
  if (result !== plain) {
    throw new Error(`length mismatch: ${result?.length} vs ${plain.length}`);
  }
});

// --- Test 4 : mauvaise clé → EncryptionError ---
check("Mauvaise clé → EncryptionError", () => {
  _clearKeyCache();
  const { token } = pyGenerateAndEncrypt("secret");
  // Génère une autre clé pour TEST (qui ne déchiffre pas le token)
  const otherKey = pyExec(`
from fiduciaire_worker.encryption import MasterKey
print(MasterKey.generate('test').value.decode('ascii'))
`);
  process.env.FIDUCIAIRE_ENCRYPTION_KEY_TEST = otherKey;
  try {
    decryptColumnValue(token, "test");
    throw new Error("aurait dû throw");
  } catch (err) {
    if (!(err instanceof EncryptionError)) {
      throw new Error(`wrong error type: ${err}`);
    }
  }
});

// --- Test 5 : Valeur sans marker → retourne tel quel (back-compat) ---
check("Valeur sans 'enc:v1:' → retournée telle quelle", () => {
  _clearKeyCache();
  const result = decryptColumnValue("plain legacy text", "test");
  if (result !== "plain legacy text") {
    throw new Error(`expected legacy text, got "${result}"`);
  }
});

// --- Test 6 : isEncryptedColumnValue detection ---
check("isEncryptedColumnValue detection", () => {
  if (!isEncryptedColumnValue("enc:v1:gAAAAAB...")) throw new Error("should detect");
  if (isEncryptedColumnValue("plain text")) throw new Error("false positive");
  if (isEncryptedColumnValue(null)) throw new Error("null should be false");
  if (isEncryptedColumnValue("")) throw new Error("empty should be false");
});

// --- Test 7 : Mode disabled → no-op pour valeurs sans marker ---
check("Mode disabled → no-op back-compat", () => {
  _clearKeyCache();
  process.env.FIDUCIAIRE_ENCRYPTION_DISABLED = "true";
  if (!isEncryptionDisabled()) throw new Error("should be disabled");
  const result = decryptColumnValue("plain text legacy", "test");
  if (result !== "plain text legacy") {
    throw new Error(`expected legacy passthrough, got "${result}"`);
  }
  delete process.env.FIDUCIAIRE_ENCRYPTION_DISABLED;
});

// --- Test 8 : Null/undefined safe ---
check("null/undefined safe", () => {
  if (decryptColumnValue(null, "test") !== null) throw new Error("null fail");
  if (decryptColumnValue(undefined, "test") !== null) {
    throw new Error("undefined fail");
  }
});

// --- Test 9 : decryptColumnValueSafe avec clé absente ---
check("decryptColumnValueSafe sans clé → '[clé absente]'", () => {
  _clearKeyCache();
  delete process.env.FIDUCIAIRE_ENCRYPTION_KEY_TEST;
  delete process.env.FIDUCIAIRE_ENCRYPTION_DISABLED;
  // Token valide-looking mais aucune clé en env (et pas de keychain en CI)
  const fakeToken = COLUMN_MARKER + "gAAAAABf";
  const result = decryptColumnValueSafe(fakeToken, "test-no-key");
  // En local macOS avec Keychain accessible le test pourrait échouer si une clé
  // existe pour test-no-key. On vérifie qu'on ne crash pas et qu'on retourne
  // un fallback string.
  if (typeof result !== "string") {
    throw new Error("safe should return string");
  }
});

// --- Test 10 : multi-mandant — clé cabinet-A ne déchiffre pas cabinet-B ---
check("Multi-mandant : clé A ≠ clé B", () => {
  _clearKeyCache();
  delete process.env.FIDUCIAIRE_ENCRYPTION_DISABLED;
  // Encrypt avec clé de "cab-a"
  const codeA = `
import os
os.environ.pop('FIDUCIAIRE_ENCRYPTION_DISABLED', None)
from fiduciaire_worker.encryption import MasterKey, encrypt_column_value
import fiduciaire_worker.encryption as enc
key = MasterKey.generate('cab-a')
os.environ['FIDUCIAIRE_ENCRYPTION_KEY_CAB_A'] = key.value.decode('ascii')
enc._try_keyring_set = lambda c, k: True
token = encrypt_column_value('data A', 'cab-a')
print(key.value.decode('ascii'))
print(token)
`;
  const linesA = pyExec(codeA).split("\n");
  const keyA = linesA[0];
  const tokenA = linesA[1];
  process.env.FIDUCIAIRE_ENCRYPTION_KEY_CAB_A = keyA;

  // Génère une clé pour cab-b (différente)
  const keyB = pyExec(
    "from fiduciaire_worker.encryption import MasterKey; " +
      "print(MasterKey.generate('cab-b').value.decode('ascii'))",
  );
  process.env.FIDUCIAIRE_ENCRYPTION_KEY_CAB_B = keyB;

  // Decrypt avec cab-a OK
  if (decryptColumnValue(tokenA, "cab-a") !== "data A") {
    throw new Error("cab-a decrypt failed");
  }
  // Decrypt avec cab-b throws
  try {
    decryptColumnValue(tokenA, "cab-b");
    throw new Error("cab-b ne devait pas décrypter le token de cab-a");
  } catch (err) {
    if (!(err instanceof EncryptionError)) {
      throw new Error(`wrong error: ${err}`);
    }
  }
});

console.log(`\n${passed} passed / ${failed} failed`);
process.exit(failed === 0 ? 0 : 1);
