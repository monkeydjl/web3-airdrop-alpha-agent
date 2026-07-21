"""User interaction / participation logs for calibration & review.

Tracks: did I farm this project, start/end dates, cost, profit, notes, outcome.
"""

from __future__ import annotations

import re
import sqlite3
import uuid
from datetime import UTC, date, datetime
from typing import Any, Literal

import structlog
from fastapi import APIRouter, HTTPException, Path, Query
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.db import dict_from_row, get_connection, scalar
from app.repository import ProjectRepository

logger = structlog.get_logger(__name__)
router = APIRouter(tags=["interactions"])

StatusType = Literal["planned", "active", "done", "abandoned"]
OutcomeType = Literal[
    "pending",
    "airdropped",
    "not_airdropped",
    "profit",
    "loss",
    "breakeven",
    "unknown",
]
EligibilityResult = Literal["unknown", "eligible", "ineligible"]
SurvivalResult = Literal["unknown", "passed", "disqualified"]
OpportunityModelVersion = Literal["opportunity-v2.0"]
OpportunityProfileVersion = Literal["low-cost-curated-multiwallet-v1"]
SUPPORTED_MODEL_VERSION = "opportunity-v2.0"
SUPPORTED_PROFILE_VERSION = "low-cost-curated-multiwallet-v1"
# planned -> active|abandoned; active -> done|abandoned; done/abandoned are terminal.
_ALLOWED_STATUS_TRANSITIONS: dict[str, frozenset[str]] = {
    "planned": frozenset({"active", "abandoned"}),
    "active": frozenset({"done", "abandoned"}),
    "done": frozenset(),
    "abandoned": frozenset(),
}
_LINKAGE_FIELDS = {
    "opportunity_assessment_id",
    "opportunity_model_version",
    "opportunity_profile_version",
}
_SENSITIVE_DATA_WARNING = (
    "Do not enter wallet addresses or sensitive identifiers. Standalone 32-44 "
    "character base58 tokens that decode to 32 bytes are rejected. Label transaction "
    "hashes explicitly with tx: or transaction:."
)
_EVM_ADDRESS = re.compile(
    r"(?<![0-9a-z])0x[0-9a-f]{40}(?![0-9a-z])",
    re.IGNORECASE,
)
_HEX_64_TOKEN = re.compile(r"(?<![0-9a-z])(?:0x)?[0-9a-f]{64}(?![0-9a-z])", re.IGNORECASE)
_BASE58_CANDIDATE = re.compile(r"(?<![0-9A-Za-z])[1-9A-HJ-NP-Za-km-z]{32,44}(?![0-9A-Za-z])")
_EXACT_DATE = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}")
_BECH32_CHARSET = "qpzry9x8gf2tvdw0s3jn54khce6mua7l"
_BASE58_ALPHABET = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"


def _bech32_polymod(values: list[int]) -> int:
    generators = (0x3B6A57B2, 0x26508E6D, 0x1EA119FA, 0x3D4233DD, 0x2A1462B3)
    checksum = 1
    for value in values:
        top = checksum >> 25
        checksum = ((checksum & 0x1FFFFFF) << 5) ^ value
        for index, generator in enumerate(generators):
            if (top >> index) & 1:
                checksum ^= generator
    return checksum


def _is_valid_bech32(token: str) -> bool:
    if not 8 <= len(token) <= 90 or (token.lower() != token and token.upper() != token):
        return False
    normalized = token.lower()
    separator = normalized.rfind("1")
    if separator < 1 or separator + 7 > len(normalized):
        return False
    hrp = normalized[:separator]
    data_text = normalized[separator + 1 :]
    if any(not 33 <= ord(char) <= 126 for char in hrp):
        return False
    try:
        data = [_BECH32_CHARSET.index(char) for char in data_text]
    except ValueError:
        return False
    expanded = [ord(char) >> 5 for char in hrp] + [0]
    expanded += [ord(char) & 31 for char in hrp]
    return _bech32_polymod([*expanded, *data]) in (1, 0x2BC830A3)


def _is_bech32_shape(token: str) -> bool:
    if not 8 <= len(token) <= 90:
        return False
    separator = token.rfind("1")
    return (
        1 <= separator <= 83
        and separator + 7 <= len(token)
        and all(33 <= ord(char) <= 126 for char in token[:separator])
        and all(char.lower() in _BECH32_CHARSET for char in token[separator + 1 :])
    )


