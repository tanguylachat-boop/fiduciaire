# 5. Exports vers votre logiciel comptable

L'employé IA exporte les écritures validées vers le logiciel
comptable que vous utilisez. Quatre formats supportés :

- **Bexio** (push direct via API)
- **Crésus** (XML générique)
- **Abacus** (XML AbaConnect)
- **Winbiz** (XML / CSV)

## Push automatique vers Bexio

Si vous utilisez Bexio, le push est **différé et automatique** :
toutes les écritures validées sont envoyées toutes les 10 minutes
en arrière-plan.

Aucune action requise de votre part.

### Vérifier les pushes récents

Ouvrez `http://localhost:3000/audit?action=bexio_pushed`

Vous voyez la liste des écritures effectivement envoyées vers Bexio,
avec horodatage et numéro de référence Bexio.

### Mode double opt-in

Au premier démarrage, le push live est **désactivé** (sécurité).
Tanguy active manuellement le flag `BEXIO_LIVE_WRITES=true` quand
vous êtes prête.

En attendant, les pushes sont en "dry-run" : ils sont loggés mais
rien n'est réellement envoyé vers Bexio.

## Export Crésus (manuel)

Si vous utilisez Crésus, exportez un fichier XML que vous importerez
ensuite manuellement dans Crésus.

Dans le Terminal :

```bash
worker/.venv/bin/python worker/scripts/cresus_export.py \\
  --client-id <votre-mandant> \\
  --output /tmp/cresus.xml \\
  --date-from 2026-04-01 --date-to 2026-04-30
```

Le fichier `.xml` est généré dans `/tmp/cresus.xml`. Vous le glissez
dans Crésus pour l'import.

Les écritures déjà exportées une fois ne sont **pas ré-exportées**
sauf si vous ajoutez l'option `--include-already-exported`.

## Export Abacus (manuel)

Même principe pour Abacus AbaConnect :

```bash
worker/.venv/bin/python worker/scripts/abacus_export.py \\
  --client-id <votre-mandant> \\
  --output /tmp/abacus.xml \\
  --date-from 2026-04-01 --date-to 2026-04-30
```

Le format XML respecte la nomenclature AbaConnect officielle.
L'admin Abacus du cabinet l'importe en quelques clics.

## Export Winbiz (manuel)

Pour le cabinet Gravosig (Winbiz), deux formats au choix :

```bash
# CSV (le plus simple à importer)
worker/.venv/bin/python worker/scripts/winbiz_export.py \\
  --client-id gravosig-fiduciaire-01 \\
  --format csv \\
  --output /tmp/winbiz.csv

# XML (plus structuré)
worker/.venv/bin/python worker/scripts/winbiz_export.py \\
  --client-id gravosig-fiduciaire-01 \\
  --format xml \\
  --output /tmp/winbiz.xml
```

## Que faire si un export échoue ?

Trois causes possibles :

1. **Aucune écriture validée** sur la période demandée. Vérifiez
   sur `/entries` qu'il y a des écritures à l'état `validated`.
2. **Mandant invalide** : vérifiez que le `--client-id` correspond
   à un mandant existant.
3. **Bug technique** : envoyez-nous le message d'erreur affiché et
   nous corrigeons.

## Audit des exports

Chaque export Abacus émet un événement dans `audit_log` avec :

- Horodatage
- Nombre de lignes exportées
- Chemin du fichier généré

Vous pouvez voir l'historique sur `/audit?action=exported`.

## Re-exporter

Si vous avez besoin de re-générer un export (par exemple pour
re-charger Crésus suite à une panne), utilisez :

```bash
... --include-already-exported
```

Cela force la ré-exportation de toutes les écritures, même celles
déjà marquées comme exportées.
