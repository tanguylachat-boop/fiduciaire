"""Mapping document → compte du plan comptable.

Charge le plan comptable depuis :
1. Cache Bexio (table bexio_sync, entity_type=account) si dispo
2. Sinon fallback config/plan_comptable_pme_ch.yaml

Pour un texte OCR, suggère top_k comptes pertinents via matching keywords.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

import yaml


@dataclass
class AccountSuggestion:
    code: str
    label: str
    score: float
    matched_keywords: list[str]


@dataclass
class PlanComptable:
    accounts: dict[str, dict[str, Any]] = field(default_factory=dict)
    source: str = "yaml"  # "bexio" | "yaml"

    @classmethod
    def from_bexio_cache(
        cls, conn: sqlite3.Connection, client_id: str
    ) -> Optional["PlanComptable"]:
        rows = conn.execute(
            "SELECT entity_id, payload_json FROM bexio_sync "
            "WHERE client_id = ? AND entity_type = 'account'",
            (client_id,),
        ).fetchall()
        if not rows:
            return None
        accounts: dict[str, dict[str, Any]] = {}
        for row in rows:
            payload = json.loads(row["payload_json"])
            code = (
                str(payload.get("account_no") or payload.get("code") or row["entity_id"])
            )
            accounts[code] = {
                "label_fr": payload.get("name", ""),
                "label_de": payload.get("name", ""),
                "classe": payload.get("account_type") or payload.get("type", "unknown"),
                # Keywords absents du pull Bexio brut → list vide.
                # Le matching keyword passe alors par le fallback YAML pour les défauts.
                "default_for_keywords": [],
            }
        return cls(accounts=accounts, source="bexio")

    @classmethod
    def from_yaml_fallback(cls, yaml_path: Path | str) -> "PlanComptable":
        data = yaml.safe_load(Path(yaml_path).read_text(encoding="utf-8"))
        return cls(accounts=data.get("accounts", {}), source="yaml")

    def get_account(self, code: str) -> dict[str, Any] | None:
        return self.accounts.get(code)

    def suggest_accounts(self, text: str, top_k: int = 3) -> list[AccountSuggestion]:
        """Score = nb_keywords_matchés / total_keywords_compte + bonus longs keywords."""
        text_low = text.lower()
        suggestions: list[AccountSuggestion] = []
        for code, data in self.accounts.items():
            kws = data.get("default_for_keywords", [])
            if not kws:
                continue
            matched = [kw for kw in kws if kw.lower() in text_low]
            if not matched:
                continue
            base = len(matched) / max(1, len(kws))
            # bonus pour keywords longs (>= 6 chars), généralement plus discriminants
            bonus = sum(0.1 for kw in matched if len(kw) >= 6)
            score = min(1.0, base + bonus)
            suggestions.append(
                AccountSuggestion(
                    code=code,
                    label=str(data.get("label_fr", code)),
                    score=score,
                    matched_keywords=matched,
                )
            )
        suggestions.sort(key=lambda s: s.score, reverse=True)
        return suggestions[:top_k]
