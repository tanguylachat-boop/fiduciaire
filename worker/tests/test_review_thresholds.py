"""Tests évaluation seuils review queue."""

from __future__ import annotations

from fiduciaire_worker import review
from fiduciaire_worker.classify import Classification


THRESHOLDS = {"type": 0.85, "client": 0.80, "date": 0.75, "montant": 0.75}


def test_pass_clean():
    c = Classification(
        type="facture_fournisseur",
        type_confidence=0.95,
        client="X SA",
        client_confidence=0.9,
        date="2024-01-01",
        date_confidence=0.9,
        montant_chf=10.0,
        montant_confidence=0.9,
    )
    assert review.evaluate_thresholds(c, THRESHOLDS) == []


def test_low_type_conf():
    c = Classification(type="facture_fournisseur", type_confidence=0.5)
    reasons = review.evaluate_thresholds(c, THRESHOLDS)
    assert any("type_conf" in r for r in reasons)


def test_client_null():
    c = Classification(
        type="facture_fournisseur", type_confidence=0.95,
        client=None, date="2024-01-01", date_confidence=0.9,
        montant_chf=10.0, montant_confidence=0.9,
    )
    reasons = review.evaluate_thresholds(c, THRESHOLDS)
    assert "client_null" in reasons


def test_classification_error():
    c = Classification(error="json: bad")
    reasons = review.evaluate_thresholds(c, THRESHOLDS)
    assert any("classification_error" in r for r in reasons)


def test_courrier_no_montant_ok():
    """Pour un courrier, l'absence de montant ne doit pas envoyer en review."""
    c = Classification(
        type="courrier", type_confidence=0.9,
        client="X SA", client_confidence=0.85,
        date="2024-01-01", date_confidence=0.8,
        montant_chf=None, montant_confidence=0.0,
    )
    reasons = review.evaluate_thresholds(c, THRESHOLDS)
    assert reasons == []
