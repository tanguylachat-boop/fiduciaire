"""Bench latence Qwen 14B sur classify_v1 — Lundi tâche 1.

Mesure : 6 itérations, exclure itération 1 (cold start), médiane et P95 sur 2-6.
Critère "OK démo" : médiane < 15 s.

Usage :
  cd worker && source .venv/bin/activate
  python scripts/latency_bench.py
  python scripts/latency_bench.py --model qwen2.5:7b-instruct-q4_K_M  # fallback
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from pathlib import Path

import httpx

PROMPT_PATH = Path(__file__).resolve().parents[1] / "prompts" / "classify_v1.txt"

# Texte OCR factice mais réaliste : facture Swisscom FR, ~1500 chars.
FAKE_OCR = """Swisscom (Suisse) SA
Postfach
3050 Bern

Restaurant Le Rivage SA
Rue du Rhône 12
1204 Geneve

Numero client : 1234567890
Numero facture : FCT-2024-03-12-00891
Date facture : 12.03.2024
Date echeance : 11.04.2024

Periode de facturation : du 12.02.2024 au 11.03.2024

Abonnement Internet Pro Fiber 1Gbit/s    99.00 CHF
Abonnement telephonie fixe Business      29.00 CHF
3 lignes mobiles natel professionnelles  45.00 CHF x 3 = 135.00 CHF
Frais services techniques                 12.50 CHF

Sous-total HT                            265.50 CHF
TVA 8.1%                                  21.50 CHF
Total TTC                                287.00 CHF

Mode de paiement : QR-Bill
IBAN : CH52 0483 5012 3456 7800 0
Reference : 21 00000 00000 03139 47143 30009

Merci de votre confiance.
Pour toute question : 0800 800 800
www.swisscom.ch
"""

KNOWN_CLIENTS = [
    {
        "name": "Restaurant Le Rivage SA",
        "aliases": ["Le Rivage", "Rivage SA"],
        "slug": "le-rivage",
    }
]


def build_prompt() -> str:
    template = PROMPT_PATH.read_text(encoding="utf-8")
    return template.replace(
        "{KNOWN_CLIENTS_JSON}", json.dumps(KNOWN_CLIENTS, ensure_ascii=False)
    ).replace("{OCR_TEXT}", FAKE_OCR)


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


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", default="qwen2.5:14b-instruct-q4_K_M")
    parser.add_argument("--endpoint", default="http://localhost:11434")
    parser.add_argument("--iterations", type=int, default=6)
    parser.add_argument("--timeout", type=int, default=120)
    parser.add_argument("--num-predict", type=int, default=512)
    args = parser.parse_args()

    prompt = build_prompt()
    print(f"Bench latence : modèle={args.model}, iters={args.iterations}, num_predict={args.num_predict}")
    print(f"Prompt size : {len(prompt)} chars\n")

    timings: list[float] = []
    last_response = ""
    for i in range(1, args.iterations + 1):
        try:
            elapsed, response = call_ollama(
                args.model, prompt, args.endpoint, args.timeout, args.num_predict
            )
        except Exception as e:
            print(f"  iter {i}: ERREUR — {type(e).__name__}: {e}", file=sys.stderr)
            return 2
        tag = " (cold start, ignoré)" if i == 1 else ""
        print(f"  iter {i}: {elapsed:.2f} s{tag}")
        timings.append(elapsed)
        last_response = response

    measured = timings[1:]  # exclure cold start
    median = statistics.median(measured)
    p95 = (
        statistics.quantiles(measured, n=20)[18]
        if len(measured) >= 2
        else max(measured)
    )
    mean = statistics.fmean(measured)

    print("\n--- Résultat (itérations 2-N) ---")
    print(f"  médiane : {median:.2f} s")
    print(f"  P95     : {p95:.2f} s")
    print(f"  moyenne : {mean:.2f} s")
    print(f"  min/max : {min(measured):.2f} s / {max(measured):.2f} s")

    print("\n--- Vérification JSON parsable de la dernière réponse ---")
    try:
        parsed = json.loads(last_response)
        for k in ("type", "client", "date", "montant_chf"):
            print(f"  {k}: {parsed.get(k)!r}")
    except json.JSONDecodeError as e:
        print(f"  JSON INVALIDE : {e}")
        print(f"  raw : {last_response[:300]}")

    print("\n--- Verdict critère démo ---")
    if median < 15:
        print(f"  OK ({median:.2f}s < 15s) — on peut continuer Mardi.")
        return 0
    print(f"  KO ({median:.2f}s >= 15s) — switch fallback Qwen 7B + relancer.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
