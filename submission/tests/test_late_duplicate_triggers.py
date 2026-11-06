"""Test suite verifying handling of late offline-buffered triggers and duplicate deliveries."""
from datetime import datetime

import pytest

from src.catalog import Catalogue
from src.decision_engine import DecisionEngine
from src.goal_registry import GoalRegistry
from src.models import TriggerEvent, ViewerState
from src.providers import MockModelProvider
from src.verifier import Verifier


@pytest.fixture
def engine():
    cat = Catalogue()
    cat.load_from_pack()
    goals = GoalRegistry(cat)
    verifier = Verifier(cat)
    provider = MockModelProvider()
    return DecisionEngine(cat, goals, verifier, provider)


def test_offline_buffered_trigger_abstention(engine):
    """
    Triggers buffered offline on phones (lag > 600s) must update facts
    but abstain from publishing live home pages or immediate pushes.
    """
    state = ViewerState(
        user_id="U-TEST-01",
        arm="agent",
        subscription_status="never",
        preferred_dialect="d2",
    )

    # Trigger with 2 hours (7200s) of buffering delay
    trigger = TriggerEvent(
        event_id="trig-late-001",
        user_id="U-TEST-01",
        event="app_open",
        occurred_at="2026-10-01T08:00:00.000Z",
        sent_at="2026-10-01T10:00:00.000Z",
        received_at="2026-10-01T10:00:02.000Z",
        session_id="sess-late-001",
        app_dialect="d2",
        app_language="hin",
        properties={},
    )

    at = datetime.fromisoformat("2026-10-01T10:00:02+00:00")
    decision, action = engine.process_trigger(trigger, state, at)

    assert decision.status == "OFFLINE_BUFFERED_SYNC"
    assert decision.action == "NO_ACTION"
    assert action is None
    assert "offline-buffered" in decision.confidence_reason.lower()


def test_duplicate_trigger_idempotency(engine):
    """
    Duplicate triggers with identical event_id must return an idempotent
    decision without publishing duplicate actions to actions.jsonl.
    """
    state = ViewerState(
        user_id="U-TEST-02",
        arm="agent",
        subscription_status="never",
        preferred_dialect="d1",
    )

    trigger = TriggerEvent(
        event_id="trig-dupe-001",
        user_id="U-TEST-02",
        event="app_open",
        occurred_at="2026-10-01T09:00:00.000Z",
        sent_at="2026-10-01T09:00:00.000Z",
        received_at="2026-10-01T09:00:01.000Z",
        session_id="sess-dupe-001",
        app_dialect="d1",
        app_language="hin",
        properties={},
    )

    at = datetime.fromisoformat("2026-10-01T09:00:01+00:00")

    # First delivery: normal processing
    dec1, act1 = engine.process_trigger(trigger, state, at)
    assert dec1.status == "PUBLISHED"
    assert act1 is not None

    # Second delivery with exact same event_id
    dec2, act2 = engine.process_trigger(trigger, state, at)
    assert dec2.status == "DUPLICATE_IDEMPOTENT"
    assert dec2.action == "NO_ACTION"
    assert act2 is None  # Zero duplicate action published

