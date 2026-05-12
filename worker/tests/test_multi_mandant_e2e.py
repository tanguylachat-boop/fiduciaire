"""Tests E2E multi-mandant — Sprint 1 §3.3.

Vérifie l'isolation cross-tenant à grande échelle :
- 3 mandants synthétiques sur la même DB
- entry_proposer, vendor_history, bexio_push : aucune fuite
- Concurrence (threads) : aucun mélange
- Logs : aucun client_id étranger
- Stress 100 docs × 3 mandants

Réutilise `worker/scripts/seed_multi_mandant_test.seed_all`.
Aucun appel LLM réel (vendor_history hit garanti via seed).
"""

from __future__ import annotations

import logging
import sqlite3
import sys
import threading
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "worker" / "src"))
sys.path.insert(0, str(REPO_ROOT / "worker" / "scripts"))

import httpx  # noqa: E402

from fiduciaire_worker import accounting_schema, db  # noqa: E402
from fiduciaire_worker import vendor_account_history as vah  # noqa: E402
from fiduciaire_worker.bexio_push import push_validated_entries  # noqa: E402
from fiduciaire_worker.entry_proposer import propose_entry  # noqa: E402
from seed_multi_mandant_test import MANDANT_SEEDS, seed_all  # noqa: E402


# --- Fixtures DB --------------------------------------------------------------


def _make_seeded_db(tmp_path: Path, docs_per_vendor: int = 2):
    conn = db.connect(tmp_path / "e2e.sqlite")
    db.init_schema(conn)
    accounting_schema.init_accounting_schema(conn)
    seeded = seed_all(conn, docs_per_vendor=docs_per_vendor)
    return conn, seeded


def _llm_panic(prompt: str) -> str:
    """Mock LLM qui FAIL si jamais appelé — garantit que vendor_history hit."""
    raise AssertionError(
        "LLM ne doit JAMAIS être appelé en E2E (vendor history pré-seedée). "
        f"Prompt reçu: {prompt[:200]}"
    )


_VAT_YAML = REPO_ROOT / "config" / "vat_codes_ch.yaml"
_PLAN_YAML = REPO_ROOT / "config" / "plan_comptable_pme_ch.yaml"


def _propose(conn, cabinet_id: str, doc_id: int):
    """Wrapper propose_entry avec paths config absolus pour les tests."""
    return propose_entry(
        conn, cabinet_id, doc_id,
        llm_caller=_llm_panic,
        vat_yaml_path=_VAT_YAML,
        plan_fallback_path=_PLAN_YAML,
    )


# --- Test 1 — Isolation seed --------------------------------------------------


def test_seed_creates_3_isolated_mandants(tmp_path: Path) -> None:
    conn, seeded = _make_seeded_db(tmp_path)
    assert set(seeded.keys()) == {
        "pilote-jura-01", "synth-vaud-02", "synth-berne-03",
    }
    for cabinet_id, doc_ids in seeded.items():
        assert len(doc_ids) == 10
        # Chaque doc est rattaché à son cabinet via client_slug
        rows = conn.execute(
            "SELECT COUNT(*) AS n FROM documents WHERE client_slug=?",
            (cabinet_id,),
        ).fetchone()
        assert rows["n"] == 10


def test_no_cross_tenant_vendors_in_db(tmp_path: Path) -> None:
    """Aucun vendor d'un mandant ne doit apparaître dans le vendor_account_history d'un autre."""
    conn, _ = _make_seeded_db(tmp_path)
    for src in MANDANT_SEEDS:
        for other in MANDANT_SEEDS:
            if other.cabinet_id == src.cabinet_id:
                continue
            for v in src.vendors:
                # Le vendor de `src` ne doit jamais figurer dans `other`
                row = conn.execute(
                    "SELECT vendor_id FROM vendor_account_history "
                    "WHERE client_id=? AND vendor_name=?",
                    (other.cabinet_id, v.name),
                ).fetchone()
                assert row is None, (
                    f"FUITE: vendor '{v.name}' de {src.cabinet_id} "
                    f"trouvé dans {other.cabinet_id}"
                )


