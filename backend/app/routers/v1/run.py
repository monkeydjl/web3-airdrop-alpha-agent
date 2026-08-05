"""Run Endpoint - 运行评分 Pipeline.

POST /api/v1/run
- 接收项目列表
- 运行 SimpleOrchestrator
- 返回评分结果

Reference:
- ENGINEERING_ROADMAP.md §8.1 核心端点
- API_SPEC.md /run 端点定义
"""

import structlog
from fastapi import APIRouter, Body, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from app.agents.collector import CollectorAgent
from app.inflight import QueueDrainInProgressError
from app.openapi import ERROR_RESPONSE_EXAMPLES, RUN_REQUEST_EXAMPLES
from app.pipeline_run import execute_analysis_pipeline

logger = structlog.get_logger(__name__)

router = APIRouter(tags=["pipeline"])


# ══════════════════════════════════════════════════════════════
# Request/Response Models
# ══════════════════════════════════════════════════════════════


class ProjectInput(BaseModel):
    """单个项目输入。"""

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "name": "LayerX",
                "url": "https://layerx.xyz",
                "sector": "L2",
                "stage": "testnet",
                "has_testnet": True,
                "has_points_program": True,
                "no_token_yet": True,
                "recent_funding": True,
            }
        }
    )

    name: str = Field(..., min_length=1, max_length=200, description="项目名称")
    url: str | None = Field(None, max_length=500, description="项目官网")
    sector: str | None = Field(None, max_length=50, description="项目类型/赛道")
    stage: str | None = Field(None, max_length=50, description="项目阶段")

    # Airdrop signals
    has_testnet: bool = Field(False, description="是否有测试网")
    has_points_program: bool = Field(False, description="是否有积分计划")
    no_token_yet: bool = Field(False, description="是否未发币")
    recent_funding: bool = Field(False, description="是否近期融资")


class RunRequest(BaseModel):
    """Run 端点请求体。"""

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "projects": [
                    {
                        "name": "LayerX",
                        "url": "https://layerx.xyz",
                        "sector": "L2",
                        "stage": "testnet",
                        "has_testnet": True,
                        "has_points_program": True,
                        "no_token_yet": True,
                        "recent_funding": True,
                    }
                ],
                "enable_llm": False,
            }
        }
    )

    projects: list[ProjectInput] | None = Field(
        None,
        max_length=100,
        description="待评分项目列表；为空/None 时自动从 raw_projects 表读取未处理项目（v2.0 自动采集）",
    )

    enable_llm: bool = Field(False, description="是否启用 LLM（默认 False，使用启发式规则）")

    llm_model: str = Field("gpt-4o-mini", description="LLM 模型名称（仅当 enable_llm=True 时生效）")


class ProjectResult(BaseModel):
    """单个项目评分结果。"""

    # 项目基本信息
    id: str
    name: str
    sector: str | None
    stage: str | None

    # 评分结果
    score: int
    label: str
    confidence: float
    reason: list[str]

    # Agent 分析结果
    narrative: dict | None = None
    team: dict | None = None
    risk: dict | None = None
    tokenomics: dict | None = None

    # 元数据
    errors: list[dict] = []


class RunResponse(BaseModel):
    """Run 端点响应体。"""

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "ok": True,
                "data": {
                    "run_id": "run-2024-01-01-12-00-00",
                    "status": "completed",
                    "project_count": 1,
                    "scored_count": 1,
                    "error_count": 0,
                    "top_projects": [
                        {
                            "id": "layerx-001",
                            "name": "LayerX",
                            "sector": "L2",
                            "score": 85,
                            "label": "FARM",
                            "confidence": 1.0,
                            "reason": ["strong airdrop signal", "early narrative", "credible team"],
                        }
                    ],
                },
            }
        }
    )

    ok: bool = Field(True, description="请求是否成功")
    data: dict = Field(..., description="响应数据")


