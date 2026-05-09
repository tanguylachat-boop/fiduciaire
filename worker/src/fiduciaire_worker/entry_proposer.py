"""CŒUR Sprint 0a — propose une AccountingEntry pour un document classifié.

Stratégie 2 niveaux :
1. Si vendor_account_history.lookup() retourne haute confiance → propose direct (skip LLM).
2. Sinon → prompt LLM avec plan comptable + suggestions keyword en contexte.

Le LLM répond en JSON strict via Ollama format=json. 1 retry si JSON cassé.
Persistance : table accounting_entries avec state='proposed'.
"""

from __future__ import annotations

import json
import logging
import sqlite3
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path
from typing import Any, Callable

import httpx

from . import accounting_schema, plan_comptable_mapper, vat_code_detector
from . import vendor_account_history as vah

VENDOR_HISTORY_CONFIDENCE_THRESHOLD = 0.8

_log = logging.getLogger("fiduciaire.entry_proposer")


@dataclass
class ProposedEntry:
    client_id: str
    source_document_id: int
    date: str
    debit_account: str
    credit_account: str
    amount_chf: float
    vat_code: str
    vat_amount: float
    description: str
    confidence_account: float
    confidence_vat: float
    reasoning: str
    state: str = accounting_schema.ENTRY_STATE_PROPOSED
    sources: dict[str, str] = field(default_factory=dict)
    db_id: int | None = None


def propose_entry(
    conn: sqlite3.Connection,
    client_id: str,
    source_document_id: int,
    plan: plan_comptable_mapper.PlanComptable | None = None,
    ollama_endpoint: str = "http://localhost:11434",
    ollama_model: str = "llama3.3:70b-instruct-q4_K_M",
    prompt_template_path: Path | str = "worker/prompts/entry_proposer_v1.txt",
    vat_yaml_path: Path | str = "config/vat_codes_ch.yaml",
    plan_fallback_path: Path | str = "config/plan_comptable_pme_ch.yaml",
    timeout_s: int = 120,
    num_ctx: int = 4096,
    persist: bool = True,
    llm_caller: Callable[[str], str] | None = None,
) -> ProposedEntry:
    """Génère une proposition d'écriture comptable. Persiste si persist=True.

    `llm_caller` permet d'injecter un mock dans les tests (signature: prompt -> raw_response).
    """
    doc = conn.execute(
        "SELECT * FROM documents WHERE id = ?", (source_document_id,)
    ).fetchone()
    if doc is None:
        raise ValueError(f"document {source_document_id} introuvable")

    classification = (
        json.loads(doc["classification_json"]) if doc["classification_json"] else {}
    )
    fournisseur = classification.get("fournisseur") or ""
    montant_chf = float(doc["montant_chf"] or 0)
    doc_date = doc["doc_date"] or ""
    ocr_text = doc["ocr_text"] or ""

    # 1. Plan comptable : Bexio cache prioritaire, fallback YAML
    if plan is None:
        plan = plan_comptable_mapper.PlanComptable.from_bexio_cache(conn, client_id)
        if plan is None:
            plan = plan_comptable_mapper.PlanComptable.from_yaml_fallback(plan_fallback_path)

    # 2. Niveau 1 — vendor history shortcut
    reco = vah.lookup(conn, client_id, fournisseur) if fournisseur else None
    if reco and reco.confidence >= VENDOR_HISTORY_CONFIDENCE_THRESHOLD:
        _log.info(
            "vendor history hit %s → %s (conf %.2f, %d occurrences)",
            reco.vendor_name,
            reco.recommended_account,
            reco.confidence,
            reco.occurrences,
        )
        vat_result = _detect_vat(ocr_text, montant_chf, classification, Path(vat_yaml_path))
        # Si détecteur VAT confiant, il l'emporte ; sinon on prend la reco vendor
        if vat_result.confidence >= 0.85:
            vat_code = vat_result.code
            vat_source = "detector"
            confidence_vat = vat_result.confidence
        else:
            vat_code = reco.recommended_vat_code
            vat_source = "vendor_history"
            confidence_vat = reco.confidence
        entry = ProposedEntry(
            client_id=client_id,
            source_document_id=source_document_id,
            date=doc_date,
            debit_account=reco.recommended_account,
            credit_account="2000",  # défaut pour une facture fournisseur
            amount_chf=montant_chf,
            vat_code=vat_code,
            vat_amount=vat_code_detector.compute_vat_amount(
                montant_chf, vat_code, vat_yaml_path
            ),
            description=f"{reco.vendor_name[:60]}",
            confidence_account=reco.confidence,
            confidence_vat=confidence_vat,
            reasoning=(
                f"Vendor history match ({reco.occurrences} occurrences). "
                f"VAT: {vat_result.reasoning}"
            ),
            sources={"account": "vendor_history", "vat_code": vat_source},
        )
        return _persist(conn, entry, persist)

    # 3. Niveau 2 — LLM
    suggestions = plan.suggest_accounts(ocr_text, top_k=5)
    prompt = _build_prompt(
        Path(prompt_template_path),
        suggestions=suggestions,
        ocr_text=ocr_text,
        fournisseur=fournisseur,
        montant_chf=montant_chf,
        doc_date=doc_date,
    )

    if llm_caller is None:
        llm_caller = lambda p: _call_ollama(  # noqa: E731
            ollama_endpoint, ollama_model, p, timeout_s, num_ctx
        )

    raw = llm_caller(prompt)
    parsed = _parse_llm_json(raw, llm_caller, prompt)

    debit = str(parsed.get("debit_account", "")) or (
        suggestions[0].code if suggestions else "6500"
    )
    credit = str(parsed.get("credit_account", "2000"))
    confidence_account = float(parsed.get("confidence_account", 0.6))

    # Cross-check VAT via détecteur
    vat_result = _detect_vat(ocr_text, montant_chf, classification, Path(vat_yaml_path))
    if vat_result.confidence >= 0.7:
        vat_code = vat_result.code
        vat_source = "detector"
        confidence_vat = vat_result.confidence
    else:
        vat_code = str(parsed.get("vat_code", "TN_NORM"))
        vat_source = "llm"
        confidence_vat = float(parsed.get("confidence_vat", 0.5))

    entry = ProposedEntry(
        client_id=client_id,
        source_document_id=source_document_id,
        date=doc_date,
        debit_account=debit,
        credit_account=credit,
        amount_chf=montant_chf,
        vat_code=vat_code,
        vat_amount=vat_code_detector.compute_vat_amount(
            montant_chf, vat_code, vat_yaml_path
        ),
        description=str(parsed.get("description", fournisseur))[:200],
        confidence_account=confidence_account,
        confidence_vat=confidence_vat,
        reasoning=str(parsed.get("reasoning", ""))[:500],
        sources={"account": "llm", "vat_code": vat_source},
    )
    return _persist(conn, entry, persist)


