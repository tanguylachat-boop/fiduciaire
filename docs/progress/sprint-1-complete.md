# SPRINT 1 — RAPPORT FINAL COMPLET

**Date livraison :** 2026-05-13
**Branche :** `feature/sprint-0a-core`
**Sessions :** 1-7 (7 sessions Option Z multi-handoff)
**Tests :** 322 Python passing, 0 régression, ~73s suite complète

---

## ✅ Modules livrés

### Sprint 0a — POC core (sessions 1-3)

| Module | Statut | Tests |
|---|---|---|
| `db.py` + schéma SQLite | ✅ | (inclus dans tests modules) |
| `prepare.py`, `qrbill.py`, `ocr.py` | ✅ | tests qrbill 9 verts |
| `classify.py` + prompt v2 fewshot | ✅ | tests classify intégration |
| `rename_route.py`, `review.py` | ✅ | tests rename/review |
| `entry_proposer.py` (vendor_history + LLM) | ✅ | tests entry_proposer |
| `bexio_client.py` (read-only) | ✅ | 7 tests bexio_client |
| Dashboard `/(poc)/entries` Next.js 16 | ✅ | 7 smoke TS |
| `ingest_local_corpus.py` | ✅ | 20 tests |
| Bench Mistral vs Llama (Mistral retenu) | ✅ | decision doc figée |

### Sprint 1 — Extension (sessions 3-7)

| §  | Module | Statut | Tests |
|---|---|---|---|
| 3.1 A | `email_parser.py` + `imap_client.py` + `secrets.py` IMAP | ✅ session 3 | 47 |
| 3.1 B | `imap_fetch.py` orchestrator + CLI | ✅ session 4 | 21 |
| 3.1 C | `process_lock.py` + launchd template | ✅ session 4 | 15 |
| 3.2 | `bexio_push.py` (dry-run + double opt-in) | ✅ session 4 | 17 |
| 3.3 | Multi-mandant E2E N=3 + stress 300 docs | ✅ session 5 | 10 |
| 3.4 | `encryption.py` Fernet pour archive files | ✅ session 5 | 19 |
| 3.4-bis | Column encryption (5 colonnes, marker `enc:v1:`) | ✅ session 6 | 20 |
| 3.5 | `backup.py` tar.gz + Fernet, rétention 30/12/10 | ✅ session 5 | 12 |
| 3.6 | `audit_log.py` chain SHA-256 immutable | ✅ session 5 | 16 |
| 3.7 | `missing_docs_detector.py` 5 règles | ✅ session 6+7 | 18 |
| 3.8 | `winbiz_export.py` CSV + XML | ✅ session 6 | 11 |
| 3.9 | `bank_camt.py` + `bank_matcher.py` | ✅ session 7 | 25 |
| 3.10 | Dashboard `/clients/[id]`, `/audit`, `/bank` | ⏳ **Sprint 2** | — |
| Tests | E2E Sprint 1 complet | ✅ session 7 | 2 |

**Total : 322 tests Python passing, 7 smoke TS dashboard.**

---

## 🏗️ Architecture finale

