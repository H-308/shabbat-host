"""Settings shared by both harnesses, so the comparison is apples-to-apples."""
from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = Path(__file__).resolve().parent / "data"

# Same model and effort in both versions (assignment rule).
MODEL = os.environ.get("SHABBAT_MODEL", "claude-opus-5-5")
EFFORT = os.environ.get("SHABBAT_EFFORT", "medium")
MAX_TOKENS = 4096

# USD per 1M tokens, Claude Opus 5.5 standard API pricing (5-minute cache writes).
PRICES = {
    "claude-opus-5-5": {"input": 4.00, "output": 20.00, "cache_write": 5.00, "cache_read": 0.20},
}

# Locked library versions, recorded into every results file.
LOCKED_VERSIONS = {"anthropic": "1.0.0", "claude-agent-sdk": "0.2.172"}


def price_for(model: str) -> dict:
    return PRICES.get(model, PRICES["claude-opus-5-5"])


def installed_versions() -> dict:
    out = {}
    try:
        from importlib.metadata import version, PackageNotFoundError
    except ImportError:  # pragma: no cover
        return out
    for pkg in LOCKED_VERSIONS:
        try:
            out[pkg] = version(pkg)
        except PackageNotFoundError:
            out[pkg] = None
    return out
