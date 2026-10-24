"""What goes into each turn.

- system: static (persona + rules). Never changes, so it caches.
- per-turn <context> block, prepended to the user message: date, a one-line guest
  roster, and ONLY the memory entries relevant to this message (memory.relevant).
  The last menu is added only when the message is about menus.
- Not included: the recipe catalog (26 dishes), full guest notes, old menus, tool log.
  The model pulls those through tools when it needs them.

The block is stored in history together with the user text, so earlier turns stay
byte-identical and the cache prefix survives across turns.
"""
from __future__ import annotations

import datetime as dt

from shared import domain
from shared.prompt import API_MEMORY_NOTE, BASE_SYSTEM_PROMPT
from shared.store import Store

from . import logger
from .memory import Memory, _topics

log = logger(__file__)
DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


def system_blocks() -> list[dict]:
    return [{"type": "text", "text": BASE_SYSTEM_PROMPT + "\n" + API_MEMORY_NOTE}]


def _roster(store: Store, text: str, max_all: int = 8) -> str:
    gs = store.guests()
    mentioned = [g for g in gs if g["name"] in text]
    shown = gs if len(gs) <= max_all else mentioned
    parts = [g["name"] + (f"[{','.join(g['restrictions'])}]" if g.get("restrictions") else "") for g in shown]
    more = f" (+{len(gs) - len(shown)} more: list_guests)" if len(shown) < len(gs) else ""
    return (", ".join(parts) or "none yet") + more


def build_user_turn(text: str, store: Store, memory: Memory, today: dt.date) -> str:
    facts, left = memory.relevant(text)
    lines = [f"today: {today.isoformat()} ({DAYS[today.weekday()]}); next friday: {domain.next_friday(today)}",
             f"guests on file: {_roster(store, text)}"]
    if facts:
        mem = "; ".join(f"{k}={v}" for k, v in facts.items())
        lines.append(f"memory: {mem}" + (f" (+{left} more: recall)" if left else ""))
    elif left:
        lines.append(f"memory: {left} entries, none matched (recall if needed)")
    if "menu" in _topics(text) and store.menus():
        m = store.menus()[-1]
        lines.append(f"last menu: {m['date']} dishes={','.join(m['dish_ids'])}")
    block = "<context>\n" + "\n".join(lines) + "\n</context>\n\n" + text
    log(f"turn context: {len(lines)} lines, {len(facts)} memory entries, ~{len(block) // 3} tokens")
    return block
