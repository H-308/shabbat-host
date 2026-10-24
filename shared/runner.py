"""Scenario plumbing shared by API/main.py and SDK/main.py (loading, clean state, results file)."""
from __future__ import annotations

import datetime as dt
import json
import shutil
from pathlib import Path

from .config import LOCKED_VERSIONS, installed_versions


def load_scenario(path: str | Path) -> dict:
    sc = json.loads(Path(path).read_text(encoding="utf-8"))
    n = sum(len(s["turns"]) for s in sc["sessions"])
    assert len(sc["sessions"]) == 2 and 6 <= n <= 8, "scenario must have 2 sessions and 6-8 turns"
    return sc


def scenario_today(sc: dict) -> dt.date:
    return dt.date.fromisoformat(sc["today"]) if sc.get("today") else dt.date.today()


def fresh_state(state_dir: str | Path) -> Path:
    """Every run starts from a clean state (assignment rule)."""
    p = Path(state_dir)
    if p.exists():
        shutil.rmtree(p)
    p.mkdir(parents=True)
    return p


def turn_record(session: int, turn: int, prompt: str, usage: dict, model_calls: int, tools: list[str],
                cost: float, seconds: float, answer: str, **extra) -> dict:
    return {"session": session, "turn": turn, "prompt": prompt,
            "tokens": {k: int(usage.get(k, 0)) for k in ("input", "cache_read", "cache_write", "output")},
            "model_calls": model_calls, "tools": tools, "cost_usd": round(cost, 6),
            "seconds": round(seconds, 2), "answer": answer[:600], **extra}


def totals(turns: list[dict]) -> dict:
    t = {k: sum(x["tokens"][k] for x in turns) for k in ("input", "cache_read", "cache_write", "output")}
    prompt_side = t["input"] + t["cache_read"] + t["cache_write"]
    t["cache_hit_pct"] = round(100 * t["cache_read"] / prompt_side, 1) if prompt_side else 0.0
    t["model_calls"] = sum(x["model_calls"] for x in turns)
    t["tool_calls"] = sum(len(x["tools"]) for x in turns)
    t["cost_usd"] = round(sum(x["cost_usd"] for x in turns), 6)
    t["seconds"] = round(sum(x["seconds"] for x in turns), 2)
    return t


def write_results(out: str | Path, harness: str, model: str, effort: str, turns: list[dict],
                  checks: list[dict], loc: dict, **extra) -> dict:
    payload = {
        "harness": harness, "model": model, "effort": effort,
        "versions": {"locked": LOCKED_VERSIONS, "installed": installed_versions()},
        "run_at": dt.datetime.now().isoformat(timespec="seconds"),
        "totals": totals(turns),
        "checks_passed": f"{sum(c['passed'] for c in checks)}/{len(checks)}",
        "checks": checks, "turns": turns, "loc": loc, **extra,
    }
    p = Path(out)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return payload
