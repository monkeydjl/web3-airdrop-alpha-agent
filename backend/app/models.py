"""Pydantic Data Models.

定义所有请求/响应数据模型。
遵循 CONVENTIONS.md §5 类型注解规范。

参考：
- API_SPEC.md 请求/响应格式
- DATA_SCORING_DICT.md 字段字典
"""

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


# ── 通用响应包络 ──────────────────────────────
class ApiResponse(BaseModel):
    """统一 API 响应包络。"""
    ok: bool = Field(..., description="请求是否成功")
    data: Any | None = Field(None, description="响应数据")
    error: dict[str, str] | None = Field(None, description="错误信息")


# ── Agent 输出模型 ─────────────────────────────
class NarrativeResult(BaseModel):
    """Narrative Agent 输出。"""
    model_config = ConfigDict(frozen=True, extra="forbid")

    sector: str = Field(..., description="标准赛道名")
    stage: str = Field(..., pattern=r"^(early|growth|peak|mature)$")
    heat_score: float = Field(..., ge=0.0, le=1.0, description="赛道热度")
    timing: str = Field(..., pattern=r"^(early|peak|late)$", description="时机修正")


class TeamResult(BaseModel):
    """Team Agent 输出。"""
    model_config = ConfigDict(frozen=True, extra="forbid")

    team_score: float = Field(..., ge=0.0, le=1.0, description="团队信誉分")
    team_flags: list[str] = Field(default_factory=list, description="团队风险标记")
    team_type: str = Field(..., pattern=r"^(doxxed|semi_anon|anon|unknown)$")


class RiskResult(BaseModel):
    """Risk Agent 输出。"""
    model_config = ConfigDict(frozen=True, extra="forbid")

    token_risk: float = Field(..., ge=0.0, le=1.0, description="代币风险")
    risk_flags: list[str] = Field(default_factory=list, description="风险标记")
    unlock_pressure: str = Field(..., pattern=r"^(low|medium|high)$")


class TokenomicsResult(BaseModel):
    """Tokenomics Agent 输出。"""
    model_config = ConfigDict(frozen=True, extra="forbid")

    vc_share: float = Field(..., ge=0.0, le=1.0, description="VC 占比")
    team_share: float = Field(..., ge=0.0, le=1.0, description="团队占比")
    unlock_penalty: float = Field(..., ge=0.0, le=1.0, description="解锁惩罚")


# ── 评分结果 ──────────────────────────────────
class ScoreResult(BaseModel):
    """评分结果。"""
    model_config = ConfigDict(frozen=True)

    score: int = Field(..., ge=0, le=100, description="总分 0-100")
    label: Literal["FARM", "WATCH", "IGNORE"] = Field(..., description="三档建议")
    confidence: float = Field(..., ge=0.0, le=1.0, description="置信度")
    reason: list[str] = Field(..., min_length=2, description="评分理由")
    sub_scores: dict[str, float] = Field(default_factory=dict, description="子项分数")


# ── 项目记录 ──────────────────────────────────
class ProjectRecord(BaseModel):
    """项目完整记录（API 响应）。"""
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    url: str | None = None
    sector: str | None = None
    stage: str | None = None
    score: int | None = None
    label: str | None = None
    recommendation: str | None = None
    confidence: float | None = None
    reason: list[str] | None = None
    raw_signals: dict[str, Any] | None = None
    source: str | None = None
    fetched_at: datetime | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


# ── 请求模型 ──────────────────────────────────
class RunRequest(BaseModel):
    """触发运行请求。"""
    source: str = Field(default="seed", description="数据源")
    dry_run: bool = Field(default=False, description="仅分析不写入")
    limit: int = Field(default=50, ge=1, le=500, description="最大项目数")


class RunResponse(BaseModel):
    """运行响应。"""
    run_id: str
    status: Literal["completed", "failed", "partial"]
    project_count: int
    top_score: int | None = None
    elapsed_ms: float
    errors: list[dict[str, str]] = Field(default_factory=list)
