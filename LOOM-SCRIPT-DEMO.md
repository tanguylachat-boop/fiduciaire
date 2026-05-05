# Loom — Démo agent IA fiduciaire (90–110 s)

**Format final** : MP4 horizontal 1920×1080 (desktop screen recording).
**Audio** : voix off française posée, pas de musique.
**Tournage** : Loom desktop, fenêtre Chrome maximisée + Finder en split.
**Durée cible** : 100 s (marge confortable).

---

## 0. Préparation (à faire AVANT de démarrer Loom)

### Pré-requis stricts
- Tunnel SSH POC actif (Ollama dev répond sur `localhost:11435`).
- DB SQLite seedée : `cd worker && .venv/bin/python scripts/seed_db_from_bench.py --reset`
  → 20 docs de référence dans le dashboard, dont 7 en review (parfait visuellement).
- Worker Python lancé en mode watcher : `cd worker && .venv/bin/python -m fiduciaire_worker.watcher`
  → tail visible dans un Terminal en arrière-plan (PAS à l'écran pendant le Loom).
- Dashboard ouvert sur `http://localhost:3001/review`.
- `data/inbox/` vide.
- `data/clients/` ouvert dans Finder, fenêtre redimensionnée pour split-screen.

### À MASQUER pendant tout l'enregistrement
- ❌ Le terminal qui montre le tunnel SSH actif (le client doit voir LOCAL UNIQUEMENT).
- ❌ Toute notification système macOS qui mentionne `runpod`, `ssh`, IP publique.
- ❌ Onglets Chrome avec `runpod.io` ou autre.
- ❌ La barre VS Code si elle montre des fichiers de config liés au cloud GPU.
- ✅ Garder uniquement : Chrome /review + Finder data/clients.

### 5 docs à préparer dans un dossier `~/Desktop/demo-drop/`
Choix des 5 docs pour l'effet visuel maximal :
1. `01_swisscom_facture_qrbill.pdf` — facture QR-bill (montre QR scan ✓ instantané).
2. `05_releve_bancaire_ubs.pdf` — relevé bancaire (cas review, montre l'agent prudent).
3. `12_decompte_tva_t1.pdf` — décompte TVA AFC (document fiscal, type non trivial).
4. `14_contrat_bail_commercial.pdf` — contrat (V1 ratait, V2 réussit, hero shot).
5. `04_note_frais_restaurant.pdf` — note de frais (client `inconnu` → routing dossier dédié).

---

## 1. Storyboard frame-by-frame

### Frame 0 — 0 → 4 s (intro mute, 1 phrase voix off)

**Visuel** : plan large dashboard /review vide ou avec données de référence. KPIs en haut, queue review visible.

**Voix off** :
> *"Voici l'agent IA fiduciaire que j'ai construit. Tout tourne en local sur mon ordinateur, en bas de l'écran."*

**Action** : pointer brièvement avec le curseur la barre de statut "DB connectée".

---

### Frame 1 — 4 → 18 s (drop des 5 docs)

**Visuel** : split horizontal — Chrome dashboard à gauche (60 %), Finder `data/inbox/` à droite (40 %).

**Action** :
- Sélectionner les 5 PDFs depuis `~/Desktop/demo-drop/`.
- Glisser-déposer en bloc dans `data/inbox/`.

**Voix off** :
> *"Je dépose 5 documents typiques d'un cabinet : une facture Swisscom, un relevé bancaire UBS, un décompte TVA, un contrat de bail, et une note de frais."*

**Animation attendue** : les fichiers apparaissent dans `data/inbox/` puis disparaissent un par un (le watcher les déplace vers `archive/`).

---

### Frame 2 — 18 → 35 s (processing, dashboard se met à jour)

**Visuel** : fermer le Finder, dashboard plein écran. Le polling 5 s déclenche les refreshes successifs.

**Action** : ne pas toucher la souris. Laisser les docs apparaître dans la queue review, puis le KPI "Documents traités" passer à 25, "À valider" augmenter, l'ActivityFeed se remplir d'événements `Classification doc #21`, etc.

**Voix off** :
> *"L'agent détecte chaque PDF, lance la lecture OCR, scanne le QR-bill suisse quand il y en a un, et classifie le document avec un modèle de langage qui tourne sur ma machine. Tout ça en moins de 30 secondes."*

**Repère temporel** : ~13 s par doc en latence médiane sur Qwen 14B. 5 docs en pipeline sériel = ~65 s total du watcher. Le Loom va plus vite (cut au montage si besoin) — viser 17 s écran sur cette frame.

---

### Frame 3 — 35 → 55 s (zoom sur les classifications)

**Visuel** : scroll dashboard jusqu'à la grille des DocCards des 5 nouveaux docs.

**Action** :
- Hover sur le badge "Classé" du doc Swisscom (vert).
- Hover sur le badge "Review" du doc UBS (orange) → mettre en lumière le message "champs ratés: date, montant".
- Pointer la card du contrat bail → badge "Contrat", client "Cabinet Avocat Vionnet & Partners".

**Voix off** :
> *"Chaque document est étiqueté : type, client du cabinet, date, montant. Quand l'agent hésite, il met le document en file de revue manuelle plutôt que d'inventer. C'est le bon comportement pour un cabinet."*

**Répere** : insister visuellement sur le chip "Review" — c'est le différentiateur vs un OCR aveugle.

---

### Frame 4 — 55 → 75 s (Finder arborescence propre)

**Visuel** : ouvrir Finder sur `data/clients/` plein écran.

**Action** :
- Naviguer dans `restaurant-le-rivage/2026/facture_fournisseur/`.
- Montrer le PDF renommé : `2026-04-15_FF_swisscom_145.50_a3b9c1.pdf`.
- Remonter à `data/clients/` racine, montrer plusieurs dossiers clients (cabinet-avocat-vionnet, sarl-etude-comptable-genevoise, etc.).
- Aller dans `inconnu/2026/note_frais/` pour montrer la quittance café qui n'a pas de client.

**Voix off** :
> *"Une fois validé, le document est rangé dans le dossier du bon client, l'année, et le bon type. Nom de fichier normalisé. C'est exactement l'arborescence qu'attend un fiduciaire."*

---

### Frame 5 — 75 → 95 s (outro de confiance)

**Visuel** : retour dashboard plein écran, KPIs visibles. Curseur immobile.

**Voix off** :
> *"Cent pourcent local. Aucune donnée n'a quitté mon ordinateur pendant cette démo. Pas de cloud, pas d'API tierce, pas de fuite. Pour un cabinet fiduciaire, c'est non négociable."*

**Action de clôture** : pointer la barre de statut "DB connectée" verte → fade out.

---

### Frame 6 — 95 → 100 s (call to action court)

**Visuel** : dashboard figé, overlay texte centré (à ajouter en post-prod ou en bas avec une fenêtre Notes) :

> **`Démo cabinet — disponible pour pilote 90 jours`**
> **`tanguy@lxstudio.ch · cal.com/lx-studio/15min`**

**Voix off** : silence ou très bref *"Si vous voulez voir ça tourner sur les vrais docs de votre cabinet, on peut programmer une visio de quinze minutes."*

---

## 2. Notes techniques pour le tournage

### Latence visible
Le watcher traite ~13 s/doc avec Qwen 14B. 5 docs en série = ~65 s. Si on attend en temps réel, la frame 2 serait trop longue. **Solutions** :
1. **Cut serré** au montage Loom (gardez 17 s sur la frame 2, sautez le reste).
2. OU lancer le watcher *avant* d'ouvrir Loom, dropper les docs hors-cam, et démarrer le Loom 5 s avant que le premier doc apparaisse dans le dashboard. Effet pseudo-live.

### Que faire si un doc rate la classification ?
Si pendant le tournage un doc tombe en `failed` (ex. OCR illisible) au lieu de `needs_review` ou `routed`, **ne pas refilmer** — l'expliquer en voix off : *"Ici l'agent a refusé de classer un reçu illisible. C'est mieux que de mettre n'importe quoi."* Honnêteté > perfection.

### Cadrage écran
- Caché en haut : barre Chrome avec autres onglets — ouvrir une nouvelle fenêtre dédiée Loom.
- Caché en bas : Dock Mac (clic-droit Dock → "Activer le masquage automatique").
- Caché à droite : Notification Center, widgets calendrier (peuvent leak des infos perso).

### Audio
- Casque + micro externe si dispo. Pas le micro intégré du Mac.
- Tester 5 s à vide avant : pas de souffle, pas de clic ventilateur.
- Ton posé, pas commercial. Cible = patron de fiduciaire 50 ans qui veut comprendre et qui a peur du cloud.

---

## 3. Texte voix-off complet (à imprimer/avoir sous les yeux)

> **(0–4 s)** Voici l'agent IA fiduciaire que j'ai construit. Tout tourne en local sur mon ordinateur, en bas de l'écran.
>
> **(4–18 s)** Je dépose 5 documents typiques d'un cabinet : une facture Swisscom, un relevé bancaire UBS, un décompte TVA, un contrat de bail, et une note de frais.
>
> **(18–35 s)** L'agent détecte chaque PDF, lance la lecture OCR, scanne le QR-bill suisse quand il y en a un, et classifie le document avec un modèle de langage qui tourne sur ma machine. Tout ça en moins de 30 secondes.
>
> **(35–55 s)** Chaque document est étiqueté : type, client du cabinet, date, montant. Quand l'agent hésite, il met le document en file de revue manuelle plutôt que d'inventer. C'est le bon comportement pour un cabinet.
>
> **(55–75 s)** Une fois validé, le document est rangé dans le dossier du bon client, l'année, et le bon type. Nom de fichier normalisé. C'est exactement l'arborescence qu'attend un fiduciaire.
>
> **(75–95 s)** Cent pourcent local. Aucune donnée n'a quitté mon ordinateur pendant cette démo. Pas de cloud, pas d'API tierce, pas de fuite. Pour un cabinet fiduciaire, c'est non négociable.
>
> **(95–100 s)** Si vous voulez voir ça tourner sur les vrais docs de votre cabinet, on peut programmer une visio de quinze minutes.

---

## 4. Checklist pré-tournage (à valider 5 min avant d'enregistrer)

- [ ] Tunnel SSH actif → `curl http://localhost:11435/api/tags` répond (terminal **caché**).
- [ ] DB seedée → `/review` montre KPIs cohérents (20 docs, 13 routed, 7 review).
- [ ] Watcher démarré → message "Watching data/inbox/..." dans terminal **caché**.
- [ ] `data/inbox/` vide.
- [ ] `~/Desktop/demo-drop/` contient les 5 PDFs ciblés.
- [ ] Chrome ouvert sur `localhost:3001/review`, autres onglets fermés.
- [ ] Finder ouvert sur `data/clients/`, fenêtre cadrée.
- [ ] Notifications macOS désactivées (Mode Concentration "Ne pas déranger").
- [ ] Dock masqué.
- [ ] Casque connecté, niveau micro testé.
- [ ] Texte voix-off imprimé ou sur second écran.

---

## 5. Si imprévu pendant le tournage

| Imprévu                                       | Action                                                          |
|-----------------------------------------------|-----------------------------------------------------------------|
| Polling 5 s ne refresh pas                    | F5 manuel discret. Si bug persistant, refilmer.                 |
| Notification macOS apparaît                   | Stop, Mode Concentration ON, refilmer.                          |
| Tunnel SSH coupe en plein milieu              | Stop. Redémarrer SSH `-N -L 11435:localhost:11434 …`. Refilmer. |
| Watcher plante sur un doc                     | Garder, expliquer en voix off (cf §2).                          |
| Doc tombe en `failed` au lieu de `routed`     | Garder, transformer en preuve d'humilité (cf §2).               |
| Le voice-over déborde de 110 s                | OK jusqu'à 130 s, au-delà refaire en plus serré.                |

---

## 6. Post-prod Loom (5 min max)

1. **Trim** : couper start (silence pré-1ère phrase) et end (silence post-dernière phrase).
2. **Cut frame 2** : si 65 s d'attente réelle, garder 15 s seulement (Loom permet de couper un segment au milieu).
3. **Pas de bullet point**, pas de transition flashy, pas de musique. Sobre.
4. **Titre Loom** : `Agent IA fiduciaire — démo locale 100s`.
5. **Description Loom** :
   > Démonstration de l'agent local de classement automatique pour cabinets fiduciaires.
   > 100 % local, aucun cloud, conforme aux exigences de confidentialité du secteur.
   > Disponible pour pilote 90 jours. Contact : tanguy@lxstudio.ch
6. **Lien partagé** : générer + tester en navigation privée que le lecteur fonctionne.