# --- Test 2 — vah.lookup isolation -------------------------------------------


def test_vah_lookup_returns_only_own_cabinet(tmp_path: Path) -> None:
    conn, _ = _make_seeded_db(tmp_path)
    for m in MANDANT_SEEDS:
        # Chaque vendor du mandant est trouvé pour SON cabinet
        for v in m.vendors:
            reco = vah.lookup(conn, m.cabinet_id, v.name)
            assert reco is not None
            assert reco.vendor_name == v.name
            assert reco.recommended_account == v.account
        # Mais aucun vendor d'un autre mandant n'est trouvé
        other = next(o for o in MANDANT_SEEDS if o.cabinet_id != m.cabinet_id)
        for v_other in other.vendors:
            reco = vah.lookup(conn, m.cabinet_id, v_other.name)
            assert reco is None, (
                f"FUITE: vendor '{v_other.name}' de {other.cabinet_id} "
                f"visible dans lookup de {m.cabinet_id}"
            )


# --- Test 3 — entry_proposer isolation ---------------------------------------


def test_entry_proposer_uses_only_own_vendor_history(tmp_path: Path) -> None:
    conn, seeded = _make_seeded_db(tmp_path)
    # Pour chaque mandant, propose 1 entry sur 1 doc et vérifie l'isolation
    for m in MANDANT_SEEDS:
        doc_id = seeded[m.cabinet_id][0]
        proposed = _propose(conn, m.cabinet_id, doc_id)
        # Le compte proposé doit être l'un des comptes du mandant (pas d'un autre)
        own_accounts = {v.account for v in m.vendors}
        assert proposed.debit_account in own_accounts
        assert proposed.client_id == m.cabinet_id


# --- Test 4 — bexio_push isolation -------------------------------------------


def test_bexio_push_isolation_dry_run(tmp_path: Path) -> None:
    conn, seeded = _make_seeded_db(tmp_path)
    # Propose 2 entries par mandant et valide-les
    for m in MANDANT_SEEDS:
        for doc_id in seeded[m.cabinet_id][:2]:
            entry = _propose(conn, m.cabinet_id, doc_id)
            conn.execute(
                "UPDATE accounting_entries SET state='validated' WHERE id=?",
                (entry.db_id,),
            )

    # Push dry-run pour le mandant 1 uniquement
    cabinet_target = MANDANT_SEEDS[0].cabinet_id

    def handler(req: httpx.Request) -> httpx.Response:
        raise AssertionError("dry-run ne doit pas faire d'HTTP")

    http = httpx.Client(
        base_url="https://api.bexio.com",
        transport=httpx.MockTransport(handler),
    )

    summary = push_validated_entries(
        cabinet_id=cabinet_target, pat="FAKE", conn=conn,
        http_client=http, dry_run=True,
        account_no_to_bexio_id={"6510": 1, "6520": 2, "4200": 3, "6530": 4,
                                "6710": 5, "2000": 6},
        tax_code_to_bexio_id={"TN_NORM": 10, "TN_RED": 11, "EXO": 12},
    )

    # Le summary ne doit voir QUE les entries du mandant cible
    assert summary.total == 2
    assert summary.cabinet_id == cabinet_target

    # Vérification DB directe : aucune entry d'autre mandant ne porte un bexio_id
    rows = conn.execute(
        "SELECT client_id, COUNT(*) AS n FROM accounting_entries "
        "WHERE bexio_id IS NOT NULL GROUP BY client_id"
    ).fetchall()
    for row in rows:
        assert row["client_id"] == cabinet_target


# --- Test 5 — concurrence threads --------------------------------------------


