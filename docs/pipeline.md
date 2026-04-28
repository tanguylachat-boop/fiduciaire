# Pipeline — détail technique

```
┌────────────┐
│ data/inbox │ ← cabinet pose un PDF / image
└─────┬──────┘
      │ watchdog event (file_created)
      ▼
┌────────────────────┐
│ 1. Préparation     │  copie brute → data/archive/<hash>.<ext>
│                    │  tag SQLite : (id, filename, sha256, status=ingested)
└─────┬──────────────┘
      ▼
┌────────────────────┐
│ 2. Pré-parser      │  pdf2image @ 300 DPI → pages
│    QR-bill suisse  │  pyzbar scan QR sur chaque page
│                    │  Si payload commence par "SPC" :
│                    │  → parser Swiss Payments Code (IBAN, montant, devise,
│                    │    créancier=fournisseur, débiteur=client, référence)
│                    │  → confidence 1.0 sur ces champs
│                    │  Sinon : passe à 3.
└─────┬──────────────┘
      ▼
┌────────────────────┐
│ 3. OCR             │  Tesseract fr+deu page-par-page
│                    │  → texte concaténé + métadonnées (nb pages, langue dominante)
│                    │  ratio_text = len(text) / (w * h * dpi)
│                    │  Si ratio_text < seuil ocr_fallback (0.70 par défaut) :
│                    │  → vision fallback Qwen 2.5-VL 7B sur la page faible
└─────┬──────────────┘
      ▼
┌────────────────────┐
│ 4. Classification  │  prompt classify_v1.txt + KNOWN_CLIENTS de config.yaml
│                    │  Si QR-bill parsé : seul le champ "type" reste à remplir,
│                    │  les autres champs viennent du QR.
│                    │  Sinon : tous les champs.
│                    │  appel Ollama (modèle env.primary, fallback si timeout)
│                    │  parsing JSON strict (1 retry sur erreur)
│                    │  → {type, client, date, montant, *_confidence}
└─────┬──────────────┘
      │
      ├── confiance par champ ≥ seuil ?
      │       │
      │       ▼  oui
      │   ┌────────────────────┐
      │   │ 5. Renommage       │  applique naming.pattern de config.yaml
      │   │                    │  → 2024-03-12_FF_swisscom_189.50_a3f1b2.pdf
      │   └─────┬──────────────┘
      │         ▼
      │   ┌────────────────────┐
      │   │ 6. Routing         │  data/clients/<client_slug>/<année>/<type_long>/
      │   │                    │  move atomique du fichier renommé
      │   │                    │  status SQLite → routed
      │   └────────────────────┘
      │
      └──▼ non
       ┌────────────────────┐
       │ 5'. Review queue   │  copy data/needs-review/ + status SQLite → needs_review
       │                    │  payload extrait + raison (champ X sous seuil)
       │                    │  visible dans dashboard /review
       └────────────────────┘
```

## Notes Swiss QR-bill

Format payload : texte plain ASCII, séparateur `\r\n`, header `SPC` (Swiss Payments Code), version `0200` ou `0210`. Spécification : Implementation Guidelines QR-bill v2.3 (SIX / SwissBanking).

Champs utiles pour la classification :
- ligne 4 : IBAN créancier
- ligne 6 : nom créancier (= fournisseur du document)
- lignes 7-10 : adresse créancier
- ligne 19 : montant (string, peut être vide pour QR sans montant)
- ligne 20 : devise (`CHF` / `EUR`)
- ligne 21 : nom débiteur (= client du cabinet)
- ligne 28 : référence (QRR / SCOR / NON)
- ligne 30 : message / informations supplémentaires

Si QR détecté et version supportée → champs `montant`, `devise`, `fournisseur`, `client` directement remplis avec confidence 1.0. Le LLM ne sert plus qu'au champ `type` (presque toujours `facture_fournisseur` quand QR-bill, mais peut être `releve_bancaire` ou autre dans des cas marginaux).

## Schéma SQLite minimal (POC)

```sql
CREATE TABLE documents (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  sha256 TEXT UNIQUE NOT NULL,
  original_filename TEXT NOT NULL,
  archive_path TEXT NOT NULL,
  ocr_text TEXT,
  ocr_engine TEXT,
  classification_json TEXT,
  type TEXT,
  client_slug TEXT,
  doc_date TEXT,
  montant_chf REAL,
  status TEXT NOT NULL,                        -- ingested | classified | routed | needs_review | failed
  needs_review_reason TEXT,
  final_path TEXT,
  created_at TEXT NOT NULL DEFAULT (datetime('now')),
  updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE actions (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  document_id INTEGER NOT NULL REFERENCES documents(id),
  action TEXT NOT NULL,                        -- ocr | classify | rename | route | review_resolved
  payload_json TEXT,
  duration_ms INTEGER,
  ok INTEGER NOT NULL DEFAULT 1,
  error TEXT,
  created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX idx_documents_status ON documents(status);
CREATE INDEX idx_actions_document ON actions(document_id);
```

## Idempotence

Hash SHA-256 du fichier d'origine en clé d'unicité. Re-déposer le même PDF dans l'inbox = `INSERT OR IGNORE` côté SQLite, log d'action `duplicate_ignored`, fichier supprimé de l'inbox.

## Gestion d'erreur

- OCR échoué → `status=failed`, fichier déplacé dans `data/needs-review/_failed/` avec raison.
- LLM JSON invalide → 1 retry avec prompt + `"Renvoie UNIQUEMENT un JSON valide."`. Si 2e échec → `needs_review`.
- Pas de Sentry, pas de retry exponentiel : POC, on log dans SQLite + fichier `data/worker.log`.
