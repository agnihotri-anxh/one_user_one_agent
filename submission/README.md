# One User, One Agent: Submission Runbook

**Candidate Assignment:** OTT Dialect Platform | AI Engineering Hiring Challenge  
**Role:** Senior AI Engineer / Applied LLM Engineer  
**Submission Date:** November 2026  

---

## 1. Quick Start (Single-Command Execution)

To execute the entire end-to-end pipeline in one command:
```bash
python run_all.py
```
This single script executes all five stages sequentially:
1. **Replay Runner**: Merges control events, live telemetry, and 2,769 triggers in monotonic virtual time. Emits `sample_run/decisions.jsonl` and `sample_run/actions.jsonl`.
2. **Outcome Simulator**: Runs `simulator/simulate_outcomes.py` to simulate 14-day viewer responses.
3. **Outcome Judge**: Evaluates attributable goal completion, enforcing exposure precedence and dynamic rule updates. Emits `sample_run/outcomes.jsonl`.
4. **Impact Analyzer**: Computes Intent-To-Treat (ITT) causal uplift against the randomized holdout arm. Emits `sample_run/impact_report.md`.
5. **Automated Test Suite**: Executes all 8 automated pytest scenarios in `tests/`.

---

## 2. Individual Component Execution

You may also run each component individually:

### Run the Replay Runner:
```bash
python -m src.replay_runner
```
*Outputs:*
* `sample_run/decisions.jsonl` (2,769 machine-readable decisions conforming to Section 4 schema)
* `sample_run/actions.jsonl` (703 published physical actions formatted for simulator)
* `sample_run/viewer_state/<user_id>.json` (Durable JSON state files for all viewers)
* `sample_run/latency_report.json` (Latency benchmarks and SLA compliance)

### Run the Outcome Simulator:
```bash
python simulator/simulate_outcomes.py --pack . --actions sample_run/actions.jsonl --out sample_run/sim
```
*Outputs:*
* `sample_run/sim/outcome_events.jsonl` (31,501 simulated events)
* `sample_run/sim/simulator_report.json` (**0 policy problems**, 100% accepted pages)

### Run the Attributable Outcome Judge:
```bash
python -m src.outcome_judge
```
*Outputs:*
* `sample_run/outcomes.jsonl` (703 goal judgments: 269 Succeeded, 399 Failed, 35 Organic/Unattributed)
* Updates durable viewer states in `sample_run/viewer_state/` with closed goal history.

### Run the Intent-To-Treat Impact Analyzer:
```bash
python -m src.impact_analyzer
```
*Outputs:*
* `sample_run/impact_report.md` (Formal ITT analysis, 95% CI, Fisher's exact test, and critique of the pilot's selection bias).

### Run the Automated Pytest Suite:
```bash
pytest tests -v
```
*Runs all 8 tests in <1 second:*
* `tests/test_late_duplicate_triggers.py` (Offline sync abstention & duplicate trigger idempotency)
* `tests/test_source_conflicts.py` (App setting vs. profile dialect & live purchase precedence)
* `tests/test_tool_failure_and_fallback.py` (503 model outage, 45s timeout, malformed JSON, degraded store)
* `tests/test_goal_rule_correction.py` (G03 dynamic correction at 08:30 UTC without database reprocessing)

---

## 3. Directory Layout

```
.
├── run_all.py                     # Single-command pipeline orchestrator
├── README.md                      # Operational guide and setup instructions
├── ARCHITECTURE.md                # System topology, ownership, trust boundaries & latency
├── AI_COLLABORATION.md            # AI tooling log & human verification audit
├── KNOWN_LIMITATIONS.md           # Intentional boundaries & future technical roadmap
├── final_report.md                # Comprehensive technical review & interview walk-through
├── src/                           # Production source code
│   ├── config.py                  # Paths, constants, pricing, and IST timezone utilities
│   ├── models.py                  # Pydantic v2 domain schemas (Decision, Action, State)
│   ├── state_store.py             # Durable per-viewer JSON memory & conflict resolver
│   ├── catalog.py                 # Catalogue index, temporal availability & anti-injection
│   ├── goal_registry.py          # 12 candidate goals, G07 logic, and dynamic G03 rule
│   ├── providers.py               # Pluggable LLM interface (MockProvider, OpenAI, Claude)
│   ├── verifier.py                # Zero-trust air-gapped policy & safety guardrails
│   ├── decision_engine.py         # 4-Tier decision pipeline with sub-2s circuit breaker
│   ├── harness.py                 # Fault injection for 503 model downtime & 8s store lag
│   ├── replay_runner.py           # Priority-queue replay orchestrator for replay day
│   ├── outcome_judge.py           # Exposure-precedence causal goal closure engine
│   └── impact_analyzer.py         # Statistical Intent-To-Treat (ITT) impact analyzer
├── tests/                         # Automated Pytest suite
│   ├── test_late_duplicate_triggers.py
│   ├── test_source_conflicts.py
│   ├── test_tool_failure_and_fallback.py
│   └── test_goal_rule_correction.py
├── sample_run/                    # Validated replay run artifacts
│   ├── decisions.jsonl            # Machine-readable decisions for 100% of triggers
│   ├── actions.jsonl              # Physical published actions for simulator
│   ├── viewer_state/              # Durable JSON files for every triggered viewer
│   ├── sim/                       # Simulation outputs (outcome_events.jsonl, report)
│   ├── outcomes.jsonl             # Evaluated attributable goal outcomes
│   ├── latency_report.json        # Execution latency statistics (p50: 0ms, p95: 3ms)
│   └── impact_report.md           # Statistical ITT analysis vs. randomized holdout
└── doc/                           # Comprehensive architectural design documents
    ├── problem_statement_and_solution.md
    ├── architecture_tradeoffs_and_tech_stack.md
    └── implementation_plan.md
```

---

## 4. Key Results & Performance Summary

* **Decisions Evaluated:** 2,769 triggers (100% recorded with evidence and freshness).
* **Actions Published:** 703 physical home pages.
* **Simulator Policy Problems:** **0 problems** (zero holdout actions, zero quiet hour violations, zero frequency cap violations, zero rejected pages).
* **Latency Profile:**
  - $p50 = 0\text{ ms}$
  - $p95 = 3.0\text{ ms}$
  - $p99 = 5.0\text{ ms}$
  - $\text{Max} = 12\text{ ms}$
  - 100% compliant with the 60-second SLA limit.
* **Causal Impact (ITT):**
  - Treatment Conversion: **77.08%**
  - Holdout Conversion: **77.66%**
  - True ITT Uplift: **-0.59%** ($p = 0.774$)
  - Contrasted with the flawed "served vs. unserved" comparison which showed a misleading **+9.37%** apparent uplift due to survivorship bias.

