# 1. Installation et premier démarrage

## Le Mac Mini

Votre Mac Mini M4 Pro est livré pré-configuré. Il contient :

- macOS à jour
- L'employé IA installé et prêt à l'emploi
- Vos clés d'accès Bexio stockées dans le Trousseau (Keychain)
  macOS, chiffrées

Branchez le Mac Mini :

1. Câble d'alimentation
2. Câble réseau (Ethernet) vers votre box internet
3. Câble écran HDMI ou DisplayPort
4. Clavier et souris USB

Allumez. Le Mac Mini démarre en quelques secondes.

## Le mot de passe utilisateur

Au premier démarrage, vous serez invitée à choisir un mot de passe.
Conseil : utilisez un mot de passe différent de celui de votre boîte
email. Notez-le dans un endroit sûr (carnet papier ou Bitwarden).

## Vérification que tout fonctionne

Sur le bureau, ouvrez l'application **Safari**.

Tapez dans la barre d'adresse :

```
http://localhost:3000
```

Vous devez voir la page d'accueil de l'employé IA. Si une erreur
apparaît, attendez 30 secondes (le service démarre en arrière-plan)
puis rafraîchissez la page.

## Le service tourne 24h/24

L'employé IA est conçu pour tourner en permanence. Vous pouvez fermer
la fenêtre Safari sans rien éteindre — le service continue de
classer les documents en arrière-plan.

Si vous devez redémarrer le Mac Mini :

1. Menu Pomme → Redémarrer
2. Attendez le bip de démarrage
3. Réouvrez Safari sur `http://localhost:3000`

Tout reprend automatiquement.

## En cas de panne réseau

L'employé IA fonctionne **100% en local**. Une coupure internet
n'empêche **rien** sauf :

- L'envoi vers Bexio (push automatique en différé jusqu'à
  rétablissement de la connexion)
- L'import de vos relevés CAMT.053 récents si vous les
  téléchargez depuis votre banque

Vous pouvez continuer à déposer des PDF, l'IA les classera et
proposera les écritures normalement.

## Sauvegardes

Une sauvegarde automatique de toute la base de données est créée
chaque soir à 23h dans `data/backups/`. Les 30 dernières sauvegardes
quotidiennes, 12 hebdomadaires et 10 mensuelles sont conservées.

Aucune action requise de votre part.
