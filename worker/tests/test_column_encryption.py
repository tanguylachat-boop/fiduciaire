"""Tests `fiduciaire_worker.encryption` — column encryption Sprint 1 §3.4-bis.

Préfixe `enc:v1:` + Fernet pour les colonnes texte sensibles
(description, reasoning, vendor_name, body_excerpt, from_addr).

L'autouse fixture local **désactive** le DISABLED par défaut du conftest
pour tester le chiffrement réel.
"""

from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "worker" / "src"))

from fiduciaire_worker import encryption  # noqa: E402
from fiduciaire_worker.encryption import (  # noqa: E402
    COLUMN_MARKER,
    ColumnMigrationResult,
    EncryptionError,
    MasterKey,
    decrypt_column_value,
    decrypt_dict_columns,
    encrypt_column_value,
    encrypt_dict_columns,
    is_encrypted_column_value,
    migrate_column_in_place,
)


@pytest.fixture(autouse=True)
def _enable_encryption(monkeypatch):
    """Override conftest : on TESTE le chiffrement réel ici."""
    monkeypatch.delenv("FIDUCIAIRE_ENCRYPTION_DISABLED", raising=False)
    yield


def _setup_key(monkeypatch, cabinet_id: str) -> MasterKey:
    key = MasterKey.generate(cabinet_id)
    env_var = encryption._env_var_for(cabinet_id)
    monkeypatch.setenv(env_var, key.value.decode("ascii"))
    # Empêche tentative d'écriture Keychain en tests
    monkeypatch.setattr(encryption, "_try_keyring_set", lambda c, k: True)
    return key


# --- encrypt / decrypt roundtrip --------------------------------------------


def test_encrypt_decrypt_roundtrip(monkeypatch) -> None:
    _setup_key(monkeypatch, "cab-x")
    token = encrypt_column_value("hello world", "cab-x")
    assert token is not None
    assert token.startswith(COLUMN_MARKER)
    plain = decrypt_column_value(token, "cab-x")
    assert plain == "hello world"


def test_encrypt_none_returns_none(monkeypatch) -> None:
    _setup_key(monkeypatch, "cab-x")
    assert encrypt_column_value(None, "cab-x") is None
    assert decrypt_column_value(None, "cab-x") is None


def test_encrypt_empty_string_returns_empty(monkeypatch) -> None:
    _setup_key(monkeypatch, "cab-x")
    assert encrypt_column_value("", "cab-x") == ""
    assert decrypt_column_value("", "cab-x") == ""


def test_encrypt_idempotent_does_not_double_encrypt(monkeypatch) -> None:
    _setup_key(monkeypatch, "cab-x")
    token = encrypt_column_value("secret", "cab-x")
    # 2e appel sur la même valeur déjà préfixée → retourne identique
    token2 = encrypt_column_value(token, "cab-x")
    assert token == token2


def test_decrypt_legacy_plain_value_returns_as_is(monkeypatch) -> None:
    """Valeur sans préfixe enc:v1: → considérée en clair (back-compat)."""
    _setup_key(monkeypatch, "cab-x")
    assert decrypt_column_value("plain text", "cab-x") == "plain text"


def test_is_encrypted_column_value_detection() -> None:
    assert is_encrypted_column_value("enc:v1:gAAAAAB...") is True
    assert is_encrypted_column_value("plain") is False
    assert is_encrypted_column_value(None) is False
    assert is_encrypted_column_value("") is False
    assert is_encrypted_column_value(123) is False  # type: ignore[arg-type]


# --- Multi-mandant isolation -------------------------------------------------


def test_multi_mandant_keys_isolated(monkeypatch) -> None:
    """Cabinet A ne peut PAS déchiffrer une valeur de cabinet B."""
    _setup_key(monkeypatch, "cab-a")
    _setup_key(monkeypatch, "cab-b")

    token_b = encrypt_column_value("secret de B", "cab-b")
    assert token_b is not None

    with pytest.raises(EncryptionError):
        decrypt_column_value(token_b, "cab-a")


# --- Dict helpers ------------------------------------------------------------


def test_encrypt_dict_columns_in_place(monkeypatch) -> None:
    _setup_key(monkeypatch, "cab-x")
    data = {"description": "facture swisscom", "amount_chf": 100.0,
            "other": "no touch"}
    out = encrypt_dict_columns(data, ["description"], "cab-x")
    assert out is data
    assert data["description"].startswith(COLUMN_MARKER)
    assert data["amount_chf"] == 100.0
    assert data["other"] == "no touch"


