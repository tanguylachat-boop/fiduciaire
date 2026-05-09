# Specs Sprint 0a — modules à implémenter

**Sprint :** 0a
**Deadline :** lundi 11 mai 2026 18h
**Précondition :** corpus 50 docs Jura reçu + token Bexio reçu (cf `docs/cabinet-onboarding-prereqs.md`)

Ordre d'implémentation **strict** (dépendances) :

1. `bexio_client.py` (lecture seule, PAT)
2. `vendor_account_history.py` (cache local construit depuis Bexio sync)
3. `vat_code_detector.py` (heuristique + LLM secondaire)
4. `plan_comptable_mapper.py` (charge Bexio en priorité, fallback YAML)
5. `entry_proposer.py` (orchestre 1+2+3+4)
6. Dashboard `/(poc)/entries` (consomme la table SQLite)
7. Bench script `entry_bench.py`

---

## 1. `bexio_client.py`

### Fichier
`worker/src/fiduciaire_worker/bexio_client.py`

### Responsabilité
Lire (jamais écrire) le plan comptable, les contacts, les écritures historiques d'un mandant Bexio. Cache local SQLite avec horodatage.

### API publique

```python
class BexioReadOnlyClient:
    def __init__(self, client_id: str, pat: str, base_url: str = "https://api.bexio.com/2.0"): ...
    def fetch_account_plan(self) -> list[BexioAccount]: ...
    def fetch_contacts(self) -> list[BexioContact]: ...
    def fetch_recent_manual_entries(self, limit: int = 100) -> list[BexioEntry]: ...
    def sync_to_local_cache(self, db: sqlite3.Connection) -> SyncReport: ...
```

### Tables SQLite ajoutées

```sql
CREATE TABLE IF NOT EXISTS bexio_sync (
    client_id TEXT NOT NULL,
    entity_type TEXT NOT NULL,  -- 'account' | 'contact' | 'manual_entry'
    entity_id TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    synced_at TEXT NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (client_id, entity_type, entity_id)
);

CREATE TABLE IF NOT EXISTS bexio_sync_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    client_id TEXT NOT NULL,
    started_at TEXT NOT NULL DEFAULT (datetime('now')),
    finished_at TEXT,
    accounts_count INTEGER,
    contacts_count INTEGER,
    entries_count INTEGER,
    ok INTEGER NOT NULL DEFAULT 0,
    error TEXT
);
```

### Tests requis

- `test_bexio_pat_auth_header` : vérifie que l'auth header est `Bearer <pat>`.
- `test_bexio_fetch_account_plan_parses_response` : avec une réponse JSON Bexio mockée, retourne `list[BexioAccount]` correctement parsée.
- `test_bexio_sync_idempotent` : 2 syncs successives → seconde ligne dans `bexio_sync_runs` mais pas de duplication dans `bexio_sync`.
- `test_bexio_pat_never_logged` : vérifie que le PAT n'apparaît JAMAIS dans les logs structlog (test grep sur l'output).
- `test_bexio_no_write_endpoint_called` : harness de test bloque tout call POST/PUT/DELETE → tests qui en feraient un échouent.

### Anti-pattern à bloquer
Aucune méthode `create_*`, `update_*`, `delete_*`, `post_*`. La classe est **read-only par design**.

---

## 2. `vendor_account_history.py`

### Fichier
`worker/src/fiduciaire_worker/vendor_account_history.py`

### Responsabilité
À partir des 100 dernières écritures Bexio (table `bexio_sync` entity_type=`manual_entry`), construire pour chaque fournisseur récurrent une recommandation de compte + code TVA. Plus le fournisseur est vu, plus la recommandation est confiante.

### API publique

```python
@dataclass
class VendorRecommendation:
    vendor_id: str
    vendor_name: str
    recommended_account: str
    recommended_vat_code: str
    occurrences: int
    last_seen: str  # ISO date
    confidence: float  # f(occurrences)

def build_history_from_bexio_cache(
    db: sqlite3.Connection,
    client_id: str,
) -> dict[str, VendorRecommendation]: ...

def lookup(
    db: sqlite3.Connection,
    client_id: str,
    vendor_name_or_id: str,
) -> VendorRecommendation | None: ...
```

