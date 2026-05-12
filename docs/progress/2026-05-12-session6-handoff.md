# Session 6 — Handoff Option Z

**Date :** 2026-05-12
**Branche :** `feature/sprint-0a-core` (commit pushed)
**Statut :** Sprint 1 **§3.4-bis + §3.7 + §3.8 livrés**. §3.10 dashboard reporté Session 7 (priorité §5 du brief).

---

## 1. Bilan modules livrés

### Sprint 1 §3.4-bis — Column encryption applicative

| Fichier | LoC | Statut |
|---|---|---|
| `worker/src/fiduciaire_worker/encryption.py` | +180 | encrypt/decrypt_column_value + helpers + migration |
| `worker/tests/test_column_encryption.py` | 320 | **20 tests verts** (16 unit + 4 E2E) |
| `worker/scripts/migrate_encrypt_columns.py` | 130 | nouveau CLI |
| `worker/src/fiduciaire_worker/entry_proposer.py` | +5 | encrypt description + reasoning AVANT INSERT |
| `worker/src/fiduciaire_worker/vendor_account_history.py` | +30 | encrypt vendor_name + decrypt fallback in-memory |
| `worker/src/fiduciaire_worker/imap_fetch.py` | +5 | encrypt body_excerpt + from_addr AVANT INSERT |
| `worker/src/fiduciaire_worker/bexio_push.py` | +5 | decrypt description AVANT POST Bexio |
| `worker/tests/conftest.py` | +5 | `FIDUCIAIRE_ENCRYPTION_DISABLED=true` autouse (non-régression) |

**5 colonnes texte chiffrées** : `accounting_entries.description`,
`accounting_entries.reasoning`, `vendor_account_history.vendor_name`,
`email_messages.body_excerpt`, `email_messages.from_addr`.

**Décision :** `amount_chf` REAL **non chiffrée** (casserait
agrégations SUM/ORDER BY ; montant seul = peu PII). Détails dans la
decision doc.

### Sprint 1 §3.8 — WinBIZ export CSV/XML

| Fichier | LoC | Statut |
|---|---|---|
| `worker/src/fiduciaire_worker/winbiz_export.py` | 230 | CSV + XML générique |
| `worker/tests/test_winbiz_export.py` | 195 | **11 tests verts** |
| `worker/scripts/winbiz_export.py` | 130 | nouveau CLI |
| `worker/src/fiduciaire_worker/accounting_schema.py` | +2 | colonne `winbiz_exported_at` idempotente |

**Format CSV** : Date;Compte_Debit;Compte_Credit;Montant;Description;Code_TVA;Journal;Reference_Bexio
(UTF-8 BOM, séparateur `;`, ajustable selon retour cabinet).

**Idempotence** via `accounting_entries.winbiz_exported_at`.

### Sprint 1 §3.7 — Missing docs detector (3 règles sur 5)

| Fichier | LoC | Statut |
|---|---|---|
| `worker/src/fiduciaire_worker/missing_docs_detector.py` | 260 | 3 règles + table anomalies + workflow |
| `worker/tests/test_missing_docs_detector.py` | 230 | **13 tests verts** |
| `worker/scripts/scan_anomalies.py` | 90 | nouveau CLI |

**Règles livrées Sprint 1 :**
1. `vat_no_evidence` (TVA sans justif valide via LEFT JOIN documents.archive_path)
2. `potential_duplicate` (même montant + dates ±5j)
3. `unpaid_invoice` (> 60j sans bexio_id)

**Reportées Sprint 2 :** `payment_without_invoice` (nécessite §3.9 CAMT.053),
`orphan_credit_note` (règles métier cabinet à finaliser).

### Sprint 1 §3.10 — Dashboard extensions

