#!/usr/bin/env python3
"""
One-command runner to execute the complete end-to-end pipeline:
1. Replay Runner (processes all triggers in virtual time)
2. Simulator (simulates 14-day outcome telemetry)
3. Outcome Judge (evaluates attributable goal success)
4. Impact Analyzer (computes Intent-To-Treat uplift vs holdout)
5. Automated Test Suite (runs pytest)
"""
import subprocess
import sys
import time
from pathlib import Path


def main():
    root = Path(__file__).resolve().parent
    print("=" * 70)
    print("ONE USER, ONE AGENT - COMPLETE PIPELINE EXECUTION")
    print("=" * 70)

    # 1. Run Replay Runner
    print("\n[Step 1/5] Running Replay Runner on virtual timeline...")
    from src.replay_runner import ReplayRunner
    runner = ReplayRunner(pack_dir=root, out_dir=root / "sample_run")
    summary = runner.run()
    print(f"Replay complete: {summary}")

    # 2. Run Official Simulator
    print("\n[Step 2/5] Running outcome simulator...")
    sim_cmd = [
        sys.executable,
        str(root / "simulator" / "simulate_outcomes.py"),
        "--pack", str(root),
        "--actions", str(root / "sample_run" / "actions.jsonl"),
        "--out", str(root / "sample_run" / "sim"),
    ]
    res_sim = subprocess.run(sim_cmd, capture_output=True, text=True)
    if res_sim.returncode != 0:
        print(f"Simulator error:\n{res_sim.stderr}", file=sys.stderr)
        sys.exit(res_sim.returncode)
    print("Simulator complete.")

    # 3. Run Outcome Judge
    print("\n[Step 3/5] Evaluating attributable goal outcomes...")
    from src.outcome_judge import OutcomeJudge
    judge = OutcomeJudge(pack_dir=root, run_dir=root / "sample_run")
    judgments = judge.judge_outcomes()
    print(f"Judged {len(judgments)} active goals.")

    # 4. Run Impact Analyzer
    print("\n[Step 4/5] Computing causal Intent-To-Treat (ITT) impact...")
    from src.impact_analyzer import ImpactAnalyzer
    analyzer = ImpactAnalyzer(pack_dir=root, run_dir=root / "sample_run")
    impact = analyzer.analyze()
    print(f"ITT Uplift: {impact['abs_uplift']:+.2%} (p-value: {impact['p_value']:.4e})")

    # 5. Run Automated Test Suite
    print("\n[Step 5/5] Executing automated test suite via pytest...")
    test_cmd = [sys.executable, "-m", "pytest", "tests", "-v"]
    res_tests = subprocess.run(test_cmd, capture_output=True, text=True)
    print(res_tests.stdout)
    if res_tests.returncode != 0:
        print("Tests failed!", file=sys.stderr)
        sys.exit(res_tests.returncode)

    print("=" * 70)
    print("ALL PIPELINE STAGES COMPLETED SUCCESSFULLY!")
    print("Artifacts generated in sample_run/:")
    print("  - sample_run/decisions.jsonl")
    print("  - sample_run/actions.jsonl")
    print("  - sample_run/viewer_state/")
    print("  - sample_run/outcomes.jsonl")
    print("  - sample_run/latency_report.json")
    print("  - sample_run/impact_report.md")
    print("=" * 70)


if __name__ == "__main__":
    main()

