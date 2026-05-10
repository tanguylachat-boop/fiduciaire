# Session 2 — Handoff Option Z

**Date :** 2026-05-10
**Branche :** `feature/sprint-0a-core` (commit imminent)
**Statut :** module préparatoire `ingest_local_corpus.py` livré pour
débloquer le bench. Sprint 1 §3.1 IMAP reporté à session 3.

---

## 1. Contexte de la session

Bench RunPod 2026-05-10 (A100 80 GB, Llama 70B + Mistral Small 3) :
**inconclusif**.

| Modèle | Pattern observé | Latence GPU |
|---|---|---|
| Llama 3.3 70B | `debit_account=5000` partout (hallucination fallback) | 6.1s/doc |
| Mistral Small 3 24B | `SKIP` partout (refus) | 3.6s/doc |

**Diagnostic confirmé** : `worker/scripts/seed_db_from_bench.py` insère
les docs dans `data/fiduciaire.sqlite` à partir d'un CSV bench **sans
passer par le pipeline OCR/classification**. Conséquences :
- `documents.ocr_text = NULL`
- `documents.classification_json` n'a pas le champ `fournisseur`
- `entry_proposer.py:78` reçoit chaîne vide → LLM halluce ou skip

**Décision session :** prioriser un script d'ingestion local
(`ingest_local_corpus.py`) **avant** §3.1 IMAP. Rationale dans
`docs/specs/ingest-local-corpus.md` §1.

---

## 2. Modules livrés cette session

### Module préparatoire — `ingest_local_corpus.py`

| Fichier | LoC | Status |
|---|---|---|
| `docs/specs/ingest-local-corpus.md` | 248 | nouveau, spec complète |
| `worker/src/fiduciaire_worker/ingest_local.py` | 161 | nouveau (logique testable) |
| `worker/scripts/ingest_local_corpus.py` | 156 | nouveau (CLI wrapper) |
| `worker/tests/test_ingest_local_corpus.py` | 234 | nouveau, **17 tests verts** |

**Architecture :** logique extraite dans le package
(`fiduciaire_worker.ingest_local`) pour testabilité, le script CLI est
un thin wrapper qui parse argparse + appelle `ingest_corpus()`.

**API publique :**
```python
ACCEPTED_SUFFIXES = {.pdf, .png, .jpg, .jpeg, .tif, .tiff}  # = watcher

@dataclass
class IngestSummary:
    total: int
    routed: int
    needs_review: int
    failed: int
    duplicates: int
    durations_s: list[float]
    by_file: list[dict]
    @property median_duration_s -> float | None
    @property total_duration_s -> float

def iter_supported_files(directory: Path) -> list[Path]: ...
def ingest_corpus(directory, config, conn, on_progress=None) -> IngestSummary: ...
```

**Garanties :**
- `delete_inbox=False` toujours passé à `process_document` (ne supprime
  pas les samples sources)
- Si `process_document` raise sur 1 doc → catch, status=failed, continue
  (mode bench tolérant)
- Aligné `ACCEPTED_SUFFIXES` avec `watcher.ACCEPTED_SUFFIXES` via test
  `test_accepted_suffixes_match_watcher`
- Sort déterministe (alpha) pour reproductibilité bench
- 50 fichiers détectés dans `data/samples/` (vérifié en sanity check)
- Schéma `accounting_entries` initialisé en parallèle pour cohérence
  Sprint 0a

### Mise à jour decision doc

`docs/decisions/2026-05-09-mistral-small-3-as-default.md` : ajout
section "Mise à jour 2026-05-10 — bench RunPod inconclusif" qui :
- Diagnostique la cause racine (seed sans pipeline)
- Note la décision temporaire Mistral (par contrainte hardware
  pilote-01 32 GB)
- Liste la séquence post-ingest pour validation définitive

---

## 3. État actuel global

| Composant | Statut |
|---|---|
| 7 modules core Python | ✅ session 1 |
| Dashboard `/(poc)/entries` | ✅ session 1 |
| Bexio sync read-only | ✅ session 1 (27 comptes pulled, sandbox vide) |
| `secrets.py` fallback chain | ✅ session 1 (9 tests) |
| Bench Mistral vs Llama | ⏳ inconclusif → re-bench post-ingest session 3 |
| `ingest_local_corpus.py` | ✅ **livré session 2** (17 tests) |
| Loom démo 2 min | ⏳ scénario livré, enregistrement Tanguy |
| Sprint 1 §3.1 IMAP | ⏳ session 3 |
| Sprint 1 §3.2 Bexio push | ⏳ session 3 |
| Sprint 1 §3.3 multi-mandant N=3 | ⏳ session 3 |
| Sprint 1 §3.4 chiffrement at-rest | ⏳ session 3 |

**Tests totaux** : 89 Python passing (72 sessions précédentes + 17
ingest_local) + 7 TS smoke = **96 tests verts, zéro régression**.

---

## 4. Point de reprise — Session 3 Option Z

### Pré-requis avant session 3

Côté Tanguy (séquence à exécuter en autonomie, ~30 min) :