def _bech32_candidates(value: str):
    for separator, char in enumerate(value):
        if char != "1":
            continue
        data_end = separator + 1
        token_limit = min(len(value), separator + 1 + 89)
        while data_end < token_limit and value[data_end].lower() in _BECH32_CHARSET:
            data_end += 1
        if data_end - separator - 1 < 6:
            continue
        start_limit = max(0, separator - 83)
        for start in range(separator - 1, start_limit - 1, -1):
            if not 33 <= ord(value[start]) <= 126:
                break
            if start > 0 and value[start - 1].isalnum():
                continue
            if data_end < len(value) and value[data_end].isalnum():
                continue
            yield value[start:data_end]


def _base58_decoded_length(token: str) -> int:
    number = 0
    for char in token:
        number = number * 58 + _BASE58_ALPHABET.index(char)
    payload_length = (number.bit_length() + 7) // 8
    return len(token) - len(token.lstrip("1")) + payload_length


def _has_safe_transaction_label(value: str, token_start: int) -> bool:
    return (
        re.search(
            r"(?<![0-9a-z_])(?:tx|transaction):\s*$",
            value[:token_start],
            re.IGNORECASE,
        )
        is not None
    )


def _reject_wallet_address(value: str | None) -> str | None:
    if value is None:
        return None
    if _EVM_ADDRESS.search(value):
        raise ValueError("wallet addresses are not allowed in interaction free text")
    for match in _HEX_64_TOKEN.finditer(value):
        if not _has_safe_transaction_label(value, match.start()):
            raise ValueError("unlabeled secret-shaped hexadecimal token is not allowed")
    if any(_is_valid_bech32(token) for token in _bech32_candidates(value)):
        raise ValueError("wallet addresses are not allowed in interaction free text")
    for match in _BASE58_CANDIDATE.finditer(value):
        token = match.group()
        if _is_bech32_shape(token):
            continue
        if _base58_decoded_length(token) == 32:
            raise ValueError("wallet addresses are not allowed in interaction free text")
    return value


def _canonical_cohort_id(value: str) -> str:
    prefix = "cohort-"
    if not value.startswith(prefix):
        raise ValueError("wallet_cohort_id must use the cohort-UUID format")
    supplied_uuid = value.removeprefix(prefix)
    try:
        parsed = uuid.UUID(supplied_uuid)
    except (AttributeError, ValueError):
        raise ValueError("wallet_cohort_id must use the cohort-UUID format") from None
    canonical = str(parsed)
    if supplied_uuid.lower() != canonical:
        raise ValueError("wallet_cohort_id must contain a canonical UUID")
    if parsed.int == 0 or parsed.version != 4 or parsed.variant != uuid.RFC_4122:
        raise ValueError("wallet_cohort_id must contain a non-nil RFC variant UUID4")
    return f"{prefix}{canonical}"


