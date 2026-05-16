# 7. L'audit trail (traçabilité fiscale)

## Pourquoi un audit trail ?

L'administration fiscale suisse exige que toute modification de
décision comptable (validation, push Bexio, rejet) soit **tracée
de manière immutable** pendant 10 ans.

L'employé IA stocke ces traces dans une **chaîne de hachages
SHA-256**. Chaque événement contient le hash du précédent. Si
quelqu'un modifie ou supprime un événement, la chaîne casse — et
c'est détecté.

## Voir l'audit trail

Ouvrez `http://localhost:3000/audit?client=<votre-mandant>`

Vous voyez la liste de tous les événements pour ce mandant, du
plus récent au plus ancien :

- Date et heure
- Utilisateur (vous, ou "system" pour les actions automatiques)
- Entité (écriture, document, push Bexio, etc.)
- Action (proposed, validated, bexio_pushed, etc.)
- Avant / après (snapshot JSON des données)

## Vérifier la chaîne

En haut de la page, un bouton **"Vérifier la chaîne"** déclenche
une recomputation complète des hashes. Le résultat :

- ✅ **Chain valide** : tout est cohérent
- ❌ **Chain cassée** : un événement a été altéré → affiche
  l'ID du premier événement corrompu

Si vous voyez une chaîne cassée et que vous ne savez pas pourquoi :
**appelez Tanguy immédiatement**. C'est rare et grave.

## Filtres utiles

- **Type d'entité** : `accounting_entry`, `email_message`,
  `bexio_push`, `bank_match`, `abacus_export`, `cabinet`, etc.
- **Action** : `proposed`, `validated`, `rejected`, `bexio_pushed`,
  `exported`, `cabinet_provisioned`
- **Période** : depuis / jusqu'à (utile pour un contrôle fiscal sur
  un trimestre précis)
- **Utilisateur** : qui a fait quoi

## Export pour contrôle fiscal

Si l'administration fédérale des contributions demande votre audit
trail, exportez-le en texte brut :

```bash
worker/.venv/bin/python -c "
from fiduciaire_worker import audit_log, db, accounting_schema
from pathlib import Path
conn = db.connect(Path('data/fiduciaire.sqlite'))
audit_log.init_audit_schema(conn)
audit_log.export_audit_text(
    conn, '<votre-mandant>',
    since='2026-01-01', until='2026-12-31',
    out_path=Path('/tmp/audit-2026.txt')
)
"
```

Le fichier `/tmp/audit-2026.txt` contient toute la trace lisible,
avec en-tête et footer signés du hash final de la chaîne.

## Que faire quand ?

| Situation | Action |
|---|---|
| Contrôle fiscal annoncé | Exporter l'audit trail de la période |
| Chaîne cassée affichée | Appeler Tanguy d'urgence |
| Doute sur une écriture | Filtrer par `entity_id=<id>` |
| Demande de preuve de validation | Filtrer par `action=validated` |

## Limites

- L'audit trail ne capture **pas** le contenu des PDF originaux.
  Ceux-ci sont archivés à part dans `data/archive/` avec hash SHA-256.
- Les colonnes sensibles (descriptions, noms fournisseurs) sont
  **chiffrées** dans la chaîne. Seul votre Mac Mini possède la clé.
- L'audit trail est **local** : aucun événement n'est envoyé vers
  un serveur tiers.

## Sauvegarde de l'audit trail

L'audit trail est inclus dans la sauvegarde quotidienne. Si le Mac
Mini tombe en panne, on restaure depuis `data/backups/` et la chaîne
reprend du même état.
