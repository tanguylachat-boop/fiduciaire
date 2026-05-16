# Decision — Reminder Engine v1

**Date** : 2026-05-15
**Auteur** : Tanguy Lachat / Claude
**Statut** : Approuvé

## Contexte

Le cabinet pilote Gravosig reçoit des anomalies détectées par `missing_docs_detector.py`. Sans moteur de relance, ces anomalies restent sans suite et les pièces manquantes ne sont jamais réclamées aux clients.

## Décision

Implémenter un `reminder_engine.py` qui :
1. Lit les anomalies ouvertes (state=open) pour un cabinet/mandant donné
2. Détermine le niveau de relance (polite → firm → escalation) selon l'historique
3. Génère un brouillon via Ollama (LLM local, jamais cloud)
4. Stocke en table `reminders` (status=pending, jamais auto-envoyé)

## Règles d'escalade

| Niveau | Condition |
|---|---|
| `polite` | 0 relances précédentes envoyées |
| `firm` | 1 relance envoyée il y a ≥ 7 jours |
| `escalation` | 2+ relances envoyées, dernière il y a ≥ 7 jours |

## Contraintes

- Multi-mandant strict : chaque query filtre `cabinet_id` + `client_id`
- Idempotence : pas de nouvelle relance si une `pending` existe déjà pour cette anomalie
- `llm_caller` injectable pour les tests (mock JSON prédéfini)
- SMTP_DRY_RUN=true par défaut : jamais d'envoi automatique
- Audit `log_audit_event()` sur chaque relance créée

## Alternatives rejetées

- **SendGrid / Mailchimp** : données client sur cloud tiers — incompatible RGPD cabinet CH
- **Relance automatique sans validation humaine** : risque légal si client mal ciblé
- **Langchain / LlamaIndex** : dépendance lourde rejetée (décision 2026-05-08-no-langchain)
