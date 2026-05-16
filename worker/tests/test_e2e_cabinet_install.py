"""Test E2E "installation cabinet" — Sprint 2 Session 12.

Valide que tout le flow d'install se déroule sans erreur, de A à Z :
1. Provision cabinet (script chantier 1)
2. Import historique Bexio mock
3. Dépose 5 documents inbox + simule classification
4. Insère 5 accounting_entries proposed
5. Valide 2 entries (workflow_states)
6. Exporte Crésus XML + Abacus XML
7. Génère rapport mensuel Markdown (+ smoke PDF)
8. Vérifie audit chain (verify_audit_chain)

Doit tourner en < 60s avec mocks Bexio.
"""

from __future__ import annotations

import sys
from pathlib import Path

import httpx
import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "worker" / "src"))

from fiduciaire_worker import (  # noqa: E402
    accounting_schema, audit_log, bexio_client, db,
)


def _bexio_with_handler(handler, cabinet_id):
    transport = httpx.MockTransport(handler)
    http = httpx.Client(
        base_url=bexio_client.DEFAULT_BASE_URL,
        headers={"Authorization": "Bearer FAKE_PAT",
                 "Accept": "application/json"},
        transport=transport,
    )
    return bexio_client.BexioReadOnlyClient(
        client_id=cabinet_id, pat="FAKE_PAT", http_client=http,
    )


@pytest.mark.timeout(60)
def test_e2e_cabinet_install_full_flow(tmp_path: Path) -> None:
    """End-to-end install : provision → import → entries → exports → report → audit."""
    from fiduciaire_worker.abacus_export import export_to_abacus_xml
    from fiduciaire_worker.bexio_history_import import import_bexio_history
    from fiduciaire_worker.cabinet_provisioning import provision_cabinet
    from fiduciaire_worker.cresus_export import export_to_cresus_xml
    from fiduciaire_worker.monthly_report import generate_monthly_report

    cabinet_id = "e2e-cab-01"
    clients_root = tmp_path / "clients"
    db_path = tmp_path / "fiduciaire.sqlite"

    conn = db.connect(db_path)
    db.init_schema(conn)
    accounting_schema.init_accounting_schema(conn)
    audit_log.init_audit_schema(conn)

    # --- 1. Provision cabinet ---
    result = provision_cabinet(
        cabinet_id=cabinet_id,
        cabinet_name="E2E Cabinet SA",
        ville="Lausanne", canton="VD", lang="fr",
        mandants=[cabinet_id],
        logiciel="bexio",
        clients_root=clients_root,
        conn=conn,
        user_id="e2e-test",
        db_path=db_path,
    )
    assert result.accounts_seeded > 20
    assert (clients_root / cabinet_id / "inbox").is_dir()

    # --- 2. Import historique Bexio (mock) ---
    def handler(req: httpx.Request) -> httpx.Response:
        url = str(req.url)
        if "/accounts" in url:
            return httpx.Response(200, json=[
                {"id": 1, "account_no": "1020", "name": "Banque",
                 "account_type": "actif"},
                {"id": 2, "account_no": "6510", "name": "Telecom",
                 "account_type": "charge"},
            ])
        if "/contact" in url:
            return httpx.Response(200, json=[
                {"id": 10, "name_1": "Swisscom (Suisse) SA",
                 "contact_type": "company"},
            ])
        if "/accounting/manual_entries" in url:
            params = dict(req.url.params)
            offset = int(params.get("offset", "0"))
            if offset > 0:
                return httpx.Response(200, json=[])
            return httpx.Response(200, json=[
                {
                    "id": 2000 + i,
                    "date": "2026-04-15",
                    "description": "Swisscom abo",
                    "contact_id": "10",
                    "entries": [{
                        "debit_account_id": "6510",
                        "credit_account_id": "2000",
                        "amount": 100.0 + i,
                        "tax_id": "TN_NORM",
                    }],
                }
                for i in range(5)
            ])
        return httpx.Response(404)

    cli = _bexio_with_handler(handler, cabinet_id)
    import_summary = import_bexio_history(
        client=cli, conn=conn,
        cabinet_id=cabinet_id, mandant_id=cabinet_id,
        months=12, page_size=100, sleep_between_pages_s=0.0,
        user_id="e2e-test",
    )
    assert import_summary.entries_imported == 5
    assert import_summary.vendor_recs_built >= 1

    # --- 3. Dépose 5 documents inbox (simulé : insert direct DB) ---
    doc_ids: list[int] = []
    for i in range(5):
        doc_id, _ = db.insert_document(
            conn, f"sha-e2e-{i}", f"doc-{i}.pdf",
            f"/arch/doc-{i}.pdf",
        )
        doc_ids.append(doc_id)

    # --- 4. Insère 5 accounting_entries proposed ---
    entry_ids: list[int] = []
    for i, doc_id in enumerate(doc_ids):
        cur = conn.execute(
            "INSERT INTO accounting_entries "
            "(client_id, source_document_id, date, debit_account, "
            " credit_account, amount_chf, vat_code, vat_amount, "
            " description, confidence_account, confidence_vat, state) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'proposed')",
            (cabinet_id, doc_id, f"2026-04-{i+1:02d}",
             "6510", "2000", 100.0 + i, "TN_NORM", (100.0 + i) * 0.081,
             f"Facture e2e {i}", 0.9, 0.9),
        )
        entry_ids.append(int(cur.lastrowid))

    # --- 5. Valide 2 entries (manuellement via UPDATE + audit) ---
    for eid in entry_ids[:2]:
        conn.execute(
            "UPDATE accounting_entries SET state='validated', "
            "updated_at=datetime('now') WHERE id=?",
            (eid,),
        )
        audit_log.log_audit_event(
            conn,
            cabinet_id=cabinet_id,
            entity_type="accounting_entry",
            entity_id=eid,
            action="validated",
            user_id="e2e-test",
            after={"state": "validated"},
        )

    validated_count = conn.execute(
        "SELECT COUNT(*) FROM accounting_entries "
        "WHERE client_id=? AND state='validated'",
        (cabinet_id,),
    ).fetchone()[0]
    assert validated_count == 2

    # --- 6. Exports Crésus + Abacus ---
    out_dir = clients_root / cabinet_id / "exports"
    cresus_summary = export_to_cresus_xml(
        cabinet_id=cabinet_id, conn=conn,
        output_path=out_dir / "cresus.xml",
    )
    assert cresus_summary.rows_exported == 2
    assert (out_dir / "cresus.xml").exists()

    abacus_summary = export_to_abacus_xml(
        cabinet_id=cabinet_id, conn=conn,
        output_path=out_dir / "abacus.xml",
    )
    assert abacus_summary.rows_exported == 2
    assert (out_dir / "abacus.xml").exists()

    # --- 7. Rapport mensuel Markdown ---
    report_summary = generate_monthly_report(
        cabinet_id=cabinet_id, client_id=cabinet_id,
        year=2026, month=4, output_dir=out_dir, conn=conn,
    )
    assert report_summary.md_path.exists()
    md_text = report_summary.md_path.read_text(encoding="utf-8")
    assert "Rapport mensuel" in md_text
    assert "Facture e2e 0" in md_text or "Facture e2e 1" in md_text

    # --- 8. Vérification audit chain ---
    verification = audit_log.verify_audit_chain(conn, cabinet_id)
    assert verification.is_valid is True, (
        f"chain invalide : id={verification.first_invalid_id} "
        f"reason={verification.first_invalid_reason}"
    )
    assert verification.total_events >= 4  # provisioned + history + 2 validations

    conn.close()


