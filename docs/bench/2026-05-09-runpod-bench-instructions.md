# Bench Mistral Small 3 24B vs Llama 3.3 70B — instructions RunPod

**Date :** 2026-05-09
**Statut :** instructions prêtes, exécution en attente Tanguy.
**Cible :** valider le seuil ≥75% compte / ≥80% TVA pour confirmer Mistral Small 3 comme défaut.

---

## 1. Pourquoi RunPod et pas en local ?

- Llama 3.3 70B Q4_K_M nécessite ~42 GB RAM. Le MacBook Pro 16 GB ne suffit pas.
- RunPod A100 80 GB (~2-3 USD/h) tient les 2 modèles confortablement et finit le bench en 30-45 min.
- Coût total estimé : 1.50-2.50 USD pour le bench complet.

## 2. Setup pod (5 min)

1. Aller sur https://www.runpod.io/console/pods
2. Cliquer "Deploy" → "Pods" → choisir un template **PyTorch + CUDA**
3. Sélectionner GPU : **A100 80 GB SXM** (~2.20 USD/h) ou H100 PCIe (~3.20 USD/h)
4. Volume : 100 GB minimum (les modèles font ~14 GB Mistral + ~42 GB Llama)
5. Network: **expose SSH** (case cochée par défaut)
6. Region : EU (Pays-Bas, Italie) si possible — latence mineure mais légèrement mieux pour les pulls modèles
7. "Deploy" → attendre 1-2 min → status "Running"
8. Récupérer SSH : icône **Connect** → ligne `ssh root@<ip> -p <port> -i ~/.ssh/id_ed25519`

## 3. Transférer le corpus + ground truth (avant SSH)

Depuis ton Mac, dans le repo `/Users/tanguylachat/fiduciaire/` :

```bash
SSH_PORT=<port donné par RunPod>
SSH_IP=<ip donnée par RunPod>

# Crée le dossier cible sur le pod
ssh -p $SSH_PORT root@$SSH_IP "mkdir -p /workspace/fiduciaire-bench/data"

# Transfère le corpus + ground truth
scp -P $SSH_PORT -r data/samples \
    root@$SSH_IP:/workspace/fiduciaire-bench/data/

# (Optionnel) transfère un fiduciaire.sqlite déjà rempli si tu en as un
# scp -P $SSH_PORT data/fiduciaire.sqlite root@$SSH_IP:/workspace/fiduciaire-bench/data/
```

## 4. SSH sur le pod et lancer le bench

```bash
ssh -p $SSH_PORT root@$SSH_IP

# Sur le pod :
cd /workspace
git clone https://github.com/tanguylachat-boop/fiduciaire.git
cd fiduciaire
git checkout feature/sprint-0a-core

# Si le corpus n'est pas dans le clone (data/samples/* est gitignored normalement)
cp -r /workspace/fiduciaire-bench/data/samples ./data/

# Lance le pipeline complet (script Sprint 0a session 2)
bash worker/scripts/run_bench_runpod.sh
```

Le script enchaîne automatiquement :
1. Install Ollama (~30 sec)
2. Pull `mistral-small:24b-instruct-2501-q4_K_M` (~14 GB, ~3 min)
3. Pull `llama3.3:70b-instruct-q4_K_M` (~42 GB, ~10 min)
4. Setup venv + install worker
5. Pipeline POC sur les 50 docs (timeout 10 min, peut être skip si DB déjà fournie)
6. Bench Mistral (~5 min sur 31 docs benchables)
7. Bench Llama (~12 min sur 31 docs benchables)

Total : ~30-35 min sur A100, ~25 min sur H100.

## 5. Récupérer les résultats

Sur le pod, les rapports JSON sont dans `data/bench-results/`.

Depuis ton Mac :
```bash
SSH_PORT=<port>
SSH_IP=<ip>

mkdir -p data/bench-results
scp -P $SSH_PORT \
    "root@$SSH_IP:/workspace/fiduciaire/data/bench-results/*.json" \
    ./data/bench-results/
```

## 6. Générer le rapport comparatif

Le script `worker/scripts/render_bench_report.py` n'est pas encore livré (sera produit en Session 2 du plan Option Z). En attendant, comparaison manuelle :

```bash
cd /Users/tanguylachat/fiduciaire
.venv/bin/python -c "
import json, glob
for f in sorted(glob.glob('data/bench-results/*.json')):
    data = json.load(open(f))
    s = data[0]
    print(f\"{s['model']:>50s}  account={s['pct_account_correct']}%  vat={s['pct_vat_correct']}%  both={s['pct_both_correct']}%  median={s['median_latency_ms']}ms\")
"
```

Sortie attendue :
```
            mistral-small:24b-instruct-2501-q4_K_M  account=82.3%  vat=87.1%  both=74.2%  median=4520ms
                  llama3.3:70b-instruct-q4_K_M  account=87.5%  vat=89.3%  both=80.6%  median=14200ms
```

(chiffres illustratifs — les vrais résultats détermineront la décision)

## 7. Interprétation et décision automatique

| Mistral résultat | Action |
|---|---|
| ≥75% compte ET ≥80% TVA | ✅ Confirme `2026-05-09-mistral-small-3-as-default.md`. Standardisation 32 GB validée. |
| 70-75% compte OU 75-80% TVA | ⚠️ Étudier l'écart Mistral vs Llama. Si Llama >15 pts au-dessus → fallback Llama 64 GB hardware. Sinon, conserver Mistral. |
| <70% compte OU <75% TVA | ❌ Mistral insuffisant pour ce use case. Ouvre `2026-05-09-llama-70b-required.md` qui révise hardware (Mac Studio 64 GB obligatoire). |

## 8. Coût et arrêt du pod

⚠️ **Stop le pod IMMÉDIATEMENT après récup des JSON.** RunPod facture à la minute.

```bash
# Sur le pod : éteint Ollama
pkill ollama || true
exit
```

Puis dans le dashboard RunPod : pod → menu → **Terminate**. Cela libère le volume aussi (sinon facturation continue à ~$0.05/h).

## 9. Si le bench échoue

Causes courantes :
- **Ollama timeout** : modèle trop lent sur le doc, vérifier `--num_ctx` dans le script (défaut 4096 OK).
- **Manque de VRAM** : Llama 70B sur A100 40 GB → out of memory. Repasser sur A100 80 GB.
- **Ground truth manque** : vérifier que `data/samples/entry_labels.csv` est bien transféré.
- **Pipeline POC pas exécuté** : la table `documents` est vide donc 0 docs benchables. Réexécuter `python -m fiduciaire_worker --once` après avoir mis les samples dans `data/inbox/`.

Logs Ollama : `/tmp/ollama.log`
Logs bench : sortie console du script (pas de fichier dédié encore).

## 10. Alternative locale (Mac Studio prêté)

Si Tanguy a accès à un Mac Studio M4 Max 64 GB+ (loueur PME chez Apple Store ou prêt entrepreneur), il peut :
- Skip RunPod
- Lancer Ollama local
- Faire tourner Mistral 24B (16 GB OK) et Llama 70B Q4 (42 GB OK avec 64 GB total)
- Coût : 0 USD si machine prêtée, ~120 CHF/jour de location

Performance attendue : Mistral 24B ≈ 30-40 sec/doc, Llama 70B ≈ 60-90 sec/doc → bench complet ~1h30 sur Mac Studio.
