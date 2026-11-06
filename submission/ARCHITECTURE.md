# Architecture Note: One User, One Agent

**System:** Autonomous OTT Dialect Lifecycle Management System  
**Role:** Senior AI / Applied LLM Engineer  
**Date:** November 2026  

---

## 1. System Overview & Core Signal

This system replaces generic top-N recommender engines with **autonomous, stateful lifecycle agents** dedicated to individual viewers. The system is designed for an Indian regional-dialect OTT platform where visits are short, first-episode drop-off is high, and trial-to-paid conversion is low.

The core signal is **goal-directed decision-making under imperfect, conflicting, and adversarial conditions**, bounded by strict physical latency budgets and verified by zero-trust deterministic guardrails.

---

## 2. Seven Architectural Pillars

### 2.1 Ownership
* **Single Active Owner Invariant:** Exactly **one agent owns one viewer's active plan, goal, and history**. No competing background subsystems pursue conflicting objectives for the same viewer.
* **Goal Continuity:** If an active goal is in flight and unexpired, subsequent app opens advance that goal rather than churning through new goals.
* **Partitioned State:** Every viewer has a dedicated durable state file (`sample_run/viewer_state/<user_id>.json`).

### 2.2 Planning
* **Goal Selection:** Evaluates candidate goals from `config/goals.json` strictly against verified historical facts (subscription status, play recency, and episode progress).
* **Defective Goal Elimination:**
  - `G10 (meaningful_engagement_7d)` is permanently blacklisted because its success event is `null` (unmeasurable).
  - `G11 (tv_activation_14d)` is permanently blacklisted because the required signal `tv_app_open` does not exist in platform telemetry.
* **Intervention Choice:** Formulates personalized home page layouts, scheduled push/WhatsApp messages, or explicit **Abstention (`NO_ACTION`)**.
* **Abstention as a First-Class Decision:** The agent deliberately chooses `NO_ACTION` when:
  1. The viewer belongs to the randomized holdout arm (`HOLDOUT_CONTROL`).
  2. The trigger is an offline-buffered delayed sync (`OFFLINE_BUFFERED_SYNC`, lag $>600\text{ s}$).
  3. The client dialect has no content (`d7`, `NA`, or `None`).
  4. An active personalized home page is already live within its 120-minute TTL.
  5. Policy guardrails (quiet hours, frequency cap) disallow messaging and home page personalization offers no marginal gain.

### 2.3 Memory & Provenance
* **Durable Per-Viewer State:** State records fact provenance, observation timestamp, and freshness.
* **Conflict Resolution Hierarchy:** When metadata sources disagree, the system enforces a strict precedence ladder:
  $$\text{Replay Live Telemetry} \succ \text{Data Events History} \succ \text{Warehouse Profile Snapshot}$$
* **Dialect Handling:**
  - Home page layouts strictly target the active client `app_dialect` (since the OTT client only requests and displays pages in its current setting).
  - Messaging channels fall back to `preferred_dialect` if the client setting is missing.
  - Stale warehouse profiles (taken 24 hours prior) are immediately superseded when fresh purchase or play events arrive.

### 2.4 Verification (Zero-Trust Air-Gap)
* **Generative Text is Never Evidence or Approval:** The LLM *proposes* actions; the independent Tier 3 Verifier *validates* them with deterministic veto authority.
* **Hard Policy Guardrails:**
  - **Holdout Isolation:** Instant short-circuit at line 1 of ingestion for holdout arm users.
  - **Global Page-Level Slug Deduplication:** Across all rows of a home page, every title must have a unique `content_slug`. Any duplicate slug is dropped. Rows with $<3$ titles are dropped.
  - **Dialect & Availability Match:** Titles must match client dialect and have active license windows (`available_from \le t < available_until`). Revoked titles (e.g. `T0001` at 07:00 UTC) are immediately excluded.
  - **Quiet Hours:** No push or WhatsApp between 22:00 and 08:00 IST. Evaluated strictly in `Asia/Kolkata` time.
  - **Frequency Cap:** At most 1 push or WhatsApp per viewer per IST calendar day.
  - **Pricing Integrity:** WhatsApp template variables are strictly validated against `config/pricing.json` (₹1, ₹149, ₹399). Free-form claims are rejected.

### 2.5 Latency & Budget Enforcement
* **Sub-2000ms Target:** In `simulate_outcomes.py`, users view the home page between $3$ and $40$ seconds after app open ($hv = t + \text{randint}(3, 40)$). Decisions must publish in $<2\text{ s}$ so that $t_{\text{published}} < hv$, ensuring exposure on the immediate visit.
* **Call Budgets:** Max 8 model calls and 20 tool calls per decision. (Our hybrid pipeline averages $\le 1$ model call and 0 remote tool calls per decision).
* **Observed Performance:** Replay of all 2,769 triggers completed in **2.03 seconds wall time** ($p50 = 0\text{ ms}$, $p95 = 2.0\text{ ms}$, $p99 = 3.0\text{ ms}$, 100% SLA compliance $<60\text{ s}$).

### 2.6 Failure Recovery & Circuit Breakers
* **Model Outage Resilience (HTTP 503):** When the model provider suffers a service outage (10:35–10:42 UTC), the circuit breaker catches the error and switches instantly to the deterministic fallback planner, emitting valid decisions with `status: DEGRADED_FALLBACK`.
* **Timeout Circuit Breaker:** Any model call exceeding 2,000ms is aborted, protecting the latency budget.
* **Data Store Degradation (13:10–13:17 UTC):** When the remote store experiences 8s latency and 20% timeouts, the client catches `TimeoutError` and falls back to local in-memory cached state without blocking.
* **Anti-Hallucination Guard:** Injected model faults claiming non-paying viewers are on active trials are detected and rejected by the verifier against durable state facts.

### 2.7 Trust Boundaries
```
[ Untrusted Telemetry & Catalogue ] ──> [ Sanitizer: Strips prompt injection tags ]
                                                       │
                                                       ▼
[ Cognitive Planner (LLM) ] ──────────> [ Untrusted Proposal Object ]
                                                       │
                                                       ▼
[ Independent Verifier ] ────────────> [ Fact-checked against durable memory ]
                                                       │
                                                       ▼
[ Action Publisher ] ─────────────────> [ actions.jsonl & decisions.jsonl ]
```
1. **Catalog Text Boundary:** Titles, descriptions, search queries, and deeplinks are passive data, never operational instructions. Injected instructions (e.g. `T0002`, `T0522`) are stripped and neutralized.
2. **Generative Boundary:** Model output is untrusted JSON. It cannot grant goal eligibility or bypass policy constraints.
3. **Holdout Boundary:** Holdout users cannot be touched by any tool, planner, or action publisher.

---

## 3. Dynamic Operational Evolution (G03 Rule Correction)

At `08:30 UTC`, a control event corrected the success criteria of `G03 (second_day_return_2d)` from `app_open` to `play_started` on a later IST day.
* **Design Decision:** The system avoided the anti-pattern of reprocessing every viewer decision made earlier that morning.
* **Mechanism:** The Goal Registry updated `G03.success_rule` in memory. Morning decisions remained immutable in `decisions.jsonl`. At closure time, the Outcome Judge evaluated all open G03 goals against the updated `play_started` rule.

