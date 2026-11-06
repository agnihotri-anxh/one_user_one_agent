"""Candidate goals specification, eligibility evaluation, and dynamic rule updating."""
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

from src.catalog import Catalogue
from src.config import parse_iso
from src.models import ActiveGoal, ViewerState

# Defective goals that cannot be selected by any compliant agent
BLACKLISTED_GOAL_IDS = {
    "G10": "Unmeasurable success condition: event is null.",
    "G11": "Nonexistent telemetry signal: tv_app_open does not exist in event stream.",
}


class GoalDefinition:
    """Specification of a candidate goal with eligibility and success rules."""

    def __init__(
        self,
        goal_id: str,
        name: str,
        description: str,
        window_hours: int,
        success_event: Optional[str],
        success_condition: str,
        eligibility_text: str,
    ):
        self.goal_id = goal_id
        self.name = name
        self.description = description
        self.window_hours = window_hours
        self.success_event = success_event
        self.success_condition = success_condition
        self.eligibility_text = eligibility_text


class GoalRegistry:
    """
    Registry of goals, factual eligibility evaluators, and dynamic rule management.
    """

    def __init__(self, catalogue: Optional[Catalogue] = None):
        self.catalogue = catalogue or Catalogue()
        self.goals: Dict[str, GoalDefinition] = {}
        self._init_default_goals()

    def _init_default_goals(self) -> None:
        """Initialize standard 12 goals from config/goals.json."""
        defs = [
            ("G01", "first_play_24h", "A new user starts any episode within 24 hours.", 24, "play_started", "any title", "Signed up in last 7 days and never started a play."),
            ("G02", "first_full_episode_3d", "The user finishes a whole episode for first time.", 72, "episode_completed", "any episode", "Has never completed an episode."),
            ("G03", "second_day_return_2d", "A new user comes back on a second day.", 48, "app_open", "on a later IST calendar day than goal start", "Signed up in last 2 days."),
            ("G04", "trial_to_paid_7d", "A user on a trial moves to a paid plan.", 168, "purchase_completed", "is_trial = false", "Subscription status is trial_active."),
            ("G05", "first_paid_7d", "A user who has never paid buys a first paid plan.", 168, "purchase_completed", "is_trial = false", "Has never had a paid plan (status = never)."),
            ("G06", "reactivate_lapsed_14d", "A recently lapsed subscriber buys again.", 336, "purchase_completed", "any paid plan", "Subscription status is lapsed."),
            ("G07", "resume_series_3d", "The user continues a series left unfinished.", 72, "play_started", "same content_slug as unfinished series", "Started a show/micro-drama, has unwatched episodes, not played for >=3 days."),
            ("G08", "try_new_release_7d", "A subscriber plays a recent release.", 168, "play_started", "title released in 30 days before goal start", "Active subscriber."),
            ("G09", "weekly_habit_14d", "A subscriber who rarely watches builds a habit.", 336, "play_started", "on 3 distinct IST days", "Active subscriber with plays on at most 1 day in last 14 days."),
            ("G10", "meaningful_engagement_7d", "The user engages meaningfully.", 168, None, "engages meaningfully", "Any user (DEFECTIVE)."),
            ("G11", "tv_activation_14d", "Subscriber starts watching on TV app.", 336, "tv_app_open", "any", "Active subscriber (DEFECTIVE)."),
            ("G12", "return_after_absence_7d", "User who stopped visiting plays again.", 168, "play_started", "any title", "No app_open in 14 days before trigger."),
        ]
        for gid, name, desc, hrs, ev, cond, elig in defs:
            self.goals[gid] = GoalDefinition(gid, name, desc, hrs, ev, cond, elig)

    def update_goal_rule(self, goal_id: str, new_success: Dict[str, Any]) -> None:
        """
        Dynamically update success rule in memory (handling G03 correction at 08:30 UTC).
        Applies to open goals without whole-DB reprocessing.
        """
        if goal_id in self.goals:
            g = self.goals[goal_id]
            g.success_event = new_success.get("event", g.success_event)
            g.success_condition = new_success.get("condition", g.success_condition)

    def evaluate_eligibility(
        self,
        state: ViewerState,
        at: datetime,
    ) -> List[Tuple[GoalDefinition, float, str]]:
        """
        Evaluate which candidate goals the viewer is factually eligible for.
        Returns a list of (GoalDefinition, priority_score, rationale).
        """
        eligible: List[Tuple[GoalDefinition, float, str]] = []

        signup_dt = parse_iso(state.signup_at)
        days_since_signup = (at - signup_dt).total_seconds() / 86400.0 if signup_dt else 999.0
        last_play_dt = parse_iso(state.last_play_at)
        days_since_play = (at - last_play_dt).total_seconds() / 86400.0 if last_play_dt else 999.0
        status = state.subscription_status

        # G01: first_play_24h
        if days_since_signup <= 7.0 and state.total_plays == 0:
            eligible.append((self.goals["G01"], 0.90, "New user (<7d) with zero plays"))

        # G02: first_full_episode_3d
        if state.total_completions == 0:
            eligible.append((self.goals["G02"], 0.85, "Viewer has never completed an episode"))

        # G03: second_day_return_2d
        if days_since_signup <= 2.0:
            eligible.append((self.goals["G03"], 0.80, "Brand-new signup within last 48 hours"))

        # G04: trial_to_paid_7d
        if status == "trial_active":
            eligible.append((self.goals["G04"], 0.95, "Subscriber is on an active trial needing paid conversion"))

        # G05: first_paid_7d
        if status == "never" and state.total_plays >= 1:
            eligible.append((self.goals["G05"], 0.75, "Viewer has watched content but never subscribed"))

        # G06: reactivate_lapsed_14d
        if status == "lapsed":
            eligible.append((self.goals["G06"], 0.88, "Recently lapsed subscriber"))

        # G07: resume_series_3d
        # Check series progress against catalog episode count and play recency
        for slug, last_eid in state.series_progress.items():
            total_eps = self.catalogue.get_total_episodes_for_slug(slug)
            curr_idx = self.catalogue.get_episode_index(slug, last_eid)
            if curr_idx >= 0 and (curr_idx + 1) < total_eps and days_since_play >= 3.0:
                eligible.append((
                    self.goals["G07"],
                    0.92,
                    f"Left series {slug} at ep {curr_idx+1}/{total_eps} and inactive for {days_since_play:.1f} days",
                ))
                break

        # G08: try_new_release_7d
        if status == "active":
            eligible.append((self.goals["G08"], 0.70, "Active subscriber suitable for recent release exploration"))

        # G09: weekly_habit_14d
        if status == "active" and len(state.distinct_app_open_ist_days) <= 2:
            eligible.append((self.goals["G09"], 0.82, "Active subscriber with low frequency in last 14 days"))

        # G12: return_after_absence_7d
        if days_since_play >= 14.0 and state.total_plays > 0:
            eligible.append((self.goals["G12"], 0.78, "Returning after >14 days of viewing absence"))

        # Filter out blacklisted goals
        eligible = [g for g in eligible if g[0].goal_id not in BLACKLISTED_GOAL_IDS]

        # Sort by priority score descending
        eligible.sort(key=lambda x: x[1], reverse=True)
        return eligible

    def create_active_goal(self, goal_def: GoalDefinition, started_at: datetime) -> ActiveGoal:
        """Instantiate a new ActiveGoal with calculated deadline."""
        deadline = started_at + timedelta(hours=goal_def.window_hours)
        from src.config import format_iso
        return ActiveGoal(
            id=goal_def.goal_id,
            name=goal_def.name,
            started_at=format_iso(started_at) or "",
            deadline=format_iso(deadline) or "",
            success_event=goal_def.success_event or "play_started",
            success_condition=goal_def.success_condition,
            status="IN_FLIGHT",
        )