def test_decrypt_dict_columns_roundtrip(monkeypatch) -> None:
    _setup_key(monkeypatch, "cab-x")
    data = {"description": "hello", "reasoning": "long reasoning"}
    encrypt_dict_columns(data, ["description", "reasoning"], "cab-x")
    decrypt_dict_columns(data, ["description", "reasoning"], "cab-x")
    assert data["description"] == "hello"
    assert data["reasoning"] == "long reasoning"


def test_encrypt_dict_skips_missing_keys(monkeypatch) -> None:
    _setup_key(monkeypatch, "cab-x")
    data = {"description": "x"}
    encrypt_dict_columns(data, ["description", "absent"], "cab-x")
    assert data["description"].startswith(COLUMN_MARKER)
    assert "absent" not in data


# --- Mode disabled -----------------------------------------------------------


def test_disabled_mode_returns_value_as_is(monkeypatch) -> None:
    monkeypatch.setenv("FIDUCIAIRE_ENCRYPTION_DISABLED", "true")
    out = encrypt_column_value("hello", "any-cabinet")
    assert out == "hello"  # pas de chiffrement
    assert decrypt_column_value("plain", "any-cabinet") == "plain"


# --- Migration ---------------------------------------------------------------


def _seed_table(conn: sqlite3.Connection) -> None:
    """Petite table de test pour migrate_column_in_place."""
    conn.executescript(
        """
        CREATE TABLE entries (
            id INTEGER PRIMARY KEY,
            client_id TEXT NOT NULL,
            description TEXT
        );
        """
    )


def test_migrate_encrypts_plain_rows(monkeypatch, tmp_path: Path) -> None:
    _setup_key(monkeypatch, "cab-a")
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    _seed_table(conn)
    for desc in ("facture 1", "facture 2", "facture 3"):
        conn.execute(
            "INSERT INTO entries (client_id, description) VALUES (?, ?)",
            ("cab-a", desc),
        )

    result = migrate_column_in_place(
        conn, table="entries", cabinet_id_column="client_id",
        target_column="description", cabinet_id="cab-a",
    )
    assert isinstance(result, ColumnMigrationResult)
    assert result.rows_encrypted == 3

    rows = conn.execute(
        "SELECT description FROM entries WHERE client_id='cab-a'"
    ).fetchall()
    for r in rows:
        assert r["description"].startswith(COLUMN_MARKER)


def test_migrate_skips_already_encrypted(monkeypatch) -> None:
    _setup_key(monkeypatch, "cab-a")
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    _seed_table(conn)
    # 2 rows déjà chiffrées + 1 en clair
    enc = encrypt_column_value("déjà chiffré", "cab-a")
    conn.execute("INSERT INTO entries (client_id, description) VALUES (?, ?)",
                 ("cab-a", enc))
    conn.execute("INSERT INTO entries (client_id, description) VALUES (?, ?)",
                 ("cab-a", enc))
    conn.execute("INSERT INTO entries (client_id, description) VALUES (?, ?)",
                 ("cab-a", "à chiffrer"))

    result = migrate_column_in_place(
        conn, "entries", "client_id", "description", "cab-a",
    )
    assert result.rows_encrypted == 1
    assert result.rows_skipped_already_encrypted == 2


def test_migrate_multi_mandant_isolation(monkeypatch) -> None:
    """Migration pour cab-a ne touche pas les rows de cab-b."""
    _setup_key(monkeypatch, "cab-a")
    _setup_key(monkeypatch, "cab-b")
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    _seed_table(conn)
    conn.execute("INSERT INTO entries (client_id, description) VALUES (?, ?)",
                 ("cab-a", "data-a"))
    conn.execute("INSERT INTO entries (client_id, description) VALUES (?, ?)",
                 ("cab-b", "data-b"))

    migrate_column_in_place(conn, "entries", "client_id", "description", "cab-a")

    row_a = conn.execute(
        "SELECT description FROM entries WHERE client_id='cab-a'"
    ).fetchone()
    row_b = conn.execute(
        "SELECT description FROM entries WHERE client_id='cab-b'"
    ).fetchone()
    assert row_a["description"].startswith(COLUMN_MARKER)
    assert row_b["description"] == "data-b"  # intact


