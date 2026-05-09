"""Détection des codes TVA suisses 2024+ (cf config/vat_codes_ch.yaml).

Stratégie :
1. Si montant_ht et montant_tva connus → calcule rate et match au code le plus proche.
2. Sinon → keyword matching dans le texte OCR.
3. Si conflit (taux explicite + keyword incompatible) → priorité aux montants.
4. Si rien → UNKNOWN, flag review humaine.

Codes : TN_NORM (8.1%), TN_RED (2.6%), TN_HEB (3.8%), EXO (0%), EXP (0%), ACQ (8.1%).
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

import yaml

# Tolérance pp sur le calcul rate=tva/ht (arrondis comptables)
RATE_TOLERANCE = 0.15


@dataclass
class VatDetectionResult:
    code: str
    rate: float
    confidence: float
    reasoning: str


def _load_codes(config_path: Path) -> dict:
    return yaml.safe_load(Path(config_path).read_text(encoding="utf-8"))["codes"]


def _rate_from_amounts(
    montant_ht: Decimal | None, montant_tva: Decimal | None
) -> float | None:
    if montant_ht is None or montant_tva is None or montant_ht == 0:
        return None
    return float(montant_tva / montant_ht * 100)


def _match_rate(rate: float, codes: dict) -> tuple[str, float, float] | None:
    """Match un taux au code le plus proche. Retourne (code, code_rate, distance)."""
    best: tuple[str, float, float] | None = None
    for code, data in codes.items():
        if data["rate"] == 0:
            continue  # EXO et EXP traités par keywords (rate=0 ambigu)
        d = abs(rate - data["rate"])
        if d <= RATE_TOLERANCE and (best is None or d < best[2]):
            best = (code, float(data["rate"]), d)
    return best


def _keyword_match(text: str, codes: dict) -> tuple[str, list[str]] | None:
    """Trouve le code dont le plus de keywords matchent. Retourne (code, matched_kws)."""
    text_low = text.lower()
    best_code: str | None = None
    best_kws: list[str] = []
    for code, data in codes.items():
        matched = [kw for kw in data.get("keywords", []) if kw.lower() in text_low]
        if matched and len(matched) > len(best_kws):
            best_code = code
            best_kws = matched
    if best_code is None:
        return None
    return best_code, best_kws


def detect_vat_code(
    text: str,
    montant_ttc: Decimal | None = None,
    montant_ht: Decimal | None = None,
    montant_tva: Decimal | None = None,
    config_path: Path | str = "config/vat_codes_ch.yaml",
) -> VatDetectionResult:
    codes = _load_codes(Path(config_path))

    # Niveau 1 : montants connus → priorité absolue
    rate = _rate_from_amounts(montant_ht, montant_tva)
    if rate is not None:
        match = _match_rate(rate, codes)
        if match:
            code, code_rate, dist = match
            return VatDetectionResult(
                code=code,
                rate=code_rate,
                confidence=0.95 if dist < 0.05 else 0.85,
                reasoning=f"rate calculé tva/ht={rate:.2f}% → {code} ({code_rate}%)",
            )

    # Niveau 2 : keywords
    kw_match = _keyword_match(text, codes)
    if kw_match:
        code, matched = kw_match
        # confidence selon nb keywords matchés (cap à 0.85 sans validation montants)
        confidence = min(0.85, 0.5 + 0.1 * len(matched))
        return VatDetectionResult(
            code=code,
            rate=float(codes[code]["rate"]),
            confidence=confidence,
            reasoning=f"keywords: {', '.join(matched)}",
        )

    return VatDetectionResult(
        code="UNKNOWN",
        rate=0.0,
        confidence=0.0,
        reasoning="aucun signal détecté (ni montants explicites, ni keywords)",
    )


def compute_vat_amount(montant_ttc: float, vat_code: str, config_path: Path | str) -> float:
    """Décompose le TTC en TVA selon le rate du code. TVA = TTC * rate / (100+rate)."""
    codes = _load_codes(Path(config_path))
    rate = float(codes.get(vat_code, {}).get("rate", 0))
    if rate == 0 or montant_ttc == 0:
        return 0.0
    return round(montant_ttc * rate / (100 + rate), 2)
