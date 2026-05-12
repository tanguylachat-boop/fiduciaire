# Session 5 — Handoff Option Z

**Date :** 2026-05-12
**Branche :** `feature/sprint-0a-core` (commit pushed)
**Statut :** Sprint 1 **§3.3 + §3.4 + §3.5 + §3.6 livrés.**

---

## 1. Bilan modules livrés

### Sprint 1 §3.3 — Multi-mandant testé N=3

| Fichier | LoC | Statut |
|---|---|---|
| `worker/scripts/seed_multi_mandant_test.py` | 230 | nouveau (3 mandants × 5 vendors) |
| `worker/tests/test_multi_mandant_e2e.py` | 410 | **10 tests verts** (incl. stress 300 docs concurrent) |

Vérifié : aucun vendor d'un mandant n'apparaît dans le lookup d'un autre,
entry_proposer reste isolé, bexio_push dry-run/live n'affecte que le
cabinet cible, threads concurrents (3 workers) → 30 entries propres,
logs ne contiennent pas les `client_id` étrangers, stress 100 docs ×
3 mandants en 3s.

### Sprint 1 §3.4 — Chiffrement at-rest

| Fichier | LoC | Statut |
|---|---|---|
| `worker/src/fiduciaire_worker/encryption.py` | 270 | nouveau (Fernet AES-128-CBC + HMAC) |
| `worker/tests/test_encryption.py` | 270 | **19 tests verts** |
| `worker/scripts/encrypt_archive_files.py` | 95 | nouveau CLI |
| `worker/scripts/rotate_master_key.py` | 85 | nouveau CLI rotation |
| `docs/decisions/2026-05-12-encryption-strategy.md` | 130 | décision (pas SQLCipher Sprint 1) |

**API publique :**
- `MasterKey.generate(cabinet_id)`, `get_master_key`, `ensure_master_key`
- `encrypt_bytes/decrypt_bytes(data, key)`
- `encrypt_file(src, dst, cabinet_id)`, `decrypt_file_to_bytes/path(src, cabinet_id)`
- `is_encrypted_file(path)`, `is_encryption_disabled()`
- `rotate_key_and_re_encrypt(cabinet_id, archive_root, new_key=None)`

**Décision clé :** **pas de SQLCipher Sprint 1**. La DB SQLite reste en
clair, FileVault macOS couvre le repos. Fichiers archive chiffrés
applicativement (1 clé/cabinet dans Keychain). Détails dans la decision.

### Sprint 1 §3.5 — Backup automatisé chiffré

| Fichier | LoC | Statut |
|---|---|---|
| `worker/src/fiduciaire_worker/backup.py` | 320 | nouveau (tar.gz + Fernet) |
| `worker/tests/test_backup.py` | 270 | **12 tests verts** |
| `worker/scripts/backup_now.py` | 110 | nouveau CLI |
| `worker/scripts/restore_from_backup.py` | 60 | nouveau CLI |
| `deploy/backup.plist.template` | 50 | nouveau launchd 03:00 quotidien |
| `deploy/install-backup-launchd.sh` | 50 | chmod +x |

**API publique :**
- `create_backup(*, db_path, archive_root, backup_dir, key=None)`
- `restore_backup(backup_path, restore_root, key=None)`
- `apply_retention(backup_dir, daily_keep=30, monthly_keep=12, yearly_keep=10, dry_run=False)`
- `verify_backup_restorable(path, tmp_dir, key=None) -> (bool, reason)`

Rétention **30/12/10** (quotidiens/mensuels/annuels). Conformité légale CH
10 ans factures + TVA.

### Sprint 1 §3.6 — Audit trail immutable

| Fichier | LoC | Statut |
|---|---|---|
| `worker/src/fiduciaire_worker/audit_log.py` | 270 | nouveau (chain SHA-256 + verify + export) |
| `worker/tests/test_audit_log.py` | 290 | **16 tests verts** |
| `worker/src/fiduciaire_worker/accounting_schema.py` | +5 | auto-init audit_log |
| `worker/src/fiduciaire_worker/workflow_states.py` | +35 | hook `_safe_audit` |
| `worker/src/fiduciaire_worker/entry_proposer.py` | +20 | hook après `_persist` |
| `worker/src/fiduciaire_worker/bexio_push.py` | +25 | hook après push success/fail |

**API publique :**
- `log_audit_event(conn, *, cabinet_id, entity_type, entity_id, action, user_id=None, before=None, after=None) -> int`
- `verify_audit_chain(conn, cabinet_id) -> ChainVerificationResult`
- `get_events_for_entity(conn, cabinet_id, entity_type, entity_id)`
- `list_events(conn, cabinet_id, since, until, entity_type, action, limit)`
- `export_audit_text(conn, cabinet_id, since, until, out_path) -> Path`
- Constantes `ACTION_PROPOSED`, `ACTION_VALIDATED`, `ACTION_REJECTED`, `ACTION_REOPENED`, `ACTION_PUSHED`, `ACTION_PUSH_FAILED`