**Reporté Session 7** (autorisé par brief §5 "peuvent être reportés
Session 7 si nécessaire"). Saturation pragmatique : §3.4-bis + §3.7 +
§3.8 étaient priorités absolues.

---

## 2. Métriques tests

| Catégorie | Avant Session 6 | Après Session 6 | Delta |
|---|---:|---:|---:|
| **Tests Python** | 246 | **290** | **+44** |
| column_encryption | 0 | 20 (16 unit + 4 E2E) | +20 |
| winbiz_export | 0 | 11 | +11 |
| missing_docs_detector | 0 | 13 | +13 |
| autres | 246 | 246 | 0 |
| **Régressions** | — | **0** | — |
| Suite complète | ~53s | ~52s | -1s |

`.venv/bin/python -m pytest tests/ -q` → `290 passed in 52.48s`.

---

## 3. Décisions techniques

1. [`2026-05-12-column-encryption-applicative.md`](../decisions/2026-05-12-column-encryption-applicative.md)
   — 5 colonnes texte chiffrées via marker `enc:v1:`, pas `amount_chf`,
   hooks dans 4 modules + helpers dict, migration script idempotent,
   mode disabled par défaut en tests.

2. [`2026-05-12-winbiz-export-format.md`](../decisions/2026-05-12-winbiz-export-format.md)
   — CSV générique 8 colonnes (UTF-8 BOM, séparateur `;`), pas de format
   propriétaire inventé, idempotence via colonne `winbiz_exported_at`,
   ajustable selon retour cabinet pilote.

3. [`2026-05-12-missing-docs-detector-rules.md`](../decisions/2026-05-12-missing-docs-detector-rules.md)
   — 3 règles Sprint 1 (vat_no_evidence, potential_duplicate, unpaid_invoice),
   table `anomalies` avec workflow resolve/false_positive, 2 règles reportées
   Sprint 2 (besoin CAMT.053 et cadrage métier).

---

## 4. USER ACTION MAP — Tanguy avant Session 7

### Pour column encryption en prod

1. **Vérifier que la clé maître archive est en Keychain** (déjà fait
   Session 5 si le smoke test encrypt_archive_files a tourné) :
   ```bash
   python -c "
   from fiduciaire_worker.encryption import get_master_key
   k = get_master_key('pilote-jura-01')
   print('Clé OK')
   "
   ```

2. **Backup la DB avant migration** :
   ```bash
   cp data/fiduciaire.sqlite data/fiduciaire.sqlite.pre-column-enc.bak
   ```

3. **Lancer migration dry-run d'abord** :
   ```bash
   worker/.venv/bin/python worker/scripts/migrate_encrypt_columns.py \
     --client-id pilote-jura-01 --dry-run
   ```
   Vérifier les compteurs (rows_encrypted, already_encrypted, null_or_empty).

4. **Migration prod** :
   ```bash
   worker/.venv/bin/python worker/scripts/migrate_encrypt_columns.py \
     --client-id pilote-jura-01
   ```

5. **Sanity check post-migration** :
   ```bash
   sqlite3 data/fiduciaire.sqlite "SELECT description FROM accounting_entries LIMIT 5"
   # → devraient afficher 'enc:v1:gAAAAAB...'
   ```

### Pour WinBIZ export

1. **Test dry-run** :
   ```bash
   worker/.venv/bin/python worker/scripts/winbiz_export.py \
     --client-id pilote-jura-01 --dry-run
   ```

2. **Export réel CSV trimestre Q2** :
   ```bash
   worker/.venv/bin/python worker/scripts/winbiz_export.py \
     --client-id pilote-jura-01 \
     --output exports/pilote-jura-01-2026-q2.csv \
     --date-from 2026-04-01 --date-to 2026-06-30
   ```

3. **Test import dans WinBIZ** : ouvrir le CSV dans Excel, vérifier
   l'encodage et le format. Si WinBIZ refuse, noter les colonnes
   manquantes/à renommer dans `docs/decisions/2026-05-12-winbiz-export-format.md`.

### Pour anomalies / missing docs

1. **Premier scan** :
   ```bash
   worker/.venv/bin/python worker/scripts/scan_anomalies.py \
     --client-id pilote-jura-01
   ```

2. **Workflow** : pour chaque anomalie open :
   - résoudre côté métier (ajouter le justificatif, payer la facture)
   - OU marquer false_positive si erreur de règle

### Pour l'install femme Gravosig (début juin)

Checklist consolidée à partir des sessions 4, 5, 6 :

- [ ] FileVault macOS actif sur Mac Mini cabinet (`fdesetup status`)
- [ ] Repo cloné dans `~/fiduciaire`, venv worker installé
- [ ] Bexio PAT pilote en Keychain (Session 4)
- [ ] IMAP credentials en Keychain (Session 4)
- [ ] Clé encryption archive en Keychain (`encryption-key-pilote-jura-01`, Session 5)
- [ ] Clé backup en Keychain (`encryption-key-backup-master`, Session 5)
- [ ] `migrate_encrypt_columns.py` exécuté (Session 6)
- [ ] LaunchAgent IMAP fetch activé (Session 4)
- [ ] LaunchAgent backup quotidien activé (Session 5)
- [ ] Maps account/tax JSON cabinet préparés (Session 4)
- [ ] Smoke test : ingestion 5 docs → propose → validate → bexio_push sandbox

---

## 5. État global

| Composant | Statut |
|---|---|
| Sprint 0a + Sprint 1 §3.1 à §3.6 | ✅ sessions 1-5 |
| **Sprint 1 §3.4-bis (column encryption)** | ✅ **session 6** |
| **Sprint 1 §3.7 (missing docs detector 3 règles)** | ✅ **session 6** |
| **Sprint 1 §3.8 (WinBIZ export CSV/XML)** | ✅ **session 6** |
| Sprint 1 §3.9 — CAMT.053 rapprochement | ⏳ session 7 |
| Sprint 1 §3.10 — Dashboard (`/clients/[id]`, `/deadlines`, `/audit`) | ⏳ session 7 |
| Sprint 1 §3.7 règles 4-5 (payment_without_invoice, orphan_credit_note) | ⏳ Sprint 2 (post-CAMT) |

---

## 6. Contraintes non-négociables respectées

| Contrainte | Vérification |
|---|---|
| Aucun appel LLM externe | Tests E2E utilisent `_llm_panic` mock. Aucun nouveau import LLM. |
| Aucune écriture Bexio "live" sans flag | `bexio_push` API inchangée (dry-run default + double opt-in CLI). |
| PAT/clés jamais loggés | `test_pat_never_logged` toujours vert. Migration script ne log que des compteurs. |
| `.env` dans `.gitignore` | OK + ajout `config/account-map-*.json`, `config/tax-map-*.json`, `data/backups/`, `data/locks/` (session 5). |
| Multi-mandant first-class | Tests E2E column encryption + winbiz export + anomalies isolés par cabinet_id. Clés crypto distinctes. |
| TDD strict | 44 tests neufs, écrits AVANT modules. |
| Pas de LangChain/etc. | Pas de nouvelle dépendance Session 6 (réutilise `cryptography` Fernet). |
| Audit CLAUDE.md | Effectué. 290 tests passing, 0 régression. |

---

## 7. Issues / TODOs Session 7+

### Smoke tests prod restants (Tanguy)

- [ ] migrate_encrypt_columns sur DB sandbox cabinet
- [ ] WinBIZ export test import dans logiciel cabinet
- [ ] scan_anomalies premier passage cabinet

### Modules à livrer Session 7

- [ ] **§3.10 Dashboard** : pages `/clients/[client_id]`, `/deadlines`, `/audit`
      avec server actions + decrypt automatique avant affichage UI
- [ ] **§3.9 CAMT.053** : parser ISO 20022, rapprochement automatique
      paiements ↔ factures
- [ ] **§3.7 règles 4-5** : `payment_without_invoice` (active post-CAMT)
      + `orphan_credit_note` (cadrer avec cabinet pilote)

### Améliorations techniques Sprint 2

- [ ] SQLCipher pour la DB complète (si compliance LPD renforcée demandée)
- [ ] AES-256-GCM via `cryptography.hazmat.AESGCM` (audit cabinet réclame
      AES-256 explicitement ?)
- [ ] Index hash déterministe sur description chiffrée pour potential_duplicate
      detection fine
- [ ] WinBIZ API native (si partenariat Raphael Perrier acquis)
- [ ] Re-open anomalies marquées résolues (workflow)
- [ ] Dashboard `/anomalies` UI avec resolve/false_positive
- [ ] Crésus / Abacus exports avec mêmes patterns que WinBIZ

---

## 8. Commande de relance Session 7

```
/clear

[paste master prompt Option Z]

Reprends Sprint 1 §3.9 (CAMT.053 rapprochement bancaire) + §3.10
(dashboard /clients/[id], /deadlines, /audit). Sessions 1-6 livrées :
290 tests Python verts. Avant Session 7, Tanguy doit avoir :
(1) migrate_encrypt_columns exécuté sur DB sandbox,
(2) Test WinBIZ export importé dans logiciel cabinet,
(3) Scan anomalies premier passage.
```
