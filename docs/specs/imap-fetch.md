# Spec — Sprint 1 §3.1 `imap_fetch`

**Date :** 2026-05-11
**Sprint :** 1 — Session 3 Option Z (phase A) + Session 4 (phase B/C)
**PRD ref :** §3.10 (reporté Sprint 0a → Sprint 1), §3.1
**Statut :** spec → phases A/B/C

---

## 1. Pourquoi ce module existe

Le pilote cabinet-01 (femme Gravosig, Jura) reçoit ses factures par
email — typiquement boîte dédiée `factures@cabinet-jura.ch` chez
Infomaniak ou Hostpoint. Sprint 0a a été livrable sans IMAP : le pilote
dépose manuellement les PDFs dans `data/inbox/`. Sprint 1 automatise
ce drop via une boîte IMAP polled toutes les 5 min.

### Contraintes PRD non négociables

- **100% local** : pas d'OAuth Google/Microsoft Graph, IMAP TLS direct
  sur serveur du cabinet (Infomaniak / Hostpoint / serveur on-prem).
  Credentials détenus par le cabinet.
- **Confidentialité** : ne décoder QUE les messages clairs. Si PGP /
  S/MIME détecté → flag pour revue humaine, ne pas tenter de
  déchiffrer (LPD : traitement sans consentement explicite du chiffré).
- **Idempotence** : re-fetcher la même boîte 10× ne produit pas 10×
  les mêmes pièces.
- **Multi-mandant** : design pour N cabinets dès le jour 1, même si
  seul `pilote-jura-01` est configuré en session 3.

---

## 2. USER ACTION MAP

### ACTION : poll la boîte email du cabinet et router les pièces jointes

**TRIGGER :** Tanguy lance manuellement (ou cron / launchd) :
```bash
python worker/scripts/imap_fetch.py --cabinet pilote-jura-01
```

**FRONTEND :** sortie console :
```
IMAP fetch — cabinet=pilote-jura-01 host=imap.infomaniak.ch:993
  Selected INBOX (uidvalidity=42, 1247 msgs)
  Resume from last_uid=1238 → 9 new messages
  [1/9] msg_id=<abc@infomaniak.ch> from=factures@swisscom.ch subj="Facture 03/2026"
        → 1 attachment: facture_swisscom_032026.pdf (245 KB)
        → ingested doc_id=42 status=routed
  [2/9] msg_id=<xyz@helsana.ch> from=billing@helsana.ch subj="Décompte assurance"
        → 0 attachments (PGP detected, body=encrypted)
        → flagged for human review
  ...
─── SUMMARY ───
  9 emails processed | 7 with attachments | 1 PGP-flagged | 1 no-attachment
  12 attachments → 11 ingested | 1 unsupported (zip)
  state: last_uid=1247 saved
  duration: 14.2s
```

**API CALL :** Aucun (CLI local). Connexion sortante : IMAP TLS 993 vers
le serveur du cabinet.

**BACKEND LOGIC :**
1. Charger config du cabinet (`config/clients/<cabinet>.yaml` ou
   `config.yaml` racine pour mono-cabinet).
2. Récupérer credentials via
   `secrets.get_imap_credentials(cabinet_id)` (Keychain → `.env` →
   raise).
3. `ImapClient.connect(host, port, user, password)` (TLS 993, login).
4. `SELECT <folder>` → lire `UIDVALIDITY` + total messages.
5. Charger `email_fetch_state` pour `(cabinet_id, folder)`.
6. Si `UIDVALIDITY` correspond à l'état stocké → fetch UIDs > `last_uid_seen`.
   Sinon → full rescan + dedup Message-ID.
7. Pour chaque UID nouveau :
   - `UID FETCH <uid> BODY.PEEK[]` → bytes RFC822 entiers.
   - `email_parser.parse_email_bytes(raw)` → `ParsedEmail`.
   - Si déjà en DB (Message-ID match) → skip, log dup.
   - Sinon : INSERT `email_messages`.
   - Pour chaque attachment supporté :
     - SHA256, save dans `data/imap-staging/<cabinet_id>/<sha>.<ext>`
     - INSERT `email_attachments` avec status `pending`
     - Si suffixe non supporté (ex. `.zip`, `.docx`) → status `unsupported`, doc_id=NULL
     - Si suffixe supporté → `pipeline.process_document(staging_path, config, conn, delete_inbox=False)`
       → UPDATE attachment `status=processed`, `document_id=<doc_id>`
   - Si `encryption_status` est `pgp` ou `smime` → log, ne pas tenter d'extraire attachments chiffrés.
