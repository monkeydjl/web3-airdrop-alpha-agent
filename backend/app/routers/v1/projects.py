"""Projects Query Endpoint - 查询项目列表.

GET /api/v1/projects
- 分页查询项目列表
- 按 score/label 筛选
- 按 sector/stage 筛选
- 排序支持

Reference:
- ENGINEERING_ROADMAP.md §8.2 查询端点
"""

import json
from enum import StrEnum
from typing import Any

import structlog
from fastapi import APIRouter, HTTPException, Path, Query, Request
from pydantic import BaseModel, ConfigDict, Field

from app.auth import ROLE_ADMIN, get_current_user
from app.openapi import ERROR_RESPONSE_EXAMPLES, PROJECTS_LIST_RESPONSE_EXAMPLE
from app.repository import ProjectRepository
from app.services.user_scope import DEFAULT_USER

logger = structlog.get_logger(__name__)

router = APIRouter(tags=["projects"])

_REASONS_ZH_MAP: dict[str, str] = {
    # Positive reasons
    "strong airdrop signal": "明确的空投信号",
    "clear airdrop / points path": "清晰的空投/积分路径",
    "moderate airdrop signal": "中等强度的空投信号",
    "explicit airdrop mention": "官方明确提及空投",
    "verifiable task / points portal": "可验证的任务/积分门户",
    "multi-source evidence": "多源交叉证据支撑",
    "early narrative, high heat": "早期叙事，高热度",
    "early narrative": "早期叙事",
    "heated narrative, peak timing": "热门叙事，最佳时机",
    "peak narrative": "顶级叙事热度",
    "credible team": "团队背景可靠",
    "low competition": "赛道竞争较低",
    "active development / roadmap traction": "开发活跃/路线图扎实推进",
    "roadmap delivery looks aligned with shipping": "路线图交付与产品上线吻合",
    "strong public docs / social presence": "公开文档与社群活跃度高",
    "on-chain product / contract signal": "有链上产品/智能合约信号",
    "high evidence confidence": "证据置信度高",
    "tier-1 / high-quality funding": "顶级/高质量融资背景",
    "solid disclosed fundraising": "公开披露融资扎实",
    "recent funding signal": "近期有融资动态",
    "reputable vc backed": "知名风投机构参投",
    # Negative reasons
    "no airdrop signal": "无明显空投信号",
    "late narrative": "叙事热度滞后",
    "mature narrative, late timing": "叙事成熟，进入时机偏晚",
    "team risk: anonymous or prior failure": "团队风险：匿名或过往有失败记录",
    "elevated token structure risk": "代币经济学结构风险较高",
    "high token unlock pressure": "代币解锁抛压偏高",
    "high competition": "赛道竞争激烈",
    "weak execution signals (stale repo or no roadmap)": "执行信号偏弱（代码库停滞或无路线图）",
    "roadmap unclear vs shipping signals": "路线图交付进展不明确",
    "low transparency (thin docs/social)": "透明度较低（文档或社群匮乏）",
    "low data confidence": "数据置信度偏低",
    # Fallback pool reasons
    "airdrop signal detected": "检测到空投信号",
    "early-stage opportunity": "早期潜力机会",
    "mixed signals, monitor closely": "信号参差，保持密切观察",
    "insufficient standout signals": "缺乏显著优势信号",
    "weak overall signals": "整体信号偏弱",
    "limited airdrop evidence": "空投相关证据有限",
    # Eligibility gate reasons
    "token already launched with no verified follow-on airdrop path": "已发币且无可验证的后续空投路径",
    "team or official source explicitly disclaimed airdrop / token incentives": "团队或官方已明确否认空投/代币激励",
    "no verified testnet, points program, task portal, or explicit airdrop mention": "暂无可验证的测试网、积分体系、任务门户或官方空投声明",
    # Viability & Runway gate reasons
    "low_runway_risk": "存活率与跑道预警（极低存活率）",
    "low runway risk": "存活率与跑道预警（极低存活率）",
}


