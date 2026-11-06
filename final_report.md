# Final Engineering Report & Technical Walkthrough

**Challenge:** One User, One Agent (Autonomous OTT Dialect Lifecycle Management System)  
**Role:** Senior AI Engineer / Applied LLM Engineer  
**Date:** November 2026  

---

## 1. Executive Summary

This report concludes the technical build for the **"One User, One Agent"** engineering challenge.

We have designed, implemented, and verified an end-to-end lifecycle management system where **each viewer is assigned a dedicated agent**. The agent selects one measurable goal, operates under real-time latency budgets on conflicting and imperfect telemetry, verifies actions through zero-trust guardrails, and evaluates attributable impact against a randomized holdout arm.

### Key Milestones Achieved:
1. **100% SLA & Budget Compliance:** All 2,769 replay triggers processed in **2.03 seconds wall time** ($p50 = 0\text{ ms}$, $p95 = 2.0\text{ ms}$, $p99 = 3.0\text{ ms}$, max $12\text{ ms}$, zero SLA breaches).
2. **Zero Policy Violations:** Evaluated against the official `simulator/simulate_outcomes.py`, producing **703 accepted home pages** and **0 policy problems** (zero holdout violations, zero quiet hour violations, zero frequency cap violations, zero empty pages).
3. **Rigorous Test Suite:** All 8 automated test cases in `tests/` pass in **0.92 seconds** (covering offline buffering, duplicate triggers, dialect conflicts, subscription precedence, 503 outage recovery, model hallucinations, store degradation, and dynamic goal rule corrections).
4. **Honest Causal Measurement:** Intent-To-Treat (ITT) statistical analysis proves that the earlier pilot's claimed "+22.4% uplift" was an artifact of survivorship bias.

---

## 2. Technical Discussion Questions (Section 10 Walkthrough)

### Q1: How does your agent decide that what it knows about a viewer is current enough to act on?
**Answer:**  
Our system enforces a strict fact provenance model with an explicit freshness hierarchy:
1. **Timestamp Age Check:** Every trigger calculates $\Delta t = t_{\text{received}} - t_{\text{occurred}}$. If $\Delta t > 600\text{ s}$ (10 minutes), the event is classified as an offline-buffered sync. The agent ingests the facts into history but explicitly abstains from publishing a live home page or immediate message, because the viewer is not actively on the app.
2. **Source Precedence Ladder:**
   $$\text{Replay Live Telemetry} \succ \text{Data Events Telemetry} \succ \text{Warehouse Profile Snapshot}$$
   If a warehouse profile exported 24 hours ago indicates `subscription_status: never`, but a `purchase_completed` telemetry event arrives at any point thereafter, the telemetry event immediately supersedes the warehouse snapshot.
3. **Dialect Context:** For client-facing UI (home pages), the agent treats the `app_dialect` sent in the trigger event as authoritative for client rendering, while recording any divergence from `preferred_dialect` as a visible conflict in the decision audit trail.

---

### Q2: When should the agent do nothing, and how do you know that was the right call?
**Answer:**  
"Doing nothing" (`NO_ACTION`) is treated as a first-class, intentional decision. The agent explicitly abstains under five documented conditions:
1. **Holdout Partition:** The viewer is assigned to the control holdout arm. Intervention is strictly prohibited to preserve experimental integrity.
2. **Offline-Buffered Delayed Sync:** The trigger arrived hours or days after it occurred. Publishing a 120-minute home page is wasted compute and will not be seen.
3. **Inventory Absence:** The viewer's client dialect is `d7`, `NA`, or missing. Since `d7` has 0 titles in the catalogue, attempting to construct a home page would collapse rows and result in a rejected empty page.
4. **Active Intervention In Flight:** A personalized home page was published $<120$ minutes ago for the same active goal. Re-publishing creates state churn without marginal user benefit.
5. **Policy & Timing Ineligibility:** The trigger occurs during quiet hours ($22:00\text{--}08:00\text{ IST}$), or the user has already received a message today, and home page personalization is not indicated.

**How we know it was the right call:**  
In `sample_run/sim/simulator_report.json`, **policy problems were exactly 0**, and **home page rejections were 0**. If our agent had forced actions on `d7` or holdout users, the simulator would have flagged explicit policy errors.

---

### Q3: How would you show that the agent caused a change rather than selecting viewers who were already likely to convert?
**Answer:**  
We prove causality using two independent mechanisms:
1. **Intent-To-Treat (ITT) over Randomized Holdout:**  
   We reject the flawed "served vs. unserved" comparison from the pilot. Instead, we compare the **entire randomized treatment arm** against the **entire randomized holdout arm**. Because randomization distributes all baseline characteristics (activity level, willingness to pay, dialect preferences) equally between both arms, any statistically significant difference in conversion is causally attributable to the agent.
2. **Exposure-Precedence Causal Attribution:**  
   In our Outcome Judge (`src/outcome_judge.py`), we filter out conversions that occurred without prior exposure. The simulator includes 38 scripted organic purchases in `live_events.jsonl`. If a viewer buys a subscription without ever viewing a personalized home page (`home_page_shown` with `personalised: true`) or clicking a message, our system classifies the conversion as `ORGANIC_UNATTRIBUTED`, preventing false claims of credit.

---

