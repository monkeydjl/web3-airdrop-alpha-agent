"""Run Endpoint - 运行评分 Pipeline.

POST /api/v1/run
- 接收项目列表
- 运行 SimpleOrchestrator
- 返回评分结果

Reference:
- ENGINEERING_ROADMAP.md §8.1 核心端点
- API_SPEC.md /run 端点定义
"""

from typing import List, Optional
from datetime import datetime

from fastapi import APIRouter, HTTPException, Body
from pydantic import BaseModel, Field, ConfigDict
import structlog

from app.agents.base import RawProject, AgentContext
from app.agents.orchestrator_simple import run_orchestrator
from app.openapi import RUN_REQUEST_EXAMPLES, RUN_RESPONSE_EXAMPLE, ERROR_RESPONSE_EXAMPLES

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
    url: Optional[str] = Field(None, max_length=500, description="项目官网")
    sector: Optional[str] = Field(None, max_length=50, description="项目类型/赛道")
    stage: Optional[str] = Field(None, max_length=50, description="项目阶段")

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

    projects: List[ProjectInput] = Field(
        ...,
        min_length=1,
        max_length=100,
        description="待评分项目列表"
    )

    enable_llm: bool = Field(
        False,
        description="是否启用 LLM（默认 False，使用启发式规则）"
    )

    llm_model: str = Field(
        "gpt-4o-mini",
        description="LLM 模型名称（仅当 enable_llm=True 时生效）"
    )


class ProjectResult(BaseModel):
    """单个项目评分结果。"""

    # 项目基本信息
    id: str
    name: str
    sector: Optional[str]
    stage: Optional[str]

    # 评分结果
    score: int
    label: str
    confidence: float
    reason: List[str]

    # Agent 分析结果
    narrative: Optional[dict] = None
    team: Optional[dict] = None
    risk: Optional[dict] = None
    tokenomics: Optional[dict] = None

    # 元数据
    errors: List[dict] = []


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
                            "reason": [
                                "strong airdrop signal",
                                "early narrative",
                                "credible team"
                            ]
                        }
                    ]
                }
            }
        }
    )

    ok: bool = Field(True, description="请求是否成功")
    data: dict = Field(..., description="响应数据")


class ErrorResponse(BaseModel):
    """错误响应。"""

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "ok": False,
                "error": {
                    "code": "VALIDATION_ERROR",
                    "message": "Invalid project data"
                }
            }
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
                "application/json": {
                    "examples": {
                        "validation_error": ERROR_RESPONSE_EXAMPLES["validation_error"]
                    }
                }
            }
        },
        500: {
            "model": ErrorResponse,
            "description": "Pipeline 执行错误",
            "content": {
                "application/json": {
                    "examples": {
                        "pipeline_error": ERROR_RESPONSE_EXAMPLES["pipeline_error"]
                    }
                }
            }
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
        "4. **三档分类**: FARM (≥75) / WATCH (60-74) / IGNORE (<60)\n\n"
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
    )
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
        project_count=len(request.projects),
        enable_llm=request.enable_llm,
    )

    try:
        # 1. 转换输入为 RawProject
        raw_projects = []
        for idx, proj_input in enumerate(request.projects):
            raw_project = RawProject(
                id=f"api-input-{idx}",  # 临时 ID，Collector 会生成确定性 ID
                name=proj_input.name,
                url=proj_input.url,
                sector=proj_input.sector,
                stage=proj_input.stage,
                source="api",
                has_testnet=proj_input.has_testnet,
                has_points_program=proj_input.has_points_program,
                no_token_yet=proj_input.no_token_yet,
                recent_funding=proj_input.recent_funding,
            )
            raw_projects.append(raw_project)

        # 2. 运行 Orchestrator
        run_id = f"api-run-{datetime.now().strftime('%Y%m%d-%H%M%S')}"

        response = await run_orchestrator(
            projects=raw_projects,
            run_id=run_id,
            enable_llm=request.enable_llm,
            # Note: llm_model parameter not yet supported in run_orchestrator
        )

        # 3. 构造响应
        top_projects = []
        for state in response.states[:10]:  # 返回前 10 个
            project_result = {
                "id": state.project.id,
                "name": state.project.name,
                "sector": state.project.sector,
                "stage": state.project.stage,
                "score": state.score,
                "label": state.label,
                "confidence": state.confidence,
                "reason": state.reason,
            }

            # 可选：包含详细分析结果
            if state.narrative:
                project_result["narrative"] = {
                    "sector": state.narrative.sector,
                    "stage": state.narrative.stage,
                    "heat_score": state.narrative.heat_score,
                    "timing": state.narrative.timing,
                }

            if state.team:
                project_result["team"] = {
                    "team_score": state.team.team_score,
                    "team_type": state.team.team_type,
                    "team_flags": state.team.team_flags,
                }

            if state.risk:
                project_result["risk"] = {
                    "token_risk": state.risk.token_risk,
                    "unlock_pressure": state.risk.unlock_pressure,
                    "risk_flags": state.risk.risk_flags,
                }

            if state.tokenomics:
                project_result["tokenomics"] = {
                    "vc_share": state.tokenomics.vc_share,
                    "team_share": state.tokenomics.team_share,
                    "unlock_penalty": state.tokenomics.unlock_penalty,
                }

            if state.errors:
                project_result["errors"] = [
                    {
                        "agent_name": err.agent_name,
                        "kind": err.kind,
                        "message": err.message,
                    }
                    for err in state.errors
                ]

            top_projects.append(project_result)

        logger.info(
            "api.run.completed",
            run_id=run_id,
            status=response.status,
            project_count=response.project_count,
        )

        return RunResponse(
            ok=True,
            data={
                "run_id": response.run_id,
                "status": response.status,
                "project_count": response.project_count,
                "scored_count": len([s for s in response.states if s.score is not None]),
                "error_count": len(response.errors),
                "top_score": response.top_score,
                "top_projects": top_projects,
            }
        )

    except Exception as e:
        logger.error(
            "api.run.failed",
            error=str(e),
            exc_info=True,
        )
        raise HTTPException(
            status_code=500,
            detail={
                "code": "PIPELINE_ERROR",
                "message": f"Pipeline execution failed: {str(e)}",
            }
        )