8. UPDATE `email_fetch_state.last_uid_seen = max(uid)`.
9. Print summary, close connection, return 0.

**EXTERNAL API :** IMAP4rev1 (RFC 3501) via TLS 993. Commandes utilisées :
- `LOGIN` (auth basique ; ne pas log password)
- `SELECT INBOX` (lit UIDVALIDITY + EXISTS)
- `UID SEARCH <uid>:* OR HEADER Message-ID <id>`
- `UID FETCH <uid> (FLAGS BODY.PEEK[] INTERNALDATE)`
- `UID STORE <uid> +FLAGS (\Seen)` (optionnel selon config)
- `LOGOUT`

**Rate limits IMAP :**
- Infomaniak : pas de limite documentée pour IMAP.
- Hostpoint : 100 connexions concurrentes max (largement OK pour
  polling 5 min).
- Stratégie : 1 connexion par fetch, fermée proprement (pas de pool).

**DB CHANGES :**
- `email_messages` : 1 INSERT par nouveau message (idempotent sur
  `(cabinet_id, message_id)`)
- `email_attachments` : 1 INSERT par PJ (idempotent sur
  `(email_id, content_sha256)`)
- `documents` : populé par `process_document` (pipeline existant)
- `email_fetch_state` : 1 UPSERT par fin de fetch

**SUCCESS STATE :** summary affiché, exit 0. Cron suivant repartira de
`last_uid_seen` mis à jour.

**ERROR STATES :**
| Erreur | Détection | Recovery | Sortie user |
|---|---|---|---|
| DNS / connexion refusée | `socket.gaierror` / `ConnectionRefusedError` | retry exp backoff 3× (1s/2s/4s) | exit 1 si épuisé, log clair |
| Auth fail (login) | `imaplib.IMAP4.error` avec `AUTH` / `LOGIN` | pas de retry | exit 2 + msg "vérifier credentials Keychain ou .env" |
| Network drop mid-fetch | `IMAP4.error` / `OSError` | retry exp backoff | summary partiel + exit 1 |
| Message corrompu | `email.errors.MessageParseError` | log + skip ce message, continue | summary marque `parse_error=N` |
| Attachment > 50 MB | size check avant save | skip, status `oversized` | summary marque, exit 0 |
| Pipeline raise sur 1 PJ | catch dans imap_fetch | attachment status `failed`, continue | summary marque |
| PGP/SMIME | détecté par email_parser | flag, attachment status `encrypted_skipped` | summary marque, pas d'erreur |
| `Ctrl-C` mid-poll | `KeyboardInterrupt` | flush summary partiel + close IMAP | exit 130 |
| DB locked | propage SQLite | retry 1× après 100ms, sinon raise | exit 1 |

**EDGE CASES :**
- **Folder UIDVALIDITY change** : serveur a rebuild la mailbox (rare,
  mais arrive sur reconfiguration). On full-rescanne + dedup Message-ID
  garantit pas de doublon.
