"""Tests rename + slugify."""

from __future__ import annotations

from fiduciaire_worker import rename_route as rr
from fiduciaire_worker.classify import Classification


def test_slugify_basic():
    assert rr.slugify("Restaurant Le Rivage SA") == "restaurant-le-rivage-sa"
    assert rr.slugify("Service Industriel Genève") == "service-industriel-geneve"
    assert rr.slugify(None) == "inconnu"
    assert rr.slugify("") == "inconnu"


def test_resolve_client_slug_canonical():
    known = [{"name": "Restaurant Le Rivage SA", "slug": "le-rivage"}]
    assert rr.resolve_client_slug("Restaurant Le Rivage SA", known) == "le-rivage"
    assert rr.resolve_client_slug("Random SA", known) == "random-sa"
    assert rr.resolve_client_slug(None, known) == "inconnu"


def test_build_filename():
    c = Classification(
        type="facture_fournisseur",
        client="Restaurant Le Rivage SA",
        fournisseur="Swisscom (Suisse) SA",
        date="2024-03-12",
        montant_chf=287.00,
    )
    type_short_map = {"facture_fournisseur": "FF"}
    pattern = "{date_iso}_{type_short}_{fournisseur_slug}_{montant_chf}_{hash6}.pdf"
    name = rr.build_filename(pattern, c, "abcdef0123", type_short_map, ".pdf")
    assert name == "2024-03-12_FF_swisscom-suisse-sa_287-00_abcdef.pdf"
