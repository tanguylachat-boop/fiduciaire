# 8. FAQ et résolution des problèmes courants

## Questions fréquentes

### 1. L'IA m'a-t-elle envoyé une donnée à OpenAI ou Anthropic ?

**Non.** L'employé IA tourne 100% en local sur votre Mac Mini.
Aucune donnée métier ne sort de la machine, jamais.

Les seules connexions sortantes sont :

- Bexio API (lecture + push uniquement après votre validation)
- Votre serveur IMAP (lecture emails)
- Votre banque (pour télécharger les CAMT.053 si vous l'activez)

Tout le reste, y compris l'IA de classification, tourne en local.

### 2. Combien de temps pour traiter 1 document ?

15 à 45 secondes selon la taille du PDF et la complexité.

Si vous trouvez ça lent : déposez plusieurs PDF d'un coup, l'employé
IA les traite en parallèle.

### 3. Combien de documents peut-il traiter par jour ?

Sur Mac Mini M4 Pro 64 GB : jusqu'à **2000 documents par jour**.
Bien au-delà du volume d'un cabinet PME standard.

### 4. Et si je dépose un PDF par erreur ?

Pas de souci. Vous pouvez :

- Le **rejeter** dans `/entries` (l'écriture proposée disparaît)
- Le **supprimer du dossier inbox** avant traitement (si dans les
  premières secondes)

Le PDF original reste dans `data/archive/` (chiffré SHA-256) pour
votre traçabilité.

### 5. Comment changer un compte par défaut ?

Le plan comptable est dans la table `chart_of_accounts`. Pour
ajouter un compte personnalisé :

```bash
worker/.venv/bin/python -c "
from fiduciaire_worker import db
from pathlib import Path
conn = db.connect(Path('data/fiduciaire.sqlite'))
conn.execute(\"\"\"
  INSERT INTO chart_of_accounts (client_id, account_no, name,
    account_type, source) VALUES (?, ?, ?, ?, 'manual')
\"\"\", ('<votre-mandant>', '6520', 'Mon compte custom', 'expense'))
conn.commit()
"
```

### 6. Comment ajouter un nouveau mandant ?

```bash
worker/.venv/bin/python worker/scripts/provision_cabinet.py --force \\
  --cabinet-id <cabinet-id> \\
  --cabinet-name "<Cabinet>" \\
  --ville X --canton GE --lang fr --logiciel bexio \\
  --mandants "<existant1>,<existant2>,<nouveau>"
```

### 7. Comment révoquer un PAT Bexio si volé ?

1. Allez sur https://office.bexio.com → Profil → Réglages → API
2. Trouvez le token de l'employé IA
3. Cliquez **"Supprimer"**

Le push Bexio s'arrête immédiatement. Vous générez un nouveau PAT
puis Tanguy le ré-installe dans le Keychain.

### 8. Que se passe-t-il si Internet coupe ?

L'IA continue de tourner normalement. Seules les actions vers
Bexio et l'import banque sont mises en file d'attente, et reprennent
automatiquement quand Internet revient.

### 9. Combien d'espace disque consomme l'IA ?

- Application + modèles IA : ~80 GB
- 1 an de PDFs archivés (cabinet ~500 docs/mois) : ~10 GB
- Base de données : ~500 MB

Le Mac Mini livré a 1 TB SSD, vous êtes large.

### 10. Comment sauvegarder mes données ailleurs ?

Une sauvegarde automatique tourne chaque nuit dans
`data/backups/`. Pour copier ailleurs (disque externe, NAS,
cloud chiffré), demandez à Tanguy de configurer Time Machine ou
rsync.

## Problèmes courants

### "La page localhost:3000 est inaccessible"

1. Attendez 30 secondes (service démarre)
2. Si toujours rouge : Menu Pomme → Forcer à quitter Safari, puis
   ré-ouvrez
3. Si persiste : redémarrez le Mac Mini

### "Un PDF reste bloqué dans inbox"

1. Vérifiez sa taille (limite 50 MB par PDF)
2. Essayez de l'ouvrir manuellement dans Aperçu macOS
3. Si corrompu : déposez une version re-scannée

### "L'IA propose toujours le mauvais compte pour Swisscom"

1. Allez sur `/entries`, ouvrez une écriture Swisscom
2. Corrigez le compte (par exemple `6500` au lieu de `6510`)
3. Cliquez **"Valider"**

La fois suivante, l'IA proposera votre choix.

Si l'erreur persiste après 3-4 corrections : appelez Tanguy, il
ré-entraîne l'historique.

### "Le push Bexio renvoie une erreur 401"

C'est que le PAT a été révoqué ou a expiré (peu probable, pas de
date d'expiration par défaut chez Bexio).

Vérifiez sur Bexio que le token existe encore. Sinon, génerez-en un
nouveau et donnez-le à Tanguy.

### "Un export Crésus renvoie 0 écritures"

Causes possibles :

- Aucune écriture **validated** sur la période demandée
- Toutes les écritures ont déjà été exportées (utilisez
  `--include-already-exported` pour forcer)
- Mauvais `--client-id`

### "Le rapport mensuel PDF ne se génère pas"

1. Vérifiez que WeasyPrint est installé :

```bash
worker/.venv/bin/pip list | grep weasyprint
```

2. Si absent : `worker/.venv/bin/pip install weasyprint`

### "Chain audit cassée"

Très rare. **Appelez Tanguy immédiatement**, en attendant ne
faites plus aucune validation. La chaîne se restaure depuis le
backup quotidien.

## Mon numéro d'urgence

Tanguy Lachat — contact@lxstudio.ch — disponible pour vous
dépanner.

Pour les questions non urgentes, envoyez un email avec :

- La date/heure du problème
- Une copie d'écran si possible
- Ce que vous étiez en train de faire

Réponse sous 4h jours ouvrés.
