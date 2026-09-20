"""User Profile Memory service (Roadmap §24.3 / §25.5.3 / W12-02).

Infers user preference vectors (sector affinity, risk tolerance, favorite sectors)
from historical actions (feedback, interactions, watchlist, skips) to support
personalized project ranking and privacy-preserving preference management.
"""
from __future__ import annotations

import math
from collections import defaultdict
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from typing import Any

import structlog

from app.db import DbConnection, get_connection
from app.services.user_scope import DEFAULT_USER

logger = structlog.get_logger(__name__)

# Global registry of cleared users (for GDPR / privacy-preserving reset)
_CLEARED_USERS: set[str] = set()


@dataclass
class UserProfile:
    user_id: str
    sector_affinity: dict[str, float] = field(default_factory=dict)
    risk_tolerance: str = "moderate"  # "conservative" | "moderate" | "aggressive"
    favorite_sectors: list[str] = field(default_factory=list)
    engagement_summary: dict[str, int] = field(default_factory=dict)
    inferred_at: str = ""
    is_cleared: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class UserProfileMemoryService:
    """Service to infer user preference vector and apply personalized ranking."""

    def __init__(self, conn: DbConnection | None = None) -> None:
        self._conn = conn

    def infer_user_profile(self, user_id: str | None = None) -> UserProfile:
        """Infer user profile from feedback, interactions, watchlist, and skips."""
        uid = (user_id or DEFAULT_USER).strip()
        now_iso = datetime.now(UTC).isoformat()

        if uid in _CLEARED_USERS:
            return UserProfile(
                user_id=uid,
                sector_affinity={},
                risk_tolerance="moderate",
                favorite_sectors=[],
                engagement_summary={"total_signals": 0},
                inferred_at=now_iso,
                is_cleared=True,
            )

        if self._conn is not None:
            return self._build_profile(self._conn, uid, now_iso)

        with get_connection() as conn:
            return self._build_profile(conn, uid, now_iso)

    def clear_user_profile(self, user_id: str | None = None) -> bool:
        """Clear inferred user profile memory for GDPR and privacy compliance."""
        uid = (user_id or DEFAULT_USER).strip()
        _CLEARED_USERS.add(uid)
        logger.info("user_memory.profile_cleared", user_id=uid)
        return True

    def personalize_projects(
        self,
        projects: list[dict[str, Any]],
        profile: UserProfile | dict[str, Any],
    ) -> list[dict[str, Any]]:
        """Rank projects based on user profile affinity without altering base score in DB."""
        affinity = (
            profile.sector_affinity
            if isinstance(profile, UserProfile)
            else (profile.get("sector_affinity") or {})
        )

        if not affinity:
            return projects

        personalized_list = []
        for p in projects:
            base_score = float(p.get("score") or 0)
            sector = str(p.get("sector") or "")
            weight = float(affinity.get(sector, 1.0))
            p_copy = dict(p)
            p_copy["personalized_score"] = round(base_score * weight, 1)
            personalized_list.append(p_copy)

        def sort_key(item: dict[str, Any]) -> tuple[float, float, float, str]:
            p_score = float(item.get("personalized_score") or 0.0)
            b_score = float(item.get("score") or 0.0)
            conf = float(item.get("confidence") or 0.0)
            name = str(item.get("name") or "")
            return (p_score, b_score, conf, name)

        return sorted(personalized_list, key=sort_key, reverse=True)

    def _build_profile(self, conn: DbConnection, uid: str, now_iso: str) -> UserProfile:
        sector_scores: dict[str, float] = defaultdict(float)
        high_risk_engaged = 0
        high_risk_avoided = 0

        feedback_count = 0
        interaction_count = 0
        watchlist_count = 0
        skip_count = 0

        # 1. Feedback signals
        try:
            fb_rows = conn.execute(
                """
                SELECT f.project_id, f.signal, f.outcome, p.sector, p.risk_json as risk
                FROM feedback f
                LEFT JOIN projects p ON f.project_id = p.id
                WHERE f.user_id = ? OR (f.user_id IS NULL AND ? = 'default')
                """,
                (uid, uid),
            ).fetchall()

            for r in fb_rows:
                feedback_count += 1
                sector = str(r["sector"] or "").strip()
                signal = str(r["signal"] or "")
                outcome = str(r["outcome"] or "")
                risk_str = str(r["risk"] or "")

                is_high_risk = "high" in risk_str.lower() or "critical" in risk_str.lower()

                if signal == "useful" or outcome in ("airdropped", "pumped"):
                    if sector:
                        sector_scores[sector] += 2.0
                    if is_high_risk:
                        high_risk_engaged += 1
                elif signal in ("useless", "wrong_label") or outcome in ("not_airdropped", "dumped"):
                    if sector:
                        sector_scores[sector] -= 1.0
                    if is_high_risk:
                        high_risk_avoided += 1
        except Exception as e:
            logger.warning("user_memory.feedback_query_failed", error=str(e))

        # 2. Interactions signals
        try:
            inter_rows = conn.execute(
                """
                SELECT i.project_id, i.status, p.sector, p.risk_json as risk
                FROM interactions i
                LEFT JOIN projects p ON i.project_id = p.id
                WHERE i.user_id = ? OR (i.user_id IS NULL AND ? = 'default')
                """,
                (uid, uid),
            ).fetchall()

            for r in inter_rows:
                interaction_count += 1
                sector = str(r["sector"] or "").strip()
                status = str(r["status"] or "")
                risk_str = str(r["risk"] or "")
                is_high_risk = "high" in risk_str.lower() or "critical" in risk_str.lower()

                if status in ("active", "done"):
                    if sector:
                        sector_scores[sector] += 2.5
                    if is_high_risk:
                        high_risk_engaged += 1
                elif status == "planned":
                    if sector:
                        sector_scores[sector] += 1.0
                elif status == "abandoned":
                    if sector:
                        sector_scores[sector] -= 0.5
        except Exception as e:
            logger.warning("user_memory.interactions_query_failed", error=str(e))

        # 3. Watchlist signals
        try:
            wl_rows = conn.execute(
                """
                SELECT w.project_id, p.sector, p.risk_json as risk
                FROM watchlist w
                LEFT JOIN projects p ON w.project_id = p.id
                WHERE w.user_id = ? OR (w.user_id IS NULL AND ? = 'default')
                """,
                (uid, uid),
            ).fetchall()

            for r in wl_rows:
                watchlist_count += 1
                sector = str(r["sector"] or "").strip()
                risk_str = str(r["risk"] or "")
                is_high_risk = "high" in risk_str.lower() or "critical" in risk_str.lower()

                if sector:
                    sector_scores[sector] += 1.5
                if is_high_risk:
                    high_risk_engaged += 1
        except Exception as e:
            logger.warning("user_memory.watchlist_query_failed", error=str(e))

        # 4. Project Skips signals
        try:
            sk_rows = conn.execute(
                """
                SELECT s.project_id, p.sector, p.risk_json as risk
                FROM project_skips s
                LEFT JOIN projects p ON s.project_id = p.id
                WHERE s.user_id = ? OR (s.user_id IS NULL AND ? = 'default')
                """,
                (uid, uid),
            ).fetchall()

            for r in sk_rows:
                skip_count += 1
                sector = str(r["sector"] or "").strip()
                risk_str = str(r["risk"] or "")
                is_high_risk = "high" in risk_str.lower() or "critical" in risk_str.lower()

                if sector:
                    sector_scores[sector] -= 1.0
                if is_high_risk:
                    high_risk_avoided += 1
        except Exception as e:
            logger.warning("user_memory.skips_query_failed", error=str(e))

        # Compute normalized sector affinity weights
        sector_affinity: dict[str, float] = {}
        for sec, score in sector_scores.items():
            if not sec:
                continue
            if score > 0:
                w = 1.0 + 0.15 * math.log(1 + score)
                sector_affinity[sec] = round(min(2.0, w), 2)
            elif score < 0:
                w = 1.0 - 0.15 * math.log(1 + abs(score))
                sector_affinity[sec] = round(max(0.5, w), 2)
            else:
                sector_affinity[sec] = 1.0

        # Favorite sectors (top 3 with score > 0)
        fav_candidates = sorted(
            [(sec, score) for sec, score in sector_scores.items() if score > 0 and sec],
            key=lambda x: x[1],
            reverse=True,
        )
        favorite_sectors = [c[0] for c in fav_candidates[:3]]

        # Risk tolerance inference
        total_risk_signals = high_risk_engaged + high_risk_avoided
        if total_risk_signals >= 2:
            if high_risk_avoided / total_risk_signals > 0.6:
                risk_tolerance = "conservative"
            elif high_risk_engaged / total_risk_signals > 0.6:
                risk_tolerance = "aggressive"
            else:
                risk_tolerance = "moderate"
        else:
            risk_tolerance = "moderate"

        total_signals = feedback_count + interaction_count + watchlist_count + skip_count

        return UserProfile(
            user_id=uid,
            sector_affinity=sector_affinity,
            risk_tolerance=risk_tolerance,
            favorite_sectors=favorite_sectors,
            engagement_summary={
                "feedback_count": feedback_count,
                "interaction_count": interaction_count,
                "watchlist_count": watchlist_count,
                "skip_count": skip_count,
                "total_signals": total_signals,
            },
            inferred_at=now_iso,
            is_cleared=False,
        )
