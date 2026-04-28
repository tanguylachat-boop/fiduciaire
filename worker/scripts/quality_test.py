"""Test qualité matching client — Lundi tâche 1bis (Option 2 few-shot).

Lance 3 cas factices :
  1. swisscom    : nom canonique explicite "Restaurant Le Rivage SA"
  2. alias       : alias court "Le Rivage" (extrait d'une facture SIG)
  3. sarl        : variante "Le Rivage Sàrl" (extrait d'une décision fiscale)

Pour chaque cas, mesure :
  - latence
  - JSON parsable ?
  - client = "Restaurant Le Rivage SA" attendu sur les 3 cas

Critère validation Option 2 : 3/3 cas retrouvent le canonique.

Usage :
  .venv/bin/python scripts/quality_test.py \\
    --model qwen2.5:7b-instruct-q4_K_M \\
    --prompt-file prompts/classify_v2_fewshot.txt
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]

KNOWN_CLIENTS = [
    {
        "name": "Restaurant Le Rivage SA",
        "aliases": ["Le Rivage", "Rivage SA", "Restaurant Rivage", "Le Rivage Sàrl"],
        "slug": "le-rivage",
    },
    {
        "name": "Atelier Boillat",
        "aliases": ["Boillat", "Atelier H. Boillat"],
        "slug": "atelier-boillat",
    },
]

CASES = {
    "swisscom": {
        "expected_client": "Restaurant Le Rivage SA",
        "ocr": """Swisscom (Suisse) SA
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
""",
    },
    "alias": {
        "expected_client": "Restaurant Le Rivage SA",
        "ocr": """SIG - Services Industriels de Geneve
Avenue de la Praille 17
1227 Carouge

Le Rivage
Rue du Rhone 12
1204 Geneve

Facture n° SIG-2024-0788
Date emission : 04.04.2024
Periode facturation : 01.01.2024 - 31.03.2024

Electricite consommee 4'215 kWh         387.20 CHF
Eau consommee 89 m3                      18.65 CHF
Frais fixes trimestriels                  7.00 CHF

Total HT                                412.85 CHF
TVA 8.1%                                 33.44 CHF
Total TTC                               446.29 CHF

QR-Bill au verso. IBAN CH64 0900 0000 1700 7672 8.
""",
    },
    "sarl": {
        "expected_client": "Restaurant Le Rivage SA",
        "ocr": """REPUBLIQUE ET CANTON DE GENEVE
Office cantonal des impots
Rue du Stand 26 - 1204 Geneve

Decision de taxation - exercice 2023

Contribuable : Le Rivage Sarl
Adresse :      Rue du Rhone 12, 1204 Geneve
No contribuable : 12.345.678

Date d'emission : 15.06.2024
Echeance paiement : 30.09.2024

Impot cantonal et communal du benefice    6'820.00 CHF
Impot cantonal du capital                   930.00 CHF
Frais de notification                       100.00 CHF
Total a payer                             8'450.00 CHF

Voies de recours : 30 jours.
""",
    },
}


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


def build_prompt(template: str, ocr_text: str) -> str:
    return template.replace(
        "{KNOWN_CLIENTS_JSON}", json.dumps(KNOWN_CLIENTS, ensure_ascii=False, indent=2)
    ).replace("{OCR_TEXT}", ocr_text)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", default="qwen2.5:7b-instruct-q4_K_M")
    parser.add_argument("--prompt-file", default="prompts/classify_v2_fewshot.txt")
    parser.add_argument("--endpoint", default="http://localhost:11434")
    parser.add_argument("--num-predict", type=int, default=512)
    parser.add_argument("--timeout", type=int, default=120)
    args = parser.parse_args()

    template_path = (ROOT / args.prompt_file).resolve()
    template = template_path.read_text(encoding="utf-8")

    print(f"Quality test : modèle={args.model}")
    print(f"Prompt : {template_path.relative_to(ROOT)}  ({len(template)} chars)")
    print(f"Cas : {', '.join(CASES.keys())}\n")

    results: list[tuple[str, bool, float, str]] = []
    for name, case in CASES.items():
        prompt = build_prompt(template, case["ocr"])
        try:
            elapsed, response = call_ollama(
                args.model, prompt, args.endpoint, args.timeout, args.num_predict
            )
        except Exception as e:
            print(f"[{name}] ERREUR : {type(e).__name__}: {e}")
            results.append((name, False, 0.0, ""))
            continue

        try:
            parsed = json.loads(response)
        except json.JSONDecodeError as e:
            print(f"[{name}] {elapsed:.2f}s — JSON INVALIDE : {e}")
            print(f"           raw : {response[:200]}")
            results.append((name, False, elapsed, ""))
            continue

        client = parsed.get("client")
        client_conf = parsed.get("client_confidence")
        type_ = parsed.get("type")
        date = parsed.get("date")
        montant = parsed.get("montant_chf")
        ok = client == case["expected_client"]
        marker = "✅" if ok else "❌"
        print(
            f"[{name}] {elapsed:.2f}s — type={type_!r} client={client!r} "
            f"(conf={client_conf}) date={date} montant={montant} {marker}"
        )
        if not ok:
            print(f"           ATTENDU client={case['expected_client']!r}")
        results.append((name, ok, elapsed, client or ""))

    print()
    passed = sum(1 for _, ok, _, _ in results if ok)
    total = len(results)
    times = [t for _, _, t, _ in results if t > 0]
    median = statistics.median(times) if times else 0.0

    print(f"--- Résumé ---")
    print(f"  matching client : {passed}/{total}")
    print(f"  latence médiane : {median:.2f} s")

    if passed == total and median < 15:
        print(f"  → Option 2 VALIDÉE : 3/3 client + médiane <15s")
        return 0
    if passed == total:
        print(f"  → qualité OK mais latence dégradée ({median:.2f}s >= 15s)")
        return 1
    print(f"  → Option 2 INSUFFISANTE : {passed}/{total} matching client")
    return 2


if __name__ == "__main__":
    sys.exit(main())
