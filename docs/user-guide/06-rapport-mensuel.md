# 6. Générer un rapport mensuel

## À quoi sert le rapport mensuel ?

Un rapport PDF imprimable que vous envoyez à votre client mandant
PME une fois par mois. Il contient :

- **CA HT du mois** (chiffre d'affaires hors taxe)
- **Cumul YTD** (cumul depuis le 1er janvier)
- **Position TVA estimée** (collectée – déductible)
- **Trésorerie estimée** (banque + créances – dettes fournisseurs)
- **Top 5 fournisseurs** du mois
- **Annexe** : les 50 dernières écritures validées

Format A4 portrait, sobre, imprimable directement.

## Générer le rapport

Ouvrez le Terminal. Tapez :

```bash
worker/.venv/bin/python worker/scripts/generate_monthly_report.py \\
  --cabinet-id <votre-mandant> \\
  --client-id <votre-mandant> \\
  --year 2026 --month 4 \\
  --output-dir reports/ \\
  --cabinet-label "Votre Cabinet SA"
```

Deux fichiers sont créés :

- `reports/<mandant>_2026-04_report.md` (Markdown, éditable si
  besoin)
- `reports/<mandant>_2026-04_report.pdf` (PDF imprimable)

## Le format `--format`

Par défaut, les deux formats sont générés. Vous pouvez choisir :

| Option | Effet |
|---|---|
| `--format both` | MD + PDF (défaut) |
| `--format md` | Markdown seul (pas besoin de WeasyPrint) |
| `--format pdf` | PDF seul, MD intermédiaire effacé |

## Personnaliser le rapport

Deux options décoratives :

- `--cabinet-label "Mon Cabinet SA"` : affiché en haut du PDF
- `--logo /chemin/vers/logo.png` : logo dans le header (optionnel)

Si vous n'avez pas de logo, laissez vide — le PDF reste propre.

## Imprimer le rapport

1. Ouvrez le fichier `.pdf` (double-clic dans Finder)
2. Aperçu macOS s'ouvre
3. Menu **Fichier → Imprimer** (ou Cmd+P)
4. Choisissez votre imprimante. Cocher recto-verso recommandé.

## Envoyer par email

1. Cliquez-droit sur le PDF dans Finder
2. **Partager → Mail**
3. Saisissez l'adresse du client mandant
4. Le rapport part en pièce jointe

## Tous les mois ?

Vous pouvez planifier le rapport en début de mois. Par exemple le
1er mai, vous générez le rapport d'avril :

```bash
worker/.venv/bin/python worker/scripts/generate_monthly_report.py \\
  --cabinet-id <mandant> --client-id <mandant> \\
  --year 2026 --month 4 --output-dir reports/
```

(Le `--month 4` = avril, le mois qui vient de se terminer.)

## Précisions techniques

- **CA HT** = somme des écritures où le compte de crédit commence
  par `3` (produits)
- **TVA collectée** = somme `vat_amount` pour les ventes au taux
  normal/réduit/hébergement
- **TVA déductible** = somme `vat_amount` pour les achats
- **Trésorerie** = approximation simple : solde banque (1020) +
  créances clients (1100) – dettes fournisseurs (2000)

Ces chiffres sont des **estimations** : ils ne remplacent pas le
bouclement comptable formel. Mais ils donnent une vue très fiable
de la santé financière du mandant.

## Si le rapport est vide

Si vous voyez "Aucune écriture sur cette période" : c'est qu'il
n'y a aucune écriture **validée** sur ce mois. Allez d'abord
valider via `/entries`, puis re-générez le rapport.