```
                              ┌────────────────────────┐
                              │   Mac Mini cabinet     │
                              │   (FileVault actif)    │
                              └───────────┬────────────┘
                                          │
              ┌───────────────────────────┼───────────────────────────┐
              │                           │                           │
              ▼                           ▼                           ▼
        ┌──────────┐               ┌──────────┐                ┌──────────┐
        │ IMAP TLS │               │ Bexio    │                │ Banque   │
        │ (5min)   │               │ API v3   │                │ CAMT.053 │
        │ Infomaniak│              │ (PAT)    │                │ XML      │
        └────┬─────┘               └────▲─────┘                └────┬─────┘
             │                          │                           │
             ▼                          │                           ▼
      ┌─────────────┐            ┌──────┴────────┐         ┌──────────────┐
      │ imap_fetch  │            │ bexio_push    │         │ bank_camt    │
      │  + lock     │            │  + audit      │         │  parser      │
      └─────┬───────┘            │  + dry-run    │         └──────┬───────┘
            │                    └───────────────┘                │
            ▼                              ▲                       ▼
      ┌───────────┐                       │              ┌──────────────┐
      │ pipeline  │                       │              │ bank_matcher │
      │ OCR+QR+   │                       │              │  3 strategies│
      │ classify  │                       │              │  + audit hook│
      └─────┬─────┘                       │              └──────┬───────┘
            │                              │                     │
            ▼                              │                     │
      ┌───────────┐               ┌────────┴──────┐              │
      │entry_     │──validate──▶  │workflow_states│              │
      │proposer   │               │ + audit hook  │              │
      │vendor_hist│               └───────────────┘              │
      │+ LLM      │                                              │
      └─────┬─────┘                                              │
            │                                                     │
            ▼                                                     ▼
      ┌─────────────────────────────────────────────────────────────┐
      │                                                             │
      │    SQLite WAL + Fernet column encryption (5 colonnes)       │
      │                                                             │
      │  ┌─────────────┐  ┌──────────────────┐  ┌──────────────┐    │
      │  │ documents   │  │accounting_entries│  │ vendor_       │    │
      │  └─────────────┘  └──────────────────┘  │ account_hist │    │
      │  ┌─────────────┐  ┌──────────────────┐  └──────────────┘    │
      │  │ bexio_sync  │  │entry_state_      │  ┌──────────────┐    │
      │  │             │  │ changes          │  │ bank_         │    │
      │  └─────────────┘  └──────────────────┘  │ transactions │    │
      │  ┌─────────────┐  ┌──────────────────┐  └──────────────┘    │
      │  │ email_      │  │ audit_log        │  ┌──────────────┐    │
      │  │ messages    │  │ (chain hash)     │  │ anomalies    │    │
      │  └─────────────┘  └──────────────────┘  └──────────────┘    │
      │  ┌─────────────┐                        ┌──────────────┐    │
      │  │ email_      │                        │ bexio_       │    │
      │  │ attachments │                        │ push_log     │    │
      │  └─────────────┘                        └──────────────┘    │
      └─────────────────────────────────────────────────────────────┘
            │                                                     ▲
            │ daily 03:00                                         │
            ▼                                                     │
      ┌──────────────┐                                            │
      │ backup tar.gz│  ◀── verify_backup_restorable mensuel ─────┘
      │ Fernet       │
      │ rétention    │      ┌──────────────────┐
      │ 30/12/10     │      │ winbiz_export    │ ────▶ CSV/XML
      └──────────────┘      │ (decrypt avant)  │       cabinet
                            └──────────────────┘
                                     ▲
                                     │
                            ┌────────┴──────────┐
                            │missing_docs_      │
                            │ detector (5 rules)│
                            └───────────────────┘
```

**Stack technique consolidée :**
- Python 3.12, stdlib + httpx + cryptography (Fernet) + watchdog + pyyaml
- SQLite WAL + Fernet column encryption (5 colonnes texte sensibles)
- Ollama local : Mistral Small 3 24B (par défaut, 32 GB Mac suffit)
- Dashboard Next.js 16 (existant `/(poc)/entries`, extensions Sprint 2)
- launchd macOS : IMAP fetch 5min + backup quotidien 03:00
- Keychain macOS : credentials + clés maîtres encryption (cabinet + backup-master)

---

## 🚀 Modules reportés Sprint 2 (avec justifications)

| § | Module | Pourquoi reporté |
|---|---|---|
| 3.10 | Dashboard `/clients`, `/audit`, `/bank` | UX moins critique que sécurité + intégrations. Le `/(poc)/entries` actuel suffit pour install pilote. Sprint 2 : pages complètes avec decrypt côté serveur. |
| 2.X | WinBIZ API native | Partenariat Raphael Perrier en signature aujourd'hui. CSV/XML fallback livré marche déjà. API native = Sprint 2 post-réception clé. |
| 2.X | Crésus export | Demande équivalente WinBIZ (CSV+XML) à coder Sprint 2 si cabinet pilote a un mandant Crésus. |
| 2.X | Abacus | Pas de demande pilote immédiate. |
| 2.X | WhatsApp Business API | DPA EU + Twilio config = complexe, Sprint 3+. |
| 2.X | Calendrier échéances réglementaires CH | Pas bloqueur pilote. Sprint 2 quand corpus cabinet permet de prioriser. |
| 2.X | Pré-bouclement / Bilan auto | Nécessite plusieurs mois de données pilote pour calibrer les heuristiques. Sprint 3+. |
| 2.X | SQLCipher complet (vs Fernet colonnes + FileVault) | Gain marginal sur Mac avec FileVault. Sprint 2 si compliance LPD demande AES-256 hardware. |
| 2.X | TSA externe pour audit_log chain | Sprint 3 si demande contrôle fiscal CH. |
| 2.X | Dashboard `/anomalies` UI | Sprint 2 avec les 3 autres pages dashboard. |

