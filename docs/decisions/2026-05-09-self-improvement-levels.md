# Decision — Niveaux d'auto-amélioration de l'agent

**Date :** 2026-05-09
**Statut :** Cadre validé. Niveau 1 livré (Sprint 0a), 2 prévu Sprint 1, 3 prévu Sprint 2.
**Auteur :** Tanguy + Claude

## Contexte

Pendant la phase de positionnement commercial, plusieurs interlocuteurs (cabinet pilote inclus) ont demandé : *"Et l'IA, est-ce qu'elle apprend de mes corrections ?"*. La question est légitime — un assistant qui ne s'améliore pas est rapidement perçu comme un gadget. Mais il faut être honnête sur les niveaux : aucun fine-tuning sauvage de modèle, pas de promesse vague de "machine learning".

Ce document fixe les **4 niveaux d'auto-amélioration**, classés par scope, par sprint d'arrivée, et par dépendance à la qualité du feedback humain.

## Niveau 1 — Mémoire fournisseur (Sprint 0a — LIVRÉ)

**Module :** `worker/src/fiduciaire_worker/vendor_account_history.py`

**Mécanisme :**
- Au pull initial Bexio, on construit pour chaque fournisseur récurrent une recommandation `(compte, code TVA)` pondérée par les occurrences passées dans la compta.
- Au runtime, si un nouveau document mentionne un fournisseur déjà vu avec ≥5 occurrences sur le même compte, l'écriture est proposée **directement** sans appel LLM (gain : -3 à -10 sec / doc + accuracy ~95% sur ces cas).
- Quand l'humain valide une écriture, on ré-incrémente le compteur (mémoire renforcée).

**Couverture estimée :** 60-70% du volume mensuel d'un cabinet (les 20-30 fournisseurs récurrents génèrent la majorité des écritures).

**Pas d'IA dans le sens "modèle qui apprend"** — c'est une heuristique fréquentielle, mais l'effet utilisateur est exactement le même : *"l'IA reconnaît mon Swisscom et propose le bon compte au premier clic"*.

## Niveau 2 — Apprentissage des corrections (Sprint 1)

**Module à créer :** `worker/src/fiduciaire_worker/correction_learner.py`

**Mécanisme prévu :**
- Chaque transition `proposed → validated` avec corrections (table `entry_state_changes` avec `reason='corrected: ...'`) est traitée comme un signal d'apprentissage.
- Pondération **temporelle** : occurrences récentes pèsent plus lourd que anciennes (decay exponentiel sur 90 jours).
- Quand l'humain corrige systématiquement le compte 6510 en 6500 pour Swisscom (cas réel : changement de plan comptable), le prochain document Swisscom proposera 6500 directement sans demander l'historique Bexio brut.
- Pondération aussi par **utilisateur** : si un comptable senior corrige, son signal pèse plus qu'un junior (à configurer cabinet par cabinet).

**Pré-requis :** Sprint 1 audit trail immutable (sinon les corrections peuvent être réécrites).

## Niveau 3 — Process custom entreprise (Sprint 2)

**Module à créer :** `worker/src/fiduciaire_worker/business_rules.py` + `config/cabinets/<slug>/rules.yaml`

**Mécanisme prévu :**
- Chaque cabinet peut écrire ses règles métier en YAML (via dashboard ou édition directe).
- Exemples concrets :
  ```yaml
  rules:
    - name: "Toutes les factures Swisscom > 500 CHF passent en immobilisation"
      when:
        vendor: "Swisscom"
        amount_chf: ">500"
      then:
        suggested_account: "1500"
        confidence_boost: 0.1
        confirmation_required: true

    - name: "Les frais de représentation > 200 CHF demandent justificatif fiscal"
      when:
        debit_account: "6500"
        amount_chf: ">200"
      then:
        flag_for_review: "justificatif_fiscal"
        attach_template_email: "demande_justificatif.txt"
  ```
- Validation conditionnelle : le bouton "Valider" peut exiger une confirmation supplémentaire si une règle se déclenche (par ex. justificatif manquant).

**Pas un LLM** — c'est un moteur de règles basé YAML, prédictible et auditable. C'est ça qui plaît aux comptables : *"je vois exactement pourquoi l'IA m'a proposé ça"*.

## Niveau 4 — Fine-tuning modèle (HORS SCOPE)

**Décision : on ne fait pas.**

Raisons :
1. **Volume insuffisant** — un cabinet typique génère 5-10K écritures/an. C'est très en-dessous du seuil pour fine-tuner un modèle 24B avec un gain mesurable (>100K samples nécessaires).
2. **Risque drift** — fine-tuner sur des données d'un seul cabinet ferait apprendre à l'IA les biais de ce cabinet (ex. choix de compte 6510 vs 6500 spécifique). Mauvais pour le multi-tenant.
3. **Maintenance opérationnelle** — chaque update modèle (Mistral 3 → Mistral 4) demanderait de re-fine-tuner. Fragile.
4. **Pas nécessaire pour le use case** — la qualité Mistral Small 3 hors-fine-tuning + niveaux 1+2+3 atteint largement les seuils accuracy attendus (objectif 90%+ all-in).

À reconsidérer **uniquement** si nous atteignons 30+ cabinets payants ET que les niveaux 1-3 plafonnent à <88% accuracy, ce qui est très peu probable.

## Disclaimer critique

**Les 4 niveaux dépendent à 100% de la qualité du feedback humain.**

Si le comptable clique "Valider" sans regarder, l'agent apprend des erreurs. Si le cabinet utilise des conventions de comptes incohérentes (compte 6510 un mois, 6500 le suivant pour le même type de charge), l'agent va alterner ses propositions.

**Conséquence pratique :** lors du déploiement cabinet, 2 obligations contractuelles :
1. Brief 30 min avec le comptable senior sur "comment l'agent apprend" (cf section dédiée dans `docs/user-guide.md`).
2. Audit hebdomadaire des 10 dernières corrections pendant les 4 premières semaines (Tanguy + senior cabinet).

Sans cette discipline, l'auto-amélioration devient un cargo-cult inutile.

## Suivi

- [x] Niveau 1 implémenté (Sprint 0a)
- [ ] Niveau 2 cadré (specs Sprint 1)
- [ ] Niveau 3 cadré (specs Sprint 2)
- [x] Disclaimer ajouté à `docs/user-guide.md`
- [ ] Brief utilisateur scripté pour le déploiement pilote
