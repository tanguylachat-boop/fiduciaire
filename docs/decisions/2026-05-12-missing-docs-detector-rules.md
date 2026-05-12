# Décision — Missing docs detector : 3 règles Sprint 1 §3.7

**Date :** 2026-05-12
**Sprint :** 1 §3.7 (Session 6)
**Statut :** Actée et livrée (13 tests verts).

## Contexte

Le brief Session 6 §3.7 demande 5 règles de détection. Sprint 1 livre
3 règles **solides et utiles immédiatement**. Les 2 autres nécessitent
des prérequis (CAMT.053 §3.9 pas encore livré, règles métier cabinet
non finalisées).

## Décision

### Règles livrées Sprint 1 (3)

| # | Type | Détection | Sévérité défaut |
|---|---|---|---|
| 1 | `vat_no_evidence` | Entry avec TVA déclarée mais doc associé sans archive_path | WARNING |
| 2 | `potential_duplicate` | Même montant + dates ±5j (fenêtre configurable) | WARNING |
| 3 | `unpaid_invoice` | Entry > 60j sans bexio_id (proxy "non payée") | WARNING |

### Règles reportées Sprint 2 (2)

| # | Type | Pourquoi reporté |
|---|---|---|
| 4 | `payment_without_invoice` | Nécessite **§3.9 CAMT.053** : sans relevé bancaire parsé, on ne sait pas distinguer paiement de facture inconnue d'une opération non comptable |
| 5 | `orphan_credit_note` | Règles métier cabinet non finalisées : la définition d'"avoir orphelin" varie par cabinet (compte 1095 vs 1100 vs custom). À cadrer avec cabinet pilote post-install |

### Table `anomalies`

```sql
CREATE TABLE anomalies (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    cabinet_id TEXT NOT NULL,
    client_id TEXT NOT NULL,
    type TEXT NOT NULL,
    severity TEXT NOT NULL DEFAULT 'warning',  -- info | warning | error
    state TEXT NOT NULL DEFAULT 'open',         -- open | resolved | false_positive
    subject_entity_type TEXT NOT NULL,
    subject_entity_id TEXT NOT NULL,
    details_json TEXT,
    detected_at TEXT NOT NULL,
    resolved_at TEXT,
    resolved_by TEXT,
    resolution_reason TEXT,
    UNIQUE (cabinet_id, client_id, type, subject_entity_id)
);
```

**Idempotence** via UNIQUE constraint sur `(cabinet_id, client_id, type, subject_entity_id)`.

Re-scan ne crée pas de doublons : `INSERT OR IGNORE`. Si l'anomalie a
été marquée résolue puis re-détectée, elle reste résolue (état terminal
par défaut). Pour ré-ouvrir : opération manuelle Sprint 2.

### Workflow

- **resolved** : humain corrige le problème (ajoute le justificatif,
  paie la facture, etc.) → `mark_anomaly_resolved(conn, id, user_id, reason)`
- **false_positive** : règle a flaggé à tort → `mark_anomaly_false_positive`
- **open** : par défaut, non-résolue

### Multi-mandant strict

Chaque appel à `scan_anomalies(cabinet_id=...)` filtre par cabinet_id.
Tests dédiés (`test_multi_mandant_isolation`).

## Choix techniques pragmatiques

### 1. `vat_no_evidence` : LEFT JOIN sur documents.archive_path

Le schéma a `source_document_id INTEGER NOT NULL FK` — on ne peut pas
avoir une entry sans doc. La règle vérifie donc que le doc associé a
un `archive_path` non-NULL non-vide. Sentinel = document "placeholder"
créé en cas d'ingestion partielle ou de fichier supprimé.

### 2. `potential_duplicate` : group on amount + description

Limitation : si `description` est chiffrée (§3.4-bis), les tokens
Fernet diffèrent pour le même contenu (nonce). Le grouping sous-détecte.

Mitigation Sprint 1 : on groupe quand même sur `(amount_chf, description)`
tels que stockés. Tests passent car `conftest.py` désactive l'encryption
en tests.

Mitigation Sprint 2 : decrypt avant scan OU stocker un hash déterministe
de description en colonne shadow (`description_hash`).

### 3. `unpaid_invoice` : proxy bexio_id NULL

Sans CAMT.053, on ne peut pas confirmer un paiement bancaire. On utilise
comme proxy : entry > 60j sans bexio_id (= pas encore exportée vers
Bexio = probablement pas payée).

Faux positif : entries gérées localement sans Bexio. Mitigation : laisser
le cabinet `mark_anomaly_false_positive` pour ces cas.

Vrai signal Sprint 2 : matching CAMT.053 → flag si pas de match bancaire
après 60j.

## API livrée

```python
def scan_anomalies(*, cabinet_id, conn, client_id=None, rules=None) -> ScanReport
def mark_anomaly_resolved(conn, anomaly_id, user_id=None, reason=None)
def mark_anomaly_false_positive(conn, anomaly_id, user_id=None, reason=None)
def list_open_anomalies(conn, cabinet_id, client_id=None, severity=None) -> list[Anomaly]
def init_anomalies_schema(conn)  # idempotent
```

CLI : `worker/scripts/scan_anomalies.py --client-id pilote-jura-01`

## Tests livrés (13 verts)

`test_missing_docs_detector.py` :
- init_schema idempotent
- vat_no_evidence détecte placeholder (archive_path='')
- vat_no_evidence skip EXO
- potential_duplicate détecté in window
- potential_duplicate skip outside window
- unpaid_invoice détecté > 60j
- unpaid_invoice skip recent
- unpaid_invoice skip si bexio_id présent
- scan idempotent (re-run = 0 nouveaux)
- multi-mandant isolation
- mark_resolved
- mark_false_positive
- ScanReport shape

## TODO Sprint 2+

- §3.9 CAMT.053 → activer `payment_without_invoice`
- Définir `orphan_credit_note` avec cabinet pilote
- Hash déterministe sur description pour potential_duplicate avec encryption
- Re-open d'anomalies marquées résolues (workflow Sprint 2)
- Dashboard `/anomalies` (Sprint 7) pour resolve/false_positive en UI
- Sévérité auto-détection (montant > 1000 CHF → ERROR)
