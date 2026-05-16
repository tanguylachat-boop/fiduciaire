# Session 12 — Handoff Option Z (Pilote Gravosig ready)

**Date :** 2026-05-16
**Branche :** `feature/sprint-0a-core`
**Statut :** Installation Gravosig prête. Provisioning + Bexio history
import + user docs FR + Gravosig seed + E2E install tests livrés. 5
chantiers menés à bien.

---

## 1. Bilan modules livrés

### Chantier 1 — Provisioning cabinet idempotent

| Fichier | LoC | Statut |
|---|---:|---|
| `worker/src/fiduciaire_worker/cabinet_provisioning.py` | 290 | nouveau — pipeline 1-command |
| `worker/src/fiduciaire_worker/plan_comptable_seed.py` | 60 | nouveau — 28 comptes KMU |
| `worker/scripts/provision_cabinet.py` | 145 | nouveau — CLI |
| `worker/tests/test_cabinet_provisioning.py` | 250 | **11 tests verts** |
| `docs/decisions/2026-05-16-cabinet-provisioning.md` | 100 | decision doc |

**Features :**
- 1 commande crée : arborescence dossiers + `config.yaml` + tables
  `cabinets` / `mandants` / `chart_of_accounts` + seed plan comptable
  KMU 28 comptes + audit event
- Idempotent : sans `--force`, échoue proprement si cabinet existe
- `--force` réécrit cabinet/mandants/config (plan comptable préservé)
- Validations strictes : slug, lang fr/de/it, logiciel
  bexio/winbiz/cresus/abacus
- Multi-mandant strict (test cross-mandant explicite COA)
- Audit log `cabinet_provisioned` / `cabinet_re_provisioned`

### Chantier 2 — Import historique Bexio

| Fichier | LoC | Statut |
|---|---:|---|
| `worker/src/fiduciaire_worker/bexio_history_import.py` | 215 | nouveau — pull paginé |
| `worker/scripts/import_bexio_history.py` | 130 | nouveau — CLI |
| `worker/tests/test_bexio_history_import.py` | 240 | **7 tests verts** |
| `docs/decisions/2026-05-16-bexio-history-import.md` | 90 | decision doc |

**Features :**
- Pull N mois (défaut 12) paginé (100/page) avec rate limit conservateur
  (1.2s/page = ~50 req/min < limite PAT standard 60)
- Backoff exponentiel sur HTTP 429 (max 3 retries)
- Idempotence via PK `bexio_sync` (cabinet_id, entity_type, entity_id)
- `--force-refresh` purge avant pull
- `--dry-run` : pas d'écriture, pas d'audit
- Reconstruit automatiquement `vendor_account_history` après pull
- Audit event `bexio_history_imported` avec rows counts
- **PAT jamais loggé** (test `caplog` explicite)
- Cross-mandant strict (test isolation explicite)
- Tests : mock `httpx.MockTransport`, zéro appel réseau réel

### Chantier 3 — Documentation utilisateur FR

| Fichier | Description |
|---|---|
| `docs/user-guide/01-installation.md` | Mac Mini + premier démarrage |
| `docs/user-guide/02-premier-document.md` | Inbox + classification |
| `docs/user-guide/03-validation-ecritures.md` | Page /entries |
| `docs/user-guide/04-matching-bancaire.md` | CAMT.053 + page /bank |
| `docs/user-guide/05-exports-comptables.md` | Bexio + Crésus + Abacus + Winbiz |
| `docs/user-guide/06-rapport-mensuel.md` | Génération PDF mensuel |
| `docs/user-guide/07-audit-trail.md` | Audit chain + contrôle fiscal |
| `docs/user-guide/08-faq-troubleshooting.md` | FAQ + dépannage 20 cas |
| `worker/scripts/generate_user_guide_pdf.py` | Compile MD → 1 PDF imprimable |
| `docs/user-guide.pdf` | **199 KB généré, prêt à imprimer** |

**Style :** phrases courtes, jargon explicité, captures écran en
placeholders à compléter sur place. Couverture + table des matières
automatiques. A4 portrait, sobre, Inter/Helvetica.

