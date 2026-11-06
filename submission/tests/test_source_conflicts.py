"""Test suite verifying resolution of conflicting sources and fact precedence."""
from datetime import datetime

import pytest

from src.catalog import Catalogue
from src.decision_engine import DecisionEngine
from src.goal_registry import GoalRegistry
from src.models import TriggerEvent, ViewerState
from src.providers import MockModelProvider
from src.state_store import StateStore
from src.verifier import Verifier


@pytest.fixture
def components():
    cat = Catalogue()
    cat.load_from_pack()
    goals = GoalRegistry(cat)
    verifier = Verifier(cat)
    provider = MockModelProvider()
    engine = DecisionEngine(cat, goals, verifier, provider)
    store = StateStore()
    return engine, store, goals


def test_dialect_source_conflict_resolution(components):
    """
    When app settings, warehouse profile, and campaign link specify conflicting dialects:
    - The home page strictly personalizes to the active client app_setting (d2)
    - Dialect conflicts are explicitly recorded in dialect.conflicts
    """
    engine, store, _ = components

    state = ViewerState(
        user_id="U-TEST-CONFLICT-01",
        arm="agent",
        subscription_status="never",
        preferred_dialect="d1",  # Profile says d1
    )

    # Trigger arrives with app_dialect = d2 and deeplink = d5
    trigger = TriggerEvent(
        event_id="trig-conflict-01",
        user_id="U-TEST-CONFLICT-01",
        event="app_open",
        occurred_at="2026-10-01T11:00:00.000Z",
        sent_at="2026-10-01T11:00:00.000Z",
        received_at="2026-10-01T11:00:01.000Z",
        session_id="sess-conflict-01",
        app_dialect="d2",
        app_language="hin",
        properties={"deeplink": "ott://c/cmp001/d5/title/T0101"},
    )

    at = datetime.fromisoformat("2026-10-01T11:00:01+00:00")
    decision, action = engine.process_trigger(trigger, state, at)

    # Verifies that client dialect d2 is used
    assert decision.dialect.used == "d2"
    assert decision.dialect.source == "app_setting"
    # Verifies both conflicting sources are documented in the decision record
    assert "profile:d1" in decision.dialect.conflicts
    assert "deeplink:d5" in decision.dialect.conflicts
    assert action is not None
    assert action.dialect == "d2"


def test_subscription_status_conflict_precedence(components):
    """
    When a stale profile snapshot says 'never' paid, but a fresh telemetry
    purchase event arrives, live telemetry must override stale warehouse data.
    """
    engine, store, goals = components

    uid = "U-TEST-PURCHASE-01"
    # State initially hydrated from stale warehouse snapshot
    state = ViewerState(
        user_id=uid,
        arm="agent",
        subscription_status="never",
        subscription_source="profile",
        preferred_dialect="d2",
        total_plays=5,
    )
    store.states[uid] = state

    # Verify that before purchase, user is eligible for G05 (first_paid_7d)
    at_morning = datetime.fromisoformat("2026-10-01T06:00:00+00:00")
    eligible_before = [g[0].goal_id for g in goals.evaluate_eligibility(state, at_morning)]
    assert "G05" in eligible_before

    # Fresh purchase event arrives in live stream
    purchase_event = {
        "event_id": "ev-purchase-999",
        "user_id": uid,
        "event": "purchase_completed",
        "received_at": "2026-10-01T09:30:00.000Z",
        "occurred_at": "2026-10-01T09:30:00.000Z",
        "properties": {"plan_id": "P_MONTH", "price_inr": 149, "is_trial": False},
    }
    store.update_from_event(purchase_event, is_live=True)

    # Verify state was updated by live event precedence
    updated_state = store.get_state(uid)
    assert updated_state.subscription_status == "active"
    assert updated_state.subscription_source == "telemetry_live"

    # G05 must now be disqualified, and G08 (try_new_release_7d) eligible
    at_afternoon = datetime.fromisoformat("2026-10-01T10:00:00+00:00")
    eligible_after = [g[0].goal_id for g in goals.evaluate_eligibility(updated_state, at_afternoon)]
    assert "G05" not in eligible_after
    assert "G08" in eligible_after

