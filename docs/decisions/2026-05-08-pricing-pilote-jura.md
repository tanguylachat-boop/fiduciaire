# Décision — Pricing pilote Jura : 600 CHF/mois × 3 mois + contreparties chiffrées

**Date :** 2026-05-08
**Statut :** Actée. Conditions à transcrire dans contrat pilote signé avant J0.

## Contexte

Règle de fer LX Studio (cf `~/.claude/CLAUDE.md` §4) : **8 000 CHF setup minimum + 690 CHF/mois.** Personne sauf Tanguy ne fixe les prix. Tanguy valide tous les devis.

Le pilote cabinet du Jura est le premier client de l'employé IA fiduciaire. À ce stade, le risque produit est ouvert (qualité accuracy LLM, ergonomie validation, intégration Bexio). Demander 8K CHF setup à un pilote = 0% de chance de signer.

## Décision

**Pricing pilote** :
- 600 CHF/mois × 3 mois = **1 800 CHF cash**
- **Acompte 50% à la signature** = 900 CHF à J0 (règle de fer maintenue)
- Conditions chiffrées contractuelles obligatoires :
  - **(a)** Testimonial vidéo 2 min à J90 (utilisable en marketing)
  - **(b)** 2 intros warm chez confrères fiduciaires (mail de présentation envoyé par le cabinet pilote)
  - **(c)** Call hebdomadaire 30 min de feedback structuré pendant 12 semaines

**Sortie pilote (à partir de J90)** : prix normal 1 500-2 500 CHF/mois avec engagement 12 mois. Setup déjà payé par les 1 800 CHF pilote.

## Justification du discount vs règle 8K

Valeur effective totale captée par LX Studio :

| Élément | Valeur estimée |
|---|---|
| Cash | 1 800 CHF |
| 2 warm intros (1 deal converti = 8K min setup, p(conversion) ≈ 50% sur warm intro fiduciaire) | ~8 000 CHF |
| Testimonial vidéo (réutilisable 12 mois minimum, équivalent ad spend) | ~5 000 CHF |
| 12 calls feedback (insights produit valorisables, R&D) | ~3 000 CHF |
| **Total équivalent** | **~17 800 CHF** |

→ Au total bien au-dessus du seuil 8K CHF setup. La règle est **respectée en valeur**, pas en cash.

À documenter dans le contrat pilote : les 3 contreparties (a/b/c) sont **contractuelles**, pas discrétionnaires. Si le cabinet ne les livre pas → clause de sortie / facturation complémentaire.

## Risques

- **Le cabinet ne livre pas les warm intros.** Mitigation : clause contractuelle "à défaut de 2 intros à J90, facturation complémentaire 4 000 CHF" + relance hebdomadaire dans le call.
- **Testimonial maladroit / inexploitable.** Mitigation : Tanguy script + tournage assisté à J85.
- **Le pilote tire le prix à terme.** Mitigation : prix normal 1500-2500/mois communiqué dès le pitch, le 600 est explicitement "tarif pilote -50% pendant 3 mois".

## Conséquence pour le pipe commercial

À partir du 2e cabinet (juin 2026 cible) : retour au pricing standard 8K setup + 690-2500/mois selon volume. Le pilote Jura n'est PAS le tarif de référence.

Mention en propal future : *"Le cabinet du Jura a payé un tarif pilote -50% en échange de feedback produit et d'intros. Aujourd'hui le tarif standard s'applique."*

## Alternatives écartées

- **Pilote gratuit contre testimonial seul** : viole la règle "acompte 50% obligatoire à la signature". Sans skin in the game cash, le cabinet décroche au premier inconvénient.
- **Pilote 8K setup + 690/mois standard** : 0% de chance de signer un cabinet à cold sur un produit non prouvé.
- **Pilote 3K setup + 0/mois** : casse le récurrent, mauvais signal pour la suite.

## Loggué dans `~/decisions.md` (journal Dalio)

À reporter dans `~/decisions.md` au format standard du journal Tanguy :

```
## 2026-05-08 — Pricing pilote employé IA fiduciaire (Jura)
**Décision** : 600 CHF/mois × 3, acompte 50% J0, contreparties chiffrées (testimonial + 2 warm intros + 12 calls feedback).
**Pourquoi** : valeur effective ~17.8K CHF respecte la règle 8K min en valeur cumulée cash + équivalents.
**Règle dérivée** : pour les 5 premiers pilotes d'un nouveau produit, discount cash autorisé jusqu'à -75% si la valeur des contreparties (intros, testimonial, IP feedback) couvre le seuil 8K.
```
