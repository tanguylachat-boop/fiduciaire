# Decision — Mistral Small 3 24B comme modèle par défaut

**Date :** 2026-05-09
**Statut :** Validée, conditionnelle au bench réel ≥75% compte / ≥80% TVA.
**Auteur :** Tanguy + Claude

## Contexte

Sprint 0a : nous avons besoin de standardiser un modèle LLM local pour l'extraction structurée d'écritures comptables suisses depuis OCR + classification. Bench prévu : Llama 3.3 70B vs Mistral Small 3 24B sur le corpus pilote (50 docs synthétiques anonymisés).

Trois contraintes simultanées :
1. **Confidentialité absolue** — modèle doit tourner 100% local sur le Mac Mini du cabinet, pas d'appel cloud.
2. **Coût hardware côté client** — chaque cabinet déploie son propre serveur. La marge dépend du tarif setup vs coût matériel.
3. **Qualité française** — comptabilité suisse, plan comptable PME, fournisseurs locaux (Swisscom, Migros, Romande Énergie, etc.).

## Décision

**Mistral Small 3 24B (Q4_K_M)** est le modèle **par défaut** pour tous les déploiements cabinet, conditionnel au seuil bench.

`config.yaml` cabinet pilote :
```yaml
llm:
  default_model: mistral-small3:24b-instruct-q4_K_M
  fallback_model: llama3.3:70b-instruct-q4_K_M  # premium, gros cabinets
```

Llama 70B reste **option premium** pour cabinets >50 mandants si bench montre écart ≥15 pts.

## Justification économique

Comparatif RAM minimum requis (modèle Q4_K_M en charge) :

| Modèle | RAM | Mac Studio M3 32 GB | Mac Studio M3 64 GB |
|---|---|---|---|
| Mistral Small 3 24B | ~16 GB | ✅ confortable | ✅ confortable |
| Llama 3.3 70B | ~42 GB | ❌ insuffisant | ✅ confortable |

| Hardware | Prix CHF | Différentiel |
|---|---|---|
| Mac Mini M4 Pro 32 GB / 512 GB | ~1 800 | base |
| Mac Studio M4 Pro 64 GB / 512 GB | ~2 600 | +800 CHF |

**Économie cumulée projetée :** 800 CHF × 30 cabinets potentiels (objectif 12 mois) = **24 000 CHF d'économies sur la flotte client** = marge brute supplémentaire pour LX Studio sur les setups.

**Argument commercial :** *"L'employé IA tourne sur du matériel ≥16 GB que vous avez peut-être déjà — pas besoin de remplacer la machine."* Lever d'objection majeur pour les cabinets qui ne veulent pas justifier un nouvel achat hardware au-dessus de 2 000 CHF.

**Cas pilote concret :** la femme de Tanguy (cabinet pilote-01) tourne sur un Mac Mini 32 GB existant. Mistral Small 3 est obligatoire de toute façon — Llama 70B ne tournerait pas.

## Justification technique

1. **Français pur** — Mistral est connu pour sur-performer Llama sur les langues européennes (benchmarks publics MMLU-fr, FQuAD). Pertinent pour libellés comptables suisses ("Fournitures bureau", "Honoraires fiduciaires", "Charges sociales AVS/AI/APG").
2. **Latence** — 24B en Q4 ≈ 3× plus rapide que 70B sur Apple Silicon (estimation Mac Studio M4). Workflow validation cabinet : 30-50 entries / jour. À 5 sec/entry vs 15 sec/entry, on passe de 12 min à 4 min de processing total → UX nettement meilleure.
3. **Ops simplicity** — un seul modèle à supporter en prod (pull, version pin, cache) = moins de surface d'incident.
4. **Output structuré** — les deux modèles supportent `format=json` Ollama de façon comparable. Pas d'écart attendu sur ce point.

## Conditions de revocation

Cette décision est **automatiquement révoquée** si le bench montre :
- Mistral Small 3 < 75% compte correct, OU
- Mistral Small 3 < 80% TVA correcte, OU
- Écart Llama 70B − Mistral 24B > 15 points absolus sur l'une des métriques

Dans ces cas, on bascule sur Llama 3.3 70B comme défaut, et on documente le surcoût hardware dans une decision doc d'override.

## Références

- Bench template : `worker/scripts/entry_bench.py` (avec `--mistral-compare`)
- Décision parente : `docs/decisions/2026-05-08-llm-bench-mistral-vs-llama.md`
- Rapport bench attendu : `docs/bench/2026-05-mistral-vs-llama.md` (Phase 4 session 2026-05-09)

## Suivi

- [ ] Bench exécuté sur RunPod ou Mac Studio prêté
- [ ] Seuils validés (≥75% / ≥80%)
- [ ] `config.yaml` cabinet pilote mis à jour avec `default_model`
- [ ] Notif client pilote du modèle retenu pour le déploiement
