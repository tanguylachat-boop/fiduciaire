# worker — Pipeline POC

Watcher Python qui ingère un document, le classe via LLM local, le renomme et le déplace.

## Setup

Prérequis macOS : Python 3.12, [Ollama](https://ollama.com), Tesseract 5, libzbar.

```bash
brew install tesseract tesseract-lang zbar

cd worker
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
```

### Modèles Ollama

Sur Mac dev (MBP M4 16 GB) :

```bash
ollama pull qwen2.5:14b-instruct-q4_K_M    # primaire dev (~9 GB)
ollama pull qwen2.5:7b-instruct-q4_K_M     # fallback latence dev (~5 GB)
ollama pull qwen2.5vl:7b-q4_K_M                    # vision fallback (~5 GB)
```

Sur Mac Mini prod (M4 Pro 64 GB) — à faire au déploiement :

```bash
ollama pull llama3.3:70b-instruct-q4_K_M   # primaire prod (~42 GB)
ollama pull qwen2.5:32b-instruct-q4_K_M    # fallback latence prod (~20 GB)
ollama pull qwen2.5vl:7b-q4_K_M
```

Sélection automatique via `config.yaml` : champ `llm.env` = `"dev"` ou `"prod"`.

## Bench (Lundi)

Mesure la précision sur le corpus `../data/samples/`. Compare aux labels
ground-truth dans `samples/labels.csv`.

```bash
python scripts/bench.py --config ../config.yaml --corpus ../data/samples
```

Output : tableau précision par champ + cas d'échec.

## Lancement watcher (Mardi+)

```bash
fiduciaire-worker --config ../config.yaml
```

Dépose un PDF dans `../data/inbox/`, observe `../data/clients/` se remplir.