### Tables SQLite ajoutées

```sql
CREATE TABLE IF NOT EXISTS vendor_account_history (
    client_id TEXT NOT NULL,
    vendor_id TEXT NOT NULL,
    vendor_name TEXT NOT NULL,
    account TEXT NOT NULL,
    vat_code TEXT NOT NULL,
    occurrences INTEGER NOT NULL DEFAULT 1,
    last_seen TEXT NOT NULL,
    PRIMARY KEY (client_id, vendor_id, account, vat_code)
);

CREATE INDEX IF NOT EXISTS idx_vah_lookup ON vendor_account_history(client_id, vendor_name);
```

### Confidence formula

```
confidence = min(1.0, 0.5 + 0.1 * occurrences)
# occurrences=1 → 0.6
# occurrences=2 → 0.7
# occurrences=5 → 1.0
```

Si plusieurs comptes différents pour le même fournisseur (ex. 50% sur 6510, 50% sur 6700) → retourner le plus fréquent avec confidence dégradée (`0.5 + 0.1 * (top_occurrences - second_occurrences)`).

### Tests requis

- `test_vah_single_vendor_single_account` : 5 écritures même fournisseur même compte → confidence 1.0.
- `test_vah_split_vendor_two_accounts` : 3 écritures compte A, 2 écritures compte B → recommande A avec confidence 0.6.
- `test_vah_unknown_vendor_returns_none` : vendor non vu → `None`.
- `test_vah_filtered_by_client_id` : vendor "Swisscom" présent chez client A et client B → lookup client A ne retourne pas les data de B.

---

## 3. `vat_code_detector.py`

### Fichier
`worker/src/fiduciaire_worker/vat_code_detector.py`

### Responsabilité
Détecter le code TVA suisse (`TN_NORM | TN_RED | TN_HEB | EXO | EXP | ACQ`) à partir du texte OCR + montants extraits.

### API publique

```python
@dataclass
class VatDetectionResult:
    code: str  # TN_NORM | TN_RED | TN_HEB | EXO | EXP | ACQ | UNKNOWN
    rate: float
    confidence: float
    reasoning: str

def detect_vat_code(
    text: str,
    montant_ttc: Decimal | None = None,
    montant_ht: Decimal | None = None,
    montant_tva: Decimal | None = None,
    config_path: str = "config/vat_codes_ch.yaml",
) -> VatDetectionResult: ...
```

### Stratégie

1. **Si TVA et HT connus** : calcule `rate = montant_tva / montant_ht`. Match au taux le plus proche (tolérance ±0.05%).
2. **Sinon** : keyword matching dans le texte OCR (mots-clés YAML par code).
3. **Si conflit** (taux 8.1% + keyword "hôtel") : confidence dégradée + `reasoning` explicite.
4. **Si rien** : `UNKNOWN`, confidence 0, flag review humaine.

### Tests requis

Cas obligatoires (à compléter avec corpus réel Jura) :

- `test_vat_normal_8_1_from_ratio` : HT=100 TVA=8.1 → TN_NORM confidence 1.0.
- `test_vat_reduit_2_6_from_ratio` : HT=100 TVA=2.6 → TN_RED.
- `test_vat_hebergement_from_ratio` : HT=100 TVA=3.8 → TN_HEB.
- `test_vat_keyword_hotel_no_amounts` : texte "Hôtel Bellevue, nuitée" sans montants → TN_HEB confidence 0.7.
- `test_vat_keyword_export` : texte "Lieferung ins Ausland, MwSt 0%" → EXP.
- `test_vat_ambiguous_restaurant_in_hotel` : texte mentionne "hôtel" ET "petit-déjeuner" → flag UNKNOWN si ambigu, ou TN_NORM si majoritaire restau.
- `test_vat_acquisition_google_ireland` : texte "Google Ireland Limited, no VAT charged" → ACQ confidence 0.9.