def _reason_to_zh(reason: str) -> str:
    if not reason:
        return ""
    text = str(reason).strip()
    return _REASONS_ZH_MAP.get(text.lower(), text)


def _parse_json_field(value: Any) -> Any:
    if value is None or value == "":
        return None
    if isinstance(value, (dict, list)):
        return value
    try:
        return json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return None


def _serialize_project_payload(project: dict[str, Any]) -> dict[str, Any]:
    narrative = _parse_json_field(project.get("narrative_json"))
    team = _parse_json_field(project.get("team_json"))
    risk = _parse_json_field(project.get("risk_json"))
    tokenomics = _parse_json_field(project.get("tokenomics_json"))

    if isinstance(team, dict) and "risk_level" not in team:
        team_score = team.get("team_score")
        if isinstance(team_score, (int, float)):
            from app.agents.team import score_to_risk_level

            team = {**team, "risk_level": score_to_risk_level(float(team_score))}

    reason = _parse_json_field(project.get("reason"))
    if reason is not None and not isinstance(reason, list):
        reason = [str(reason)]

    sub_scores = _parse_json_field(project.get("sub_scores"))
    weight_version = project.get("weight_version")

    from app.services.project_signals import funding_public_view, parse_meta

    meta = parse_meta(project.get("meta"))
    funding = funding_public_view(project.get("meta"))
    signals = meta.get("signals") if isinstance(meta.get("signals"), dict) else {}

    return {
        "id": project["id"],
        "name": project["name"],
        "url": project.get("url"),
        "sector": project.get("sector"),
        "stage": project.get("stage"),
        "score": project.get("score"),
        "label": project.get("label"),
        "confidence": project.get("confidence"),
        "reason": reason or [],
        "reason_zh": [_reason_to_zh(r) for r in (reason or [])],
        "narrative": narrative or {},
        "team": team or {},
        "risk": risk or {},
        "tokenomics": tokenomics or {},
        "source": project.get("source"),
        "funding": funding,
        "signals": signals,
        "funding_note": meta.get("funding_note"),
        "sub_scores": sub_scores if isinstance(sub_scores, dict) else {},
        "weight_version": weight_version or "v1.2",
        "veto": project.get("veto"),
        "skipped": bool(project.get("skipped", False)),
        "signal_consensus": project.get("signal_consensus"),
        "created_at": str(project["created_at"]) if project.get("created_at") is not None else None,
        "updated_at": str(project["updated_at"]) if project.get("updated_at") is not None else None,
    }


# ══════════════════════════════════════════════════════════════
# Enums and Models
# ══════════════════════════════════════════════════════════════


class SortBy(StrEnum):
    """排序字段枚举."""

    SCORE = "score"
    NAME = "name"
    CREATED_AT = "created_at"


class SortOrder(StrEnum):
    """排序顺序枚举."""

    ASC = "asc"
    DESC = "desc"


class ProjectListItem(BaseModel):
    """项目列表项（精简版）."""

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "id": "layerx-001",
                "name": "LayerX",
                "sector": "L2",
                "stage": "testnet",
                "score": 85,
                "label": "FARM",
                "confidence": 1.0,
            }
        }
    )

    id: str
    name: str
    sector: str | None = None
    stage: str | None = None
    score: int | None = None
    label: str | None = None
    confidence: float | None = None


class ProjectsResponse(BaseModel):
    """项目列表响应."""

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "ok": True,
                "data": {
                    "projects": [{"id": "layerx-001", "name": "LayerX", "sector": "L2", "score": 85, "label": "FARM"}],
                    "total": 1,
                    "page": 1,
                    "page_size": 20,
                },
            }
        }
    )

    ok: bool = Field(True, description="请求是否成功")
    data: dict[str, Any] = Field(..., description="响应数据")


# ══════════════════════════════════════════════════════════════
# Endpoints
# ══════════════════════════════════════════════════════════════


