"""Prompt-cache breakpoints (cache_control), at most 4 per request; we use 2.

Prefix order in the API is tools -> system -> messages.
  BP1: last system block   -> caches tool schemas + system prompt (identical every call).
  BP2: last block of the last message -> caches the whole conversation so far; the next
       loop iteration / next turn reads it back and only pays for the new tail.
Breakpoints are added to deep copies, so history on disk never contains cache_control.
Prefixes shorter than the model's minimum cacheable length are silently not cached by
the API; we log an estimate so that shows up in the run output.
"""
from __future__ import annotations

import copy
import json

from . import logger

log = logger(__file__)
EPHEMERAL = {"type": "ephemeral"}
MIN_CACHEABLE_TOKENS = 4096  # Opus-family minimum; prefixes below this are not cached


def _est_tokens(obj) -> int:
    return len(json.dumps(obj, ensure_ascii=False)) // 3


def apply(system: list[dict], tools: list[dict], messages: list[dict]) -> tuple[list, list, list]:
    system = copy.deepcopy(system)
    messages = copy.deepcopy(messages)
    system[-1]["cache_control"] = EPHEMERAL
    marks = ["system"]
    if messages:
        last = messages[-1]
        if isinstance(last["content"], str):
            last["content"] = [{"type": "text", "text": last["content"]}]
        for block in reversed(last["content"]):
            if block.get("type") in ("text", "tool_result", "tool_use", "image"):
                block["cache_control"] = EPHEMERAL
                marks.append(f"msg[{len(messages) - 1}]")
                break
    prefix = _est_tokens(tools) + _est_tokens(system)
    total = prefix + _est_tokens(messages)
    note = "" if total >= MIN_CACHEABLE_TOKENS else f" (below ~{MIN_CACHEABLE_TOKENS}: API won't cache yet)"
    log(f"breakpoints: {', '.join(marks)}; est. tools+system~{prefix} tok, full prompt~{total} tok{note}")
    return system, tools, messages