### Q4: What happens when 1,000 viewers open the app in the same minute?
**Answer:**  
Our architecture is designed for peak load resilience:
1. **Tier 0 & Tier 1 Deterministic Fast-Path:**  
   Holdout checks, offline lag filtering, dialect validation, and fact-based goal filtering execute in $<2\text{ ms}$ of CPU time without any I/O or network locks.
2. **Circuit Breakers & Model Call Budgets:**  
   Under heavy peak bursts, external model providers can become throttled or slow down. Our Decision Engine enforces a strict **2,000ms timeout**. If model calls queue up or exceed 2 seconds, the circuit breaker automatically routes the trigger to Tier 2 Deterministic Fallback, which curates available dialect titles in $<1\text{ ms}$.
3. **Benchmark Validation:**  
   In our replay run, all 2,769 triggers were processed in **2.03 seconds**, demonstrating a sustained throughput of $>1,350\text{ decisions/second}$ on a single core.

---

### Q5: Which decisions should never be automated?
**Answer:**  
1. **Pricing & Financial Terms Alterations:**  
   Agents must never be allowed to invent custom subscription prices, offer unauthorized discounts, or extend billing trial periods dynamically. All pricing must be strictly hardcoded from verified billing configurations (`pricing.json`).
2. **Direct PII Alteration & Consent Overrides:**  
   An agent must never be permitted to re-enable opt-in flags for a user who explicitly unsubscribed (`notification_opt_out`). Consent is an inviolable compliance boundary.
3. **Legal Content Revocation Overrides:**  
   When a title is withdrawn due to copyright or licensing expiry (e.g. `T0001` at 07:00 UTC), no agent may continue promoting or serving that content under any optimization rationale.
4. **Policy & Quiet Hours Exceptions:**  
   Automated systems must never bypass quiet hours ($22:00\text{--}08:00\text{ IST}$) based on predicted high urgency or high conversion probability.

---

### Q6: How would the system work for 10 million viewers and 40 dialects?
**Answer:**  
To scale from 5,000 viewers to 10 million viewers across 40 dialects:
1. **Virtual Actor Framework:**  
   Model each viewer agent as a stateful, distributed actor (e.g. using Ray Actors, Microsoft Orleans, or Akka). Each actor is activated into memory upon app open, holds the viewer's single active plan, and hibernates after session inactivity.
2. **Sharded In-Memory Tier:**  
   Replace local JSON state files with a distributed, partitioned caching layer (e.g., Redis Cluster or Aerospike) partitioned by `hash(user_id)`.
3. **Dialect-Sharded Catalogue Indices:**  
   Pre-index the catalogue into 40 independent in-memory indices by dialect. When a viewer opens the app in Dialect 14, the actor queries only Dialect 14 inventory, ensuring $O(1)$ title lookup regardless of total catalog size.
4. **Edge Gateway Inference:**  
   Deploy Tier 0 and Tier 3 guardrails directly at edge API gateways (e.g., Cloudflare Workers or Envoy sidecars). 60% of requests (holdouts, repeat opens, offline syncs, quiet hours) are resolved at the network edge in $<5\text{ ms}$ without ever hitting backend LLM infrastructure.

---

### Q7: What did an AI coding assistant suggest that you chose not to accept?
**Answer:**  
As documented in `AI_COLLABORATION.md`, five significant AI suggestions were audited and rejected:
1. **Dialect Fallback on Missing Settings:** The assistant suggested falling back to profile dialect when `app_dialect` is `None` or `NA`. Inspection of `simulate_outcomes.py` line 249 revealed that the client only requests the page for its own dialect (`p[1] != dialect`). Publishing in a profile dialect would result in pages that are never shown. We rejected this and implemented strict abstention.
2. **Reprocessing on Goal Correction:** The assistant suggested querying and re-running morning decisions when G03 was corrected at 08:30 UTC. The brief explicitly penalizes reprocessing all users. We rejected this and updated only the in-flight evaluation rule for open goals.
3. **UTC Timezone Quiet Hours:** The assistant suggested checking quiet hours using UTC hours. In India (IST, UTC+05:30), this would have sent messages at 3:30 AM local time and triggered opt-out penalties. We enforced explicit IST conversion.
4. **Unconditional Conversion Attribution:** The assistant suggested crediting the agent with all purchases during the goal window. We rejected this to avoid claiming false credit for the 38 scripted organic purchases.
5. **Independent Row Selection Without Slug Registry:** The assistant suggested letting the model pick 3 titles per row independently. In thin dialects, duplicate content slugs across rows cause simulator row drops. We built a global page-level slug registry.

---

## 3. Submission Artifact Verification

All required submission deliverables have been generated and validated:
* `README.md` (Operational setup and run commands)
* `ARCHITECTURE.md` (System topology and trust boundaries)
* `AI_COLLABORATION.md` (Human oversight audit)
* `KNOWN_LIMITATIONS.md` (Design boundaries and future roadmap)
* `src/` (Production implementation)
* `tests/` (8 passing pytest suites)
* `sample_run/decisions.jsonl` (2,769 decisions)
* `sample_run/actions.jsonl` (703 published actions)
* `sample_run/viewer_state/` (5,000 durable state JSONs)
* `sample_run/outcomes.jsonl` (703 evaluated goal outcomes)
* `sample_run/latency_report.json` (Latency benchmarks)
* `sample_run/impact_report.md` (Causal ITT impact report)

