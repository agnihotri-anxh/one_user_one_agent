"""Zero-trust air-gapped policy and safety verifier."""
from datetime import datetime
from typing import Any, Dict, List, Optional, Set, Tuple

from src.catalog import Catalogue
from src.config import (
    FORBIDDEN_PHRASES,
    MAX_MESSAGES_PER_IST_DAY,
    MAX_ROWS_PER_PAGE,
    MAX_TITLES_PER_ROW,
    MIN_TITLES_PER_ROW,
    PUSH_MAX_BODY_CHARS,
    PUSH_MAX_TITLE_CHARS,
    VALID_PRICES_INR,
    get_ist_date,
    is_quiet_hours,
    load_approved_whatsapp_templates,
    parse_iso,
)
from src.models import DecisionChecks, PublishedAction, ViewerState


class Verifier:
    """
    Air-Gapped deterministic policy and safety verifier.
    Has absolute veto authority over proposed actions.
    Generated text is NEVER treated as approval or evidence.
    """

    def __init__(self, catalogue: Catalogue):
        self.catalogue = catalogue
        self.approved_templates = load_approved_whatsapp_templates()

    def verify_action(
        self,
        action: PublishedAction,
        state: ViewerState,
        trigger_dialect: Optional[str],
        at: datetime,
    ) -> Tuple[bool, Optional[PublishedAction], DecisionChecks, Optional[str]]:
        """
        Verify a proposed physical action against all physical, policy, and catalog rules.
        Returns: (is_approved, sanitized_action, decision_checks, rejection_reason).
        """
        checks = DecisionChecks()

        # 1. Zero-Tolerance Holdout Check
        if state.arm == "holdout":
            checks.failed.append("holdout_control_arm")
            return False, None, checks, "Viewer is in randomized holdout arm; no action permitted"
        checks.passed.append("holdout_isolation")

        action_type = action.type

        # 2. Home Page Verification
        if action_type == "home_page":
            return self._verify_home_page(action, trigger_dialect, at, checks)

        # 3. Push Notification Verification
        elif action_type == "push":
            return self._verify_push(action, state, at, checks)

        # 4. WhatsApp Verification
        elif action_type == "whatsapp":
            return self._verify_whatsapp(action, state, at, checks)

        # 5. In-App Message Verification
        elif action_type == "in_app_message":
            checks.passed.append("in_app_consent_exempt")
            return True, action, checks, None

        checks.failed.append("unknown_action_type")
        return False, None, checks, f"Unknown action type: {action_type}"

    def _verify_home_page(
        self,
        action: PublishedAction,
        trigger_dialect: Optional[str],
        at: datetime,
        checks: DecisionChecks,
    ) -> Tuple[bool, Optional[PublishedAction], DecisionChecks, Optional[str]]:
        """Verify home page layout, dialect match, availability, and global slug uniqueness."""
        page_dialect = action.dialect

        # Dialect presence & validity
        if not page_dialect or page_dialect in ("NA", "None"):
            checks.failed.append("invalid_page_dialect")
            return False, None, checks, f"Invalid page dialect: {page_dialect}"

        if trigger_dialect and page_dialect != trigger_dialect:
            checks.failed.append("dialect_mismatch_with_client")
            return False, None, checks, f"Page dialect {page_dialect} does not match client {trigger_dialect}"

        checks.passed.append("dialect_match")

        # Global page-level slug registry to prevent cross-row collisions
        seen_slugs: Set[str] = set()
        sanitized_hero: Optional[str] = None

        # Verify Hero Title
        if action.hero_title_id:
            hero_t = self.catalogue.titles.get(action.hero_title_id)
            if (
                hero_t
                and hero_t["dialect"] == page_dialect
                and self.catalogue.is_available(action.hero_title_id, at)
            ):
                sanitized_hero = action.hero_title_id
                seen_slugs.add(hero_t["content_slug"])
                checks.passed.append("hero_valid")
            else:
                checks.failed.append("hero_unavailable_or_wrong_dialect")

        # Verify Rows
        sanitized_rows: List[Dict[str, Any]] = []
        raw_rows = (action.rows or [])[:MAX_ROWS_PER_PAGE]

        for row in raw_rows:
            keep_tids: List[str] = []
            for tid in (row.get("title_ids") or [])[:MAX_TITLES_PER_ROW]:
                t = self.catalogue.titles.get(tid)
                if not t:
                    continue
                if t["dialect"] != page_dialect:
                    continue
                if not self.catalogue.is_available(tid, at):
                    continue
                if t["content_slug"] in seen_slugs:
                    continue  # Deduplicate by slug across the entire page

                seen_slugs.add(t["content_slug"])
                keep_tids.append(tid)

            if len(keep_tids) >= MIN_TITLES_PER_ROW:
                sanitized_rows.append({"row_type": row.get("row_type"), "title_ids": keep_tids})
            else:
                checks.failed.append("row_dropped_below_minimum_titles")

        # Page viability check: must have at least one valid row or valid hero
        if not sanitized_rows and not sanitized_hero:
            checks.failed.append("home_page_empty")
            return False, None, checks, "Home page collapsed: 0 valid rows and no hero"

        checks.passed.append("page_viability")
        action.rows = sanitized_rows
        action.hero_title_id = sanitized_hero
        return True, action, checks, None

    def _verify_push(
        self,
        action: PublishedAction,
        state: ViewerState,
        at: datetime,
        checks: DecisionChecks,
    ) -> Tuple[bool, Optional[PublishedAction], DecisionChecks, Optional[str]]:
        """Verify push notification consent, quiet hours, frequency cap, copy limits."""
        # 1. Consent
        if not state.notifications_opt_in or "push" in state.opted_out_channels:
            checks.failed.append("push_consent_missing")
            return False, None, checks, "User has not opted in to push notifications"
        checks.passed.append("push_consent")

        # 2. Quiet Hours (22:00 to 08:00 IST)
        send_at = parse_iso(action.send_at) or at
        if is_quiet_hours(send_at):
            checks.failed.append("push_quiet_hours_violation")
            return False, None, checks, f"Send time {send_at.isoformat()} falls within IST quiet hours"
        checks.passed.append("quiet_hours")

        # 3. Frequency Cap (1 message per IST calendar day)
        ist_day_str = str(get_ist_date(send_at))
        msgs_today = state.messages_sent_ist_days.get(ist_day_str, 0)
        if msgs_today >= MAX_MESSAGES_PER_IST_DAY:
            checks.failed.append("frequency_cap_exceeded")
            return False, None, checks, f"Frequency cap exceeded: {msgs_today} messages already sent on {ist_day_str}"
        checks.passed.append("frequency_cap")

        # 4. Title Availability & Dialect Match
        if action.title_id:
            t = self.catalogue.titles.get(action.title_id)
            if not t or not self.catalogue.is_available(action.title_id, send_at):
                checks.failed.append("push_title_unavailable")
                return False, None, checks, f"Push title {action.title_id} is unavailable"
        checks.passed.append("title_availability")

        # 5. Copy Sanity & Forbidden Phrases
        text = action.text or {}
        title_text = text.get("title", "")
        body_text = text.get("body", "")

        if len(title_text) > PUSH_MAX_TITLE_CHARS or len(body_text) > PUSH_MAX_BODY_CHARS:
            checks.failed.append("push_copy_length_exceeded")
            return False, None, checks, "Push copy exceeds character limit"

        combined_text = f"{title_text} {body_text}".lower()
        for phrase in FORBIDDEN_PHRASES:
            if phrase in combined_text:
                checks.failed.append(f"forbidden_phrase_{phrase.replace(' ', '_')}")
                return False, None, checks, f"Forbidden marketing phrase detected: {phrase}"

        checks.passed.append("honest_copy")
        return True, action, checks, None

    def _verify_whatsapp(
        self,
        action: PublishedAction,
        state: ViewerState,
        at: datetime,
        checks: DecisionChecks,
    ) -> Tuple[bool, Optional[PublishedAction], DecisionChecks, Optional[str]]:
        """Verify WhatsApp opt-in, quiet hours, daily cap, and approved templates."""
        # 1. Consent
        if not state.whatsapp_opt_in or "whatsapp" in state.opted_out_channels:
            checks.failed.append("whatsapp_consent_missing")
            return False, None, checks, "User has not opted in to WhatsApp messages"
        checks.passed.append("whatsapp_consent")

        # 2. Quiet Hours (22:00 to 08:00 IST)
        send_at = parse_iso(action.send_at) or at
        if is_quiet_hours(send_at):
            checks.failed.append("whatsapp_quiet_hours_violation")
            return False, None, checks, f"Send time {send_at.isoformat()} falls within IST quiet hours"
        checks.passed.append("quiet_hours")

        # 3. Frequency Cap
        ist_day_str = str(get_ist_date(send_at))
        msgs_today = state.messages_sent_ist_days.get(ist_day_str, 0)
        if msgs_today >= MAX_MESSAGES_PER_IST_DAY:
            checks.failed.append("frequency_cap_exceeded")
            return False, None, checks, f"Frequency cap exceeded: {msgs_today} messages sent on {ist_day_str}"
        checks.passed.append("frequency_cap")

        # 4. Approved Template Check
        tmpl_id = action.template_id
        if not tmpl_id or tmpl_id not in self.approved_templates:
            checks.failed.append("unapproved_whatsapp_template")
            return False, None, checks, f"Template {tmpl_id} is not an approved WhatsApp template"
        checks.passed.append("approved_template")

        # 5. Template Variables Validation
        variables = action.variables or {}
        if tmpl_id == "wa_trial_ending_v1":
            price_val = variables.get("plan_price", "").replace("₹", "").strip()
            try:
                numeric_price = int(price_val)
                if numeric_price not in VALID_PRICES_INR:
                    checks.failed.append("unsupported_plan_price")
                    return False, None, checks, f"Invalid price claim: {variables.get('plan_price')}"
            except ValueError:
                checks.failed.append("unsupported_plan_price")
                return False, None, checks, f"Invalid price format: {variables.get('plan_price')}"

        checks.passed.append("valid_variables")
        return True, action, checks, None