def test_migrate_dry_run_does_not_modify(monkeypatch) -> None:
    _setup_key(monkeypatch, "cab-a")
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    _seed_table(conn)
    conn.execute("INSERT INTO entries (client_id, description) VALUES (?, ?)",
                 ("cab-a", "to encrypt"))

    result = migrate_column_in_place(
        conn, "entries", "client_id", "description", "cab-a",
        dry_run=True,
    )
    assert result.rows_encrypted == 1
    # Mais la valeur n'a pas changé
    row = conn.execute("SELECT description FROM entries").fetchone()
    assert row["description"] == "to encrypt"


# --- Intégration modules métier (encryption ACTIVE) -------------------------


def test_entry_proposer_persists_encrypted_description(monkeypatch, tmp_path) -> None:
    """Quand encryption ON, entry_proposer.propose_entry stocke description
    chiffrée en DB mais retourne l'objet en clair."""
    from fiduciaire_worker import accounting_schema, db
    from fiduciaire_worker.entry_proposer import propose_entry

    _setup_key(monkeypatch, "cab-x")

    conn = db.connect(tmp_path / "x.sqlite")
    db.init_schema(conn)
    accounting_schema.init_accounting_schema(conn)

    # Seed minimal : document + vendor history pour skip LLM
    doc_id, _ = db.insert_document(conn, "sha1", "x.pdf", "/arch/x.pdf")
    import json
    conn.execute(
        "UPDATE documents SET classification_json=?, montant_chf=?, "
        "doc_date='2026-04-15' WHERE id=?",
        (json.dumps({"fournisseur": "Swisscom AG"}), 100.0, doc_id),
    )
    conn.execute(
        "INSERT INTO vendor_account_history "
        "(client_id, vendor_id, vendor_name, account, vat_code, "
        " occurrences, last_seen) VALUES (?, ?, ?, ?, ?, ?, '2026-04-01')",
        ("cab-x", "v1", "Swisscom AG", "6510", "TN_NORM", 10),
    )

    def _llm_panic(p):
        raise AssertionError("LLM ne doit pas être appelé")

    entry = propose_entry(
        conn, "cab-x", doc_id, llm_caller=_llm_panic,
        vat_yaml_path=REPO_ROOT / "config" / "vat_codes_ch.yaml",
        plan_fallback_path=REPO_ROOT / "config" / "plan_comptable_pme_ch.yaml",
    )

    # L'objet retourné est en clair
    assert entry.description and not entry.description.startswith(COLUMN_MARKER)

    # Mais la DB contient une valeur chiffrée
    row = conn.execute(
        "SELECT description FROM accounting_entries WHERE id=?",
        (entry.db_id,),
    ).fetchone()
    assert row["description"].startswith(COLUMN_MARKER)

    # decrypt manuel donne la même chose
    decrypted = decrypt_column_value(row["description"], "cab-x")
    assert decrypted == entry.description


def test_vendor_history_lookup_decrypts_name(monkeypatch, tmp_path) -> None:
    """vendor_history.lookup decrypt vendor_name avant retour."""
    from fiduciaire_worker import accounting_schema, db, vendor_account_history as vah

    _setup_key(monkeypatch, "cab-y")

    conn = db.connect(tmp_path / "y.sqlite")
    db.init_schema(conn)
    accounting_schema.init_accounting_schema(conn)

    # Insert via le helper qui chiffre (build_history) — ou direct chiffré
    enc_name = encrypt_column_value("Romande Energie SA", "cab-y")
    conn.execute(
        "INSERT INTO vendor_account_history "
        "(client_id, vendor_id, vendor_name, account, vat_code, "
        " occurrences, last_seen) VALUES (?, ?, ?, ?, ?, ?, '2026-04-01')",
        ("cab-y", "vendor-RE", enc_name, "6520", "TN_NORM", 5),
    )

    # lookup exact match sur vendor_id (vendor_id reste en clair)
    reco = vah.lookup(conn, "cab-y", "vendor-RE")
    assert reco is not None
    assert reco.vendor_name == "Romande Energie SA"  # decrypted

    # lookup fuzzy : LIKE SQL ne matche pas (le contenu est chiffré),
    # mais le fallback in-memory decrypt + match doit fonctionner
    reco2 = vah.lookup(conn, "cab-y", "Romande")
    assert reco2 is not None
    assert reco2.vendor_name == "Romande Energie SA"