class ErrorResponse(BaseModel):
    """错误响应。"""

    model_config = ConfigDict(
        json_schema_extra={
            "example": {"ok": False, "error": {"code": "VALIDATION_ERROR", "message": "Invalid project data"}}
        }
    )

    ok: bool = Field(False, description="请求失败")
    error: dict = Field(..., description="错误信息")


# ══════════════════════════════════════════════════════════════
# Endpoints
# ══════════════════════════════════════════════════════════════


@router.post(
    "/run",
    response_model=RunResponse,
    responses={
        400: {
            "model": ErrorResponse,
            "description": "输入验证失败",
            "content": {
                "application/json": {"examples": {"validation_error": ERROR_RESPONSE_EXAMPLES["validation_error"]}}
            },
        },
        500: {
            "model": ErrorResponse,
            "description": "Pipeline 执行错误",
            "content": {
                "application/json": {"examples": {"pipeline_error": ERROR_RESPONSE_EXAMPLES["pipeline_error"]}}
            },
        },
    },
    summary="运行评分 Pipeline",
    description=(
        "提交项目列表，运行完整评分 Pipeline，返回评分结果。\n\n"
        "## 评分流程\n\n"
        "1. **数据收集**: 接收项目基本信息和空投信号\n"
        "2. **并行分析**: 4 个 Agent 同时分析\n"
        "   - Narrative Agent: 叙事时机和赛道热度\n"
        "   - Team Agent: 团队信誉和背书\n"
        "   - Risk Agent: 代币风险和解锁压力\n"
        "   - Tokenomics Agent: 代币经济学模型\n"
        "3. **综合评分**: Scorer Agent 加权计算最终分数\n"
        "4. **三档分类**: FARM (≥65) / WATCH (≥50) / IGNORE (<50)\n\n"
        "## 限制\n\n"
        "- 每次最多 100 个项目\n"
        "- 每个项目名称必填，最长 200 字符\n"
        "- URL/sector/stage 可选\n\n"
        "## 返回内容\n\n"
        "- 前 10 个评分项目（按分数排序）\n"
        "- 每个项目包含完整分析结果和评分理由\n"
        "- 运行统计信息（总数/成功/失败）\n"
    ),
)
async def run_pipeline(
    request: RunRequest = Body(
        ...,
        openapi_examples=RUN_REQUEST_EXAMPLES,
    ),
) -> RunResponse:
    """运行评分 Pipeline。

    Args:
        request: RunRequest 请求体

    Returns:
        RunResponse 包含评分结果

    Raises:
        HTTPException: 验证失败或执行错误
    """
    logger.info(
        "api.run.started",
        has_input_projects=request.projects is not None and len(request.projects) > 0,
        enable_llm=request.enable_llm,
    )

    trigger = "manual" if request.projects else "auto"

    try:
        seed_projects = None
        if request.projects:
            seed_inputs = [p.model_dump() for p in request.projects]
            seed_projects = CollectorAgent().collect_from_seed(seed_inputs)

        data = await execute_analysis_pipeline(
            projects=seed_projects,
            enable_llm=request.enable_llm,
            trigger=trigger,
        )
        return RunResponse(ok=True, data=data)

    except QueueDrainInProgressError as e:
        # 空 body 的 /run 排空共享队列，已有一次在飞时拒绝而不是并发跑第二次
        # （会重复评分同批项目）。409 表示"稍后重试即可"，非服务端故障。
        logger.info("api.run.rejected", reason="queue_drain_in_progress")
        raise HTTPException(
            status_code=409,
            detail={
                "code": "ANALYSIS_IN_PROGRESS",
                "message": "An analysis run is already in progress",
            },
        ) from e

    except Exception as e:
        logger.error(
            "api.run.failed",
            error=str(e),
            exc_info=True,
        )
        # 不回显异常原文：psycopg 的 OperationalError 带完整 DSN（含库密码），
        # httpx 的异常带完整 URL（含 ?apikey=）。细节只进日志，不进响应体。
        raise HTTPException(
            status_code=500,
            detail={
                "code": "PIPELINE_ERROR",
                "message": "Pipeline execution failed",
            },
        ) from e