- **Email avec 0 attachments** : INSERT email_messages, 0 attachments,
  status `no_attachment` (utile pour debug : "j'ai bien reçu ton mail
  mais sans PJ").
- **Email avec attachment vide** (0 bytes) : skip, status `empty`.
- **Same attachment in 2 emails** : sha256 différent par mail ; on accepte
  les doublons logiques mais SQLite assure unicité technique via sha
  sur `documents` (le pipeline dédup déjà). Le 2e ingest retourne
  status=duplicate côté pipeline → on link l'attachment au doc existant.
- **Multipart imbriqué** : `email_parser` walk récursif pour trouver tous
  les `application/pdf` même nichés dans `multipart/related`.
- **Encoding sujet/from non-UTF8** : `email.header.decode_header` gère
  RFC 2047 (`=?utf-8?B?…?=`, `=?iso-8859-1?Q?…?=`).
- **Reply chain longue** : on garde uniquement les 200 premiers
  caractères du body texte comme `body_excerpt` (pas de stockage du
  fil complet — RGPD/LPD minimisation).
- **From spoofé / phishing** : pas de validation DKIM/SPF en Sprint 1.
  Cabinet doit avoir SpamAssassin côté serveur. Documenter dans le
  guide cabinet.
- **2 process imap_fetch concurrents** : verrouillage via lock file
  `data/imap-fetch.<cabinet_id>.lock` (flock POSIX). 2e instance exit
  0 avec message "déjà en cours".
- **Boîte vide** : 0 nouveau message → summary "no new", exit 0.

---

## 3. ARCHITECTURE TECHNIQUE

### 3.1 Phases de livraison

| Phase | Modules | Sessions | Effort |
|---|---|---|---|
| **A** | `email_parser.py` + `imap_client.py` + schéma SQL + `secrets.get_imap_credentials` + tests unitaires | Session 3 (en cours) | ~0.75j |
| **B** | `imap_fetch.py` (orchestrator) + CLI script + tests intégration FakeImap | Session 4 | ~0.5j |
| **C** | Lock file daemon + launchd plist Mac Mini + smoke test cabinet réel | Session 5 | ~0.25j |

### 3.2 Data flow (vue Phase B complète)

```
CLI args (--cabinet, --folder, --since)
   ↓
load_config(--config) → Config + ClientConfig
   ↓
secrets.get_imap_credentials(cabinet_id) → ImapCredentials
   ↓
acquire_lock(data/imap-fetch.<cabinet>.lock)
   ↓
ImapClient(host, port).connect(user, password)
   ↓
SELECT <folder> → UIDVALIDITY, exists
   ↓
load_or_init_fetch_state(conn, cabinet, folder) → FetchState
   ↓
if state.uidvalidity != current:
    full_rescan = True
new_uids = imap.fetch_uids_above(state.last_uid_seen if not full_rescan else 0)
   ↓
for uid in new_uids:
    raw = imap.fetch_message(uid)
    parsed = email_parser.parse_email_bytes(raw)
    if dedup_message_id(conn, cabinet, parsed.message_id): continue
    insert_email_message(conn, cabinet, parsed, uid)
    for att in parsed.attachments:
        if att.is_supported_pipeline():
            staging = save_attachment(att, cabinet)
            try: outcome = process_document(staging, config, conn, delete_inbox=False)
            insert_email_attachment(conn, email_id, att, outcome.doc_id, status)
        else:
            insert_email_attachment(conn, email_id, att, None, 'unsupported')
   ↓
update_fetch_state(conn, cabinet, folder, last_uid=max(new_uids), uidvalidity)
   ↓
imap.close() + release_lock()
   ↓
print_summary, exit 0
```

### 3.3 Schéma SQL (Phase A — session 3)

```sql
CREATE TABLE IF NOT EXISTS email_messages (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  cabinet_id TEXT NOT NULL,
  folder TEXT NOT NULL,
  uid INTEGER NOT NULL,
  uidvalidity INTEGER NOT NULL,
  message_id TEXT NOT NULL,
  date_received TEXT,
  from_addr TEXT,
  to_addr TEXT,
  subject TEXT,
  body_excerpt TEXT,
  encryption_status TEXT NOT NULL DEFAULT 'plain',  -- 'plain'|'pgp'|'smime'
  size_bytes INTEGER,
  fetched_at TEXT NOT NULL DEFAULT (datetime('now')),
  UNIQUE (cabinet_id, message_id)
);

CREATE INDEX IF NOT EXISTS idx_email_messages_cabinet_uid
  ON email_messages (cabinet_id, folder, uid);

CREATE TABLE IF NOT EXISTS email_attachments (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  email_id INTEGER NOT NULL REFERENCES email_messages(id),
  filename TEXT,
  content_type TEXT,
  size_bytes INTEGER,
  content_sha256 TEXT NOT NULL,
  status TEXT NOT NULL,  -- 'pending'|'processed'|'failed'|'unsupported'|'encrypted_skipped'|'oversized'|'empty'
  document_id INTEGER REFERENCES documents(id),
  reason TEXT,
  created_at TEXT NOT NULL DEFAULT (datetime('now')),
  UNIQUE (email_id, content_sha256)
);

CREATE INDEX IF NOT EXISTS idx_email_attachments_email
  ON email_attachments (email_id);
CREATE INDEX IF NOT EXISTS idx_email_attachments_doc
  ON email_attachments (document_id);

CREATE TABLE IF NOT EXISTS email_fetch_state (
  cabinet_id TEXT NOT NULL,
  folder TEXT NOT NULL,
  uidvalidity INTEGER,
  last_uid_seen INTEGER NOT NULL DEFAULT 0,
  last_fetch_at TEXT NOT NULL DEFAULT (datetime('now')),
  last_fetch_status TEXT NOT NULL DEFAULT 'ok',
  PRIMARY KEY (cabinet_id, folder)
);
```

### 3.4 Modules Phase A — API

```python
# fiduciaire_worker.email_parser

@dataclass
class ParsedAttachment:
    filename: str
    content_type: str
    size_bytes: int
    content_sha256: str
    raw_bytes: bytes  # in-memory ; caller persiste

@dataclass
class ParsedEmail:
    message_id: str            # "<...@host>" RFC 822, fallback synthétique si absent
    date_received: str | None  # ISO 8601
    from_addr: str | None
    to_addr: str | None
    subject: str | None
    body_excerpt: str          # plain-text, 200 premiers caractères, RGPD-light
    encryption_status: str     # 'plain'|'pgp'|'smime'
    attachments: list[ParsedAttachment]
    size_bytes: int

def parse_email_bytes(raw: bytes) -> ParsedEmail: ...
def detect_encryption(parsed: email.message.Message) -> str: ...
def is_supported_pipeline(content_type: str, filename: str) -> bool: ...

# fiduciaire_worker.imap_client

@dataclass
class ImapCredentials:
    host: str
    port: int  # default 993
    user: str
    password: str
    use_tls: bool = True

@dataclass
class FetchedMessage:
    uid: int
    raw_bytes: bytes
    internal_date: str | None

class ImapClient:
    def __init__(self, host: str, port: int = 993,
                 imap_factory: Callable | None = None): ...
    def connect(self, user: str, password: str) -> None: ...
    def select_folder(self, folder: str) -> tuple[int, int]:  # (uidvalidity, exists)
        ...
    def fetch_uids_above(self, last_uid: int) -> list[int]: ...
    def fetch_message(self, uid: int) -> FetchedMessage: ...
    def mark_seen(self, uid: int) -> None: ...
    def close(self) -> None: ...

# fiduciaire_worker.secrets

IMAP_KEYRING_USER_PATTERN = "imap-{cabinet_id}-{field}"  # imap-pilote-jura-01-password
IMAP_ENV_PATTERN = "IMAP_{FIELD}_{CABINET}"               # IMAP_PASSWORD_PILOTE_JURA_01

def get_imap_credentials(cabinet_id: str) -> ImapCredentials: ...
```

### 3.5 Error recovery matrix

| Erreur | Détection | Recovery | Action user |
|---|---|---|---|
| `socket.gaierror` (DNS) | imap_client.connect | retry 3× exp backoff | exit 1, log "host introuvable" |
| `ConnectionRefusedError` | imap_client.connect | retry 3× exp backoff | exit 1 |
| `IMAP4.error: AUTHENTICATIONFAILED` | imap_client.connect après login | pas de retry | exit 2 "credentials invalides" |
| `email.errors.MessageParseError` | email_parser | skip ce mail | log, summary marque parse_error |
| sha256 collision impossible | n/a | n/a | n/a |
| disque plein staging | `OSError` save_attachment | raise | exit 1, summary partiel |
| pipeline raise sur PJ | catch dans orchestrator | status=failed, continue | summary marque |
| 2× même Message-ID | UNIQUE constraint | catch IntegrityError → log dup | continue |

---

## 4. IMPLEMENTATION ORDER

### Session 3 (en cours — Phase A)

1. ✅ Spec (ce document)
2. Schéma SQL — ajouts `db.SCHEMA` + tests
3. Tests TDD `email_parser.py` (offline, fixtures email synthétiques)
4. Implémentation `email_parser.py`
5. Tests TDD `imap_client.py` avec `FakeImapServer`
6. Implémentation `imap_client.py`
7. Extension `secrets.get_imap_credentials` + tests
8. Handoff session 3 + commit + push

### Session 4 (Phase B)

9. Tests TDD `imap_fetch.py` orchestrator
10. Implémentation orchestrator
11. CLI script `worker/scripts/imap_fetch.py`
12. Integration tests Phase A+B (FakeImapServer end-to-end → DB → process_document)

### Session 5 (Phase C)

13. Lock file (flock POSIX)
14. launchd plist Mac Mini cabinet
15. Smoke test contre vrai serveur Infomaniak (compte test)
16. Documentation onboarding cabinet (IMAP_HOST, generation app password
    Infomaniak, etc.)

---

## 5. TESTS

### email_parser (~10 tests, all offline)

| Test | Setup | Vérifie |
|---|---|---|
| `test_parse_simple_text_email` | raw bytes plaintext | message_id, from, subject, body_excerpt, 0 attachments |
| `test_parse_multipart_alternative` | text + html | body_excerpt depuis text/plain, 0 attachments |
| `test_parse_with_pdf_attachment` | multipart/mixed avec 1 PDF | 1 ParsedAttachment, sha256, content_type, raw_bytes |
| `test_parse_multiple_attachments` | 2 PDFs + 1 PNG | 3 attachments, ordre préservé |
| `test_parse_nested_multipart_related` | PDF nichée dans related | walk recursive trouve la PJ |
| `test_parse_filename_rfc2047_utf8` | filename=`=?utf-8?B?Zm9v?=` | filename décodé correctement |
| `test_parse_subject_rfc2047_iso` | subject ISO-8859-1 encoded | subject décodé |
| `test_parse_pgp_encrypted` | content-type multipart/encrypted | encryption_status='pgp', 0 attachments |
| `test_parse_smime_encrypted` | content-type application/pkcs7-mime | encryption_status='smime' |
| `test_parse_missing_message_id` | header absent | message_id synthétique stable (hash) |
| `test_parse_body_excerpt_truncation` | body 500 chars | excerpt 200 chars |
| `test_parse_malformed_returns_best_effort` | bytes incomplets | ParsedEmail avec champs null, pas de raise |

### imap_client (~8 tests, FakeImapServer)

| Test | Setup | Vérifie |
|---|---|---|
| `test_connect_login_success` | FakeImap accepte creds | pas de raise |
| `test_connect_login_fail_raises` | FakeImap reject | raise ImapAuthError |
| `test_select_folder_returns_uidvalidity` | FakeImap select INBOX | (uidvalidity, exists) |
| `test_fetch_uids_above_filters` | FakeImap with UIDs 1..10 | fetch_uids_above(5) returns [6,7,8,9,10] |
| `test_fetch_message_returns_bytes` | FakeImap fixed payload | bytes correspond |
| `test_close_calls_logout` | FakeImap | LOGOUT called once |
| `test_factory_injection` | custom factory | utilise le factory passé |
| `test_retry_exp_backoff_on_network_error` | factory raise puis succeed | retry 3× max, succès au 2e |

### secrets.get_imap_credentials (~5 tests)

| Test | Setup | Vérifie |
|---|---|---|
| `test_keyring_first_priority` | keyring + env present | retourne keyring |
| `test_env_fallback` | only env | retourne env |
| `test_raises_when_missing_password` | rien | raise RuntimeError clair |
| `test_per_cabinet_namespacing` | 2 cabinets | clés distinctes |
| `test_imap_host_port_user_password_all_loaded` | tous champs | ImapCredentials dataclass complet |

---

## 6. CRITÈRES DE DONE (Phase A — session 3)

- [ ] Spec écrite (ce fichier)
- [ ] Schéma SQL ajouté dans `db.SCHEMA`, idempotent, init_schema OK
- [ ] `email_parser.py` livré, 10+ tests verts
- [ ] `imap_client.py` livré, 8+ tests verts avec FakeImap
- [ ] `secrets.get_imap_credentials` livré, 5+ tests verts
- [ ] Zéro régression sur les 89 tests existants
- [ ] Commit + push sur `feature/sprint-0a-core`
- [ ] Handoff session 3 doc

### Phase B (session 4)
- [ ] `imap_fetch.py` orchestrator livré
- [ ] CLI script `worker/scripts/imap_fetch.py`
- [ ] Integration tests Phase A+B end-to-end avec FakeImap → DB
- [ ] Documentation usage CLI dans le handoff session 4

### Phase C (session 5)
- [ ] Lock file POSIX
- [ ] launchd plist Mac Mini
- [ ] Smoke test serveur réel cabinet pilote
- [ ] Guide onboarding cabinet (génération app password Infomaniak)

---

## 7. POST-LIVRAISON — INTÉGRATION CABINET PILOTE

Une fois phase B livrée (session 4), séquence côté Tanguy / cabinet :

1. Le cabinet active une boîte dédiée `factures@cabinet-jura.ch` (déjà
   existante en pratique).
2. Cabinet génère un "app password" depuis le panel Infomaniak (3 clics,
   ~2 min). Transmis chiffré (Signal / sealed envelope).
3. Tanguy stocke en Keychain Mac Mini cabinet :
   ```bash
   python -c "import keyring; keyring.set_password('fiduciaire',
     'imap-pilote-jura-01-password', '<app-pwd>')"
   ```
4. `config/clients/pilote-jura-01.yaml` : ajouter `imap: {host, port,
   user, folder: INBOX}`.
5. Smoke test : `python worker/scripts/imap_fetch.py
   --cabinet pilote-jura-01` → vérifier summary.
6. Cron via launchd : poll toutes les 5 min. Plist livré phase C.

---

## 8. POURQUOI imaplib stdlib et non imapclient / aioimaplib

- **Zéro dépendance ajoutée** : la cabinet pilote n'aime pas les
  dépendances opaques. `imaplib` est dans la stdlib depuis Python 1.6.
- **Sync polling 5 min suffit** : pas besoin d'IDLE async. Async ajoute
  complexité de test (event loop, asyncio fixtures pytest).
- **Mockabilité totale** : `imaplib.IMAP4_SSL` est une classe simple à
  remplacer par un fake dans `imap_client.__init__` via factory.
- **Trade-off** : API verbeuse (réponses sous forme de bytes/tuples,
  parsing manuel). Mitigé par la facade `ImapClient`.

Alternatives écartées :
- **imapclient** : wrapper plus propre, mais +1 dep, peu d'avantage net
  pour notre usage limité (login, select, search, fetch, logout).
- **aioimaplib** : async, overhead asyncio sans bénéfice (polling, pas
  de stream temps réel).
- **OAuth Google/Microsoft** : viole "100% local". Le cabinet n'utilise
  pas Gmail/Outlook365 ; il a son propre serveur IMAP.

---

## 9. SÉCURITÉ

- **Credentials** : jamais loggés, jamais dans le code. Keychain → `.env`
  → raise (même pattern que `get_bexio_pat`).
- **TLS obligatoire** : `IMAP4_SSL` uniquement. `IMAP4` plain refusé
  (raise au démarrage si user demande port 143).
- **App passwords** : cabinet doit générer un app password dédié à
  Fiduciaire AI (révocable depuis le panel sans toucher le mot de
  passe principal de la boîte).
- **PGP / S/MIME** : flag, ne pas tenter de déchiffrer. La clé privée
  reste chez le cabinet ; le module IMAP ne la voit jamais.
- **Body excerpt 200 chars max** : minimisation RGPD/LPD. Le corps
  complet du mail n'est jamais stocké (seul l'attachment l'est, copié
  une fois dans `data/archive/`).
- **From / Subject** : stockés pour traçabilité, mais retournés
  uniquement dans le dashboard cabinet (RLS multi-mandant).

---

## 10. RÉFÉRENCES

- PRD V2 §3.10 (IMAP reporté Sprint 0a → Sprint 1)
- Session 1 handoff §3.1 (cadrage initial)
- Session 2 handoff §4 (renvoi vers cette spec)
- `worker/src/fiduciaire_worker/secrets.py` (pattern fallback chain)
- `worker/src/fiduciaire_worker/ingest_local.py` (pattern testabilité)
- RFC 3501 (IMAP4rev1) — référence protocole
- RFC 5322 (Internet Message Format) — parsing email
- RFC 2047 (MIME header encoding) — encodage non-ASCII
