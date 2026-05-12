# Décision — Encryption at-rest Sprint 1 §3.4

**Date :** 2026-05-12
**Sprint :** 1 §3.4 (Session 5)
**Statut :** Actée et livrée.

## Contexte

Le PRD V2 §3.4 demande chiffrement at-rest : SQLCipher pour `fiduciaire.sqlite`
+ age pour fichiers `data/archive/`. Le but est protéger les données du
cabinet en cas de vol du Mac Mini ou copie disque non autorisée.

## Décision

**Sprint 1 : Fernet (lib `cryptography`) pour les fichiers archive
uniquement. SQLCipher reporté Sprint 2.**

### 1. Fichiers archive `data/archive/<cabinet>/*` → Fernet AES-128-CBC + HMAC

- 1 clé maître par cabinet, 256 bits aléatoires.
- Stockée dans Keychain macOS (`fiduciaire`, `encryption-key-<cabinet>`).
- Fallback env var `FIDUCIAIRE_ENCRYPTION_KEY_<CABINET>` pour dev.
- Format on-disk : magic `FID1` (4 bytes) + version (4 bytes) + token Fernet.
- Mode dev `FIDUCIAIRE_ENCRYPTION_DISABLED=true` pour tests rapides.

### 2. DB SQLite `fiduciaire.sqlite` → NON chiffrée par cette couche

Repose sur **FileVault macOS** (disk-level encryption AES-XTS-256, par
défaut actif sur les Macs récents). Le Mac Mini cabinet pilote a
FileVault activé (vérification opérateur à l'install).

## Pourquoi pas SQLCipher Sprint 1

1. **Installation pénible sur macOS** : `pysqlcipher3` nécessite le binaire
   SQLCipher + compilation, souvent KO sans homebrew configuré. Friction
   install cabinet = blocage commercial.
2. **Gain marginal vs FileVault déjà actif** : la DB est chiffrée au repos
   par FileVault. SQLCipher ajoute une couche, mais le vecteur d'attaque
   "vol Mac éteint" est déjà couvert.
3. **Complexité tests** : chaque test pytest devrait initialiser une
   connexion SQLCipher avec clé → patterns plus complexes, risque de
   tests qui ne reflètent pas la prod.
4. **Le brief §7 du prompt session 5 autorise ce fallback** :
   *"Si SQLCipher trop complexe, fallback sur `cryptography` + chiffrement
   applicatif (chiffrer les colonnes sensibles seulement)"*.

## Vecteurs d'attaque couverts vs non couverts

| Attaque | FileVault | Fernet archive | Couvert ? |
|---|---|---|---|
| Vol Mac éteint, disque copié | ✓ | ✓ | OUI |
| Vol Mac allumé déverrouillé | ✗ | ✗ | NON (process en cours) |
| Exfiltration PDF via réseau interne | ✗ | ✓ | OUI (PDF chiffrés out-of-process) |
| Backup non chiffré copié | dépend | ✓ pour les PDF | PARTIEL (DB en clair) |
| SQL injection ou RCE worker | ✗ | ✗ | NON (à mitiger code review) |

**Conclusion** : couverture suffisante pour Sprint 1 install cabinet
pilote. Sprint 2 ajoutera SQLCipher pour le scenario "backup DB exporté
sans chiffrement explicite" qui n'est pas couvert ici.

## Pourquoi Fernet (et pas age)

- **Pas de dépendance binaire** : `cryptography` pip install pur Python.
  `age` exigerait `pyrage` (binding Rust) ou le binaire `age` CLI.
- **Format Fernet stable** : RFC-informel, spec figée, large adoption.
- **API simple** : `Fernet(key).encrypt(bytes)` → `Fernet(key).decrypt(token)`.
- **HMAC intégré** : détection tampering automatique.

Trade-off : Fernet utilise AES-128-CBC, pas AES-256-GCM. Sécurité équivalente
en pratique pour notre besoin (clé maître 256-bit qui dérive la clé AES-128).
Pour Sprint 2, possibilité de migrer à `cryptography.hazmat.AESGCM` si besoin.

## Implémentation livrée

### Module : `worker/src/fiduciaire_worker/encryption.py`

API publique :
- `MasterKey.generate(cabinet_id) -> MasterKey`
- `get_master_key(cabinet_id) -> MasterKey` (raise si absent)
- `ensure_master_key(cabinet_id) -> MasterKey` (génère si absent, persiste Keychain)
- `encrypt_bytes/decrypt_bytes(data, key) -> bytes`
- `encrypt_file(src, dst, cabinet_id)`
- `decrypt_file_to_bytes(src, cabinet_id) -> bytes` (streaming pipeline)
- `decrypt_file_to_path(src, dst, cabinet_id)`
- `is_encrypted_file(path) -> bool` (check magic FID1)
- `rotate_key_and_re_encrypt(cabinet_id, archive_root, new_key=None) -> RotationResult`
- `is_encryption_disabled() -> bool`

### Scripts CLI

- `worker/scripts/encrypt_archive_files.py` : chiffre in-place une archive existante (idempotent, skip les déjà chiffrés).
- `worker/scripts/rotate_master_key.py` : rotation clé + re-chiffrement (confirm 'ROTATE' interactif).

### Tests : 19 tests verts (`test_encryption.py`)

Roundtrip, mauvaise clé, corruption détectée, mode disabled, isolation
multi-mandant, rotation OK, plain files non touchés, header magic, dev mode.

## TODO Sprint 2

- SQLCipher pour `fiduciaire.sqlite` (quand stack stabilisée et install
  cabinet automatisée — `brew install sqlcipher` puis `pip install pysqlcipher3`).
- Chiffrement applicatif optionnel pour colonnes ultra-sensibles
  (`accounting_entries.reasoning`, `email_messages.body_excerpt`) si
  besoin compliance LPD renforcé.
- Migration vers AES-256-GCM via `cryptography.hazmat.AESGCM` si audit
  cabinet réclame AES-256 explicitement.
