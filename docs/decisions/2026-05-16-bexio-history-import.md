# Décision — Import historique Bexio : N mois d'écritures pour bootstrap vendor_history

**Date :** 2026-05-16
**Statut :** Actée Sprint 2 Session 12.
**Voir aussi :** `worker/src/fiduciaire_worker/bexio_history_import.py`,
`worker/src/fiduciaire_worker/bexio_client.py`,
`worker/src/fiduciaire_worker/vendor_account_history.py`.

## Contexte

Sprint 0a a livré `bexio_client.fetch_recent_manual_entries(limit=100)` qui
pull les 100 dernières écritures (read-only via PAT). C'est suffisant pour
la démo Loom mais insuffisant pour un **vrai cabinet en prod** :
- 100 écritures = ~2 semaines d'activité pour un mandant moyen
- `vendor_account_history` mal calibré ⇒ `entry_proposer` tombe sur le
  fallback LLM trop souvent ⇒ latence + précision moindres

Pour Gravosig (install semaine du 19 mai), il faut bootstrap chaque mandant
avec **12 mois d'historique** = ~600-2400 écritures → recommandations
fournisseur stables dès le jour 1.

## Décision

**Script `import_bexio_history.py` pull paginé + idempotent**, par mandant,
avec rate-limit Bexio (60 req/min PAT standard) et backoff.

```bash
worker/.venv/bin/python worker/scripts/import_bexio_history.py \
  --cabinet-id gravosig-fiduciaire-01 \
  --mandant-id mandant-pme-01 \
  --months 12
```

Effets :
1. Pull plan comptable du mandant (réutilise `fetch_account_plan`)
2. Pull contacts (réutilise `fetch_contacts`)
3. Pull `accounting/manual_entries` paginé, `date_from`/`date_to` =
   `now - N mois` → `now`. Page size 100, sleep ~1.1s entre pages
   (rate limit conservateur)
4. Upsert dans `bexio_sync` (idempotent via PK
   `(client_id, entity_type, entity_id)`)
5. Reconstruit `vendor_account_history` via
   `build_history_from_bexio_cache` existant
6. Émet event audit `bexio_history_imported` avec rows counts

## Rate limit

Bexio PAT standard : 60 req/min. On vise 50 req/min pour avoir une marge :
- `sleep(1.2)` entre requêtes par défaut
- Backoff exponentiel sur HTTP 429 : 2s → 4s → 8s, max 3 retries
- `--rate-limit-req-per-min` overrideable (utile pour Pro PAT 300 req/min)

## Idempotence

- `bexio_sync` PK garantit pas de doublon
- Re-run avec mêmes paramètres ⇒ 0 row ajouté (DRY hash sur entity_id Bexio)
- Flag `--force-refresh` purge `bexio_sync entity_type='manual_entry'` du
  mandant avant pull (utile si écritures ont été modifiées côté Bexio)

## Dry-run

`--dry-run` :
- Pas d'écriture en DB
- Pas d'event audit
- Log + count seulement

## Cross-mandant strict

- Chaque pull est lié à `cabinet_id` (= `client_id` en DB)
- `bexio_sync` indexé par `client_id` ⇒ aucun risque de leak
- Test cross-mandant explicite : mandant-a et mandant-b avec deux mocks
  PAT distincts, on vérifie aucune entrée croisée

## Audit log

Event en mode live (pas dry-run) :
- `entity_type = "bexio_sync"`
- `entity_id = "<cabinet_id>:<mandant_id>"`
- `action = "bexio_history_imported"`
- `after = {accounts_count, contacts_count, entries_count, months,
  vendor_rec_count}`

**Pas de PAT dans le payload**, jamais. Le PAT n'est pas non plus loggé
au format texte (`logger.error("PAT auth failed", exc_info=False)`).

## Critères de succès

- ✅ Pull 12 mois sans timeout (rate limit respecté)
- ✅ Idempotence : re-run = 0 ajout
- ✅ Cross-mandant strict
- ✅ Dry-run silencieux (pas d'audit, pas d'écriture)
- ✅ PAT jamais loggé (test explicite)
- ✅ vendor_account_history rebuilt après import

## Alternatives écartées

- **OAuth2 Bexio** : Sprint 2 reste sur PAT (cf
  `2026-05-08-bexio-auth-pat-vs-oauth2.md`). Pas dans le scope Session 12.
- **Webhook Bexio** : push, pas pull. Hors scope (nécessite Sprint 3).
- **Batch all-mandants au lieu de mandant-par-mandant** : refusé. Un seul
  mandant qui plante ne doit pas bloquer les autres. CLI relancé par
  mandant dans le runbook install Gravosig.
