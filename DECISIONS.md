# DECISIONS — Fiduciaire AI POC

Format : ADR léger. Une décision = un bloc daté, contexte court, choix, raisons, alternatives écartées.

---

## 2026-04-27 — Pivot scope Phase 1 : ingestion documentaire offline

**Contexte.** Architecture initiale (cf `1-projects/fiduciaire-ai/Architecture.md` dans Obsidian) prévoyait un SaaS multi-tenant Supabase + n8n + Anthropic API, avec triage email IMAP, extraction écritures comptables, relances factures clients, multi-cabinet. Découverte issue des discovery calls : le fiduciaire **ne saisit pas dans Bexio/WinBIZ** — il accède à ces logiciels en mode comptable pour **lire** les écritures de ses clients. La douleur "scan + renommer + classer" est **purement côté cabinet**, sur les documents reçus mail/courrier.

**Décision.** Phase 1 = pure gestion documentaire **locale** sur la machine du cabinet. Pas d'API logiciel comptable, pas de multi-tenant, pas de Supabase. Stack Python + Ollama + Tesseract + SQLite + Next.js minimal en read-only.

**Pourquoi.**
- Réduit le risque conformité / RGPD-FADP : aucune donnée client ne quitte le cabinet.
- Différenciation forte vs Counteo (pré-compta IA cloud, déjà sur le marché) : runtime offline = argument commercial unique en Suisse.
- POC livrable en 1 semaine vs 3-4 semaines pour la version SaaS.
- Permet de valider la vraie douleur N°1 (classement docs) avant d'attaquer les couches plus complexes (extraction écritures, relances).

**Conséquences.**
- L'arborescence Next.js + `supabase/` + `n8n/` existante à la racine du repo est mise en standby. Elle sera réutilisée pour Phase 2/3, **pas** pour la POC.
- Le dashboard Mercredi sera reconstruit minimal (read-only, queue de validation) — soit en repartant d'une page propre, soit en gutant l'existant pour pointer sur SQLite local au lieu de Supabase.

**Alternatives écartées.**
- *Continuer la version SaaS Supabase* : superflu pour valider la valeur, et bloque sur conformité.
- *Tout coder côté n8n* : OCR + LLM local mal supportés en n8n. Python natif est plus rapide à itérer.
- *Cloud + chiffrement zero-knowledge* : sur-engineering pour un POC, et perd l'argument "data stays local".

---

## 2026-04-27 — LLM : split dev (16 GB) / prod (64 GB)

**Contexte.** Hardware **prod** = Mac Mini M4 Pro 64 GB chez le cabinet. Hardware **dev** = MacBook Pro M4 16 GB de Tanguy. Une cible unique de modèle (Llama 3.3 70B Q4 ~42 GB) est inopérante côté dev — même Qwen 2.5 32B Q4 (~20 GB) sature un 16 GB partagé.

**Décision.** Deux modèles par défaut, sélectionnés via `config.yaml` :

| Environnement | Modèle primaire | Fallback latence | Vision fallback |
|---|---|---|---|
| dev (MBP 16 GB) | `qwen2.5:14b-instruct-q4_K_M` (~9 GB) | `qwen2.5:7b-instruct-q4_K_M` (~5 GB) | `qwen2.5vl:7b-q4_K_M` (~5 GB) |
| prod (Mac Mini 64 GB) | `llama3.3:70b-instruct-q4_K_M` (~42 GB) | `qwen2.5:32b-instruct-q4_K_M` (~20 GB) | `qwen2.5vl:7b-q4_K_M` |

**Pourquoi.**
- Qwen 2.5 14B Q4 : meilleur rapport qualité/empreinte sur extraction structurée multilingue, supporte fr/de, JSON-mode robuste. Tient à l'aise en 16 GB unifié avec OCR + Next.js dev en parallèle.
- Llama 3.3 70B Q4 reste la référence prod : qualité supérieure mais inutilisable hors machine cible.
- Conséquence pour le bench Lundi : la mesure 80 % est faite sur **Qwen 14B**, pas sur la cible prod → **plancher**, le 70B sera ≥ tant que les deux familles n'ont pas un comportement divergent sur le français bancaire/fiscal CH.

