"""Durable per-viewer state storage, conflict resolution, and fact provenance."""
import csv
import json
import os
import random
import time
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

from src.config import (
    DATA_DIR,
    REPLAY_DIR,
    SAMPLE_RUN_DIR,
    VIEWER_STATE_DIR,
    format_iso,
    get_ist_date,
    parse_iso,
)
from src.models import ActiveGoal, ViewerState


class StateStore:
    """
    Manages in-memory and durable on-disk state for all 5,000 users.
    Implements strict source precedence:
    Replay Live Events > Historical Events Telemetry > Profile Warehouse Snapshot.
    """

    def __init__(self, state_dir: Optional[Path] = None):
        self.state_dir = state_dir or VIEWER_STATE_DIR
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self.states: Dict[str, ViewerState] = {}
        self.arms: Dict[str, str] = {}
        self.catalogue_genre_map: Dict[str, List[str]] = {}
        self.catalogue_slug_map: Dict[str, str] = {}

        # Degradation simulation flags (for 13:10 UTC control event)
        self.simulate_degradation: bool = False
        self.degradation_latency_s: float = 8.0
        self.degradation_timeout_rate: float = 0.20

    def initialize_from_pack(
        self,
        pack_dir: Optional[Path] = None,
        catalogue_titles: Optional[Dict[str, Dict[str, Any]]] = None,
    ) -> None:
        """
        Bootstrap viewer states from replay/arms.csv, data/profiles_snapshot.csv,
        and data/events.jsonl.
        """
        base = pack_dir or DATA_DIR.parent

        # 1. Load arms
        arms_path = base / "replay" / "arms.csv"
        if arms_path.exists():
            with open(arms_path, "r", encoding="utf-8") as f:
                for row in csv.DictReader(f):
                    self.arms[row["user_id"]] = row["arm"]

        # Cache catalogue lookups if provided
        if catalogue_titles:
            for tid, tinfo in catalogue_titles.items():
                self.catalogue_genre_map[tid] = tinfo.get("genres", [])
                self.catalogue_slug_map[tid] = tinfo.get("slug", "")

        # 2. Ingest profiles snapshot with de-duplication (pick latest updated_at)
        profiles_path = base / "data" / "profiles_snapshot.csv"
        raw_profiles: Dict[str, Dict[str, str]] = {}
        if profiles_path.exists():
            with open(profiles_path, "r", encoding="utf-8") as f:
                for row in csv.DictReader(f):
                    uid = row["user_id"]
                    existing = raw_profiles.get(uid)
                    if existing is None or row["updated_at"] > existing["updated_at"]:
                        raw_profiles[uid] = row

        # Initialize ViewerState objects for all known users
        all_user_ids = set(self.arms.keys()) | set(raw_profiles.keys())
        for uid in all_user_ids:
            prof = raw_profiles.get(uid, {})
            arm = self.arms.get(uid, "agent")
            status = prof.get("subscription_status", "never")
            if status not in ("never", "trial_active", "active", "lapsed"):
                status = "never"

            state = ViewerState(
                user_id=uid,
                arm=arm,  # type: ignore
                signup_at=prof.get("signup_at") or None,
                subscription_status=status,  # type: ignore
                subscription_source="profile",
                preferred_dialect=prof.get("preferred_dialect") or None,
                preferred_language=prof.get("preferred_language") or None,
                notifications_opt_in=prof.get("notifications_opt_in") == "true",
                whatsapp_opt_in=prof.get("whatsapp_opt_in") == "true",
                platform=prof.get("platform") or None,
                updated_at=prof.get("updated_at") or "2026-09-30T00:00:00.000Z",
            )
            self.states[uid] = state

        # 3. Stream historical events from data/events.jsonl to populate factual history
        events_path = base / "data" / "events.jsonl"
        if events_path.exists():
            with open(events_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    event = json.loads(line)
                    self.update_from_event(event, is_live=False)

    def update_from_event(self, event: Dict[str, Any], is_live: bool = False) -> None:
        """
        Update durable viewer state from an incoming telemetry event.
        Precedence: is_live=True represents real-time live events (highest authority).
        """
        uid = event.get("user_id")
        if not uid:
            return

        state = self.states.get(uid)
        if not state:
            arm = self.arms.get(uid, "agent")
            state = ViewerState(
                user_id=uid,
                arm=arm,  # type: ignore
                updated_at=event.get("received_at", ""),
            )
            self.states[uid] = state

        ev_type = event.get("event")
        rec_at = event.get("received_at")
        dt_rec = parse_iso(rec_at)

        # Track first and last event timestamps
        if rec_at:
            if not state.first_event_at or rec_at < state.first_event_at:
                state.first_event_at = rec_at
            if not state.last_event_at or rec_at > state.last_event_at:
                state.last_event_at = rec_at

        state.updated_at = rec_at or state.updated_at

        # Session tracking
        if ev_type == "app_open":
            state.sessions_count += 1
            state.last_app_open = rec_at
            if dt_rec:
                ist_day_str = str(get_ist_date(dt_rec))
                if ist_day_str not in state.distinct_app_open_ist_days:
                    state.distinct_app_open_ist_days.append(ist_day_str)

        elif ev_type == "signup_completed":
            if not state.signup_at or is_live:
                state.signup_at = rec_at

        elif ev_type == "play_started":
            state.total_plays += 1
            state.last_play_at = rec_at
            tid = event.get("properties", {}).get("title_id")
            if tid:
                genres = self.catalogue_genre_map.get(tid, [])
                for g in genres:
                    state.genre_affinities[g] = state.genre_affinities.get(g, 0) + 1

        elif ev_type == "episode_completed":
            state.total_completions += 1
            props = event.get("properties", {})
            tid = props.get("title_id")
            eid = props.get("episode_id")
            slug = self.catalogue_slug_map.get(tid)
            if slug and eid:
                state.series_progress[slug] = eid

        elif ev_type == "purchase_completed":
            props = event.get("properties", {})
            is_trial = props.get("is_trial", False)
            if is_trial:
                state.subscription_status = "trial_active"
            else:
                state.subscription_status = "active"
            state.subscription_source = "telemetry_live" if is_live else "telemetry_history"

        elif ev_type == "subscription_renewed":
            state.subscription_status = "active"
            state.subscription_source = "telemetry_live" if is_live else "telemetry_history"

        elif ev_type == "subscription_lapsed":
            state.subscription_status = "lapsed"
            state.subscription_source = "telemetry_live" if is_live else "telemetry_history"

        elif ev_type == "notification_opt_out":
            channel = event.get("properties", {}).get("channel")
            if channel:
                if channel not in state.opted_out_channels:
                    state.opted_out_channels.append(channel)
                if channel == "push":
                    state.notifications_opt_in = False
                elif channel == "whatsapp":
                    state.whatsapp_opt_in = False

        elif ev_type == "app_dialect_changed":
            to_dialect = event.get("properties", {}).get("to")
            if to_dialect:
                state.preferred_dialect = to_dialect

    def get_state(self, user_id: str) -> ViewerState:
        """
        Retrieve state for a user.
        Simulates data store degradation (8s latency and 20% timeout) when enabled.
        """
        if self.simulate_degradation:
            # Simulate degraded read latency
            if random.random() < self.degradation_timeout_rate:
                raise TimeoutError("UserDataStore timeout (simulated degradation)")
            time.sleep(min(0.05, self.degradation_latency_s * 0.01))  # Scaled for fast replay

        if user_id not in self.states:
            arm = self.arms.get(user_id, "agent")
            self.states[user_id] = ViewerState(user_id=user_id, arm=arm)  # type: ignore
        return self.states[user_id]

    def save_state(self, user_id: str) -> None:
        """Persist individual viewer state to disk."""
        state = self.states.get(user_id)
        if not state:
            return
        out_path = self.state_dir / f"{user_id}.json"
        with open(out_path, "w", encoding="utf-8") as f:
            f.write(state.model_dump_json(indent=2))

    def save_all_states(self) -> None:
        """Flush all in-memory states to sample_run/viewer_state/."""
        self.state_dir.mkdir(parents=True, exist_ok=True)
        for uid in self.states:
            self.save_state(uid)

