---
name: brainstorming
description: >-
  Interactive framework for collaborative brainstorming, design exploration,
  architecture ideation, and evaluating technical trade-offs before implementing complex systems.
  Use when exploring ideas, designing agent workflows, stress-testing assumptions, or refining requirements.
---

# Brainstorming & Architecture Ideation Skill

This skill provides a structured, collaborative methodology for brainstorming and stress-testing system designs, agent architectures, and complex technical decisions before committing to implementation.

---

## 1. Core Principles

1. **Clarify Constraints First**: Ground all ideation in strict physical, computational, operational, and policy boundaries (e.g., latency budgets, data consistency, consent rules, trust boundaries).
2. **Divergent Before Convergent**: Explore multiple viable paradigms (e.g., pure LLM vs. hybrid heuristic-LLM vs. finite state machines) before narrowing down.
3. **Stress-Test Assumptions**: Actively look for edge cases, adversarial inputs, data imperfections, and failure modes (e.g., stale state, prompt injection, cascade failures).
4. **Independent Verification**: Separate generation/proposal mechanisms from deterministic verification and safety guardrails.
5. **Measurable Outcomes**: Ensure every decision is falsifiable, attributable, and evaluated against true counterfactuals (e.g., randomized holdout).

---

## 2. The 5-Step Brainstorming Workflow

```
[1. Problem Framing] ──> [2. Divergent Options] ──> [3. Stress-Testing] ──> [4. Trade-Off Evaluation] ──> [5. Convergent Blueprint]
```

### Step 1: Problem Framing & Boundaries
- Identify the core objective vs. secondary goals.
- Enumerate non-negotiable constraints:
  - Latency budget (p50, p95, hard timeouts).
  - Cost and call limits (model call budget, tool budget).
  - Policy, compliance, and privacy rules.
  - Data availability, provenance, and freshness.

### Step 2: Divergent Solution Exploration
- Brainstorm 2 to 3 distinct architectural patterns:
  - **Pattern A (Deterministic / Heuristic First)**: Rule engines, scoring heuristics, fast deterministic fallback.
  - **Pattern B (Pure Generative / Agentic)**: Dynamic LLM planning, multi-agent reasoning, open tool selection.
  - **Pattern C (Hybrid Cognitive Architecture)**: Deterministic state tracking + LLM for intent/creative ranking + deterministic verifier circuit.
- Document the distinctive merits and failure risks of each.

### Step 3: Adversarial & Edge Case Stress-Testing
- What happens under degraded or slow dependencies (e.g., 503 outages, elevated p95 latency)?
- What happens if inputs are adversarial (prompt injections in catalog metadata, malformed data)?
- What happens with temporal distortions (out-of-order events, offline-buffered triggers, clock drift)?
- What happens under peak load surges?

### Step 4: Trade-Off Analysis
Compare candidate approaches across:
- **Decision Quality & Adaptability**
- **Deterministic Reliability & Latency Predictability**
- **Safety & Verification Guarantees**
- **Auditability & Explainability**
- **Observability & Ease of Testing**

### Step 5: Convergent Blueprint & Next Steps
- Agree on the selected architecture.
- Define interface contracts, trust boundaries, and state representation.
- Produce an actionable execution roadmap with verifiable milestones.