@router.get(
    "/projects",
    response_model=ProjectsResponse,
    responses={
        200: {
            "description": "项目列表查询成功",
            "content": {"application/json": {"example": PROJECTS_LIST_RESPONSE_EXAMPLE}},
        }
    },
    summary="查询项目列表",
    description=(
        "分页查询项目列表，支持按 score/label/sector 筛选和排序。\n\n"
        "## 查询参数\n\n"
        "- **分页**: page (页码), page_size (每页数量, 最大 500)\n"
        "- **筛选**: label (FARM/WATCH/IGNORE), sector, stage, min_score\n"
        "- **排序**: sort_by (score/name/created_at), sort_order (asc/desc)\n\n"
        "## 示例\n\n"
        "```\n"
        "GET /api/v1/projects?label=FARM&min_score=70&sort_by=score&sort_order=desc\n"
        "```\n"
    ),
)
def list_projects(
    req: Request,
    page: int = Query(1, ge=1, description="页码（从1开始）"),
    page_size: int = Query(20, ge=1, le=500, description="每页数量"),
    label: str | None = Query(None, description="按标签筛选 (FARM/WATCH/IGNORE)"),
    sector: str | None = Query(None, description="按赛道筛选"),
    stage: str | None = Query(None, description="按阶段筛选"),
    min_score: int | None = Query(None, ge=0, le=100, description="最低分数"),
    sort_by: SortBy = Query(SortBy.SCORE, description="排序字段"),
    sort_order: SortOrder = Query(SortOrder.DESC, description="排序顺序"),
    auto_discovered: bool | None = Query(None, description="筛选自动发现项目 (true) 或手动录入 (false)"),
    veto: str | None = Query(
        None,
        description="按资格否决筛选（no_participation_path=缺参与路径、already_launched=已发币）",
    ),
    user_id: str | None = Query(None, description="用户 ID（匿名时走 default）"),
    curated: bool = Query(False, description="仅返回满足精选门槛的项目（评分/置信度/近90天活动/参与路径）"),
    zero_cost_only: bool = Query(False, description="仅返回零资金成本/纯测试网项目（保本优先）"),
    personalized: bool = Query(False, description="是否启用基于用户偏好的个性化加权排序（V3 Memory，Roadmap §25.5.3）"),
) -> ProjectsResponse:
    """查询项目列表（分页 + 筛选 + 排序，数据来自 projects 表）.

    Args:
        page: 页码
        page_size: 每页数量
        label: 标签筛选
        sector: 赛道筛选
        stage: 阶段筛选
        min_score: 最低分数
        sort_by: 排序字段
        sort_order: 排序顺序

    Returns:
        ProjectsResponse 包含项目列表
    """
    current_user = get_current_user(req)
    if current_user["role"] == ROLE_ADMIN:
        uid = user_id or (current_user["user_id"] if current_user["user_id"] != "anonymous" else DEFAULT_USER)
    elif current_user["user_id"] != "anonymous":
        uid = user_id or current_user["user_id"]
    else:
        uid = user_id or DEFAULT_USER
    effective_user_id = uid.strip()

    logger.info(
        "api.projects.list",
        page=page,
        page_size=page_size,
        label=label,
        sector=sector,
        stage=stage,
        min_score=min_score,
        sort_by=sort_by,
        sort_order=sort_order,
        auto_discovered=auto_discovered,
        user_id=effective_user_id,
        zero_cost_only=zero_cost_only,
    )

    # Query from database
    try:
        repo = ProjectRepository()
        db_projects, total = repo.list_projects(
            page=page,
            page_size=page_size,
            label=label,
            sector=sector,
            stage=stage,
            min_score=min_score,
            sort_by=sort_by.value,
            sort_order=sort_order.value,
            auto_discovered=auto_discovered,
            veto=veto,
            skip_user_id=effective_user_id,
            curated=curated,
            zero_cost_only=zero_cost_only,
        )

        # Convert to response format — include discovery metadata for Dashboard
        projects = []
        for p in db_projects:
            raw_reason = _parse_json_field(p.get("reason"))
            reasons_list = raw_reason if isinstance(raw_reason, list) else ([str(raw_reason)] if raw_reason else [])
            reasons_zh = [_reason_to_zh(r) for r in reasons_list] if reasons_list else []
            projects.append(
                {
                    "id": p["id"],
                    "name": p["name"],
                    "sector": p["sector"],
                    "stage": p["stage"],
                    "score": p["score"],
                    "label": p["label"],
                    "confidence": p["confidence"],
                    "reason": reasons_list,
                    "reason_zh": reasons_zh,
                    "discovery_source": p.get("discovery_source"),
                    "discovered_at": str(p["discovered_at"]) if p.get("discovered_at") else None,
                    "auto_discovered": bool(p.get("auto_discovered", False)),
                    "veto": p.get("veto"),
                    "skipped": bool(p.get("skipped", False)),
                    "signal_consensus": p.get("signal_consensus"),
                }
            )

        if personalized and sort_by == SortBy.SCORE:
            from app.services.user_memory import UserProfileMemoryService

            user_svc = UserProfileMemoryService()
            profile = user_svc.infer_user_profile(effective_user_id)
            projects = user_svc.personalize_projects(projects, profile)

    except Exception as e:
        # 此前这里吞掉所有异常返回 projects=[], total=0 且 200 OK：调用方
        # 无法区分"真的没有项目"与"数据库挂了"，对前端是静默失败，且
        # export_projects 复用本层数据时会把 DB 故障误当成空结果。真实错误
        # 必须以 5xx 暴露，与同文件 get_project 的处理保持一致。异常原文只
        # 进日志、响应给通用码（防 DSN/连接串泄露）。
        logger.error(
            "api.projects.list_failed",
            error=str(e),
            exc_info=True,
        )
        raise HTTPException(
            status_code=500, detail={"code": "INTERNAL_ERROR", "message": "Failed to list projects"}
        ) from e

    return ProjectsResponse(
        ok=True,
        data={
            "projects": projects,
            "total": total,
            "page": page,
            "page_size": page_size,
            "filters": {
                "label": label,
                "sector": sector,
                "stage": stage,
                "min_score": min_score,
                "auto_discovered": auto_discovered,
                "veto": veto,
                "zero_cost_only": zero_cost_only,
            },
            "sort": {
                "by": sort_by.value,
                "order": sort_order.value,
            },
        },
    )


