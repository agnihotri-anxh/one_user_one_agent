# Known Limitations & Design Boundaries

**Project:** Autonomous OTT Dialect Lifecycle Management System  
**Date:** November 2026  

---

## 1. Executive Summary

In accordance with the assignment guidelines (*"Spend no more than 10-12 hours. Incomplete but well-prioritized work is acceptable"*), this document outlines the intentional design simplifications, architectural boundaries, and future roadmap items left out of the current submission.

---

## 2. Intentional Simplifications & Boundaries

### 2.1 Scale Architecture (Single-Node vs. Distributed Actor Framework)
* **Current Implementation:** The replay runner processes 2,769 triggers sequentially in virtual time on a single process, utilizing in-memory state backed by local JSON persistence in `sample_run/viewer_state/`.
* **Production Horizon (10 Million Viewers & 40 Dialects):**
  - A single-node file system cannot scale to 10M concurrent viewers.
  - In production, each viewer agent would be modeled as a **Virtual Actor / Stateful Entity** (e.g., using Ray Actors, Microsoft Orleans, or Temporal workflows) pinned to a sharded Redis/DynamoDB memory layer.
  - State locks per viewer ensure consistency without global coordination bottlenecks.

### 2.2 Messaging Channel Scope (Push & WhatsApp vs. In-App Popups & SMS)
* **Current Implementation:** Focuses heavily on personalized home pages (the highest-leverage intervention with zero messaging friction), with full policy guardrails for Push and WhatsApp.
* **Intentionally Omitted:** In-app popups and SMS campaigns were omitted from active publication. In-app popups interrupt active video navigation, and SMS introduces higher telecommunication costs without significant conversion advantages over WhatsApp in regional Indian markets.

### 2.3 Generative Marketing Copy vs. Deterministic Templates
* **Current Implementation:** Uses pre-approved templates (`wa_recommend_title_v1`, `wa_new_episode_v2`, `wa_trial_ending_v1`) with deterministic variable extraction from catalog titles and pricing.
* **Why Left Incomplete:** Open-ended LLM generation of promotional text introduces non-zero hallucination risks (e.g., promising non-existent trial discounts or using forbidden urgency words like "hurry"). Strict deterministic templates guaranteed **100% compliance with zero policy violations**.

### 2.4 Multi-Device Concurrent Session Collisions
* **Current Implementation:** The system tracks the latest `app_dialect` and session received by the server.
* **Edge Case Left Unresolved:** If a single viewer simultaneously streams on an Android phone set to `d2` and an iPad set to `d1`, the agent currently tracks the latest arriving event. A complete multi-device arbitration protocol was deferred.

### 2.5 Long-Term Semantic Vector Memory
* **Current Implementation:** Durable memory tracks structured telemetry facts: session counts, watch recency, completed episodes, genre frequency maps, and goal closure history.
* **Production Horizon:** Incorporating dense vector embeddings of user search queries and video watch intervals into a vector database (e.g., Milvus / Qdrant) would allow nuanced semantic affinity matching, but was omitted to maintain sub-2ms decision latency.