---

## 📊 Métriques finales Sprint 1

- **322 tests Python passing**, 0 régression (chacun des 7 commits a passé `pytest tests/`)
- **7 commits propres** sur `feature/sprint-0a-core` (ordre chronologique des sessions)
- **~13 modules Python** dans `worker/src/fiduciaire_worker/` (POC + Sprint 1)
- **~17 scripts CLI** dans `worker/scripts/`
- **~10 fichiers décisions techniques** dans `docs/decisions/`
- **0 dépendance LLM externe** (Ollama local exclusif)
- **0 secret commité** (`.env`, `config/account-map-*.json`, `config/tax-map-*.json` gitignored)
- **0 fuite cross-mandant** (vérifié par tests E2E `test_multi_mandant_e2e` + `test_sprint1_e2e`)

---

## ✅ Critères DONE Sprint 1 (revue)

- [x] IMAP auto avec poll 5min, lock POSIX, multi-cabinet
- [x] Push Bexio dry-run par défaut, double opt-in `--live` + env var
- [x] Multi-mandant testé sur 3 mandants synthétiques + stress 300 docs concurrent
- [x] Chiffrement at-rest : Fernet archive files + 5 colonnes texte sensibles
- [x] Backup automatisé chiffré, rétention 30/12/10 ans, verify_restorable
- [x] Audit trail immutable chain SHA-256, verify détecte tampering
- [x] Détection 5 règles anomalies (vat_no_evidence, potential_duplicate, unpaid_invoice, unpaid_overdue, payment_without_invoice)
- [x] WinBIZ export CSV/XML idempotent par cabinet + decrypt avant export
- [x] CAMT.053 parser multi-banques + bank_matcher 3 stratégies + audit hooks
- [x] Tests E2E complet `test_sprint1_full_pipeline_3_mandants` < 1s

---

## 🎯 Checklist install femme Gravosig (juin 2026)

Cf section 4 du handoff Session 7 (`2026-05-13-session7-handoff.md`).

Résumé :
1. Hardware Mac Mini 32 GB + FileVault
2. Ollama + Mistral Small 3 24B + Tesseract
3. Repo cloné + venv installé
4. Credentials Keychain : Bexio PAT × N mandants + IMAP password × N + encryption keys × N + backup-master
5. Config `config/clients/<mandant>.yaml` × N
6. Maps `config/account-map-*.json` + `config/tax-map-*.json` × N
7. `migrate_encrypt_columns.py` exécuté
8. LaunchAgents IMAP + backup activés
9. 7 tests de validation (mail→entry, validate UI, push Bexio sandbox, CAMT import+match, WinBIZ export, scan anomalies, audit chain verify)

---

## 🛣️ Plan Sprint 2 (juin-juillet 2026)

**Priorité commerciale :**
1. **Dashboard ext** `/clients/[id]`, `/audit`, `/bank`, `/anomalies` (UX install confort)
2. **Connecteur WinBIZ API natif** post-réception clé Raphael Perrier
3. **Crésus export** (CSV/XML similaire WinBIZ)

**Priorité fonctionnelle :**
4. **Reporting mensuel automatique** par mandant
5. **Pré-bouclement** (accruals, amortissements proposés)
6. **Bilan + PP brouillon** auto-générés

**Priorité sécurité (si LPD renforcée) :**
7. SQLCipher complet
8. TSA externe pour audit_log
9. Backup offsite chiffré (Backblaze B2, rsync.net)

**Priorité communication :**
10. WhatsApp Business API (DPA EU, Twilio)
11. Bot Telegram fallback

---

## 🙏 Crédits

- 7 sessions Claude Code Option Z multi-handoff
- Co-authored : Claude Opus 4.7 (1M context)
- Repo : `feature/sprint-0a-core` branch pushed à chaque session
