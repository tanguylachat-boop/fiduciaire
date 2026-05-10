# Spec — `ingest_local_corpus.py`

**Date :** 2026-05-10
**Sprint :** 1 (Session 2 Option Z) — module préparatoire
**Statut :** spec → tests → implémentation

---

## 1. Pourquoi ce module existe

### Contexte

Le bench `entry_bench.py` du 2026-05-10 (RunPod A100, Llama 70B + Mistral
Small 3) a été **inconclusif** :

- Llama 70B : hallucinations (`debit_account=5000` partout, pattern fallback).
- Mistral Small 3 : `SKIP` partout (refus de répondre faute de contexte).

### Cause racine identifiée

`worker/scripts/seed_db_from_bench.py` insère les documents dans
`data/fiduciaire.sqlite` à partir d'un CSV bench, **sans passer par le
pipeline OCR/classification**. Conséquences :

- `documents.ocr_text = NULL` → `entry_proposer.py:81` reçoit chaîne vide.
- `documents.classification_json` ne contient **pas** le champ `fournisseur`
  (seulement `client`, `type`, `date`, `montant_chf`).
- → `entry_proposer.py:78` ne trouve aucun fournisseur → bypass vendor
  history → LLM appelé avec OCR vide → halluce ou skip.

### Décision

Construire `ingest_local_corpus.py` qui passe **réellement** un dossier
local (`data/samples/`) à travers le pipeline complet `prepare → qrbill
→ ocr → classify → route|review`, populant ainsi `documents.ocr_text`
et `documents.classification_json` correctement. Le bench peut alors
être relancé sur des inputs valides.

### Pourquoi pas IMAP en premier (PRD §3.1 Sprint 1)

- Le bench est le **gate de validation** de la décision « Mistral as
  default » (`docs/decisions/2026-05-09-mistral-small-3-as-default.md`).
  Tant qu'il est rouge, tout Sprint 1 repose sur une hypothèse non
  validée.
- IMAP (~1-2 jours : TLS, polling, dedup, mocks) wrappe le même
  pipeline `process_document`. Mieux vaut valider le pipeline sur 30
  docs locaux **avant** de l'exposer à un flux email.
- `ingest_local_corpus.py` est un thin wrapper (~100 LoC) sur l'existant.

---

## 2. USER ACTION MAP

### ACTION : ingérer le corpus de bench depuis ligne de commande

**TRIGGER :** Tanguy lance
`python worker/scripts/ingest_local_corpus.py --dir data/samples --client-id pilote-jura-01 --reset-db`

**FRONTEND :** sortie console structurée
- Header : `INGEST corpus dir=… client_id=… db=…`
- Pour chaque fichier : `[k/n] filename → status=routed|needs_review|failed|duplicate dur=2.3s`
- Footer summary :
  ```
  ─── SUMMARY ───
  Total            : 50
  Routed           : 12
  Needs review     : 31
  Failed           : 2
  Duplicates       : 5
  Median duration  : 2.4s
  Total duration   : 124.8s
  DB               : data/fiduciaire.sqlite (52 MB)
  ```

**API CALL :** Aucun (script local).

**BACKEND LOGIC :**
1. Parser CLI args (`argparse`) : `--dir`, `--config`, `--client-id`,
   `--db`, `--reset-db`, `--verbose`.
2. Charger `Config` via `config.load_config()`.
3. Si `--reset-db` : `Path(db).unlink(missing_ok=True)`.
4. Connecter SQLite via `db.connect()` + `db.init_schema()` +
   `accounting_schema.init_accounting_schema()`.
5. Itérer sur les fichiers du dossier triés par nom (déterminisme
   bench), filtrer par suffixes `ACCEPTED_SUFFIXES`
   (`.pdf|.png|.jpg|.jpeg|.tif|.tiff` — copié de `watcher.ACCEPTED_SUFFIXES`).
6. Pour chaque fichier : `pipeline.process_document(path, config, conn,
   delete_inbox=False)` (CRUCIAL : ne pas supprimer les samples).
7. Logger l'outcome (status, duration, review_reasons) + accumulator
   pour summary.
8. Imprimer summary final.

**EXTERNAL API :** Aucun (Ollama+Tesseract sont locaux pour le pipeline,
mais le script ingest n'a pas de dépendance directe — il appelle
`pipeline.process_document` qui les utilise).

**DB CHANGES :**
- `documents` : 1 INSERT par fichier nouveau (status `routed` ou
  `needs_review` ou `failed`), 0 INSERT pour duplicate (sha-based).
- `actions` : N rows par doc (prepare, qrbill_scan, ocr, classify,
  review|route).