### Chantier 4 — Seed Gravosig pilot

| Fichier | LoC | Statut |
|---|---:|---|
| `worker/scripts/seed_gravosig_pilot.py` | 130 | nouveau — wrapper provision |
| `docs/decisions/2026-05-16-gravosig-pilot-setup.md` | 70 | decision doc |

**Features :**
- 1 commande pré-remplie : cabinet `gravosig-fiduciaire-01` (Winbiz,
  Delémont JU) + 3 mandants placeholder Bexio
- Affiche checklist install 10 points à dérouler sur place
- Idempotent (rejette si déjà provisionné, donne la commande --force)

### Chantier 5 — Tests E2E install

| Fichier | LoC | Statut |
|---|---:|---|
| `worker/tests/test_e2e_cabinet_install.py` | 230 | **2 tests verts** |

**Features :**
- `test_e2e_cabinet_install_full_flow` : provision → mock Bexio import
  → docs inbox → entries proposed → 2 validations → export Crésus +
  Abacus → rapport mensuel MD → verify_audit_chain. Durée ~0.1s.
- `test_e2e_cross_mandant_isolation_smoke` : 2 cabinets, vérifie
  chain audit isolée + COA isolé + zéro leak.

---

## 2. Métriques tests

| Catégorie | Avant Session 12 | Après Session 12 | Delta |
|---|---:|---:|---:|
| Tests Python | 354 | **374** | **+20** |
| ↳ test_cabinet_provisioning.py | 0 | 11 | +11 |
| ↳ test_bexio_history_import.py | 0 | 7 | +7 |
| ↳ test_e2e_cabinet_install.py | 0 | 2 | +2 |
| Smoke TS | 42 | **42** | — |
| Typecheck `tsc --noEmit` | clean | **clean** | — |
| Build Next.js | OK | **OK** (Compiled 1.6s) | — |
| Pytest full pass | 354/354 | **374/374** | +20 |

**Tests cumulés** : 374 Python + 42 smoke TS = **416 tests** passing.

---

## 3. Décisions techniques Session 12

[`2026-05-16-cabinet-provisioning.md`](../decisions/2026-05-16-cabinet-provisioning.md) :
- Tables dédiées `cabinets` / `mandants` / `chart_of_accounts` (pas de
  hack via `bexio_sync`)
- Plan comptable seed = 28 comptes KMU minimum (suffit ~95% du volume)
- f-string pour config.yaml (pas de Jinja2, overkill)

[`2026-05-16-bexio-history-import.md`](../decisions/2026-05-16-bexio-history-import.md) :
- Pull paginé `date_from`/`date_to` avec offset (compat API Bexio 3.0)
- Rate limit conservateur 50 req/min vs limite 60
- Idempotence via PK `bexio_sync`, pas de logic métier ad-hoc
- 1 mandant à la fois (anti-corrélation, plus simple à debug)

[`2026-05-16-gravosig-pilot-setup.md`](../decisions/2026-05-16-gravosig-pilot-setup.md) :
- Script wrapper dédié, pas de flag `--gravosig` polluant le générique
- Checklist install affichée par le script lui-même
- Renommage mandants placeholder → réels via `provision_cabinet --force`

---

## 4. USER ACTION MAP — Tanguy AVANT install Gravosig

### Pré-install (avant départ chez Gravosig)

```bash
cd /Users/tanguylachat/fiduciaire

# 1. Imprimer le manuel utilisateur (à laisser sur place)
open docs/user-guide.pdf
# Cmd+P → impression recto-verso, agrafer en livret

# 2. Préparer le Mac Mini chez toi
# - macOS à jour
# - Ollama installé : curl -fsSL https://ollama.com/install.sh | sh
# - Pull modèles :
#     ollama pull llama3.3:70b-instruct-q4_K_M
#     ollama pull qwen2.5vl:7b-q4_K_M
# - Clone le repo : git clone <repo-url> ~/fiduciaire
# - Setup venv : cd worker && python3.12 -m venv .venv && .venv/bin/pip install -e .

# 3. Smoke test pré-départ sur ton MBP :
worker/.venv/bin/python -m pytest -q
# Doit afficher : 374 passed
```

