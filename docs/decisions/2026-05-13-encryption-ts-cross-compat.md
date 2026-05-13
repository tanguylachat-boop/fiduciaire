# Décision — lib/encryption-ts.ts cross-compat Python Sprint 2 §3.10 Phase 1

**Date :** 2026-05-13
**Sprint :** 2 §3.10 Phase 1 (Session 9)
**Statut :** Actée et livrée (10 cross-compat tests verts + 6 audit log + 4 page).

## Contexte

Session 8 a livré la page `/clients/[client_id]` avec un placeholder
`displayPossiblyEncrypted` qui retournait `[chiffré]` pour les valeurs
préfixées `enc:v1:` (cf decision Session 6 §3.4-bis). Limitation
critique : dashboard inutilisable en prod cabinet (toutes les
descriptions/reasoning/vendor_name affichaient `[chiffré]`).

Session 9 implémente le **decrypt Fernet côté Node.js** + un **audit
log côté TS** avec chain hash SHA-256 100% compatible avec
`audit_log.py` (Session 5).

## Décisions

### 1. Fernet implémenté en `node:crypto` pur (zéro dépendance npm)

**`lib/encryption-ts.ts`** réimplémente Fernet via `node:crypto` :
- AES-128-CBC + HMAC-SHA256 + PKCS7
- base64url encoding (supporté nativement par Node Buffer)
- timingSafeEqual pour HMAC comparison
- Format on-disk identique au Python `cryptography` lib

Pourquoi pas la lib npm `fernet` :
- 1 dépendance externe en moins (cohérent stack repo)
- Implémentation 130 LoC très lisible
- Tests cross-compat garantissent compatibilité format

### 2. Résolution clé : Keychain macOS via subprocess + env fallback

**Ordre :**
1. `security find-generic-password -s fiduciaire -a encryption-key-<cabinet_id> -w`
   (macOS uniquement)
2. Env var `FIDUCIAIRE_ENCRYPTION_KEY_<CABINET_NORMALIZED>` (dev/test)
3. Throw `KeyNotFoundError`

**Cache in-memory** : `_keyCache` Map pour éviter de spawn `security`
à chaque decrypt (perf Server Components).

**Note Linux/Windows** : Keychain inaccessible → env var seul. Pour
serveur Linux, prévoir Vault / fichier chiffré (Sprint 2+).

### 3. `decryptColumnValue` vs `decryptColumnValueSafe`

- **`decryptColumnValue`** : throw `EncryptionError` si KO (clé absente,
  HMAC invalide, tampering). Pour code applicatif qui doit gérer l'erreur.
- **`decryptColumnValueSafe`** : never throws, retourne `[clé absente]`
  ou `[chiffré]` en fallback. **Utilisé partout dans les Server
  Components** pour ne pas crash sur une row corrompue.

### 4. Intégration silencieuse dans helpers DB existants

Modifié `lib/db-poc.ts` (`listAccountingEntries`, `getAccountingEntry`)
et `lib/db-poc-clients.ts` (`listClientRecentEntries`) pour decrypt
automatiquement `description` + `reasoning` avant retour.

L'appelant (Server Component) reçoit les valeurs claires sans modification.

### 5. Mode disabled compatible Sprint 1

`FIDUCIAIRE_ENCRYPTION_DISABLED=true` → `decryptColumnValue` :
- Retourne tel quel pour les valeurs sans préfixe (back-compat clair)
- Tente quand même de déchiffrer si la clé est dispo en env
  (utile transition dev → prod)

### 6. Audit log côté TS (`lib/audit-log-ts.ts`)

Cross-compat chain hash 100% avec Python `audit_log.py`:
- Séparateur `\x1f` (Unit Separator)
- `prevHash || cabinetId || userId || ts || entityType || entityId || action || beforeJson || afterJson`
- SHA-256 hex

**JSON canonique** : implémentation maison `canonicalJsonPythonStyle`
qui produit le même output que `json.dumps(sort_keys=True, ensure_ascii=False)` :
- keys triées récursivement
- séparateurs `, ` et `: ` (avec espaces, contrairement à JSON.stringify natif)
- utf-8 natif (pas d'échappement Unicode)

**Test cross-compat hash vérifié** : `computeAuditHash` TS vs
`_compute_hash` Python avec mêmes inputs → mêmes 64 chars hex.

### 7. Hook audit_log dans `markAnomaly*` TS

`lib/db-poc-anomalies-write.ts` étendu :
- `transitionAnomaly` interne factorisé
- Après UPDATE anomalies, appelle `logAuditEvent` (silent skip si table
  absente, back-compat)
- Action : `anomaly_resolved` ou `anomaly_false_positive`
- before/after : `{state}` / `{state, reason}`

### 8. Page `/audit/page.tsx` Server Component

Affiche les events filtrés + status chain au top :
- ✅ "Chain intacte" si verify_audit_chain OK
- ⚠️ "Tampering détecté" + entity_id + raison sinon
- Filtres : cabinet, entity_type, action (form GET)
- Pagination 50 par page

Pas de bouton "Vérifier" séparé : verify run on-page-load (perf OK pour
quelques milliers d'events Sprint 1).

Pas d'export PDF Sprint 2 Phase 3 (placeholder reporté Sprint 2+).

### 9. `/bank/page.tsx` reporté Session 10

Complexité : upload XML + Server Action wrappant Python `import_camt053_file`
+ 2 colonnes + match manuel. Le matcher auto tourne déjà en CLI Sprint 1.
Sans dashboard `/bank`, l'install femme Gravosig peut toujours fonctionner
(matcher CLI mensuel).

## Tests livrés (20 smoke TS)

`test-encryption-ts.ts` (10) :
- ASCII roundtrip Python encrypt → TS decrypt
- UTF-8 français
- Long string 200 chars
- Mauvaise clé → EncryptionError
- Valeur sans marker → passthrough
- isEncryptedColumnValue detection
- Mode disabled → no-op
- null/undefined safe
- decryptColumnValueSafe sans clé → fallback string
- Multi-mandant : clé A ne déchiffre pas B

`test-audit-log-ts.ts` (6) :
- canonicalJsonPythonStyle == Python json.dumps(sort_keys)
- computeAuditHash == Python `_compute_hash`
- logAuditEvent insert + GENESIS prev_hash
- 2 events consécutifs : chain lié
- markAnomalyResolved → audit_log créé
- Multi-mandant chains isolées

`test-audit-page.ts` (4) :
- verifyAuditChain VALID après inserts
- BROKEN après tampering
- listAuditEvents avec filtres + pagination
- Multi-mandant isolation

## TODO Session 10

1. **`/bank/page.tsx`** : 2 colonnes (transactions non matchées | factures
   impayées) + match manuel (Server Action `manuallyLinkTransaction`)
   + upload CAMT.053
2. **Server Action wrapping Python** : pattern pour upload CAMT et
   match manuel
3. **Export PDF audit** (lib `pdfkit` ou `puppeteer`) — Sprint 2+
4. **Decrypt côté `/entries/[id]`** pour le reasoning si non encore fait