@pytest.mark.timeout(30)
def test_e2e_cross_mandant_isolation_smoke(tmp_path: Path) -> None:
    """Provision 2 cabinets, vérifie zéro leak data entre eux."""
    from fiduciaire_worker.cabinet_provisioning import provision_cabinet

    db_path = tmp_path / "iso.sqlite"
    conn = db.connect(db_path)
    db.init_schema(conn)
    accounting_schema.init_accounting_schema(conn)
    audit_log.init_audit_schema(conn)

    for cab in ("cab-a-iso", "cab-b-iso"):
        provision_cabinet(
            cabinet_id=cab,
            cabinet_name=f"Cabinet {cab}",
            ville="X", canton="GE", lang="fr",
            mandants=[cab],
            logiciel="bexio",
            clients_root=tmp_path / "clients",
            conn=conn,
            db_path=db_path,
        )
        # Insert 1 entry par cabinet
        doc_id, _ = db.insert_document(
            conn, f"sha-{cab}", f"d-{cab}.pdf", f"/a/{cab}.pdf",
        )
        conn.execute(
            "INSERT INTO accounting_entries "
            "(client_id, source_document_id, date, debit_account, "
            " credit_account, amount_chf, vat_code, vat_amount, "
            " description, confidence_account, confidence_vat, state) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'validated')",
            (cab, doc_id, "2026-04-15", "6510", "2000", 100.0,
             "TN_NORM", 8.10, f"entry-{cab}", 0.9, 0.9),
        )

    # Chain audit cab-a ne contient AUCUN event cab-b
    events_a = audit_log.list_events(conn, "cab-a-iso")
    events_b = audit_log.list_events(conn, "cab-b-iso")
    assert all(e.cabinet_id == "cab-a-iso" for e in events_a)
    assert all(e.cabinet_id == "cab-b-iso" for e in events_b)

    # COA isolé
    coa_a = conn.execute(
        "SELECT COUNT(*) FROM chart_of_accounts WHERE client_id=?",
        ("cab-a-iso",),
    ).fetchone()[0]
    coa_b = conn.execute(
        "SELECT COUNT(*) FROM chart_of_accounts WHERE client_id=?",
        ("cab-b-iso",),
    ).fetchone()[0]
    assert coa_a == coa_b and coa_a > 0
    leak = conn.execute(
        "SELECT COUNT(*) FROM chart_of_accounts "
        "WHERE client_id NOT IN ('cab-a-iso','cab-b-iso')"
    ).fetchone()[0]
    assert leak == 0
    conn.close()
