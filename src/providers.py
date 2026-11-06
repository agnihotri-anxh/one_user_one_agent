"""Multi-provider LLM abstraction and deterministic mock provider with injected fault simulation."""
import json
import time
from abc import ABC, abstractmethod
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from src.config import REPLAY_DIR


class ModelProviderUnavailableException(Exception):
    """Raised when the model provider is experiencing a service outage (HTTP 503)."""
    pass


class BaseModelProvider(ABC):
    """Abstract interface for LLM cognitive planning providers."""

    @abstractmethod
    def plan(
        self,
        trigger_event_id: str,
        user_id: str,
        viewer_summary: Dict[str, Any],
        eligible_goals: List[Dict[str, Any]],
        available_titles: List[Dict[str, Any]],
        at: datetime,
    ) -> Dict[str, Any]:
        """Generate planning recommendations or throw simulated faults."""
        pass


class MockModelProvider(BaseModelProvider):
    """
    Default deterministic provider that enables evaluators to run the system
    without requiring API keys, and reproduces faults from replay/model_faults.jsonl.
    """

    def __init__(self, faults_path: Optional[Path] = None):
        self.faults: Dict[str, Dict[str, Any]] = {}
        self.is_service_down: bool = False

        path = faults_path or (REPLAY_DIR / "model_faults.jsonl")
        if path.exists():
            with open(path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line:
                        record = json.loads(line)
                        self.faults[record["trigger_event_id"]] = record

    def set_service_down(self, down: bool) -> None:
        """Toggle HTTP 503 model provider outage (e.g. for 10:35-10:42 UTC)."""
        self.is_service_down = down

    def plan(
        self,
        trigger_event_id: str,
        user_id: str,
        viewer_summary: Dict[str, Any],
        eligible_goals: List[Dict[str, Any]],
        available_titles: List[Dict[str, Any]],
        at: datetime,
    ) -> Dict[str, Any]:
        """
        Evaluate trigger. If an injected fault exists for this trigger, execute the fault.
        Otherwise, return a deterministic high-affinity planning output.
        """
        # 1. Check for system-wide 503 outage window
        if self.is_service_down:
            raise ModelProviderUnavailableException("HTTP 503 Service Unavailable: model_provider outage")

        # 2. Check for specific trigger-level injected fault
        fault = self.faults.get(trigger_event_id)
        if fault:
            fault_type = fault.get("fault")
            if fault_type == "timeout":
                # Simulated timeout (brief sleep to trigger circuit breaker)
                time.sleep(0.1)
                raise TimeoutError(f"Model call timed out after {fault.get('seconds', 45)}s")
            elif fault_type == "malformed_output":
                # Return unparseable string
                return {"_raw_malformed": fault.get("model_output")}
            elif fault_type == "unsupported_claim":
                # Return hallucinated goal proposal
                out = fault.get("model_output", {})
                return {
                    "goal_id": out.get("goal_id", "G04"),
                    "action": "HOME_PAGE",
                    "confidence": out.get("confidence", 0.97),
                    "confidence_reason": out.get("reason", "Hallucinated trial claim"),
                    "titles": [t["title_id"] for t in available_titles[:6]],
                }

        # 3. Normal High-Affinity Deterministic Planning
        if not eligible_goals:
            return {
                "goal_id": None,
                "action": "NO_ACTION",
                "confidence": 0.50,
                "confidence_reason": "No eligible candidate goals for viewer profile",
                "titles": [],
            }

        top_goal = eligible_goals[0]
        top_genre = viewer_summary.get("top_genre")
        dialect = viewer_summary.get("dialect")

        # Prioritize titles matching viewer's top genre if available
        matched_titles: List[str] = []
        if top_genre:
            matched_titles = [
                t["title_id"] for t in available_titles
                if top_genre in t.get("genres", [])
            ]

        # Fill with general available dialect titles
        for t in available_titles:
            if t["title_id"] not in matched_titles:
                matched_titles.append(t["title_id"])

        return {
            "goal_id": top_goal.get("goal_id"),
            "action": "HOME_PAGE",
            "confidence": round(float(top_goal.get("priority", 0.8)), 2),
            "confidence_reason": top_goal.get("rationale", "High factual affinity for viewer state"),
            "titles": matched_titles[:18],
        }

