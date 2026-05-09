"""Bench entry_proposer sur 50 docs synthétiques + ground truth `entry_labels.csv`.

Mesures séparées :
  - % compte correct (debit_account)
  - % code TVA correct
  - % les deux corrects (proposition utilisable d'un clic)
  - latence médiane et P95

Usage :
  python worker/scripts/entry_bench.py \\
    --model llama3.3:70b-instruct-q4_K_M \\
    --client-id pilote-jura-01 \\
    [--mistral-compare]   # lance aussi Mistral Small 3 et compare

Préreq :
  - Ollama running avec le modèle pulled
  - Pipeline POC déjà passé sur les 50 docs (table documents alimentée)
  - Vendor history seed via worker/scripts/seed_synthetic_vendor_history.py
"""

from __future__ import annotations

import argparse
import csv
import json
import statistics
import time
from datetime import datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
import sys
sys.path.insert(0, str(REPO_ROOT / "worker" / "src"))

from fiduciaire_worker import (  # noqa: E402
    accounting_schema,
    db,
    entry_proposer,
    plan_comptable_mapper,
)


def load_ground_truth(path: Path) -> dict[str, dict]:
    out: dict[str, dict] = {}
    with path.open(encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            if (row.get("skip_bench") or "").strip().lower() == "true":
                continue
            out[row["filename"]] = {
                "debit_account": row["debit_account"],
                "credit_account": row["credit_account"],
                "vat_code": row["vat_code"],
                "description": row["description"],
            }
    return out


def run_bench(
    db_path: Path,
    client_id: str,
    model: str,
    ollama_endpoint: str,
    truth: dict[str, dict],
) -> dict:
    conn = db.connect(db_path)
    db.init_schema(conn)
    accounting_schema.init_accounting_schema(conn)

    plan = plan_comptable_mapper.PlanComptable.from_bexio_cache(conn, client_id)
    if plan is None:
        plan = plan_comptable_mapper.PlanComptable.from_yaml_fallback(
            REPO_ROOT / "config" / "plan_comptable_pme_ch.yaml"
        )

    docs = conn.execute(
        "SELECT id, original_filename FROM documents "
        "WHERE original_filename IN ({})".format(
            ",".join(["?"] * len(truth))
        ),
        list(truth.keys()),
    ).fetchall()

    results = []
    latencies_ms = []

    for doc_row in docs:
        fname = doc_row["original_filename"]
        if fname not in truth:
            continue
        expected = truth[fname]

        t0 = time.perf_counter()
        try:
            entry = entry_proposer.propose_entry(
                conn,
                client_id,
                doc_row["id"],
                plan=plan,
                ollama_endpoint=ollama_endpoint,
                ollama_model=model,
                prompt_template_path=REPO_ROOT / "worker" / "prompts" / "entry_proposer_v1.txt",
                vat_yaml_path=REPO_ROOT / "config" / "vat_codes_ch.yaml",
                plan_fallback_path=REPO_ROOT / "config" / "plan_comptable_pme_ch.yaml",
                persist=False,
            )
            elapsed_ms = int((time.perf_counter() - t0) * 1000)
            latencies_ms.append(elapsed_ms)

            ok_account = entry.debit_account == expected["debit_account"]
            ok_vat = entry.vat_code == expected["vat_code"]

            results.append({
                "filename": fname,
                "expected_account": expected["debit_account"],
                "got_account": entry.debit_account,
                "ok_account": ok_account,
                "expected_vat": expected["vat_code"],
                "got_vat": entry.vat_code,
                "ok_vat": ok_vat,
                "ok_both": ok_account and ok_vat,
                "confidence_account": entry.confidence_account,
                "confidence_vat": entry.confidence_vat,
                "source_account": entry.sources.get("account"),
                "source_vat": entry.sources.get("vat_code"),
                "latency_ms": elapsed_ms,
                "reasoning": entry.reasoning[:120],
            })
        except Exception as e:
            results.append({
                "filename": fname,
                "error": f"{type(e).__name__}: {e}",
                "ok_account": False,
                "ok_vat": False,
                "ok_both": False,
            })

    n = len(results)
    if n == 0:
        return {"model": model, "n": 0, "error": "aucun doc benché"}

    pct_account = sum(1 for r in results if r.get("ok_account")) / n * 100
    pct_vat = sum(1 for r in results if r.get("ok_vat")) / n * 100
    pct_both = sum(1 for r in results if r.get("ok_both")) / n * 100
    n_history = sum(1 for r in results if r.get("source_account") == "vendor_history")
    n_llm = sum(1 for r in results if r.get("source_account") == "llm")

    summary = {
        "model": model,
        "client_id": client_id,
        "n": n,
        "pct_account_correct": round(pct_account, 1),
        "pct_vat_correct": round(pct_vat, 1),
        "pct_both_correct": round(pct_both, 1),
        "median_latency_ms": int(statistics.median(latencies_ms)) if latencies_ms else None,
        "p95_latency_ms": int(statistics.quantiles(latencies_ms, n=20)[-1])
            if len(latencies_ms) >= 20 else None,
        "vendor_history_shortcuts": n_history,
        "llm_proposals": n_llm,
        "errors": [r for r in results if "error" in r],
        "results": results,
    }
    return summary


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--db", default=str(REPO_ROOT / "data" / "fiduciaire.sqlite"))
    p.add_argument("--client-id", default="pilote-jura-01")
    p.add_argument("--model", default="llama3.3:70b-instruct-q4_K_M")
    p.add_argument("--ollama", default="http://localhost:11434")
    p.add_argument(
        "--truth",
        default=str(REPO_ROOT / "data" / "samples" / "entry_labels.csv"),
    )
    p.add_argument(
        "--out",
        default=str(REPO_ROOT / "data" / "bench-results" / f"entry-bench-{datetime.now():%Y%m%d-%H%M%S}.json"),
    )
    p.add_argument("--mistral-compare", action="store_true",
                   help="Lance aussi Mistral Small 3 et compare")
    args = p.parse_args()

    truth = load_ground_truth(Path(args.truth))
    print(f"Ground truth : {len(truth)} docs benchables")

    summaries: list[dict] = []
    models_to_test = [args.model]
    if args.mistral_compare:
        models_to_test.append("mistral-small3:24b-instruct-q4_K_M")

    for model in models_to_test:
        print(f"\n=== Bench {model} ===")
        summary = run_bench(
            db_path=Path(args.db),
            client_id=args.client_id,
            model=model,
            ollama_endpoint=args.ollama,
            truth=truth,
        )
        summaries.append(summary)
        print(f"  account correct : {summary.get('pct_account_correct')}%")
        print(f"  vat correct     : {summary.get('pct_vat_correct')}%")
        print(f"  both correct    : {summary.get('pct_both_correct')}%")
        print(f"  median latency  : {summary.get('median_latency_ms')} ms")
        print(f"  vendor history  : {summary.get('vendor_history_shortcuts')}/{summary['n']}")

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(summaries, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\nRapport : {out_path}")


if __name__ == "__main__":
    main()
