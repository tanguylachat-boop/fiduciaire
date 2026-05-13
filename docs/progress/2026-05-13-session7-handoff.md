# Session 7 — Handoff Option Z (DERNIÈRE AVANT INSTALL)

**Date :** 2026-05-13
**Branche :** `feature/sprint-0a-core` (commit pushed)
**Statut :** Sprint 1 **§3.9 + §3.7 finition + Tests E2E livrés**. §3.10 dashboard reporté Sprint 2 (autorisé par brief §5).

---

## 1. Bilan modules livrés

### Sprint 1 §3.9 — CAMT.053 + bank_matcher

| Fichier | LoC | Statut |
|---|---|---|
| `worker/src/fiduciaire_worker/bank_camt.py` | 330 | parser namespace-agnostic + import + queries |
| `worker/tests/test_bank_camt.py` | 280 | **12 tests verts** |
| `worker/src/fiduciaire_worker/bank_matcher.py` | 280 | 3 stratégies + audit hooks + manual link/unlink |
| `worker/tests/test_bank_matcher.py` | 280 | **13 tests verts** |
| `worker/scripts/import_camt.py` | 85 | nouveau CLI |
| `worker/scripts/run_bank_matcher.py` | 80 | nouveau CLI |

**3 stratégies de matching :** qr_exact (conf 1.0, auto-apply), amount_date_exact (conf 0.85, suggestion), fuzzy ±2% (conf 0.65, suggestion).

**Décision clé :** IBAN PAS chiffré (semi-public + filtres dashboard).
FileVault couvre repos. Détails dans decision doc.

### Sprint 1 §3.7 finition — 2 règles dépendantes CAMT.053

| Fichier | LoC | Statut |
|---|---|---|
| `worker/src/fiduciaire_worker/missing_docs_detector.py` | +110 | 2 nouvelles règles + types constants |
| `worker/tests/test_missing_docs_detector.py` | +110 | **5 nouveaux tests verts** (18 total) |

**Règles ajoutées :**
4. `unpaid_invoice_overdue` : entry > 60j sans bank_transactions.matched_accounting_entry_id (plus précis que `unpaid_invoice` qui regardait juste bexio_id)
5. `payment_without_invoice` : bank_tx CRDT non matchée > 7j grace

**Silent skip** si table `bank_transactions` absente (back-compat).

### Tests E2E Sprint 1 complet

| Fichier | LoC | Statut |
|---|---|---|
| `worker/tests/test_sprint1_e2e.py` | 220 | **2 tests verts** |

**Scénario E2E `test_sprint1_full_pipeline_3_mandants`** parcourt :
1. Seed 3 mandants → 30 documents synthétiques
2. Propose 30 entries (vendor history hit, pas de LLM)
3. Validate 5 entries du pilote (workflow + audit log)
4. Bexio push dry-run → 5 skipped_dry_run
5. Import CAMT.053 avec QR-ref matchant 1 entry
6. Run bank_matcher → 1 auto_matched strategy=qr_exact confidence=1.0
7. Scan anomalies → toutes règles
8. WinBIZ export CSV → 5 rows exportées
9. Verify audit chain → VALID pour chaque cabinet
10. Backup tar.gz Fernet → verify_backup_restorable OK
11. Assertions multi-mandant : chaque cabinet a 10 entries, bank_tx isolées

**Performance : ~0.4s** (loin du seuil <60s du brief).

`test_sprint1_audit_chain_resists_tampering` : valide qu'altérer une row audit_log casse la chain (sécurité).

### Sprint 1 §3.10 dashboard — REPORTÉ Sprint 2

Autorisé par brief §5 "peuvent être reportés Session 8 si nécessaire".

**Justification pragmatique :**
- Le dashboard Next.js actuel `/(poc)/entries` suffit pour démo install pilote
- Decrypt côté serveur Next.js (Keychain) reste complexe (Sprint 2 : proxy Python local)
- Toutes les API Python sont prêtes pour être consommées par futur dashboard
- Priorité absolue brief §5 = §3.9 + tests E2E → tous deux livrés ✅

