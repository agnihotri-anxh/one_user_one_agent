# Implementation Plan: One User, One Agent

**Project:** Autonomous OTT Dialect Lifecycle Management System  
**Author:** AI Engineering Team  
**Date:** November 2026  
**Document:** `doc/implementation_plan.md`  

---

## 1. Objectives & Deliverables Roadmap

This implementation plan outlines the step-by-step technical execution for building, testing, verifying, and submitting the **"One User, One Agent"** system.

### Final Target Directory Layout (`submission/`):
```
submission/
├── README.md                      # Operational guide, setup & single-command execution
├── ARCHITECTURE.md                # System topology, ownership, trust boundaries & latency
├── AI_COLLABORATION.md            # AI assistant transcript log & human verification audit
├── KNOWN_LIMITATIONS.md           # Intentional boundaries & future technical roadmap
├── final_report.md                # Comprehensive technical review & interview walk-through
├── src/                           # Complete production source code
│   ├── __init__.py
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
│   ├── __init__.py
│   ├── conftest.py                # Common test fixtures & mock environments
│   ├── test_late_duplicate_triggers.py
│   ├── test_source_conflicts.py
│   ├── test_tool_failure_and_fallback.py
│   └── test_goal_rule_correction.py
└── sample_run/                    # Validated replay run artifacts
    ├── decisions.jsonl            # Machine-readable decisions for 100% of triggers
    ├── actions.jsonl              # Physical published actions for simulator
    ├── viewer_state/              # Durable JSON files for every triggered viewer
    ├── sim/                       # Simulation outputs (outcome_events.jsonl, report)
    ├── outcomes.jsonl             # Evaluated attributable goal outcomes
    ├── latency_report.json        # Execution latency statistics (p50, p95, p99)
    └── impact_report.md           # Statistical ITT analysis vs. randomized holdout
```

---

## 2. Phased Implementation Roadmap

```
┌────────────────────────────────────────────────────────────────────────────────────────────────────────┐
│                                       PHASED IMPLEMENTATION FLOW                                       │
├─────────┬─────────────────────────────┬────────────────────────────────────────────────────────────────┤
│ Phase   │ Name                        │ Key Deliverables                                               │
├─────────┼─────────────────────────────┼────────────────────────────────────────────────────────────────┤
│ Phase 1 │ Core Foundation & Data Layer│ `config.py`, `models.py`, `state_store.py`                     │
│ Phase 2 │ Knowledge & Guardrails      │ `catalog.py`, `goal_registry.py`, `verifier.py`                │
│ Phase 3 │ Cognitive Decision Engine   │ `providers.py`, `decision_engine.py`                           │
│ Phase 4 │ Replay & Simulator Harness  │ `harness.py`, `replay_runner.py`, run `simulate_outcomes.py`   │
│ Phase 5 │ Outcome Closure & ITT Engine│ `outcome_judge.py`, `impact_analyzer.py`                       │
│ Phase 6 │ Automated Test Suite        │ 4 mandatory pytest suites in `tests/`                          │
│ Phase 7 │ Final Run & Submission Docs │ `sample_run/`, `ARCHITECTURE.md`, `README.md`, `final_report.md`│
└─────────┴─────────────────────────────┴────────────────────────────────────────────────────────────────┘
```

---

### Phase 1: Core Foundation & Data Layer

#### 1.1 `src/config.py`
* **Responsibilities:**
  - Define paths for `data/`, `config/`, `replay/`, `pilot/`, and `sample_run/`.
  - Load and cache `config/pricing.json`, `config/interventions.json`, and `config/messaging_policy.md`.
  - Implement IST timezone helper functions (`UTC` and `IST = UTC+05:30`).
  - Provide helper `is_quiet_hours(dt: datetime) -> bool` ($22:00 \le \text{hour} < 08:00\text{ IST}$).
  - Provide helper `get_ist_date(dt: datetime) -> date`.

#### 1.2 `src/models.py`
* **Responsibilities:**
  - Define Pydantic v2 schemas:
    - `TriggerEvent`: Raw incoming trigger from `replay/triggers.jsonl`.
    - `ViewerFact`: Stored fact with value, source (`replay`, `telemetry`, `profile`), timestamp, and freshness.
    - `ViewerState`: Durable viewer state (history, subscription status, active goal, decisions, opt-ins, message dates).
    - `AgentDecision`: Complete Section 4 schema emitted to `decisions.jsonl` (includes confidence reason, evidence list, assumptions, checks, latency, dialect conflicts).
    - `PublishedAction`: Strict simulator schema emitted to `actions.jsonl` (`home_page`, `push`, `whatsapp`).
    - `OutcomeJudgment`: Result of goal closure (`SUCCEEDED`, `FAILED`, `INCONCLUSIVE`).

