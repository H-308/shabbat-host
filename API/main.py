"""Run the scenario on the API harness.

    python API/main.py --scenario scenario.json --out results/api.json
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import importlib.util  # noqa: E402

for _s in (sys.stdout, sys.stderr):  # Windows consoles default to cp1255; Hebrew logs need UTF-8
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8", errors="replace")

HERE = Path(__file__).resolve().parent
_spec = importlib.util.spec_from_file_location("api_agent", HERE / "agent.py")  # unique name: SDK/ also has agent.py
api_agent = sys.modules.setdefault("api_agent", importlib.util.module_from_spec(_spec))
if not hasattr(api_agent, "ShabbatAgent"):
    _spec.loader.exec_module(api_agent)
ROOT, ShabbatAgent = api_agent.ROOT, api_agent.ShabbatAgent

from harness.memory import Memory  # noqa: E402
from shared import checks, config, loc, runner  # noqa: E402
from shared.store import Store  # noqa: E402


def run_scenario(scenario_path, out, state_dir=None, client_factory=None, fetch=None) -> dict:
    sc = runner.load_scenario(scenario_path)
    state = runner.fresh_state(state_dir or ROOT / "state" / "api_run")
    today = runner.scenario_today(sc)
    turns, results, answers, n = [], [], {}, 0
    for s_idx, session in enumerate(sc["sessions"], 1):
        print(f"\n===== session {s_idx}: new ShabbatAgent instance (state loaded from disk) =====", flush=True)
        agent = ShabbatAgent(state, client_factory() if client_factory else None, session=s_idx, today=today,
                             compact_threshold=sc.get("compact_threshold_tokens", 50_000), fetch=fetch)
        for prompt in session["turns"]:
            n += 1
            print(f"\n--- turn {n} (session {s_idx}) ---\nUSER: {prompt}", flush=True)
            r = agent.ask(prompt)
            print(f"AGENT: {r.answer}", flush=True)
            answers[n] = r.answer
            turns.append(runner.turn_record(s_idx, n, prompt, r.usage, r.model_calls, r.tools, r.cost, r.seconds,
                                            r.answer, compacted=r.compacted, stop_reason=r.stop_reason))
        memory = Memory(state / "api" / "memory.json").as_dict()
        results += checks.run_checks(sc["checks"], Store(state / "domain"), memory, answers, s_idx)
    payload = runner.write_results(out, "api", config.MODEL, config.EFFORT, turns, results, loc.api_loc(),
                                   compactions=sum(t["compacted"] for t in turns))
    print(f"\nchecks {payload['checks_passed']}  cost ${payload['totals']['cost_usd']:.4f}  -> {out}")
    for c in results:
        print(f"  [{'PASS' if c['passed'] else 'FAIL'}] {c['id']}: {c['detail']}")
    return payload


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--scenario", default=str(ROOT / "scenario.json"))
    ap.add_argument("--out", default=str(ROOT / "results" / "api.json"))
    ap.add_argument("--state-dir", default=None)
    a = ap.parse_args()
    run_scenario(a.scenario, a.out, a.state_dir)
