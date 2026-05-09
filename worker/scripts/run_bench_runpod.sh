#!/usr/bin/env bash
# Bench Mistral Small 3 24B vs Llama 3.3 70B sur le corpus pilote (50 docs).
# Exécution sur un pod RunPod (A100 80GB ou H100, ~2-3 USD/h).
#
# Pré-requis (côté local) :
#   1. Pod RunPod lancé manuellement : https://www.runpod.io/console/pods → Deploy → A100 80GB → SSH access
#   2. Récupérer l'IP/port SSH : `ssh root@<ip> -p <port>`
#
# Étapes (à exécuter UNE PAR UNE sur le pod après SSH) :
#   bash worker/scripts/run_bench_runpod.sh

set -euo pipefail

REPO_URL="${REPO_URL:-https://github.com/tanguylachat-boop/fiduciaire.git}"
WORKDIR="${WORKDIR:-/workspace/fiduciaire}"
MISTRAL_MODEL="mistral-small:24b-instruct-2501-q4_K_M"
LLAMA_MODEL="llama3.3:70b-instruct-q4_K_M"
CLIENT_ID="cabinet-pilote-01"

echo "=== [1/6] Install Ollama ==="
if ! command -v ollama &>/dev/null; then
    curl -fsSL https://ollama.com/install.sh | sh
fi
# Démarre Ollama serveur en background
nohup ollama serve > /tmp/ollama.log 2>&1 &
sleep 5

echo "=== [2/6] Pull modèles ==="
ollama pull "$MISTRAL_MODEL"
ollama pull "$LLAMA_MODEL"

echo "=== [3/6] Clone repo + install worker ==="
if [ ! -d "$WORKDIR" ]; then
    git clone "$REPO_URL" "$WORKDIR"
fi
cd "$WORKDIR/worker"
git checkout feature/sprint-0a-core
python3 -m venv .venv
source .venv/bin/activate
pip install -e .

echo "=== [4/6] Préparer corpus + DB ==="
# Pré-requis : data/samples/ + data/samples/entry_labels.csv déjà transférés via SCP avant SSH.
# Si absent, le bench échouera avec un message clair.
if [ ! -d "$WORKDIR/data/samples" ]; then
    echo "ERREUR: $WORKDIR/data/samples manquant — transfère via:"
    echo "  scp -P <port> -r data/samples root@<ip>:$WORKDIR/data/"
    exit 1
fi

# Pipeline POC sur les samples si DB vide
if [ ! -f "$WORKDIR/data/fiduciaire.sqlite" ]; then
    echo "→ Lancement pipeline POC pour alimenter table documents..."
    cd "$WORKDIR"
    cp -r data/samples/* data/inbox/ 2>/dev/null || true
    timeout 600 python -m fiduciaire_worker --once || true
    cd "$WORKDIR/worker"
fi

# Seed vendor_account_history synthétique si Bexio non accessible
if [ -f scripts/seed_synthetic_vendor_history.py ]; then
    python scripts/seed_synthetic_vendor_history.py
else
    echo "(seed_synthetic_vendor_history.py absent — on démarre sans cache fournisseur)"
fi

echo "=== [5/6] Bench Mistral Small 3 ==="
python scripts/entry_bench.py \
    --model "$MISTRAL_MODEL" \
    --client-id "$CLIENT_ID" \
    --truth "$WORKDIR/data/samples/entry_labels.csv" \
    --out "$WORKDIR/data/bench-results/mistral-$(date +%Y%m%d-%H%M%S).json"

echo "=== [6/6] Bench Llama 3.3 70B ==="
python scripts/entry_bench.py \
    --model "$LLAMA_MODEL" \
    --client-id "$CLIENT_ID" \
    --truth "$WORKDIR/data/samples/entry_labels.csv" \
    --out "$WORKDIR/data/bench-results/llama-$(date +%Y%m%d-%H%M%S).json"

echo ""
echo "=== Bench terminé ==="
echo "Récupère les rapports via SCP :"
echo "  scp -P <port> root@<ip>:$WORKDIR/data/bench-results/*.json ./data/bench-results/"
echo ""
echo "Puis génère le rapport comparatif :"
echo "  python worker/scripts/render_bench_report.py \\"
echo "    --mistral data/bench-results/mistral-*.json \\"
echo "    --llama data/bench-results/llama-*.json \\"
echo "    --out docs/bench/2026-05-mistral-vs-llama.md"
