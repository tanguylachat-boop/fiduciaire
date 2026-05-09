# Décision — Scope Sprint 0a réduit

**Date :** 2026-05-08
**Auteurs :** Tanguy + agent technique (assessment PRD V1 → V2)
**Statut :** Actée. Valable jusqu'à livraison Sprint 0a (lundi 11 mai 2026).

## Contexte

PRD V1 (8 mai matin) spécifiait un **Sprint 0** livrable lundi 11 mai 2026 incluant 10 modules : ingestion email IMAP, pull/push Bexio OAuth2, accounting entry proposer 80% accuracy sur 50 docs, parser CAMT.053, workflow validation, multi-mandant testé, audit trail, dashboard 4 routes.

Estimation honnête en revue technique : **3-4 semaines** de dev solo. Disponible : **1 jour ouvré + week-end** (vendredi 8 mai → lundi 11 mai 18h).

Tenter Sprint 0 complet en 3 jours = livrer 30% testé / 70% buggué = perdre la confiance du pilote dès semaine 1.

## Décision

**Sprint 0a réduit**, livrable lundi 11 mai 2026 :

- 1 mandant uniquement
- Bexio en lecture seule (PAT, pas OAuth2)
- Pas d'IMAP automatique (drop manuel dans `data/inbox/` la première semaine)
- Pas de CAMT.053 ni rapprochement bancaire
- Pas de WhatsApp
- Pas de push Bexio (écritures restent en SQLite local)
- Démo focus : **"drag-drop facture → écriture proposée → 1 clic validate"**

## Pourquoi ce scope tient

Le pitch fonctionne sans push Bexio : la valeur visible est *"l'IA propose, tu valides au lieu de saisir"*. L'écart de valeur perçue entre "écriture proposée à l'écran" et "écriture poussée dans Bexio" est faible pour la démo Loom 2 min. Le push Bexio arrive en Sprint 1, après 2 semaines de feedback réel sur la qualité des propositions.

Le risque qualité reste : si les écritures proposées sont mauvaises, push ou pas, le pilote part. Donc Sprint 0a met tout l'effort sur la **qualité de proposition** + l'**ergonomie de validation**.

## Reporté à Sprint 1 (semaines du 18 mai au 1er juin)

- IMAP automatique
- Push Bexio (mode dry-run d'abord, prod après validation cabinet)
- Multi-mandant testé sur 3 clients du cabinet pilote
- CAMT.053 + rapprochement bancaire basique
- Audit trail immutable (hash chaîné)
- Chiffrement at-rest (SQLCipher + age)
- Backup automatisé chiffré
- Détection pièces manquantes + relances draft

## Reporté à Sprint 2 (juin-juillet 2026)

- WhatsApp Business API
- Calendrier échéances réglementaires
- Connecteurs WinBIZ / Crésus / Abacus
- Reporting mensuel + pré-bouclement
- Bilan + PP brouillon

## Critères de validation Sprint 0a

- [ ] Plan comptable + 100 dernières écritures Bexio pulled, cache local opérationnel
- [ ] 50 docs corpus pilote benchés : **≥75% compte correct** (avec cache fournisseur), **≥80% TVA correcte**
- [ ] Bench Mistral Small 3 vs Llama 3.3 70B documenté dans `docs/bench/2026-05-llm-comparison.md`
- [ ] Dashboard `/entries` avec workflow valider/corriger/rejeter sur les 50 docs
- [ ] Démo Loom 2 min envoyée avant **lundi 11 mai 18h**

## Alternatives écartées

- **Pousser pilote au 1er juin avec Sprint 0 complet** : risque commercial. Le cabinet a son propre calendrier. Repousser de 3 semaines = signal de manque de contrôle, perte d'élan.
- **Faire Sprint 0 complet et livrer 70% buggué** : tue la confiance pilote dès semaine 1. Anti-pattern bien connu (cf CLAUDE.md "UI sans backend").
- **Cancel pilote** : on n'a pas d'autre cabinet en file d'attente à M0 (cf mémoire `project_lx_prospection.md` — 40 RDV/mois cible M4-M6 pas S6).

## Hypothèse à valider pendant Sprint 0a

> Le pilote accepte que la démo lundi 11 mai porte uniquement sur "écriture proposée à l'écran + validation 1 clic", sans push Bexio. Sinon, repousser la démo de 2 semaines.

À tester : envoyer le brief Sprint 0a au pilote dès vendredi 8 mai soir. Si "non, je veux le push Bexio direct", → renégocier scope ou date.
