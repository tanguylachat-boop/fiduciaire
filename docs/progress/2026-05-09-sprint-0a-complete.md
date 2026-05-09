# Sprint 0a — rapport de livraison complet (session 2)

**Date :** 2026-05-09
**Branche :** `feature/sprint-0a-core` (continuation session 1)
**Statut global :** **Phase 1 (dashboard) livrée. Phase 2 (Bexio sync) reportée — PAT absent du Keychain. Phase 4 (bench réel) reportée — RunPod non lancé cette session. Phase 5 (Loom) script prêt, enregistrement à faire par Tanguy.**

---

## 1. Bilan dashboard `/(poc)/entries`

### Livré

| Fichier | Lignes | Rôle |
|---|---|---|
| `lib/db-poc.ts` | +180 | Read-side : `listClients`, `listAccountingEntries`, `getAccountingEntry`, `listEntryHistory`, `getDocumentArchivePathForEntry` |
| `lib/db-poc-write.ts` | 195 | Write-side transactionnelle : `validateEntry`, `correctEntry`, `rejectEntry`, `reopenEntry`. Cohabitation Python via WAL mode. |
| `app/(poc)/entries/page.tsx` | 240 | Liste paginée + filtres (mandant, état, confiance, montants). Server Component. |
| `app/(poc)/entries/[id]/page.tsx` | 175 | Vue 2 colonnes — PDF iframe gauche / formulaire droite. Audit trail en bas. |
| `app/(poc)/entries/actions.ts` | 130 | Server Actions `validateEntryAction`, `correctEntryAction`, `rejectEntryAction` avec `useActionState`. |
| `app/(poc)/entries/pdf/[docId]/route.ts` | 60 | Stream PDF binaire scope au mandant via join `accounting_entries`. Path traversal bloqué. |
| `components/poc/EntryFilters.tsx` | 110 | Client component, écrit dans search params. |
| `components/poc/EntryEditor.tsx` | 350 | Client component, formulaire éditable + 3 actions. Forms parallèles (pas imbriquées). |
| `docs/specs/dashboard-entries.md` | — | Specs livrée. |

**Total : ~1 440 lignes TS livrées + types alignés sur le schéma Python.**

### Tests

- `scripts/test-db-poc-write.ts` : **7/7 passing** (validate, cross-tenant block, correct, reject, reject-without-reason, double-validate-blocked, validate-rejected-blocked).
- `npx tsc --noEmit --skipLibCheck` : ✓ pas d'erreur.
- `npm run build` : ✓ 9 routes générées dont `/entries`, `/entries/[id]`, `/entries/pdf/[docId]` (dynamiques).
- Smoke E2E manuel via curl :
  - `GET /entries?client=cabinet-pilote-01` → 200, liste 8 entries (6 proposed + 1 validated + 1 rejected).
  - `GET /entries/1?client=cabinet-pilote-01` → 200, détail rendu.
  - `GET /entries/pdf/21?client=cabinet-pilote-01` → 200, application/pdf, 10 125 bytes.
  - `GET /entries/pdf/21?client=cabinet-WRONG` → 404 (cross-tenant isolation OK).

### Garanties techniques

- **Multi-mandant strict** : toutes les requêtes lecture/écriture filtrées par `client_id`. Cross-tenant testé et bloqué (`EntryNotFoundError`).
- **Workflow states cohérents** avec `worker/src/fiduciaire_worker/workflow_states.py` : `proposed → validated`, `proposed → rejected` (terminal), correction = transition vers `validated` avec diff loggé.
- **Atomicité** : chaque mutation utilise `db.transaction()` (better-sqlite3) — UPDATE + INSERT state_change ou rollback.
- **Path traversal bloqué** dans `/entries/pdf/[docId]` : validation sur `path.resolve` que le résultat reste sous `data/archive/`.
- **PAT jamais loggé** : route handler utilise `request.url` parsing, pas de variables sensibles dans les logs.

### Demo data

- `worker/scripts/seed_demo_entries.py` : 8 documents synthétiques + 8 écritures variées (mix vendor_history / llm, états proposed/validated/rejected) pour le mandant `cabinet-pilote-01`.
- 8 PDFs réels copiés dans `data/archive/demo*.pdf` depuis `data/samples/` pour que l'iframe affiche un vrai contenu.

---

## 2. Bilan Bexio sync — REPORTÉ

### Statut

