"""Configuration, constants, policy definitions, and timezone utilities."""
import json
import os
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

# Root and directory paths
ROOT_DIR = Path(os.environ.get("PROJECT_ROOT", Path(__file__).resolve().parent.parent))
DATA_DIR = ROOT_DIR / "data"
CONFIG_DIR = ROOT_DIR / "config"
REPLAY_DIR = ROOT_DIR / "replay"
PILOT_DIR = ROOT_DIR / "pilot"
SIMULATOR_DIR = ROOT_DIR / "simulator"
SAMPLE_RUN_DIR = ROOT_DIR / "sample_run"
VIEWER_STATE_DIR = SAMPLE_RUN_DIR / "viewer_state"
SIM_DIR = SAMPLE_RUN_DIR / "sim"

# Timezones
UTC = timezone.utc
IST = timezone(timedelta(hours=5, minutes=30))

# Operational constraints
OFFLINE_LAG_THRESHOLD_SECONDS = 600.0  # 10 minutes; triggers older than this are offline-buffered
PAGE_TTL_MINUTES = 120
PAGE_TTL = timedelta(minutes=PAGE_TTL_MINUTES)
TARGET_LATENCY_MS = 2000  # Sub-2s target to beat the 3-40s simulate_outcomes home view window
MAX_ALLOWED_LATENCY_MS = 60000  # 60s hard budget from assignment brief
MAX_MODEL_CALLS = 8
MAX_TOOL_CALLS = 20

# Home page layout limits
MIN_TITLES_PER_ROW = 3
MAX_TITLES_PER_ROW = 10
MAX_ROWS_PER_PAGE = 6
VALID_ROW_TYPES = {
    "next_episode",
    "because_you_watched",
    "popular_in_dialect",
    "new_releases",
    "genre",
}

# Messaging limits & policy
MAX_MESSAGES_PER_IST_DAY = 1  # Push and WhatsApp combined
PUSH_MAX_TITLE_CHARS = 40
PUSH_MAX_BODY_CHARS = 120
FORBIDDEN_PHRASES = {
    "last chance",
    "hurry",
    "only today",
    "free forever",
    "guaranteed",
}

# Pricing values (INR)
VALID_PRICES_INR = {1, 149, 399}
KNOWN_PLANS = {
    "P_TRIAL": {"price_inr": 1, "days": 3, "renews_to": "P_MONTH"},
    "P_MONTH": {"price_inr": 149, "days": 30},
    "P_QUARTER": {"price_inr": 399, "days": 90},
}


def parse_iso(s: Optional[str]) -> Optional[datetime]:
    """Parse ISO-8601 string to a timezone-aware UTC datetime."""
    if not s:
        return None
    s = s.strip()
    if not s:
        return None
    # Normalize Z to +00:00
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


def format_iso(dt: Optional[datetime]) -> Optional[str]:
    """Format datetime as ISO-8601 UTC string with Z suffix and ms precision."""
    if dt is None:
        return None
    dt_utc = dt.astimezone(UTC)
    return dt_utc.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def to_ist(dt: datetime) -> datetime:
    """Convert datetime to IST timezone."""
    return dt.astimezone(IST)


def get_ist_date(dt: datetime) -> date:
    """Get the calendar date in Indian Standard Time."""
    return to_ist(dt).date()


def is_quiet_hours(dt: datetime) -> bool:
    """
    Check if a timestamp falls in quiet hours (22:00 to 08:00 IST).
    During quiet hours, Push and WhatsApp messages are prohibited.
    """
    hour = to_ist(dt).hour
    return hour >= 22 or hour < 8


def load_interventions_config() -> Dict[str, Any]:
    """Load configuration from config/interventions.json."""
    path = CONFIG_DIR / "interventions.json"
    if path.exists():
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def load_pricing_config() -> Dict[str, Any]:
    """Load configuration from config/pricing.json."""
    path = CONFIG_DIR / "pricing.json"
    if path.exists():
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def load_approved_whatsapp_templates() -> Dict[str, Dict[str, Any]]:
    """Return dictionary of approved WhatsApp templates keyed by template_id."""
    cfg = load_interventions_config()
    templates = cfg.get("whatsapp", {}).get("approved_templates", [])
    return {t["template_id"]: t for t in templates}

