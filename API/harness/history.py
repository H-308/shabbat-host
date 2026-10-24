"""Conversation history: an append-only JSONL log on disk.

Nothing is ever rewritten. Compaction appends a `compact` event; rebuilding the
message list starts from the last such event, so the full raw transcript stays
on disk for auditing while the model only sees summary + tail.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

from . import logger

log = logger(__file__)

COMPACT_ACK = "הבנתי, ממשיכים מהסיכום."


def block_to_dict(block) -> dict:
    """API content block -> plain dict that can be sent back verbatim (thinking signatures included)."""
    if isinstance(block, dict):
        return block
    if hasattr(block, "model_dump"):
        return block.model_dump(exclude_none=True)
    raise TypeError(f"cannot serialise block {block!r}")


class History:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.touch(exist_ok=True)
        self._events = self._load()
        log(f"loaded {len(self._events)} events from {self.path.name}")

    def _load(self) -> list[dict]:
        return [json.loads(l) for l in self.path.read_text(encoding="utf-8").splitlines() if l.strip()]

    def _append(self, event: dict) -> None:
        event = {"ts": round(time.time(), 3), **event}
        with open(self.path, "a", encoding="utf-8") as f:
            f.write(json.dumps(event, ensure_ascii=False) + "\n")
        self._events.append(event)

    def add(self, role: str, content) -> None:
        if not isinstance(content, str):
            content = [block_to_dict(b) for b in content]
        self._append({"t": "msg", "role": role, "content": content})
        kinds = "text" if isinstance(content, str) else ",".join(b.get("type", "?") for b in content)
        log(f"append {role}: {kinds}")

    def add_compaction(self, summary: str, tokens_before: int) -> None:
        self._append({"t": "compact", "summary": summary, "tokens_before": tokens_before})
        log(f"append compaction marker (context was {tokens_before} tokens)")

    def messages(self) -> list[dict]:
        """Messages for the next API call: [summary, ack] + everything after the last compaction."""
        start, msgs = 0, []
        for i, e in enumerate(self._events):
            if e["t"] == "compact":
                start = i + 1
                msgs = [{"role": "user", "content": f"<conversation_summary>\n{e['summary']}\n</conversation_summary>"},
                        {"role": "assistant", "content": COMPACT_ACK}]
        msgs += [{"role": e["role"], "content": e["content"]} for e in self._events[start:] if e["t"] == "msg"]
        return msgs

    def __len__(self) -> int:
        return len(self._events)
