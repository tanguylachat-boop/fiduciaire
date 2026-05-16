# 4. Rapprochement bancaire (matching CAMT.053)

## Pourquoi le rapprochement bancaire ?

Quand votre banque débite une facture sur votre compte courant, il
faut faire correspondre :

- La **transaction bancaire** (ce qui apparaît sur l'extrait)
- La **facture fournisseur** (ce que vous avez reçu)

L'employé IA fait ça automatiquement à 80% du temps. Les 20%
restants, vous matchez manuellement via la page `/bank`.

## Importer un relevé CAMT.053

CAMT.053 est le format XML que toutes les banques suisses
fournissent. Vous le téléchargez depuis votre e-banking habituel.

1. Ouvrez `http://localhost:3000/bank`
2. Cliquez sur **"Choisir un fichier"**
3. Sélectionnez le fichier `.xml` téléchargé de votre banque
4. Cliquez **"Importer"**

L'import prend 5 à 30 secondes selon le nombre de transactions.

## Que se passe-t-il après import

L'employé IA :

1. Parse toutes les transactions du relevé
2. Pour chaque transaction, cherche une facture validée qui :
   - Correspond au montant **exact** (CHF)
   - Date de transaction comprise dans ± 5 jours de la facture
   - Description / fournisseur cohérents
3. Si match unique trouvé → lien créé automatiquement
4. Si match ambigu ou aucun → la transaction reste **non matchée**

## Matcher manuellement

Sur `/bank`, deux colonnes :

- **Gauche** : transactions bancaires non matchées
- **Droite** : factures validées non encore payées

Pour chaque ligne, un bouton radio. Pour matcher :

1. Cochez **1 transaction** à gauche
2. Cochez **1 facture** à droite
3. Cliquez le bouton central **"Lier ces 2 lignes"**

Un toast vert confirme le lien. La paire disparaît des listes.

## Filtres utiles

En haut de la page, vous pouvez filtrer par :

- **Mandant** (si vous en gérez plusieurs)
- **Date de transaction** (par défaut les 90 derniers jours)
- **Montant minimum / maximum**

## Statistiques en haut

Le bandeau affiche en temps réel :

- Nombre de transactions non matchées + total CHF
- Nombre de factures non payées + total CHF
- **Taux de matching automatique** (en %)

L'objectif : maintenir ce taux **au-dessus de 75%**. Si ça
descend, dites-le à Tanguy.

## Annuler un lien

Si vous avez lié par erreur :

1. Allez sur la page `/audit?entity=bank_match`
2. Trouvez l'événement de match récent
3. Cliquez **"Annuler le lien"**

Le lien est défait, les 2 lignes redeviennent disponibles.

## Sécurité multi-mandant

Les transactions du mandant A ne se mélangent jamais avec celles du
mandant B. Le bouton de match vérifie systématiquement que la
transaction et la facture appartiennent au même mandant.

Si vous tentez de matcher des éléments cross-mandant (par exemple
par erreur), l'IA refuse et affiche un message clair.
