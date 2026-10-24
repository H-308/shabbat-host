"""Run the scenario on the Agent SDK version (uses your Claude Code login, not an API key).

    python SDK/main.py --scenario scenario.json --out results/sdk.json
"""
from __future__ import annotations

import argparse
import asyncio
import importlib.util
import os
import sys
from pathlib import Path

for _s in (sys.stdout, sys.stderr):  # Windows consoles default to cp1255; Hebrew logs need UTF-8
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8", errors="replace")

HERE = Path(__file__).resolve().parent
_spec = importlib.util.spec_from_file_location("sdk_agent", HERE / "agent.py")  # unique name: API/ also has agent.py
sdk_agent = sys.modules.setdefault("sdk_agent", importlib.util.module_from_spec(_spec))
if not hasattr(sdk_agent, "SDKShabbatAgent"):
    _spec.loader.exec_module(sdk_agent)
ROOT, SDKShabbatAgent = sdk_agent.ROOT, sdk_agent.SDKShabbatAgent

from shared import checks, config, loc, runner  # noqa: E402
from shared.store import Store  # noqa: E402


async def run_scenario(scenario_path, out, state_dir=None, client_cls=None, fetch=None) -> dict:
    if os.environ.pop("ANTHROPIC_API_KEY", None):
        print("[SDK/main.py] ANTHROPIC_API_KEY was set: removed for this run so billing stays on your Claude login")
    sc = runner.load_scenario(scenario_path)
    state = runner.fresh_state(state_dir or ROOT / "state" / "sdk_run")
    today = runner.scenario_today(sc)
    turns, results, answers, n = [], [], {}, 0
    for s_idx, session in enumerate(sc["sessions"], 1):
        print(f"\n===== session {s_idx}: new SDKShabbatAgent instance (resume from disk) =====", flush=True)
        kw = {"client_cls": client_cls} if client_cls else {}
        async with SDKShabbatAgent(state, session=s_idx, today=today, fetch=fetch, **kw) as agent:
            for prompt in session["turns"]:
                n += 1
                print(f"\n--- turn {n} (session {s_idx}) ---\nUSER: {prompt}", flush=True)
                r = await agent.ask(prompt)
                print(f"AGENT: {r.answer}", flush=True)
                answers[n] = r.answer
                turns.append(runner.turn_record(s_idx, n, prompt, r.usage, r.model_calls, r.tools, r.cost, r.seconds,
                                                r.answer, sdk_reported_cost_usd=r.reported_cost,
                                                session_id=r.session_id, model_usage=r.model_usage))
            memory = agent.memory()
        results += checks.run_checks(sc["checks"], Store(state / "domain"), memory, answers, s_idx)
    payload = runner.write_results(out, "sdk", config.MODEL, config.EFFORT, turns, results, loc.sdk_loc())
    print(f"\nchecks {payload['checks_passed']}  cost ${payload['totals']['cost_usd']:.4f}  -> {out}")
    for c in results:
        print(f"  [{'PASS' if c['passed'] else 'FAIL'}] {c['id']}: {c['detail']}")
    return payload


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--scenario", default=str(ROOT / "scenario.json"))
    ap.add_argument("--out", default=str(ROOT / "results" / "sdk.json"))
    ap.add_argument("--state-dir", default=None)
    a = ap.parse_args()
    asyncio.run(run_scenario(a.scenario, a.out, a.state_dir))
