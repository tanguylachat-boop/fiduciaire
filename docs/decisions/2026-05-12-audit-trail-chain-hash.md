# Décision — Audit trail immutable Sprint 1 §3.6

**Date :** 2026-05-12
**Sprint :** 1 §3.6 (Session 5)
**Statut :** Actée et livrée (16 tests verts).

## Contexte

Le PRD V2 §3.6 exige un audit trail immutable : hash chaîné append-only
sur toutes les actions critiques (validation écriture, push Bexio,
rejet). Objectif : preuve contrôle fiscal CH (rétention 10 ans), preuve
LPD (qui a fait quoi sur les données du cabinet).

## Décisions

### 1. Chain SHA-256 append-only en SQLite

**Table `audit_log` avec colonnes `prev_hash` + `current_hash` chaînées.**

Chaque event stocke :
- `prev_hash` : current_hash du précédent event du même cabinet (ou
  GENESIS pour le premier)
- `current_hash` : SHA-256 de la concaténation canonique des champs +
  prev_hash

Vérification : `verify_audit_chain(conn, cabinet_id)` recompute chaque
hash et confirme que la chain est cohérente. Détecte :
- Tampering d'un champ d'une row (current_hash recalculé ≠ stocké)
- Tampering de prev_hash (rupture de chain)
- Insertion sauvage au milieu (prev_hash ne matche pas)

**Limite assumée** : la table peut être TRUNCATE/DROP par un attaquant
avec write SQLite. Mitigation Sprint 2 : backup externe + signature
externe (TSA). Sprint 1 : on protège contre tampering "subtil" (modif
ciblée d'un champ), pas contre destruction totale.

### 2. Chains isolées par cabinet (multi-mandant strict)

**Décision : chaque `cabinet_id` a sa propre chain indépendante.**

- `_last_hash_for_cabinet(conn, cabinet_id)` cherche dans le sous-ensemble
  de ce cabinet.
- Tampering sur le cabinet A n'invalide pas la chain du cabinet B.
- Test dédié : `test_chains_isolated_per_cabinet`.

Rationale : multi-mandant first-class est non-négociable (CLAUDE.md §3).
Une chain globale ferait fuiter de l'info inter-cabinet (un cabinet
pourrait savoir si un autre a eu de l'activité juste en regardant la
densité de hashes).

### 3. Hooks intégrés silent-fallback

**Décision : hooks dans `workflow_states`, `entry_proposer`, `bexio_push`
appellent `audit_log.log_audit_event` MAIS skip silencieusement si la
table audit_log n'existe pas.**

```python
try:
    audit_log.log_audit_event(...)
except sqlite3.OperationalError:
    pass
```

Pourquoi : back-compat avec d'éventuels callers qui n'ont pas appelé
`accounting_schema.init_accounting_schema()`. Évite de casser les 234
tests existants qui pourraient être affectés par un hook obligatoire.

Auto-init dans `init_accounting_schema` : tous les callers normaux ont
la table audit_log présente.

### 4. Actions standardisées

Constantes Python exportées : `ACTION_PROPOSED`, `ACTION_VALIDATED`,
`ACTION_REJECTED`, `ACTION_REOPENED`, `ACTION_PUSHED`, `ACTION_PUSH_FAILED`.

Les hooks Sprint 1 :
- `entry_proposer.propose_entry` → `ACTION_PROPOSED` après persist
- `workflow_states.transition` → mapping state → action via
  `_AUDIT_ACTION_FOR_STATE`
- `bexio_push` → `ACTION_PUSHED` (succès live) ou `ACTION_PUSH_FAILED`

### 5. Export texte plutôt que PDF

**Décision Sprint 1 : `export_audit_text` produit un .txt structuré, pas
un PDF.**

Pourquoi : `reportlab` ou `weasyprint` = dépendance lourde. Le PDF
n'apporte rien fonctionnellement (le contrôle fiscal accepte tout
format texte signé). Sprint 2 si vraiment nécessaire :
- `weasyprint` + template HTML/CSS
- Ou export ZIP (txt + chain hash signé externe TSA)

Le format texte actuel inclut :
- Header : cabinet, période, total events, chain VALID/BROKEN
- 1 bloc par event : timestamp, user, entity, action, before/after, hash
- Footer : final chain hash

### 6. Pas de cabinet_id dans les hooks bexio_push qui échouent dry-run

Le hook bexio_push log uniquement les push **live** (success + failed
HTTP). Le dry-run n'écrit pas d'event audit — c'est une simulation, pas
une action métier réelle.

## Tests livrés (16 verts)

`test_audit_log.py` :
- init_schema idempotent, first event prev_hash=GENESIS
- chain links consecutive events, verify_chain valid après appends
- detect field tampering, detect prev_hash tampering, empty chain
- multi-mandant isolation (corruption A n'invalide pas B)
- query API : get_events_for_entity, list_events avec filtres
- hooks intégrés : workflow_states validated, entry_proposer proposed,
  bexio_push pushed
- export_audit_text crée fichier, marks BROKEN chain
- determinisme hash (mêmes inputs → mêmes hash)

## TODO Sprint 2+

- TSA externe (RFC 3161) pour signer périodiquement le final chain hash.
- Export PDF basique pour contrôle fiscal CH si demandé.
- Compaction / archivage des anciens events (>3 ans → fichier signé externe).