**Critères de switch.**
- Dev → 7B si Qwen 14B > 30 s/doc sur le MBP (peu probable sur extraction courte) ou si JSON cassé > 5 %.
- Prod → 32B si Llama 70B > 30 s/doc sur le Mac Mini ou précision < 80 % sur 50 docs Jeudi.

**Hypothèse à valider Lundi.** Le delta de qualité entre Qwen 14B et Llama 70B sur ce cas d'usage est < 10 pts — sinon il faut benchmarker prod en miroir avant de présenter chiffres au client.

---

## 2026-04-27 — Pipeline = Python script + watchdog (pas n8n)

**Contexte.** Stack maison LX Studio = n8n self-hosted Railway. Tentation de réutiliser. Mais Ollama en local + OCR + watcher filesystem + SQLite local sont mal couverts par n8n hosted.

**Décision.** Pipeline en Python 3.12 standalone, packagé `worker/`, exécuté en service launchd sur le Mac Mini.

**Pourquoi.**
- n8n cloud ne peut pas lire le filesystem du Mac client.
- n8n self-hosted sur le Mac client = couche d'infra inutile pour 1 cabinet.
- Python = OCR + Ollama HTTP + SQLite + watchdog couverts par stdlib + 3 deps.

**Conséquence.** Si on industrialise plus tard (multi-cabinet supervisé), on garde Python côté cabinet et on remonte les events vers un n8n central via webhook signé.

---

## 2026-04-27 — Synthèse 7 interviews : statut hypothèse, pas validation

**Contexte.** Demandé "synthèse 7 interviews fiduciaires en 5 lignes". Le vault Obsidian (`2-areas/business/discovery-calls-fiduciaires.md`, `1-projects/lx-prospection/discovery-calls-tracker.md`) contient le **template tracker** des 20 calls cible M0-M1, mais **aucune note d'entretien individuelle** (pas de `calls/cabinet-X.md`).

**Décision.** Tout point de la synthèse de cette semaine — ICP, pain ranking, prix tenable, différenciation Counteo — est **hypothèse à valider** sur les prochains contacts commerciaux. Les chiffres dans propositions doivent porter une mention "à confirmer après 5 calls" jusqu'à validation explicite.

**Hypothèses encore ouvertes (par ordre de risque) :**

1. **ICP "3-15 employés, GE/VD"** : repris du `target-list-m0.md` mais non validé sur entretiens. Possible que la sweet-spot soit 5-8 (associé unique débordé) ou 15-30 (asso. délègue à employés mais cherche outil pour eux).
2. **Pain #1 = classement documentaire** : cohérent avec la DÉCOUVERTE CLÉ donnée par Tanguy mais pas chiffré sur n cabinets. Le call Lundi-Vendredi devra demander : "combien de minutes/jour passé à renommer/déplacer des PDFs ?".
3. **Prix 8K setup + 690/mois tenable** : aucune réaction client mesurée. Réaction-test à demander dès le 2e call.
4. **Différenciation "offline" porte** : intuition logique (FADP, secret professionnel art. 47 LB), pas verbatim client.

**How to apply.**
- Marquer ces points "(hyp.)" dans toute communication interne ou externe jusqu'à validation.
- Les 5 premières discovery calls de la semaine doivent prioritairement tester **pain #1** et **réaction prix**, pas l'ICP (l'ICP s'auto-corrige si on parle aux mauvais).
- Mettre à jour cette section avec verbatim au fur et à mesure (pattern : `(validé / call N° X / verbatim)` ou `(invalidé / call N° X / pivoter)`).

---

## 2026-04-27 — Différenciation vs Counteo : sources et angle

