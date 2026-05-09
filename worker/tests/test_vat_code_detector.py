"""Tests vat_code_detector — détection codes TVA suisses 2024+."""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

from fiduciaire_worker import vat_code_detector as vd

REPO_ROOT = Path(__file__).resolve().parents[2]
VAT_YAML = REPO_ROOT / "config" / "vat_codes_ch.yaml"


def test_normal_rate_from_amounts():
    r = vd.detect_vat_code(
        text="",
        montant_ht=Decimal("100.00"),
        montant_tva=Decimal("8.10"),
        config_path=VAT_YAML,
    )
    assert r.code == "TN_NORM"
    assert r.rate == 8.1
    assert r.confidence >= 0.9


def test_reduced_rate_from_amounts():
    r = vd.detect_vat_code(
        text="",
        montant_ht=Decimal("100.00"),
        montant_tva=Decimal("2.60"),
        config_path=VAT_YAML,
    )
    assert r.code == "TN_RED"
    assert r.rate == 2.6


def test_hebergement_rate_from_amounts():
    r = vd.detect_vat_code(
        text="",
        montant_ht=Decimal("100.00"),
        montant_tva=Decimal("3.80"),
        config_path=VAT_YAML,
    )
    assert r.code == "TN_HEB"


def test_keyword_hotel_no_amounts():
    r = vd.detect_vat_code(
        text="Hôtel Bellevue, Genève. Nuitée du 12 au 13.",
        config_path=VAT_YAML,
    )
    assert r.code == "TN_HEB"
    assert 0.5 <= r.confidence <= 0.85


def test_keyword_export_lieferung():
    r = vd.detect_vat_code(
        text="Lieferung ins Ausland, MwSt 0%",
        config_path=VAT_YAML,
    )
    assert r.code == "EXP"


def test_keyword_acquisition_google_ireland():
    r = vd.detect_vat_code(
        text="Google Ireland Limited services digitaux. Reverse charge.",
        config_path=VAT_YAML,
    )
    assert r.code == "ACQ"


def test_unknown_falls_back():
    r = vd.detect_vat_code(text="aucune indication", config_path=VAT_YAML)
    assert r.code == "UNKNOWN"
    assert r.confidence == 0.0


def test_amounts_override_keywords():
    """Si montants donnent un taux clair, ils gagnent vs keywords."""
    r = vd.detect_vat_code(
        text="Hôtel Bellevue",  # keyword TN_HEB
        montant_ht=Decimal("100.00"),
        montant_tva=Decimal("8.10"),  # mais rate dit TN_NORM
        config_path=VAT_YAML,
    )
    assert r.code == "TN_NORM"


def test_compute_vat_amount_normal():
    # TTC 108.10 → TVA 8.10 (8.1%)
    tva = vd.compute_vat_amount(108.10, "TN_NORM", VAT_YAML)
    assert abs(tva - 8.10) < 0.01


def test_compute_vat_amount_exo_returns_zero():
    tva = vd.compute_vat_amount(1000.0, "EXO", VAT_YAML)
    assert tva == 0.0