**Phase 2 non exécutée cette session.** Raison : `keyring.get_password('fiduciaire', 'bexio-pat-pilote-dev')` retourne `None` — le PAT n'est pas dans le Keychain macOS.

Le prompt session 2 mentionnait *"PAT Bexio prêt : stocké dans Keychain macOS sous fiduciaire / bexio-pat-pilote-dev"*. C'est faux à ce stade. À reprendre dès que Tanguy a généré son PAT dans Bexio.

### Livré (script prêt)

- `worker/scripts/initial_bexio_sync.py` : script paramétré, lit le PAT depuis le Keychain, appelle `BexioReadOnlyClient.sync_to_local_cache(conn)`, puis `vendor_account_history.build_history_from_bexio_cache(conn, client_id)`. Mode dry-run forcé (la classe `BexioReadOnlyClient` n'a aucune méthode write par design).

### À faire (5 min quand Tanguy a son PAT)

```bash
# 1. Générer le PAT dans Bexio : Profil → Personal Access Tokens → Generate
# 2. Stocker dans Keychain
python3 -c "import keyring; keyring.set_password('fiduciaire', 'bexio-pat-pilote-dev', '<PAT>')"

# 3. Sync (read-only, dry-run forcé par design du client)
cd /Users/tanguylachat/fiduciaire
./worker/.venv/bin/python worker/scripts/initial_bexio_sync.py --client-id cabinet-pilote-01

# Sortie attendue : N comptes pulled + M contacts + 100 manual_entries + top fournisseurs avec confidence
```

---

## 3. Decision docs livrés

- `docs/decisions/2026-05-09-mistral-small-3-as-default.md` — Mistral Small 3 24B (Q4_K_M) modèle par défaut conditionnel au bench. Économie 24 000 CHF projetée sur 30 cabinets (16 GB vs 64 GB RAM hardware).
- `docs/decisions/2026-05-09-self-improvement-levels.md` — 4 niveaux d'auto-amélioration formalisés. Niveau 1 livré, niveaux 2-3 cadrés, niveau 4 (fine-tuning) hors scope avec justification.

### Update livré

- `docs/user-guide.md` (nouveau) — guide non-technique cabinet pilote avec section *"Comment l'agent apprend"* expliquant les niveaux 1-3 en langage utilisateur. Inclut le disclaimer critique sur la qualité du feedback humain.

---

## 4. Bilan bench Mistral vs Llama — REPORTÉ

### Statut

**Phase 4 non exécutée cette session.** Raison : RunPod pas lancé pendant cette session, pas d'accès Ollama avec les modèles cibles.

### Livré (script prêt)

- `worker/scripts/run_bench_runpod.sh` : pipeline complet 6 étapes pour exécution sur pod RunPod A100 80 GB ou H100 (~2-3 USD/h). Install Ollama → pull `mistral-small:24b-instruct-2501-q4_K_M` + `llama3.3:70b-instruct-q4_K_M` → clone repo → seed vendor history → run `entry_bench.py` sur les 31 docs benchables → sortie JSON dans `data/bench-results/`.

### À faire (Tanguy ou agent suivant)

1. Lancer un pod RunPod A100 80 GB (~2 USD/h, 30 min de bench attendu).
2. Transférer `data/samples/` + `data/samples/entry_labels.csv` via SCP.
3. SSH sur le pod : `bash worker/scripts/run_bench_runpod.sh`.
4. Récupérer les 2 JSON de bench.
5. Générer rapport comparatif (script à écrire — `worker/scripts/render_bench_report.py` n'a pas été produit cette session pour économiser le contexte).
6. Décision : si Mistral ≥75% compte / ≥80% TVA → confirmer la decision doc Mistral comme défaut. Sinon, ouvrir override doc.

### Hypothèses qui restent ouvertes

1. **Mistral Small 3 24B Q4 atteint ≥75% compte / ≥80% TVA** sur le corpus synthétique. À mesurer.
2. **Mistral est compétitif vs Llama 70B** sur le français comptable suisse. Hypothèse à valider.

---

## 5. Loom 2 min — script prêt, enregistrement à faire

### Livré

- `docs/demo/loom-script-sprint-0a.md` — scénario timeline détaillé 100-120 secondes :
  - 0:00–0:08 hook
  - 0:08–0:18 liste + filtres
  - 0:18–0:35 vue détail 2 colonnes
  - 0:35–0:42 validation 1 clic
  - 0:42–0:60 correction d'une entry
  - 0:60–0:75 audit trail + filtre état
  - 0:75–0:95 différenciateur 100 % local
  - 0:95–1:55 outro

### À faire (Tanguy)

1. Lancer `./worker/.venv/bin/python worker/scripts/seed_demo_entries.py` (déjà exécuté cette session, dashboard prêt).
2. `npm run dev` puis ouvrir Loom.
3. Suivre le timeline du script.
4. Lien Loom à coller dans ce rapport (section livrables ci-dessous).

---

## 6. Décisions techniques prises pendant la session

1. **Forms parallèles plutôt qu'imbriquées** dans `EntryEditor` — HTML invalide sinon. Mode édition affiche un seul `<form>` correctAction ; mode lecture affiche les actions Validate/Reject comme `<form>` séparées.
2. **Pas de Vitest installé** côté TS — smoke test custom via `tsx scripts/test-db-poc-write.ts`. Évite d'ajouter une dépendance pour 7 tests Sprint 0a. À installer en Sprint 1 si suite TS grossit.
3. **PDF route handler scope tenant via join** plutôt que via cookie/auth — plus simple et plus sûr en Sprint 0a.
4. **Démo seed isolé du pipeline réel** — `seed_demo_entries.py` insère directement dans `accounting_entries` sans passer par `entry_proposer.py`, pour ne pas dépendre d'Ollama tournant en local. Idempotent.

---

## 7. Cas en échec restants + hypothèses

| Cas | Hypothèse de cause | Action |
|---|---|---|
| PAT Bexio absent du Keychain | confusion entre prompt session et état réel | Tanguy génère le PAT dans Bexio, l'ajoute via `keyring.set_password` |
| Bench réel pas exécuté | RunPod pas démarré cette session | Lancer pod + suivre `run_bench_runpod.sh` |
| Loom pas enregistré | Décision Tanguy enregistrement | Suivre `loom-script-sprint-0a.md` |
| `render_bench_report.py` non livré | Économie de contexte session | À écrire en 30 min lors du run bench réel |

---

## 8. Statut prochaine session (Sprint 1)

Sprint 0a est **livrable** sous réserve des 3 actions Tanguy ci-dessus (PAT, bench, Loom). Sprint 1 peut démarrer avec :

- IMAP automatique (ingestion factures depuis boîte mail dédiée).
- Push Bexio (écritures validées poussées via API en mode dry-run d'abord).
- Multi-mandant testé sur 3 mandants du cabinet pilote.
- Audit trail immutable (hash chaîné append-only).
- Chiffrement at-rest (SQLCipher + age pour fichiers).
- Backup automatisé chiffré (NAS ou Infomaniak chiffré).
- Detection pièces manquantes + relances draft.
- Niveau 2 d'auto-amélioration : `correction_learner.py`.

---

## 9. Livrables session 2 — checklist DOD

- [x] Specs `docs/specs/dashboard-entries.md`
- [x] `lib/db-poc.ts` étendu avec read functions
- [x] `lib/db-poc-write.ts` créé + 7 tests passing
- [x] Page liste `/(poc)/entries` + filtres + multi-mandant
- [x] Page détail `/(poc)/entries/[id]` 2 colonnes PDF + form
- [x] Server Actions valider/corriger/rejeter avec `useActionState`
- [x] Route handler `/entries/pdf/[docId]` scope tenant + path traversal bloqué
- [x] Smoke test 7/7 passing sur write layer
- [x] `npm run build` passe sans erreur
- [x] Decision doc `2026-05-09-mistral-small-3-as-default.md`
- [x] Decision doc `2026-05-09-self-improvement-levels.md`
- [x] `docs/user-guide.md` créé avec section "Comment l'agent apprend"
- [x] `worker/scripts/initial_bexio_sync.py` (prêt, exécution reportée)
- [x] `worker/scripts/run_bench_runpod.sh` (prêt, exécution reportée)
- [x] `worker/scripts/seed_demo_entries.py` (exécuté, 8 entries seedées)
- [x] `docs/demo/loom-script-sprint-0a.md` (prêt, enregistrement reporté à Tanguy)
- [ ] PAT Bexio sync exécuté → vendor_account_history populé depuis Bexio réel **(REPORTÉ)**
- [ ] Bench Mistral vs Llama exécuté → décision LLM gagnant **(REPORTÉ)**
- [ ] Loom 2 min enregistré → lien collé ici **(REPORTÉ)**

### Lien Loom (à compléter par Tanguy)

`<URL Loom>`
