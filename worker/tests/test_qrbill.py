"""Tests unitaires QR-bill parsing."""

from __future__ import annotations

from fiduciaire_worker import qrbill


def test_is_swiss_qr_payload_valid():
    payload = "SPC\r\n0200\r\n1\r\n"
    assert qrbill.is_swiss_qr_payload(payload)


def test_is_swiss_qr_payload_other_qr():
    assert not qrbill.is_swiss_qr_payload("https://example.com")
    assert not qrbill.is_swiss_qr_payload("")


def test_parse_spc_payload_complete():
    payload = "\r\n".join(
        [
            "SPC",                          # 0
            "0200",                         # 1
            "1",                            # 2
            "CH5204835012345678000",        # 3 IBAN
            "S",                            # 4
            "Swisscom (Suisse) SA",         # 5 créancier
            "Postfach", "", "3050", "Bern", # 6-9
            "CH",                           # 10
            "", "", "", "", "", "", "",     # 11-17 ultimate creditor
            "287.00",                       # 18 montant
            "CHF",                          # 19 devise
            "S",                            # 20 type adresse débiteur
            "Restaurant Le Rivage SA",      # 21 débiteur
            "Rue du Rhone 12", "",          # 22-23
            "1204", "Geneve",               # 24-25
            "CH",                           # 26
            "QRR",                          # 27
            "210000000000003139471433000",  # 28 reference
            "",                             # 29
            "EPD",                          # 30
        ]
    )
    qr = qrbill.parse_spc_payload(payload)
    assert qr.iban == "CH5204835012345678000"
    assert qr.fournisseur == "Swisscom (Suisse) SA"
    assert qr.client_raw == "Restaurant Le Rivage SA"
    assert qr.montant_chf == 287.0
    assert qr.devise == "CHF"
    assert qr.reference_type == "QRR"
    assert qr.reference == "210000000000003139471433000"


def test_parse_spc_payload_no_amount():
    payload = "SPC\r\n0200\r\n1\r\n" + "\r\n" * 16 + "\r\n\r\nCHF" + "\r\n" * 11
    qr = qrbill.parse_spc_payload(payload)
    assert qr.montant_chf is None
