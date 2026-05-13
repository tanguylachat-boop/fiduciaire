# Décision — CAMT.053 parser + bank_matcher Sprint 1 §3.9

**Date :** 2026-05-13
**Sprint :** 1 §3.9 (Session 7)
**Statut :** Actée et livrée (25 tests verts : 12 parser + 13 matcher).

## Contexte

PRD V2 §3.9 demande un rapprochement bancaire automatique facture ↔
paiement. Cabinet pilote (Jura) utilise majoritairement BCJ (Banque
Cantonale du Jura), parfois UBS/PostFinance. Format imposé : CAMT.053
ISO 20022 XML.

Sprint 1 livre **parser CAMT.053 multi-banques** + **matcher 3 stratégies
priorisées** + **audit log intégré**.

## Décisions

### 1. Parser CAMT.053 namespace-agnostic

**`xml.etree.ElementTree` stdlib avec strip namespace.**

Les banques utilisent différentes versions (camt.053.001.02 → .04 → .08
→ .10). Le parser strip les namespaces via regex pour robustesse. Tests
incluent fixtures avec version .04 ET .08.

Pas de validation XSD Sprint 1 (gain marginal vs coût dépendance). Si
besoin, ajouter `lxml` + XSD officiel BCV Sprint 2.

### 2. Schéma `bank_transactions` riche pour audit

Colonnes :
- Identifiant : `id`, `cabinet_id`, `client_id`, `iban`, `bank_ref`
- Données : `value_date`, `booking_date`, `amount_chf` (signé : + crédit,
  - débit), `currency`, `credit_debit`, `description`
- Refs : `qr_reference` (QRR/SCOR), `end_to_end_id`
- Parties : `creditor_name`, `debtor_name`
- Audit : `raw_xml_blob` (Ntry XML brut tronqué 5000 chars)
- Match : `matched_document_id`, `matched_accounting_entry_id`, `matched_at`,
  `matched_by`, `match_confidence`, `match_strategy`
- Lifecycle : `imported_at`

**Idempotence** via UNIQUE `(cabinet_id, client_id, iban, value_date,
amount_chf, bank_ref)` : ré-import même fichier = 0 doublons.

### 3. IBAN PAS chiffré applicativement

Décision : ne PAS chiffrer l'IBAN dans bank_transactions (contrairement
aux 5 colonnes texte sensibles §3.4-bis).

Rationale :
- IBAN du cabinet est connu par tous les fournisseurs / clients (figure
  sur les factures qu'ils émettent et reçoivent)
- Pas de PII directe (l'IBAN seul ne révèle pas de donnée privée)
- Chiffrement casserait les filtres dashboard "factures liées à IBAN X"
- FileVault macOS couvre déjà la DB au repos (cf decision
  `2026-05-12-encryption-strategy.md`)

À reconsidérer Sprint 2 si compliance LPD renforcée demandée.

### 4. Bank matcher 3 stratégies par priorité décroissante

| # | Stratégie | Critère | Confidence |
|---|---|---|---|
| 1 | `qr_exact` | qr_reference identique entre bank_tx et documents.classification_json | 1.0 |
| 2 | `amount_date_exact` | montant ABSOLU identique + date ±3j | 0.85 |
| 3 | `fuzzy_low_conf` | montant ±2% + date ±5j | 0.65 |

**Seuil auto-apply** : 0.9 par défaut → seul `qr_exact` apply auto.
Strategies 2-3 → suggestions à valider via UI manuellement.

Trade-offs assumés :
- `amount_date_exact` 0.85 < 0.9 → suggestion plutôt qu'apply (sécurité :
  on évite les faux positifs sur factures avec montants similaires).
- Fuzzy creditor_name pas activé en strategy 3 par défaut (pas fiable
  avec chiffrement description Fernet — tokens variant).

### 5. Audit log hooks sur tout match

Chaque match (auto OU manuel) déclenche `audit_log.log_audit_event`
avec :
- `entity_type="bank_transaction"`, `entity_id=tx_id`
- `action="matched"` ou `"unlinked"`
- `after={document_id, accounting_entry_id, strategy, confidence, reason}`
- `user_id="system-auto"` (auto) ou `user_id` réel (manuel)

Silent fallback si table audit_log absente (back-compat).

### 6. API manuelle pour UI dashboard

```python
manually_link_transaction(*, transaction_id, document_id, accounting_entry_id,
                          conn, user_id, reason) -> None
unlink_transaction(*, transaction_id, conn, user_id, reason) -> None
```

Pour Sprint 1 §3.10 dashboard `/bank` (reporté Sprint 2). API prête à
être consommée par Server Actions Next.js.

## Tests livrés (25 verts)

`test_bank_camt.py` (12) :
- parse simple credit, debit négatif, multi-Ntries, XML invalide,
  Stmt manquant, Othr/Id fallback, namespaces variés
- import idempotent, multi-mandant isolation, query unmatched + only_credits

`test_bank_matcher.py` (13) :
- QR exact auto-applies, QR no-match
- amount+date in/out window, apply below threshold
- fuzzy ±2%
- multi-mandant no cross-matching
- dry-run no persist
- manually_link / unlink
- audit log hooks
- report shape

## Scripts CLI livrés

- `worker/scripts/import_camt.py` : import 1 fichier CAMT.053
- `worker/scripts/run_bank_matcher.py` : lance matcher, auto-apply
  configurable

## TODO Sprint 2+

- Validation XSD officielle CAMT.053
- Strategies fuzzy creditor_name (post amélioration encryption)
- Auto-import depuis IMAP attachment (CAMT.053 reçu par mail banque)
- Connecteur direct API banque (BCJ open banking, PostFinance API)
  pour éviter l'export manuel
- Dashboard `/bank` UI avec drag-and-drop manual link
