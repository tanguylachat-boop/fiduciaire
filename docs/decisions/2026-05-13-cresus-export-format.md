# Décision — Crésus export XML : format générique ajustable

**Date :** 2026-05-13
**Statut :** Actée Sprint 2. Format générique livré, à ajuster cas par cas selon retours terrain.
**Voir aussi :** `2026-05-08-winbiz-fallback-csv.md` (stratégie globale connecteurs), `2026-05-13-camt053-bank-matcher.md`.

## Contexte

Crésus (Epsitec SA) compte ~700 fiduciaires partenaires en Suisse, majoritairement en Suisse romande — cible directe pour l'install Jura/Vaud. La décision globale `2026-05-08-winbiz-fallback-csv.md` a déjà acté qu'on exporte plutôt que d'attaquer une API tierce. Restait à choisir le format Crésus précis.

## Réalité du format Crésus

- **Crésus Comptabilité Desktop** (la version majoritaire chez les anciens cabinets) accepte un import XML mais le **schéma officiel n'est pas publiquement diffusé**. Documentation officielle uniquement via canal partenaire Epsitec (signature NDA).
- **Crésus Synchro** (module cloud payant) expose un format XML structuré qui varie selon la version. Pas de schéma stable cross-versions.
- **En pratique** : la majorité des cabinets Crésus acceptent un format XML « générique » avec balises lisibles (mapping manuel à l'import), ou re-tapent depuis un CSV. Les éditeurs tiers (BMD, Topal, Sage) génèrent des XML maison pour Crésus avec le même pragmatisme.

## Décision

**Sprint 2 : on émet un XML générique aux balises explicites**, pas un format propriétaire signé.

Structure :

```xml
<EcrituresComptables cabinet_id="..." format_version="1.0" generator="fiduciaire-ai/sprint-2">
  <Ecriture>
    <Date>2026-05-13</Date>
    <Mandant>pilote-jura-01</Mandant>
    <CompteDebit>6510</CompteDebit>
    <CompteCredit>1020</CompteCredit>
    <MontantCHF>89.50</MontantCHF>
    <Description>Swisscom abonnement Internet</Description>
    <CodeTVA>TN_NORM</CodeTVA>
    <Journal>ACH</Journal>
    <ReferenceBexio>BX-12345</ReferenceBexio>
  </Ecriture>
  ...
</EcrituresComptables>
```

Position assumée : ce format est ajustable par cabinet via une éventuelle config `config/clients/<id>.yaml` (champs `cresus_export.field_mapping`), à ajouter quand un cabinet réel demande un mapping différent. Pas de spéculation Sprint 2.

## Idempotence

Colonne `accounting_entries.cresus_exported_at` (ALTER TABLE idempotent via `accounting_schema._add_column_if_missing`). Re-run ne ré-exporte pas les entries marquées. Flag `--include-already-exported` pour forcer.

## Compatibilité Sprint 3

Si un cabinet Crésus demande un format précis (schéma XSD reçu via canal partenaire), on ajoute :
- `cresus_export.py` : paramètre `output_format` enum (`generic-v1`, `cresus-synchro-v2`, ...)
- Module `cresus_format_<v>.py` dédié, mêmes contrats API.
- Switch via config cabinet.

## Risques

- **Re-saisie partielle** chez le cabinet si l'import Crésus ne reconnaît pas un champ → mitigation : les balises sont en français et lisibles, le cabinet peut ajuster son template d'import en 5 min.
- **Pas de signature numérique du fichier** → mitigation Sprint 3 si requis (rare pour Crésus mainstream).
- **Pas de doc XSD officielle** → on ne peut pas garantir 100% compat « out of the box ». C'est documenté commercialement : « 1 clic puis tu relis » (cf doc commerciale).

## Alternatives écartées

- **CSV générique uniquement** : aurait fonctionné, mais XML donne plus de structure (mandant, références) et matche mieux le workflow Crésus mainstream qui préfère XML pour les imports volumineux.
- **Attendre partenariat Epsitec officiel** : 3-6 mois de négociation. Bloquant pour install Jura début juin.
- **Format Crésus Synchro précis** : trop spécifique, casse pour cabinets Desktop sans Synchro.

## Critères de succès

- ✅ Export généré en < 1s pour 100 écritures
- ✅ Idempotence vérifiée par test
- ✅ Multi-mandant strict (test isolation cab-a vs cab-b)
- ✅ Decrypt automatique des descriptions chiffrées
- ⏳ Validation sur 1 cabinet Crésus réel (post-install Q3)
