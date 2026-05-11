# Session 4 — Handoff Option Z

**Date :** 2026-05-11
**Branche :** `feature/sprint-0a-core` (commit pushed)
**Statut :** Sprint 1 §3.1 **Phases B + C livrées**, Sprint 1 §3.2 **Bexio push livré**.

---

## 1. Bilan modules livrés

### Sprint 1 §3.1 Phase B — orchestrator IMAP

| Fichier | LoC | Statut |
|---|---|---|
| `worker/src/fiduciaire_worker/imap_fetch.py` | 365 | nouveau |
| `worker/tests/test_imap_fetch_integration.py` | 700 | **21 tests verts** |
| `worker/scripts/imap_fetch.py` | 200 | nouveau CLI |

**API publique :**
- `fetch_emails(*, cabinet_id, creds, conn, config, folder='INBOX', limit, dry_run, mark_seen, filters, staging_dir, max_attachment_size_bytes, imap_factory, process_document_fn) -> ImapFetchSummary`
- Dataclasses : `ImapFetchFilters`, `MessageOutcome`, `ImapFetchSummary`
- Constantes : `MSG_STATUS_*`, `MAX_ATTACHMENT_SIZE_DEFAULT = 50 MB`

### Sprint 1 §3.1 Phase C — lock file + launchd

| Fichier | LoC | Statut |
|---|---|---|
| `worker/src/fiduciaire_worker/process_lock.py` | 130 | nouveau |
| `worker/tests/test_process_lock.py` | 130 | **15 tests verts** |
| `deploy/imap-fetch.plist.template` | 65 | nouveau (launchd) |
| `deploy/install-launchd.sh` | 55 | nouveau (chmod +x) |
| `docs/specs/imap-fetch.md` §10 | +90 lignes | section "Smoke test prod" |

**API publique :**
- `ProcessLock(path, auto_reclaim_stale=False)` avec context manager
- `LockAcquireError`, `LockInfo`
- `is_pid_alive(pid)`, `parse_lock_file(path)`

Le CLI `imap_fetch.py` intègre désormais le lock via `--force` et `--lock-dir`.

### Sprint 1 §3.2 — Bexio push

| Fichier | LoC | Statut |
|---|---|---|
| `worker/src/fiduciaire_worker/bexio_push.py` | 380 | nouveau |
| `worker/src/fiduciaire_worker/accounting_schema.py` | +30 | ALTER TABLE + `bexio_push_log` |
| `worker/tests/test_bexio_push.py` | 470 | **17 tests verts** |
| `worker/scripts/bexio_push.py` | 200 | nouveau CLI |

**API publique :**
- `push_validated_entries(*, cabinet_id, pat, conn, base_url, state_filter, dry_run, limit, max_retries, retry_initial_backoff_s, http_client, account_no_to_bexio_id, tax_code_to_bexio_id) -> BexioPushSummary`
- Dataclasses : `BexioPushResult`, `BexioPushSummary`
- Constantes status : `PUSH_STATUS_PUSHED`, `PUSH_STATUS_DRY_RUN`, `PUSH_STATUS_FAILED`, `PUSH_STATUS_ALREADY_PUSHED`, `PUSH_STATUS_ACCOUNT_NOT_MAPPED`

**Schéma SQL ajouté :**
- `accounting_entries.bexio_id TEXT` (idempotent ALTER)
- `accounting_entries.bexio_pushed_at TEXT` (idempotent ALTER)
- Nouvelle table `bexio_push_log` (audit trail des push attempts)

---

## 2. Métriques tests

| Catégorie | Avant Session 4 | Après Session 4 | Delta |
|---|---:|---:|---:|
| **Tests Python** | 136 | **189** | **+53** |
| imap_fetch (intégration) | 0 | 21 | +21 |
| process_lock | 0 | 15 | +15 |
| bexio_push | 0 | 17 | +17 |
| autres | 136 | 136 | 0 |
| **Régressions** | — | **0** | — |
| Temps suite complète | ~70s | ~61s | -9s (tests rapides) |

`.venv/bin/python -m pytest tests/ -q` → `189 passed in 61.07s`.

---

## 3. Décisions techniques prises

