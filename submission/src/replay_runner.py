"""Replay runner streaming virtual time events in monotonic priority order."""
import json
import statistics
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from src.catalog import Catalogue
from src.config import (
    DATA_DIR,
    REPLAY_DIR,
    SAMPLE_RUN_DIR,
    VIEWER_STATE_DIR,
    format_iso,
    parse_iso,
)
from src.decision_engine import DecisionEngine
from src.goal_registry import GoalRegistry
from src.harness import OperationalHarness
from src.models import AgentDecision, PublishedAction, TriggerEvent
from src.providers import MockModelProvider
from src.state_store import StateStore
from src.verifier import Verifier


class ReplayRunner:
    """
    Executes the replay day (2026-10-01 IST) by merging control events,
    live telemetry, and decision triggers into a single virtual-clock stream.
    """

    def __init__(
        self,
        pack_dir: Optional[Path] = None,
        out_dir: Optional[Path] = None,
    ):
        self.pack_dir = pack_dir or DATA_DIR.parent
        self.out_dir = out_dir or SAMPLE_RUN_DIR
        self.out_dir.mkdir(parents=True, exist_ok=True)
        self.viewer_state_dir = self.out_dir / "viewer_state"
        self.viewer_state_dir.mkdir(parents=True, exist_ok=True)

        # Subsystems initialization
        self.catalogue = Catalogue()
        self.catalogue.load_from_pack(self.pack_dir)

        self.state_store = StateStore(self.viewer_state_dir)
        self.state_store.initialize_from_pack(self.pack_dir, self.catalogue.titles)

        self.goal_registry = GoalRegistry(self.catalogue)
        self.verifier = Verifier(self.catalogue)
        self.provider = MockModelProvider(self.pack_dir / "replay" / "model_faults.jsonl")
        self.harness = OperationalHarness(
            self.catalogue, self.goal_registry, self.provider, self.state_store
        )
        self.decision_engine = DecisionEngine(
            self.catalogue, self.goal_registry, self.verifier, self.provider
        )

        self.decisions: List[AgentDecision] = []
        self.published_actions: List[PublishedAction] = []
        self.latency_records: List[int] = []

    def run(self) -> Dict[str, Any]:
        """
        Merge and stream all events across the replay day in priority virtual time.
        Priority: Control Events (0) > Live Telemetry (1) > Triggers (2).
        """
        print("Building unified virtual timeline...")
        timeline: List[Tuple[datetime, int, str, Dict[str, Any]]] = []

        # 1. Ingest Control Events (Priority 0)
        control_path = self.pack_dir / "replay" / "control_events.jsonl"
        if control_path.exists():
            with open(control_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line:
                        ev = json.loads(line)
                        dt = parse_iso(ev["at"])
                        if dt:
                            timeline.append((dt, 0, "control", ev))

        # 2. Ingest Live Replay Events (Priority 1)
        live_path = self.pack_dir / "replay" / "live_events.jsonl"
        if live_path.exists():
            with open(live_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line:
                        ev = json.loads(line)
                        dt = parse_iso(ev["received_at"])
                        if dt:
                            timeline.append((dt, 1, "live", ev))

        # 3. Ingest Decision Triggers (Priority 2)
        triggers_path = self.pack_dir / "replay" / "triggers.jsonl"
        trigger_count = 0
        if triggers_path.exists():
            with open(triggers_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line:
                        ev = json.loads(line)
                        dt = parse_iso(ev.get("deliver_at") or ev.get("received_at"))
                        if dt:
                            timeline.append((dt, 2, "trigger", ev))
                            trigger_count += 1

        # Sort timeline by (datetime, priority)
        timeline.sort(key=lambda x: (x[0], x[1]))
        print(f"Streaming {len(timeline)} events ({trigger_count} triggers) in virtual time...")

        start_wall_time = time.time()

        for dt, priority, ev_kind, payload in timeline:
            # Advance harness virtual clock
            self.harness.tick(dt)

            if ev_kind == "control":
                self.harness.apply_control_event(payload, dt)

            elif ev_kind == "live":
                self.state_store.update_from_event(payload, is_live=True)

            elif ev_kind == "trigger":
                raw_trigger = TriggerEvent(**payload)
                user_id = raw_trigger.user_id

                # Update live state from the trigger's app_open event
                self.state_store.update_from_event(payload, is_live=True)
                try:
                    viewer_state = self.state_store.get_state(user_id)
                except TimeoutError:
                    # Circuit breaker: Fallback to local memory cache during remote data store degradation
                    viewer_state = self.state_store.states.get(user_id) or ViewerState(
                        user_id=user_id,
                        arm=self.state_store.arms.get(user_id, "agent"),  # type: ignore
                    )

                decision, action = self.decision_engine.process_trigger(
                    raw_trigger, viewer_state, dt
                )

                self.decisions.append(decision)
                self.latency_records.append(decision.decided_in_ms)

                if action:
                    self.published_actions.append(action)

        wall_duration = time.time() - start_wall_time
        print(f"Replay completed in {wall_duration:.2f}s wall time.")

        # Export artifacts
        self._export_artifacts(wall_duration)

        return {
            "triggers_processed": len(self.decisions),
            "actions_published": len(self.published_actions),
            "wall_duration_s": round(wall_duration, 2),
            "p50_latency_ms": round(statistics.median(self.latency_records), 2) if self.latency_records else 0,
            "p95_latency_ms": round(statistics.quantiles(self.latency_records, n=20)[18], 2) if len(self.latency_records) >= 20 else 0,
        }

    def _export_artifacts(self, wall_duration: float) -> None:
        """Write sample_run/decisions.jsonl, actions.jsonl, viewer_state/, and latency_report.json."""
        print("Exporting replay artifacts...")

        # 1. decisions.jsonl
        decisions_path = self.out_dir / "decisions.jsonl"
        with open(decisions_path, "w", encoding="utf-8") as f:
            for d in self.decisions:
                f.write(d.model_dump_json() + "\n")

        # 2. actions.jsonl
        actions_path = self.out_dir / "actions.jsonl"
        with open(actions_path, "w", encoding="utf-8") as f:
            for act in self.published_actions:
                # Omit None fields for clean simulator compatibility
                clean_dict = {k: v for k, v in act.model_dump().items() if v is not None}
                f.write(json.dumps(clean_dict, ensure_ascii=False) + "\n")

        # 3. Flush durable viewer states
        print("Flushing updated viewer states to disk...")
        self.state_store.save_all_states()

        # 4. Latency report
        p50 = round(statistics.median(self.latency_records), 2) if self.latency_records else 0.0
        p95 = round(statistics.quantiles(self.latency_records, n=20)[18], 2) if len(self.latency_records) >= 20 else p50
        p99 = round(statistics.quantiles(self.latency_records, n=100)[98], 2) if len(self.latency_records) >= 100 else p95
        max_lat = max(self.latency_records) if self.latency_records else 0
        min_lat = min(self.latency_records) if self.latency_records else 0
        mean_lat = round(statistics.mean(self.latency_records), 2) if self.latency_records else 0.0

        latency_report = {
            "total_decisions": len(self.latency_records),
            "wall_duration_seconds": round(wall_duration, 2),
            "latency_ms": {
                "min": min_lat,
                "mean": mean_lat,
                "p50": p50,
                "p95": p95,
                "p99": p99,
                "max": max_lat,
            },
            "sla_compliance": {
                "sub_2000ms_compliance_rate": round(sum(1 for x in self.latency_records if x <= 2000) / len(self.latency_records), 4) if self.latency_records else 1.0,
                "sub_60000ms_compliance_rate": round(sum(1 for x in self.latency_records if x <= 60000) / len(self.latency_records), 4) if self.latency_records else 1.0,
                "sla_breaches_count": sum(1 for x in self.latency_records if x > 60000),
            },
        }

        with open(self.out_dir / "latency_report.json", "w", encoding="utf-8") as f:
            json.dump(latency_report, f, indent=2)

        print(f"Artifacts exported to {self.out_dir}:")
        print(f"  - decisions.jsonl ({len(self.decisions)} decisions)")
        print(f"  - actions.jsonl ({len(self.published_actions)} published actions)")
        print(f"  - latency_report.json (p50: {p50}ms, p95: {p95}ms, p99: {p99}ms)")


if __name__ == "__main__":
    runner = ReplayRunner()
    summary = runner.run()
    print("Replay summary:", summary)
