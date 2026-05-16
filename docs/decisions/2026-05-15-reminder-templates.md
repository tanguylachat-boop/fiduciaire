# Decision — Templates Relances FR (Suisse)

**Date** : 2026-05-15
**Auteur** : Tanguy Lachat / Claude
**Statut** : Approuvé

## Contexte

Les emails de relance doivent respecter les usages professionnels suisses romands : ton formel mais humain, références légales suisses (AFC, pas DGFIP), formules de politesse helvétiques.

## Décision

3 templates Markdown dans `templates/reminders/` :
- `polite_fr.md` — 1ère relance, ton chaleureux, simple demande
- `firm_fr.md` — 2ème relance, rappel de la première, ton direct sans être agressif
- `escalation_fr.md` — 3ème relance, propose appel téléphonique, mentionne gel dossier sous quinzaine

Variables `{{double_braces}}` remplacées par `.replace()` simple (pas Jinja2).

## Variables disponibles

| Variable | Source |
|---|---|
| `{{contact_name}}` | `bexio_sync` contact ou `needs_contact_info=True` |
| `{{cabinet_signature}}` | Config cabinet |
| `{{document_type}}` | Type anomalie traduit |
| `{{vendor_or_client_name}}` | `subject_entity_id` |
| `{{anomaly_context}}` | LLM généré depuis `details_json` |

## Alternatives rejetées

- **Jinja2** : dépendance inutile pour 5 variables simples
- **Templates HTML** : incompatible lecture sur mobile bas de gamme, PDF client — Markdown/texte brut universel
- **Templates en allemand** : cabinet pilote Gravosig = Jura francophone uniquement pour V1