def test_concurrent_proposers_no_cross_contamination(tmp_path: Path) -> None:
    """3 threads parallèles, 1 par mandant, propose des entries simultanément."""
    conn_main, seeded = _make_seeded_db(tmp_path)
    conn_main.close()
    db_path = tmp_path / "e2e.sqlite"

    errors: list[str] = []

    def worker(cabinet_id: str, doc_ids: list[int]) -> None:
        try:
            conn = db.connect(db_path)
            db.init_schema(conn)
            accounting_schema.init_accounting_schema(conn)
            for doc_id in doc_ids:
                propose_entry(
                    conn, cabinet_id, doc_id, llm_caller=_llm_panic,
                    vat_yaml_path=_VAT_YAML, plan_fallback_path=_PLAN_YAML,
                )
            conn.close()
        except Exception as exc:
            errors.append(f"{cabinet_id}: {exc}")

    threads = []
    for cabinet_id, doc_ids in seeded.items():
        t = threading.Thread(target=worker, args=(cabinet_id, doc_ids))
        threads.append(t)
        t.start()
    for t in threads:
        t.join(timeout=30)

    assert errors == [], f"Erreurs concurrence: {errors}"

    # Vérifie l'isolation final
    conn = db.connect(db_path)
    for cabinet_id in seeded.keys():
        own_count = conn.execute(
            "SELECT COUNT(*) AS n FROM accounting_entries WHERE client_id=?",
            (cabinet_id,),
        ).fetchone()["n"]
        assert own_count == 10
    # Total = 30 (10 × 3)
    total = conn.execute(
        "SELECT COUNT(*) AS n FROM accounting_entries"
    ).fetchone()["n"]
    assert total == 30
    conn.close()


# --- Test 6 — logs scrubbing -------------------------------------------------


def test_logs_never_contain_cross_tenant_data(tmp_path: Path, caplog) -> None:
    """Run un cycle complet pour mandant A, caplog ne doit pas mentionner les vendors de B/C."""
    caplog.set_level(logging.DEBUG, logger="fiduciaire")
    conn, seeded = _make_seeded_db(tmp_path)

    target = MANDANT_SEEDS[0]
    for doc_id in seeded[target.cabinet_id]:
        _propose(conn, target.cabinet_id, doc_id)

    log_text = "\n".join(rec.getMessage() for rec in caplog.records)

    for other in MANDANT_SEEDS[1:]:
        # client_id ne doit jamais apparaître dans les logs du cycle target
        assert other.cabinet_id not in log_text, (
            f"FUITE LOG: '{other.cabinet_id}' visible pendant cycle "
            f"de {target.cabinet_id}"
        )
        # Aucun vendor d'autre mandant ne doit fuiter non plus
        for v in other.vendors:
            assert v.name not in log_text, (
                f"FUITE LOG: vendor '{v.name}' de {other.cabinet_id} "
                f"visible pendant cycle de {target.cabinet_id}"
            )


# --- Test 7 — full pipeline 3 mandants indépendants --------------------------


def test_full_pipeline_3_mandants_independent_run(tmp_path: Path) -> None:
    """Cycle propose → validate → bexio_push dry-run, 3 mandants chacun ses résultats."""
    conn, seeded = _make_seeded_db(tmp_path)

    account_map = {"6510": 1, "6520": 2, "4200": 3, "6530": 4, "6710": 5,
                   "2000": 6}
    tax_map = {"TN_NORM": 10, "TN_RED": 11, "EXO": 12}

    def handler(req):
        raise AssertionError("dry-run ne doit pas faire d'HTTP")

    summaries: dict[str, object] = {}
    for m in MANDANT_SEEDS:
        # Propose toutes les entries du mandant
        for doc_id in seeded[m.cabinet_id]:
            e = _propose(conn, m.cabinet_id, doc_id)
            conn.execute(
                "UPDATE accounting_entries SET state='validated' WHERE id=?",
                (e.db_id,),
            )

        http = httpx.Client(
            base_url="https://api.bexio.com",
            transport=httpx.MockTransport(handler),
        )
        summaries[m.cabinet_id] = push_validated_entries(
            cabinet_id=m.cabinet_id, pat="FAKE", conn=conn,
            http_client=http, dry_run=True,
            account_no_to_bexio_id=account_map,
            tax_code_to_bexio_id=tax_map,
        )

    # Chaque mandant doit avoir EXACTEMENT 10 entries (pas + pas -)
    for cabinet_id, s in summaries.items():
        assert s.total == 10, f"{cabinet_id} → total {s.total} attendu 10"
        assert s.skipped_dry_run == 10


