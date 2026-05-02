"""Bench précision sur corpus annoté (data/samples/labels.csv).

Pipeline pour chaque doc :
  1. QR-bill scan (si activé dans config)
  2. OCR Tesseract (+ vision fallback)
  3. Classification LLM (prompt configuré)
  4. Merge QR (montant/devise/fournisseur ont confidence 1.0 si QR-bill)
  5. Compare au ground-truth, par champ.

Output :
  - tableau précision par champ (type, client, date, montant_chf)
  - cas ratés + raisonnement LLM
  - latence médiane / P95
  - CSV archivé dans data/bench-results/

Critère succès Jeudi 50 docs (DECISIONS.md 2026-04-27) :
  type ≥ 90% | client ≥ 80% | date ≥ 75% | montant ≥ 75%

Usage :
  .venv/bin/python scripts/bench.py [--config ../config.yaml] [--corpus ../data/samples] [--limit N]
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import statistics
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from fiduciaire_worker import classify as classify_mod
from fiduciaire_worker import ocr as ocr_mod
from fiduciaire_worker import qrbill
from fiduciaire_worker.classify import warmup_ollama
from fiduciaire_worker.config import REPO_ROOT, load_config

SCORED_FIELDS = ("type", "client", "date", "montant_chf")
SUCCESS_THRESHOLDS = {"type": 0.90, "client": 0.80, "date": 0.75, "montant_chf": 0.75}
GO_NOGO_TYPE = 0.80  # critère Lundi


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
    sources: dict[str, str] = field(default_factory=dict)


def load_labels(corpus: Path) -> dict[str, dict[str, Any]]:
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


def _normalize(value: Any, field: str) -> Any:
    if value is None:
        return None
    if field == "montant_chf":
        try:
            return round(float(value), 2)
        except (TypeError, ValueError):
            return None
    if field == "date":
        s = str(value).strip()
        return s[:10] if len(s) >= 10 else s
    return str(value).strip()


def _match(expected: Any, obtained: Any, field: str) -> bool:
    e = _normalize(expected, field)
    o = _normalize(obtained, field)
    if e is None and o is None:
        return True
    if e is None or o is None:
        return False
    if field == "montant_chf":
        return abs(float(e) - float(o)) < 0.01
    if field == "client":
        return e.lower() == o.lower()
    return e == o


def run_one(pdf: Path, expected: dict[str, Any], config) -> DocResult:
    res = DocResult(filename=pdf.name, expected=expected, obtained={})

    qr_data = None
    if config.qr_enabled:
        try:
            qr_data = qrbill.detect_and_parse(pdf, dpi=config.ocr_dpi)
            res.qr_used = qr_data is not None
        except Exception as e:
            res.error = f"qr: {type(e).__name__}: {e}"
            return res

    try:
        ocr_res = ocr_mod.run_ocr(
            pdf,
            langs=config.langues_ocr,
            dpi=config.ocr_dpi,
            vision_model=config.llm.vision,
            vision_endpoint=config.llm.endpoint,
            vision_timeout_s=config.llm.timeout_s,
            ratio_threshold=config.vision_when_ratio_below,
        )
        res.ocr_chars = len(ocr_res.text)
    except Exception as e:
        res.error = f"ocr: {type(e).__name__}: {e}"
        return res

    classification = classify_mod.classify(
        ocr_text=ocr_res.text,
        known_clients=config.known_clients,
        template_path=config.llm.prompt_file,
        endpoint=config.llm.endpoint,
        model=config.llm.primary,
        timeout_s=config.llm.timeout_s,
        num_predict=config.llm.num_predict,
        temperature=config.llm.temperature,
    )
    res.latency_s = classification.latency_s
    if classification.error:
        res.error = classification.error
        return res

    classification = classify_mod.merge_with_qr(classification, qr_data)
    res.raisonnement = classification.raisonnement
    res.sources = dict(classification.sources)
    res.obtained = {
        "type": classification.type,
        "client": classification.client,
        "date": classification.date,
        "montant_chf": classification.montant_chf,
        "fournisseur": classification.fournisseur,
        "devise": classification.devise,
    }
    for f in SCORED_FIELDS:
        res.correct[f] = _match(expected.get(f), res.obtained.get(f), f)
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
        print(f"  {f:14s} : {ok:3d}/{n:<3d}  {acc * 100:5.1f}%   (cible Jeudi {threshold * 100:.0f}%)  {marker}")

    type_acc = accuracy.get("type", 0.0)
    print(f"\n=== Critère GO/NO-GO Lundi (≥ {GO_NOGO_TYPE * 100:.0f}% type) ===")
    print(f"  type : {type_acc * 100:.1f}%  {'✅ GO' if type_acc >= GO_NOGO_TYPE else '❌ NO-GO'}")

    times = [r.latency_s for r in results if r.latency_s > 0]
    qr_count = sum(1 for r in results if r.qr_used)
    if times:
        median = statistics.median(times)
        p95 = (
            statistics.quantiles(times, n=20)[18] if len(times) >= 2 else max(times)
        )
        print(f"\n=== Latence ({len(times)} docs LLM, {qr_count} avec QR-bill) ===")
        print(f"  médiane : {median:.2f} s")
        print(f"  P95     : {p95:.2f} s")
        print(f"  min/max : {min(times):.2f} s / {max(times):.2f} s")

    failures = [r for r in results if not all(r.correct.values()) or r.error]
    if failures:
        print(f"\n=== Cas ratés ({len(failures)}/{n}) ===")
        for r in failures:
            print(f"\n  📄 {r.filename}  (latence {r.latency_s:.1f}s, ocr {r.ocr_chars} chars, qr={r.qr_used})")
            if r.error:
                print(f"     ERREUR : {r.error}")
                continue
            for f in SCORED_FIELDS:
                if not r.correct.get(f):
                    print(f"     [{f}] attendu={r.expected.get(f)!r}  obtenu={r.obtained.get(f)!r}  source={r.sources.get(f, '?')}")
            if r.raisonnement:
                print(f"     LLM : {r.raisonnement[:240]}")

    print(f"\n=== Verdict modèle {model} ===")
    all_pass = all(accuracy[f] >= SUCCESS_THRESHOLDS[f] for f in SCORED_FIELDS)
    if all_pass:
        print("  ✅ Tous les seuils Jeudi atteints.")
    else:
        misses = [
            f"{f} {accuracy[f] * 100:.1f}% < {SUCCESS_THRESHOLDS[f] * 100:.0f}%"
            for f in SCORED_FIELDS
            if accuracy[f] < SUCCESS_THRESHOLDS[f]
        ]
        print(f"  ❌ Seuils manqués : {', '.join(misses)}")
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
                "filename", "model", "prompt", "latency_s", "ocr_chars", "qr_used", "error",
                "exp_type", "got_type", "src_type", "ok_type",
                "exp_client", "got_client", "src_client", "ok_client",
                "exp_date", "got_date", "src_date", "ok_date",
                "exp_montant", "got_montant", "src_montant", "ok_montant",
                "raisonnement",
            ]
        )
        for r in results:
            w.writerow(
                [
                    r.filename, model, prompt_path.name, f"{r.latency_s:.2f}", r.ocr_chars, r.qr_used, r.error or "",
                    r.expected.get("type") or "", r.obtained.get("type") or "", r.sources.get("type", ""), r.correct.get("type", False),
                    r.expected.get("client") or "", r.obtained.get("client") or "", r.sources.get("client", ""), r.correct.get("client", False),
                    r.expected.get("date") or "", r.obtained.get("date") or "", r.sources.get("date", ""), r.correct.get("date", False),
                    r.expected.get("montant_chf") or "", r.obtained.get("montant_chf") or "", r.sources.get("montant_chf", ""), r.correct.get("montant_chf", False),
                    r.raisonnement,
                ]
            )
    return out


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, default=None)
    parser.add_argument("--corpus", type=Path, default=REPO_ROOT / "data" / "samples")
    parser.add_argument("--model", default=None)
    parser.add_argument("--prompt-file", default=None)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--out-dir", type=Path, default=REPO_ROOT / "data" / "bench-results")
    args = parser.parse_args()

    config = load_config(args.config)
    if args.model:
        config.llm.primary = args.model
    if args.prompt_file:
        from fiduciaire_worker.config import _resolve
        config.llm.prompt_file = _resolve(args.prompt_file)

    corpus = args.corpus.resolve()
    labels = load_labels(corpus)
    pdfs = []
    for fn in labels:
        p = corpus / fn
        if not p.exists():
            print(f"  ⚠️  {fn} listé dans labels.csv mais absent du corpus, skip.")
            continue
        pdfs.append(p)
    if args.limit:
        pdfs = pdfs[: args.limit]

    if not pdfs:
        print(
            "Aucun document à benchmarker. Remplis data/samples/labels.csv "
            "et dépose les PDFs correspondants dans data/samples/."
        )
        return 2

    print(f"Bench précision")
    print(f"  config   : {Path(args.config) if args.config else REPO_ROOT / 'config.yaml ou .example'}")
    print(f"  corpus   : {corpus}  ({len(pdfs)} docs)")
    print(f"  modèle   : {config.llm.primary}")
    print(f"  prompt   : {config.llm.prompt_file.relative_to(REPO_ROOT)}")
    print(f"  clients  : {len(config.known_clients)} canoniques")
    print()

    print(f"Warmup Ollama ({config.llm.primary}) ...", end=" ", flush=True)
    ok = warmup_ollama(config.llm.endpoint, config.llm.primary, timeout_s=config.llm.timeout_s)
    print("✓" if ok else "✗ (non bloquant)")
    print()

    results: list[DocResult] = []
    for i, pdf in enumerate(pdfs, 1):
        expected = labels[pdf.name]
        print(f"[{i:2d}/{len(pdfs)}] {pdf.name} ...", end=" ", flush=True)
        r = run_one(pdf, expected, config)
        results.append(r)
        if r.error:
            print(f"❌ ERREUR ({r.error})")
        else:
            scored = "/".join(("✓" if r.correct.get(f) else "✗") for f in SCORED_FIELDS)
            print(f"{r.latency_s:5.1f}s  qr={r.qr_used}  {scored}")

    accuracy = print_summary(results, config.llm.primary)
    csv_path = write_csv(results, config.llm.primary, config.llm.prompt_file, args.out_dir)
    print(f"\nCSV archivé : {csv_path.relative_to(REPO_ROOT)}")

    type_pass = accuracy.get("type", 0.0) >= GO_NOGO_TYPE
    return 0 if type_pass else 1


if __name__ == "__main__":
    sys.exit(main())