---

## 2. Métriques tests

| Catégorie | Avant Session 7 | Après Session 7 | Delta |
|---|---:|---:|---:|
| **Tests Python** | 290 | **322** | **+32** |
| bank_camt | 0 | 12 | +12 |
| bank_matcher | 0 | 13 | +13 |
| missing_docs (finition) | 13 | 18 | +5 |
| sprint1_e2e | 0 | 2 | +2 |
| autres | 277 | 277 | 0 |
| **Régressions** | — | **0** | — |
| Suite complète | ~52s | ~73s | +21s (E2E + tests bank) |

`.venv/bin/python -m pytest tests/ -q` → `322 passed in 73.18s`.

---

## 3. Décisions techniques Session 7

1. [`2026-05-13-camt053-bank-matcher.md`](../decisions/2026-05-13-camt053-bank-matcher.md)
   — Parser CAMT.053 namespace-agnostic, 3 stratégies matching priorisées,
   IBAN non chiffré (semi-public), audit log hooks sur tout match.

---

## 4. USER ACTION MAP — Tanguy avant install femme Gravosig

(Consolide les sessions 4-7 — checklist install pilote)

### Hardware

- [ ] Mac Mini 32 GB minimum (le 24B Mistral tient)
- [ ] FileVault macOS actif (`fdesetup status`)
- [ ] Stockage > 256 GB pour archive + backups longs

### Logiciel à installer

- [ ] Ollama installé + modèle `mistral-small:24b-instruct-2501-q4_K_M` pulled
- [ ] Tesseract OCR + paquets langue fr + de
- [ ] Python 3.12+, pip, venv créé dans `worker/.venv/`
- [ ] `pip install -e worker/` (dépendances)
- [ ] `pip install cryptography` (Fernet) — déjà dans pyproject

### Credentials à obtenir d'elle

Pour chaque mandant (Sprint 1 : 1-3 mandants pilote) :
- [ ] Bexio PAT (Profil → API → Personal access token) — à stocker Keychain
- [ ] IBAN bancaire(s) du mandant (pour CAMT.053)
- [ ] WinBIZ Cloud credentials (export CSV/import, Sprint 2 API)
- [ ] Account map Bexio (numéros comptes Bexio → IDs internes)
- [ ] Tax map Bexio (TN_NORM → tax_id Bexio)

### Configuration

- [ ] `config/clients/<mandant_id>.yaml` pour chaque mandant :
  ```yaml
  client_id: pilote-jura-01
  cabinet_name: "Fiduciaire Gravosig"
  bexio:
    pat_keychain_user: "bexio-pat-pilote-jura-01"
  imap:
    host: "mail.infomaniak.com"
    port: 993
    folder: "INBOX"
  encryption:
    cabinet_keychain_user: "encryption-key-pilote-jura-01"
  ```

### Clés Keychain à créer

```bash
# Pour CHAQUE mandant :
python -c "import keyring; keyring.set_password('fiduciaire', 'bexio-pat-pilote-jura-01', 'BEXIO_PAT_VALUE')"
python -c "import keyring; keyring.set_password('fiduciaire', 'imap-pilote-jura-01-password', 'APP_PWD')"

# Encryption key (générée automatiquement par ensure_master_key) :
python -c "from fiduciaire_worker.encryption import ensure_master_key; ensure_master_key('pilote-jura-01')"

# Backup master key (généré automatique au 1er backup) :
python worker/scripts/backup_now.py --verify
```

### Migration colonnes chiffrées (sur DB sandbox d'abord)

```bash
worker/.venv/bin/python worker/scripts/migrate_encrypt_columns.py \
  --client-id pilote-jura-01 --dry-run

# Si OK :
worker/.venv/bin/python worker/scripts/migrate_encrypt_columns.py \
  --client-id pilote-jura-01
```

### LaunchAgents à activer

```bash
# IMAP fetch toutes les 5 min :
deploy/install-launchd.sh pilote-jura-01

# Backup quotidien 03:00 :
deploy/install-backup-launchd.sh
```