---

## 4. `plan_comptable_mapper.py`

### Fichier
`worker/src/fiduciaire_worker/plan_comptable_mapper.py`

### Responsabilité
Charger le plan comptable du cabinet en mémoire, fournir mapping mot-clé → compte, et permettre de scorer la pertinence d'un compte donné un texte.

### API publique

```python
@dataclass
class AccountSuggestion:
    account_code: str
    account_label: str
    score: float  # 0-1
    matched_keywords: list[str]

class PlanComptable:
    @classmethod
    def from_bexio_cache(cls, db: sqlite3.Connection, client_id: str) -> "PlanComptable": ...

    @classmethod
    def from_yaml_fallback(cls, yaml_path: str) -> "PlanComptable": ...

    def suggest_accounts(self, text: str, top_k: int = 3) -> list[AccountSuggestion]: ...

    def get_account(self, code: str) -> dict | None: ...
```

### Stratégie de chargement

```
1. Tenter from_bexio_cache(db, client_id).
   Si table bexio_sync vide pour ce client → fallback.
2. Fallback from_yaml_fallback("config/plan_comptable_pme_ch.yaml").
3. Logger laquelle des 2 sources a été utilisée.
```

### Stratégie suggest_accounts

Score = nombre de keywords matchés / total_keywords du compte (normalisé). Tie-breaker : préférer compte de classe `charge_exploitation` quand le texte mentionne un fournisseur, et `produit_exploitation` quand le texte mentionne un client.

### Tests requis

- `test_plan_loaded_from_bexio_cache_when_available`.
- `test_plan_falls_back_to_yaml_when_no_cache`.
- `test_suggest_accounts_swisscom_returns_6510_telecom`.
- `test_suggest_accounts_loyer_returns_6000`.
- `test_suggest_accounts_unknown_text_returns_empty`.

---

## 5. `entry_proposer.py` — CŒUR

### Fichier
`worker/src/fiduciaire_worker/entry_proposer.py`

### Responsabilité
Orchestre `vendor_account_history` + `plan_comptable_mapper` + `vat_code_detector` + LLM Ollama pour proposer une écriture comptable structurée.

### API publique

```python
@dataclass
class ProposedEntry:
    client_id: str
    source_document_id: int  # FK vers documents.id
    date: str  # ISO
    debit_account: str
    credit_account: str
    amount_chf: Decimal
    vat_code: str
    vat_amount: Decimal
    description: str
    confidence_account: float
    confidence_vat: float
    reasoning: str
    state: Literal["proposed"] = "proposed"

def propose_entry(
    db: sqlite3.Connection,
    client_id: str,
    source_document_id: int,
) -> ProposedEntry: ...
```

### Stratégie 2 niveaux

```
1. Lire le document classifié dans la table `documents` (déjà existant POC).
2. Extraire vendor_name (= fournisseur du QR-bill OU client.classification.fournisseur).
3. Niveau 1 — vendor history :
   recommendation = vendor_account_history.lookup(db, client_id, vendor_name)
   si recommendation.confidence >= 0.8 → propose direct, skip LLM.
4. Niveau 2 — LLM :
   plan = PlanComptable.from_bexio_cache(db, client_id)
   suggestions = plan.suggest_accounts(ocr_text, top_k=3)
   prompt = build_entry_prompt(doc, suggestions, vendor_history_partial=recommendation)
   réponse = call_ollama(prompt)
   parse_json_strict(réponse)
5. Détecter le vat_code via vat_code_detector.detect_vat_code(...).
6. Construire ProposedEntry.
7. Persister dans table accounting_entries.
```

### Tables SQLite ajoutées

