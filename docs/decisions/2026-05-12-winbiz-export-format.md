# Décision — WinBIZ export format CSV/XML Sprint 1 §3.8

**Date :** 2026-05-12
**Sprint :** 1 §3.8 (Session 6)
**Statut :** Actée et livrée (11 tests verts). À ajuster selon retour cabinet pilote.

## Contexte

Le PRD V2 §3.8 demande "WinBIZ export CSV/XML (fallback si API non
accessible)". Le partenariat WinBIZ Store/API natif est en cours de
négociation (Raphael Perrier FIDUCIAL WINBIZ SA, réponse 24-48h).

On livre donc le **fallback fichier** qui fonctionne SANS partenariat.
Si l'API native devient disponible, on l'ajoutera en §3.8-bis Sprint 2.

## Décision

**Format CSV générique avec 8 colonnes explicites, séparateur point-virgule,
encodage UTF-8 BOM (compatible Excel + WinBIZ Import).**

### Format CSV livré

```csv
Date;Compte_Debit;Compte_Credit;Montant;Description;Code_TVA;Journal;Reference_Bexio
2026-04-15;6510;2000;100.00;Facture Swisscom;TN_NORM;ACH;
2026-04-17;6520;2000;250.50;Romande Energie;TN_NORM;ACH;42
```

Choix techniques :
- **Séparateur `;`** (standard CH/EU, évite confusion avec virgule décimale)
- **UTF-8 BOM** (Excel macOS reconnaît correctement, WinBIZ aussi)
- **Date ISO YYYY-MM-DD** (sans ambiguïté locale)
- **Montant `100.00`** (point décimal, 2 décimales fixes)
- **Journal `ACH`** (Achats fournisseurs) par défaut Sprint 1
- **Reference_Bexio** vide si pas encore pushed, sinon ID Bexio

### Format XML livré (alternative)

```xml
<?xml version="1.0" encoding="utf-8"?>
<winbiz_export cabinet_id="pilote-jura-01" format_version="1">
  <entry>
    <date>2026-04-15</date>
    <compte_debit>6510</compte_debit>
    <compte_credit>2000</compte_credit>
    <montant>100.00</montant>
    <description>Facture Swisscom</description>
    <code_tva>TN_NORM</code_tva>
    <journal>ACH</journal>
    <reference_bexio></reference_bexio>
  </entry>
</winbiz_export>
```

Pas de XSD officiel WinBIZ public Sprint 1 — format ajustable selon
retour cabinet.

### Pourquoi ce format minimaliste

1. **Pas inventer un format proprio** : WinBIZ accepte des imports
   flexibles, autant rester explicite et auto-documenté.
2. **Pas casser sur les versions WinBIZ** : tous les imports WinBIZ
   savent gérer un CSV avec headers, séparateur ;, UTF-8.
3. **Lisible humainement** : un comptable peut ouvrir le CSV dans
   Excel/Numbers et vérifier avant import → confiance accrue.
4. **Ajustable** : si le cabinet pilote demande des colonnes supplémentaires
   ou un format alternatif, on adapte sans casser l'API.

### Idempotence

Nouvelle colonne `accounting_entries.winbiz_exported_at` ajoutée via
`ALTER TABLE ADD COLUMN` idempotent.

À l'export, on filtre `WHERE winbiz_exported_at IS NULL`. Après écriture
réussie, on UPDATE `winbiz_exported_at = datetime('now')` sur les rows
exportées. Re-run = 0 nouvelles entries exportées.

Override possible : `--include-already-exported` pour ré-exporter
manuellement (cas : fichier perdu, ré-import WinBIZ après reset).

### Multi-mandant

Filtre `client_id = ?` obligatoire. Sprint 1 : `cabinet_id` argument =
`client_id` en DB (one cabinet per DB en pratique, mais le code supporte
N mandants dans la même DB pour Sprint 1+ multi-mandant).

### Decrypt description

Hook avec encryption.py : description Fernet-chiffrée en DB est déchiffrée
avant écriture dans le CSV (le cabinet veut lire un texte clair).

## Conséquences

- Le cabinet pilote peut **immédiatement** pousser ses écritures
  validées dans WinBIZ via Import CSV manuel (3 clics WinBIZ).
- Si partenariat API arrive plus tard : ajout module `winbiz_api.py`
  Sprint 2 qui réutilise la même logique de query + idempotence.
- Pas de friction commerciale : on n'a pas besoin du partenariat pour
  livrer la valeur pilote.

## Tests livrés (11 verts)

`test_winbiz_export.py` :
- CSV headers + rows corrects
- Idempotence : 2e run = 0 exported
- Date range filter (date_from / date_to)
- State filter (only validated)
- Multi-mandant isolation
- Dry-run no file no mark
- include_already_exported
- ValueError si pas d'output_path en mode normal
- XML structure correcte (root attribs + entries)
- XML multi-mandant
- XML limit

## TODO Sprint 2+

- **WinBIZ API native** (si partenariat OK) : module `winbiz_api.py`
  utilisant les endpoints WinBIZ Store.
- **Format ajustable par cabinet** : YAML `config/clients/<id>/winbiz_format.yaml`
  pour custom column mapping.
- **Crésus / Abacus exports** (autres logiciels comptables CH) avec
  les mêmes patterns.
- **Validation post-import** : webhook ou fetch WinBIZ pour confirmer
  que l'import s'est bien passé (sinon flag dans audit_log).