```bash
# 1. Ingestion réelle des 50 docs locaux via le pipeline complet
cd ~/fiduciaire/worker
.venv/bin/python scripts/ingest_local_corpus.py \
  --dir ../data/samples \
  --client-id pilote-jura-01 \
  --reset-db

# Attendre ~15-25 min (50 docs × ~20s pipeline OCR+classify local).
# Output attendu : 50 docs en DB, dont la majorité en needs_review
# (les 33 benchables avec entry_labels.csv) et quelques routed/failed.

# 2. Vérifier que les docs ont bien ocr_text + fournisseur
sqlite3 ~/fiduciaire/data/fiduciaire.sqlite \
  "SELECT COUNT(*) FROM documents WHERE ocr_text IS NOT NULL"
# attendu : ≥45 (max 50 - failed)

# 3. SCP DB + samples sur RunPod (réutiliser les instructions
#    docs/bench/2026-05-09-runpod-bench-instructions.md, étape "transfert")

# 4. Sur RunPod, relancer le bench
.venv/bin/python worker/scripts/entry_bench.py \
  --mistral-compare \
  --client-id pilote-jura-01

# 5. Selon résultats :
#    Mistral ≥75% / ≥80% → cocher case "Seuils validés" dans decision doc
#    Mistral < seuils    → demander à Claude d'ouvrir
#                          docs/decisions/2026-05-XX-llama-70b-required.md
```

### Démarrage de session 3

1. `git pull origin feature/sprint-0a-core`
2. Lis ce fichier (`2026-05-10-session2-handoff.md`)
3. Lis `docs/decisions/2026-05-09-mistral-small-3-as-default.md` mise à
   jour pour le statut bench
4. Si bench OK → démarre **§3.1 IMAP** + **§3.2 Bexio push** dans cet ordre
5. Si bench KO → ouvre decision doc Llama 70B required + revoir hardware
   stratégie avant tout code Sprint 1

### Modules cibles Session 3 (pré-requis bench OK)

| Module | Effort estimé | Bloquant |
|---|---|---|
| §3.1 `email_imap.py` | 1.5j (TLS, polling, mocks aiosmtpd) | non |
| §3.2 `bexio_push.py` | 0.5j (réutilise client v3.0, dry-run + retry) | non |
| §3.3 multi-mandant N=3 | 1j (config/clients/, tests isolation cross-tenant) | non |
| §3.4 `encryption_at_rest.py` | 1j (SQLCipher + age + Keychain) | non |

Tous reportés Session 4+ : §3.5 Backup, §3.6 Audit trail immutable,
§3.7 Missing docs detector, §3.8 Outreach, §3.9 Deadlines calendar,
§3.10 Dashboard extensions.

---

## 5. Décisions techniques prises Session 2

1. **Logique testable extraite du script CLI dans le package**
   (`fiduciaire_worker.ingest_local`). Pattern différent de
   `seed_db_from_bench.py` qui est tout-en-un dans le script. Justifié :
   l'ingest_local sera réutilisé par le module IMAP en Session 3 (chaque
   pièce jointe download → `ingest_corpus` ou direct
   `process_document`).
2. **`client_id` non persisté sur la table `documents`** en Sprint 0a.
   Logged dans summary + matché par `entry_bench` via `original_filename`.
   Sera ajouté en Sprint 1 §3.3 multi-mandant.
3. **Mode bench tolérant** : si `process_document` raise sur 1 doc, on
   catch, on marque failed, on continue. Garantit que 1 doc corrompu ne
   bloque pas le bench des 49 autres.
4. **Pas de récursion sous-dossiers** : `data/samples/` est plat. Si
   besoin de structure cabinet/année plus tard, ce sera un flag explicite.

---

## 6. Issues / TODOs

- [ ] **Re-bench Mistral vs Llama post-ingest** (Tanguy, pré-session 3)
- [ ] Vérifier sur 1-2 docs réels que `classification_json` parsé par
      `entry_proposer.py` contient bien le champ `fournisseur` (sanity
      check post-ingest, avant SCP RunPod)
- [ ] Si bench KO Mistral → revoir stratégie hardware pilote-01 (Mac
      Mini 32 GB → upgrade ou pivot)
- [ ] Test end-to-end vendor history avec données Bexio réelles (post
      seed cabinet pilote, dépend session 3 §3.2)
- [ ] EXP / ACQ pas testés sur corpus réel — à valider quand 50 docs
      réels arriveront (post pilote 11 mai)

---

## 7. Pour Tanguy entre Session 2 et Session 3

**À faire (parallèle au démarrage Session 3) :**
1. Lancer l'ingest local + re-bench RunPod (séquence ci-dessus §4)
2. Enregistrer Loom 2 min : `docs/demo/loom-script-sprint-0a.md`
3. Confirmer livraison cabinet pilote 11 mai (deadline initiale Sprint 0a)

**Quand tu auras les résultats du bench post-ingest :**
- Si Mistral ≥75% / ≥80% → confirme case suivi dans decision doc, pas
  d'autre action
- Si en-dessous → ping Claude session 3 pour ouvrir decision doc
  "Llama 70B required" et revoir stratégie hardware

---

## 8. Commande de relance Session 3

```
/clear

[paste master prompt Option Z]

PUIS ajoute en fin de prompt :
"Reprends à §3.1 (email_imap.py) si bench Mistral validé, ou décision
hardware Llama 70B si bench KO. Lis
docs/progress/2026-05-10-session2-handoff.md en premier pour le contexte.
Sprint 0a finalisé + bench débloqué via ingest_local_corpus.py session 2."
```