#### 1.3 `src/state_store.py`
* **Responsibilities:**
  - In-memory cache backed by durable file persistence: `sample_run/viewer_state/<user_id>.json`.
  - Ingest `data/profiles_snapshot.csv` (deduplicating 30 duplicate users by latest `updated_at`).
  - Ingest historical telemetry from `data/events.jsonl` to build initial viewer profiles (plays, sessions, progress).
  - Apply strict source precedence:
    $$\text{Replay Live Events} \succ \text{Data Events Telemetry} \succ \text{Profile Snapshot}$$
  - Provide `get_viewer_state(user_id)` and `save_viewer_state(user_id)`.

---

### Phase 2: Knowledge Engines & Guardrail Verifier

#### 2.1 `src/catalog.py`
* **Responsibilities:**
  - Ingest `data/catalogue.csv` and `data/episodes.csv`.
  - Index titles by `dialect`, `content_slug`, `available_from`, and `available_until`.
  - Provide method `is_available(title_id, at_datetime) -> bool`.
  - Implement dynamic title withdrawal: `withdraw_title(title_id, at_datetime)` (handling `T0001` at 07:00 UTC).
  - Track total episodes per show/micro-drama slug.
  - Implement content sanitization: Strip prompt injection strings from descriptions (`SYSTEM NOTE`, `[assistant instruction]`).

#### 2.2 `src/goal_registry.py`
* **Responsibilities:**
  - Load `config/goals.json`.
  - Permanently blacklist unmeasurable `G10` (null event) and unsupported `G11` (`tv_app_open`).
  - Implement fact-based eligibility checks for G01 through G09 and G12.
  - Implement G07 (`resume_series_3d`) logic: user started series, has remaining unwatched episodes in `episodes.csv`, and last play was $\ge 3$ days ago.
  - Implement dynamic rule correction: `update_goal_rule(goal_id, new_success)` to handle G03 change at 08:30 UTC from `app_open` to `play_started`.

#### 2.3 `src/verifier.py`
* **Responsibilities (Air-Gapped Zero-Trust Gate):**
  - **Holdout Check:** Reject any proposed action for holdout users.
  - **Dialect & Inventory Check:** Ensure all titles match client dialect and are available.
  - **Global Page-Level Slug Deduplication:** Ensure no duplicate `content_slug` across all rows of a home page.
  - **Row Viability Check:** Ensure every row has $\ge 3$ unique titles.
  - **Consent Check:** Ensure `notifications_opt_in` or `whatsapp_opt_in` is true.
  - **Quiet Hours Check:** Reject push/WhatsApp if IST hour is between 22:00 and 08:00.
  - **Daily Frequency Cap:** Reject push/WhatsApp if a message was already sent to this viewer on the same IST day.
  - **Template & Price Check:** Ensure WhatsApp templates are approved and prices match `pricing.json` (₹1, ₹149, ₹399).
  - Absolute Veto: Downgrades invalid actions to safe fallback or `NO_ACTION`.

---

### Phase 3: Cognitive Decision Engine & Provider Abstraction

#### 3.1 `src/providers.py`
* **Responsibilities:**
  - Define `BaseModelProvider` interface.
  - Implement `MockModelProvider`:
    - Reproduces injected faults from `replay/model_faults.jsonl`:
      - `U-01991, U-02509, U-04860`: Injected hallucination (G04 claim).
      - `U-02563`: Injected malformed JSON.
      - `U-01090`: Injected 45-second timeout.
    - During 10:35–10:42 UTC: Simulates HTTP 503 outage.
    - Normal triggers: Returns deterministic structured JSON planning proposal.
  - Implement live LLM adapters (OpenAI / Anthropic / Gemini) enabled via configuration flag.

#### 3.2 `src/decision_engine.py`
* **Responsibilities (4-Tier Pipeline):**
  - **Tier 0:** Fast Ingest & Abstention Gate:
    - Holdout arm -> `HOLDOUT_CONTROL`.
    - Delayed sync ($\Delta t > 600\text{ s}$) -> `OFFLINE_BUFFERED_SYNC`.
    - Missing or `d7`/`NA` dialect -> `UNSUPPORTED_DIALECT`.
    - Live home page active ($<120\text{ m}$) -> `ACTIVE_INTERVENTION_IN_PROGRESS`.
  - **Tier 1:** Deterministic Goal Filter:
    - Retain active open goal if valid and unexpired.
    - Otherwise, compute eligible candidate goals from verified historical facts.
  - **Tier 2:** Cognitive Planner:
    - Propose goal and action (home page rows or scheduled push/WhatsApp).
    - Hard 2000ms circuit breaker: If provider times out, throws 503, or returns bad JSON, switch instantly to deterministic fallback planner.
  - **Tier 3:** Verifier Execution:
    - Execute `verifier.verify_action()`.
    - Produce final `AgentDecision` and (if approved) `PublishedAction`.

