"""Étapes 5+6 — Renommage selon naming.pattern, routing dans data/clients/."""

from __future__ import annotations

import re
import shutil
import sqlite3
import unicodedata
from dataclasses import dataclass
from pathlib import Path

from . import db
from .classify import Classification
from .config import Config


@dataclass
class RouteResult:
    final_path: Path
    new_filename: str


def slugify(text: str | None) -> str:
    if not text:
        return "inconnu"
    nfkd = unicodedata.normalize("NFKD", text)
    ascii_str = "".join(c for c in nfkd if not unicodedata.combining(c))
    s = re.sub(r"[^a-zA-Z0-9]+", "-", ascii_str.lower()).strip("-")
    return s or "inconnu"


def resolve_client_slug(client_name: str | None, known_clients: list[dict]) -> str:
    """Match client name → slug du config.yaml (canonique uniquement)."""
    if not client_name:
        return "inconnu"
    target = client_name.strip().lower()
    for kc in known_clients:
        if kc.get("name", "").lower() == target:
            return kc.get("slug") or slugify(kc.get("name"))
    return slugify(client_name)


def build_filename(
    pattern: str,
    classification: Classification,
    sha256: str,
    type_short_map: dict,
    original_ext: str,
) -> str:
    type_short = type_short_map.get(classification.type or "autre", "XX")
    montant = (
        f"{classification.montant_chf:.2f}".replace(".", "-")
        if classification.montant_chf is not None
        else "0-00"
    )
    parts = {
        "date_iso": classification.date or "0000-00-00",
        "type_short": type_short,
        "client_slug": slugify(classification.client),
        "fournisseur_slug": slugify(classification.fournisseur),
        "montant_chf": montant,
        "hash6": sha256[:6],
    }
    name = pattern
    for k, v in parts.items():
        name = name.replace("{" + k + "}", str(v))
    if not name.lower().endswith(original_ext.lower()):
        # le pattern par défaut termine en .pdf — on remplace par l'extension réelle
        name = re.sub(r"\.[a-zA-Z0-9]+$", "", name) + original_ext
    return name


def route(
    archive_path: Path,
    classification: Classification,
    sha256: str,
    config: Config,
    conn: sqlite3.Connection,
    doc_id: int,
) -> RouteResult:
    """Copie le fichier archivé vers data/clients/<slug>/<année>/<type_long>/ avec nouveau nom."""
    client_slug = resolve_client_slug(classification.client, config.known_clients)
    type_long = classification.type or "autre"
    annee = (classification.date or "0000-00-00")[:4]

    sub = config.routing_pattern.format(
        client_slug=client_slug, annee=annee, type_long=type_long
    )
    target_dir = config.paths.clients_root / sub
    target_dir.mkdir(parents=True, exist_ok=True)

    new_name = build_filename(
        config.naming_pattern,
        classification,
        sha256,
        config.type_short_map,
        archive_path.suffix.lower(),
    )
    final_path = target_dir / new_name

    # collision : suffixe -dup1, -dup2
    if final_path.exists():
        stem, ext = final_path.stem, final_path.suffix
        i = 1
        while (target_dir / f"{stem}-dup{i}{ext}").exists():
            i += 1
        final_path = target_dir / f"{stem}-dup{i}{ext}"

    shutil.copy2(archive_path, final_path)

    db.update_document(
        conn,
        doc_id,
        status=db.STATUS_ROUTED,
        final_path=str(final_path),
        type=classification.type,
        client_slug=client_slug,
        doc_date=classification.date,
        montant_chf=classification.montant_chf,
    )
    db.log_action(
        conn,
        doc_id,
        action="route",
        payload={"final_path": str(final_path), "client_slug": client_slug},
    )
    return RouteResult(final_path=final_path, new_filename=new_name)
