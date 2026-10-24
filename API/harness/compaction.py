"""Context-window management: once the prompt passes a threshold, summarise the whole conversation.

Runs between user turns (never inside a tool loop, so no tool_use is left dangling).
The transcript is flattened to plain text first: no tool/thinking blocks to keep valid,
and long tool results are clipped, so the summary call itself stays cheap.
The summary is appended to history as a `compact` event (history stays append-only).
"""
from __future__ import annotations

import json

from . import logger
from .history import History
from .tokens import TurnMeter

log = logger(__file__)

SUMMARY_SYSTEM = ("You compress a conversation between a Shabbat-dinner host and their assistant. Write a Hebrew summary "
                  "(max 200 words) keeping: guests and restrictions mentioned, menus decided (dish ids), host preferences "
                  "and any changes to them, open questions. Facts only, no pleasantries.")


def should_compact(context_tokens: int, threshold: int) -> bool:
    hit = threshold > 0 and context_tokens > threshold
    log(f"context {context_tokens} / threshold {threshold} -> {'COMPACT' if hit else 'keep'}")
    return hit


def _flatten(messages: list[dict], clip: int = 300) -> str:
    lines = []
    for m in messages:
        content = m["content"]
        if isinstance(content, str):
            lines.append(f"{m['role']}: {content}")
            continue
        for b in content:
            t = b.get("type")
            if t == "text":
                lines.append(f"{m['role']}: {b['text']}")
            elif t == "tool_use":
                lines.append(f"assistant -> {b['name']}({json.dumps(b.get('input', {}), ensure_ascii=False)})")
            elif t == "tool_result":
                c = b.get("content")
                c = c if isinstance(c, str) else json.dumps(c, ensure_ascii=False)
                lines.append(f"tool{' ERROR' if b.get('is_error') else ''}: {c[:clip]}")
    return "\n".join(lines)


def compact(client, history: History, model: str, meter: TurnMeter, context_tokens: int, **params) -> str:
    transcript = _flatten(history.messages())
    log(f"summarising {len(transcript)} chars of transcript")
    resp = client.messages.create(
        model=model, max_tokens=1200, system=SUMMARY_SYSTEM,
        messages=[{"role": "user", "content": f"<transcript>\n{transcript}\n</transcript>\n\nSummarise."}], **params)
    meter.record(resp.usage, kind="compaction")
    summary = "".join(getattr(b, "text", "") for b in resp.content if getattr(b, "type", "") == "text").strip()
    history.add_compaction(summary, context_tokens)
    return summary