**Décision clé :** chains isolées par cabinet (multi-mandant non-négociable),
hooks silent-fallback si table absente (back-compat).

---

## 2. Métriques tests

| Catégorie | Avant Session 5 | Après Session 5 | Delta |
|---|---:|---:|---:|
| **Tests Python** | 189 | **246** | **+57** |
| multi_mandant_e2e | 0 | 10 (incl. stress) | +10 |
| encryption | 0 | 19 | +19 |
| backup | 0 | 12 | +12 |
| audit_log | 0 | 16 | +16 |
| autres | 189 | 189 | 0 |
| **Régressions** | — | **0** | — |
| Suite complète | ~61s | ~53s | -8s |

`.venv/bin/python -m pytest tests/ -q` → `246 passed in 52.82s`.

---

## 3. Décisions techniques

1. [`2026-05-12-encryption-strategy.md`](../decisions/2026-05-12-encryption-strategy.md) — **Fernet pour fichiers archive, pas SQLCipher Sprint 1**. FileVault macOS couvre la DB au repos. Defense in depth (2 niveaux : archive files + backup global). Mode dev `FIDUCIAIRE_ENCRYPTION_DISABLED=true`.

2. [`2026-05-12-audit-trail-chain-hash.md`](../decisions/2026-05-12-audit-trail-chain-hash.md) — Chain SHA-256 append-only en SQLite, chains isolées par cabinet, hooks silent-fallback dans 3 modules existants (workflow_states, entry_proposer, bexio_push), export texte plutôt que PDF (dépendance lourde reportée Sprint 2).

3. [`2026-05-12-backup-retention-30-12-10.md`](../decisions/2026-05-12-backup-retention-30-12-10.md) — Backup global tar.gz + Fernet, clé `backup-master` distincte des clés cabinet, rétention 30 daily / 12 monthly / 10 yearly, verify_restorable mensuel opt-in.

---

## 4. USER ACTION MAP — Tanguy avant Session 6

### Pour la prod IMAP (rappel session 4)

Voir `docs/progress/2026-05-11-session4-handoff.md` §4. Smoke test
toujours valable, indépendant des modules livrés en Session 5.

### Pour la prod chiffrement archive

1. **Vérifier FileVault macOS actif sur Mac Mini cabinet :**
   ```bash
   fdesetup status  # doit afficher "FileVault is On"
   ```
   Si OFF : activer dans Préférences Système → Sécurité → FileVault.

2. **Générer la clé maître archive pour le cabinet :**
   ```bash
   cd ~/fiduciaire
   worker/.venv/bin/python -c "
   from fiduciaire_worker.encryption import ensure_master_key
   k = ensure_master_key('pilote-jura-01')
   print(f'Clé créée pour pilote-jura-01. Stockée dans Keychain.')
   "
   ```

3. **Chiffrer les fichiers archive existants (idempotent) :**
   ```bash
   worker/.venv/bin/python worker/scripts/encrypt_archive_files.py \
     --client-id pilote-jura-01 --dry-run
   # Si tout OK :
   worker/.venv/bin/python worker/scripts/encrypt_archive_files.py \
     --client-id pilote-jura-01
   ```

4. **À noter dans le runbook cabinet :** rotation annuelle clé
   archive via `worker/scripts/rotate_master_key.py`.

### Pour la prod backup quotidien

1. **Activer le LaunchAgent backup :**
   ```bash
   deploy/install-backup-launchd.sh
   ```

2. **Test manuel premier backup :**
   ```bash
   worker/.venv/bin/python worker/scripts/backup_now.py --verify
   ls -lh data/backups/
   ```

3. **Configurer une cible offsite (optionnel mais recommandé) :**
   - Disque externe USB chiffré (Time Machine compatible) OU
   - Backblaze B2 / rsync.net via rsync chiffré (à scripter Sprint 2)

4. **Vérifier rétention au bout d'une semaine :** confirmer que les
   anciens backups expirent bien selon la politique 30/12/10.

### Pour l'audit trail

1. **Vérifier la chain après quelques cycles** (propose → validate → push) :
   ```bash
   worker/.venv/bin/python -c "
   from fiduciaire_worker import db, audit_log
   conn = db.connect('data/fiduciaire.sqlite')
   result = audit_log.verify_audit_chain(conn, 'pilote-jura-01')
   print(f'Chain valid: {result.is_valid}, total events: {result.total_events}')
   "
   ```

2. **Export texte pour archivage cabinet :**
   ```bash
   worker/.venv/bin/python -c "
   from fiduciaire_worker import db, audit_log
   from pathlib import Path
   conn = db.connect('data/fiduciaire.sqlite')
   audit_log.export_audit_text(conn, 'pilote-jura-01',
     out_path=Path('audit-pilote-jura-01-2026-q2.txt'))
   "
   ```

---

## 5. État global

