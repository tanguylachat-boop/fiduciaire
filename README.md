# Fiduciaire AI — POC ingestion documentaire offline

POC technique LX Studio. Une boîte tourne **chez le cabinet** (Mac Mini M4 Pro 64 GB), aspire les documents reçus par mail/courrier, les classe par client/type/année et les renomme proprement. Aucune donnée ne sort du cabinet.

Ce repo couvre **uniquement la Phase 1** de Fiduciaire AI : ingestion → OCR → classification LLM locale → renommage → classement. Pas d'API logiciel comptable, pas de relances, pas de multi-tenant.

## Pourquoi cette Phase 1

Découverte clé issue des entretiens cabinets *(hypothèse à valider sur les prochains contacts commerciaux — cf [`DECISIONS.md`](./DECISIONS.md) §statut hypothèse)* :
> Le fiduciaire **ne saisit pas** dans Bexio/Winbiz. Il s'y connecte en **mode comptable** pour lire les écritures de ses clients. La douleur quotidienne ("scan + renommer + classer dans le bon dossier client") est donc **côté cabinet**, sur les documents que les clients lui envoient.

→ On résout d'abord ce nœud-là, en **local**, avec un LLM offline. Une fois le cabinet accroché, on étendra côté logiciels comptables (Phase 2/3).

ICP de travail (hyp.) : cabinet 3-15 employés, GE/VD, stack Bexio/Abacus/Crésus/WinBIZ. À reconfirmer sur les 5 premières discovery calls.

## Scope POC (1 semaine)

Pipeline qui résout **un seul problème** :

1. Le cabinet pose un PDF / image dans `data/inbox/`
2. Le worker fait l'OCR (Tesseract fr+de, fallback vision)
3. Un LLM local (Llama 3.3 70B Q4_K_M via Ollama) classe le document : `type`, `client`, `date`, `montant`
4. Le fichier est renommé selon la convention du cabinet (paramétrable `config.yaml`)
5. Il est déplacé dans `data/clients/<nomClient>/<année>/<typeDoc>/`
6. Si la confiance est sous le seuil → le doc atterrit dans `data/needs-review/` et apparaît dans le dashboard
7. Chaque opération est loggée en SQLite

Cible démo : **2 minutes de vidéo, 80%+ de précision sur 50 documents réels**.

## Stack

| Couche | Dev (MBP M4 16 GB) | Prod (Mac Mini M4 Pro 64 GB) | Pourquoi |
|---|---|---|---|
| LLM primaire | `qwen2.5:14b-instruct-q4_K_M` (~9 GB) | `llama3.3:70b-instruct-q4_K_M` (~42 GB) | Offline. Qwen 14B en dev car 70B inopérant sur 16 GB. Cf [`DECISIONS.md`](./DECISIONS.md). |
| LLM fallback latence | `qwen2.5:7b-instruct-q4_K_M` | `qwen2.5:32b-instruct-q4_K_M` | Si > 30 s/doc. |
| Pré-parser QR-bill | `pyzbar` + parser Swiss Payments Code | idem | Confidence ≈ 1.0 sur 40-60 % du corpus estimé sans appel LLM. |
| OCR | Tesseract 5 (`fra` + `deu`) | idem | Fallback `qwen2.5vl:7b-q4_K_M` si extraction Tesseract < 70 %/page. |
| Orchestration | Python 3.12 + `watchdog` | idem | Watcher filesystem + pipeline simple. |
| Storage | Filesystem local + SQLite | idem | Aucune dépendance externe. |
| Dashboard | Next.js minimal (read-only) | idem | Validation manuelle des cas incertains. Rework Mercredi à partir du scaffold racine. |

## Structure repo

```
fiduciaire/
├── README.md           ← ce fichier
├── DECISIONS.md        ← log des décisions techniques
├── config.example.yaml ← convention de nommage + chemins par cabinet
├── worker/             ← pipeline Python (POC)
│   ├── pyproject.toml
│   ├── src/fiduciaire_worker/
│   ├── prompts/
│   ├── scripts/
│   └── tests/
├── data/               ← gitignored
│   ├── inbox/          ← drop des documents à traiter
│   ├── needs-review/   ← seuil de confiance non atteint
│   ├── archive/        ← copie brute du document original
│   ├── clients/        ← arborescence finale classée
│   └── samples/        ← corpus de test (anonymisé)
├── docs/
│   ├── scope.md
│   └── pipeline.md
└── (Phase 2/3 — Next.js + Supabase + n8n existants à la racine, en standby)
```

## Roadmap commerciale (NE PAS coder)

- **Phase 1** (cette semaine) : ingestion documentaire offline ✅ POC en cours
- **Phase 2** (T+30 j) : relances automatiques basées sur calendrier comptable suisse
- **Phase 3** (T+60-90 j) : connexion **lecture** Bexio / WinBIZ → croisement docs reçus vs écritures attendues

## Critère GO/NO-GO Lundi

**Signal initial uniquement, pas validation.** Bench sur 20 docs avec Qwen 2.5 14B Q4 (modèle dev, plancher de qualité par rapport au 70B prod). Cible : précision ≥ 80 % sur le champ `type`.

→ ≥ 80 % : on continue Mardi sur le pipeline complet.
→ < 80 % : ajustement prompt, switch modèle, ou élargissement OCR (zone de texte / vision fallback).

**La vraie mesure produit = Jeudi sur 50 docs**, corpus gelé Mardi soir. Aucun chiffre Lundi ne sort de l'équipe — propal et démo client ne citent que le score Jeudi.

## Livrables semaine

| Jour | Livrable |
|---|---|
| Lundi | Repo + Ollama installé + classification 5 docs réels + mesure précision |
| Mardi | Pipeline complet end-to-end (watcher → OCR → LLM → rename → move → log SQLite) |
| Mercredi | Dashboard Next.js minimal (queue de validation, lecture seule) |
| Jeudi | Test 50 docs réels + précision finale + rapport d'erreurs |
| Vendredi | 4 livrables : (1) Loom 2 min ingest → classé, (2) script de pitch parlé 1 page, (3) proposition commerciale 1 page **3 paliers de pricing**, (4) doc convention de nommage par défaut + démo paramétrabilité (édit `config.yaml` → relance worker → nouvelle convention appliquée) |

## Contraintes

- **Tout offline en runtime.** Aucune API externe pendant un traitement.
- **POC propre, pas optimisé prod** (pas de retry exponentiel, pas de monitoring distant).
- Toute décision technique va dans [`DECISIONS.md`](./DECISIONS.md).
