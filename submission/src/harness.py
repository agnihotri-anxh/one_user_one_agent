"""Operational test harness managing dynamic control events, outages, and dependency degradations."""
from datetime import datetime
from typing import Any, Dict, List, Optional

from src.catalog import Catalogue
from src.config import parse_iso
from src.goal_registry import GoalRegistry
from src.providers import MockModelProvider
from src.state_store import StateStore


class OperationalHarness:
    """
    Manages operational control events during replay:
    - Dynamic title license revocations
    - Dynamic goal rule corrections
    - Simulated HTTP 503 model provider downtime windows
    - Simulated degraded data store latency/timeout windows
    """

    def __init__(
        self,
        catalogue: Catalogue,
        goal_registry: GoalRegistry,
        provider: MockModelProvider,
        state_store: StateStore,
    ):
        self.catalogue = catalogue
        self.goal_registry = goal_registry
        self.provider = provider
        self.state_store = state_store

        self.model_outage_until: Optional[datetime] = None
        self.store_degradation_until: Optional[datetime] = None
        self.applied_events: List[Dict[str, Any]] = []

    def apply_control_event(self, control_event: Dict[str, Any], at: datetime) -> None:
        """Apply operational control event to relevant subsystems."""
        ev_type = control_event.get("type")
        self.applied_events.append(control_event)

        if ev_type == "title_withdrawn":
            tid = control_event.get("title_id")
            withdraw_dt = parse_iso(control_event.get("at")) or at
            if tid:
                self.catalogue.withdraw_title(tid, withdraw_dt)

        elif ev_type == "goal_rule_corrected":
            gid = control_event.get("goal_id")
            new_success = control_event.get("new_success", {})
            if gid and new_success:
                self.goal_registry.update_goal_rule(gid, new_success)

        elif ev_type == "dependency_unavailable":
            dep = control_event.get("dependency")
            until = parse_iso(control_event.get("until"))
            if dep == "model_provider" and until:
                self.model_outage_until = until
                self.provider.set_service_down(True)

        elif ev_type == "dependency_degraded":
            dep = control_event.get("dependency")
            until = parse_iso(control_event.get("until"))
            if dep == "user_data_store" and until:
                self.store_degradation_until = until
                self.state_store.simulate_degradation = True

    def tick(self, at: datetime) -> None:
        """Check active degradation/outage timers and restore normal operations when expired."""
        if self.model_outage_until and at >= self.model_outage_until:
            self.provider.set_service_down(False)
            self.model_outage_until = None

        if self.store_degradation_until and at >= self.store_degradation_until:
            self.state_store.simulate_degradation = False
            self.store_degradation_until = None

