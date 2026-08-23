"""Pydantic Data Models.

定义所有请求/响应数据模型。
遵循 CONVENTIONS.md §5 类型注解规范。

参考：
- API_SPEC.md 请求/响应格式
- DATA_SCORING_DICT.md 字段字典
"""

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, computed_field, model_validator


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

    @computed_field  # type: ignore[prop-decorator]
    @property
    def risk_level(self) -> str:
        """团队风险档（low/medium/high），由 team_score 唯一决定。

        `agents/team.py` 早就有 `score_to_risk_level()`，但只用于打印日志，
        没有字段承载 —— 于是前端详情页与 `services/ai_brief.py` 都在读
        `team_json.risk_level`，而落库的 281 条数据里**这个键出现 0 次**，
        两处永远拿到空值。`routers/v1/insights.py` 则第三次重算了同一套分档。

        做成 computed_field 而不是普通字段：分档必须由 team_score 唯一决定，
        不允许外部传入一个与分数矛盾的档位。
        """
        from app.agents.team import score_to_risk_level

        return score_to_risk_level(self.team_score)

    @model_validator(mode="before")
    @classmethod
    def _drop_computed_risk_level(cls, data):
        """允许把自己 dump 出来的 dict 再喂回来。

        与 `TokenomicsResult._drop_computed_risk` 同因同治：computed_field 会出现在
        `model_dump()` 里，而 `extra="forbid"` 会把它当非法额外字段，于是任何从
        `team_json` 回放的导入/重算路径都会硬失败。丢弃传入值并重算，保证
        risk_level 永远由 team_score 唯一决定。
        """
        if isinstance(data, dict) and "risk_level" in data:
            data = {key: value for key, value in data.items() if key != "risk_level"}
        return data


class RiskResult(BaseModel):
    """Risk Agent 输出。"""

    model_config = ConfigDict(frozen=True, extra="forbid")

    token_risk: float = Field(..., ge=0.0, le=1.0, description="代币风险")
    risk_flags: list[str] = Field(default_factory=list, description="风险标记")
    unlock_pressure: str = Field(..., pattern=r"^(low|medium|high)$")
    # Risk Agent 本就计算了女巫难度，此前无字段承载只能打日志，Scorer 只好去
    # 猜 risk_flags 里的字符串（且字符串对不上，恒为 medium）。补字段消除猜测。
    sybil_difficulty: str = Field(
        default="medium",
        pattern=r"^(low|medium|high)$",
        description="女巫攻击难度（DATA_SCORING_DICT §5.4 sybil_factor 输入）",
    )
    # 同一个毛病的第二例：`assess_farming_cost()` 早就在算，但结果只进日志
    # （risk.py 里那行注释写着 "not in RiskResult but useful for logging"），
    # 而前端详情页「交互成本」与 ai_brief 都在读 risk.farming_cost —— 落库的
    # 281 条里这个键出现 0 次，两处一直显示兜底值。
    farming_cost: str = Field(
        default="medium",
        pattern=r"^(low|medium|high)$",
        description="交互成本（gas + 时间投入），来自 assess_farming_cost()",
    )


class TokenomicsResult(BaseModel):
    """Tokenomics Agent 输出。"""

    model_config = ConfigDict(frozen=True, extra="forbid")

    vc_share: float = Field(..., ge=0.0, le=1.0, description="VC 占比")
    team_share: float = Field(..., ge=0.0, le=1.0, description="团队占比")
    unlock_penalty: float = Field(..., ge=0.0, le=1.0, description="解锁惩罚")

    @model_validator(mode="before")
    @classmethod
    def _drop_computed_risk(cls, data):
        """允许把自己 dump 出来的 dict 再喂回来。

        `risk` 是 computed_field，会出现在 `model_dump()` 里；而 `extra="forbid"`
        会把它当成非法额外字段。不处理的话 `TokenomicsResult(**t.model_dump())`
        与 `.model_validate(t.model_dump())` 都会抛 ValidationError——任何从
        `tokenomics_json` 回放的导入/重算路径都会硬失败。这里丢弃传入值并重新
        计算，保证 risk 永远由三个输入唯一决定，不可被外部覆盖。
        """
        if isinstance(data, dict) and "risk" in data:
            data = {key: value for key, value in data.items() if key != "risk"}
        return data

    @computed_field  # type: ignore[prop-decorator]
    @property
    def risk(self) -> float:
        """综合代币结构风险。

        DATA_SCORING_DICT §5.7.1 的权威定义：
            risk = vc_share × 0.4 + team_share × 0.3 + unlock_penalty × 0.3

        此前该字段缺失，Scorer 内联重算（正确）而 Risk Agent 用 unlock_penalty
        顶替（错误），同一概念存在两套实现。此处收敛为单一定义。
        """
        return round(self.vc_share * 0.4 + self.team_share * 0.3 + self.unlock_penalty * 0.3, 6)


# ── 评分结果 ──────────────────────────────────
class ScoreResult(BaseModel):
    """评分结果。"""

    model_config = ConfigDict(frozen=True)

    score: int = Field(..., ge=0, le=100, description="总分 0-100")
    label: Literal["FARM", "WATCH", "IGNORE"] = Field(..., description="三档建议")
    confidence: float = Field(..., ge=0.0, le=1.0, description="置信度")
    reason: list[str] = Field(..., min_length=2, description="评分理由")
    sub_scores: dict[str, float] = Field(default_factory=dict, description="子项分数")
    weight_version: str = Field(default="v1.2", description="产出该分数的权重版本（ADR-006）")


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
    validation_errors: list[str] | None = None  # 导入验证错误
    # Store states for API access
    states: list[Any] = Field(default_factory=list, exclude=True)
    persisted_project_rows: list[dict[str, Any]] = Field(default_factory=list, exclude=True)
