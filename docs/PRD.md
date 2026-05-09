# PRD V2 — Employé IA Fiduciaire

**Version :** 2026-05-08 (V2 — corrige les 4 blocages identifiés par l'agent technique + intègre le tri stratégique)
**Cible immédiate :** Sprint 0a livrable pour pilote cabinet du Jura (démarrage 11 mai 2026)
**Cible produit :** version commerciale stable mois 3 (août 2026)

---

## 0. CHANGEMENTS PAR RAPPORT À LA V1

Suite à l'assessment de l'agent technique, **4 blocages corrigés** :

1. **Timeline réaliste** : Sprint 0a réduit (3 jours, démo "j'évite la re-saisie" sans push Bexio) au lieu du Sprint 0 complet impossible.
2. **Hypothèse produit** : marché validé sur 10 cabinets ; nuance — le pattern d'usage exact "IA propose / fiduciaire valide en 1 clic" sera validé en conditions réelles pendant le pilote.
3. **"100% offline" reformulé** : *"données métier traitées 100% localement, jamais envoyées à OpenAI/Anthropic ; connexions sortantes limitées aux outils du cabinet (Bexio, IMAP) avec credentials du cabinet"*.
4. **Bexio auth** : Personal Access Token (PAT, équivalent API key) en Sprint 0a. OAuth2 reporté à la version multi-cabinet.

**4 ajouts stratégiques** (suite tri du dump ChatGPT) :

5. **Bench LLM** : Llama 3.3 70B vs Mistral Small 3 sur le corpus pilote (Mistral potentiellement meilleur en français).
6. **Pitch commercial verrouillé** : "100% local, zéro donnée hors cabinet" — pas de mention d'hybride cloud dans la com.
7. **Stack orchestration** : Python pur + Ollama. **Pas de n8n / LangChain / Flowise pour le cœur métier.** (n8n possible pour automations périphériques uniquement.)
8. **Allocation effort 70/20/10** : 70% intégrations + UX + stabilité, 20% qualité extraction LLM, 10% features avancées.

---

## 1. CONTEXTE & MISSION

Produit : **Employé IA Fiduciaire** — automatise la chaîne de traitement comptable d'un cabinet fiduciaire suisse, de la réception des pièces jusqu'à la proposition d'écritures dans le logiciel comptable du cabinet.

**Cible utilisateur :** cabinets fiduciaires suisses (5-30 collaborateurs), gérant 50-300 clients PME suisses.

**Différenciateur unique :** *"100% local sur serveur cabinet — vos données ne sortent jamais"*. Adresse la peur n°1 (confidentialité, LPD, fuite vers OpenAI).

**Contraintes non-négociables :**
- Données métier traitées 100% localement via Ollama (jamais d'appel LLM externe).
- Connexions sortantes limitées aux outils du cabinet eux-mêmes (Bexio API, IMAP, banque CAMT).
- Conforme LPD suisse révisée + archivage 10 ans.
- Multi-mandant strict.
- Workflow humain-dans-la-boucle pour TOUTE écriture comptable.
- Audit trail immutable (Sprint 1+).

**Ce qu'on NE construit PAS :**
- Pas de portail client web (l'IA va chercher les pièces là où elles sont déjà : email, WhatsApp, Bexio).
- Pas d'analyse type Goldman Sachs (les fiduciaires veulent gagner du temps, pas du raisonnement complexe).
- Pas de cloud hybride dans le pitch initial.

---

## 2. ÉTAT ACTUEL DU POC (à conserver)

```
data/inbox/         → watcher fichiers
data/archive/       → originaux SHA-256
data/clients/<client>/<année>/<type>/  → arborescence rangée
data/needs-review/  → docs faible confiance
SQLite              → tables documents + actions
Pipeline            → QR-bill → Tesseract fra+deu → fallback Qwen 2.5-VL → classifier LLM → renaming
Dashboard Next.js   → /review fonctionnel
config.yaml         → conventions par cabinet
```

**À CONSERVER tel quel.** Sprint 0a étend, ne refactore pas.

---

## 3. SPRINT 0a — VERSION HONNÊTE LIVRABLE LUNDI 11 MAI

**Objectif unique :** démo Loom 2 minutes — *"drag-drop facture → écriture proposée à l'écran → 1 clic validate"*. Le pitch tient sans push Bexio.

**3 jours, 1 mandant, sans ingestion email automatique, sans push Bexio.**

### 3.1 — `bexio_client.py` (lecture uniquement)
- Auth : **Personal Access Token (PAT)** — l'utilisateur génère son token dans l'interface Bexio en 5 min.
- Fonctionnalités Sprint 0a :
  - Pull plan comptable du mandant pilote
  - Pull 100 dernières écritures du mandant pilote (pour construire le cache fournisseur → compte)
  - Pull liste contacts (clients/fournisseurs)
- Cache local SQLite (table `bexio_sync`) avec horodatage de dernière sync.
- **Pas d'écriture vers Bexio en Sprint 0a.** Les écritures validées restent dans la base locale.

### 3.2 — `vendor_account_history.py` (heuristique simple, gain énorme)
- Table SQLite `vendor_account_history (vendor_id, account, vat_code, occurrences, last_seen)`.
- Construite à partir des 100 dernières écritures Bexio pulled.
- Permet de proposer instantanément le bon compte pour les fournisseurs récurrents (typiquement 60-70% du volume d'un cabinet).

### 3.3 — `entry_proposer.py` (CŒUR Sprint 0a)
- Input : document classifié (déjà fait par le POC) + extracted fields (montant, fournisseur, date, type).
- Stratégie 2 niveaux :
  - **Niveau 1 — heuristique vendor history** : si fournisseur déjà vu dans `vendor_account_history` → propose le compte le plus fréquent + TVA correspondante (haute confiance, instantané).
  - **Niveau 2 — LLM local** : si fournisseur inconnu → prompt LLM avec plan comptable du cabinet en contexte + function calling structuré.
- Output structuré :
  ```python
  {
      "client_id": str,
      "date": ISO_date,
      "debit_account": str,
      "credit_account": str,
      "amount_chf": Decimal,
      "vat_code": str,
      "vat_amount": Decimal,
      "description": str,
      "source_document_id": str,
      "confidence_account": float,   # 0-1, séparé
      "confidence_vat": float,       # 0-1, séparé (mesuré au bench)
      "reasoning": str,              # explication LLM, auditable
      "state": "proposed"
  }
  ```

### 3.4 — `vat_code_detector.py` (taux suisses 2024+)
- `TN_NORM` 8.1% (taux normal)
- `TN_RED` 2.6% (alimentation, livres, médicaments, presse)
- `TN_HEB` 3.8% (hébergement)
- `EXO` exonéré
- `EXP` export
- `ACQ` acquisition prestations étrangères
- Détection : montant TVA / montant HT calculé + croisement keywords. Si ambiguïté → flag review humaine.

### 3.5 — `plan_comptable_mapper.py`
- Charge depuis Bexio en priorité (pull réel du cabinet).
- Fallback : `config/plan_comptable_pme_ch.yaml` (plan PME standard CH).
- Mapping mots-clés → compte par défaut configurable.

### 3.6 — Dashboard `/entries` (UI critique)
- Layout 2 colonnes : **PDF original à gauche** (PDF.js viewer), **écriture proposée à droite**.
- Champs éditables : compte débit, compte crédit, montant, code TVA, libellé.
- 3 boutons : `Valider` / `Corriger` / `Rejeter` (avec raison).
- Validé = état SQLite uniquement, **aucun push Bexio en Sprint 0a**.
- Filtres : client, état, montant, confiance, date.

### 3.7 — `workflow_states.py` (minimal)
- États : `proposed` → `validated` ou `rejected`.
- Transitions tracées dans table `entry_state_changes` (user_id, timestamp, reason).
- (Audit trail immutable arrive en Sprint 1.)

### 3.8 — Bench obligatoire avant démo
- 50 docs anonymisés du cabinet pilote (corpus à demander d'urgence).
- Mesures **séparées** :
  - % compte correct
  - % TVA correcte
  - % les deux corrects (= proposition utilisable d'un clic)
- **Comparaison Llama 3.3 70B vs Mistral Small 3 sur les 50 docs** — garde le meilleur.
- Plancher honnête attendu : 60-70% sans cache fournisseur, 85-90% avec cache (60% du corpus typiquement). À mesurer.

### 3.9 — Multi-mandant (1 seul mandant en Sprint 0a)
- Tout le code filtré par `client_id`, mais 1 seul mandant configuré pour la démo.
- Tests multi-mandant arriveront en Sprint 1.

### 3.10 — PAS dans Sprint 0a (reporté Sprint 1+)
- IMAP automatique (le pilote dépose les docs manuellement dans `data/inbox/` pendant les 2 premières semaines).
- CAMT.053 et rapprochement bancaire.
- WhatsApp Business API.
- Push Bexio (écritures restent locales).
- Audit trail chiffré.
- Pré-bouclement, reporting mensuel.
- Calendrier échéances réglementaires.
- Multi-mandant testé sur N>1.
- Backup automatisé chiffré.

### 3.11 — Critères de DONE Sprint 0a
- [ ] Bexio PAT configuré, plan comptable + 100 écritures pulled, cache local opérationnel.
- [ ] 50 docs corpus pilote benchés, ≥75% compte correct (avec cache fournisseur), ≥80% TVA correcte.
- [ ] Bench Llama vs Mistral documenté dans `docs/bench/2026-05-llm-comparison.md`, gagnant retenu.
- [ ] Dashboard `/entries` workflow validation fonctionnel sur les 50 docs.
- [ ] Démo Loom 2 min enregistrée et envoyée avant lundi 11 mai 18h.

---

## 4. SPRINT 1 — EXTENSION (semaines 18-31 mai 2026)

À détailler après livraison Sprint 0a et retour terrain pilote Jura. Modules prévus dans l'ordre :

1. **IMAP automatique** : ingestion factures depuis boîte mail dédiée du cabinet.
2. **Push Bexio** : écritures validées poussées via API en mode dry-run d'abord, puis prod après validation cabinet.
3. **WinBIZ export CSV/XML** (fallback si API non accessible — voir script appel partenariat).
4. **CAMT.053 + rapprochement bancaire** basique.
5. **Multi-mandant testé sur 3 clients du cabinet pilote**.
6. **Audit trail immutable** (hash chaîné append-only).
7. **Chiffrement at-rest** (SQLCipher + age pour fichiers).
8. **Backup automatisé** (chiffré, rétention 30j/12m/10ans).
9. **Détection pièces manquantes** + relances draft (validation humaine obligatoire avant envoi).

---

## 5. SPRINT 2 — VERSION COMMERCIALE STABLE (juin-juillet 2026)

1. **WhatsApp Business API** (Twilio + DPA EU validé avec cabinet) — ou fallback Telegram.
2. **Calendrier échéances** réglementaires (TVA trimestrielle, AVS, déclarations cantonales par canton).
3. **Connecteurs WinBIZ / Crésus / Abacus** (export ou API selon partenariats négociés).
4. **Reporting mensuel auto** par client.
5. **Pré-bouclement** (accruals, amortissements, provisions proposés).
6. **Bilan + PP brouillon** générés automatiquement.
7. **Dashboard `/audit`** (vue audit trail complet, export contrôle fiscal).

---

## 6. STACK & CONVENTIONS

### Python
- 3.12+, type hints obligatoires (mypy strict).
- Pydantic v2.
- pytest, ≥80% coverage sur core/.
- Black + ruff.
- structlog JSON.

### LLM
- Ollama local exclusif. **AUCUN appel LLM externe.**
- Sprint 0a : bench Llama 3.3 70B vs Mistral Small 3, garder le meilleur en français.
- Function calling via JSON schema strict.
- Cache responses sur (prompt_hash, doc_hash).

### Orchestration
- **Python pur + appels Ollama directs** pour le pipeline cœur.
- **PAS de LangChain / LangGraph / Flowise / n8n** pour le cœur métier (fragilité prod).
- n8n autorisé UNIQUEMENT pour automations périphériques (notifications Slack, rappels, etc.) si besoin futur.

### Bases de données
- SQLite (Sprint 0a) → SQLCipher avec chiffrement à partir Sprint 1.
- Migrations via Alembic.
- Schemas versionnés.

### Auth Bexio
- **Sprint 0a : Personal Access Token** (généré dans interface Bexio par le cabinet).
- **Sprint 2+ multi-cabinet : OAuth2** (avec callback Vercel/Render hébergé).

### Sécurité
- Tous les secrets dans Keychain macOS, jamais dans le code ou les YAML.
- TLS obligatoire pour toute connexion sortante.
- Pas de logs avec PII non hashée.

### Multi-mandant
- TOUTE requête SQLite doit filtrer par `client_id`.
- Tests automatisés vérifient l'isolation.
- Aucun endpoint dashboard ne retourne de données sans filtre client.

### Allocation effort 70/20/10
- **70%** intégrations + UX + stabilité (le vrai différenciateur).
- **20%** qualité extraction LLM (cache fournisseur fait 80% du job).
- **10%** features avancées.

---

## 7. PRICING & POSITIONNEMENT

### Pilote cabinet Jura
- **600 CHF/mois × 3 mois** = 1 800 CHF total.
- **Acompte 50% à la signature** = 900 CHF cash à J0.
- Conditions chiffrées contractuelles :
  - (a) Testimonial vidéo 2 min à J90.
  - (b) 2 intros warm chez confrères fiduciaires (mail de présentation envoyé par le cabinet pilote).
  - (c) Call hebdomadaire 30 min de feedback structuré pendant 12 semaines.
- Après J90 : prix normal 1 500-2 500 CHF/mois avec engagement 12 mois.

### Prix cible commercial (à partir de juillet 2026)
- **Setup one-shot** : 4 000-8 000 CHF (selon volume et nombre de mandants).
- **Abonnement mensuel** : 1 500-3 000 CHF/mois (selon volume mensuel de docs).
- Acompte 50% obligatoire à la signature (règle de fer).

### Pitch commercial verrouillé
- Headline : *"L'employé IA privé pour cabinets fiduciaires suisses — 100% local, zéro donnée hors cabinet"*.
- Pain points adressés : confidentialité, LPD, fuite OpenAI/Anthropic, temps perdu en saisie, recrutement difficile.
- Argument Apporteur d'Affaires : viser les **patrons de cabinet**, pas les comptables individuels (decision-makers vs end-users).

---

## 8. INSTRUCTIONS POUR CLAUDE CODE

1. **Lis l'état actuel du repo** `tanguylachat-boop/fiduciaire`. Ne casse rien du POC.
2. **Démarre Sprint 0a uniquement.** Pas Sprint 1 ou 2 tant que Sprint 0a n'est pas livré et benché.
3. **Pour chaque module Sprint 0a** : (a) spec dans `docs/specs/<module>.md`, (b) tests d'abord (TDD), (c) implémentation, (d) PR avec checklist DOD.
4. **Aucun appel LLM externe.** Tout via Ollama local.
5. **Aucune écriture Bexio en Sprint 0a.** Lecture uniquement + cache local.
6. **Multi-mandant en first-class** dès Sprint 0a, même avec 1 seul mandant configuré.
7. **Bench Llama vs Mistral obligatoire avant démo** — résultats dans `docs/bench/`.
8. **Si tu identifies un trade-off non spécifié**, écris ta question dans `docs/decisions/<date>-<topic>.md` et propose 2-3 options chiffrées avant de coder.
9. **Reporting quotidien** dans `docs/progress/<date>.md` pendant les 3 jours du Sprint 0a : ce qui est fait, ce qui bloque, métriques.
10. **Mode dry-run par défaut** sur tout ce qui touche Bexio.

---

## 9. PRÉREQUIS À OBTENIR DU CABINET PILOTE AVANT LUNDI

Voir `docs/cabinet-onboarding-prereqs.md` pour la liste complète envoyable au cabinet.

- [ ] Personal Access Token Bexio (généré par le cabinet, transmis chiffré).
- [ ] **50 documents anonymisés** (mix factures fournisseurs + factures clients + relevés bancaires + notes de frais) pour le corpus de bench.
- [ ] Confirmation logiciel comptable principal du mandant pilote (Bexio confirmé ou WinBIZ ?).
- [ ] Plan comptable utilisé (standard PME CH ou plan custom du cabinet ?).
- [ ] Liste des banques principales du cabinet et de ses clients (pour Sprint 1 CAMT.053).
- [ ] Accord pour passage en prod si bench ≥75%/80% (Sprint 0a → Sprint 1 enchaîné).

---

## 10. POINTS LOGGÉS DANS `docs/decisions/`

- `docs/decisions/2026-05-08-sprint-0-scope.md` — Pourquoi Sprint 0a réduit
- `docs/decisions/2026-05-08-bexio-auth-pat-vs-oauth2.md` — Pourquoi PAT en Sprint 0a
- `docs/decisions/2026-05-08-no-langchain-orchestration.md` — Pourquoi Python pur
- `docs/decisions/2026-05-08-llm-bench-mistral-vs-llama.md` — Méthodologie bench
- `docs/decisions/2026-05-08-pricing-pilote-jura.md` — Justification 600 CHF×3
- `docs/decisions/2026-05-08-winbiz-fallback-csv.md` — Plan B si API WinBIZ inaccessible

---

**FIN PRD V2.** Document de vérité produit. Toute déviation documentée dans `docs/decisions/`.
