"""Long-term memory: host preferences and decisions, kept across sessions.

Storage: <state>/memory.json, a dict key -> {value, updated, history[]}.
Writing the same key again overwrites the value but keeps the old one in
`history`, so a contradiction is resolved explicitly and stays auditable.

Retrieval: memory is NOT dumped into every turn. `relevant()` scores entries
against the user message (topic keywords + word overlap) and returns the top k;
`pref.*` entries are always included because they constrain every plan.
The model can fetch anything else with the `recall` tool.
"""
from __future__ import annotations

import datetime as dt
import json
import re
from pathlib import Path

from . import logger

log = logger(__file__)

TOPICS = {
    "menu": ["תפריט", "מנה", "מנות", "קינוח", "עיקרית", "ראשונה", "תוספת", "מתכון", "לבשל", "ארוחה", "dessert", "menu"],
    "weather": ["גשם", "מזג", "חם", "קר", "בחוץ", "מרפסת", "rain"],
    "time": ["זמן", "דקות", "שעה", "מהר", "הכנה", "prep"],
}
_WORD = re.compile(r"[\w֐-׿]+")


def _words(text: str) -> set[str]:
    # crude Hebrew normalisation: drop one-letter prefixes (ו, ה, ב, ל, מ, ש) from longer words
    out = set()
    for w in _WORD.findall(text.lower()):
        out.add(w)
        if len(w) > 3 and w[0] in "והבלמש":
            out.add(w[1:])
    return out


def _topics(text: str) -> set[str]:
    return {t for t, kws in TOPICS.items() if any(k in text for k in kws)}


class Memory:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.facts: dict = json.loads(self.path.read_text(encoding="utf-8")) if self.path.exists() else {}
        log(f"loaded {len(self.facts)} entries from {self.path.name}")

    def _save(self) -> None:
        self.path.write_text(json.dumps(self.facts, ensure_ascii=False, indent=1), encoding="utf-8")

    def remember(self, key: str, value: str) -> dict:
        key, value = key.strip(), str(value).strip()
        if not key or not value:
            raise ValueError("key and value are required")
        old = self.facts.get(key)
        hist = (old.get("history", []) + [old["value"]]) if old else []
        self.facts[key] = {"value": value, "updated": dt.date.today().isoformat(), "history": hist[-3:]}
        self._save()
        if old and old["value"] != value:
            log(f"overwrite {key}: {old['value']!r} -> {value!r}")
            return {"saved": key, "replaced": old["value"]}
        log(f"save {key} = {value!r}")
        return {"saved": key}

    def recall(self, query: str = "") -> dict:
        hits = self._rank(query, k=10) if query else list(self.facts)
        log(f"recall {query!r} -> {len(hits)} entries")
        return {"memory": {k: self.facts[k]["value"] for k in hits}}

    def _rank(self, text: str, k: int) -> list[str]:
        q_words, q_topics = _words(text), _topics(text)
        scored = []
        for key, f in self.facts.items():
            blob = f"{key} {f['value']}"
            score = len(q_words & _words(blob)) + 2 * len(q_topics & (_topics(blob) | {key.split(".")[-1]}))
            if score:
                scored.append((score, key))
        return [key for _, key in sorted(scored, reverse=True)[:k]]

    def relevant(self, text: str, k: int = 5) -> tuple[dict, int]:
        """Entries worth putting in this turn's context, and how many were left out."""
        prefs = [key for key in self.facts if key.startswith("pref.")]
        ranked = [key for key in self._rank(text, k) if key not in prefs]
        keys = prefs + ranked[:max(0, k - len(prefs))]
        picked = {key: self.facts[key]["value"] for key in keys}
        left = len(self.facts) - len(picked)
        log(f"retrieved {len(picked)}/{len(self.facts)} entries for this turn")
        return picked, left

    def as_dict(self) -> dict:
        return {k: f["value"] for k, f in self.facts.items()}


def tool_specs(mem: Memory) -> list[dict]:
    """Memory tools in the shape tools.py registers: name, description, schema, fn(args)->dict."""
    return [
        {"name": "remember",
         "description": "Store or overwrite a lasting host preference/decision. Same key = overwrite.",
         "schema": {"type": "object", "properties": {"key": {"type": "string"}, "value": {"type": "string"}},
                    "required": ["key", "value"]},
         "fn": lambda a: mem.remember(a.get("key", ""), a.get("value", ""))},
        {"name": "recall",
         "description": "Search long-term memory for entries not shown in <context>. Empty query = everything.",
         "schema": {"type": "object", "properties": {"query": {"type": "string"}}},
         "fn": lambda a: mem.recall(a.get("query", ""))},
    ]
