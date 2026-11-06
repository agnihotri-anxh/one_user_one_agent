"""Attributable goal outcome evaluator with exposure precedence and dynamic rule handling."""
import json
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from src.catalog import Catalogue
from src.config import (
    DATA_DIR,
    SAMPLE_RUN_DIR,
    format_iso,
    get_ist_date,
    parse_iso,
)
from src.goal_registry import GoalRegistry
from src.models import OutcomeJudgment, ViewerState
from src.state_store import StateStore


class OutcomeJudge:
    """
    Evaluates in-flight viewer goals against 14-day outcome telemetry:
    - Enforces causal exposure precedence (home page exposure or message click required)
    - Applies dynamic rule corrections (evaluates open G03 goals using play_started)
    - Outputs auditable judgments to sample_run/outcomes.jsonl
    - Updates durable viewer state in sample_run/viewer_state/<user_id>.json
    """

    def __init__(
        self,
        pack_dir: Optional[Path] = None,
        run_dir: Optional[Path] = None,
    ):
        self.pack_dir = pack_dir or DATA_DIR.parent
        self.run_dir = run_dir or SAMPLE_RUN_DIR
        self.catalogue = Catalogue()
        self.catalogue.load_from_pack(self.pack_dir)
        self.goal_registry = GoalRegistry(self.catalogue)
        self.state_store = StateStore(self.run_dir / "viewer_state")

        # Load arms
        self.arms: Dict[str, str] = {}
        arms_path = self.pack_dir / "replay" / "arms.csv"
        if arms_path.exists():
            import csv
            with open(arms_path, "r", encoding="utf-8") as f:
                for r in csv.DictReader(f):
                    self.arms[r["user_id"]] = r["arm"]

    def judge_outcomes(
        self,
        outcome_events_path: Optional[Path] = None,
    ) -> List[OutcomeJudgment]:
        """
        Evaluate all users who had decisions and active goals against outcome events.
        """
        events_file = outcome_events_path or (self.run_dir / "sim" / "outcome_events.jsonl")
        if not events_file.exists():
            raise FileNotFoundError(f"Outcome events not found at {events_file}")

        print("Indexing simulated outcome events per user...")
        user_events: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
        with open(events_file, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    ev = json.loads(line)
                    user_events[ev["user_id"]].append(ev)

        # Sort each user's events chronologically
        for uid in user_events:
            user_events[uid].sort(key=lambda x: x["received_at"])

        # Load latest decisions
        decisions_path = self.run_dir / "decisions.jsonl"
        user_decisions: Dict[str, Dict[str, Any]] = {}
        if decisions_path.exists():
            with open(decisions_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line:
                        d = json.loads(line)
                        if d.get("goal"):
                            user_decisions[d["viewer_id"]] = d

        judgments: List[OutcomeJudgment] = []
        judged_at_str = format_iso(datetime.now()) or ""

        print(f"Evaluating goals for {len(user_decisions)} viewers with assigned goals...")

        for uid, dec in user_decisions.items():
            goal_info = dec["goal"]
            goal_id_name = goal_info["id"]  # e.g. "first_full_episode_3d" or "G02"
            deadline_dt = parse_iso(goal_info["deadline"])
            dec_dt = parse_iso(dec["trigger"]["received_at"])
            events = user_events.get(uid, [])

            # Check exposure precedence: did user see a personalized home page or click a message?
            exposure_time: Optional[datetime] = None
            for ev in events:
                ev_dt = parse_iso(ev["received_at"])
                if ev["event"] == "home_page_shown" and ev.get("properties", {}).get("personalised"):
                    exposure_time = ev_dt
                    break
                elif ev["event"] == "message_clicked":
                    exposure_time = ev_dt
                    break

            # Map goal name back to goal definition
            goal_def = None
            for g in self.goal_registry.goals.values():
                if g.name == goal_id_name or g.goal_id == goal_id_name:
                    goal_def = g
                    break

            if not goal_def:
                continue

            # Evaluate success criteria within the deadline window
            succeeded = False
            organic_unattributed = False
            success_ev_id: Optional[str] = None
            success_ev_type: Optional[str] = None
            success_ev_time: Optional[str] = None

            for ev in events:
                ev_dt = parse_iso(ev["received_at"])
                if not ev_dt or (deadline_dt and ev_dt > deadline_dt):
                    continue
                if dec_dt and ev_dt < dec_dt:
                    continue  # Ignore events before decision

                ev_type = ev["event"]
                props = ev.get("properties", {})

                # Check G01 (first_play_24h)
                if goal_def.goal_id == "G01" and ev_type == "play_started":
                    succeeded = True

                # Check G02 (first_full_episode_3d)
                elif goal_def.goal_id == "G02" and ev_type == "episode_completed":
                    succeeded = True

                # Check G03 (second_day_return_2d) -> Evaluated with corrected rule (play_started on later IST day)
                elif goal_def.goal_id == "G03":
                    start_ist = get_ist_date(dec_dt) if dec_dt else None
                    ev_ist = get_ist_date(ev_dt)
                    if ev_type == "play_started" and start_ist and ev_ist > start_ist:
                        succeeded = True

                # Check G04 (trial_to_paid_7d) / G05 (first_paid_7d) / G06 (reactivate_lapsed)
                elif goal_def.goal_id in ("G04", "G05", "G06") and ev_type == "purchase_completed":
                    if not props.get("is_trial", False):
                        succeeded = True

                # Check G07 (resume_series_3d)
                elif goal_def.goal_id == "G07" and ev_type == "play_started":
                    succeeded = True

                # Check G08 (try_new_release_7d)
                elif goal_def.goal_id == "G08" and ev_type == "play_started":
                    tid = props.get("title_id")
                    if tid and self.catalogue.titles.get(tid):
                        succeeded = True

                # Check G09 (weekly_habit_14d) & G12 (return_after_absence_7d)
                elif goal_def.goal_id in ("G09", "G12") and ev_type == "play_started":
                    succeeded = True

                if succeeded:
                    success_ev_id = ev.get("event_id")
                    success_ev_type = ev_type
                    success_ev_time = ev.get("received_at")

                    # Check causal exposure: if user converted without exposure, flag as organic
                    if exposure_time is None or ev_dt < exposure_time:
                        organic_unattributed = True
                    break

            # Assign final outcome status
            if succeeded:
                if organic_unattributed:
                    status = "ORGANIC_UNATTRIBUTED"
                    reason = "Goal success criteria met, but occurred organically without prior agent exposure"
                else:
                    status = "SUCCEEDED"
                    reason = f"Goal criteria successfully achieved following agent exposure ({success_ev_type})"
            else:
                status = "FAILED"
                reason = "Goal window deadline expired without observed success criteria"

            judgment = OutcomeJudgment(
                decision_id=dec["decision_id"],
                user_id=uid,
                goal_id=goal_def.goal_id,
                goal_name=goal_def.name,
                goal_started_at=dec["trigger"]["received_at"],
                deadline=goal_info["deadline"],
                status=status,
                attributed_to_action_id=dec.get("action_id"),
                evidence_event_id=success_ev_id,
                evidence_event_type=success_ev_type,
                evidence_timestamp=success_ev_time,
                judged_at=judged_at_str,
                reason=reason,
            )
            judgments.append(judgment)

            # Update durable state in viewer memory
            viewer_file = self.run_dir / "viewer_state" / f"{uid}.json"
            if viewer_file.exists():
                try:
                    with open(viewer_file, "r", encoding="utf-8") as vf:
                        vdata = json.load(vf)
                    vdata["goal_history"] = vdata.get("goal_history", [])
                    vdata["goal_history"].append(judgment.model_dump())
                    if vdata.get("active_goal"):
                        vdata["active_goal"]["status"] = status
                    vdata["learned_insights"] = vdata.get("learned_insights", [])
                    vdata["learned_insights"].append(
                        f"Goal {goal_def.name} judged as {status} on {judged_at_str}: {reason}"
                    )
                    with open(viewer_file, "w", encoding="utf-8") as vf:
                        json.dump(vdata, vf, indent=2)
                except Exception:
                    pass

        # Write sample_run/outcomes.jsonl
        outcomes_path = self.run_dir / "outcomes.jsonl"
        with open(outcomes_path, "w", encoding="utf-8") as f:
            for j in judgments:
                f.write(j.model_dump_json() + "\n")

        print(f"Judged {len(judgments)} goals -> {outcomes_path}")
        succ_cnt = sum(1 for j in judgments if j.status == "SUCCEEDED")
        fail_cnt = sum(1 for j in judgments if j.status == "FAILED")
        org_cnt = sum(1 for j in judgments if j.status == "ORGANIC_UNATTRIBUTED")
        print(f"Outcomes summary: {succ_cnt} Succeeded, {fail_cnt} Failed, {org_cnt} Organic/Unattributed")

        return judgments


if __name__ == "__main__":
    judge = OutcomeJudge()
    judge.judge_outcomes()

