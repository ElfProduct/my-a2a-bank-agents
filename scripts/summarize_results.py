#!/usr/bin/env python3
"""Compact local summary for tau2 dir-format result folders.

This intentionally avoids printing run metadata because the harness may store
provider API keys in user_llm_args.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def load_simulations(result_dir: Path) -> list[dict]:
    sim_dir = result_dir / "simulations"
    if not sim_dir.exists():
        raise SystemExit(f"No simulations directory found: {sim_dir}")
    simulations = []
    for path in sorted(sim_dir.glob("*.json")):
        with open(path) as fp:
            simulations.append(json.load(fp))
    return simulations


def action_summary(sim: dict) -> str:
    reward_info = sim.get("reward_info") or {}
    checks = reward_info.get("action_checks") or []
    if not checks:
        return "-"
    parts = []
    for check in checks:
        action = check.get("action") or {}
        ok = "ok" if check.get("action_match") else "miss"
        parts.append(f"{action.get('requestor')}:{action.get('name')}={ok}")
    return ", ".join(parts)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "result_dir",
        nargs="?",
        default="../a2a-hackathon/results/feedback",
        help="tau2 result directory, default: ../a2a-hackathon/results/feedback",
    )
    args = parser.parse_args()

    result_dir = Path(args.result_dir).expanduser().resolve()
    simulations = load_simulations(result_dir)
    if not simulations:
        print(f"No simulations found in {result_dir}")
        return 1

    rewards = []
    print(f"Results: {result_dir}")
    print("task_id   reward  duration  termination  env_calls  leg2  actions")
    print("-------   ------  --------  -----------  ---------  ----  -------")
    for sim in sorted(simulations, key=lambda item: str(item.get("task_id"))):
        reward_info = sim.get("reward_info") or {}
        reward = reward_info.get("reward")
        if isinstance(reward, (int, float)):
            rewards.append(float(reward))
            reward_text = f"{reward:.3f}"
        else:
            reward_text = "n/a"
        info = sim.get("info") or {}
        leg2 = info.get("leg2") or []
        print(
            f"{sim.get('task_id', '-'):<9} "
            f"{reward_text:>6}  "
            f"{float(sim.get('duration') or 0):>8.1f}s  "
            f"{str(sim.get('termination_reason', '-')):<11}  "
            f"{info.get('num_env_tool_calls', '-')!s:>9}  "
            f"{len(leg2):>4}  "
            f"{action_summary(sim)}"
        )

    mean = sum(rewards) / len(rewards) if rewards else 0.0
    print(f"\nMean reward over scored simulations: {mean:.3f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
