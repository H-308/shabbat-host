"""Pass/fail checks from scenario.json, evaluated mostly on persisted state.

The harness supplies `memory`: a dict key -> value read from its own memory store
(API: memory.json, SDK: CLAUDE.md), so the same checks judge both versions.
"""
from __future__ import annotations

import re

from . import domain
from .store import Store


def _guest(store: Store, name: str) -> dict | None:
    return store.find_guest(name)


def evaluate(check: dict, store: Store, memory: dict, answers: dict) -> tuple[bool, str]:
    t = check["type"]
    if t == "guest_restrictions":
        g = _guest(store, check["guest"])
        if not g:
            return False, f"guest {check['guest']} not saved"
        have = set(g.get("restrictions") or [])
        miss = [r for r in check.get("has", []) if r not in have]
        bad = [r for r in check.get("lacks", []) if r in have]
        return (not miss and not bad), f"{g['name']} restrictions={sorted(have)}"
    if t == "guest_count_min":
        n = len(store.guests())
        return n >= check["n"], f"{n} guests"
    if t == "memory_value":
        key = check["key"]
        val = str(memory.get(key, ""))
        ok = key in memory
        if "matches" in check:
            ok = ok and re.search(check["matches"], val) is not None
        if "not_matches" in check:
            ok = ok and re.search(check["not_matches"], val) is None
        return ok, f"{key}={val!r}" if key in memory else f"{key} missing (keys: {sorted(memory)[:8]})"
    if t == "menu_count_min":
        n = len(store.menus())
        return n >= check["n"], f"{n} menus"
    if t == "latest_menu_valid":
        ms = store.menus()
        if not ms:
            return False, "no menu"
        m = ms[-1]
        guests = [store.find_guest(g) or {"name": g, "restrictions": []} for g in m["guests"]]
        v = domain.validate_menu(m["dish_ids"], guests, check.get("max_prep"))
        return v["ok"], f"{m['date']} {m['dish_ids']} issues={v['issues']}"
    if t == "latest_menu_has_guest":
        ms = store.menus()
        ok = bool(ms) and any(check["guest"] in g or g in check["guest"] for g in ms[-1]["guests"])
        return ok, f"guests={ms[-1]['guests'] if ms else None}"
    if t == "latest_course_kinds":
        # e.g. the host's rule "dessert is always parve"
        ms = store.menus()
        if not ms:
            return False, "no menu"
        course = [r for r in (domain.recipe(d) for d in ms[-1]["dish_ids"]) if r and r["course"] == check["course"]]
        ok = bool(course) and all(r["kind"] in check["kinds"] for r in course)
        return ok, f"{check['course']}={[(r['id'], r['kind']) for r in course]}"
    if t == "answer_mentions_menu_main":
        # retrieval across sessions: the answer names the main dish of an earlier saved menu
        ms = store.menus()
        if len(ms) <= check.get("menu_index", 0):
            return False, "menu missing"
        mains = [r for r in (domain.recipe(d) for d in ms[check.get("menu_index", 0)]["dish_ids"])
                 if r and r["course"] == "main"]
        ans = answers.get(check["turn"], "")
        hit = [r["name"] for r in mains if " ".join(r["name"].split()[:2]) in ans]
        return bool(hit), f"mains={[r['name'] for r in mains]} mentioned={hit}"
    if t == "mains_differ":
        ms = store.menus()
        if len(ms) < 2:
            return False, f"{len(ms)} menus"
        def primary(m):  # the meat main if there is one, otherwise the first main
            mains = [r for r in (domain.recipe(d) for d in m["dish_ids"]) if r and r["course"] == "main"]
            meat = [r for r in mains if r["kind"] == "meat"]
            return (meat or mains or [{"id": None}])[0]["id"]
        a, b = primary(ms[-2]), primary(ms[-1])
        return a is not None and a != b, f"prev main={a} last main={b}"
    if t == "tool_called":
        calls = [c for c in store.tool_log() if c["tool"] == check["tool"] and c["ok"]
                 and ("session" not in check or c["session"] == check["session"])]
        return bool(calls), f"{len(calls)} successful calls"
    if t == "answer_matches":
        ans = answers.get(check["turn"], "")
        return re.search(check["regex"], ans) is not None, ans[:80].replace("\n", " ")
    return False, f"unknown check type {t}"


def run_checks(checks: list[dict], store: Store, memory: dict, answers: dict, after_session: int) -> list[dict]:
    out = []
    for c in checks:
        if c.get("after_session", 2) != after_session:
            continue
        ok, detail = evaluate(c, store, memory, answers)
        out.append({"id": c["id"], "desc": c.get("desc", ""), "after_session": after_session,
                    "passed": ok, "detail": detail})
    return out
