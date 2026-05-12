# Décision — Backup automatisé chiffré Sprint 1 §3.5

**Date :** 2026-05-12
**Sprint :** 1 §3.5 (Session 5)
**Statut :** Actée et livrée (12 tests verts).

## Contexte

PRD V2 §3.5 + exigences légales CH (10 ans rétention factures, AVS,
TVA). Le cabinet pilote Jura veut un backup qui :
- Quotidien automatique sans intervention humaine
- Chiffré (LPD : pas d'exfiltration possible si backup volé)
- Restorable testé (mensuel : vérifier que les backups ne sont pas corrompus)
- Rétention longue durée (10 ans)

## Décisions

### 1. Format : tar.gz + Fernet, 1 fichier par run

**`backup-YYYY-MM-DD-HHMMSS.tar.gz.fid` chiffré en bloc.**

Contenu tar :
- `db.sql` : dump SQL via `sqlite3.iterdump` (texte, déterministe, restorable)
- `archive/<cabinet>/...` : fichiers PDFs déjà chiffrés individuellement
  par `encryption.py` (double chiffrement = defense in depth)

Pourquoi pas `.sqlite` binaire : le dump SQL est plus robuste (corruption
locale d'un page SQLite n'invalide pas tout le dump). Restorable via
`executescript` simple.

### 2. Clé backup distincte (`backup-master`)

**Décision : clé Fernet 256-bit dans Keychain avec user `backup-master-key`.**

Distincte des clés archive cabinet (`encryption-key-<cabinet>`). Permet :
- Rotation séparée (rotation backup ≠ rotation archive)
- Backup utilisable par un opérateur DR sans accès aux clés cabinet
  individuelles
- Defense in depth : pour exfiltrer un PDF cabinet depuis un backup
  volé, il faut casser 2 clés (backup-master + cabinet)

### 3. Rétention 30 quotidiens + 12 mensuels + 10 ans annuels

**Décision : `apply_retention(daily_keep=30, monthly_keep=12, yearly_keep=10)`.**

Algorithme :
1. Liste tous les backups, parse timestamp depuis le nom.
2. Daily : conserve les 30 plus récents.
3. Monthly : 1 par mois (le plus ancien backup du mois), sur les 12
   derniers mois.
4. Yearly : 1 par année (le plus ancien), sur les 10 dernières années.
5. Le reste supprimé.

Le 1er backup de chaque mois est typiquement aussi le 1er jour, donc
"plus ancien du mois" = backup du 1er.

Conformité légale CH : 10 ans annuels couvrent l'exigence factures +
TVA. Pour AVS (5 ans), 12 mensuels suffisent.

### 4. Backup global multi-mandant (pas par cabinet)

**Décision : 1 backup contient TOUTES les données de tous les cabinets.**

Pourquoi : simplicité opérationnelle. La DB SQLite est commune (avec
filtrage `client_id`). Le dossier archive contient des sous-dossiers
par cabinet, déjà chiffrés individuellement.

Conséquence : pour restore SÉLECTIF d'un seul cabinet, on doit unpack
le backup global puis extraire le sous-dossier. Acceptable, scénario
rare.

Sprint 2 : si on déploie chez plusieurs cabinets sur le MÊME Mac Mini
(unlikely — chaque cabinet a son install), on pourrait segmenter les
backups par cabinet. Pas nécessaire pour Sprint 1.

### 5. verify_backup_restorable mensuel

**Décision : `verify_backup_restorable(path, tmp_dir)` exécutable par
launchd mensuel, valide que le backup est déchiffrable + DB exécute
des queries de smoke.**

Pourquoi : un backup non testé = pas un backup. Mensuellement, on
restaure dans un dossier temp et on confirme l'intégrité.

Sprint 1 livre la fonction. Activation launchd à la main par Tanguy
(opt-in : ajouter une entrée dans `deploy/install-backup-launchd.sh`).

### 6. Mode dev disabled

**`FIDUCIAIRE_ENCRYPTION_DISABLED=true` désactive le chiffrement backup.**

Réutilise le flag global de `encryption.py`. Tests rapides sans Keychain.

## Tests livrés (12 verts)

`test_backup.py` :
- create_backup writes encrypted file (header FID1)
- restore_backup recreates db + archive intacts
- restore with wrong key → EncryptionError
- verify_backup_restorable OK / detects corruption
- retention keeps 30 daily / 12 monthly / 10 yearly
- retention dry_run does not delete
- retention ignores non-backup files
- multi-mandant : tous cabinets dans le même backup, restore OK

## Scripts livrés

- `worker/scripts/backup_now.py` : create + retention + (optionnel) verify
- `worker/scripts/restore_from_backup.py` : restore d'un backup vers tmp
- `deploy/backup.plist.template` + `install-backup-launchd.sh` :
  schedule 03:00 quotidien

## TODO Sprint 2+

- Cibles backup distantes (Backblaze B2, Storj, rsync.net) chiffrées
  end-to-end (côté client).
- Restore sélectif (1 cabinet) sans unpack global.
- Test restore mensuel automatique via launchd séparé (StartCalendarInterval Day=1).
- Signature externe TSA du backup hash (preuve d'antériorité).
