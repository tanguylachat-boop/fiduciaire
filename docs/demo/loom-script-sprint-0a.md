# Scénario Loom 2 min — démo Sprint 0a

**Objectif :** prouver en 100-120 secondes le workflow *"drag-drop facture → écriture proposée → validation 1 clic"*.

**Setup avant enregistrement :**
1. Lancer le worker (s'assurer que le DB est bien peuplée) :
   ```bash
   cd /Users/tanguylachat/fiduciaire
   ./worker/.venv/bin/python worker/scripts/seed_demo_entries.py
   ```
2. Vérifier qu'il y a 6 entries proposed + 1 validated + 1 rejected dans cabinet-pilote-01.
3. Ouvrir Chrome en plein écran, fenêtre 1280×800 minimum.
4. URL : `http://localhost:3000/entries?client=cabinet-pilote-01`
5. Lancer Loom en mode *plein écran + cam visage discret en bas droite*.

---

## Plan d'enregistrement (timestamps en secondes)

### 0:00–0:08 — Hook (8s)
**Voix off** (caméra) :
> *"Voilà à quoi ressemble la validation comptable d'un cabinet fiduciaire suisse, version IA. 100 % local, zéro donnée cloud."*

**Écran :** Vue dashboard `/entries` avec 8 écritures listées. Le titre "Validation des écritures" + badges "6 proposées · 1 validée · 1 rejetée" sont bien visibles.

### 0:08–0:18 — Liste + filtres (10s)
**Voix off :**
> *"Le matin, le comptable ouvre cette page. À gauche les pièces du jour, à droite les filtres : mandant, état, confiance, montant. Je vais cliquer sur la première facture Swisscom."*

**Écran :** zoom doux sur le sélecteur "Mandant : cabinet-pilote-01 (6 en attente)". Click sur la ligne #1 (Swisscom 287 CHF, compte 6510).

### 0:18–0:35 — Vue détail 2 colonnes (17s)
**Voix off :**
> *"Vue 2 colonnes. À gauche le PDF original — c'est la facture telle quelle, intacte. À droite la proposition de l'IA : compte 6510 télécom, compte 2000 dette fournisseurs, montant CHF, code TVA TN_NORM 8.1%, libellé. Confiance compte 92 %, confiance TVA 95 %."*

**Écran :** la page détail s'affiche, PDF Swisscom à gauche, formulaire à droite. Mettre en évidence (souris) :
- Le compte débit 6510
- Le code TVA TN_NORM
- Les confidences en haut
- Le bloc "Raisonnement IA" déplié : *"Vendor history match (12 occurrences sur 6510)…"*

### 0:35–0:42 — Validation 1 clic (7s)
**Voix off :**
> *"Tout est correct, le comptable clique Valider, l'écriture passe à l'état validé."*

**Écran :** click sur le bouton vert "Valider". Toast vert "Écriture validée". Retour automatique sur la liste — la ligne a maintenant le badge vert "Validé".

### 0:42–0:60 — Correction sur une autre entry (18s)
**Voix off :**
> *"Maintenant un cas plus intéressant — la facture freelance designer. L'IA propose le compte 6900 honoraires, mais notre cabinet utilise 6800 sous-traitance pour ce type. Je clique Corriger, je change le compte, je sauve."*

**Écran :** click sur entry #6 (Druckerei imprimante 1240 CHF, confiance 62 %). Vue détail. Click "Corriger". Le formulaire devient éditable. Changer 6700 → 6700 + ajuster libellé "Matériel imprimante service IT — comptabilisé en charge". Click "Sauver et valider". Retour liste.

### 0:60–0:75 — Audit trail + filtre (15s)
**Voix off :**
> *"Toutes les corrections sont tracées : utilisateur, horodatage, ce qui a changé. Et je peux filtrer par état pour voir uniquement les écritures qui restent à valider."*

**Écran :** rouvrir une entry validée → scroller vers le bas pour montrer le tableau "Historique des transitions". Retour liste + bouger le filtre "État" sur "Proposé" → la liste réduit aux 4 entries restantes.

### 0:75–0:95 — Différenciateur (20s)
**Voix off :**
> *"Tout ça tourne 100 % sur le Mac Mini installé dans le cabinet. Aucun appel cloud. Le modèle Mistral Small 3 24B fait l'extraction en français suisse, avec votre plan comptable PME, vos fournisseurs récurrents en mémoire. Pas de fuite vers OpenAI ou Anthropic. La femme de l'utilisateur peut faire tourner ça sur un Mac Mini 32 GB qu'elle a déjà."*

**Écran :** retour à la liste pleine. Mettre en évidence le footer *"100 % local · Sprint 0a · pas de push Bexio · isolation multi-mandant stricte"*. Optionnel : alt-tab vers terminal qui montre `ollama list` avec les modèles locaux.

### 0:95–0:115 — Outro (20s)
**Voix off :**
> *"Le résultat : votre fiduciaire passe de 30 minutes de re-saisie quotidienne à 5 minutes de validation. Pas de remplacement du comptable — l'humain garde la main sur chaque écriture. Pour une démo en conditions réelles dans votre cabinet, écris-moi : tanguy@lxstudio.ch."*

**Écran :** retour vue d'ensemble, le badge Sprint 0a visible. Coupe outro avec carte de contact email + mention "100 % local · LPD compliant".

---

## Total

100-120 secondes. Cible Loom : 1:50 à 2:00.

## Asset final attendu

Lien Loom partagé dans `docs/progress/2026-05-09-sprint-0a-complete.md` (section livrables).

## Backup en cas d'échec d'enregistrement

Si Loom n'est pas dispo le jour J :
- Capture vidéo macOS native (Cmd+Shift+5) → MP4 dans `docs/demo/loom-sprint-0a.mp4`.
- Alternative : 6 captures écran timeline + voix off PDF (moins impact mais utilisable).
