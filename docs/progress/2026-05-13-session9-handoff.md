# Session 9 — Handoff Option Z (Sprint 2 §3.10 Phases 1-3)

**Date :** 2026-05-13
**Branche :** `feature/sprint-0a-core` (continue Sprint 2)
**Statut :** Sprint 2 §3.10 **Phases 1, 2, 3 livrées**. Phase 4 (`/bank`) reportée Session 10.

---

## 1. Bilan modules livrés

### Sprint 2 §3.10 Phase 1 — `lib/encryption-ts.ts` (CRITIQUE prod)

| Fichier | LoC | Statut |
|---|---|---|
| `lib/encryption-ts.ts` | 200 | nouveau — Fernet pure `node:crypto`, Keychain macOS via subprocess |
| `lib/db-poc-clients.ts` | +5 | `listClientRecentEntries` decrypt auto |
| `lib/db-poc.ts` | +10 | `listAccountingEntries` + `getAccountingEntry` decrypt auto |
| `app/(poc)/clients/[client_id]/page.tsx` | -2 | retire wrapper `displayPossiblyEncrypted` |
| `scripts/test-encryption-ts.ts` | 220 | **10 cross-compat Python↔TS verts** |

**API publique :**
- `decryptColumnValue(value, cabinetId)` : throws EncryptionError si KO
- `decryptColumnValueSafe(value, cabinetId)` : never throws, fallback string
- `isEncryptedColumnValue(value)` : detection marker `enc:v1:`
- `isEncryptionDisabled()` : env var `FIDUCIAIRE_ENCRYPTION_DISABLED`

### Sprint 2 §3.10 Phase 2 — `lib/audit-log-ts.ts` (hook côté TS)

| Fichier | LoC | Statut |
|---|---|---|
| `lib/audit-log-ts.ts` | 180 | nouveau — chain SHA-256 + canonicalJsonPythonStyle |
| `lib/db-poc-anomalies-write.ts` | +30 | hook audit dans transitionAnomaly |
| `scripts/test-audit-log-ts.ts` | 230 | **6 cross-compat tests verts** |

**API publique :**
- `logAuditEvent(db, args)` : insert + chain hash automatique
- `computeAuditHash(args)` : hash SHA-256 compatible Python
- `canonicalJsonPythonStyle(value)` : `json.dumps(sort_keys=True)` équivalent
- `GENESIS_HASH` : "0" × 64
- `isoTimestampUtcMicro()` : timestamp Python-compat

### Sprint 2 §3.10 Phase 3 — `/audit/page.tsx`

| Fichier | LoC | Statut |
|---|---|---|
| `lib/db-poc-audit.ts` | 200 | helpers read + verifyAuditChain en pur TS |
| `app/(poc)/audit/page.tsx` | 250 | Server Component avec status chain + filtres + pagination |
| `scripts/test-audit-page.ts` | 130 | **4 smoke tests verts** |

**Features :**
- Status chain au top : ✅ VALID / ⚠️ BROKEN (verify on-page-load)
- Filtres : cabinet, entity_type, action (form GET)
- Pagination 50 par page
- Hash tronqué 12 chars affiché

### Sprint 2 §3.10 Phase 4 `/bank/page.tsx` — REPORTÉ Session 10

Complexité : upload XML + Server Action wrappant Python + drag/drop.
Matcher auto tourne déjà en CLI (`run_bank_matcher.py` Sprint 1).
Sans `/bank` dashboard, install pilote toujours possible via CLI.

---

## 2. Métriques tests

| Catégorie | Avant Session 9 | Après Session 9 | Delta |
|---|---:|---:|---:|
| Tests Python | 322 | 322 | 0 (régression flaky test_backup re-test OK) |
| Tests TS smoke | 12 | **32** | **+20** |
| encryption cross-compat | 0 | 10 | +10 |
| audit_log cross-compat | 0 | 6 | +6 |
| audit page lib | 0 | 4 | +4 |
| Typecheck `tsc --noEmit` | clean | **clean** | — |
| Build Next.js | OK | **OK** + 2 routes neuves | — |

**Tests cumulés** : 322 Python + 32 smoke TS = **354** tests passing.

---

## 3. Décisions techniques Session 9