def test_imap_fetch_persists_encrypted_body_excerpt(monkeypatch, tmp_path) -> None:
    """imap_fetch INSERT stocke body_excerpt + from_addr chiffrés."""
    from fiduciaire_worker import accounting_schema, db
    from fiduciaire_worker.imap_fetch import _insert_email_message
    from fiduciaire_worker.email_parser import ParsedEmail

    _setup_key(monkeypatch, "cab-z")

    conn = db.connect(tmp_path / "z.sqlite")
    db.init_schema(conn)
    accounting_schema.init_accounting_schema(conn)

    parsed = ParsedEmail(
        message_id="<m1@x.ch>", date_received="2026-04-01",
        from_addr="billing@swisscom.ch", to_addr="cab@x.ch",
        subject="Facture", body_excerpt="Voici votre facture...",
        encryption_status="plain", attachments=[], size_bytes=1024,
    )
    email_id = _insert_email_message(conn, "cab-z", "INBOX", 1, 42, parsed)

    row = conn.execute(
        "SELECT body_excerpt, from_addr FROM email_messages WHERE id=?",
        (email_id,),
    ).fetchone()
    assert row["body_excerpt"].startswith(COLUMN_MARKER)
    assert row["from_addr"].startswith(COLUMN_MARKER)

    # decrypt manuel cohérent
    assert decrypt_column_value(row["body_excerpt"], "cab-z") == "Voici votre facture..."
    assert decrypt_column_value(row["from_addr"], "cab-z") == "billing@swisscom.ch"


def test_bexio_push_decrypts_description_before_send(monkeypatch, tmp_path) -> None:
    """bexio_push lit description chiffrée en DB, decrypt avant POST Bexio."""
    import httpx
    from fiduciaire_worker import accounting_schema, db
    from fiduciaire_worker.bexio_push import push_validated_entries

    _setup_key(monkeypatch, "cab-w")

    conn = db.connect(tmp_path / "w.sqlite")
    db.init_schema(conn)
    accounting_schema.init_accounting_schema(conn)
    doc_id, _ = db.insert_document(conn, "sha1", "x.pdf", "/arch/x.pdf")

    # INSERT entry avec description chiffrée
    enc_desc = encrypt_column_value("Achat fournitures bureau", "cab-w")
    conn.execute(
        "INSERT INTO accounting_entries "
        "(client_id, source_document_id, date, debit_account, credit_account, "
        " amount_chf, vat_code, vat_amount, description, "
        " confidence_account, confidence_vat, state) "
        "VALUES (?, ?, '2026-04-15', '6510', '2000', 100.0, 'TN_NORM', 8.1, "
        "        ?, 0.9, 0.9, 'validated')",
        ("cab-w", doc_id, enc_desc),
    )

    received_bodies: list[dict] = []
    def handler(req):
        import json as j
        received_bodies.append(j.loads(req.content.decode()))
        return httpx.Response(201, json={"id": 1})

    http = httpx.Client(
        base_url="https://api.bexio.com",
        transport=httpx.MockTransport(handler),
    )

    push_validated_entries(
        cabinet_id="cab-w", pat="FAKE", conn=conn, http_client=http,
        dry_run=False,
        account_no_to_bexio_id={"6510": 1, "2000": 2},
        tax_code_to_bexio_id={"TN_NORM": 10},
    )

    # Bexio a reçu la description EN CLAIR
    assert len(received_bodies) == 1
    body_desc = received_bodies[0]["entries"][0]["description"]
    assert body_desc == "Achat fournitures bureau"
    assert not body_desc.startswith(COLUMN_MARKER)


def test_migrate_skips_null_and_empty(monkeypatch) -> None:
    _setup_key(monkeypatch, "cab-a")
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    _seed_table(conn)
    conn.execute("INSERT INTO entries (client_id, description) VALUES (?, ?)",
                 ("cab-a", None))
    conn.execute("INSERT INTO entries (client_id, description) VALUES (?, ?)",
                 ("cab-a", ""))
    conn.execute("INSERT INTO entries (client_id, description) VALUES (?, ?)",
                 ("cab-a", "real"))

    result = migrate_column_in_place(
        conn, "entries", "client_id", "description", "cab-a",
    )
    assert result.rows_encrypted == 1
    assert result.rows_skipped_null_or_empty == 2
