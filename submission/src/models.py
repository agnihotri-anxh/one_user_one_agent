"""Pydantic domain models for telemetry, decisions, actions, viewer memory, and outcomes."""
from typing import Any, Dict, List, Literal, Optional, Union
from pydantic import BaseModel, Field


class TriggerEvent(BaseModel):
    """Raw incoming trigger event from telemetry stream."""
    event_id: str
    user_id: str
    event: str
    occurred_at: str
    sent_at: str
    received_at: str
    session_id: str
    app_dialect: Optional[str] = None
    app_language: Optional[str] = None
    platform: Optional[str] = None
    app_version: Optional[str] = None
    properties: Dict[str, Any] = Field(default_factory=dict)
    deliver_at: Optional[str] = None


class ActiveGoal(BaseModel):
    """Active goal pursued by the agent for a specific viewer."""
    id: str  # Goal ID (e.g. G02)
    name: str  # e.g. first_full_episode_3d
    started_at: str  # ISO-8601 UTC
    deadline: str  # ISO-8601 UTC
    success_event: str  # e.g. episode_completed
    success_condition: str  # e.g. any episode
    status: Literal["IN_FLIGHT", "SUCCEEDED", "FAILED", "SUPERSEDED"] = "IN_FLIGHT"


class DialectInfo(BaseModel):
    """Dialect metadata, source provenance, and detected conflicts."""
    used: Optional[str] = None
    source: str = "app_setting"  # app_setting | profile | fallback | none
    conflicts: List[str] = Field(default_factory=list)


class DecisionChecks(BaseModel):
    """Deterministic policy and guardrail checks evaluation."""
    passed: List[str] = Field(default_factory=list)
    failed: List[str] = Field(default_factory=list)


class AgentDecision(BaseModel):
    """Standardized decision output conforming to Section 4 of the candidate brief."""
    decision_id: str
    viewer_id: str
    trigger: Dict[str, Any]  # {"event": "app_open", "received_at": "...Z", "event_age_s": float}
    goal: Optional[Dict[str, str]] = None  # {"id": "...", "deadline": "...Z"}
    action: Literal["HOME_PAGE", "PUSH", "WHATSAPP", "IN_APP_MESSAGE", "NO_ACTION"]
    dialect: DialectInfo = Field(default_factory=DialectInfo)
    content: List[str] = Field(default_factory=list)  # ["title:T0412", ...]
    confidence: float = 0.5
    confidence_reason: str = "Standard baseline heuristic"
    evidence: List[str] = Field(default_factory=list)  # ["event:E88123", "catalogue:T0412", ...]
    assumptions: List[str] = Field(default_factory=list)
    checks: DecisionChecks = Field(default_factory=DecisionChecks)
    decided_in_ms: int = 0
    status: Literal[
        "PUBLISHED",
        "ABSTAINED",
        "HOLDOUT_CONTROL",
        "OFFLINE_BUFFERED_SYNC",
        "DUPLICATE_IDEMPOTENT",
        "DEGRADED_FALLBACK",
        "ERROR",
    ] = "PUBLISHED"


class HomeRow(BaseModel):
    """Row specification for personalized home page."""
    row_type: Literal[
        "next_episode",
        "because_you_watched",
        "popular_in_dialect",
        "new_releases",
        "genre",
    ]
    title_ids: List[str] = Field(min_length=3, max_length=10)


class PublishedAction(BaseModel):
    """
    Physical action published for consumption by simulate_outcomes.py.
    Written strictly to sample_run/actions.jsonl (NO_ACTION is never written).
    """
    action_id: str
    decision_id: str
    user_id: str
    trigger_event_id: str
    type: Literal["home_page", "push", "whatsapp", "in_app_message"]
    published_at: str
    dialect: Optional[str] = None
    hero_title_id: Optional[str] = None
    rows: Optional[List[Dict[str, Any]]] = None
    send_at: Optional[str] = None
    title_id: Optional[str] = None
    text: Optional[Dict[str, str]] = None
    deeplink: Optional[str] = None
    template_id: Optional[str] = None
    variables: Optional[Dict[str, str]] = None


class ViewerState(BaseModel):
    """Durable per-viewer state file stored in sample_run/viewer_state/<user_id>.json."""
    user_id: str
    arm: Literal["agent", "holdout"] = "agent"
    signup_at: Optional[str] = None
    subscription_status: Literal["never", "trial_active", "active", "lapsed"] = "never"
    subscription_source: str = "profile"
    preferred_dialect: Optional[str] = None
    preferred_language: Optional[str] = None
    notifications_opt_in: bool = False
    whatsapp_opt_in: bool = False
    opted_out_channels: List[str] = Field(default_factory=list)
    platform: Optional[str] = None

    # Telemetry metrics
    first_event_at: Optional[str] = None
    last_event_at: Optional[str] = None
    last_app_open: Optional[str] = None
    sessions_count: int = 0
    distinct_app_open_ist_days: List[str] = Field(default_factory=list)
    total_plays: int = 0
    total_completions: int = 0
    genre_affinities: Dict[str, int] = Field(default_factory=dict)
    series_progress: Dict[str, str] = Field(default_factory=dict)  # content_slug -> episode_id
    last_play_at: Optional[str] = None

    # Goal & intervention history
    active_goal: Optional[ActiveGoal] = None
    goal_history: List[Dict[str, Any]] = Field(default_factory=list)
    messages_sent_ist_days: Dict[str, int] = Field(default_factory=dict)
    last_home_page_published_at: Optional[str] = None
    last_home_page_dialect: Optional[str] = None
    last_action_id: Optional[str] = None

    # Deduplication & audit
    processed_event_ids: List[str] = Field(default_factory=list)
    decisions_count: int = 0
    learned_insights: List[str] = Field(default_factory=list)
    updated_at: str = ""


class OutcomeJudgment(BaseModel):
    """Result of closing a goal after its deadline passes or outcome events arrive."""
    decision_id: str
    user_id: str
    goal_id: str
    goal_name: str
    goal_started_at: str
    deadline: str
    status: Literal["SUCCEEDED", "FAILED", "INCONCLUSIVE", "ORGANIC_UNATTRIBUTED"]
    attributed_to_action_id: Optional[str] = None
    evidence_event_id: Optional[str] = None
    evidence_event_type: Optional[str] = None
    evidence_timestamp: Optional[str] = None
    judged_at: str
    reason: str