### Sur place chez Gravosig (jour J, 4h)

```bash
# 1. Vérification matériel (5 min)
# Mac Mini branché, écran allumé, réseau OK

# 2. Seed Gravosig (15 secondes)
cd ~/fiduciaire
worker/.venv/bin/python worker/scripts/seed_gravosig_pilot.py
# → crée cabinet gravosig-fiduciaire-01 + 3 mandants placeholder + plan comptable
# → affiche la checklist install à dérouler

# 3. Récupérer le PAT Bexio cabinet (5 min)
# Loger la femme Gravosig sur https://office.bexio.com
# Profil → Réglages → API → "Personal Access Token"
# Scope lecture seule → copier le token

# 4. Stocker le PAT dans Keychain (1 min)
.venv/bin/python -c "
import keyring
keyring.set_password('fiduciaire-ai', 'bexio-pat-<vrai-nom-mandant-1>', '<PAT>')
"
# Répéter pour chaque mandant Bexio

# 5. Renommer les mandants placeholder (2 min)
# Quand tu as les vrais noms des 3 mandants PME :
worker/.venv/bin/python worker/scripts/provision_cabinet.py --force \\
  --cabinet-id gravosig-fiduciaire-01 \\
  --cabinet-name "Gravosig Fiduciaire" \\
  --ville Delémont --canton JU --lang fr --logiciel winbiz \\
  --mandants "<vrai-m1>,<vrai-m2>,<vrai-m3>"

# 6. Import historique Bexio (5-15 min selon volume)
# Pour chaque mandant Bexio (cabinet est Winbiz, pas concerné) :
worker/.venv/bin/python worker/scripts/import_bexio_history.py \\
  --cabinet-id gravosig-fiduciaire-01 \\
  --mandant-id <vrai-m1> --months 12

# 7. Smoke test : déposer 1 PDF de Gravosig dans inbox
cp ~/Desktop/test.pdf data/clients/gravosig-fiduciaire-01/inbox/
# Attendre 30s puis ouvrir http://localhost:3000/documents
# Le PDF doit être classé + une écriture proposée

# 8. Démo validation manuelle (5 min)
open http://localhost:3000/entries
# Valider 1 écriture devant la femme Gravosig

# 9. Démo export Crésus (5 min)
worker/.venv/bin/python worker/scripts/cresus_export.py \\
  --client-id gravosig-fiduciaire-01 \\
  --output /tmp/cresus-demo.xml --dry-run
# Montrer le fichier généré

# 10. Démo rapport mensuel PDF (5 min)
worker/.venv/bin/python worker/scripts/generate_monthly_report.py \\
  --cabinet-id gravosig-fiduciaire-01 \\
  --client-id gravosig-fiduciaire-01 \\
  --year 2026 --month 5 \\
  --output-dir reports/ \\
  --cabinet-label "Gravosig Fiduciaire"
open reports/gravosig-fiduciaire-01_2026-05_report.pdf

# 11. Démo audit trail (5 min)
open "http://localhost:3000/audit?client=gravosig-fiduciaire-01"
# Montrer la chaîne, cliquer "Vérifier la chaîne"

# 12. Backup initial (1 min)
worker/.venv/bin/python worker/scripts/backup_now.py
ls -lh data/backups/
```

### Checklist pré-installation (matériel + accès)

- [ ] Mac Mini M4 Pro 64GB livré + câbles HDMI + clavier + souris
- [ ] Photo PDF du serial du Mac Mini (warranty Apple)
- [ ] Accès réseau Ethernet du cabinet Gravosig confirmé
- [ ] Mot de passe Bexio cabinet pour générer le PAT
- [ ] Si CAMT.053 : login e-banking pour télécharger un relevé test
- [ ] Manuel imprimé recto-verso, agrafé
- [ ] `decisions/2026-05-16-gravosig-pilot-setup.md` lu
- [ ] Tests pré-départ verts : `pytest -q` → 374 passed
- [ ] `docs/user-guide.pdf` à jour (199 KB)
- [ ] Numéro de téléphone direct de la femme Gravosig