### Tests de validation install (à passer chez elle avant validation pilote)

1. **Ingestion mail → écriture proposée** :
   - Envoyer un mail avec PDF facture à factures@pilote-jura
   - Attendre cycle launchd (5 min)
   - Vérifier `data/inbox/` puis `data/archive/`
   - Vérifier `accounting_entries` populée

2. **Validation manuelle dashboard** :
   - Ouvrir `dashboard` (Next.js)
   - Page `/entries` → entries en `proposed`
   - Click "Valider" → state → `validated` + audit log

3. **Push Bexio sandbox** (PAS prod tant que pas validé) :
   ```bash
   BEXIO_PUSH_LIVE=true worker/.venv/bin/python worker/scripts/bexio_push.py \
     --client-id pilote-jura-01 --live --limit 1 \
     --account-map config/account-map-pilote-jura-01.json \
     --tax-map config/tax-map-pilote-jura-01.json
   ```
   Vérifier dans Bexio sandbox que l'écriture apparaît.

4. **Import CAMT.053 + matcher** :
   ```bash
   worker/.venv/bin/python worker/scripts/import_camt.py \
     --client-id pilote-jura-01 --mandant pilote-jura-01 \
     --file data/inbox/camt053-2026-05.xml

   worker/.venv/bin/python worker/scripts/run_bank_matcher.py \
     --client-id pilote-jura-01
   ```

5. **WinBIZ export** :
   ```bash
   worker/.venv/bin/python worker/scripts/winbiz_export.py \
     --client-id pilote-jura-01 \
     --output exports/pilote-2026-q2.csv \
     --date-from 2026-04-01 --date-to 2026-06-30
   ```
   Importer le CSV dans WinBIZ → vérifier que les écritures arrivent.

6. **Anomalies** :
   ```bash
   worker/.venv/bin/python worker/scripts/scan_anomalies.py \
     --client-id pilote-jura-01
   ```

7. **Audit chain verify** :
   ```bash
   python -c "
   from fiduciaire_worker import db, audit_log
   conn = db.connect('data/fiduciaire.sqlite')
   r = audit_log.verify_audit_chain(conn, 'pilote-jura-01')
   print(f'Chain valid: {r.is_valid} ({r.total_events} events)')
   "
   ```

---

## 5. État global Sprint 1 (toutes sessions)

| Composant | Statut |
|---|---|
| Sprint 0a — POC complet | ✅ sessions 1-2 |
| Sprint 1 §3.1 — IMAP (Phase A/B/C) | ✅ sessions 3-4 |
| Sprint 1 §3.2 — Bexio push | ✅ session 4 |
| Sprint 1 §3.3 — Multi-mandant N=3 | ✅ session 5 |
| Sprint 1 §3.4 — Chiffrement archive Fernet | ✅ session 5 |
| Sprint 1 §3.4-bis — Chiffrement colonnes | ✅ session 6 |
| Sprint 1 §3.5 — Backup 30/12/10 | ✅ session 5 |
| Sprint 1 §3.6 — Audit trail chain hash | ✅ session 5 |
| Sprint 1 §3.7 — Anomalies (5/5 règles) | ✅ session 6 + 7 |
| Sprint 1 §3.8 — WinBIZ CSV/XML | ✅ session 6 |
| **Sprint 1 §3.9 — CAMT.053 + matcher** | ✅ **session 7** |
| Sprint 1 §3.10 — Dashboard extensions | ⏳ **Sprint 2** |
| Tests E2E Sprint 1 | ✅ session 7 |

---

## 6. Commande de relance Sprint 2

```
/clear

[paste master prompt Sprint 2]

Reprends Sprint 2 — DASHBOARD + WINBIZ API NATIF + CRÉSUS/ABACUS +
REPORTING MENSUEL. Sprint 1 livré, 322 tests verts, branche
feature/sprint-0a-core commit dca06d3. Femme Gravosig install début juin
en cours. Apporteur d'affaires démarre. Lire docs/progress/sprint-1-complete.md
pour l'état complet.
```