- Aucune écriture sur `accounting_entries` (entry_proposer s'en charge
  via `entry_bench.py` ensuite).

**SUCCESS STATE :** summary affiché, exit code 0. Le user peut
immédiatement enchaîner avec `python worker/scripts/entry_bench.py
--mistral-compare`.

**ERROR STATES :**
| Erreur | Détection | Recovery | Sortie user |
|---|---|---|---|
| `--dir` n'existe pas | `Path.is_dir()` False | aucune | exit 2 + message clair |
| `--dir` vide ou aucun fichier supporté | `len(files) == 0` | aucune | exit 2 + message |
| Config introuvable | `load_config()` raise | aucune | propage exception, exit 1 |
| Ollama down (utile pour la classif) | `httpx.ConnectError` dans pipeline | continue les autres docs, marque `failed` | summary affiche `failed=N` + warning final |
| OCR Tesseract non installé | `ocr.run_ocr` raise | continue les autres docs, marque `failed` | idem |
| Doc corrompu | `prepare()` ou `ocr.run_ocr()` raise | catch, status=failed, log | idem |
| Permission denied sur archive_dir | `prepare()` raise OSError | propage (système non opérationnel) | exit 1 |
| `Ctrl-C` mid-loop | `KeyboardInterrupt` | flush summary partiel + exit 130 | summary "interrompu après k/n docs" |

