# Décision — Pas de LangChain / LangGraph / n8n / Flowise pour le cœur métier

**Date :** 2026-05-08
**Statut :** Actée. Règle d'architecture durable.

## Contexte

Le module `entry_proposer.py` (cœur Sprint 0a) chaîne plusieurs étapes : lookup `vendor_account_history` → si absent, prompt LLM avec plan comptable en contexte → parsing JSON strict → fallback retry si JSON invalide → écriture SQLite. Tentation : utiliser LangChain (ou LangGraph pour les états, Flowise pour le dessin visuel, n8n pour l'orchestration).

## Décision

**Tout en Python pur + appels Ollama HTTP directs.** Aucun framework d'orchestration LLM dans le code de production.

**Exception unique :** n8n autorisé pour automations **périphériques** non-critiques (notifications Slack quand le worker plante, rappels d'échéances dans Google Calendar, etc.). Jamais sur le pipeline d'extraction ou les écritures comptables.

## Pourquoi

### Fragilité en prod
LangChain change ses API à chaque version mineure. Un cabinet ne va pas tolérer "ça marchait hier, aujourd'hui le lib a bumpé et on a une régression silencieuse sur la classification TVA". Python pur + Ollama HTTP = surface d'API stable (HTTP/JSON depuis Ollama 0.x, pas de breaking changes).

### Debugging opaque
Un bug de classification dans une chain LangChain à 5 étages avec callbacks asynchrones = 1 heure de debug minimum. Le même bug en Python procédural = 5 minutes. Pour un produit qui doit tenir 10 ans (archivage légal CH), la lisibilité du code de prod prime.

### Performance
LangChain ajoute typiquement 200-500 ms de latence par call (sérialisation, callbacks, validation Pydantic redondante). Sur 200 docs/jour à 30 s chacun, ça compte. Ollama a déjà sa propre interface HTTP/JSON optimisée.

### Audit légal
Un contrôle fiscal demande à voir le code qui a généré la proposition d'écriture archivée. Code Python procédural avec un prompt explicite et une parse JSON = 30 lignes lisibles par un comptable. Code LangChain avec abstractions = "boîte noire pour qui n'est pas dev".

### Stack maison existante
LX Studio a n8n self-hosted Railway (cf CLAUDE.md global). Tentation logique : "réutiliser n8n". Mais n8n + Ollama local = n8n doit être hébergé sur le Mac Mini cabinet, ou on perd le "100% local". Hébergement n8n sur Mac Mini = couche d'infra pour 1 cabinet = sur-engineering.

## n8n autorisé où exactement

- Notifications opérationnelles (worker crash → Slack DM Tanguy)
- Rappels d'échéances réglementaires côté cabinet (TVA trimestrielle J-30)
- Sync calendrier Google ↔ deadlines.yaml
- Webhook depuis le cabinet pour signaler un bug

n8n hébergé sur Railway central (pas sur le Mac Mini). Reçoit des events anonymisés (pas de pièce comptable, pas de données client).

## Stack du cœur métier

```
worker/src/fiduciaire_worker/
├── classify.py            # déjà existant, Python pur + httpx → Ollama
├── entry_proposer.py      # NOUVEAU, même pattern
├── vendor_account_history.py
├── plan_comptable_mapper.py
└── vat_code_detector.py
```

Dépendances (cf `worker/pyproject.toml`) : `httpx`, `pydantic`, `pyyaml`, `rich`. **Zéro lib LLM-framework.**

## Conséquence pour le hiring / docs

Si on hire un dev junior dans 6 mois pour étendre Sprint 1+, lui passer un repo Python procédural classique = onboarding 2 jours. Repo LangChain custom + n8n custom = onboarding 2 semaines.

## Alternatives écartées

- **LangChain + Ollama** : fragilité API, abstractions opaques.
- **LangGraph pour state machine entry_proposer** : un dict Python + un match/case font le job en 20 lignes.
- **Flowise** : visuel, mais bloat runtime + couche d'infra Node.js.
- **n8n self-hosted sur le Mac Mini cabinet** : couche d'infra pour 1 cabinet, casse le "rien à administrer pour le cabinet".
