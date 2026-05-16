# Décision — Provisioning cabinet : script idempotent + tables `cabinets` / `mandants`

**Date :** 2026-05-16
**Statut :** Actée Sprint 2 Session 12. Pipeline livré.
**Voir aussi :** `worker/src/fiduciaire_worker/cabinet_provisioning.py`,
`worker/src/fiduciaire_worker/plan_comptable_seed.py`,
`worker/scripts/provision_cabinet.py`.

## Contexte

Install Gravosig prévue semaine du 19 mai 2026. Le jour J, Tanguy se
déplace, installe le Mac Mini M4 Pro, configure, forme en 4h. Tout doit
être préparé en amont. Aujourd'hui, créer un cabinet exige :
- Édition manuelle de `config.yaml`
- `mkdir` arborescences clients
- Init SQLite via lancement worker
- Plan comptable seedé via Bexio (qui n'est pas dispo pour la
  compta cabinet Winbiz)

C'est fragile, non reproductible, et impossible à valider en E2E.

## Décision

**Un script `provision_cabinet.py`** crée tout en 1 commande :

```bash
worker/.venv/bin/python worker/scripts/provision_cabinet.py \
  --cabinet-id gravosig-fiduciaire-01 \
  --cabinet-name "Gravosig Fiduciaire SA" \
  --ville Delémont --canton JU --lang fr \
  --mandants "mandant-pme-01,mandant-pme-02,mandant-pme-03" \
  --logiciel winbiz
```

Effets :
1. Crée `data/clients/<cabinet-id>/{inbox,archive,needs-review,validated,exports}`
2. Génère `data/clients/<cabinet-id>/config.yaml` depuis un template typé
3. Initialise toutes les tables SQLite existantes (`init_schema`,
   `init_accounting_schema`, `init_audit_schema`) si absent
4. Crée les nouvelles tables `cabinets` + `mandants` (idempotent
   `CREATE TABLE IF NOT EXISTS`)
5. Insère le cabinet + ses mandants (INSERT OR REPLACE)
6. Seed le plan comptable suisse standard (KMU-Kontenrahmen, 28 comptes
   minimum) dans la nouvelle table `chart_of_accounts`
7. Émet un event audit `cabinet_provisioned` avec
   `after={cabinet_name, mandants_count, logiciel, lang}`

## Schéma SQLite

```sql
CREATE TABLE IF NOT EXISTS cabinets (
    cabinet_id TEXT PRIMARY KEY,
    cabinet_name TEXT NOT NULL,
    ville TEXT,
    canton TEXT,
    lang TEXT NOT NULL DEFAULT 'fr',
    logiciel TEXT NOT NULL,
    config_path TEXT NOT NULL,
    provisioned_at TEXT NOT NULL DEFAULT (datetime('now')),
    provisioned_by TEXT
);

CREATE TABLE IF NOT EXISTS mandants (
    cabinet_id TEXT NOT NULL REFERENCES cabinets(cabinet_id),
    mandant_id TEXT NOT NULL,
    mandant_name TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (cabinet_id, mandant_id)
);

CREATE TABLE IF NOT EXISTS chart_of_accounts (
    client_id TEXT NOT NULL,
    account_no TEXT NOT NULL,
    name TEXT NOT NULL,
    account_type TEXT NOT NULL,  -- asset|liability|revenue|expense|equity
    source TEXT NOT NULL DEFAULT 'seed',  -- seed|bexio|winbiz|manual
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (client_id, account_no)
);

CREATE INDEX IF NOT EXISTS idx_coa_client_type
  ON chart_of_accounts(client_id, account_type);
```

## Plan comptable suisse standard (seed minimum)

Source : KMU-Kontenrahmen 2024 (norme PME suisse). 28 comptes principaux
suffisent pour bootstrap. Les autres seront ajoutés par pull Bexio
(Sprint 1 §3.1 existant) ou Winbiz (Sprint 3).

Bloc | Plage | Comptes seedés
---|---|---
Actifs liquides | 100x | 1000 Caisse, 1020 Banque, 1100 Créances clients
Actifs immobilisés | 14xx-15xx | 1400 Marchandises, 1500 Machines
TVA | 11xx-22xx | 1170 TVA déductible, 2200 TVA collectée, 2202 Décompte TVA
Capitaux étrangers | 20xx | 2000 Dettes fournisseurs, 2100 Dettes bancaires
Capitaux propres | 28xx | 2800 Capital, 2900 Réserves
Produits | 3xxx | 3000 Ventes services, 3200 Ventes marchandises
Charges | 4xxx-6xxx | 4000 Achats marchandises, 5000 Salaires, 5700 Charges sociales, 6000 Loyer, 6100 Entretien, 6200 Véhicules, 6400 Énergie, 6500 Administration, 6510 Telecom, 6600 Marketing
Hors exploitation | 8xxx | 8000 Charges hors exploitation, 8500 Impôts directs

## Idempotence

- Sans `--force` : si le cabinet existe déjà en DB ⇒ exit 4 avec message
  clair (`✗ Cabinet '<id>' existe déjà. Utiliser --force pour réécrire.`)
- Avec `--force` : `INSERT OR REPLACE` sur `cabinets` + `mandants`,
  réécriture du `config.yaml`, plan comptable non touché (on garde
  l'historique).
- Re-run sans modif : 0 effet de bord. Tests explicites.

## Audit log

Chaque provisioning live appelle `log_audit_event` :
- `entity_type = "cabinet"`
- `entity_id = <cabinet-id>`
- `action = "cabinet_provisioned"` (ou `"cabinet_re_provisioned"` si force)
- `after = {cabinet_name, ville, canton, lang, logiciel, mandants_count,
  accounts_seeded}`
- `user_id = $USER` du shell (capturé via `os.environ.get('USER')`)

Pas de leak de credentials (aucun PAT manipulé à ce stade).

## Critères de succès

- ✅ 1 commande crée tout (DB + folders + config + seed plan + audit event)
- ✅ Idempotent : re-run = 0 effet de bord
- ✅ Multi-mandant strict (chaque mandant lié au cabinet via FK)
- ✅ `--force` réécrit proprement
- ✅ Erreurs claires si inputs invalides (slug, lang, logiciel)
- ✅ Tests pytest : 6 minimum
- ⏳ Validation install Gravosig (post-session)

## Alternatives écartées

- **Template Jinja2** pour config.yaml : overkill, f-string suffit.
- **Migrations Alembic** : trop lourd pour SQLite mono-fichier. Pattern
  `_add_column_if_missing` existant suffit.
- **Plan comptable complet KMU** (200+ comptes) : pollue la DB seed.
  Les 28 comptes ci-dessus couvrent ~95% des écritures cabinet typique ;
  le reste est seedé par pull Bexio Sprint 1 §3.1 ou manuel.
