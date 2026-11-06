"""Catalogue and episode indexing, temporal availability tracking, and prompt-injection defense."""
import csv
import re
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

from src.config import DATA_DIR, parse_iso

# Regex patterns for adversarial instructions injected into catalogue content
PROMPT_INJECTION_PATTERNS = [
    re.compile(r"SYSTEM\s+NOTE\s+FOR\s+AI\s+AGENTS:?.*", re.IGNORECASE),
    re.compile(r"\[assistant\s+instruction\].*", re.IGNORECASE),
    re.compile(r"ignore\s+your\s+previous\s+rules.*", re.IGNORECASE),
    re.compile(r"mark\s+every\s+user\s+eligible.*", re.IGNORECASE),
]


class Catalogue:
    """
    Catalogue index with temporal availability checking, dialect indexing,
    episode sequence tracking, and adversarial instruction stripping.
    """

    def __init__(self):
        self.titles: Dict[str, Dict[str, Any]] = {}
        self.titles_by_dialect: Dict[str, List[str]] = defaultdict(list)
        self.titles_by_slug: Dict[str, List[str]] = defaultdict(list)
        self.episodes_by_slug: Dict[str, List[Tuple[int, int, str, int]]] = defaultdict(list)
        self.withdrawn_titles: Dict[str, datetime] = {}

    def load_from_pack(self, pack_dir: Optional[Path] = None) -> None:
        """Load data/catalogue.csv and data/episodes.csv."""
        base = pack_dir or DATA_DIR.parent
        cat_path = base / "data" / "catalogue.csv"
        eps_path = base / "data" / "episodes.csv"

        if cat_path.exists():
            with open(cat_path, "r", encoding="utf-8") as f:
                for row in csv.DictReader(f):
                    tid = row["title_id"]
                    slug = row["content_slug"]
                    avail_from = parse_iso(row["available_from"])
                    avail_until = parse_iso(row["available_until"]) if row["available_until"] else None

                    raw_desc = row.get("description", "")
                    clean_desc = self.sanitize_description(raw_desc)

                    entry = {
                        "title_id": tid,
                        "content_slug": slug,
                        "title": row["title"],
                        "dialect": row["dialect"],
                        "language": row["language"],
                        "content_type": row["content_type"],
                        "genres": row["genres"].split("|") if row["genres"] else [],
                        "release_date": parse_iso(row["release_date"]),
                        "available_from": avail_from,
                        "available_until": avail_until,
                        "is_premium": row["is_premium"] == "true",
                        "description": clean_desc,
                        "raw_description": raw_desc,
                    }
                    self.titles[tid] = entry
                    self.titles_by_dialect[entry["dialect"]].append(tid)
                    self.titles_by_slug[slug].append(tid)

        if eps_path.exists():
            with open(eps_path, "r", encoding="utf-8") as f:
                for row in csv.DictReader(f):
                    slug = row["content_slug"]
                    season = int(row["season"])
                    ep_num = int(row["episode"])
                    eid = row["episode_id"]
                    mins = int(row["minutes"])
                    self.episodes_by_slug[slug].append((season, ep_num, eid, mins))

            for slug in self.episodes_by_slug:
                self.episodes_by_slug[slug].sort(key=lambda x: (x[0], x[1]))

    @staticmethod
    def sanitize_description(desc: str) -> str:
        """
        Strip known adversarial prompt injections from catalogue descriptions.
        Data is passive content, never agent instruction.
        """
        cleaned = desc
        for pat in PROMPT_INJECTION_PATTERNS:
            cleaned = pat.sub("", cleaned)
        return cleaned.strip()

    def is_available(self, title_id: str, at: datetime) -> bool:
        """Check if title is active and available at the given UTC datetime."""
        t = self.titles.get(title_id)
        if not t:
            return False
        if t["available_from"] and at < t["available_from"]:
            return False
        if t["available_until"] and at >= t["available_until"]:
            return False
        return True

    def withdraw_title(self, title_id: str, at: datetime) -> None:
        """Dynamically revoke title availability (e.g. T0001 at 07:00 UTC)."""
        if title_id in self.titles:
            self.titles[title_id]["available_until"] = at
            self.withdrawn_titles[title_id] = at

    def get_available_titles_in_dialect(
        self,
        dialect: str,
        at: datetime,
        content_type: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Return all available titles in the requested dialect."""
        res = []
        for tid in self.titles_by_dialect.get(dialect, []):
            t = self.titles[tid]
            if self.is_available(tid, at):
                if content_type is None or t["content_type"] == content_type:
                    res.append(t)
        return res

    def get_total_episodes_for_slug(self, slug: str) -> int:
        """Return total episode count for a content slug."""
        return len(self.episodes_by_slug.get(slug, []))

    def get_episode_index(self, slug: str, episode_id: str) -> int:
        """Return 0-indexed position of an episode in the series."""
        eps = self.episodes_by_slug.get(slug, [])
        for idx, ep in enumerate(eps):
            if ep[2] == episode_id:
                return idx
        return -1