**Contexte.** Counteo a été cité dans `marche/etat-marche-suisse-2026.md` comme "MARCHÉ DÉJÀ PRIS" sur la pré-compta IA. Vérification site web faite ce jour.

**Sources** (fetch 2026-04-27, `https://counteo.ch/`) :
- Société : Counteo SA, Route de Chêne 5, 1207 Genève, +41 22 355 02 30.
- Pitch : "All-in-One Fiduciary Platform", "by accounting experts for Swiss fiduciaries".
- Claims : "saves up to 60% time on accounting entry", "more than 100 fiduciaries" clients.
- Modules : automated accounting (réconciliation bancaire IA), document exchange platform (cabinet ↔ client), financial dashboards, task management, secure messaging, PDF automation, company creation, audit platform.
- Intégrations : Winbiz, Crésus, "Git" (probable Abacus / AbaWeb).
- Mode : SaaS cloud, pas de mention on-premise / offline.

**Décision.** Différenciation maintenue, articulée en 3 angles :

1. **Couche amont (vs aval).** Counteo automatise la **saisie comptable** (extraction écritures, réconciliation bancaire) — c'est-à-dire ce qui se passe **dans** Bexio/WinBIZ. Notre POC s'attaque à ce qui arrive **avant** : ingestion + classement des documents physiques/PDF reçus. Tant qu'un cabinet doit toujours scanner-renommer-classer, Counteo ne résout pas ça.
2. **Runtime offline (vs SaaS cloud).** Counteo est une plateforme cloud, donc les pièces transitent. Notre POC tourne intégralement chez le cabinet — argument secret professionnel art. 47 LB et art. 321 CP, RGPD/FADP simplifié, pas de DPA tiers.
3. **Paramétrable par cabinet (vs convention figée).** Convention de nommage + arborescence client définies par cabinet via `config.yaml`. Counteo impose sa structure de dossier dans son module "Document Exchange".

**Faiblesses à documenter honnêtement vs Counteo.** Counteo offre relances, dashboards financiers, messagerie sécurisée — couches que la POC ne touche pas. Pour un cabinet qui veut "tout-en-un cloud", on perd. Cible = cabinet qui refuse explicitement le cloud OU qui est déjà multi-outils et veut une brique localisée.

**Hypothèse à valider** : "le runtime offline est un facteur d'achat top-3" — à demander Lundi-Vendredi.

---

## 2026-04-27 — Pré-traitement : QR-bill suisse + vision fallback

**Contexte.** Une part importante des factures fournisseurs reçues par un cabinet en Suisse porte un Swiss QR Code (norme implementation guideline 2.3, obligatoire depuis 30.09.2022). Le QR contient déjà : IBAN créancier, nom + adresse créancier, montant, devise, débiteur, référence, message non structuré. Faire passer ces docs par OCR + LLM est une perte de signal — la vérité-terrain est dans le QR.

**Décision.** Ajouter en **étape 0** du pipeline (avant Tesseract) une détection QR-bill :

1. `pdf2image` page → `pyzbar` scan QR codes.
2. Si QR détecté ET payload commence par `SPC` (Swiss Payments Code header) → parser dédié extrait `montant`, `devise`, `créancier (= fournisseur)`, `débiteur (= client)`, `référence`. Confidence = 1.0 sur ces champs.
3. LLM appelé en complément uniquement pour `type` (qui reste à classer : facture vs note de frais vs autre) + dédup contre la base SQLite.
4. Si pas de QR → pipeline OCR + LLM standard.

**Vision fallback (Qwen2-VL 7B) :** déclenché si Tesseract retourne < 70 % de caractères extraits par page (heuristique : ratio `len(text) / (largeur * hauteur * dpi)` sous un seuil calibré). Évite de fail silencieusement sur les scans dégradés ou photos floues.