**EDGE CASES :**
- Fichier ouvert/écrit pendant le loop : on bypass `_is_stable()` du
  watcher car les samples sont stables sur disque. On accepte le risque
  (et de toute façon c'est offline).
- 2 fichiers avec le même contenu (même sha256) : 2e passage retourne
  `STATUS_DUPLICATE`, compté dans `duplicates`.
- Fichiers cachés (`.DS_Store`) : ignorés via filtre suffixe.
- Sous-dossiers : ignorés (Path.iterdir non récursif). Documenté.
- Symlinks : suivis si pointent vers fichier supporté.
- Fichier > 100 MB : OK techniquement, mais affichage warning si
  duration > 30s (pour debug Tesseract slow).
- Doc sans QR ni texte (page scannée pure image) : pipeline déclenche
  vision fallback ; si vision désactivé ou indisponible, `failed`.
- Multi-mandant : script écrit les docs dans la même DB SQLite
  multi-mandant. `--client-id` est passé à `route_mod.route()` via le
  config… **mais** le pipeline actuel n'utilise pas `client_id` pour
  `documents` (la colonne n'existe pas dans la table). **DÉCISION :**
  on log `client_id` dans le summary mais on ne le persiste PAS sur
  `documents` (ce sera Sprint 1 §3.3 multi-mandant). Pour le bench,
  `entry_bench.py --client-id pilote-jura-01` matche les docs par
  `original_filename ∈ entry_labels.csv` indépendamment.

---

## 3. ARCHITECTURE TECHNIQUE

### 3.1 Data flow

```
CLI args
   ↓
load_config(--config) → Config
   ↓
[optional] unlink(db_path)  ← --reset-db
   ↓
db.connect(db_path)
   ↓
db.init_schema(conn)
accounting_schema.init_accounting_schema(conn)  ← pour cohérence sprint 0a
   ↓
iter_supported_files(dir) → list[Path] trié
   ↓
for each path:
    pipeline.process_document(path, config, conn, delete_inbox=False)
        → PipelineOutcome(doc_id, status, classification, ...)
   accumulate(summary, outcome)
   ↓
print_summary(summary, db_path)
   ↓
exit 0
```

### 3.2 API contract (fonctions Python publiques)

```python
ACCEPTED_SUFFIXES = {".pdf", ".png", ".jpg", ".jpeg", ".tif", ".tiff"}

@dataclass
class IngestSummary:
    total: int
    routed: int
    needs_review: int
    failed: int
    duplicates: int
    durations_s: list[float]   # pour median calc
    by_file: list[dict]        # [{filename, status, doc_id, duration_s, reasons}]

    @property
    def median_duration_s(self) -> float | None: ...
    @property
    def total_duration_s(self) -> float: ...

def iter_supported_files(directory: Path) -> list[Path]:
    """Retourne les fichiers supportés (suffixes acceptés) du dossier,
    triés par nom. Non récursif. Ignore les fichiers cachés."""

def ingest_corpus(
    directory: Path,
    config: Config,
    conn: sqlite3.Connection,
    on_progress: Callable[[int, int, Path, PipelineOutcome], None] | None = None,
) -> IngestSummary:
    """Ingère tous les fichiers supportés du dossier via process_document.
    on_progress permet aux tests/CLI de réagir par fichier."""

def main() -> int:
    """Entry point CLI. Retourne le code de sortie."""
```

### 3.3 State machine (par doc, déjà couverte par pipeline)

```
ingested → classified → routed | needs_review | failed
                     ↘ duplicate (depuis prepare)
```

### 3.4 Error recovery matrix

| Erreur | Détection | Recovery | Output user |
|---|---|---|---|
| Doc indv erreur OCR/classif | catch dans pipeline | status=failed, continue | log warning, count failed |
| Ollama down sur 1 doc | propage depuis classify | catch au niveau script, status=failed | continue sur les suivants |
| DB locked / IO | propage SQLite | re-raise (bug système) | exit 1 |
| Aucun fichier supporté | `len([]) == 0` | aucune | exit 2 message clair |

---

## 4. IMPLEMENTATION ORDER

1. ✅ Spec (ce document)
2. Tests TDD (`worker/tests/test_ingest_local_corpus.py`)
3. Implémentation (`worker/scripts/ingest_local_corpus.py`)
4. Smoke run sur `data/samples/` (manuel)
5. Doc handoff session 2 + commit + push

---

## 5. TESTS

### Unit (mocks `pipeline.process_document`)

| Test | Setup | Vérifie |
|---|---|---|
| `test_iter_supported_files_filters` | dir avec `a.pdf`, `b.txt`, `c.PNG`, `.DS_Store`, `sub/` | retourne `[a.pdf, c.PNG]` triés |
| `test_iter_supported_files_empty_dir` | dir vide | retourne `[]` |
| `test_iter_supported_files_dir_not_exists` | dir absent | raise `NotADirectoryError` ou `FileNotFoundError` |
| `test_iter_supported_files_sorted` | dir avec b.pdf, a.pdf, c.pdf | retourne dans l'ordre alpha |
| `test_iter_supported_files_ignores_hidden` | `.hidden.pdf` | ignoré |
| `test_ingest_corpus_calls_process_document_per_file` | 3 PDFs, mock pipeline | mock appelé 3x avec delete_inbox=False |
| `test_ingest_corpus_summary_routed` | mock 3 outcomes routed | summary.routed=3, others=0 |
| `test_ingest_corpus_summary_mixed` | mock routed + needs_review + failed + duplicate | summary correct |
| `test_ingest_corpus_continues_on_doc_error` | mock raise sur le 2e | summary.failed inclut le 2e, total=3 |
| `test_ingest_corpus_durations_collected` | mock outcomes avec durations | median + total cohérents |
| `test_ingest_corpus_on_progress_callback` | callback custom | appelé N fois avec (k, n, path, outcome) |

### Smoke integration (skipif no Ollama+Tesseract)

| Test | Setup | Vérifie |
|---|---|---|
| `test_ingest_corpus_smoke_pdf_qrbill` | conftest fixture pdf_qrbill_swisscom dans tmp dir | doc en DB avec ocr_text non vide, classification_json contient `fournisseur` |

---

## 6. CRITÈRES DE DONE

- [ ] Spec écrite (ce fichier).
- [ ] 11+ tests pytest verts (10 unit + 1 smoke skip-able).
- [ ] Zéro régression sur les 72 tests Python existants.
- [ ] Sortie console claire et utilisable (vérifiable via smoke run).
- [ ] Code typé (mypy strict friendly), structlog/logging stdlib OK.
- [ ] Commit + push sur `feature/sprint-0a-core` (même branche, pas de
      nouvelle branche pour cette mini-PR).
- [ ] Handoff doc `docs/progress/2026-05-10-session2-handoff.md` mis à jour.

---

## 7. POST-LIVRAISON — RELANCE BENCH

Une fois ce script livré, séquence côté Tanguy (ou Claude si délégué) :

```bash
# 1. Reset DB locale + ingest réel
python worker/scripts/ingest_local_corpus.py \
  --dir data/samples \
  --client-id pilote-jura-01 \
  --reset-db

# 2. Vérifier que les 33 docs benchables sont en DB avec ocr_text non NULL
sqlite3 data/fiduciaire.sqlite \
  "SELECT COUNT(*) FROM documents WHERE ocr_text IS NOT NULL"
# attendu : 50 (ou 50 - failed)

# 3. SCP DB + samples sur RunPod, puis :
python worker/scripts/entry_bench.py --mistral-compare \
  --model mistral-small3:24b-instruct-q4_K_M

# 4. Décision automatique :
#    Mistral ≥75% account / ≥80% VAT → confirme decision doc
#    Mistral <70% → écrire decision doc llama-70b-required.md, revoir hardware
```