# --- Helpers internes ---------------------------------------------------------


def _detect_vat(
    ocr_text: str, montant_ttc: float, classification: dict[str, Any], vat_yaml_path: Path
) -> vat_code_detector.VatDetectionResult:
    montant_ht: Decimal | None = None
    montant_tva: Decimal | None = None
    if "montant_tva" in classification:
        try:
            montant_tva = Decimal(str(classification["montant_tva"]))
            if "montant_ht" in classification:
                montant_ht = Decimal(str(classification["montant_ht"]))
            elif montant_ttc:
                montant_ht = Decimal(str(montant_ttc)) - montant_tva
        except Exception:
            pass
    return vat_code_detector.detect_vat_code(
        text=ocr_text,
        montant_ht=montant_ht,
        montant_tva=montant_tva,
        config_path=vat_yaml_path,
    )


def _build_prompt(
    template_path: Path,
    suggestions: list[plan_comptable_mapper.AccountSuggestion],
    ocr_text: str,
    fournisseur: str,
    montant_chf: float,
    doc_date: str,
) -> str:
    template = Path(template_path).read_text(encoding="utf-8")
    sugg_lines = (
        "\n".join(
            f"  {s.code} ({s.label}) — match: {', '.join(s.matched_keywords)}"
            for s in suggestions
        )
        or "  (aucune suggestion automatique)"
    )
    return (
        template.replace("{OCR_TEXT}", ocr_text[:3000])
        .replace("{FOURNISSEUR}", fournisseur or "inconnu")
        .replace("{MONTANT_CHF}", str(montant_chf or 0))
        .replace("{DOC_DATE}", doc_date or "")
        .replace("{ACCOUNT_SUGGESTIONS}", sugg_lines)
    )


def _call_ollama(
    endpoint: str, model: str, prompt: str, timeout_s: int, num_ctx: int
) -> str:
    payload = {
        "model": model,
        "prompt": prompt,
        "format": "json",
        "stream": False,
        "options": {"temperature": 0.0, "num_predict": 512, "num_ctx": num_ctx},
    }
    r = httpx.post(f"{endpoint}/api/generate", json=payload, timeout=timeout_s)
    r.raise_for_status()
    return r.json().get("response", "")


def _parse_llm_json(
    raw: str, llm_caller: Callable[[str], str], prompt: str
) -> dict[str, Any]:
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        retry_prompt = (
            prompt + "\n\nRENVOIE UNIQUEMENT UN JSON VALIDE PARSABLE, RIEN D'AUTRE."
        )
        retry_raw = llm_caller(retry_prompt)
        try:
            return json.loads(retry_raw)
        except json.JSONDecodeError:
            _log.warning("LLM response not JSON-parseable after retry")
            return {}


def _persist(
    conn: sqlite3.Connection, entry: ProposedEntry, persist: bool
) -> ProposedEntry:
    if not persist:
        return entry
    cur = conn.execute(
        "INSERT INTO accounting_entries "
        "(client_id, source_document_id, date, debit_account, credit_account, "
        " amount_chf, vat_code, vat_amount, description, "
        " confidence_account, confidence_vat, reasoning, sources_json, state) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            entry.client_id,
            entry.source_document_id,
            entry.date,
            entry.debit_account,
            entry.credit_account,
            entry.amount_chf,
            entry.vat_code,
            entry.vat_amount,
            entry.description,
            entry.confidence_account,
            entry.confidence_vat,
            entry.reasoning,
            json.dumps(entry.sources, ensure_ascii=False),
            entry.state,
        ),
    )
    entry.db_id = int(cur.lastrowid)
    return entry