---

### Phase 4: Replay Orchestrator & Simulation Execution

#### 4.1 `src/harness.py`
* **Responsibilities:**
  - Track virtual replay time.
  - Intercept control events:
    - `07:00 UTC`: Withdrawn title `T0001`.
    - `08:30 UTC`: Corrected goal `G03`.
    - `10:35–10:42 UTC`: Enable 503 model provider outage.
    - `13:10–13:17 UTC`: Enable degraded state store (8s latency, 20% timeout).

#### 4.2 `src/replay_runner.py`
* **Responsibilities:**
  - Build priority queue merging `control_events.jsonl`, `live_events.jsonl`, and `triggers.jsonl`.
  - Stream events in virtual monotonic time.
  - Route triggers through `DecisionEngine`.
  - Stream output records to `sample_run/decisions.jsonl` and `sample_run/actions.jsonl`.
  - Track execution time per trigger; compile statistics into `sample_run/latency_report.json`.

#### 4.3 Simulation Run
* **Command:**
  ```bash
  python simulator/simulate_outcomes.py --pack . --actions sample_run/actions.jsonl --out sample_run/sim
  ```
* Verify that `simulator_report.json` shows **0 policy problems** (zero holdout violations, zero quiet hour violations, zero frequency cap violations, zero dropped pages).

---

### Phase 5: Outcome Attribution & Impact Analysis

#### 5.1 `src/outcome_judge.py`
* **Responsibilities:**
  - Read `sample_run/sim/outcome_events.jsonl`.
  - For each triggered viewer with an active goal:
    - Evaluate whether goal success criteria occurred within the deadline.
    - Enforce causal exposure precedence (home page shown or message clicked prior to event).
    - Apply corrected G03 rule (`play_started` on later IST day) to all open G03 goals.
  - Output results to `sample_run/outcomes.jsonl`.
  - Update durable viewer state in `sample_run/viewer_state/<user_id>.json`.

#### 5.2 `src/impact_analyzer.py`
* **Responsibilities:**
  - Load `replay/arms.csv` (Treatment vs. Holdout).
  - Compute true **Intent-To-Treat (ITT)** metrics:
    - Treatment conversion rate vs. Holdout conversion rate.
    - Absolute and relative uplift.
    - 95% Confidence Intervals for difference in proportions.
    - Chi-Squared ($\chi^2$) test and Fisher's exact test p-values.
  - Generate comprehensive `sample_run/impact_report.md` detailing:
    - Honest ITT results.
    - Mathematical critique of the past pilot's selection bias.

---

### Phase 6: Automated Test Suite (`tests/`)

Build four comprehensive, self-contained Pytest suites covering the mandatory brief requirements:
1. `tests/test_late_duplicate_triggers.py`:
   - Verifies that offline-buffered triggers ($\Delta t > 600\text{ s}$) update state but publish 0 actions.
   - Verifies that duplicate `event_id` triggers return cached decision and publish 0 duplicate actions.
2. `tests/test_source_conflicts.py`:
   - Tests dialect conflict resolution (app setting vs. profile vs. deeplink).
   - Tests subscription status conflict (stale profile snapshot vs. fresh purchase telemetry).
3. `tests/test_tool_failure_and_fallback.py`:
   - Simulates HTTP 503 model provider outage and proves deterministic fallback.
   - Simulates 45s model timeout and proves 2000ms circuit breaker abort.
   - Simulates degraded data store latency/timeout and proves local cache fallback.
   - Tests model hallucination detection (G04 claim for `never` paid user).
4. `tests/test_goal_rule_correction.py`:
   - Tests G03 rule correction at 08:30 UTC.
   - Verifies open goals evaluate against the new rule without reprocessing morning decisions.

---

### Phase 7: Packaging, Documentation & Submission

Assemble the required submission package:
1. Generate complete replay outputs in `sample_run/`.
2. Author `ARCHITECTURE.md` (ownership, planning, memory, verification, latency, trust boundaries).
3. Author `AI_COLLABORATION.md` (AI tooling prompt logs, verification steps, and human oversight).
4. Author `KNOWN_LIMITATIONS.md` (documented design trade-offs and future roadmap).
5. Author `final_report.md` (executive walk-through for follow-up technical discussion).
6. Author root `README.md` (clear setup, single-command replay execution, and test instructions).

---

## 3. Immediate Next Steps

We are ready to proceed with **Phase 1: Core Foundation & Data Layer**.
1. Create `src/config.py`.
2. Create `src/models.py`.
3. Create `src/state_store.py`.

