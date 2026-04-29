"""Entry point CLI : `fiduciaire-worker --config <path>`."""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from .config import load_config
from .watcher import run


def main() -> int:
    parser = argparse.ArgumentParser(prog="fiduciaire-worker")
    parser.add_argument("--config", type=Path, default=None, help="config.yaml (défaut: ./config.yaml ou config.example.yaml)")
    parser.add_argument("--log-level", default="INFO")
    args = parser.parse_args()

    config = load_config(args.config)
    config.paths.ensure()

    logging.basicConfig(
        level=getattr(logging, args.log_level.upper(), logging.INFO),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=[
            logging.StreamHandler(sys.stdout),
            logging.FileHandler(config.paths.worker_log),
        ],
    )
    logging.getLogger("watchdog").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)

    run(config)
    return 0


if __name__ == "__main__":
    sys.exit(main())
