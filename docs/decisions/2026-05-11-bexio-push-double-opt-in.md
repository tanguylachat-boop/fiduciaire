# Décision — Bexio push : double opt-in obligatoire

**Date :** 2026-05-11
**Sprint :** 1 §3.2 (Session 4)
**Statut :** Actée et livrée (17 tests verts).

## Contexte

§3.2 du PRD V2 demande de pousser les écritures `validated` vers Bexio v3
manual_entries. Risque : un script CLI qui écrit en prod par accident
peut polluer la compta du cabinet (écritures fantômes à supprimer
manuellement dans Bexio).

## Décisions

### 1. Dry-run par défaut **non-négociable**

**`push_validated_entries(dry_run=True)` est le défaut.**

Pour pousser en prod, le caller doit EXPLICITEMENT passer `dry_run=False`.
Pas d'env var qui peut basculer ça côté lib — la lib est neutre. La
politique vit côté CLI.

### 2. Double opt-in CLI : flag + env var

**Le CLI `worker/scripts/bexio_push.py` exige LES DEUX :**
- `--live` argument CLI
- `BEXIO_PUSH_LIVE=true` env var

Sans les deux, dry-run forcé. Message clair quand un seul est présent
("flag passé mais env var absent" et vice versa).

Rationale : un opérateur ne tape pas accidentellement les deux. Si
launchd / cron pousse en mode prod sans intention, l'opérateur peut
revoir l'env var. Si quelqu'un teste en dev avec `--live`, l'absence
de l'env empêche l'écriture.

### 3. Idempotence via `accounting_entries.bexio_id`

**Une entry avec `bexio_id IS NOT NULL` n'est jamais re-poussée.**

Bexio v3 ne supporte pas (à notre connaissance) `Idempotency-Key`.
On stocke localement le `bexio_id` retourné par la première poussée
réussie. Tout re-run skip avec `status='already_pushed'`.

Conséquence : si Bexio a accepté l'écriture mais on n'a pas reçu la
réponse (timeout), l'entry reste sans bexio_id local → re-push créera
un doublon Bexio. Mitigation Sprint 2 : recovery via fetch_recent_manual_entries
+ matching par description+date.

### 4. Retry exp uniquement sur 5xx

**Décision : retry 3× exp backoff sur 5xx ou erreurs réseau. Pas de
retry sur 4xx.**

- 5xx = transitoire (Bexio down, gateway 502) → retry justifié
- 4xx = problème données (date invalide, account_id inconnu) → retry
  donnerait le même résultat, gaspille des appels. Fail-fast.

### 5. account_no et tax_code via maps externes JSON

**Décision : `account_no_to_bexio_id` et `tax_code_to_bexio_id` sont
des `dict[str, int]` passés au module, chargés depuis JSON par le CLI.**

Pourquoi pas en config.yaml : ces mappings sont SPÉCIFIQUES au cabinet
Bexio (les IDs internes Bexio diffèrent par compte). Les hardcoder
casserait au passage au cabinet suivant. JSON séparé = source de vérité
mutable sans toucher le code.

Fallback : si tax_map=None → on n'envoie pas `tax_id` dans le body
(Bexio accepte les manual_entries sans TVA). Si account_map ne couvre
pas un account_no rencontré → status `account_not_mapped`, entry skippée
+ audit log.

### 6. Audit log dédié — `bexio_push_log`

**Nouvelle table SQLite (1 ligne par tentative HTTP).**

Schéma : id, client_id, entry_id, attempt, http_status, bexio_id, ok,
error, response_excerpt (500 chars max), dry_run, created_at.

Permet d'auditer : qui a poussé quoi, quand, avec quel résultat. Le
`response_excerpt` aide à diagnostiquer les rejets Bexio (typiquement
JSON `{"error": "..."}` qu'on extrait dans le summary).

PAT **jamais** stocké dans cette table — uniquement `bexio_id` de la
réponse + status code.

### 7. Migration ALTER TABLE idempotente

**Décision : `accounting_schema.init_accounting_schema()` appelle
`_add_column_if_missing()` pour `bexio_id` et `bexio_pushed_at` sur
`accounting_entries`.**

Pattern : `PRAGMA table_info` → check column absent → ALTER TABLE ADD.
Idempotent : re-run no-op. Pas de migration manuelle requise pour les
DB Sprint 0a existantes.

## Conséquences

- Les 17 tests test_bexio_push.py couvrent : dry-run zero-call, success,
  retry, exhausted retries, 4xx no-retry, idempotence, multi-mandant,
  state filter, account map miss, PAT never logged, audit log records,
  limit, summary shape.
- CLI prêt pour smoke contre sandbox Bexio (Tanguy doit obtenir un compte
  sandbox + créer manuellement le PAT sandbox).
- Bexio v3 endpoint figé : `POST /3.0/accounting/manual_entries`.
- Aucune écriture vers Bexio prod tant que double opt-in pas posé.

## TODO Sprint 2

- Recovery via fetch_recent_manual_entries (détecter les doublons après
  timeout)
- Mapping tax_id auto via fetch du plan TVA Bexio (au lieu de JSON manuel)
- Audit trail chiffré (Sprint 1 §3.6)