**Pourquoi.**
- Précision quasi-100 % sur ~40-60 % du corpus (estimé) sans même appeler le LLM → améliore le score global ET réduit la latence.
- Pour le client cible suisse, savoir parser le QR-bill = signal de sérieux fort (différenciation immédiate vs outils US/anglo qui n'ont pas le concept).
- Vision fallback existe en dépendance déjà identifiée (Qwen2-VL 7B Q4) → pas de coût marginal.

**Impact dépendances.** `pyzbar` ajouté à `worker/pyproject.toml`. Nécessite `brew install zbar` côté système.

**Risques connus.** `pyzbar` dépend du runtime libzbar — packaging launchd à valider en prod sur Mac Mini M4. Si problème, fallback sur `qreader` (pure Python).

---

## 2026-04-27 — Hardware dev exact + critère pratique latence

**Hardware dev confirmé (sortie `system_profiler SPHardwareDataType`) :**
- MacBook Pro, Apple M4, 10 cœurs (4 perf + 6 eff), **16 GB RAM unifiée**.
- Note Rosetta : Homebrew installé est x86_64 (`/usr/local/`), donc Tesseract, libzbar, Python 3.12 utilisés tournent sous Rosetta. Ollama lui-même est universal2 → inference LLM en arm64 natif. Le wrapper Python paie la pénalité Rosetta uniquement sur OCR/QR-bill, pas sur le LLM (la couche lourde).

**Hardware prod cible (à confirmer au déploiement chez le cabinet) :**
- Mac Mini M4 Pro, ~12-14 cœurs CPU + GPU 16-20 cœurs, **64 GB RAM unifiée**.
- À l'install client : viser Homebrew arm64 (`/opt/homebrew/`) pour éviter Rosetta.

**Conséquences chiffres bench cette semaine :**
- Tous les chiffres de précision et latence collectés Lundi-Jeudi viennent du dev MBP 16 GB tournant **Qwen 14B Q4** en arm64 natif côté inference, Rosetta côté OCR.
- Ils ne sont **pas représentatifs** de la latence prod (Llama 70B Q4 sur M4 Pro 64 GB) ni de la précision prod (modèle plus grand).
- Communication client : citer les chiffres en mentionnant explicitement "mesuré sur poste dev, attendu meilleur sur le Mac Mini livré". Les chiffres prod seront mesurés au déploiement réel ou en miroir Mac Mini si on en a un dispo.

**Critère pratique latence dev :**
- Cible : **médiane < 15 s/doc** sur le bench Lundi → "OK pour démo". Au-delà, la démo Loom 2 min ne tient plus le rythme visuel attendu.
- Calcul : 6 itérations sur le même prompt, **exclure itération 1 (cold start)**, médiane et P95 sur itérations 2-6.
- Si médiane > 15 s : switch dev fallback Qwen 7B Q4 ; documenter ici.

---

## 2026-04-27 — Tag Ollama vision : qwen2.5vl, pas qwen2-vl

**Contexte.** Tag initial planifié `qwen2-vl:7b`. Vérification registry Ollama (`https://ollama.com/library/qwen2-vl/tags` → vide / tag déprécié).

**Décision.** Vision fallback = `qwen2.5vl:7b-q4_K_M` (~6 GB). Tag confirmé sur registry, modèle plus récent et plus performant que Qwen2-VL.

---

## 2026-04-27 — Bench Lundi = signal initial, pas validation

**Contexte.** Critère GO posé : "≥ 80 % précision sur 20 docs Lundi". 20 docs, c'est 5-6 docs par catégorie principale → intervalle de confiance large. Tentation : annoncer "validé" si on tape 80 %.

**Décision.** Le bench Lundi sert à **désamorcer le risque modèle** (Qwen 14B est-il capable du tout ?) et à **calibrer les prompts**, pas à valider la solution. La validation produit = **bench Jeudi sur 50 docs**, dont la composition est gelée Mardi.

**How to apply.**
- Communication interne et externe (propal) : ne pas citer le score Lundi. Citer uniquement le score Jeudi 50-docs.
- Si Lundi < 80 % → switch modèle / prompt-engineering, pas remontée commerciale.
- Si Lundi ≥ 95 % → signal qu'on est probablement sur des docs trop faciles, élargir le corpus Mardi avant de geler les 50.

---

## 2026-04-27 — Bench latence Lundi matin : modèle dev = Qwen 7B + prompt v2 few-shot

**Contexte.** Lancement bench latence sur `worker/scripts/latency_bench.py` (cas factice facture Swisscom, prompt `classify_v1.txt`, 6 itérations exclu cold start, médiane sur 2-6). Critère démo : médiane < 15 s/doc. MBP M4 16 GB, Ollama 0.21.2, modèles déjà pullés.

**Essai 1 — Qwen 14B Q4, prompt v1, num_predict=512 (config par défaut DECISIONS du jour).**
- Médiane 24.92 s, P95 33.90 s, moyenne 26.03 s.
- JSON parsé : type ✅ client ✅ date ✅ montant ✅ — qualité parfaite sur cas Swisscom.
- **Verdict : KO latence.**

**Essai 2 — Qwen 7B Q4, prompt v1, num_predict=512 (fallback latence dev).**
- Médiane 9.19 s, P95 9.22 s, moyenne 9.13 s — très stable.
- JSON parsé : type ✅ **client `null` ❌** date ✅ montant ✅.
- Le 7B n'arrive pas à mapper "Restaurant Le Rivage SA" présent à la fois dans l'OCR ET dans `KNOWN_CLIENTS`. Probable confusion client/fournisseur (le prompt v1 explique la distinction en une phrase, insuffisant pour le 7B).
- **Verdict : OK latence, KO qualité — non utilisable tel quel.**

**Essai 3 — Qwen 14B Q4, prompt v1, num_predict=256 (Option "réduire tokens générés").**
- Médiane 23.42 s, P95 29.15 s, moyenne 23.61 s.
- Gain marginal ~1.5 s vs Essai 1 (le bottleneck n'est pas le nombre de tokens générés mais le throughput d'inférence sur 16 GB partagés).
- Qualité : type ✅ client ✅ date ✅ montant ✅.
- **Verdict : KO latence, gain insuffisant.**

**Essai 4 — Qwen 7B Q4, prompt v2 few-shot (4 exemples client matching), num_predict=512.**
- Nouveau script `worker/scripts/quality_test.py` : 3 cas distincts pour valider matching client (canonique explicite, alias court "Le Rivage", variante orthographique "Le Rivage Sàrl").
- Run cold (1er passage modèle non chargé) : swisscom 27.3 s, alias 10.3 s, sarl 14.0 s — médiane 14.0 s.
- Run warm (modèle chargé) : swisscom 13.0 s, alias 10.8 s, sarl 12.7 s — médiane 12.66 s.
- **3/3 cas matching client correct** ("Restaurant Le Rivage SA" retrouvé sur les 3, y compris depuis "Le Rivage" et "Le Rivage Sàrl").
- Type, date, montant : 3/3 corrects également.
- **Verdict : VALIDÉ. Modèle dev figé = Qwen 2.5 7B Q4 + prompt v2 few-shot.**

**Décision.**
- Modèle dev primaire : `qwen2.5:7b-instruct-q4_K_M` (PAS le 14B initialement prévu).
- Prompt par défaut : `worker/prompts/classify_v2_fewshot.txt` (PAS v1).
- Mise à jour `config.example.yaml` à venir : `llm.models.dev.primary` → `qwen2.5:7b-instruct-q4_K_M`, `llm.models.dev.fallback` → restera `qwen2.5:7b-instruct-q4_K_M` aussi (ou suppression du fallback dev — un seul modèle dev suffit).
- Conserver le 14B Q4 sur disque pour A/B test sur le bench Jeudi (50 docs) : si le 7B craque sur certains types, on a un repli prêt.

**Implications prod (Mac Mini M4 Pro 64 GB).**
- L'hypothèse "Llama 3.3 70B Q4 ≥ Qwen 14B Q4 ≥ Qwen 7B Q4" en qualité reste à valider sur 50 docs Jeudi.
- Le few-shot v2 doit être testé aussi sur le 70B prod : un prompt few-shot lourd peut paradoxalement dégrader un gros modèle qui sait déjà faire la tâche. Si delta qualité 70B v1 vs v2 < 1 pt → on garde v2 partout (cohérence dev/prod). Sinon → prompt v1 en prod, prompt v2 en dev.

**Hypothèse à vérifier sur le bench Jeudi 50 docs.**
- Le 7B + few-shot tient ≥ 80 % type sur corpus réel mixte (FR/DE, factures fournisseurs, relevés bancaires, notes de frais, documents fiscaux). Le test factice ne couvre pas l'OCR bruité, les scans dégradés, ni les documents allemands.
- Si <80 % : repasser au 14B Q4 quitte à dégrader la latence démo (compensée par pré-parsing QR-bill qui élimine ~50 % du corpus sans LLM).

**Anti-pattern évité.** Annoncer "Lundi validé" sur la base du seul cas factice. Tous les chiffres de cette section doivent porter la mention "validation factice — corpus réel Jeudi" en com client.

---

## 2026-04-27 — Structure du repo : POC à côté du scaffold Phase 2/3

**Contexte.** Le repo `~/fiduciaire/` contient déjà un scaffold Next.js + Supabase + n8n issu de l'archi initiale (commit `b833e00 init`). Question : tout déplacer dans un sous-dossier ou garder à la racine ?

**Décision.** Garder l'existant à la racine en standby, scaffolder la POC dans `worker/`, `data/`, `docs/`. README clarifie. Pas de move git pour ne pas alourdir l'historique.

**Pourquoi.** Évite un commit "rename" qui pollue le diff. La POC vit dans son arbo isolée. Si on a besoin de nettoyer plus tard, un seul `git mv` final.

---

## 2026-04-30 — Stratégie bench : Qwen 7B dev / 14B référence

**Contexte.** Bench V1 (Qwen 7B) a duré 1 h 30 sur MBP 16 GB à cause de la pression RAM (Chrome + Cowork + autres apps en parallèle). Qwen 14B (9 GB) sature systématiquement la RAM unifiée 16 GB partagée OS + IDE + Ollama.

**Décision.** Itération dev sur Qwen 7B uniquement (`primary` ET `fallback` 7B dans `config.yaml` dev). Bench final de référence (avant chaque livrable client) sur Qwen 14B, avec apps non essentielles fermées et ≥ 6 GB RAM libres confirmés.

**Conséquence.** Tous les chiffres communiqués au client doivent préciser le modèle utilisé. La propal Phi vendredi cite le score Qwen 14B + extrapolation Llama 70B prod, jamais 7B. Pas de citation hors contexte des résultats 7B en commercial.

---

## 2026-04-30 — known_clients chargés depuis le corpus

**Contexte.** `config.example.yaml` ne contenait que 2 `clients` (Le Rivage, Atelier Boillat), expliquant le score `client` à 30 % sur bench V1 — le LLM ne pouvait pas matcher les 12 autres clients du corpus 20 docs.

**Décision.** Pour le POC sur le corpus 20 docs, charger manuellement les 14 clients du corpus dans `config.yaml` (et `config.example.yaml` pour la traçabilité versionnée du POC, données synthétiques). À court terme (Phase 1.5), automatiser : chaque cabinet client fournit son fichier d'export "liste clients" → `clients` généré automatiquement.

**Conséquence.** Le score `client` mesurable monte mécaniquement avec une `clients` exhaustive. À tester sur 50 docs Jeudi avec 30+ clients distincts. Si le LLM ne tient pas le matching tolérant à grande échelle, basculer sur retrieval lexical (rapidfuzz) en post-traitement.

