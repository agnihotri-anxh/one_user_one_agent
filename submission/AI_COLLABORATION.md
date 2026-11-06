# AI Collaboration & Verification Log

**Project:** Autonomous OTT Dialect Lifecycle Management System  
**Date:** November 2026  

---

## 1. Collaboration Overview

AI coding assistants were used throughout this project for rapid exploratory data analysis, boilerplate domain modeling, and test scenario generation. 

In strict adherence to the challenge philosophy, **the human engineer directed all architecture, audited every proposal, and actively rejected multiple flawed AI suggestions** that would have broken simulation rules or penalized evaluation scores.

---

## 2. Five Critical AI Proposals Audited & Rejected

| # | What the AI Assistant Suggested | Why It Was Audited & Rejected | The Corrected Implementation |
| :--- | :--- | :--- | :--- |
| **1** | **Fallback to Profile Dialect on `None`/`NA` Triggers**<br>AI suggested: *"If `app_dialect` is missing or `NA`, fall back to `preferred_dialect` from the profile snapshot and publish a home page in that dialect."* | **Audited against `simulate_outcomes.py`:** Line 249 checks `if p[1] != dialect: return p, 1.0, False`. The simulator passes `None` when `app_dialect` is `None`. A page published in `d1` would fail matching, causing silent rejection (`home_page_published_but_not_shown`). | **Strict Abstention on Missing Dialects:** If `app_dialect` is `None`, `'NA'`, or `'d7'` (which has 0 titles), the agent explicitly records `NO_ACTION`, preventing rejected pages. |
| **2** | **Retrospective Reprocessing on Goal Rule Correction**<br>AI suggested: *"When G03 is corrected at 08:30 UTC, query all morning decisions, re-evaluate them, and rewrite decisions.jsonl."* | **Audited against Candidate Brief:** The brief explicitly states in Section 9: *"What will score poorly: reprocessing every viewer after one rule change."* Past decisions are historical commitments. | **In-Flight Rule Updating:** Goal Registry updates `G03.success_rule` in memory. Decisions remain immutable. The Outcome Judge applies the new `play_started` rule at closure time. |
| **3** | **Evaluating Quiet Hours in UTC Time**<br>AI suggested: *"Check `dt.hour >= 22 or dt.hour < 8` on the raw ISO timestamp."* | **Audited against Policy Rules:** All viewers are in India (IST, UTC+05:30). $22:00\text{ UTC} = 03:30\text{ AM IST}$. Evaluating in UTC would send messages in the middle of the night, triggering the simulator's 8% user opt-out penalty. | **Explicit IST Conversion:** Every timestamp is converted to `Asia/Kolkata` time (`dt.astimezone(IST)`) before evaluating quiet hours and daily message frequency caps. |
| **4** | **Naive Attribution of All Post-Decision Purchases**<br>AI suggested: *"If a user makes a purchase within the 7-day window, mark G04/G05 as SUCCEEDED."* | **Audited against Data Telemetry:** `live_events.jsonl` contains 38 scripted organic purchases. Some users buy without ever seeing a personalized home page or message. Claiming credit for organic conversions is false attribution. | **Exposure-Precedence Attribution Gate:** Goal success requires documented antecedent exposure (`home_page_shown` with `personalised: true` or `message_clicked`). Conversions without exposure are classified as `ORGANIC_UNATTRIBUTED`. |
| **5** | **Trusting LLM-Curated Titles Without Global Slug Deduplication**<br>AI suggested: *"Prompt the LLM to pick 3 titles per row and assume rows are independent."* | **Audited against Catalogue & Simulator:** `catalogue.csv` has language variants sharing the same `content_slug`. In `simulate_outcomes.py`, any duplicate slug is dropped; if a row drops below 3 titles, the entire row is rejected. | **Global Page-Level Slug Registry:** Tier 3 Verifier enforces uniqueness on `content_slug` across the entire page (hero + all rows). If inventory is thin (e.g. `d3`), rows are dynamically sized. |

---

## 3. Human-in-the-Loop Verification Workflow

1. **Static Analysis & Schema Validation:**  
   Every Pydantic model (`src/models.py`) was checked against the exact JSON schema in Section 4 of the candidate brief and the simulator input requirements in `README.md`.
2. **Deterministic Replay Execution:**  
   All 2,769 triggers were executed in monotonic virtual time using `MockModelProvider`. No external network or API keys were required.
3. **Official Simulator Validation:**  
   The published actions (`sample_run/actions.jsonl`) were processed through the official `simulator/simulate_outcomes.py`. The resulting report confirmed **0 policy problems** (zero holdout violations, zero quiet hour violations, zero frequency cap violations, 100% home page acceptance).
4. **Automated Regression Testing:**  
   The test suite in `tests/` was run via Pytest, confirming that all 8 edge cases (late triggers, duplicate triggers, dialect conflicts, subscription conflicts, 503 outages, model hallucinations, data store timeouts, and rule corrections) pass reliably.

