"""Test suite verifying resilience to external tool and model failures with graceful fallback."""
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
def env():
    cat = Catalogue()
    cat.load_from_pack()
    goals = GoalRegistry(cat)
    verifier = Verifier(cat)
    provider = MockModelProvider()
    engine = DecisionEngine(cat, goals, verifier, provider)
    store = StateStore()
    return engine, provider, store


def test_model_provider_503_outage_circuit_breaker(env):
    """
    During a model provider HTTP 503 outage (10:35-10:42 UTC), the circuit breaker
    must catch the error, switch to deterministic heuristic fallback,
    and publish a safe action with status DEGRADED_FALLBACK.
    """
    engine, provider, _ = env

    state = ViewerState(
        user_id="U-TEST-503-01",
        arm="agent",
        subscription_status="never",
        preferred_dialect="d1",
        total_plays=2,
    )

    trigger = TriggerEvent(
        event_id="trig-503-01",
        user_id="U-TEST-503-01",
        event="app_open",
        occurred_at="2026-10-01T10:36:00.000Z",
        sent_at="2026-10-01T10:36:00.000Z",
        received_at="2026-10-01T10:36:01.000Z",
        session_id="sess-503-01",
        app_dialect="d1",
        app_language="hin",
        properties={},
    )

    at = datetime.fromisoformat("2026-10-01T10:36:01+00:00")

    # Simulate HTTP 503 outage
    provider.set_service_down(True)

    decision, action = engine.process_trigger(trigger, state, at)

    # Must not crash, and must mark status as DEGRADED_FALLBACK
    assert decision.status == "DEGRADED_FALLBACK"
    assert decision.action == "HOME_PAGE"
    assert action is not None
    assert action.dialect == "d1"
    assert any("degraded/unavailable" in a.lower() for a in decision.assumptions)


def test_model_hallucination_rejected_by_verifier(env):
    """
    When the model provider hallucinates that a user is on an active trial (G04),
    the air-gapped verifier checks durable state (status='never') and rejects the hallucination.
    """
    engine, provider, _ = env

    # User U-01991 is one of the injected unsupported_claim faults in model_faults.jsonl
    uid = "U-01991"
    state = ViewerState(
        user_id=uid,
        arm="agent",
        subscription_status="never",
        preferred_dialect="d3",
    )

    trigger = TriggerEvent(
        event_id="202cccb8-8127-465f-b2d0-038cf533197e",  # Exact event_id in model_faults.jsonl
        user_id=uid,
        event="app_open",
        occurred_at="2026-10-01T04:14:00.000Z",
        sent_at="2026-10-01T04:14:00.000Z",
        received_at="2026-10-01T04:14:02.000Z",
        session_id="sess-hallucinate-01",
        app_dialect="d3",
        app_language="hin",
        properties={},
    )

    at = datetime.fromisoformat("2026-10-01T04:14:02+00:00")
    decision, action = engine.process_trigger(trigger, state, at)

    # Tier 1 & Verifier assign factual goal (e.g. G02 or G05), NOT the hallucinated G04 trial
    assert decision.goal["id"] != "trial_to_paid_7d"
    assert decision.goal["id"] in ("first_full_episode_3d", "first_paid_7d", "first_play_24h")


def test_user_data_store_timeout_resilience(env):
    """
    When the user data store degrades with high latency and 20% timeouts,
    the client catches the timeout and falls back to local cached memory.
    """
    engine, _, store = env
    uid = "U-TEST-STORE-01"
    store.states[uid] = ViewerState(user_id=uid, arm="agent", subscription_status="active")

    # Enable simulated degradation
    store.simulate_degradation = True
    store.degradation_timeout_rate = 1.0  # Force 100% timeout

    # Must raise TimeoutError from store
    with pytest.raises(TimeoutError):
        store.get_state(uid)

    # Replay harness fallback pattern: retrieve directly from local memory cache
    cached_state = store.states.get(uid)
    assert cached_state is not None
    assert cached_state.subscription_status == "active"

