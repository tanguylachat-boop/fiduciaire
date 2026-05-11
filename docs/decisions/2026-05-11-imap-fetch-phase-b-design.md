# Décision — imap_fetch Phase B : orchestrator design

**Date :** 2026-05-11
**Sprint :** 1 §3.1 Phase B (Session 4)
**Statut :** Actée et livrée (21 tests verts).

## Contexte

Phase A (session 3) a livré email_parser + imap_client + secrets + schéma SQL,
sans orchestrateur. Phase B doit wirer le tout end-to-end : poll IMAP →
parse → dedup → save attachments → pipeline → fetch_state update.

## Décisions

### 1. API fonctionnelle vs classe

**Choix : fonction `fetch_emails(**kwargs)` + dataclasses.**

- Pas de classe `ImapFetcher` avec state — la connexion IMAP est ouverte
  et fermée à chaque appel (poll 5 min, pas de pool).
- Tous les arguments passés explicitement (kwargs-only via `*`). Facilite
  testabilité + lisibilité côté CLI.
- Le state minimal nécessaire (last_uid_seen, uidvalidity) vit en DB
  (`email_fetch_state`), pas en mémoire.

### 2. Dry-run = pure preview, zéro side-effect

**Décision : `dry_run=True` n'écrit AUCUNE ligne DB, ne marque AUCUN message
SEEN, ne lance AUCUN pipeline.**

Rationale : le dry-run est utilisé pour audit cabinet — "qu'est-ce que tu
prendrais si je te laissais courir maintenant ?". Si on persiste les
email_messages metadata, le dry-run pollue le state. Le summary +
`by_message` list suffisent pour l'audit.

Conséquence : on calcule quand même le dedup via SELECT (pour ne pas
double-compter), mais sans INSERT. L'orchestrator passe `dry_run` à
toutes les fonctions de persistance qui no-op si True.

### 3. Filtres sender en kwargs, pas en config YAML

**Décision : `ImapFetchFilters` est un dataclass passé au runtime.**

Phase B : aucun `config/clients/<id>.yaml` n'existe encore. Plutôt que
de bloquer, on accepte les filtres en argument. Le CLI les expose via
`--sender-allow` répétable.

Session 5+ : on ajoutera la lecture YAML cabinet. Pas de breaking change
attendu (les filtres seront juste lus depuis le YAML au lieu de CLI args).

### 4. process_document injectable

**Décision : `process_document_fn` est un paramètre du orchestrator,
default = `pipeline.process_document`.**

Permet aux tests d'éviter Tesseract + Ollama (sinon le test prend 30s+
par doc). En prod, on utilise le pipeline complet.

Trade-off : 1 paramètre supplémentaire dans la signature publique. Acceptable
car le contrat est simple (signature stable depuis Sprint 0a).

### 5. Staging file naming par sha256

**Décision : `data/imap-staging/<cabinet>/<sha256>.<ext>` (pas le filename
original).**

Évite collisions si 2 attachments ont le même filename (cas réel : tous
les fournisseurs nomment leurs PDFs `facture.pdf`). Le pipeline dédupe
sur sha256 dans `data/archive/` de toute façon.

Cleanup : suppression best-effort du fichier staging après `process_document`
(le pipeline a déjà copié dans archive).

### 6. UIDVALIDITY change → full rescan + dedup Message-ID

**Décision : si serveur a rebuild la mailbox (UIDVALIDITY différent), on
re-scan TOUS les UIDs et on dédupe via `email_messages.UNIQUE(cabinet_id,
message_id)`.**

Rare (reconfiguration serveur, restauration backup), mais documenté dans
RFC 3501. Sans rescan, on raterait des emails qui ont changé d'UID.

### 7. Lock file PID-based (process_lock.py)

**Décision : lock file simple PID + timestamp, `os.kill(pid, 0)` pour
vérifier vivacité. Pas de `fcntl.flock`.**

Pourquoi : portabilité (Windows si jamais, BSD aussi), lisibilité du
state (`cat data/locks/...lock` montre le PID + ISO timestamp), pas de
concurrence haute fréquence à gérer (poll 5 min).

Politique stale lock : 
- `auto_reclaim_stale=False` par défaut → orphelin force `--force` à la CLI
- Audit trail : pas besoin (le launchd log montre déjà l'historique)

## Tests livrés

- `test_imap_fetch_integration.py` : 21 tests (dry-run, idempotence,
  multi-mandant, PGP/SMIME, oversized, unsupported, limit, mark_seen,
  UIDVALIDITY rescan, fetch_state, pipeline crash, filters dataclass)
- `test_process_lock.py` : 15 tests (acquire/release, context manager,
  PID vivant/mort, force, idempotent release, parents créés)

## Conséquences

- Le CLI `worker/scripts/imap_fetch.py` est prêt pour smoke test cabinet
  réel (Session 5 manuel)
- launchd plist + script d'install livrés dans `deploy/`
- 0 régression sur les 136 tests existants
- API stable pour Phase C : on ajoute juste le lock acquisition + plist
  template
