"""Token usage and cost, per model call and per user turn."""
from __future__ import annotations

from shared.config import price_for

from . import logger

log = logger(__file__)


def usage_dict(usage) -> dict:
    """Normalise the API usage object (or a dict) into our four counters."""
    g = (lambda k: usage.get(k)) if isinstance(usage, dict) else (lambda k: getattr(usage, k, None))
    return {"input": g("input_tokens") or 0, "cache_read": g("cache_read_input_tokens") or 0,
            "cache_write": g("cache_creation_input_tokens") or 0, "output": g("output_tokens") or 0}


def cost(u: dict, model: str) -> float:
    p = price_for(model)
    return (u["input"] * p["input"] + u["cache_read"] * p["cache_read"]
            + u["cache_write"] * p["cache_write"] + u["output"] * p["output"]) / 1_000_000


class TurnMeter:
    """Accumulates every model call made while answering one user message (incl. compaction)."""

    def __init__(self, model: str):
        self.model = model
        self.calls: list[dict] = []

    def record(self, usage, kind: str = "loop") -> dict:
        u = usage_dict(usage)
        c = cost(u, self.model)
        self.calls.append({"kind": kind, **u, "cost": c})
        log(f"call#{len(self.calls)} [{kind}] in={u['input']} cache_r={u['cache_read']} "
            f"cache_w={u['cache_write']} out={u['output']} ${c:.4f}")
        return u

    @property
    def usage(self) -> dict:
        return {k: sum(c[k] for c in self.calls) for k in ("input", "cache_read", "cache_write", "output")}

    @property
    def cost(self) -> float:
        return sum(c["cost"] for c in self.calls)

    def context_size(self) -> int:
        """Prompt size of the last loop call = how full the context window is right now."""
        loop_calls = [c for c in self.calls if c["kind"] == "loop"]
        if not loop_calls:
            return 0
        c = loop_calls[-1]
        return c["input"] + c["cache_read"] + c["cache_write"] + c["output"]

    def summary(self) -> str:
        u = self.usage
        line = (f"turn total: calls={len(self.calls)} in={u['input']} cache_r={u['cache_read']} "
                f"cache_w={u['cache_write']} out={u['output']} cost=${self.cost:.4f}")
        log(line)
        return line
