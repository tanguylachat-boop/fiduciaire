"""Bench précision classification sur corpus annoté.

Pour chaque PDF dans <corpus>/ :
  1. Pré-parser QR-bill (pyzbar) si activé dans config.yaml.
  2. OCR Tesseract (langues du config) + fallback vision si extraction trop pauvre.
  3. Appel Ollama avec le prompt configuré (par défaut prompts/classify_v2_fewshot.txt).
  4. Compare au ground-truth dans <corpus>/labels.csv.

Output :
  - Tableau précision par champ (type, client, date, montant_chf).
  - Verbatim des cas ratés (filename, champ, attendu, obtenu, raisonnement LLM).
  - Latence par doc (médiane, P95).
  - CSV résultats archivé dans data/bench-results/bench-<modèle>-<timestamp>.csv.

Critère succès Jeudi 50 docs (cf DECISIONS.md 2026-04-27) :
  type ≥ 90% | client ≥ 80% | date ≥ 75% | montant ≥ 75%

Usage :
  .venv/bin/python scripts/bench.py \\
    --config ../config.yaml \\
    --corpus ../data/samples \\
    [--model qwen2.5:7b-instruct-q4_K_M]      # override config
    [--prompt-file prompts/classify_v2_fewshot.txt]
    [--limit 5]                                 # debug : 5 premiers docs
    [--no-qr]                                   # désactive QR-bill pre-parser
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
import statistics
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx
import yaml

ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = ROOT.parent

# Champs notés vs ground-truth (labels.csv).
SCORED_FIELDS = ("type", "client", "date", "montant_chf")
# Seuils succès Jeudi 50 docs (cf DECISIONS.md).
SUCCESS_THRESHOLDS = {"type": 0.90, "client": 0.80, "date": 0.75, "montant_chf": 0.75}


@dataclass
class DocResult:
    filename: str
    expected: dict[str, Any]
    obtained: dict[str, Any]
    correct: dict[str, bool] = field(default_factory=dict)
    latency_s: float = 0.0
    ocr_chars: int = 0
    qr_used: bool = False
    error: str | None = None
    raisonnement: str = ""


def load_config(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def load_labels(corpus: Path) -> dict[str, dict[str, Any]]:
    """Lit labels.csv → dict {filename: {type, client, date, montant_chf, ...}}.

    Les lignes commençant par # sont ignorées (commentaires).
    Une cellule vide → None.
    """
    labels_path = corpus / "labels.csv"
    if not labels_path.exists():
        sys.exit(f"FATAL : pas de labels.csv dans {corpus}")
    out: dict[str, dict[str, Any]] = {}
    with labels_path.open(encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            fn = (row.get("filename") or "").strip()
            if not fn or fn.startswith("#"):
                continue
            cleaned: dict[str, Any] = {}
            for k, v in row.items():
                v = (v or "").strip()
                if k == "montant_chf":
                    cleaned[k] = float(v) if v else None
                else:
                    cleaned[k] = v if v else None
            out[fn] = cleaned
    return out


def select_model_and_prompt(config: dict, model_override: str | None, prompt_override: str | None) -> tuple[str, Path]:
    env = config.get("llm", {}).get("env", "dev")
    models = config.get("llm", {}).get("models", {}).get(env, {})
    model = model_override or models.get("primary") or "qwen2.5:7b-instruct-q4_K_M"
    prompt_rel = prompt_override or config.get("llm", {}).get(
        "prompt_file", "worker/prompts/classify_v2_fewshot.txt"
    )
    prompt_path = (REPO_ROOT / prompt_rel) if not Path(prompt_rel).is_absolute() else Path(prompt_rel)
    if not prompt_path.exists():
        # fallback chemin relatif au worker
        prompt_path = ROOT / prompt_rel
    if not prompt_path.exists():
        sys.exit(f"FATAL : prompt introuvable : {prompt_rel}")
    return model, prompt_path


def pdf_or_image_to_text(path: Path, langs: list[str], dpi: int) -> tuple[str, bool]:
    """OCR Tesseract simple. Retourne (texte, qr_used=False).

    QR-bill pre-parser non implémenté ici (pyzbar) — TODO Mardi quand on
    intègre le pipeline complet. Pour le bench, on s'appuie sur OCR seul.
    Si tu vois `qr_used=True` dans les résultats, c'est qu'on aura ajouté
    la branche pyzbar plus tard.
    """
    import pytesseract
    from PIL import Image

    if path.suffix.lower() == ".pdf":
        from pdf2image import convert_from_path

        pages = convert_from_path(str(path), dpi=dpi)
        chunks = []
        for p in pages:
            chunks.append(pytesseract.image_to_string(p, lang="+".join(langs)))
        return "\n\n".join(chunks), False

    img = Image.open(path)
    return pytesseract.image_to_string(img, lang="+".join(langs)), False


def build_prompt(template: str, ocr_text: str, known_clients: list[dict]) -> str:
    return template.replace(
        "{KNOWN_CLIENTS_JSON}", json.dumps(known_clients, ensure_ascii=False, indent=2)
    ).replace("{OCR_TEXT}", ocr_text)


def call_ollama(
    model: str, prompt: str, endpoint: str, timeout_s: int, num_predict: int
) -> tuple[float, str]:
    payload = {
        "model": model,
        "prompt": prompt,
        "format": "json",
        "stream": False,
        "options": {"temperature": 0.0, "num_predict": num_predict},
    }
    t0 = time.perf_counter()
    r = httpx.post(f"{endpoint}/api/generate", json=payload, timeout=timeout_s)
    elapsed = time.perf_counter() - t0
    r.raise_for_status()
    return elapsed, r.json().get("response", "")


def normalize(value: Any, field: str) -> Any:
    if value is None:
        return None
    if field == "montant_chf":
        try:
            return round(float(value), 2)
        except (TypeError, ValueError):
            return None
    if field == "date":
        # tolère "2024-03-12T00:00:00" ou "2024-03-12"
        s = str(value).strip()
        return s[:10] if len(s) >= 10 else s
    return str(value).strip()


def fields_match(expected: Any, obtained: Any, field: str) -> bool:
    e = normalize(expected, field)
    o = normalize(obtained, field)
    if e is None and o is None:
        return True
    if e is None or o is None:
        return False
    if field == "montant_chf":
        return abs(float(e) - float(o)) < 0.01
    if field == "client":
        # match strict canonique (le prompt v2 force le canonique)
        return e.lower() == o.lower()
    return e == o


def run_one(
    pdf: Path,
    expected: dict[str, Any],
    template: str,
    known_clients: list[dict],
    config: dict,
    model: str,
) -> DocResult:
    res = DocResult(filename=pdf.name, expected=expected, obtained={})
    try:
        langs = config.get("cabinet", {}).get("langues_ocr", ["fra", "deu"])
        dpi = config.get("ocr", {}).get("dpi", 300)
        ocr_text, qr_used = pdf_or_image_to_text(pdf, langs, dpi)
        res.ocr_chars = len(ocr_text)
        res.qr_used = qr_used

        prompt = build_prompt(template, ocr_text, known_clients)
        endpoint = config.get("llm", {}).get("endpoint", "http://localhost:11434")
        timeout_s = int(config.get("llm", {}).get("timeout_s", 120))
        num_predict = int(config.get("llm", {}).get("num_predict", 512))
        elapsed, response = call_ollama(model, prompt, endpoint, timeout_s, num_predict)
        res.latency_s = elapsed

        try:
            parsed = json.loads(response)
        except json.JSONDecodeError as e:
            res.error = f"json: {e}"
            return res

        res.obtained = parsed
        res.raisonnement = str(parsed.get("raisonnement_court") or "")
        for f in SCORED_FIELDS:
            res.correct[f] = fields_match(expected.get(f), parsed.get(f), f)
    except Exception as e:
        res.error = f"{type(e).__name__}: {e}"
    return res


def print_summary(results: list[DocResult], model: str) -> dict[str, float]:
    n = len(results)
    accuracy: dict[str, float] = {}
    print(f"\n=== Précision par champ (n={n}) ===")
    for f in SCORED_FIELDS:
        ok = sum(1 for r in results if r.correct.get(f))
        acc = ok / n if n else 0.0
        accuracy[f] = acc
        threshold = SUCCESS_THRESHOLDS[f]
        marker = "✅" if acc >= threshold else "❌"
        print(f"  {f:14s} : {ok:3d}/{n:<3d}  {acc * 100:5.1f}%   (cible {threshold * 100:.0f}%)  {marker}")

    times = [r.latency_s for r in results if r.latency_s > 0]
    if times:
        median = statistics.median(times)
        p95 = (
            statistics.quantiles(times, n=20)[18] if len(times) >= 2 else max(times)
        )
        print(f"\n=== Latence ({len(times)} docs) ===")
        print(f"  médiane : {median:.2f} s")
        print(f"  P95     : {p95:.2f} s")
        print(f"  min/max : {min(times):.2f} s / {max(times):.2f} s")

    failures = [r for r in results if not all(r.correct.values()) or r.error]
    if failures:
        print(f"\n=== Cas ratés ({len(failures)}/{n}) — verbatim pour ajuster prompt ===")
        for r in failures:
            print(f"\n  📄 {r.filename}  (latence {r.latency_s:.1f}s, ocr {r.ocr_chars} chars)")
            if r.error:
                print(f"     ERREUR : {r.error}")
                continue
            for f in SCORED_FIELDS:
                if not r.correct.get(f):
                    e = r.expected.get(f)
                    o = r.obtained.get(f)
                    print(f"     [{f}] attendu={e!r:50s} obtenu={o!r}")
            if r.raisonnement:
                print(f"     LLM dit : {r.raisonnement[:240]}")

    print(f"\n=== Verdict global (modèle {model}) ===")
    all_pass = all(accuracy[f] >= SUCCESS_THRESHOLDS[f] for f in SCORED_FIELDS)
    if all_pass:
        print("  ✅ Tous les seuils Jeudi atteints — le 7B + few-shot tient sur ce corpus.")
    else:
        misses = [
            f"{f} {accuracy[f] * 100:.1f}% < {SUCCESS_THRESHOLDS[f] * 100:.0f}%"
            for f in SCORED_FIELDS
            if accuracy[f] < SUCCESS_THRESHOLDS[f]
        ]
        print(f"  ❌ Seuils manqués : {', '.join(misses)}")
        print("  → analyser cas ratés ci-dessus, itérer prompt OU basculer 14B/70B.")
    return accuracy


def write_csv(results: list[DocResult], model: str, prompt_path: Path, out_dir: Path) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    ts = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    safe_model = model.replace(":", "_").replace("/", "_")
    out = out_dir / f"bench-{safe_model}-{ts}.csv"
    with out.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(
            [
                "filename",
                "model",
                "prompt",
                "latency_s",
                "ocr_chars",
                "qr_used",
                "error",
                "exp_type",
                "got_type",
                "ok_type",
                "exp_client",
                "got_client",
                "ok_client",
                "exp_date",
                "got_date",
                "ok_date",
                "exp_montant",
                "got_montant",
                "ok_montant",
                "raisonnement",
            ]
        )
        for r in results:
            w.writerow(
                [
                    r.filename,
                    model,
                    prompt_path.name,
                    f"{r.latency_s:.2f}",
                    r.ocr_chars,
                    r.qr_used,
                    r.error or "",
                    r.expected.get("type") or "",
                    r.obtained.get("type") or "",
                    r.correct.get("type", False),
                    r.expected.get("client") or "",
                    r.obtained.get("client") or "",
                    r.correct.get("client", False),
                    r.expected.get("date") or "",
                    r.obtained.get("date") or "",
                    r.correct.get("date", False),
                    r.expected.get("montant_chf") or "",
                    r.obtained.get("montant_chf") or "",
                    r.correct.get("montant_chf", False),
                    r.raisonnement,
                ]
            )
    return out


def collect_pdfs(corpus: Path, labels: dict[str, dict]) -> list[Path]:
    pdfs: list[Path] = []
    for fn in labels:
        p = corpus / fn
        if not p.exists():
            print(f"  ⚠️  {fn} listé dans labels.csv mais absent du corpus, skip.")
            continue
        pdfs.append(p)
    return pdfs


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default="../config.yaml")
    parser.add_argument("--corpus", default="../data/samples")
    parser.add_argument("--model", default=None, help="Override config llm.models.<env>.primary")
    parser.add_argument("--prompt-file", default=None, help="Override config llm.prompt_file")
    parser.add_argument("--limit", type=int, default=None, help="Limite nombre de docs (debug)")
    parser.add_argument(
        "--out-dir",
        default="../data/bench-results",
        help="Répertoire CSV résultats",
    )
    args = parser.parse_args()

    config_path = (ROOT / args.config).resolve() if not Path(args.config).is_absolute() else Path(args.config)
    if not config_path.exists():
        # fallback : config.example.yaml
        example = REPO_ROOT / "config.example.yaml"
        if example.exists():
            print(f"⚠️  {config_path} absent, utilise {example.name}")
            config_path = example
        else:
            sys.exit(f"FATAL : ni {config_path} ni config.example.yaml trouvés")

    corpus = Path(args.corpus)
    if not corpus.is_absolute():
        corpus = (ROOT / corpus).resolve()

    out_dir = Path(args.out_dir)
    if not out_dir.is_absolute():
        out_dir = (ROOT / out_dir).resolve()

    config = load_config(config_path)
    model, prompt_path = select_model_and_prompt(config, args.model, args.prompt_file)
    template = prompt_path.read_text(encoding="utf-8")
    known_clients = config.get("clients", [])
    labels = load_labels(corpus)

    pdfs = collect_pdfs(corpus, labels)
    if args.limit:
        pdfs = pdfs[: args.limit]

    if not pdfs:
        sys.exit(
            "Aucun document à benchmarker. Remplis data/samples/labels.csv "
            "et dépose les PDFs correspondants dans data/samples/."
        )

    print(f"Bench précision")
    print(f"  config   : {config_path}")
    print(f"  corpus   : {corpus}  ({len(pdfs)} docs)")
    print(f"  modèle   : {model}")
    print(f"  prompt   : {prompt_path.relative_to(REPO_ROOT)}")
    print(f"  clients  : {len(known_clients)} canoniques")
    print()

    results: list[DocResult] = []
    for i, pdf in enumerate(pdfs, 1):
        expected = labels[pdf.name]
        print(f"[{i:2d}/{len(pdfs)}] {pdf.name} ...", end=" ", flush=True)
        r = run_one(pdf, expected, template, known_clients, config, model)
        results.append(r)
        if r.error:
            print(f"❌ ERREUR ({r.error})")
        else:
            scored = "/".join(
                ("✓" if r.correct.get(f) else "✗") for f in SCORED_FIELDS
            )
            print(f"{r.latency_s:5.1f}s  type/client/date/montant: {scored}")

    accuracy = print_summary(results, model)
    csv_path = write_csv(results, model, prompt_path, out_dir)
    print(f"\nCSV archivé : {csv_path.relative_to(REPO_ROOT)}")

    # Code retour : 0 si tous seuils OK, 1 sinon. Permet usage CI plus tard.
    all_pass = all(accuracy[f] >= SUCCESS_THRESHOLDS[f] for f in SCORED_FIELDS)
    return 0 if all_pass else 1


if __name__ == "__main__":
    sys.exit(main())