1. **[`2026-05-11-imap-fetch-phase-b-design.md`](../decisions/2026-05-11-imap-fetch-phase-b-design.md)** — orchestrator fonctionnel, dry-run = zero side-effect, filtres en kwargs, process_document injectable, staging par sha256, UIDVALIDITY rescan + dedup, lock PID-based.

2. **[`2026-05-11-bexio-push-double-opt-in.md`](../decisions/2026-05-11-bexio-push-double-opt-in.md)** — dry-run par défaut, double opt-in CLI (`--live` ET `BEXIO_PUSH_LIVE=true`), idempotence via `bexio_id`, retry exp uniquement sur 5xx, maps account/tax via JSON externe, audit table `bexio_push_log`, ALTER TABLE idempotent.

---

## 4. USER ACTION MAP — ce que Tanguy doit faire avant Session 5

### Pour la prod IMAP (cabinet pilote)

1. **Créer une boîte test sur Infomaniak** (ex. `test-fiduciaire@infomaniak.com`).
   Ne pas utiliser la boîte de production tant qu'un cycle complet n'est pas validé.
2. **Générer un app password Infomaniak** (Panel → Mail → Mot de passe d'application).
3. **Envoyer 5 emails test** à cette boîte (1 PDF, 1 PNG, 1 zip, 1 sans PJ, optionnel : 1 > 50 MB).
4. **Configurer credentials** :
   ```bash
   # Keychain (recommandé)
   python -c "import keyring; \
     keyring.set_password('fiduciaire', 'imap-pilote-jura-01-host', 'mail.infomaniak.com')"
   python -c "import keyring; \
     keyring.set_password('fiduciaire', 'imap-pilote-jura-01-user', 'test-fiduciaire@infomaniak.com')"
   python -c "import keyring; \
     keyring.set_password('fiduciaire', 'imap-pilote-jura-01-password', '<APP_PWD>')"
   ```
5. **Exécuter le smoke test** documenté dans `docs/specs/imap-fetch.md` §10 :
   ```bash
   # Étape 1 — dry-run
   worker/.venv/bin/python worker/scripts/imap_fetch.py \
     --client-id pilote-jura-01 --dry-run --limit 10

   # Étape 2 — run réel
   worker/.venv/bin/python worker/scripts/imap_fetch.py \
     --client-id pilote-jura-01 --mark-seen

   # Étape 3 — vérifier idempotence (0 nouveaux)
   worker/.venv/bin/python worker/scripts/imap_fetch.py --client-id pilote-jura-01

   # Étape 4 — launchd polling 5 min
   deploy/install-launchd.sh pilote-jura-01
   tail -f ~/Library/Logs/fiduciaire/imap-fetch-pilote-jura-01.log
   ```
6. **Critère validation** : 3-5 documents arrivent dans `data/archive/`, `email_messages` peuplé, lock file relâché après chaque run, logs grep "password" → 0 hits.

### Pour la prod Bexio push (quand cabinet OK pour pousser)

1. **Sandbox Bexio** : créer un compte sandbox Bexio (gratuit), générer un PAT
   sandbox via Profil → API → Personal access token.
2. **Construire les maps account/tax** depuis le plan comptable du cabinet :
   ```json
   // config/account-map-pilote-jura-01.json
   { "6510": 9510, "2000": 9200, "1020": 9000, ... }
   ```
   ```json
   // config/tax-map-pilote-jura-01.json
   { "TN_NORM": 12, "TN_RED": 13, "EXO": 30 }
   ```
   Les IDs Bexio internes sont visibles via `BexioReadOnlyClient.fetch_account_plan()`
   (déjà testé Sprint 0a) — chaque account a un `id` int interne.
3. **Smoke test dry-run** (safe) :
   ```bash
   worker/.venv/bin/python worker/scripts/bexio_push.py \
     --client-id pilote-jura-01 \
     --account-map config/account-map-pilote-jura-01.json \
     --tax-map config/tax-map-pilote-jura-01.json
   ```
4. **Smoke test sandbox** (LIVE vers compte sandbox) :
   ```bash
   BEXIO_PAT="<sandbox_pat>" BEXIO_PUSH_LIVE=true \
     worker/.venv/bin/python worker/scripts/bexio_push.py \
     --client-id pilote-jura-01 --live \
     --account-map config/account-map-pilote-jura-01.json \
     --tax-map config/tax-map-pilote-jura-01.json \
     --limit 2
   ```
5. **Vérifier dans Bexio sandbox UI** : les 2 écritures apparaissent. Si OK :
   ré-exécuter → `summary.already_pushed == 2`, aucun nouveau dans Bexio.
6. **Critère prod** : valider sur sandbox avec ≥10 entries variées avant de
   pointer `--base-url` vers la prod cabinet.

---

## 5. État global

| Composant | Statut |
|---|---|
| Sprint 0a — 7 modules core + Dashboard + Bexio read | ✅ session 1-2 |
| Sprint 0a — `ingest_local_corpus.py` | ✅ session 2 |
| Sprint 0a — Bench Mistral vs Llama figé | ✅ session 3 |
| Sprint 1 §3.1 Phase A (email_parser + imap_client + secrets) | ✅ session 3 |
| **Sprint 1 §3.1 Phase B (orchestrator + CLI)** | ✅ **session 4** |
| **Sprint 1 §3.1 Phase C (lock + launchd + smoke doc)** | ✅ **session 4** |
| **Sprint 1 §3.2 (Bexio push + audit log + CLI)** | ✅ **session 4** |
| Sprint 1 §3.3 — Multi-mandant testé N=3 | ⏳ session 5 |
| Sprint 1 §3.4 — Chiffrement at-rest (SQLCipher + age) | ⏳ session 5+ |
| Sprint 1 §3.5 — Backup automatisé chiffré | ⏳ session 5+ |
| Sprint 1 §3.6 — Audit trail immutable | ⏳ session 5+ |
| Sprint 1 §3.7 — Détection pièces manquantes | ⏳ session 6+ |
| Sprint 1 §3.8 — WinBIZ export CSV/XML | ⏳ session 6+ |
| Sprint 1 §3.9 — CAMT.053 rapprochement | ⏳ session 6+ |
| Sprint 1 §3.10 — Dashboard extension | ⏳ session 5+ |

---

## 6. Contraintes non-négociables respectées

| Contrainte | Vérification |
|---|---|
| Aucun appel LLM externe | Les modules nouveaux n'importent ni OpenAI ni Anthropic. OCR/classify utilisent le pipeline Sprint 0a (Ollama local). |
| Aucune écriture Bexio "live" sans flag explicite | `push_validated_entries(dry_run=True)` par défaut. CLI exige `--live` + `BEXIO_PUSH_LIVE=true`. Test dédié. |
| PAT jamais loggé | `test_pat_never_logged` passe. Pas de header ni body request dans les logs. |
| `.env` dans `.gitignore` | Confirmé (`.env`, `.env.local`, `.env.production`). |
| Multi-mandant first-class | Toutes les requêtes SQL filtrent par `cabinet_id` / `client_id`. Tests dédiés `test_multi_mandant_isolation` dans IMAP et Bexio. |
| TDD strict | Tests d'abord pour chacun des 3 modules livrés. 53 tests neufs. |
| Pas de LangChain/Flowise/n8n core | Imports : stdlib + httpx + email + sqlite3. Zéro dépendance ajoutée Session 4. |
| Audit CLAUDE.md | Effectué. Tous les tests passent (189/189), zéro régression. |

---

## 7. Issues / TODOs Session 5+

- [ ] **Smoke test cabinet réel** (Tanguy USER ACTION MAP §4 ci-dessus)
- [ ] **Lecture YAML cabinet** (`config/clients/<id>.yaml`) pour les filtres
      IMAP + maps account/tax — actuellement passés en CLI args / JSON externe
- [ ] **§3.3 Multi-mandant N=3** : déployer chez 3 clients du cabinet pilote,
      tester l'isolation cross-cabinet sur DB partagée
- [ ] **§3.4 Chiffrement at-rest** : SQLCipher pour fiduciaire.sqlite +
      age pour les PDFs dans data/archive/
- [ ] **§3.5 Backup chiffré** : rsync + age vers stockage cabinet (NAS ou
      Backblaze B2 chiffré côté client)
- [ ] **§3.6 Audit trail immutable** : hash chaîné append-only sur les
      transitions critiques (validate, bexio_push, bexio_id assigned)
- [ ] **Recovery Bexio post-timeout** : si push HTTP timeout et entry sans
      bexio_id local, fetcher les manual_entries Bexio récents et matcher
      par description+date+amount pour éviter doublons

---

## 8. Notes annexes

### Tests ajoutés détaillés

**`test_imap_fetch_integration.py` (21 tests)** :
- `test_end_to_end_fetch_and_ingest_5_emails` — pipeline complet 4 PDFs + 1 newsletter
- `test_idempotence_second_run_no_duplicates` — 2× run, dedup Message-ID
- `test_dry_run_no_db_writes_no_pipeline_no_mark_seen` — zero side-effect
- `test_filter_sender_allowlist_exact_email` — match exact
- `test_filter_sender_allowlist_domain_wildcard` — `@swisscom.ch` wildcard
- `test_pgp_email_flagged_no_attachments_extracted` — encryption_status=pgp
- `test_smime_email_flagged_no_attachments_extracted` — encryption_status=smime
- `test_multi_mandant_isolation` — cabinet-a vs cabinet-b
- `test_oversized_attachment_marked_and_skipped` — > max_size → 'oversized'
- `test_unsupported_attachment_zip_status_set` — .zip → 'unsupported'
- `test_limit_caps_processing` — limit=2 sur 5 emails
- `test_mark_seen_when_flag_set` — STORE +Seen
- `test_mark_seen_false_by_default`
- `test_uidvalidity_change_triggers_full_rescan` — server mailbox rebuild
- `test_fetch_state_persisted_after_run` — last_uid_seen + uidvalidity
- `test_pipeline_exception_marks_attachment_failed` — graceful per-attachment
- `test_summary_dataclass_shape`
- `test_filters_dataclass_defaults`
- `test_filters_matches_sender_with_name_prefix` — `Foo <foo@bar.com>`
- `test_filters_empty_allowlist_rejects_all` — explicit deny-all
- `test_auth_error_propagates_without_db_write` — ImapAuthError clean

**`test_bexio_push.py` (17 tests)** :
- `test_dry_run_default_no_http_call`
- `test_live_push_marks_bexio_id_and_timestamp`
- `test_payload_format_v3_manual_entries` — body shape Bexio v3
- `test_already_pushed_skipped`
- `test_retry_on_5xx_then_succeeds`
- `test_retry_exhausted_after_max_retries`
- `test_4xx_no_retry`
- `test_idempotence_second_run_no_duplicates`
- `test_multi_mandant_isolation`
- `test_only_validated_state_pushed`
- `test_account_no_not_mapped_skipped`
- `test_pat_never_logged`
- `test_audit_log_records_all_attempts`
- `test_dry_run_logs_to_audit_with_dry_run_flag`
- `test_limit_caps_processing`
- `test_summary_shape_and_results`
- `test_dry_run_status_constants_exposed`

**`test_process_lock.py` (15 tests)** :
- `test_acquire_creates_lock_file`, `test_release_removes_lock_file`
- `test_context_manager_releases_on_exit`, `test_context_manager_releases_on_exception`
- `test_second_acquire_fails_if_pid_alive`
- `test_stale_lock_dead_pid_acquires_when_force`
- `test_stale_lock_dead_pid_auto_reclaim_without_force`
- `test_parse_lock_file_returns_none_if_missing`, `_if_corrupt`
- `test_is_pid_alive_self`, `_dead`
- `test_lockinfo_dataclass`
- `test_lock_path_parents_created`
- `test_release_idempotent`
- `test_acquire_after_release_works`

### Commande de relance Session 5

```
/clear

[paste master prompt Option Z]

Reprends Sprint 1 §3.3+ (multi-mandant N=3, §3.4 chiffrement,
§3.5 backup, §3.6 audit trail). Phase B/C IMAP livrées,
§3.2 Bexio push livré (dry-run + double opt-in). Tanguy doit
avant cette session : smoke test cabinet réel IMAP (USER ACTION
MAP §4 du handoff session 4) + créer sandbox Bexio + maps
account/tax JSON pour pilote-jura-01.
```
