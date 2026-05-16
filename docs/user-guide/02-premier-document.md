# 2. Déposer un premier document

## Le dossier "inbox"

Pour qu'un document soit traité par l'employé IA, il doit arriver
dans le dossier **inbox** du mandant concerné.

Le chemin est :

```
data/clients/<nom-du-mandant>/inbox/
```

Trois manières d'y déposer un document :

1. **Glisser-déposer** depuis le Finder (le plus simple)
2. **Email** : transférer le PDF de votre boîte mail vers cette
   adresse interne pré-configurée pendant l'installation
3. **Scanner directement** : si vous avez un scanner réseau, il
   sauvegarde déjà dans ce dossier

## Que se passe-t-il ?

Dès qu'un PDF arrive dans inbox, l'employé IA :

1. Calcule un hash unique du fichier (évite les doublons)
2. Lance la reconnaissance de caractères (OCR)
3. Détecte le type : facture fournisseur, note de frais, etc.
4. Identifie le fournisseur (par exemple Swisscom)
5. Détecte le montant, la TVA, la date
6. Propose une écriture comptable
7. Range le PDF original dans `data/archive/` (lecture seule)

Délai habituel : **15 à 45 secondes par document**.

## Voir le document classé

Ouvrez Safari sur :

```
http://localhost:3000/documents
```

Vous voyez la liste de tous les documents traités, du plus récent
au plus ancien. Cliquez sur l'un d'eux pour voir :

- L'aperçu du PDF original
- Les champs extraits (montant, TVA, fournisseur)
- L'écriture proposée
- Le score de confiance (de 0 à 1)

## Confiance et révision

Chaque document a deux scores :

- **Confiance compte** : à quel point l'IA est sûre du compte de
  débit choisi (par exemple 6510 Téléphonie)
- **Confiance TVA** : à quel point elle est sûre du code TVA

Si l'un des deux est sous le seuil (par défaut 0.80), le document
passe automatiquement en **review** dans la page `/review`.

Vous y validez ou corrigez avant qu'il n'aille en validation
définitive.

## Si l'IA se trompe

Pas de souci : rien n'est jamais envoyé vers Bexio ou Crésus
**sans votre validation manuelle**. L'IA propose, vous disposez.

Si vous corrigez une écriture (par exemple compte 6500 au lieu de
6510), l'employé IA mémorise votre correction. La fois suivante
pour le même fournisseur, il proposera votre compte préféré.

## Documents non traités

Si un document reste plus de 5 minutes dans inbox sans être traité,
deux causes possibles :

1. Le service est arrêté (rare). Redémarrez le Mac Mini.
2. Le PDF est protégé par un mot de passe ou très abîmé. Dans ce
   cas, il est déplacé dans `data/needs-review/` avec une note
   d'erreur.

Vous pouvez visualiser ces documents bloqués dans la page
`/review`.
