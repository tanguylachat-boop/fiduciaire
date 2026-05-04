"""Chargement de config.yaml (avec fallback config.example.yaml).

Tous les paths du config sont résolus relativement à la racine du repo.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parents[3]


@dataclass
class Paths:
    inbox: Path
    needs_review: Path
    archive: Path
    clients_root: Path
    db: Path
    worker_log: Path

    def ensure(self) -> None:
        for p in (self.inbox, self.needs_review, self.archive, self.clients_root):
            p.mkdir(parents=True, exist_ok=True)
        self.db.parent.mkdir(parents=True, exist_ok=True)
        self.worker_log.parent.mkdir(parents=True, exist_ok=True)


@dataclass
class LLMConfig:
    endpoint: str
    env: str
    primary: str
    fallback: str | None
    vision: str | None
    prompt_file: Path
    timeout_s: int
    temperature: float
    num_predict: int
    num_ctx: int


@dataclass
class Config:
    raw: dict[str, Any]
    cabinet_name: str
    cabinet_slug: str
    langues_ocr: list[str]
    paths: Paths
    llm: LLMConfig
    qr_enabled: bool
    vision_when_ratio_below: float
    ocr_dpi: int
    confidence_thresholds: dict[str, float]
    naming_pattern: str
    type_short_map: dict[str, str]
    type_long_map: dict[str, str]
    routing_pattern: str
    known_clients: list[dict[str, Any]] = field(default_factory=list)


def _resolve(p: str) -> Path:
    path = Path(p)
    return path if path.is_absolute() else (REPO_ROOT / path).resolve()


def load_config(config_path: Path | None = None) -> Config:
    """Charge config.yaml. Si absent, retombe sur config.example.yaml."""
    if config_path is None:
        candidate = REPO_ROOT / "config.yaml"
        config_path = candidate if candidate.exists() else REPO_ROOT / "config.example.yaml"
    raw = yaml.safe_load(Path(config_path).read_text(encoding="utf-8"))

    cabinet = raw.get("cabinet", {})
    paths_raw = raw.get("paths", {})
    paths = Paths(
        inbox=_resolve(paths_raw.get("inbox", "./data/inbox")),
        needs_review=_resolve(paths_raw.get("needs_review", "./data/needs-review")),
        archive=_resolve(paths_raw.get("archive", "./data/archive")),
        clients_root=_resolve(paths_raw.get("clients_root", "./data/clients")),
        db=_resolve(paths_raw.get("db", "./data/fiduciaire.sqlite")),
        worker_log=_resolve(raw.get("logging", {}).get("file", "./data/worker.log")),
    )

    llm_raw = raw.get("llm", {})
    env = llm_raw.get("env", "dev")
    models = llm_raw.get("models", {}).get(env, {})
    llm = LLMConfig(
        endpoint=llm_raw.get("endpoint", "http://localhost:11434"),
        env=env,
        primary=models.get("primary", "qwen2.5:7b-instruct-q4_K_M"),
        fallback=models.get("fallback"),
        vision=models.get("vision"),
        prompt_file=_resolve(llm_raw.get("prompt_file", "worker/prompts/classify_v2_fewshot.txt")),
        timeout_s=int(llm_raw.get("timeout_s", 120)),
        temperature=float(llm_raw.get("temperature", 0.0)),
        num_predict=int(llm_raw.get("num_predict", 512)),
        # 4096 = prompt classify_v2_fewshot (~1500 tok) + OCR (~150) + output 512 + marge.
        # Sans cap, Ollama applique le ctx du modèle (131072 sur llama3.3) qui
        # explose le KV cache et force du CPU offloading → ~0.8 tok/s génération.
        num_ctx=int(llm_raw.get("num_ctx", 4096)),
    )

    naming = raw.get("naming", {})
    routing = raw.get("routing", {})
    type_short = naming.get("type_short_map", {}) or {}
    # type_long pour le routing : on dérive depuis type_short_map (clés = type_long)
    type_long_map = {k: k for k in type_short.keys()}

    return Config(
        raw=raw,
        cabinet_name=cabinet.get("name", "Cabinet"),
        cabinet_slug=cabinet.get("slug", "cabinet"),
        langues_ocr=list(cabinet.get("langues_ocr", ["fra", "deu"])),
        paths=paths,
        llm=llm,
        qr_enabled=raw.get("preparser", {}).get("swiss_qr_bill", {}).get("enabled", True),
        vision_when_ratio_below=float(
            raw.get("ocr_fallback", {}).get("vision_when_text_ratio_below", 0.70)
        ),
        ocr_dpi=int(raw.get("ocr", {}).get("dpi", 300)),
        confidence_thresholds=raw.get("confidence_thresholds", {}),
        naming_pattern=naming.get(
            "pattern", "{date_iso}_{type_short}_{fournisseur_slug}_{montant_chf}_{hash6}.pdf"
        ),
        type_short_map=type_short,
        type_long_map=type_long_map,
        routing_pattern=routing.get("client_dir_pattern", "{client_slug}/{annee}/{type_long}"),
        known_clients=raw.get("clients", []) or [],
    )