| Composant | Statut |
|---|---|
| Sprint 0a — core + dashboard + Bexio read | ✅ sessions 1-2 |
| Sprint 0a — ingest_local_corpus + bench Mistral | ✅ sessions 2-3 |
| Sprint 1 §3.1 Phase A (IMAP foundation) | ✅ session 3 |
| Sprint 1 §3.1 Phase B+C (orchestrator + launchd) | ✅ session 4 |
| Sprint 1 §3.2 (Bexio push) | ✅ session 4 |
| **Sprint 1 §3.3 (multi-mandant E2E N=3)** | ✅ **session 5** |
| **Sprint 1 §3.4 (chiffrement at-rest)** | ✅ **session 5** (Fernet, pas SQLCipher) |
| **Sprint 1 §3.5 (backup chiffré)** | ✅ **session 5** |
| **Sprint 1 §3.6 (audit trail immutable)** | ✅ **session 5** |
| Sprint 1 §3.7 — Détection pièces manquantes | ⏳ session 6 |
| Sprint 1 §3.8 — WinBIZ export CSV/XML | ⏳ session 6 |
| Sprint 1 §3.9 — CAMT.053 rapprochement | ⏳ session 6+ |
| Sprint 1 §3.10 — Dashboard ext (audit view) | ⏳ session 6+ |

---

## 6. Contraintes non-négociables respectées

| Contrainte | Vérification |
|---|---|
| Aucun appel LLM externe | Tous tests E2E utilisent `_llm_panic` mock — confirme que vendor_history hit toujours, jamais d'appel LLM réel. |
| Aucune écriture Bexio "live" sans flag | `dry_run=True` reste défaut, double opt-in CLI inchangé (session 4). |
| PAT jamais loggé | Tests `test_pat_never_logged` existants toujours verts. |
| `.env` dans `.gitignore` | OK. Ajout des patterns `config/account-map-*.json`, `config/tax-map-*.json`, `data/backups/`, `data/locks/`. |
| Multi-mandant first-class | 10 tests E2E dédiés (§3.3). Chain audit isolée par cabinet. Clés encryption distinctes par cabinet. |
| TDD strict | 57 tests neufs, tous écrits AVANT ou EN MÊME TEMPS que les modules. |
| Pas de LangChain/etc. | Seules nouvelles deps : `cryptography` (Fernet). Pure Python par ailleurs. |
| Audit CLAUDE.md | Effectué. 246 tests passing, 0 régression. |

---

## 7. Issues / TODOs Session 6+

### Smoke tests prod restants (Tanguy)

- [ ] IMAP réel cabinet pilote (session 4 USER ACTION MAP)
- [ ] Bexio sandbox push (session 4)
- [ ] Encryption archive cabinet (§4 ci-dessus)
- [ ] Backup quotidien activé (§4)
- [ ] Audit trail chain verify après 10+ cycles (§4)

### Modules à livrer Session 6+

- [ ] **§3.7 Détection pièces manquantes + relances draft** : croiser
  `documents` × `email_messages` × historique cabinet pour repérer
  "j'attends une facture de X mais elle n'arrive pas". Génère un draft
  d'email de relance, validation humaine obligatoire avant envoi.
- [ ] **§3.8 WinBIZ export CSV/XML** : format export fallback si l'API
  WinBIZ partenariat n'est pas accordé en juin. CSV standard import
  WinBIZ + XML alternative.
- [ ] **§3.9 CAMT.053 bancaire** : parser CAMT.053 standard ISO 20022,
  rapprochement automatique paiements ↔ factures.
- [ ] **§3.10 Dashboard `/audit`** : vue Next.js du audit_log avec
  filtres + export texte.

### Tests à ajouter Session 6+

- [ ] Test launchd backup réel (créer/restaurer, sur Mac Mini cabinet)
- [ ] Test concurrent backup + IMAP fetch simultanés (lock files OK ?)
- [ ] Bench performance backup sur 1000 docs + 500 MB archive
- [ ] Test rotation clé en prod (1 cabinet, sans downtime)

### Améliorations techniques Sprint 2

- [ ] SQLCipher pour la DB (quand install pipeline automatisée disponible)
- [ ] TSA externe pour signer périodiquement le final chain hash
- [ ] Export PDF audit (weasyprint ou reportlab)
- [ ] Backup offsite chiffré (Backblaze B2 / rsync.net)
- [ ] Restore sélectif par cabinet
- [ ] Compaction audit_log >3 ans → fichier signé externe

---

## 8. Commande de relance Session 6

```
/clear

[paste master prompt Option Z]

Reprends Sprint 1 §3.7+ (détection pièces manquantes, WinBIZ CSV,
CAMT.053, dashboard /audit). Sessions 1-5 livrées : core POC + IMAP
foundation + Bexio push + multi-mandant E2E + encryption Fernet +
backup 30/12/10 + audit trail immutable. 246 tests verts, 0 régression.
Avant Session 6, Tanguy doit avoir : (1) FileVault confirmé actif sur
Mac Mini cabinet, (2) encrypt_archive_files.py exécuté pour pilote-jura-01,
(3) launchd backup activé, (4) IMAP réel cabinet smoke testé, (5)
Bexio sandbox push smoke testé.
```