@router.get(
    "/projects/digest",
    summary="生成每日/每周 Alpha 投研周报合辑",
    description="纯规则确定性批量聚合优质 FARM 项目、最新大额融资、零成本测试网新机会与防 PUA 避坑清单，返回 Markdown 研报与核心指标摘要。",
)
def get_projects_digest(
    window_days: int = Query(7, ge=1, le=90, description="时间窗口（天）"),
    min_score: float = Query(70.0, ge=0.0, le=100.0, description="入选最低分数线"),
    limit: int = Query(15, ge=1, le=50, description="精选项目数量上限"),
) -> dict[str, Any]:
    """生成每日/每周 Alpha 投研周报."""
    from app.services.alpha_digest import generate_alpha_digest

    try:
        digest = generate_alpha_digest(
            window_days=window_days,
            min_score=min_score,
            limit=limit,
        )
        return digest
    except Exception as e:
        logger.error("api.projects.digest_failed", error=str(e), exc_info=True)
        raise HTTPException(
            status_code=500, detail={"code": "INTERNAL_ERROR", "message": f"Failed to generate alpha digest: {e}"}
        ) from e


@router.get(
    "/projects/{project_id}",
    response_model=ProjectsResponse,
    responses={
        404: {
            "description": "项目未找到",
            "content": {"application/json": {"examples": {"not_found": ERROR_RESPONSE_EXAMPLES["not_found"]}}},
        }
    },
    summary="获取项目详情",
    description=(
        "根据项目 ID 获取完整项目信息（含子评分、融资、信号明细）。\n\n"
        "项目不存在返回 404。\n\n"
        "## 示例\n\n"
        "```\n"
        "GET /api/v1/projects/layerx-l2-001\n"
        "```\n"
    ),
)
def get_project(
    project_id: str = Path(..., description="项目 ID"),
) -> dict[str, Any]:
    """获取单个项目详情.

    Args:
        project_id: 项目 ID

    Returns:
        ProjectsResponse 包含项目详情

    Raises:
        HTTPException: 项目不存在
    """
    logger.info(
        "api.projects.get",
        project_id=project_id,
    )

    # Query from database
    try:
        repo = ProjectRepository()
        project = repo.get_by_id(project_id)

        if not project:
            raise HTTPException(
                status_code=404, detail={"code": "NOT_FOUND", "message": f"Project {project_id} not found"}
            )

        return {
            "ok": True,
            "data": {
                "project": _serialize_project_payload(project),
            },
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(
            "api.projects.get_failed",
            project_id=project_id,
            error=str(e),
            exc_info=True,
        )
        raise HTTPException(
            status_code=500, detail={"code": "INTERNAL_ERROR", "message": "Failed to retrieve project"}
        ) from e


@router.post(
    "/projects/{project_id}/evaluate",
    response_model=ProjectsResponse,
    responses={
        404: {
            "description": "项目未找到",
            "content": {"application/json": {"examples": {"not_found": ERROR_RESPONSE_EXAMPLES["not_found"]}}},
        }
    },
    summary="即时全链路重新评估项目",
    description="对指定项目触发即时 8 维综合评估、存活/跑道门禁、防 PUA 退出检测、多源共识加成与演化快照落库，并更新关联的机会与决策。",
)
async def evaluate_project(
    project_id: str = Path(..., description="项目 ID"),
) -> dict[str, Any]:
    """即时全链路重新评估项目."""
    try:
        from app.services.project_evaluation import evaluate_single_project

        updated_project = await evaluate_single_project(project_id)
        return {
            "ok": True,
            "data": {
                "project": _serialize_project_payload(updated_project),
            },
        }
    except ValueError as e:
        raise HTTPException(
            status_code=404, detail={"code": "NOT_FOUND", "message": f"Project {project_id} not found"}
        ) from e
    except HTTPException:
        raise
    except Exception as e:
        logger.error("api.projects.evaluate_failed", project_id=project_id, error=str(e), exc_info=True)
        raise HTTPException(
            status_code=500, detail={"code": "INTERNAL_ERROR", "message": f"Failed to evaluate project: {e}"}
        ) from e


@router.get(
    "/projects/{project_id}/dossier",
    response_model=ProjectsResponse,
    responses={
        404: {
            "description": "项目未找到",
            "content": {"application/json": {"examples": {"not_found": ERROR_RESPONSE_EXAMPLES["not_found"]}}},
        }
    },
    summary="生成项目 Alpha 深度投研研报",
    description="一站式聚合基本面、VC 融资跑道、防 PUA 摩擦预警、多源共识印证、多钱包策略与水龙头任务清单，生成 100% 确定性零 Token 投研 Markdown 研报与核心指标摘要。",
)
def get_project_dossier(
    project_id: str = Path(..., description="项目 ID"),
) -> dict[str, Any]:
    """生成项目 Alpha 深度投研研报."""
    try:
        from app.services.alpha_dossier import generate_alpha_dossier

        dossier = generate_alpha_dossier(project_id)
        return {
            "ok": True,
            "data": dossier,
        }
    except ValueError as e:
        raise HTTPException(
            status_code=404, detail={"code": "NOT_FOUND", "message": f"Project {project_id} not found"}
        ) from e
    except HTTPException:
        raise
    except Exception as e:
        logger.error("api.projects.dossier_failed", project_id=project_id, error=str(e), exc_info=True)
        raise HTTPException(
            status_code=500, detail={"code": "INTERNAL_ERROR", "message": f"Failed to generate alpha dossier: {e}"}
        ) from e



@router.get(
    "/projects/{project_id}/multi-wallet-strategy",
    response_model=ProjectsResponse,
    responses={
        404: {
            "description": "项目未找到",
            "content": {"application/json": {"examples": {"not_found": ERROR_RESPONSE_EXAMPLES["not_found"]}}},
        }
    },
    summary="获取项目多钱包参与建议",
    description="根据项目女巫难度、阶段、成本分级与参与路径，输出多钱包参与梯度建议、资金预估与防女巫隔离规范（US-019 / W12-01）。",
)
def get_project_multi_wallet_strategy(
    project_id: str = Path(..., description="项目 ID"),
) -> dict[str, Any]:
    """获取单项目多钱包参与建议 (US-019)."""
    try:
        repo = ProjectRepository()
        project = repo.get_by_id(project_id)
        if not project:
            raise HTTPException(
                status_code=404, detail={"code": "NOT_FOUND", "message": f"Project {project_id} not found"}
            )

        from app.services.multi_wallet_strategy import generate_multi_wallet_strategy

        strategy = generate_multi_wallet_strategy(project)
        return {
            "ok": True,
            "data": strategy.to_dict(),
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(
            "api.projects.multi_wallet_strategy_failed",
            project_id=project_id,
            error=str(e),
            exc_info=True,
        )
        raise HTTPException(
            status_code=500, detail={"code": "INTERNAL_ERROR", "message": "Failed to generate multi-wallet strategy"}
        ) from e


@router.get(
    "/projects/{project_id}/timeline",
    response_model=ProjectsResponse,
    responses={
        404: {
            "description": "项目未找到",
            "content": {"application/json": {"examples": {"not_found": ERROR_RESPONSE_EXAMPLES["not_found"]}}},
        }
    },
    summary="获取项目演化时间轴与历史指标",
    description="查询项目跨 run 演化时间序列、阶段迁移、评分走势与历史波动率指标（Roadmap §24.3 / W12-02）。",
)
def get_project_timeline(
    project_id: str = Path(..., description="项目 ID"),
    limit: int = Query(50, ge=1, le=200, description="最大快照数"),
) -> dict[str, Any]:
    """获取单项目演化时间轴 (Roadmap §24.3 / W12-02)."""
    try:
        from app.services.project_memory import ProjectEvolutionService

        svc = ProjectEvolutionService()
        evolution = svc.get_project_timeline(project_id, limit=limit)
        if not evolution:
            raise HTTPException(
                status_code=404, detail={"code": "NOT_FOUND", "message": f"Project {project_id} not found"}
            )
        return {
            "ok": True,
            "data": evolution.to_dict(),
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(
            "api.projects.timeline_failed",
            project_id=project_id,
            error=str(e),
            exc_info=True,
        )
        raise HTTPException(
            status_code=500, detail={"code": "INTERNAL_ERROR", "message": "Failed to fetch project timeline"}
        ) from e


@router.get(
    "/projects/{project_id}/signals-consensus",
    summary="获取项目多源信号交叉印证与共识",
    description="聚合 Telegram、Farcaster、GitHub、RSS 等免费源，计算 14 天信号共识度与免 Token 推荐加成。",
)
def get_project_signals_consensus(
    project_id: str = Path(..., description="项目 ID"),
    window_days: int = Query(14, ge=1, le=90, description="时间窗口（天）"),
) -> dict[str, Any]:
    """获取项目多源信号交叉印证与共识度."""
    try:
        repo = ProjectRepository()
        project = repo.get_by_id(project_id)
        if not project:
            raise HTTPException(
                status_code=404, detail={"code": "NOT_FOUND", "message": f"Project {project_id} not found"}
            )
        from app.services.signal_correlation import correlate_signals_for_project

        conn = repo._get_conn()
        try:
            consensus = correlate_signals_for_project(conn, project_id, window_days=window_days)
        finally:
            if repo._should_close():
                conn.close()
        return {
            "ok": True,
            "data": consensus,
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error("api.projects.signals_consensus_failed", project_id=project_id, error=str(e), exc_info=True)
        raise HTTPException(
            status_code=500, detail={"code": "INTERNAL_ERROR", "message": "Failed to get signals consensus"}
        ) from e


