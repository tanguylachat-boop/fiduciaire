# Décision — Abacus AbaConnect : XML export format

**Date :** 2026-05-15
**Statut :** Actée Sprint 2 Session 11. XML AbaConnect-inspiré livré.
**Voir aussi :** `worker/src/fiduciaire_worker/abacus_export.py`,
`2026-05-13-cresus-export-format.md` (pattern de référence),
`2026-05-08-winbiz-fallback-csv.md` (stratégie globale connecteurs).

## Contexte

Abacus est un ERP suisse leader en comptabilité (~30% des fiduciaires
> 100 employés, particulièrement dominant en Suisse alémanique mais aussi
chez les cabinets de Suisse romande qui ont migré au cloud). AbaConnect est
l'API/format d'échange officielle (XML schémas par module).

Pour le pilote Gravosig (cabinet Abacus probable), il faut un export
écritures comptables compatible import AbaConnect AccountingDocument.

## Réalité du format AbaConnect

- **AbaConnect** documente un format XML par module (AddressDocument,
  AccountingDocument, etc.). Documentation publique partielle sur
  `help.abacus.ch/abaconnect/` ; détail XSD complet via canal partenaire
  Abacus (signature NDA + abonnement).
- **AccountingDocument** (le module qui nous intéresse) accepte un fichier
  XML structuré `<Data><AccountingDocument>...</AccountingDocument></Data>`
  avec écritures double-entrée. Champs documentés publiquement :
  `DocumentDate`, `AccountNumber` (débit), `AccountNumberAgainst` (crédit),
  `Amount`, `Currency`, `Text`, `VatCode`, `OrderNumber`.
- **En pratique** les cabinets Abacus acceptent un import "manuel" depuis
  XML sans XSD officiel signé si la structure de champs matche. Le mapping
  est ajustable à l'import via les templates AbaConnect.

## Décision

**On émet un XML inspiré AbaConnect** avec les balises publiquement
documentées, à valider et raffiner après premier import réel cabinet.

Structure :

```xml
<?xml version="1.0" encoding="UTF-8"?>
<Data abacs_export_version="1.0" cabinet_id="..." generator="fiduciaire-ai/sprint-2">
  <AccountingDocument>
    <DocumentDate>2026-04-15</DocumentDate>
    <Currency>CHF</Currency>
    <AccountNumber>6510</AccountNumber>             <!-- débit -->
    <AccountNumberAgainst>2000</AccountNumberAgainst> <!-- crédit -->
    <Amount>89.50</Amount>
    <Text>Swisscom abonnement Internet</Text>
    <VatCode>TN_NORM</VatCode>
    <OrderNumber>BX-12345</OrderNumber>
    <ClientReference>pilote-jura-01</ClientReference>
  </AccountingDocument>
  ...
</Data>
```

Cf module `worker/src/fiduciaire_worker/abacus_export.py` qui suit la même
forme que `cresus_export.py`.

## Idempotence

Nouvelle colonne `accounting_entries.abacus_exported_at`, ajoutée via
`_add_column_if_missing` dans `accounting_schema.init_accounting_schema`
(idempotent). Re-run ne ré-exporte pas. Flag `--include-already-exported`
pour forcer.

## Audit log

Chaque export Abacus en mode live (`dry_run=False`, `mark_exported=True`)
émet un événement `log_audit_event` avec :
- `entity_type = "abacus_export"`
- `entity_id = "<cabinet_id>:<output_filename>"`
- `action = "exported"`
- `after = {format, client_id, rows_count, output_path}`

Le PAT/clé n'est PAS dans cet audit (aucune écriture distante côté Sprint 2,
le fichier est local).

## Risques

- **Pas de schéma XSD signé Abacus** → on ne peut pas garantir « out of the
  box ». Mitigation : les balises sont en CamelCase officiel AbaConnect,
  l'admin cabinet peut mapper en 5-10 min depuis l'interface Abacus
  AbaConnect import.
- **Pas de signature numérique du fichier** → mitigation Sprint 3 si requis.
- **Compat XSD AccountingDocument** : on passera en validation XSD si
  Gravosig fournit le fichier officiel post-install.

## Alternatives écartées

- **CSV générique** : Abacus AbaConnect accepte aussi CSV, mais XML matche
  mieux le flow standard cabinet Abacus et porte plus d'info structurée
  (ClientReference, OrderNumber pour traçabilité).
- **API REST AbaConnect** : nécessite abonnement Abacus Cloud + clés OAuth2
  cabinet. Hors scope Sprint 2 — à reprendre Sprint 3 si cabinet réel le
  demande.
- **Attendre XSD officiel** : 4-6 semaines minimum, bloquant pour pilote.

## Critères de succès

- ✅ Export généré en < 1s pour 100 écritures
- ✅ Idempotence vérifiée par test
- ✅ Multi-mandant strict (test isolation cab-a vs cab-b)
- ✅ Decrypt automatique des descriptions chiffrées
- ✅ Audit log événement créé par export live (test)
- ⏳ Validation sur 1 cabinet Abacus réel (post-install Gravosig)