# --- Test 8 — stress 100 docs × 3 mandants -----------------------------------


@pytest.mark.slow
def test_stress_100_docs_3_mandants(tmp_path: Path) -> None:
    """300 docs au total (100/mandant via 5 vendors × 20 docs)."""
    conn = db.connect(tmp_path / "stress.sqlite")
    db.init_schema(conn)
    accounting_schema.init_accounting_schema(conn)
    seeded = seed_all(conn, docs_per_vendor=20)  # 5 vendors × 20 = 100/mandant
    conn.close()

    db_path = tmp_path / "stress.sqlite"

    errors: list[str] = []

    def worker(cabinet_id: str, doc_ids: list[int]) -> None:
        try:
            conn = db.connect(db_path)
            for doc_id in doc_ids:
                propose_entry(
                    conn, cabinet_id, doc_id, llm_caller=_llm_panic,
                    vat_yaml_path=_VAT_YAML, plan_fallback_path=_PLAN_YAML,
                )
            conn.close()
        except Exception as exc:
            errors.append(f"{cabinet_id}: {type(exc).__name__}: {exc}")

    threads = []
    for cabinet_id, doc_ids in seeded.items():
        assert len(doc_ids) == 100
        t = threading.Thread(target=worker, args=(cabinet_id, doc_ids))
        threads.append(t)
        t.start()
    for t in threads:
        t.join(timeout=60)

    assert errors == [], f"Erreurs stress: {errors}"

    conn = db.connect(db_path)
    for cabinet_id in seeded.keys():
        own_count = conn.execute(
            "SELECT COUNT(*) AS n FROM accounting_entries WHERE client_id=?",
            (cabinet_id,),
        ).fetchone()["n"]
        assert own_count == 100
    total = conn.execute(
        "SELECT COUNT(*) AS n FROM accounting_entries"
    ).fetchone()["n"]
    assert total == 300
    conn.close()


# --- Test 9 — bexio_push avec une seule cabinet n'affecte pas les autres ----


def test_bexio_push_live_isolation_no_other_mandant_pushed(tmp_path: Path) -> None:
    """Live push (HTTP mocké) pour mandant A → seul A est marqué bexio_id."""
    conn, seeded = _make_seeded_db(tmp_path)
    for m in MANDANT_SEEDS:
        for doc_id in seeded[m.cabinet_id][:3]:
            e = _propose(conn, m.cabinet_id, doc_id)
            conn.execute(
                "UPDATE accounting_entries SET state='validated' WHERE id=?",
                (e.db_id,),
            )

    target = MANDANT_SEEDS[0].cabinet_id
    seen_ids: list[str] = []

    def handler(req: httpx.Request) -> httpx.Response:
        seen_ids.append(str(req.url))
        return httpx.Response(201, json={"id": len(seen_ids) + 9000})

    http = httpx.Client(
        base_url="https://api.bexio.com",
        transport=httpx.MockTransport(handler),
    )

    summary = push_validated_entries(
        cabinet_id=target, pat="FAKE_PAT", conn=conn,
        http_client=http, dry_run=False,
        account_no_to_bexio_id={"6510": 1, "6520": 2, "4200": 3, "6530": 4,
                                "6710": 5, "2000": 6},
        tax_code_to_bexio_id={"TN_NORM": 10, "TN_RED": 11, "EXO": 12},
    )

    assert summary.pushed == 3
    # Vérifie qu'aucun autre mandant n'a un bexio_id
    pushed_per_cabinet = conn.execute(
        "SELECT client_id, COUNT(*) AS n FROM accounting_entries "
        "WHERE bexio_id IS NOT NULL GROUP BY client_id"
    ).fetchall()
    pushed_dict = {r["client_id"]: r["n"] for r in pushed_per_cabinet}
    assert pushed_dict == {target: 3}
