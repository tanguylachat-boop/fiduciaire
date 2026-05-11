# Décision — Bench Mistral Small 3 vs Llama 3.3 70B sur corpus pilote

**Date :** 2026-05-08
**Statut :** Méthodologie figée. Bench à exécuter dès réception du corpus 50 docs Jura (deadline lundi 11 mai 12h pour démo 18h).

## Contexte

PRD V1 fixait Llama 3.3 70B Q4_K_M (~42 GB) en modèle prod, sans alternative. Tri ChatGPT pendant l'élaboration V2 a remonté Mistral Small 3 (24B paramètres, ~14 GB en Q4) comme potentiellement meilleur en français, plus rapide, et plus léger.

Le bench V2 cloud GPU runpod (commit `7428e24`, 5 mai) avait déjà testé Qwen 14B et Llama 70B sur 20 docs synthétiques. Sprint 0a doit refaire le bench sur **50 docs réels** du cabinet pilote, avec Mistral Small 3 ajouté à la comparaison.

## Décision

**Bench A/B obligatoire avant la démo Loom :**

| Modèle | Taille Q4 | RAM nécessaire | Position |
|---|---|---|---|
| `llama3.3:70b-instruct-q4_K_M` | ~42 GB | tient en 64 GB Mac Mini | référence prod actuelle |
| `mistral-small:24b-instruct-2501-q4_K_M` | ~14 GB | tient en 16 GB MBP | challenger français |

Mêmes prompts, même corpus, mesures séparées :

- % compte correct
- % TVA correcte
- % les deux corrects (proposition utilisable d'un clic)
- Latence médiane et P95 par document
- Qualité du `reasoning` produit (audit qualitatif sur 5 docs où la proposition diffère)

**Modèle gagnant retenu pour la démo lundi.** Documenté dans `docs/bench/2026-05-llm-comparison.md`.

## Critères de décision

1. **Si Mistral Small 3 est à ±2 pts de Llama 70B sur compte+TVA combinés ET 2× plus rapide** → garder Mistral Small 3 (meilleur ratio coût/perf, peut tourner sur MBP dev sans Mac Mini en local pour le développement).
2. **Si Mistral Small 3 est >5 pts en dessous** → garder Llama 70B prod, Mistral comme fallback dev.
3. **Si Mistral Small 3 est meilleur** (plausible sur français nuancé) → bascule prod sur Mistral Small 3, le 70B devient un témoin pour les cas durs.

## Méthodologie bench

Réutiliser `worker/scripts/bench.py` (déjà existant, cf bench V2 cloud GPU).

Étapes :
1. Pull les modèles sur Mac Mini cabinet (ou cloud GPU runpod si Mac Mini pas dispo le 11 mai matin) :
   ```
   ollama pull llama3.3:70b-instruct-q4_K_M
   ollama pull mistral-small:24b-instruct-2501-q4_K_M
   ```
2. Charger le corpus 50 docs anonymisés Jura dans `data/samples/jura-pilote/`.
3. Exécuter le bench pour chaque modèle avec le **même prompt** `worker/prompts/entry_proposer_v1.txt` (à créer).
4. Mesurer cold start vs warm (exclure itération 1).
5. Reporter dans `docs/bench/2026-05-llm-comparison.md`.

## Pourquoi ajouter Mistral Small 3 maintenant

- **Multilinguisme français** : Mistral est entraîné majoritairement sur du contenu français/européen. Llama est plus généraliste anglo-centré.
- **Fiscalité suisse** : nuances FR (canton, terminologie LB art. 47) où Mistral peut avoir vu plus de corpus.
- **Empreinte mémoire** : 14 GB vs 42 GB = 3× plus léger = peut tourner sur MBP dev pour itération rapide, pas seulement sur Mac Mini cabinet.
- **Coût futur multi-cabinet** : si on déploie chez 10 cabinets, un Mac Mini 32 GB suffit avec Mistral Small 3 vs 64 GB obligatoire avec Llama 70B → économie matériel ~500 CHF par site.

## Risques

- **Mistral Small 3 nouveau** (sortie début 2026, peu de retours longs sur extraction structurée multilingue). Si JSON cassé > 5%, retour Llama 70B.
- **Bench sur 50 docs reste petit** : intervalle de confiance ±5 pts. Considérer écart > 5 pts comme significatif, en dessous comme égalité.
- **Anonymisation du corpus** doit conserver les patterns (montants, IBAN structure, formats dates) sinon le bench est biaisé.

## Sortie attendue

`docs/bench/2026-05-llm-comparison.md` avec tableau récapitulatif, gagnant, justification, et `config.yaml` mis à jour si bascule prod.

## Alternatives écartées

- **Tester aussi Qwen 2.5 32B Q4** : déjà benché V2, on connaît son profil. Pas la peine de re-tester sur Sprint 0a.
- **Tester GPT-4o ou Claude via API** : viole le "100% local" non négociable. Seulement utile pour mesurer le plafond théorique, pas pour la prod.
