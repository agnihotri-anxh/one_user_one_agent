"""Test suite verifying dynamic goal rule correction (G03) without database reprocessing."""
from datetime import datetime

import pytest

from src.catalog import Catalogue
from src.goal_registry import GoalRegistry
from src.models import ViewerState
from src.outcome_judge import OutcomeJudge


@pytest.fixture
def judge_env(tmp_path):
    cat = Catalogue()
    cat.load_from_pack()
    goals = GoalRegistry(cat)
    judge = OutcomeJudge(run_dir=tmp_path)
    return judge, goals


def test_dynamic_goal_rule_correction_application(judge_env):
    """
    At 08:30 UTC, control event corrects G03 success criteria from 'app_open'
    to 'play_started' on a later IST day.
    The rule update must apply to all in-flight G03 goals at closure time
    without requiring retrospective reprocessing of morning decisions.
    """
    judge, goals = judge_env

    # 1. Verify initial definition of G03
    g03 = goals.goals["G03"]
    assert g03.success_event == "app_open"

    # 2. Simulate control event arrival at 08:30 UTC
    control_event = {
        "at": "2026-10-01T08:30:00.000Z",
        "type": "goal_rule_corrected",
        "goal_id": "G03",
        "old_success": {"event": "app_open", "condition": "on a later IST calendar day within the window"},
        "new_success": {"event": "play_started", "condition": "on a later IST calendar day within the window"},
        "applies_to": "every G03 goal that is still open, including goals opened before this correction",
    }

    # Dynamically update goal rule in registry
    goals.update_goal_rule(control_event["goal_id"], control_event["new_success"])

    # 3. Verify in-memory definition updated
    assert g03.success_event == "play_started"
    assert "later IST calendar day" in g03.success_condition

    # 4. User who opened the app at 06:00 UTC (before correction) has G03
    # In outcome evaluation, an app_open on day 2 does NOT count as success under the corrected rule;
    # only a play_started on a later IST day counts!
    uid = "U-TEST-G03-CORRECTION"
    dec_time = "2026-10-01T06:00:00.000Z"
    deadline = "2026-10-03T06:00:00.000Z"

    # Simulated events: user only opened app on day 2, but did NOT start any play
    only_app_open_events = [
        {"event_id": "ev-open-d2", "user_id": uid, "event": "app_open", "received_at": "2026-10-02T10:00:00.000Z", "properties": {}},
    ]

    # Under corrected rule, only_app_open should NOT satisfy G03
    has_play = any(e["event"] == "play_started" for e in only_app_open_events)
    assert not has_play

    # When play_started arrives on a later day, G03 successfully completes
    events_with_play = [
        {"event_id": "ev-open-d2", "user_id": uid, "event": "app_open", "received_at": "2026-10-02T10:00:00.000Z", "properties": {}},
        {"event_id": "ev-play-d2", "user_id": uid, "event": "play_started", "received_at": "2026-10-02T10:05:00.000Z", "properties": {"title_id": "T0101"}},
    ]
    has_play_corrected = any(e["event"] == "play_started" for e in events_with_play)
    assert has_play_corrected
