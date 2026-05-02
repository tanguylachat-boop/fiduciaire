"""Étape 4 — Classification LLM via Ollama.

Prompt = template (classify_v2_fewshot.txt par défaut) + KNOWN_CLIENTS + OCR_TEXT.
JSON strict. 1 retry sur erreur de parsing avec instruction explicite.
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx

ALLOWED_TYPES = {
    "facture_fournisseur",
    "note_frais",
    "releve_bancaire",
    "document_fiscal",
    "contrat",
    "courrier",
    "autre",
}


@dataclass
class Classification:
    type: str | None = None
    type_confidence: float = 0.0
    client: str | None = None
    client_confidence: float = 0.0
    date: str | None = None
    date_confidence: float = 0.0
    montant_chf: float | None = None
    montant_confidence: float = 0.0
    fournisseur: str | None = None
    devise: str | None = None
    raisonnement: str = ""
    raw_response: str = ""
    latency_s: float = 0.0
    error: str | None = None
    retries: int = 0
    sources: dict[str, str] = field(default_factory=dict)  # field → "qr" | "llm"

    def confidence(self, field_name: str) -> float:
        return getattr(self, f"{field_name}_confidence", 0.0)


def _build_prompt(template: str, known_clients: list[dict], ocr_text: str) -> str:
    return template.replace(
        "{KNOWN_CLIENTS_JSON}", json.dumps(known_clients, ensure_ascii=False, indent=2)
    ).replace("{OCR_TEXT}", ocr_text)


def _coerce_montant(v: Any) -> float | None:
    if v is None:
        return None
    try:
        return round(float(v), 2)
    except (TypeError, ValueError):
        return None


def _coerce_date(v: Any) -> str | None:
    if not v:
        return None
    s = str(v).strip()
    return s[:10] if len(s) >= 10 else None


def _from_dict(payload: dict[str, Any]) -> Classification:
    c = Classification()
    t = payload.get("type")
    c.type = str(t) if t in ALLOWED_TYPES else None
    c.type_confidence = float(payload.get("type_confidence") or 0.0)
    c.client = payload.get("client") or None
    c.client_confidence = float(payload.get("client_confidence") or 0.0)
    c.date = _coerce_date(payload.get("date"))
    c.date_confidence = float(payload.get("date_confidence") or 0.0)
    c.montant_chf = _coerce_montant(payload.get("montant_chf"))
    c.montant_confidence = float(payload.get("montant_confidence") or 0.0)
    c.fournisseur = payload.get("fournisseur") or None
    c.devise = payload.get("devise") or None
    c.raisonnement = str(payload.get("raisonnement_court") or "")[:480]
    return c


def _call_ollama(
    endpoint: str,
    model: str,
    prompt: str,
    timeout_s: int,
    num_predict: int,
    temperature: float,
) -> tuple[float, str]:
    payload = {
        "model": model,
        "prompt": prompt,
        "format": "json",
        "stream": False,
        "options": {"temperature": temperature, "num_predict": num_predict},
    }
    t0 = time.perf_counter()
    r = httpx.post(f"{endpoint}/api/generate", json=payload, timeout=timeout_s)
    elapsed = time.perf_counter() - t0
    r.raise_for_status()
    return elapsed, r.json().get("response", "")


def classify(
    ocr_text: str,
    known_clients: list[dict],
    template_path: Path,
    endpoint: str,
    model: str,
    timeout_s: int = 120,
    num_predict: int = 512,
    temperature: float = 0.0,
) -> Classification:
    template = template_path.read_text(encoding="utf-8")
    prompt = _build_prompt(template, known_clients, ocr_text)

    total_latency = 0.0
    last_response = ""
    last_error: str | None = None

    for attempt in range(2):
        try:
            elapsed, response = _call_ollama(
                endpoint, model, prompt, timeout_s, num_predict, temperature
            )
        except Exception as e:
            last_error = f"{type(e).__name__}: {e}"
            break
        total_latency += elapsed
        last_response = response
        try:
            parsed = json.loads(response)
        except json.JSONDecodeError as e:
            last_error = f"json: {e}"
            if attempt == 0:
                prompt = (
                    prompt
                    + "\n\nLa réponse précédente n'était pas un JSON valide. "
                    "Renvoie UNIQUEMENT un JSON parsable, rien d'autre."
                )
                continue
            break
        c = _from_dict(parsed)
        c.raw_response = response
        c.latency_s = total_latency
        c.retries = attempt
        for f in ("type", "client", "date", "montant_chf", "fournisseur", "devise"):
            c.sources[f] = "llm"
        return c

    c = Classification()
    c.raw_response = last_response
    c.latency_s = total_latency
    c.error = last_error
    c.retries = 1
    return c


def warmup_ollama(endpoint: str, model: str, timeout_s: int = 120) -> bool:
    """Précharge le modèle Ollama en RAM pour éviter le timeout 60s
    au premier doc réel (cold start). Appel léger (1 token) qui force
    Ollama à charger les poids du modèle.

    Non bloquant : log un warning si échec, retourne False, mais ne lève pas.
    """
    log = logging.getLogger("fiduciaire.classify")
    payload = {
        "model": model,
        "prompt": "ok",
        "format": "json",
        "stream": False,
        "options": {"temperature": 0.0, "num_predict": 1},
    }
    t0 = time.perf_counter()
    try:
        r = httpx.post(f"{endpoint}/api/generate", json=payload, timeout=timeout_s)
        r.raise_for_status()
        elapsed = time.perf_counter() - t0
        log.info("Ollama warmup OK (%s) en %.1fs", model, elapsed)
        return True
    except Exception as e:
        log.warning("Ollama warmup échec (non bloquant) pour %s: %s", model, e)
        return False


def merge_with_qr(c: Classification, qr) -> Classification:
    """Si QR-bill parsé, écrase montant/devise/fournisseur (confidence 1.0).

    Le client du QR (débiteur) est gardé en mémoire mais on laisse le LLM faire
    le mapping vers la liste canonique — sauf si le LLM a mis null, auquel cas
    on prend la valeur QR brute.
    """
    if qr is None:
        return c
    if qr.montant_chf is not None:
        c.montant_chf = qr.montant_chf
        c.montant_confidence = 1.0
        c.sources["montant_chf"] = "qr"
    if qr.devise:
        c.devise = qr.devise
        c.sources["devise"] = "qr"
    if qr.fournisseur:
        c.fournisseur = qr.fournisseur
        c.sources["fournisseur"] = "qr"
    if not c.client and qr.client_raw:
        c.client = qr.client_raw
        c.client_confidence = max(c.client_confidence, 0.5)
        c.sources["client"] = "qr"
    return c