class _InteractionOutcomeFields(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    wallet_cohort_id: str | None = Field(
        None,
        max_length=100,
        description="Anonymous local wallet cohort identifier; never a wallet address.",
    )
    wallet_count: int = Field(1, ge=1)
    actual_hard_cost_usd: float | None = Field(None, ge=0)
    actual_time_minutes: int | None = Field(None, ge=0)
    eligibility_result: EligibilityResult | None = None
    survival_result: SurvivalResult | None = None
    disqualification_reason: str | None = Field(None, max_length=1000, description=_SENSITIVE_DATA_WARNING)
    reward_received_usd: float | None = Field(None, ge=0)
    claim_cost_usd: float | None = Field(None, ge=0)
    opportunity_assessment_id: str | None = None
    opportunity_model_version: OpportunityModelVersion | None = None
    opportunity_profile_version: OpportunityProfileVersion | None = None
    outcome_observed_at: datetime | None = None

    @field_validator("outcome_observed_at", mode="before")
    @classmethod
    def validate_strict_outcome_datetime(cls, value: Any) -> datetime | None:
        if value is None:
            return None
        if isinstance(value, bool) or not isinstance(value, (str, datetime)):
            raise ValueError("outcome_observed_at must be an ISO 8601 datetime with timezone")
        if isinstance(value, str):
            if "T" not in value or not (value.endswith("Z") or re.search(r"[+-]\d{2}:\d{2}$", value)):
                raise ValueError("outcome_observed_at must include a timezone")
            try:
                value = datetime.fromisoformat(value.replace("Z", "+00:00"))
            except ValueError:
                raise ValueError("outcome_observed_at must be a valid datetime") from None
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("outcome_observed_at must include a timezone")
        return value.astimezone(UTC)

    @field_validator("started_at", "ended_at", mode="before", check_fields=False)
    @classmethod
    def validate_exact_date(cls, value: Any) -> date | None:
        if value is None or type(value) is date:
            return value
        if not isinstance(value, str) or _EXACT_DATE.fullmatch(value) is None:
            raise ValueError("date must be an exact YYYY-MM-DD string")
        try:
            parsed = date.fromisoformat(value)
        except ValueError:
            raise ValueError("date must be a valid calendar date") from None
        if parsed.isoformat() != value:
            raise ValueError("date must round-trip as an exact YYYY-MM-DD string")
        return parsed

    @field_validator("user_id", "activities", "note", "disqualification_reason", check_fields=False)
    @classmethod
    def reject_wallet_addresses(cls, value: str | None) -> str | None:
        return _reject_wallet_address(value)

    @model_validator(mode="after")
    def validate_outcome_fields(self):
        if (
            isinstance(self, InteractionCreate)
            and self.survival_result == "disqualified"
            and not (self.disqualification_reason and self.disqualification_reason.strip())
        ):
            raise ValueError("disqualified survival requires a reason")
        if self.wallet_cohort_id is not None:
            self.wallet_cohort_id = _canonical_cohort_id(self.wallet_cohort_id)
        elif "wallet_cohort_id" in self.model_fields_set:
            raise ValueError("wallet_cohort_id cannot be null")
        return self


class InteractionCreate(_InteractionOutcomeFields):
    project_id: str = Field(..., description="项目 ID")
    user_id: str | None = Field(None, max_length=255, description=_SENSITIVE_DATA_WARNING)
    status: StatusType = "active"
    started_at: date | None = Field(None, description="开始日期 YYYY-MM-DD")
    ended_at: date | None = Field(None, description="结束日期 YYYY-MM-DD")
    cost_usd: float | None = Field(None, ge=0, description="投入成本 USD (Gas/时间折算等)")
    profit_usd: float | None = Field(None, description="最终收益 USD (可负)")
    hours_spent: float | None = Field(None, ge=0, description="花费小时数")
    activities: str | None = Field(None, max_length=1000, description=_SENSITIVE_DATA_WARNING)
    note: str | None = Field(None, max_length=2000, description=_SENSITIVE_DATA_WARNING)
    outcome: OutcomeType | None = Field("pending", description="结果状态")

    @model_validator(mode="after")
    def validate_create_linkage(self):
        if "wallet_cohort_id" not in self.model_fields_set:
            self.wallet_cohort_id = f"cohort-{uuid.uuid4()}"
        supplied = self.model_fields_set.intersection(_LINKAGE_FIELDS)
        if supplied and ("opportunity_assessment_id" not in supplied or self.opportunity_assessment_id is None):
            raise ValueError("model and profile versions require an assessment ID")
        return self


class InteractionUpdate(_InteractionOutcomeFields):
    status: StatusType | None = None
    started_at: date | None = None
    ended_at: date | None = None
    cost_usd: float | None = Field(None, ge=0)
    profit_usd: float | None = None
    hours_spent: float | None = Field(None, ge=0)
    activities: str | None = Field(None, max_length=1000, description=_SENSITIVE_DATA_WARNING)
    note: str | None = Field(None, max_length=2000, description=_SENSITIVE_DATA_WARNING)
    outcome: OutcomeType | None = None
    user_id: str | None = Field(None, max_length=255, description=_SENSITIVE_DATA_WARNING)

    @model_validator(mode="after")
    def validate_update_linkage(self):
        supplied = self.model_fields_set.intersection(_LINKAGE_FIELDS)
        if not supplied:
            return self
        if "opportunity_assessment_id" not in supplied:
            raise ValueError("model or profile version cannot be updated alone")
        if self.opportunity_assessment_id is None and len(supplied) != 1:
            raise ValueError("unlinking accepts only a null assessment ID")
        return self


def _row_to_item(row: Any) -> dict[str, Any]:
    d = dict_from_row(row)
    # computed net
    cost = d.get("cost_usd")
    profit = d.get("profit_usd")
    net = None
    if cost is not None or profit is not None:
        try:
            net = float(profit or 0) - float(cost or 0)
        except (TypeError, ValueError):
            net = None
    d["net_usd"] = net
    d["realized_net_usd"] = (
        float(d.get("reward_received_usd") or 0)
        - float(d.get("actual_hard_cost_usd") or 0)
        - float(d.get("claim_cost_usd") or 0)
    )
    return d


def _canonical_assessment_linkage(
    conn: Any,
    assessment_id: str,
    project_id: str,
) -> tuple[str, str, str]:
    row = conn.execute(
        """SELECT project_id, profile_version, model_version
           FROM opportunity_assessments WHERE assessment_id = ?""",
        (assessment_id,),
    ).fetchone()
    assessment = dict_from_row(row)
    if (
        not assessment
        or assessment.get("project_id") != project_id
        or assessment.get("model_version") != SUPPORTED_MODEL_VERSION
        or assessment.get("profile_version") != SUPPORTED_PROFILE_VERSION
    ):
        raise HTTPException(
            status_code=422,
            detail={
                "code": "INVALID_ASSESSMENT",
                "message": "Assessment does not match the project or supported model/profile",
            },
        )
    return (
        assessment_id,
        assessment["model_version"],
        assessment["profile_version"],
    )


def _validate_status_transition(current_status: str | None, new_status: str) -> None:
    """Enforce interaction lifecycle; same-status patches are no-ops."""
    if current_status == new_status:
        return
    allowed = _ALLOWED_STATUS_TRANSITIONS.get(current_status or "", frozenset())
    if new_status not in allowed:
        raise HTTPException(
            status_code=422,
            detail={
                "code": "INVALID_STATUS_TRANSITION",
                "message": (
                    f"Cannot transition interaction status from "
                    f"{current_status!r} to {new_status!r}"
                ),
            },
        )


@router.post("/interactions")
async def create_interaction(body: InteractionCreate):
    """Create a participation log for a project."""
    repo = ProjectRepository()
    project = repo.get_by_id(body.project_id)
    if not project:
        raise HTTPException(
            status_code=404,
            detail={"code": "NOT_FOUND", "message": f"Project {body.project_id} not found"},
        )

    score_at = project.get("score")
    label_at = project.get("label")
    now = datetime.now(UTC).isoformat()
    outcome_observed_at = body.outcome_observed_at
    if outcome_observed_at is None and body.model_fields_set.intersection(
        {"eligibility_result", "survival_result", "reward_received_usd"}
    ):
        outcome_observed_at = datetime.now(UTC)
    started = body.started_at.isoformat() if body.started_at else now[:10]
    ended = body.ended_at.isoformat() if body.ended_at else None

    conn = get_connection()
    try:
        linkage: tuple[str | None, str | None, str | None] = (None, None, None)
        if body.opportunity_assessment_id is not None:
            linkage = _canonical_assessment_linkage(conn, body.opportunity_assessment_id, body.project_id)
            if (body.opportunity_model_version is not None and body.opportunity_model_version != linkage[1]) or (
                body.opportunity_profile_version is not None and body.opportunity_profile_version != linkage[2]
            ):
                raise HTTPException(status_code=422, detail="Assessment version mismatch")
        insert_sql = """
            INSERT INTO interactions (
                project_id, user_id, status, started_at, ended_at,
                cost_usd, profit_usd, hours_spent, activities, note, outcome,
                score_at_start, label_at_start, created_at, updated_at,
                wallet_cohort_id, wallet_count, actual_hard_cost_usd,
                actual_time_minutes, eligibility_result, survival_result,
                disqualification_reason, reward_received_usd, claim_cost_usd,
                opportunity_assessment_id, opportunity_model_version,
                opportunity_profile_version, outcome_observed_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """
        supports_returning = conn.kind == "postgres" or sqlite3.sqlite_version_info >= (3, 35, 0)
        if supports_returning:
            insert_sql += " RETURNING *"
        cur = conn.execute(
            insert_sql,
            (
                body.project_id,
                body.user_id,
                body.status,
                started,
                ended,
                body.cost_usd,
                body.profit_usd,
                body.hours_spent,
                body.activities,
                body.note,
                body.outcome or "pending",
                score_at,
                label_at,
                now,
                now,
                body.wallet_cohort_id,
                body.wallet_count,
                body.actual_hard_cost_usd,
                body.actual_time_minutes,
                body.eligibility_result,
                body.survival_result,
                body.disqualification_reason,
                body.reward_received_usd,
                body.claim_cost_usd,
                *linkage,
                outcome_observed_at.isoformat() if outcome_observed_at else None,
            ),
        )
        if supports_returning:
            row = cur.fetchone()
        else:
            iid = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
            row = conn.execute("SELECT * FROM interactions WHERE id = ?", (iid,)).fetchone()
        conn.commit()
        item = _row_to_item(row) if row else {"project_id": body.project_id}
        logger.info(
            "interaction.created",
            interaction_id=item.get("id"),
            project_id=body.project_id,
            status=body.status,
        )
        return {"ok": True, "data": item}
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


@router.get("/interactions")
async def list_interactions(
    project_id: str | None = Query(None),
    status: str | None = Query(None),
    limit: int = Query(50, ge=1, le=200),
):
    """List interaction logs (optionally filter by project / status)."""
    conn = get_connection()
    try:
        clauses: list[str] = []
        params: list[Any] = []
        if project_id:
            clauses.append("project_id = ?")
            params.append(project_id)
        if status:
            clauses.append("status = ?")
            params.append(status)
        where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
        params.append(limit)
        # SQL fragments come only from closed internal allowlists; values stay parameterized.
        list_sql = f"""
            SELECT * FROM interactions
            {where}
            ORDER BY COALESCE(started_at, created_at) DESC, id DESC
            LIMIT ?
            """  # noqa: S608
        rows = conn.execute(list_sql, tuple(params)).fetchall()
        items = [_row_to_item(r) for r in rows]
        # SQL fragments come only from closed internal allowlists; values stay parameterized.
        count_sql = f"SELECT COUNT(*) FROM interactions {where}"  # noqa: S608
        total = scalar(
            conn.execute(
                count_sql,
                tuple(params[:-1]),
            ).fetchone()
        )
        return {"ok": True, "data": {"items": items, "total": total, "count": len(items)}}
    finally:
        conn.close()


@router.get("/interactions/summary")
async def interactions_summary():
    """Aggregate stats for calibration / ops."""
    conn = get_connection()
    try:
        total = int(scalar(conn.execute("SELECT COUNT(*) FROM interactions").fetchone()) or 0)
        by_status = {
            dict_from_row(r).get("status"): dict_from_row(r).get("c")
            for r in conn.execute("SELECT status, COUNT(*) AS c FROM interactions GROUP BY status").fetchall()
        }
        by_outcome = {
            dict_from_row(r).get("outcome"): dict_from_row(r).get("c")
            for r in conn.execute("SELECT outcome, COUNT(*) AS c FROM interactions GROUP BY outcome").fetchall()
        }
        # label_at_start vs outcome for simple lift view
        label_outcome = [
            dict_from_row(r)
            for r in conn.execute(
                """
                SELECT label_at_start, outcome, COUNT(*) AS c
                FROM interactions
                WHERE label_at_start IS NOT NULL
                GROUP BY label_at_start, outcome
                """
            ).fetchall()
        ]
        sums = conn.execute(
            """
            SELECT
                COALESCE(SUM(cost_usd), 0) AS total_cost,
                COALESCE(SUM(profit_usd), 0) AS total_profit,
                COALESCE(SUM(hours_spent), 0) AS total_hours
            FROM interactions
            """
        ).fetchone()
        s = dict_from_row(sums) if sums else {}
        total_cost = float(s.get("total_cost") or 0)
        total_profit = float(s.get("total_profit") or 0)
        return {
            "ok": True,
            "data": {
                "total": total,
                "by_status": by_status,
                "by_outcome": by_outcome,
                "label_outcome_matrix": label_outcome,
                "total_cost_usd": total_cost,
                "total_profit_usd": total_profit,
                "net_usd": total_profit - total_cost,
                "total_hours": float(s.get("total_hours") or 0),
            },
        }
    finally:
        conn.close()


@router.get("/projects/{project_id}/interactions")
async def list_project_interactions(
    project_id: str = Path(...),
    limit: int = Query(50, ge=1, le=200),
):
    return await list_interactions(project_id=project_id, status=None, limit=limit)


@router.patch("/interactions/{interaction_id}")
async def update_interaction(
    interaction_id: int = Path(...),
    body: InteractionUpdate = ...,
):
    fields = body.model_dump(exclude_unset=True, mode="json")
    if not fields:
        raise HTTPException(
            status_code=400,
            detail={"code": "EMPTY", "message": "No fields to update"},
        )
    now = datetime.now(UTC)
    if "outcome_observed_at" not in fields and body.model_fields_set.intersection(
        {"eligibility_result", "survival_result", "reward_received_usd"}
    ):
        fields["outcome_observed_at"] = now.isoformat()
    fields["updated_at"] = now.isoformat()
    sets = ", ".join(f"{k} = ?" for k in fields)
    values = [*fields.values(), interaction_id]

    conn = get_connection()
    try:
        conn.begin_serialized_write()
        select_sql = "SELECT * FROM interactions WHERE id = ?"
        if conn.kind == "postgres":
            select_sql += " FOR UPDATE"
        existing = conn.execute(select_sql, (interaction_id,)).fetchone()
        if existing is None:
            raise HTTPException(
                status_code=404,
                detail={"code": "NOT_FOUND", "message": "Interaction not found"},
            )
        current = dict_from_row(existing)
        if "status" in fields:
            _validate_status_transition(current.get("status"), fields["status"])
        final_survival = fields.get("survival_result", current.get("survival_result"))
        final_reason = fields.get("disqualification_reason", current.get("disqualification_reason"))
        if final_survival == "disqualified" and not (final_reason and final_reason.strip()):
            raise HTTPException(
                status_code=422,
                detail={
                    "code": "INVALID_OUTCOME",
                    "message": "Disqualified survival requires a reason",
                },
            )
        supplied_linkage = body.model_fields_set.intersection(_LINKAGE_FIELDS)
        if "opportunity_assessment_id" in supplied_linkage:
            assessment_id = fields["opportunity_assessment_id"]
            if assessment_id is None:
                linkage: tuple[str | None, str | None, str | None] = (
                    None,
                    None,
                    None,
                )
            else:
                linkage = _canonical_assessment_linkage(conn, assessment_id, current["project_id"])
                if (
                    "opportunity_model_version" in supplied_linkage
                    and fields["opportunity_model_version"] != linkage[1]
                ) or (
                    "opportunity_profile_version" in supplied_linkage
                    and fields["opportunity_profile_version"] != linkage[2]
                ):
                    raise HTTPException(status_code=422, detail="Assessment version mismatch")
            fields.update(
                {
                    "opportunity_assessment_id": linkage[0],
                    "opportunity_model_version": linkage[1],
                    "opportunity_profile_version": linkage[2],
                }
            )
            sets = ", ".join(f"{k} = ?" for k in fields)
            values = [*fields.values(), interaction_id]
        supports_returning = conn.kind == "postgres" or sqlite3.sqlite_version_info >= (3, 35, 0)
        # SQL fragments come only from closed Pydantic/internal field allowlists.
        update_sql = f"UPDATE interactions SET {sets} WHERE id = ?"  # noqa: S608
        if supports_returning:
            update_sql += " RETURNING *"
        cur = conn.execute(
            update_sql,
            tuple(values),
        )
        if supports_returning:
            row = cur.fetchone()
        else:
            if (cur.rowcount or 0) == 0:
                raise HTTPException(
                    status_code=404,
                    detail={"code": "NOT_FOUND", "message": "Interaction not found"},
                )
            row = conn.execute("SELECT * FROM interactions WHERE id = ?", (interaction_id,)).fetchone()
        if row is None:
            raise HTTPException(
                status_code=404,
                detail={"code": "NOT_FOUND", "message": "Interaction not found"},
            )
        conn.commit()
        return {"ok": True, "data": _row_to_item(row)}
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


@router.delete("/interactions/{interaction_id}")
async def delete_interaction(interaction_id: int = Path(...)):
    conn = get_connection()
    try:
        cur = conn.execute("DELETE FROM interactions WHERE id = ?", (interaction_id,))
        conn.commit()
        if (cur.rowcount or 0) == 0:
            raise HTTPException(
                status_code=404,
                detail={"code": "NOT_FOUND", "message": "Interaction not found"},
            )
        return {"ok": True, "data": {"deleted": True, "id": interaction_id}}
    finally:
        conn.close()
