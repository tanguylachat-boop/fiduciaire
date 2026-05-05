"""Populate data/fiduciaire.sqlite à partir du CSV d'un bench récent.

Utile pour démarrer le dashboard /review avec des données réelles sans avoir
à relancer le watcher complet sur data/inbox/. Idempotent (INSERT OR IGNORE).

Statut du doc :
- routed       : tous les champs scorés OK (type, client, date, montant_chf)
- needs_review : un ou plusieurs champs ratés
- failed       : ligne avec error dans le CSV bench

Usage :
  .venv/bin/python scripts/seed_db_from_bench.py [--csv path] [--db path] [--reset]
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import sqlite3
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DB = REPO_ROOT / "data" / "fiduciaire.sqlite"
BENCH_DIR = REPO_ROOT / "data" / "bench-results"
SAMPLES_DIR = REPO_ROOT / "data" / "samples"

SCHEMA = """
CREATE TABLE IF NOT EXISTS documents (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  sha256 TEXT UNIQUE NOT NULL,
  original_filename TEXT NOT NULL,
  archive_path TEXT NOT NULL,
  ocr_text TEXT,
  ocr_engine TEXT,
  classification_json TEXT,
  type TEXT,
  client_slug TEXT,
  doc_date TEXT,
  montant_chf REAL,
  status TEXT NOT NULL,
  needs_review_reason TEXT,
  final_path TEXT,
  created_at TEXT NOT NULL DEFAULT (datetime('now')),
  updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS actions (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  document_id INTEGER NOT NULL REFERENCES documents(id),
  action TEXT NOT NULL,
  payload_json TEXT,
  duration_ms INTEGER,
  ok INTEGER NOT NULL DEFAULT 1,
  error TEXT,
  created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_documents_status ON documents(status);
CREATE INDEX IF NOT EXISTS idx_actions_document ON actions(document_id);
"""


def latest_bench_csv() -> Path:
    csvs = sorted(BENCH_DIR.glob("bench-*.csv"), key=lambda p: p.stat().st_mtime, reverse=True)
    if not csvs:
        sys.exit(f"Aucun CSV dans {BENCH_DIR}. Lance d'abord un bench.")
    return csvs[0]


def slugify(s: str | None) -> str | None:
    if not s:
        return None
    s = s.lower()
    repl = {"é": "e", "è": "e", "ê": "e", "ë": "e", "à": "a", "â": "a",
            "ï": "i", "î": "i", "ô": "o", "ö": "o", "ù": "u", "û": "u",
            "ü": "u", "ç": "c", "ñ": "n", "&": "et", "'": " ", "\"": " "}
    for k, v in repl.items():
        s = s.replace(k, v)
    out = []
    for ch in s:
        if ch.isalnum():
            out.append(ch)
        elif ch in (" ", "-", "_", "."):
            out.append("-")
    slug = "".join(out)
    while "--" in slug:
        slug = slug.replace("--", "-")
    return slug.strip("-") or None


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--csv", type=Path, default=None,
                        help="CSV bench à ingérer (default = le plus récent)")
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    parser.add_argument("--reset", action="store_true",
                        help="Supprime la DB avant ingestion (idempotent dev)")
    args = parser.parse_args()

    csv_path = (args.csv or latest_bench_csv()).resolve()
    if not csv_path.exists():
        sys.exit(f"CSV introuvable : {csv_path}")

    if args.reset and args.db.exists():
        args.db.unlink()
        print(f"✗ {args.db.relative_to(REPO_ROOT)} supprimée (--reset)")

    args.db.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(args.db), isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)

    inserted = 0
    skipped = 0

    with csv_path.open(encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            filename = row.get("filename", "").strip()
            if not filename:
                continue
            pdf_path = SAMPLES_DIR / filename
            if pdf_path.exists():
                sha = hashlib.sha256(pdf_path.read_bytes()).hexdigest()
            else:
                sha = hashlib.sha256(filename.encode("utf-8")).hexdigest()

            error = (row.get("error") or "").strip()
            ok_type = row.get("ok_type", "False").strip().lower() == "true"
            ok_client = row.get("ok_client", "False").strip().lower() == "true"
            ok_date = row.get("ok_date", "False").strip().lower() == "true"
            ok_montant = row.get("ok_montant", "False").strip().lower() == "true"

            if error:
                status = "failed"
                review_reason = error
            elif ok_type and ok_client and ok_date and ok_montant:
                status = "routed"
                review_reason = None
            else:
                status = "needs_review"
                misses = [
                    f for f, ok in (("type", ok_type), ("client", ok_client),
                                    ("date", ok_date), ("montant", ok_montant))
                    if not ok
                ]
                review_reason = "champs ratés: " + ", ".join(misses) if misses else None

            type_v = (row.get("got_type") or "").strip() or None
            client_v = (row.get("got_client") or "").strip() or None
            date_v = (row.get("got_date") or "").strip() or None
            montant_raw = (row.get("got_montant") or "").strip()
            montant_v = None
            if montant_raw:
                try:
                    montant_v = float(montant_raw)
                except ValueError:
                    montant_v = None

            classification_json = json.dumps({
                "type": type_v,
                "client": client_v,
                "date": date_v,
                "montant_chf": montant_v,
                "raisonnement": (row.get("raisonnement") or "")[:480],
                "model": row.get("model"),
                "prompt": row.get("prompt"),
            }, ensure_ascii=False)

            cur = conn.execute(
                """INSERT OR IGNORE INTO documents
                   (sha256, original_filename, archive_path, ocr_text, ocr_engine,
                    classification_json, type, client_slug, doc_date, montant_chf,
                    status, needs_review_reason, final_path)
                   VALUES (?, ?, ?, NULL, 'tesseract', ?, ?, ?, ?, ?, ?, ?, NULL)""",
                (
                    sha, filename, str(pdf_path), classification_json,
                    type_v, slugify(client_v), date_v, montant_v,
                    status, review_reason,
                ),
            )
            if cur.rowcount == 1:
                doc_id = cur.lastrowid
                inserted += 1
                latency_s = row.get("latency_s", "0").strip()
                duration_ms = None
                try:
                    duration_ms = int(float(latency_s) * 1000) if latency_s else None
                except ValueError:
                    duration_ms = None
                conn.execute(
                    """INSERT INTO actions
                       (document_id, action, payload_json, duration_ms, ok, error)
                       VALUES (?, 'classify', ?, ?, ?, ?)""",
                    (doc_id, classification_json, duration_ms,
                     0 if error else 1, error or None),
                )
            else:
                skipped += 1

    conn.close()
    print(f"✓ DB seedée : {args.db.relative_to(REPO_ROOT)}")
    print(f"  CSV source : {csv_path.relative_to(REPO_ROOT)}")
    print(f"  Insérés    : {inserted}")
    print(f"  Skippés    : {skipped} (déjà présents)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