```sql
CREATE TABLE IF NOT EXISTS accounting_entries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    client_id TEXT NOT NULL,
    source_document_id INTEGER NOT NULL REFERENCES documents(id),
    date TEXT NOT NULL,
    debit_account TEXT NOT NULL,
    credit_account TEXT NOT NULL,
    amount_chf REAL NOT NULL,
    vat_code TEXT NOT NULL,
    vat_amount REAL,
    description TEXT NOT NULL,
    confidence_account REAL NOT NULL,
    confidence_vat REAL NOT NULL,
    reasoning TEXT,
    state TEXT NOT NULL DEFAULT 'proposed',  -- proposed | validated | rejected
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS entry_state_changes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    entry_id INTEGER NOT NULL REFERENCES accounting_entries(id),
    from_state TEXT NOT NULL,
    to_state TEXT NOT NULL,
    user_id TEXT,
    reason TEXT,
    changed_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_entries_client_state ON accounting_entries(client_id, state);
```

### Tests requis

- `test_propose_entry_uses_vendor_history_when_high_confidence` : vendor connu avec 5 occurrences → skip LLM, retourne direct.
- `test_propose_entry_falls_back_to_llm_when_unknown_vendor` : vendor inconnu → call Ollama mocké → parse JSON.
- `test_propose_entry_handles_invalid_llm_json_with_retry` : 1er call retourne JSON cassé → 2e call avec prompt corrigé → si OK passe, sinon flag review.
- `test_propose_entry_filtered_by_client_id` : 2 mandants en parallèle, isolation stricte.
- `test_propose_entry_persists_to_accounting_entries`.
- `test_propose_entry_creates_state_change_log`.

---

## 6. Dashboard `/(poc)/entries`

### Fichier
`app/(poc)/entries/page.tsx`

### Composants
- `components/poc/EntryReviewCard.tsx` : card avec PDF gauche + champs éditables droite + 3 boutons.
- `components/poc/EntryFilters.tsx` : filtres (client, état, montant, confiance, date).
- `components/poc/EntriesList.tsx` : liste avec pagination.

### Lecture/écriture SQLite

- Lecture : étendre `lib/db-poc.ts` avec `listAccountingEntries(filters)` et `getAccountingEntry(id)`.
- Écriture (validation/rejet) : nouveau Server Action ou Route Handler `app/api/entries/[id]/route.ts`. Auth simple par token cabinet (Sprint 0a, à durcir Sprint 1).

### Tests requis (Playwright ou test manuel)

- Charger la liste, voir les 50 entries.
- Filtrer par état "proposed" → 50 entries.
- Cliquer "Valider" sur 1 entry → état `validated` en SQLite, ligne dans `entry_state_changes`.
- Cliquer "Corriger" → modal champs éditables → sauver → état reste `proposed` mais champs mis à jour.
- Cliquer "Rejeter" → demande raison → état `rejected` + raison loguée.

---

## 7. Bench `entry_bench.py`

### Fichier
`worker/scripts/entry_bench.py`

### Responsabilité
Comparer les propositions de `entry_proposer.py` à la vérité-terrain `ground-truth.csv` du cabinet pilote sur 50 docs.

### Métriques

```
total_docs                          int
correct_account                     int (debit_account match exact)
correct_vat_code                    int
correct_both                        int (= proposition utilisable d'un clic)
median_latency_ms_per_doc           float
p95_latency_ms_per_doc              float
docs_using_vendor_history_shortcut  int
docs_using_llm                      int
```

### Sortie

`docs/bench/2026-05-llm-comparison.md` avec tableaux comparatifs Mistral Small 3 vs Llama 3.3 70B.

---

## Définition of done Sprint 0a

- [ ] Tous les modules ci-dessus testés (≥80% coverage worker/).
- [ ] Bench exécuté sur les 2 modèles, gagnant retenu, config.yaml mis à jour.
- [ ] Dashboard `/entries` fonctionnel sur 50 entries du corpus.
- [ ] Démo Loom 2 min enregistrée et envoyée.
- [ ] PRD V2 et toutes les decision docs commités sur `main`.
