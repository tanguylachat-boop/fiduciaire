# Décision — Gravosig pilot : seed script dédié pour install J-1

**Date :** 2026-05-16
**Statut :** Actée Sprint 2 Session 12. Script seed livré.
**Voir aussi :** `worker/scripts/seed_gravosig_pilot.py`,
`docs/decisions/2026-05-16-cabinet-provisioning.md` (script générique).

## Contexte

Tanguy se déplace chez la femme Gravosig la semaine du 19 mai 2026 pour
installer le Mac Mini M4 Pro. 4h sur place : pas le moment de taper des
commandes longues ou de débugger un provisioning à la main.

Le cabinet utilise :
- **Winbiz** pour SA propre compta (cabinet fiduciaire)
- **Bexio** pour les comptas de ses clients PME sous-jacents (3 mandants
  identifiés à l'avance, à renommer sur place avec les vrais noms)

## Décision

**Un script `seed_gravosig_pilot.py`** appelle `provision_cabinet` avec
les paramètres pré-remplis Gravosig :

```bash
worker/.venv/bin/python worker/scripts/seed_gravosig_pilot.py
```

Effets :
1. Provisionne le cabinet `gravosig-fiduciaire-01` (Winbiz, Delémont, JU)
2. Crée 3 mandants placeholder : `mandant-pme-01`, `mandant-pme-02`,
   `mandant-pme-03` (tous Bexio)
3. Seed plan comptable (28 comptes KMU standards)
4. Initialise audit log
5. Affiche un récap clair + checklist install à dérouler sur place

Renommage des mandants : Tanguy sur place exécutera
`provision_cabinet.py --force --cabinet-id ... --mandants "<noms-réels>"`
quand il aura les vrais noms PME.

## Pourquoi un script dédié et pas juste appeler `provision_cabinet` ?

- **Reproductibilité** : 1 nom de commande, 0 paramètre, impossible de se
  tromper sur place.
- **Auditable** : le script vit dans le repo, on relit le seed avant install.
- **Checklist install incluse** : affiche un récap des actions Tanguy à
  faire (token Winbiz, corpus 50 docs, etc.) — pas juste du provisioning
  silencieux.
- **Pas de duplication** : appelle `provision_cabinet` (chantier 1), n'y
  duplique pas la logique.

## Idempotence

- 1ère exécution : crée tout.
- 2ème exécution : `CabinetAlreadyExistsError` ⇒ exit 4 (sans casse).
  Pour reset : `--force`.

## Critères de succès

- ✅ `seed_gravosig_pilot.py` → cabinet + 3 mandants + plan comptable en
  < 1s
- ✅ Idempotent
- ✅ Affiche la checklist install Gravosig
- ✅ Pas de secret embarqué dans le script (le PAT Bexio sera saisi
  ailleurs)

## Alternatives écartées

- **Tout dans `provision_cabinet.py` avec un flag `--gravosig`** : pollue
  le script générique. Mieux vaut un wrapper dédié.
- **Config YAML pré-remplie** : Tanguy oublierait de la commiter. Hardcodé
  dans un script = audité par git.
