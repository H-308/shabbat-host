"""Domain state on disk: guests, saved menus and a log of every tool call.

Both harnesses point a Store at their own state directory, so the scenario
checks can inspect the same files no matter which harness produced them.
"""
from __future__ import annotations

import json
import time
from pathlib import Path


def norm(name: str) -> str:
    return " ".join(str(name).strip().split())


class Store:
    def __init__(self, state_dir: str | Path, session: int = 1):
        self.dir = Path(state_dir)
        self.dir.mkdir(parents=True, exist_ok=True)
        self.session = session

    # ---- generic json helpers -------------------------------------------
    def _read(self, name: str, default):
        p = self.dir / name
        if not p.exists():
            return default
        return json.loads(p.read_text(encoding="utf-8"))

    def _write(self, name: str, data) -> None:
        p = self.dir / name
        tmp = p.with_suffix(p.suffix + ".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
        tmp.replace(p)

    # ---- guests ---------------------------------------------------------
    def guests(self) -> list[dict]:
        return self._read("guests.json", [])

    def find_guest(self, name: str) -> dict | None:
        n = norm(name)
        gs = self.guests()
        for g in gs:
            if g["name"] == n:
                return g
        for g in gs:  # "אבא יוסי" vs "יוסי"
            if n in g["name"] or g["name"] in n:
                return g
        return None

    def upsert_guest(self, guest: dict) -> tuple[dict, dict | None]:
        gs = self.guests()
        old = None
        for i, g in enumerate(gs):
            if g["name"] == guest["name"] or guest["name"] in g["name"] or g["name"] in guest["name"]:
                old = dict(g)
                merged = {**g, **{k: v for k, v in guest.items() if v is not None}}
                merged["name"] = g["name"]
                gs[i] = merged
                guest = merged
                break
        else:
            gs.append(guest)
        self._write("guests.json", gs)
        return guest, old

    # ---- menus ----------------------------------------------------------
    def menus(self) -> list[dict]:
        return self._read("menus.json", [])

    def add_menu(self, menu: dict) -> int:
        ms = self.menus()
        ms = [m for m in ms if m["date"] != menu["date"]]  # one menu per date
        ms.append(menu)
        ms.sort(key=lambda m: m["date"])
        self._write("menus.json", ms)
        return len(ms)

    # ---- tool log -------------------------------------------------------
    def log_tool(self, tool: str, args: dict, ok: bool) -> None:
        rec = {"ts": round(time.time(), 3), "session": self.session, "tool": tool, "ok": ok, "args": args}
        with open(self.dir / "tool_log.jsonl", "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")

    def tool_log(self) -> list[dict]:
        p = self.dir / "tool_log.jsonl"
        if not p.exists():
            return []
        return [json.loads(l) for l in p.read_text(encoding="utf-8").splitlines() if l.strip()]
