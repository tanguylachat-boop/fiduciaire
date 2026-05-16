# 3. Valider les écritures comptables

## La page `/entries`

C'est la page que vous utiliserez le plus. Tapez dans Safari :

```
http://localhost:3000/entries
```

Vous voyez la liste des écritures proposées par l'IA, triées par
date. Pour chaque écriture :

- Date
- Compte débit / compte crédit
- Montant CHF
- Code TVA
- Description (ce que vous verrez sur Bexio après push)
- État : `proposed` / `validated` / `rejected`

## Filtrer par mandant

En haut de la page, un sélecteur **Mandant** vous permet de voir
les écritures d'un mandant en particulier. Si vous gérez 3 PME,
choisissez celle qui vous intéresse.

## Valider une écriture

Cliquez sur la ligne. Une fenêtre s'ouvre avec :

- L'aperçu du PDF source
- Les champs détectés (modifiables)
- Le raisonnement de l'IA (en clair, lisible)

Si tout est juste, cliquez sur **"Valider"**. L'écriture passe en
état `validated`. Elle sera incluse dans le prochain export
Bexio / Crésus / Abacus / Winbiz.

## Corriger une écriture

Si l'IA s'est trompée :

1. Cliquez sur le champ à corriger (compte, TVA, montant,
   description)
2. Saisissez la bonne valeur
3. Cliquez **"Valider"**

La correction est mémorisée. La fois suivante, pour le même
fournisseur, l'IA propose votre choix.

## Rejeter une écriture

Une écriture rejetée n'est jamais envoyée vers le logiciel
comptable. Utile pour :

- Doublons (par exemple si vous avez déposé la même facture deux
  fois)
- Documents hors comptabilité (CV, contrat, papier publicitaire)
- Erreurs de classification incorrigibles

Cliquez **"Rejeter"** puis confirmez. L'écriture passe en
`rejected` mais reste visible (vous pouvez la rouvrir si besoin).

## Statuts possibles

| Statut | Signification |
|---|---|
| `proposed` | L'IA a proposé, pas encore vue par vous |
| `validated` | Validée, en attente d'export |
| `rejected` | Refusée, jamais exportée |
| `bexio_pushed` | Déjà envoyée vers Bexio |

## Combien faut-il valider ?

Notre objectif : 70% des écritures validées en moins de 5 secondes
chacune (un coup d'œil + clic). Si vous mettez plus de temps, dites-le
à Tanguy, c'est le signe que l'IA propose mal et qu'il faut affiner
le bench.

## Astuce raccourcis

Quand une fenêtre d'écriture est ouverte :

- **V** = valider
- **R** = rejeter
- **N** = écriture suivante
- **P** = écriture précédente