---

## 5. État global Sprint 2

| Module | Statut |
|---|---|
| §3.10 dashboard /audit + /bank + /clients/[id] | ✅ sessions 9-10 |
| Crésus export XML | ✅ session 10 |
| Reporting mensuel MD + PDF | ✅ sessions 10-11 |
| Abacus AbaConnect XML | ✅ session 11 |
| **Provisioning cabinet idempotent** | ✅ **session 12** |
| **Import historique Bexio** | ✅ **session 12** |
| **User guide FR + PDF** | ✅ **session 12** |
| **Seed Gravosig pilot** | ✅ **session 12** |
| **E2E install test** | ✅ **session 12** |
| Connecteur Winbiz API natif | ⏳ post clé Raphael |
| Pré-bouclement automatique | ⏳ Sprint 3 |
| Bilan + PP brouillon | ⏳ Sprint 3 |
| WhatsApp/Telegram bridge | ⏳ Sprint 3 |

---

## 6. Contraintes non-négociables vérification

| Contrainte | Vérification |
|---|---|
| TDD strict | Tests AVANT prod : 11+7+2 = 20 nouveaux RED→GREEN |
| Multi-mandant first-class | Tests cross-mandant explicites (provisioning COA, bexio import, E2E) |
| Encryption decrypt automatique | Hérité existant (PDF reporting + exports déjà couverts S10/11) |
| Audit log opérations sensibles | `cabinet_provisioned`, `bexio_history_imported` implémentés + tests |
| Aucun appel LLM externe | Cette session ne touche pas le LLM |
| PAT/clés jamais loggés | Test `caplog` explicite Session 12 (test_history_import_pat_not_logged) |
| Zéro régression | 354→374 Python (sans casse Sprint 1/2), 42→42 smoke TS |
| Typecheck + Next build | Clean / OK |

---

## 7. Reste Sprint 2 / Sprint 3

**Sprint 2 reste :**
- Connecteur Winbiz API natif (attente clé Raphael — bloqué externe)
- (Optionnel) Retrofitter audit log live sur Crésus + Winbiz exports
  (3 lignes par module, non critique)

**Sprint 3 prévu :**
- Pré-bouclement automatique (raffiner trésorerie + écritures
  régularisation TVA, charges payées d'avance, factures non parvenues)
- Bilan + PP brouillon
- WhatsApp/Telegram bridge fiduciaire ↔ client mandant
- Plan comptable étendu (200+ comptes via pull Winbiz natif)
- Templates PDF personnalisables par cabinet

**Post-install Gravosig :**
- Récolter feedback semaine 1 (qu'est-ce qui marche / qu'est-ce qui
  bloque)
- Compléter `docs/user-guide/` avec captures d'écran réelles
- Ajuster `--rate-limit-req-per-min` Bexio si Pro PAT (Gravosig en
  ont probablement un, 300 req/min)

---

## 8. Commande de relance Session 13

```
/clear

[paste master prompt Sprint 2]

Reprends Sprint 2 / Sprint 3. Session 12 a livré le pack "pilote-ready" :
provisioning cabinet + Bexio history import + user docs FR + Gravosig seed
+ E2E install tests. 416 tests verts (374 Python + 42 smoke TS).

Décision Tanguy avant Session 13 :
A. Si install Gravosig OK + feedback récolté → Sprint 3 (pré-bouclement
   automatique, bilan/PP brouillon, WhatsApp bridge)
B. Si install Gravosig incidents → debug + patch + retest E2E
C. Si clé Raphael Winbiz reçue → winbiz_client.py natif (pattern Bexio
   double opt-in WINBIZ_LIVE_WRITES=true)

Avant Session 13, vérifier :
- docs/user-guide.pdf imprimé et à jour
- Tests verts : worker/.venv/bin/python -m pytest -q
- Install Gravosig terminée (ou rendez-vous reporté)
```
