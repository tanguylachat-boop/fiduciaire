# Décision — Column encryption applicative Sprint 1 §3.4-bis

**Date :** 2026-05-12
**Sprint :** 1 §3.4-bis (Session 6)
**Statut :** Actée et livrée (20 tests verts).

## Contexte

Session 5 livré la couche Fernet sur les fichiers archive PDF, mais a
laissé la DB SQLite en clair (couverte par FileVault macOS). Limite
identifiée : un curieux avec accès au Mac allumé déverrouillé OU à un
dump SQL non chiffré peut lire montants, fournisseurs, libellés directs.

## Décision

**Ajouter une couche column encryption applicative sur 5 colonnes texte
sensibles via Fernet (même clé maître archive cabinet).** Format
`enc:v1:<token>` pour permettre détection + back-compat valeurs legacy.

### Colonnes chiffrées

| Table | Colonne | Justification |
|---|---|---|
| `accounting_entries` | `description` | Libellé peut révéler nom client / nature transaction |
| `accounting_entries` | `reasoning` | Raisonnement LLM contient logique + PII |
| `vendor_account_history` | `vendor_name` | PII fournisseur |
| `email_messages` | `body_excerpt` | Extrait email contient PII contenu |
| `email_messages` | `from_addr` | Email expéditeur (PII RGPD/LPD) |

### Colonnes NON chiffrées Sprint 1

- `accounting_entries.amount_chf` (REAL) — chiffrement casserait les
  agrégations SUM/ORDER BY/MAX nécessaires aux dashboards et rapports.
  Le montant seul n'est pas PII sans le fournisseur ou le client.
  Sprint 2 si besoin : approche hybride (montant clair + checksum chiffré).
- `accounting_entries.date`, `debit_account`, `credit_account` —
  non sensibles (codes comptables génériques + dates publiques).
- `accounting_entries.vat_code` — code énuméré (TN_NORM, etc.), pas PII.
- `email_messages.subject` — pourrait être chiffré Sprint 2, choix
  pragmatique pour ne pas casser les filtres LIKE sur subject côté UI.

### Architecture technique

**Format on-DB :** `enc:v1:<base64-fernet-token>` (préfixe explicite).

Avantages du préfixe :
- Détection facile (back-compat) : valeurs sans préfixe = legacy en clair.
- Versionnage : `v2:` pour upgrades futurs (ex. AES-256-GCM).
- Pas de schéma additionnel (colonnes restent TEXT).

**API publique** dans `encryption.py` :
```python
encrypt_column_value(value: str | None, cabinet_id: str) -> str | None
decrypt_column_value(value: str | None, cabinet_id: str) -> str | None
is_encrypted_column_value(value) -> bool
encrypt_dict_columns(data: dict, fields: list[str], cabinet_id) -> dict
decrypt_dict_columns(data: dict, fields: list[str], cabinet_id) -> dict
migrate_column_in_place(conn, table, cabinet_id_column, target_column, cabinet_id, dry_run=False)
```

**Mode dev :** `FIDUCIAIRE_ENCRYPTION_DISABLED=true` → encrypt/decrypt =
no-op (retourne value tel quel). Activé par défaut dans `tests/conftest.py`
pour non-régression sur les 246 tests existants.

### Hooks intégrés dans modules métier

| Module | Modification |
|---|---|
| `entry_proposer._persist` | encrypt `description` + `reasoning` AVANT INSERT |
| `vendor_account_history.build_history_from_bexio_cache` | encrypt `vendor_name` AVANT INSERT |
| `vendor_account_history.lookup` | decrypt `vendor_name` AVANT retour + fallback in-memory fuzzy |
| `imap_fetch._insert_email_message` | encrypt `body_excerpt` + `from_addr` AVANT INSERT |
| `bexio_push._build_payload` | decrypt `description` AVANT POST Bexio |

L'objet retourné par les modules reste en clair (les attributs ne sont
pas réécrits). Ainsi le code aval (dashboard, tests) voit les valeurs
claires sans modification.

### Migration legacy → chiffré

Script `worker/scripts/migrate_encrypt_columns.py` :
- Filtre par `cabinet_id` (multi-mandant strict)
- Idempotent : skip valeurs déjà `enc:v1:...`
- Skip valeurs NULL ou vides
- Mode `--dry-run` pour preview avant prod
- Rapport par table : encrypted / already / null-or-empty

À exécuter en prod avec backup préalable.

### Limites assumées Sprint 1

1. **vendor_account_history.lookup fuzzy** : SQL LIKE ne marche plus
   sur colonnes chiffrées (token aléatoire ≠ contenu). Fallback :
   chargement full + decrypt en mémoire + match. Acceptable car N ≤
   quelques centaines vendors par cabinet.

2. **potential_duplicate detection** (§3.7) : groupage sur `description`
   chiffrée échoue (tokens Fernet uniques par cabinet). On groupe sur
   `amount_chf` (en clair) + description token, ce qui sous-détecte.
   Mitigation Sprint 2 : decrypt avant scan ou clé déterministe.

3. **Dashboard Next.js** : ne fait pas de decrypt côté serveur. Sprint 1
   le dashboard tourne sur le Mac Mini cabinet en mode dev DISABLED.
   Sprint 2 : passer par un proxy Python local qui décrypte avant de
   servir au dashboard, OU implémenter Fernet en TypeScript.

## Conséquences positives

- **PII protégée au repos** même si la DB est lue avec un client SQLite
  externe sans la clé Keychain.
- **Multi-mandant cryptographique** : clé par cabinet, isolation garantie
  (cabinet A ne peut pas déchiffrer description de cabinet B).
- **Idempotent** : migration safe à relancer.
- **Back-compat** : valeurs legacy en clair restent lisibles.

## Tests livrés (20 verts)

`test_column_encryption.py` :
- encrypt/decrypt roundtrip
- None/empty edge cases
- idempotent double-encrypt
- legacy plain value pass-through
- is_encrypted_column_value detection
- multi-mandant isolation (decrypt avec mauvaise clé → EncryptionError)
- dict helpers
- mode disabled no-op
- migration : encrypts plain, skips already-encrypted, skips null/empty,
  dry-run, multi-mandant
- **E2E intégration** : entry_proposer.propose_entry stocke chiffré,
  vendor_history.lookup decrypt, imap_fetch persiste chiffré,
  bexio_push decrypt avant POST

## TODO Sprint 2+

- SQLCipher (si besoin compliance LPD renforcé pour grands cabinets)
- AES-256-GCM via `cryptography.hazmat.AESGCM`
- Index déterministe sur hash(description) pour LIKE-like queries
- Decryption layer côté dashboard Next.js
- Migration script avec rotation clé (re-chiffre toutes les colonnes
  avec nouvelle clé maître cabinet)