[`2026-05-13-encryption-ts-cross-compat.md`](../decisions/2026-05-13-encryption-ts-cross-compat.md) :
- Fernet pure `node:crypto` (zéro dépendance npm)
- Keychain macOS via `security` subprocess + env var fallback
- `decryptColumnValueSafe` partout dans Server Components (never throws)
- `lib/audit-log-ts.ts` cross-compat chain hash 100% Python
- JSON canonique custom matchant `json.dumps(sort_keys=True)`
- `/bank` reporté Session 10 (complexité upload + wrap Python)

---

## 4. USER ACTION MAP — Tanguy avant Session 10

### Tester le decrypt en mode prod

```bash
# 1. Set la clé encryption pour pilote-jura-01 en Keychain (déjà fait Session 5)
python -c "
import keyring
from fiduciaire_worker.encryption import MasterKey
key = MasterKey.generate('pilote-jura-01')
keyring.set_password('fiduciaire', 'encryption-key-pilote-jura-01', key.value.decode())
print('Clé OK')
"

# 2. Migrate la DB pour chiffrer les colonnes existantes
cd worker && .venv/bin/python scripts/migrate_encrypt_columns.py \
  --client-id pilote-jura-01

# 3. Lancer le dashboard sans FIDUCIAIRE_ENCRYPTION_DISABLED
npm run dev

# 4. Ouvrir http://localhost:3000/clients/pilote-jura-01
# Les descriptions doivent s'afficher EN CLAIR (decrypt via Keychain auto).
```

### Tester l'audit chain dashboard

```bash
# 1. Faire quelques actions (validate/reject entries) pour générer des audits
# 2. Ouvrir http://localhost:3000/audit?client=pilote-jura-01
# 3. Status au top doit afficher "Chain intacte ✅"

# Test tampering (juste pour curiosité) :
sqlite3 data/fiduciaire.sqlite "UPDATE audit_log SET action='hacked' WHERE id=1"
# Reload page → status "Tampering détecté ⚠️"
# (puis rollback : restaurer depuis backup ou re-build)
```

### Préparer install femme Gravosig (rappel checklist complète)

Cf `sprint-1-complete.md` §🎯 + handoff Session 8 §4.

---

## 5. État global Sprint 2

| Module | Statut |
|---|---|
| §3.10 Phase 1 lib/encryption-ts.ts | ✅ **session 9** |
| §3.10 Phase 1 intégration decrypt | ✅ **session 9** |
| §3.10 Phase 2 lib/audit-log-ts.ts | ✅ **session 9** |
| §3.10 Phase 2 hook anomalies | ✅ **session 9** |
| §3.10 Phase 3 /audit/page.tsx | ✅ **session 9** |
| §3.10 Phase 4 /bank/page.tsx | ⏳ session 10 |
| Connecteur Winbiz API natif (post réception clé) | ⏳ Sprint 2 ultérieur |
| Crésus export | ⏳ Sprint 2 |
| Abacus AbaConnect | ⏳ Sprint 2 |
| Reporting mensuel | ⏳ Sprint 2 |
| Pré-bouclement automatique | ⏳ Sprint 3 |
| WhatsApp/Telegram bridge | ⏳ Sprint 3 |

---

## 6. Contraintes non-négociables respectées

| Contrainte | Vérification |
|---|---|
| **Cross-compat Python↔TS prouvée** | 10 tests encryption + 6 audit log avec génération Python via subprocess |
| Multi-mandant first-class | URL `/clients/[id]`, filtres `WHERE client_id=?`, ownership check, chains isolées par cabinet |
| Aucun appel LLM externe | OK |
| `.env` gitignored | OK (inchangé) |
| TDD strict | 20 smoke TS écrits AVANT les modules (chacun a son test cross-compat) |
| Zéro régression | 322 Python + 12 TS Sprint 1+S8 toujours verts |
| CLAUDE.md audit | Effectué. 354 tests, build OK, typecheck clean |

---

## 7. Commande de relance Session 10

```
/clear

[paste master prompt Sprint 2]

Reprends Sprint 2 §3.10 Phase 4 (/bank/page.tsx) + (optionnel) connecteur
Winbiz API natif si Tanguy a reçu la clé partenariat. Session 9 a livré
Phases 1-3 (encryption-ts cross-compat Python, audit-log-ts cross-compat,
/audit page). 354 tests verts (322 Python + 32 smoke TS).

Avant Session 10, Tanguy doit avoir testé /clients/pilote-jura-01 ET
/audit en local avec DB chiffrée + Keychain set (cf §4 USER ACTION MAP).
```
