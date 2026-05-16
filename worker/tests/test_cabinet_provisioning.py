"""Tests `fiduciaire_worker.cabinet_provisioning` — Sprint 2 Session 12.

Provisioning idempotent d'un nouveau cabinet : DB + folders + config.yaml
+ seed plan comptable + audit event. Multi-mandant strict.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "worker" / "src"))

from fiduciaire_worker import accounting_schema, audit_log, db  # noqa: E402


def _setup_db(tmp_path: Path):
    conn = db.connect(tmp_path / "cabinet.sqlite")
    db.init_schema(conn)
    accounting_schema.init_accounting_schema(conn)
    audit_log.init_audit_schema(conn)
    return conn


def test_provision_creates_folder_structure(tmp_path: Path) -> None:
    from fiduciaire_worker.cabinet_provisioning import provision_cabinet

    conn = _setup_db(tmp_path)
    clients_root = tmp_path / "clients"

    result = provision_cabinet(
        cabinet_id="cab-jura-01",
        cabinet_name="Cabinet Jura SA",
        ville="Delémont",
        canton="JU",
        lang="fr",
        mandants=["mandant-a"],
        logiciel="winbiz",
        clients_root=clients_root,
        conn=conn,
    )
    assert result.created is True
    base = clients_root / "cab-jura-01"
    for sub in ("inbox", "archive", "needs-review", "validated", "exports"):
        assert (base / sub).is_dir(), f"missing dir {sub}"
    assert result.config_path.exists()
    assert result.config_path.name == "config.yaml"


def test_provision_writes_valid_config_yaml(tmp_path: Path) -> None:
    from fiduciaire_worker.cabinet_provisioning import provision_cabinet

    conn = _setup_db(tmp_path)
    result = provision_cabinet(
        cabinet_id="cab-vd-01",
        cabinet_name="Fiduciaire Vaudoise",
        ville="Lausanne",
        canton="VD",
        lang="fr",
        mandants=["m1", "m2"],
        logiciel="bexio",
        clients_root=tmp_path / "clients",
        conn=conn,
    )
    raw = yaml.safe_load(result.config_path.read_text(encoding="utf-8"))
    assert raw["cabinet"]["name"] == "Fiduciaire Vaudoise"
    assert raw["cabinet"]["slug"] == "cab-vd-01"
    assert raw["cabinet"]["ville"] == "Lausanne"
    assert raw["cabinet"]["canton"] == "VD"
    assert raw["cabinet"]["lang"] == "fr"
    assert raw["cabinet"]["logiciel"] == "bexio"
    assert "m1" in raw["mandants"]
    assert "m2" in raw["mandants"]


def test_provision_seeds_plan_comptable(tmp_path: Path) -> None:
    from fiduciaire_worker.cabinet_provisioning import provision_cabinet
    from fiduciaire_worker.plan_comptable_seed import seed_account_count

    conn = _setup_db(tmp_path)
    result = provision_cabinet(
        cabinet_id="cab-a",
        cabinet_name="Cab A",
        ville="X", canton="GE", lang="fr",
        mandants=["m"], logiciel="cresus",
        clients_root=tmp_path / "clients", conn=conn,
    )
    assert result.accounts_seeded == seed_account_count()

    # Plan présent en DB
    rows = conn.execute(
        "SELECT account_no, name, account_type FROM chart_of_accounts "
        "WHERE client_id=? ORDER BY account_no",
        ("cab-a",),
    ).fetchall()
    assert len(rows) == seed_account_count()
    # Quelques comptes clés présents
    nos = {r["account_no"] for r in rows}
    for must in ("1020", "1100", "1170", "2000", "2200", "3000", "6510"):
        assert must in nos, f"compte standard manquant : {must}"


def test_provision_inserts_cabinet_and_mandants_rows(tmp_path: Path) -> None:
    from fiduciaire_worker.cabinet_provisioning import provision_cabinet

    conn = _setup_db(tmp_path)
    provision_cabinet(
        cabinet_id="cab-tri",
        cabinet_name="Tri Cabinet",
        ville="Sion", canton="VS", lang="fr",
        mandants=["m-a", "m-b", "m-c"], logiciel="abacus",
        clients_root=tmp_path / "clients", conn=conn,
    )
    row = conn.execute(
        "SELECT * FROM cabinets WHERE cabinet_id=?", ("cab-tri",),
    ).fetchone()
    assert row is not None
    assert row["cabinet_name"] == "Tri Cabinet"
    assert row["logiciel"] == "abacus"
    mandants = conn.execute(
        "SELECT mandant_id FROM mandants WHERE cabinet_id=? ORDER BY mandant_id",
        ("cab-tri",),
    ).fetchall()
    assert [m["mandant_id"] for m in mandants] == ["m-a", "m-b", "m-c"]


def test_provision_idempotent_re_run_no_changes(tmp_path: Path) -> None:
    """Re-run sans --force ⇒ AlreadyExistsError, DB intacte."""
    from fiduciaire_worker.cabinet_provisioning import (
        CabinetAlreadyExistsError,
        provision_cabinet,
    )

    conn = _setup_db(tmp_path)
    provision_cabinet(
        cabinet_id="cab-x",
        cabinet_name="X", ville="Y", canton="GE", lang="fr",
        mandants=["m"], logiciel="bexio",
        clients_root=tmp_path / "clients", conn=conn,
    )
    coa_before = conn.execute(
        "SELECT COUNT(*) FROM chart_of_accounts WHERE client_id=?", ("cab-x",),
    ).fetchone()[0]

    with pytest.raises(CabinetAlreadyExistsError, match="cab-x"):
        provision_cabinet(
            cabinet_id="cab-x",
            cabinet_name="X v2", ville="Y", canton="GE", lang="fr",
            mandants=["m"], logiciel="bexio",
            clients_root=tmp_path / "clients", conn=conn,
        )
    coa_after = conn.execute(
        "SELECT COUNT(*) FROM chart_of_accounts WHERE client_id=?", ("cab-x",),
    ).fetchone()[0]
    assert coa_before == coa_after


def test_provision_force_overwrites_cabinet_row(tmp_path: Path) -> None:
    from fiduciaire_worker.cabinet_provisioning import provision_cabinet

    conn = _setup_db(tmp_path)
    provision_cabinet(
        cabinet_id="cab-f",
        cabinet_name="Original", ville="Y", canton="GE", lang="fr",
        mandants=["m"], logiciel="bexio",
        clients_root=tmp_path / "clients", conn=conn,
    )
    result = provision_cabinet(
        cabinet_id="cab-f",
        cabinet_name="Renamed", ville="Lausanne", canton="VD", lang="fr",
        mandants=["m", "m2"], logiciel="winbiz",
        clients_root=tmp_path / "clients", conn=conn, force=True,
    )
    assert result.created is True
    row = conn.execute(
        "SELECT cabinet_name, logiciel, ville FROM cabinets WHERE cabinet_id=?",
        ("cab-f",),
    ).fetchone()
    assert row["cabinet_name"] == "Renamed"
    assert row["logiciel"] == "winbiz"
    assert row["ville"] == "Lausanne"
    # Mandants ré-écrits
    mids = [r["mandant_id"] for r in conn.execute(
        "SELECT mandant_id FROM mandants WHERE cabinet_id=? ORDER BY mandant_id",
        ("cab-f",),
    )]
    assert mids == ["m", "m2"]


def test_provision_rejects_invalid_lang(tmp_path: Path) -> None:
    from fiduciaire_worker.cabinet_provisioning import provision_cabinet

    conn = _setup_db(tmp_path)
    with pytest.raises(ValueError, match="lang"):
        provision_cabinet(
            cabinet_id="cab-bad",
            cabinet_name="X", ville="Y", canton="GE",
            lang="en",  # invalide (fr/de/it seulement)
            mandants=["m"], logiciel="bexio",
            clients_root=tmp_path / "clients", conn=conn,
        )


def test_provision_rejects_invalid_logiciel(tmp_path: Path) -> None:
    from fiduciaire_worker.cabinet_provisioning import provision_cabinet

    conn = _setup_db(tmp_path)
    with pytest.raises(ValueError, match="logiciel"):
        provision_cabinet(
            cabinet_id="cab-bad",
            cabinet_name="X", ville="Y", canton="GE", lang="fr",
            mandants=["m"], logiciel="sage",  # pas supporté
            clients_root=tmp_path / "clients", conn=conn,
        )


def test_provision_rejects_invalid_cabinet_id(tmp_path: Path) -> None:
    from fiduciaire_worker.cabinet_provisioning import provision_cabinet

    conn = _setup_db(tmp_path)
    with pytest.raises(ValueError, match="cabinet_id"):
        provision_cabinet(
            cabinet_id="Cabinet With Spaces!",
            cabinet_name="X", ville="Y", canton="GE", lang="fr",
            mandants=["m"], logiciel="bexio",
            clients_root=tmp_path / "clients", conn=conn,
        )


def test_provision_emits_audit_event(tmp_path: Path) -> None:
    from fiduciaire_worker.cabinet_provisioning import provision_cabinet

    conn = _setup_db(tmp_path)
    before = audit_log.list_events(conn, "cab-aud")
    assert len(before) == 0

    provision_cabinet(
        cabinet_id="cab-aud",
        cabinet_name="Aud Cab", ville="Y", canton="GE", lang="fr",
        mandants=["m-1", "m-2"], logiciel="bexio",
        clients_root=tmp_path / "clients", conn=conn,
        user_id="tanguy",
    )
    events = audit_log.list_events(conn, "cab-aud")
    provisions = [e for e in events if e.action == "cabinet_provisioned"]
    assert len(provisions) == 1
    ev = provisions[0]
    assert ev.entity_type == "cabinet"
    assert ev.entity_id == "cab-aud"
    assert ev.user_id == "tanguy"
    assert "Aud Cab" in (ev.after_json or "")
    assert '"mandants_count": 2' in (ev.after_json or "")


def test_provision_multi_mandant_isolation_chart_of_accounts(
    tmp_path: Path,
) -> None:
    """Plan comptable d'un cabinet ne fuit pas vers un autre."""
    from fiduciaire_worker.cabinet_provisioning import provision_cabinet

    conn = _setup_db(tmp_path)
    provision_cabinet(
        cabinet_id="cab-1",
        cabinet_name="C1", ville="X", canton="GE", lang="fr",
        mandants=["m"], logiciel="bexio",
        clients_root=tmp_path / "clients", conn=conn,
    )
    provision_cabinet(
        cabinet_id="cab-2",
        cabinet_name="C2", ville="X", canton="VD", lang="fr",
        mandants=["m"], logiciel="cresus",
        clients_root=tmp_path / "clients", conn=conn,
    )
    rows1 = conn.execute(
        "SELECT COUNT(*) FROM chart_of_accounts WHERE client_id=?",
        ("cab-1",),
    ).fetchone()[0]
    rows2 = conn.execute(
        "SELECT COUNT(*) FROM chart_of_accounts WHERE client_id=?",
        ("cab-2",),
    ).fetchone()[0]
    assert rows1 > 0 and rows1 == rows2
    # Aucun account avec client_id=NULL ou cabinet_id absurde
    leak = conn.execute(
        "SELECT COUNT(*) FROM chart_of_accounts "
        "WHERE client_id NOT IN ('cab-1','cab-2')"
    ).fetchone()[0]
    assert leak == 0
