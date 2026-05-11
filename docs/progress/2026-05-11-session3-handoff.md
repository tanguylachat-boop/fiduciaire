# Session 3 — Handoff Option Z

**Date :** 2026-05-11
**Branche :** `feature/sprint-0a-core` (commits `050da46` + commit Phase A imminent)
**Statut :** Sprint 1 §3.1 **Phase A livrée**. Phase B (orchestrator) +
Phase C (daemon + cabinet réel) reportées sessions 4 et 5.

---

## 1. Contexte de la session

### En entrée

- Bench RunPod re-exécuté sur corpus correctement ingéré (post
  `ingest_local_corpus.py` session 2). Résultats cold start :
  Llama 70B account **18.2%** / VAT **81.8%** / 7.5s ; Mistral 24B
  account **15.2%** / VAT **69.7%** / 4.7s. **Décision figée : Mistral
  default** (32 GB cabinet pilote-01 force la main, écart 3pts dans
  marge d'erreur, 1.6× plus rapide, 800 CHF/cabinet économisés).
- Bug tag Ollama corrigé : `mistral-small3:24b-instruct-q4_K_M`
  (n'existe pas) → `mistral-small:24b-instruct-2501-q4_K_M` (tag réel).
- Commit `050da46` "fix(bench): correct mistral tag + log real bench
  numbers" pushed.

### En sortie

- Sprint 1 §3.1 IMAP : spec complète + Phase A foundation livrée et
  testée. Cabinet pilote-01 pas encore connecté à un vrai IMAP — c'est
  Phase B+C.

---

## 2. Modules livrés cette session

### Fixes bench (commit `050da46`)

| Fichier | Changement |
|---|---|
| `worker/scripts/entry_bench.py` | tag `mistral-small3` → `mistral-small:24b-instruct-2501-q4_K_M` |
| `docs/decisions/2026-05-09-mistral-small-3-as-default.md` | section "Mise à jour 2026-05-11" avec chiffres réels, décision figée |
| `docs/decisions/2026-05-08-llm-bench-mistral-vs-llama.md` | tags corrigés |
| `docs/specs/ingest-local-corpus.md` | tag corrigé dans la séquence post-livraison |

### Sprint 1 §3.1 Phase A (commit imminent)

| Fichier | LoC | Status |
|---|---|---|
| `docs/specs/imap-fetch.md` | 365 | nouveau, spec complète Phases A/B/C |
| `worker/src/fiduciaire_worker/email_parser.py` | 187 | nouveau, parse RFC822 → ParsedEmail |
| `worker/tests/test_email_parser.py` | 295 | **20 tests verts** |
| `worker/src/fiduciaire_worker/imap_client.py` | 218 | nouveau, facade IMAP4_SSL mockable |
| `worker/tests/test_imap_client.py` | 305 | **16 tests verts** |
| `worker/src/fiduciaire_worker/secrets.py` | +110 | extension `get_imap_credentials` |
| `worker/tests/test_secrets_imap.py` | 154 | **11 tests verts** |
| `worker/src/fiduciaire_worker/db.py` | +55 | schéma `email_messages`, `email_attachments`, `email_fetch_state` |

**Total Phase A** : 4 nouveaux modules code, 3 nouveaux fichiers tests,
**47 nouveaux tests**, 0 régression.

### API publique Phase A

#### `email_parser.parse_email_bytes(raw: bytes) -> ParsedEmail`

Parse stdlib `email.message_from_bytes`, walk récursif multipart pour
attachments, détection PGP/SMIME (n'extrait PAS les chiffrés), décode
RFC 2047, body excerpt 200 chars (RGPD/LPD minimisation).

`ParsedEmail` : message_id, date_received, from_addr, to_addr, subject,
body_excerpt, encryption_status, attachments[], size_bytes.

`ParsedAttachment` : filename, content_type, size_bytes, content_sha256,
raw_bytes.

`is_supported_pipeline(content_type, filename) -> bool` : true si
content-type ∈ {pdf, png, jpeg, tiff} OU extension du filename ∈
{.pdf, .png, .jpg, .jpeg, .tif, .tiff}. Aligné avec
`watcher.ACCEPTED_SUFFIXES`.

#### `imap_client.ImapClient`

Facade autour de `imaplib.IMAP4_SSL` avec factory injectable pour les
tests. TLS obligatoire (port 143 refusé). Retry exponentiel backoff sur
erreurs réseau (3× par défaut, 1s/2s/4s). Pas de retry sur auth fail.

Méthodes : `connect(user, password)`, `select_folder(folder) → (uidvalidity, exists)`,
`fetch_uids_above(last_uid) → list[int]`, `fetch_message(uid) →
FetchedMessage`, `mark_seen(uid)`, `close()`.

Exceptions : `ImapAuthError`, `ImapNetworkError`.

#### `secrets.get_imap_credentials(cabinet_id, host?, port?, user?) -> ImapCredentials`

Fallback chain identique à `get_bexio_pat` :
1. Keychain `imap-<cabinet>-<field>` (service `fiduciaire`)
2. Env var `IMAP_<FIELD>_<CABINET_NORMALIZED>` (cabinet `-` → `_`)
3. Argument passé (host/port/user uniquement)
4. RuntimeError explicite si password manquant

### Schéma SQL ajouté

- `email_messages (id, cabinet_id, folder, uid, uidvalidity, message_id,
  date_received, from_addr, to_addr, subject, body_excerpt,
  encryption_status, size_bytes, fetched_at)` — UNIQUE
  `(cabinet_id, message_id)`
- `email_attachments (id, email_id FK, filename, content_type, size,
  content_sha256, status, document_id FK nullable, reason, created_at)`
  — UNIQUE `(email_id, content_sha256)`
- `email_fetch_state (cabinet_id, folder, uidvalidity, last_uid_seen,
  last_fetch_at, last_fetch_status)` — PK `(cabinet_id, folder)`
- Constantes Python exportées : `EMAIL_ATT_STATUS_*` et `EMAIL_ENC_*`

Schéma idempotent (CREATE IF NOT EXISTS), aucune migration manuelle
nécessaire.

---

## 3. État global

| Composant | Statut |
|---|---|
| Sprint 0a — 7 modules core | ✅ session 1 |
| Sprint 0a — Dashboard `/(poc)/entries` | ✅ session 1 |
| Sprint 0a — Bexio sync read-only | ✅ session 1 |
| Sprint 0a — `secrets.get_bexio_pat` | ✅ session 1 |
| Sprint 0a — `ingest_local_corpus.py` | ✅ session 2 |
| Sprint 0a — Bench Mistral vs Llama | ✅ session 3 (décision figée) |
| Sprint 1 §3.1 — Phase A (email_parser + imap_client + secrets + schéma) | ✅ **session 3** |
| Sprint 1 §3.1 — Phase B (orchestrator + CLI) | ⏳ session 4 |
| Sprint 1 §3.1 — Phase C (daemon launchd + cabinet réel) | ⏳ session 5 |
| Sprint 1 §3.2 — Bexio push | ⏳ session 4 (parallèle Phase B) |
| Sprint 1 §3.3 — Multi-mandant N=3 | ⏳ session 5+ |
| Sprint 1 §3.4 — Chiffrement at-rest | ⏳ session 5+ |

**Tests totaux** : **136 Python passing** (89 prior + 20 email_parser
+ 16 imap_client + 11 imap_secrets) + 7 TS smoke = **143 tests verts**,
zéro régression.

---

## 4. Point de reprise — Session 4 Option Z

### Modules cibles Session 4 (Phase B)

#### `imap_fetch.py` orchestrator (estimation 0.5j)

Wire Phase A end-to-end :
1. Charger config cabinet + creds via `secrets.get_imap_credentials`
2. `ImapClient.connect/select_folder`
3. Charger `email_fetch_state(cabinet, folder)`
4. Si `UIDVALIDITY` change → full rescan + dedup Message-ID
5. Sinon → `fetch_uids_above(last_uid_seen)`
6. Pour chaque UID :
   - `fetch_message` → bytes
   - `parse_email_bytes` → ParsedEmail
   - Dedup check sur `email_messages.UNIQUE(cabinet_id, message_id)`
   - INSERT email_messages
   - Pour chaque attachment :
     - Si `encryption_status` ∈ {pgp, smime} → status `encrypted_skipped`
     - Si `is_supported_pipeline()` → save staging + `process_document()`
     - Sinon → status `unsupported`
7. UPDATE `email_fetch_state.last_uid_seen`
8. Optionnel : `mark_seen(uid)` selon config
9. Summary console + exit 0

#### CLI `worker/scripts/imap_fetch.py`

```bash
python worker/scripts/imap_fetch.py --cabinet pilote-jura-01 \
  [--folder INBOX] [--config config.yaml] [--mark-seen] [--dry-run]
```

#### Tests intégration Phase A+B

`worker/tests/test_imap_fetch_integration.py` : FakeImap server end-to-end
avec 3-5 emails synthétiques (1 PDF simple, 1 multi-attachments, 1 PGP),
vérifie que documents + email_messages + email_attachments sont
correctement peuplés en DB + dedup fonctionne sur 2e run.

### Modules cibles Session 5 (Phase C)

- Lock file POSIX `data/imap-fetch.<cabinet>.lock` (flock)
- launchd plist Mac Mini cabinet (`com.lxstudio.fiduciaire.imap.plist`,
  StartInterval=300)
- Smoke test contre vrai serveur Infomaniak (compte test, pas pilote)
- Documentation onboarding cabinet : "comment générer un app password
  Infomaniak en 3 clics"

### Démarrage session 4

1. `git pull origin feature/sprint-0a-core`
2. Lis ce fichier (`2026-05-11-session3-handoff.md`)
3. Lis `docs/specs/imap-fetch.md` (Phase B = §4 step 9-12)
4. Démarre `imap_fetch.py` orchestrator selon spec §3.2 data flow
5. Tests intégration FakeImap server end-to-end

---

## 5. Décisions techniques prises Session 3

1. **`imaplib` stdlib retenu** vs `imapclient` ou `aioimaplib`.
   Justification dans `docs/specs/imap-fetch.md §8` : zéro dépendance
   ajoutée, sync polling 5 min suffit, mockabilité totale via factory.

2. **Phase A séparée de Phase B** : `email_parser` + `imap_client` +
   secrets + schéma livrés isolément, sans orchestrator. Permet de
   tester chaque brique à fond avant de les wirer. Aligné avec le
   protocole Option Z (handoff propre à chaque saturation contexte).

3. **PGP/SMIME : detect-not-decrypt** : on flag l'email avec
   `encryption_status` et on N'EXTRAIT PAS les attachments chiffrés.
   Justification : LPD interdit le traitement sans consentement
   explicite ; la clé privée reste chez le cabinet, jamais vue par
   notre module.

4. **`body_excerpt` 200 chars max** : minimisation RGPD/LPD. Le corps
   complet du mail n'est jamais stocké en DB (seul l'attachment l'est,
   via le pipeline existant qui copie dans `data/archive/`).

5. **Message-ID synthétique stable** : si header `Message-ID` absent
   (rare mais possible — mailers bricolés), on génère
   `<synth-<sha256_short>@fiduciaire.local>`. Stable = même bytes → même
   id → dedup fonctionne quand même.

6. **TLS obligatoire dur** : `ImapClient(port=143)` raise au démarrage.
   Pas de "warning, continue" — refus net pour éviter qu'un cabinet
   ouvre un port plain par erreur.

7. **Retry exponentiel sur réseau, pas sur auth** : DNS / connexion
   refusée / timeout → retry 3× avec backoff 1s/2s/4s. Auth failure
   → raise immédiatement (pas de risque de DOS le compte du cabinet).

---

## 6. Issues / TODOs

- [ ] **Phase B (orchestrator) session 4** : voir §4 ci-dessus
- [ ] Vérifier que `policy=email.policy.compat32` est le bon choix vs
      `email.policy.default` — compat32 plus tolérant aux mails mal
      formés mais retourne `str` au lieu de `EmailMessage`. À tester
      sur 5-10 emails réels en session 5 Phase C.
- [ ] Décider du comportement `mark_seen` par défaut : actuellement
      manuel via `--mark-seen`. Pour cabinet pilote, mark seen = bonne
      pratique (le cabinet voit visuellement ce qui a été traité).
- [ ] Encodage chemin staging : `data/imap-staging/<cabinet>/<sha>.<ext>`
      doit gérer les filenames Unicode (Phase B).
- [ ] Tests réels Infomaniak en Phase C : créer un compte
      `test-fiduciaire@infomaniak.com` dédié, envoyer 5 emails avec
      différentes PJs.

---

## 7. Notes annexes

### .env

Le fichier `.env` du repo contient actuellement (session 1) le PAT
Bexio dev. Pour Phase B, ajouter :
```
IMAP_HOST_PILOTE_JURA_01=imap.infomaniak.com
IMAP_PORT_PILOTE_JURA_01=993
IMAP_USER_PILOTE_JURA_01=factures@cabinet-jura.ch
IMAP_PASSWORD_PILOTE_JURA_01=<app-password>  # généré sur Infomaniak
```

Ou (recommandé prod) Keychain :
```bash
python -c "import keyring; \
  keyring.set_password('fiduciaire', 'imap-pilote-jura-01-password', '<pwd>')"
```

### Documentation onboarding cabinet (Phase C)

À écrire en session 5 : `docs/cabinet-imap-setup.md` avec :
- Comment générer un app password Infomaniak / Hostpoint
- Comment transmettre le password chiffré (Signal sealed message)
- Quelle boîte dédier (`factures@<cabinet>`)
- Filtres serveur SpamAssassin recommandés

---

## 8. Commande de relance Session 4

```
/clear

[paste master prompt Option Z]

PUIS ajoute en fin de prompt :
"Reprends Sprint 1 §3.1 Phase B (imap_fetch.py orchestrator + CLI +
integration tests). Lis docs/progress/2026-05-11-session3-handoff.md
puis docs/specs/imap-fetch.md §4 étapes 9-12. Phase A foundation
livrée et testée (47 tests verts). Schéma SQL email_* déjà dans
db.SCHEMA."
```
