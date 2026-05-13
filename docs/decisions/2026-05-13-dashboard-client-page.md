# Décision — Dashboard `/clients/[client_id]` Sprint 2 §3.10 Phase 1

**Date :** 2026-05-13
**Sprint :** 2 §3.10 Phase 1 (Session 8)
**Statut :** Actée et livrée (5 smoke tests TS verts + build Next.js OK + 322 Python toujours verts).

## Contexte

Le brief Session 8 demande 3 pages dashboard (`/clients/[id]`, `/audit`,
`/bank`). Priorité absolue selon §5 = `/clients/[client_id]` car UX critique
install femme Gravosig début juin. Les 2 autres pages peuvent être reportées
Session 9.

Session 8 livre **Phase 1 uniquement** (page client + actions sur anomalies).
Phases 2-3 reportées Session 9.

## Décisions

### 1. Structure : 4 sections empilées + 4 stats cards

**Page `app/(poc)/clients/[client_id]/page.tsx`** Server Component
dynamique (`export const dynamic = "force-dynamic"`) :

1. **Header** : breadcrumb + client_id en mono + lien rapide vers entries
2. **4 stats cards** : Validées (mois) + En attente + Anomalies open + Documents (mois)
3. **Écritures récentes** (10 dernières) : table + lien "Voir toutes"
4. **Anomalies à traiter** : table avec boutons Résoudre / Faux positif (Server Actions)
5. **Rapprochement bancaire** (stats) + **Audit récent** (5 derniers) en 2 colonnes

Pas de tabs : on choisit vertical stacked pour scrollabilité + screenshots.

### 2. Multi-mandant strict via URL param `[client_id]`

Le `client_id` est dans l'URL (`/clients/pilote-jura-01`). Toutes les
queries DB le passent en filtre obligatoire (`WHERE client_id = ?`).

Les Server Actions sur anomalies vérifient l'ownership avant mutation
(pattern identique à `lib/db-poc-write.ts` Sprint 1) :
- `fetchAnomaly(db, id, clientId)` → raise `AnomalyNotFoundError` si pas
  d'ownership.

Test smoke `scripts/test-anomalies-write.ts` vérifie le cross-tenant
(résoudre une anomalie cabinet-B en tant que cabinet-A → fail).

### 3. Helpers lib séparés (read vs write)

- `lib/db-poc-clients.ts` (read-only) : 5 helpers (`getClientStats`,
  `listClientRecentEntries`, `listClientOpenAnomalies`,
  `listClientRecentAuditEvents`, `getClientBankStats`).
- `lib/db-poc-anomalies-write.ts` (write) : 2 mutations
  (`markAnomalyResolved`, `markAnomalyFalsePositive`) avec
  `AnomalyNotFoundError` + `AnomalyAlreadyClosedError`.

Pattern identique au split `db-poc.ts` (read) + `db-poc-write.ts` (write)
de Sprint 1. Maintient `withDb` / `withWriteDb` séparés (readonly vs WAL).

### 4. Decrypt colonnes chiffrées : `displayPossiblyEncrypted` placeholder

**Limitation Sprint 2 Phase 1 :** la lib Fernet n'est pas réimplémentée
côté Node.js. Si la DB est chiffrée (prod cabinet, Sprint 1 §3.4-bis), le
dashboard affiche `[chiffré]` à la place du contenu.

En **dev/test** : `FIDUCIAIRE_ENCRYPTION_DISABLED=true` côté worker
Python → DB en clair → dashboard affiche les valeurs normalement.

**Sprint 2 Phase 2 (Session 9)** : implémentation `lib/encryption-ts.ts`
avec :
- Read Keychain via `child_process` Python helper OU
- Implémentation Fernet TS pure (lib `fernet` npm + AES-128-CBC + HMAC-SHA256)
- Decrypt côté Server Component avant affichage

Décision pragmatique : ne pas bloquer Phase 1 sur cette dépendance non-triviale.

### 5. Composant `AnomalyActions` client component

Bouton "Résoudre" + bouton "Faux positif" via `useActionState` (React 19
+ Next 16 Server Actions). Hidden inputs `__anomalyId` + `__clientId`
pour le multi-mandant.

État : `pending` désactive les 2 boutons pendant submission. Si erreur,
message rouge inline.

Pas de modale de confirmation Sprint 2 Phase 1 — clic direct (à
améliorer Sprint 2 Phase 2 avec dialog shadcn si besoin UX).

### 6. Phases 2-3 reportées Session 9

**`/audit/page.tsx`** : reporté. Le dashboard `/(poc)/entries` actuel
montre déjà l'historique transitions (`entry_state_changes`). Le verify
audit chain peut être exécuté en CLI Python pendant l'install. Pas
bloqueur UX.

**`/bank/page.tsx`** : reporté. Le matcher auto (§3.9 Sprint 1) tourne
en CLI. Le manual link via UI peut attendre Session 9 ou Sprint 2 Phase 2.

Aligné avec brief §5 : "Peuvent être reportés Session 9 si nécessaire".

## Implémentation livrée

### Fichiers créés

- `lib/db-poc-clients.ts` (200 LoC) — 5 helpers read + `displayPossiblyEncrypted`
- `lib/db-poc-anomalies-write.ts` (90 LoC) — 2 mutations transitionnelles
- `app/(poc)/clients/[client_id]/page.tsx` (320 LoC) — Server Component complet
- `app/(poc)/clients/[client_id]/actions.ts` (90 LoC) — Server Actions
- `components/poc/AnomalyActions.tsx` (60 LoC) — Client Component avec useActionState
- `scripts/test-anomalies-write.ts` (130 LoC) — smoke test TS via tsx

### Tests livrés

- 5 smoke tests TS Sprint 2 Phase 1 (`test-anomalies-write.ts`) :
  resolve OK, false_positive OK, cross-tenant isolation, double-resolve
  bloqué, unknown id error
- Non-régression : 7 smoke TS Sprint 1 + 322 Python tests toujours verts
- Typecheck `tsc --noEmit` clean
- Build Next.js `npm run build` OK (route `/clients/[client_id]` dynamique)

## TODO Session 9+

1. **`lib/encryption-ts.ts`** : decrypt Fernet côté Node.js (Sprint 2 Phase 2)
2. **`/audit/page.tsx`** : verify_audit_chain + filtres + export texte
3. **`/bank/page.tsx`** : manual link + import CAMT.053 upload
4. **Tests UI Playwright** (vs smoke TS actuels) si besoin install validation
5. **Modale confirmation** sur Résoudre/Faux positif (UX)
6. **Pagination anomalies** si N grand
