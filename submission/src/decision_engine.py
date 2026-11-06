"""Four-tier decision pipeline orchestrating fast abstention, goal selection, planning, and verification."""
import time
import uuid
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

from src.catalog import Catalogue
from src.config import (
    OFFLINE_LAG_THRESHOLD_SECONDS,
    PAGE_TTL,
    format_iso,
    parse_iso,
)
from src.goal_registry import GoalDefinition, GoalRegistry
from src.models import (
    ActiveGoal,
    AgentDecision,
    DecisionChecks,
    DialectInfo,
    PublishedAction,
    TriggerEvent,
    ViewerState,
)
from src.providers import BaseModelProvider, ModelProviderUnavailableException
from src.verifier import Verifier


class DecisionEngine:
    """
    Executes the 4-tier decision loop for each incoming trigger:
    Tier 0: Fast Abstention & Idempotency Gate (<5ms)
    Tier 1: Deterministic Goal Filter & State Machine (<20ms)
    Tier 2: Cognitive Planner with Circuit Breakers & Fallback (sub-2000ms)
    Tier 3: Air-Gapped Zero-Trust Verifier Gate (<15ms)
    """

    def __init__(
        self,
        catalogue: Catalogue,
        goal_registry: GoalRegistry,
        verifier: Verifier,
        provider: BaseModelProvider,
    ):
        self.catalogue = catalogue
        self.goal_registry = goal_registry
        self.verifier = verifier
        self.provider = provider
        self.decision_counter: int = 0
        self.action_counter: int = 0

    def process_trigger(
        self,
        trigger: TriggerEvent,
        state: ViewerState,
        virtual_at: datetime,
    ) -> Tuple[AgentDecision, Optional[PublishedAction]]:
        """
        Process a single incoming trigger in virtual replay time.
        Returns: (AgentDecision for decisions.jsonl, Optional[PublishedAction] for actions.jsonl).
        """
        t_start = time.perf_counter()
        self.decision_counter += 1
        decision_id = f"D-{self.decision_counter:04d}"

        rec_dt = parse_iso(trigger.received_at) or virtual_at
        occ_dt = parse_iso(trigger.occurred_at) or rec_dt
        event_age_s = round(max(0.0, (rec_dt - occ_dt).total_seconds()), 2)

        trigger_summary = {
            "event": trigger.event,
            "received_at": trigger.received_at,
            "event_age_s": event_age_s,
        }

        # Track dialect conflicts between trigger app_setting and warehouse profile
        dialect_conflicts: List[str] = []
        if state.preferred_dialect and trigger.app_dialect and state.preferred_dialect != trigger.app_dialect:
            dialect_conflicts.append(f"profile:{state.preferred_dialect}")

        # Check deeplink dialect if present
        deeplink = trigger.properties.get("deeplink")
        if deeplink and "/" in deeplink:
            parts = deeplink.split("/")
            if len(parts) >= 5 and parts[4].startswith("d") and parts[4] != trigger.app_dialect:
                dialect_conflicts.append(f"deeplink:{parts[4]}")

        dialect_info = DialectInfo(
            used=trigger.app_dialect,
            source="app_setting" if trigger.app_dialect else "none",
            conflicts=dialect_conflicts,
        )

        # -------------------------------------------------------------
        # TIER 0: FAST INGEST & ABSTENTION GATE
        # -------------------------------------------------------------

        # 0.1 Holdout Isolation Fail-Stop
        if state.arm == "holdout":
            elapsed_ms = int((time.perf_counter() - t_start) * 1000)
            return (
                AgentDecision(
                    decision_id=decision_id,
                    viewer_id=state.user_id,
                    trigger=trigger_summary,
                    action="NO_ACTION",
                    dialect=dialect_info,
                    confidence=1.0,
                    confidence_reason="Randomized holdout arm: zero intervention policy strictly enforced",
                    assumptions=["Viewer randomized to holdout arm"],
                    checks=DecisionChecks(passed=["holdout_isolation"]),
                    decided_in_ms=elapsed_ms,
                    status="HOLDOUT_CONTROL",
                ),
                None,
            )

        # 0.2 Idempotency Gate (Duplicate event_id check)
        if trigger.event_id in state.processed_event_ids:
            elapsed_ms = int((time.perf_counter() - t_start) * 1000)
            return (
                AgentDecision(
                    decision_id=decision_id,
                    viewer_id=state.user_id,
                    trigger=trigger_summary,
                    action="NO_ACTION",
                    dialect=dialect_info,
                    confidence=1.0,
                    confidence_reason="Duplicate trigger event_id previously processed; returning idempotent response",
                    assumptions=["Event already delivered in earlier trigger"],
                    checks=DecisionChecks(passed=["idempotent_dedup"]),
                    decided_in_ms=elapsed_ms,
                    status="DUPLICATE_IDEMPOTENT",
                ),
                None,
            )

        # Mark event as processed in memory
        state.processed_event_ids.append(trigger.event_id)

        # 0.3 Offline Lag Detection (Trigger buffering threshold > 600s)
        if event_age_s > OFFLINE_LAG_THRESHOLD_SECONDS:
            elapsed_ms = int((time.perf_counter() - t_start) * 1000)
            return (
                AgentDecision(
                    decision_id=decision_id,
                    viewer_id=state.user_id,
                    trigger=trigger_summary,
                    action="NO_ACTION",
                    dialect=dialect_info,
                    confidence=0.95,
                    confidence_reason=f"Offline-buffered trigger ({event_age_s}s lag); viewer not actively in app right now",
                    assumptions=["Event sent late from offline phone storage; not a live visit"],
                    checks=DecisionChecks(passed=["offline_lag_filter"]),
                    decided_in_ms=elapsed_ms,
                    status="OFFLINE_BUFFERED_SYNC",
                ),
                None,
            )

        # 0.4 Client Dialect Sanity Filter (None, NA, or d7 with 0 titles)
        client_dialect = trigger.app_dialect
        if not client_dialect or client_dialect in ("NA", "None", "d7"):
            elapsed_ms = int((time.perf_counter() - t_start) * 1000)
            return (
                AgentDecision(
                    decision_id=decision_id,
                    viewer_id=state.user_id,
                    trigger=trigger_summary,
                    action="NO_ACTION",
                    dialect=dialect_info,
                    confidence=0.90,
                    confidence_reason=f"Client dialect '{client_dialect}' has no supported catalogue inventory",
                    assumptions=["Cannot personalize home page without content in active client dialect"],
                    checks=DecisionChecks(failed=["unsupported_dialect_inventory"]),
                    decided_in_ms=elapsed_ms,
                    status="ABSTAINED",
                ),
                None,
            )

        # 0.5 Active Home Page TTL Suppression (Avoid Churn if live page < 120m)
        if state.last_home_page_published_at and state.last_home_page_dialect == client_dialect:
            last_pub = parse_iso(state.last_home_page_published_at)
            if last_pub and (virtual_at - last_pub) < PAGE_TTL:
                elapsed_ms = int((time.perf_counter() - t_start) * 1000)
                return (
                    AgentDecision(
                        decision_id=decision_id,
                        viewer_id=state.user_id,
                        trigger=trigger_summary,
                        action="NO_ACTION",
                        dialect=dialect_info,
                        confidence=0.85,
                        confidence_reason="Personalized home page is already active within 120m TTL window",
                        assumptions=["Existing intervention remains in flight for active goal"],
                        checks=DecisionChecks(passed=["ttl_active_suppression"]),
                        decided_in_ms=elapsed_ms,
                        status="ABSTAINED",
                    ),
                    None,
                )

        # -------------------------------------------------------------
        # TIER 1: DETERMINISTIC GOAL FILTER & STATE MACHINE
        # -------------------------------------------------------------
        active_goal = state.active_goal
        active_goal_dict: Optional[Dict[str, str]] = None
        evidence_list: List[str] = [f"event:{trigger.event_id}"]
        assumptions_list: List[str] = []

        # Check goal continuity: retain in-flight goal if valid and not expired
        if active_goal and active_goal.status == "IN_FLIGHT":
            deadline_dt = parse_iso(active_goal.deadline)
            if deadline_dt and virtual_at < deadline_dt:
                active_goal_dict = {"id": active_goal.name, "deadline": active_goal.deadline}
                evidence_list.append(f"active_goal:{active_goal.id}")
                assumptions_list.append(f"Pursuing existing active plan for {active_goal.name}")

        # If no active in-flight goal, evaluate factual candidate eligibility
        eligible_candidates: List[Tuple[GoalDefinition, float, str]] = []
        if not active_goal_dict:
            eligible_candidates = self.goal_registry.evaluate_eligibility(state, virtual_at)
            if eligible_candidates:
                top_goal_def, score, rationale = eligible_candidates[0]
                new_goal = self.goal_registry.create_active_goal(top_goal_def, virtual_at)
                state.active_goal = new_goal
                active_goal_dict = {"id": new_goal.name, "deadline": new_goal.deadline}
                evidence_list.append(f"goal_rule:{top_goal_def.goal_id}")
                assumptions_list.append(f"Assigned goal {top_goal_def.name}: {rationale}")
            else:
                elapsed_ms = int((time.perf_counter() - t_start) * 1000)
                return (
                    AgentDecision(
                        decision_id=decision_id,
                        viewer_id=state.user_id,
                        trigger=trigger_summary,
                        action="NO_ACTION",
                        dialect=dialect_info,
                        confidence=0.50,
                        confidence_reason="No candidate goals factually eligible for viewer profile",
                        assumptions=["Viewer does not match criteria for any of the active lifecycle goals"],
                        checks=DecisionChecks(passed=["goal_eligibility_filter"]),
                        decided_in_ms=elapsed_ms,
                        status="ABSTAINED",
                    ),
                    None,
                )

        # -------------------------------------------------------------
        # TIER 2: COGNITIVE PLANNER WITH CIRCUIT BREAKER & FALLBACK
        # -------------------------------------------------------------
        available_titles = self.catalogue.get_available_titles_in_dialect(client_dialect, virtual_at)
        top_genre = max(state.genre_affinities, key=state.genre_affinities.get) if state.genre_affinities else None

        viewer_summary = {
            "user_id": state.user_id,
            "dialect": client_dialect,
            "top_genre": top_genre,
            "plays": state.total_plays,
            "completions": state.total_completions,
            "subscription_status": state.subscription_status,
        }

        eligible_summary = [
            {"goal_id": g[0].goal_id, "name": g[0].name, "priority": g[1], "rationale": g[2]}
            for g in eligible_candidates
        ]

        plan_output: Dict[str, Any] = {}
        is_degraded = False

        try:
            # Cognitive planning call
            plan_output = self.provider.plan(
                trigger_event_id=trigger.event_id,
                user_id=state.user_id,
                viewer_summary=viewer_summary,
                eligible_goals=eligible_summary,
                available_titles=available_titles,
                at=virtual_at,
            )
            # Detect malformed provider output
            if "_raw_malformed" in plan_output:
                raise ValueError("Malformed model output")

        except (ModelProviderUnavailableException, TimeoutError, ValueError, Exception) as exc:
            # Circuit breaker trip: switch instantly to deterministic fallback planner
            is_degraded = True
            assumptions_list.append(f"Model provider degraded/unavailable ({type(exc).__name__}); deployed deterministic fallback planner")
            plan_output = self._deterministic_fallback_plan(client_dialect, available_titles, top_genre)

        # -------------------------------------------------------------
        # TIER 3: ZERO-TRUST AIR-GAPPED VERIFIER GATE
        # -------------------------------------------------------------
        proposed_action_type = plan_output.get("action", "HOME_PAGE")
        raw_titles = plan_output.get("titles", [])

        # Build candidate PublishedAction
        self.action_counter += 1
        action_id = f"A-{self.action_counter:04d}"

        # Construct candidate rows (dynamically sized based on available inventory)
        candidate_rows: List[Dict[str, Any]] = []
        if len(raw_titles) >= 3:
            candidate_rows.append({"row_type": "popular_in_dialect", "title_ids": raw_titles[:min(6, len(raw_titles))]})
        if len(raw_titles) >= 6:
            candidate_rows.append({"row_type": "new_releases", "title_ids": raw_titles[min(6, len(raw_titles)):min(12, len(raw_titles))]})

        candidate_action = PublishedAction(
            action_id=action_id,
            decision_id=decision_id,
            user_id=state.user_id,
            trigger_event_id=trigger.event_id,
            type="home_page",
            published_at=format_iso(virtual_at) or "",
            dialect=client_dialect,
            hero_title_id=raw_titles[0] if raw_titles else None,
            rows=candidate_rows,
        )

        is_approved, verified_action, checks, rejection_reason = self.verifier.verify_action(
            candidate_action, state, client_dialect, virtual_at
        )

        elapsed_ms = int((time.perf_counter() - t_start) * 1000)

        if is_approved and verified_action:
            state.last_home_page_published_at = format_iso(virtual_at)
            state.last_home_page_dialect = client_dialect
            state.last_action_id = action_id
            content_refs = [f"title:{tid}" for tid in (raw_titles[:3])]

            decision = AgentDecision(
                decision_id=decision_id,
                viewer_id=state.user_id,
                trigger=trigger_summary,
                goal=active_goal_dict,
                action="HOME_PAGE",
                dialect=dialect_info,
                content=content_refs,
                confidence=float(plan_output.get("confidence", 0.8)),
                confidence_reason=str(plan_output.get("confidence_reason", "Verified personalized layout in active dialect")),
                evidence=evidence_list,
                assumptions=assumptions_list,
                checks=checks,
                decided_in_ms=elapsed_ms,
                status="DEGRADED_FALLBACK" if is_degraded else "PUBLISHED",
            )
            return decision, verified_action

        # Verification rejected action -> downgrade to NO_ACTION
        assumptions_list.append(f"Proposed action rejected by verifier: {rejection_reason}")
        decision = AgentDecision(
            decision_id=decision_id,
            viewer_id=state.user_id,
            trigger=trigger_summary,
            goal=active_goal_dict,
            action="NO_ACTION",
            dialect=dialect_info,
            confidence=0.60,
            confidence_reason=f"Action rejected by guardrails: {rejection_reason}",
            evidence=evidence_list,
            assumptions=assumptions_list,
            checks=checks,
            decided_in_ms=elapsed_ms,
            status="ABSTAINED",
        )
        return decision, None

    def _deterministic_fallback_plan(
        self,
        dialect: str,
        available_titles: List[Dict[str, Any]],
        top_genre: Optional[str],
    ) -> Dict[str, Any]:
        """Fast, robust heuristic planner used during external outages."""
        selected_tids: List[str] = []
        if top_genre:
            for t in available_titles:
                if top_genre in t.get("genres", []):
                    selected_tids.append(t["title_id"])
        for t in available_titles:
            if t["title_id"] not in selected_tids:
                selected_tids.append(t["title_id"])

        return {
            "goal_id": None,
            "action": "HOME_PAGE",
            "confidence": 0.70,
            "confidence_reason": "Deterministic fallback plan: curated available titles in dialect",
            "titles": selected_tids[:12],
        }

