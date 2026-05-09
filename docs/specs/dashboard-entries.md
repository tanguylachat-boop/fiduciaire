# Spec dashboard `/(poc)/entries` — Sprint 0a

**Cible :** session 2 (2026-05-09).
**Pré-requis :** modules core Python livrés en session 1 (cf `docs/progress/2026-05-09-sprint-0a-v0.md`), tables `accounting_entries` + `entry_state_changes` initialisées par `accounting_schema.init_accounting_schema(conn)`.

## 1. Contraintes

- Next.js 16 App Router, React 19. App à la racine du repo (`app/`, `lib/`, `components/`), **pas** dans `dashboard/`.
- Server Components par défaut, Client Components uniquement pour interactions formulaire.
- SQLite local via `better-sqlite3`. Read-only pour la liste, read-write isolé pour les Server Actions.
- **Multi-mandant strict** : toute requête filtrée par `client_id`. Sélecteur header `?client=` (search param) avec fallback premier mandant.
- **Aucune écriture vers Bexio** depuis ce dashboard. État conservé en local SQLite.

## 2. Routes

```
app/(poc)/entries/page.tsx          # liste paginée + filtres
app/(poc)/entries/[id]/page.tsx     # détail 2 colonnes PDF + form
app/(poc)/entries/actions.ts        # 'use server' : validate / correct / reject
app/(poc)/entries/pdf/[docId]/route.ts   # streaming binaire PDF (pour viewer iframe)
```

## 3. Composants

```
components/poc/EntryFilters.tsx     # client component, écrit dans search params
components/poc/EntryListRow.tsx     # ligne liste — link vers /entries/[id]
components/poc/EntryEditor.tsx      # client component, formulaire éditable + 3 boutons
components/poc/PdfViewer.tsx        # iframe vers /entries/pdf/[docId]
components/poc/ClientSelector.tsx   # sélecteur multi-mandant header
```

## 4. Read-side (lib/db-poc.ts étendu)

```ts
listClients(): { client_id: string; n_entries: number }[]
listAccountingEntries(filters: EntryFilters): EntryRow[]
getAccountingEntry(id: number, clientId: string): EntryDetail | null
listEntryHistory(id: number, clientId: string): StateChangeRow[]
getDocumentForEntry(entryId: number, clientId: string): DocumentRow | null
```

`EntryFilters` : `clientId` (obligatoire), `state?`, `confidenceMin?`, `dateFrom?`, `dateTo?`, `amountMin?`, `amountMax?`, `limit`, `offset`.

## 5. Write-side (lib/db-poc-write.ts — nouveau)

Connexion SQLite read-write avec WAL pour cohabiter avec le worker Python.

```ts
validateEntry(id, clientId, userId): void
correctEntry(id, clientId, userId, payload, diff): void  // state → 'validated'
rejectEntry(id, clientId, userId, reason): void          // reason obligatoire
```

Chaque mutation est **transactionnelle** :
1. SELECT current state with `WHERE id=? AND client_id=?` (cross-tenant block).
2. Vérifie transition autorisée (cf `workflow_states.py` : `proposed → validated`, `proposed → rejected`).
3. UPDATE `accounting_entries` SET state, updated_at, optionally modified fields.
4. INSERT INTO `entry_state_changes` (from_state, to_state, user_id, reason).
5. COMMIT.

Cross-tenant : si `client_id` ne correspond pas → throw `EntryNotFoundError` (pas `Forbidden` — évite l'oracle d'existence).

## 6. Server Actions (app/(poc)/entries/actions.ts)

```ts
'use server'

export async function validateEntry(formData: FormData) { ... }
export async function correctEntry(formData: FormData) { ... }
export async function rejectEntry(formData: FormData) { ... }
```

Lecture du `client_id` : depuis le formulaire (caché) + revérification en DB pour bloquer manipulation.
`revalidatePath('/(poc)/entries')` après chaque action.

## 7. Tests

- Vitest unit sur `db-poc-write.ts` :
  - `test_validate_changes_state` : entry proposed → validate → state=validated, ligne dans entry_state_changes.
  - `test_correct_updates_fields_and_state` : entry proposed → correct(payload) → fields updated, state=validated.
  - `test_reject_requires_reason` : reject sans raison → throw.
  - `test_cross_tenant_validate_blocked` : entry du client A, tenter validate avec client_id=B → throw EntryNotFoundError.
  - `test_double_validate_blocked` : entry validated → re-validate → throw InvalidTransition.
- Smoke run manuel : `npm run dev` + curl sur `/(poc)/entries`, page liste + détail.

## 8. PDF viewer (route handler)

`app/(poc)/entries/pdf/[docId]/route.ts` :
- Read-only.
- Vérifie que le `documentId` appartient bien à un entry du `client_id` actif (préviens leak cross-tenant).
- Stream le binaire `data/archive/<sha256>.pdf` avec `Content-Type: application/pdf`.

## 9. Hors scope

- PDF.js custom render (l'iframe natif `<iframe src="/entries/pdf/[id]">` du navigateur suffit en Sprint 0a).
- Authentification user (Sprint 1, header `X-User-Id` provisoire en POC).
- Realtime (Sprint 1).
- Audit immutable hash chaîné (Sprint 1).

## 10. DOD

- [x] specs livrée (ce fichier)
- [ ] `lib/db-poc.ts` étendu + read functions
- [ ] `lib/db-poc-write.ts` créé + tests Vitest
- [ ] page liste + filtres + sélecteur mandant
- [ ] page détail 2 colonnes + 3 actions
- [ ] PDF route handler avec scope tenant
- [ ] smoke test `npm run build` passant
