"""OpenAPI documentation customization and examples.

Provides example data and custom schema for OpenAPI documentation.
"""

from typing import Any

from fastapi import FastAPI

# ══════════════════════════════════════════════════════════════
# Request Examples
# ══════════════════════════════════════════════════════════════

RUN_REQUEST_EXAMPLES: dict[str, Any] = {
    "single_project": {
        "summary": "单个项目评分",
        "description": "评分单个具有完整信号的项目",
        "value": {
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
        },
    },
    "multiple_projects": {
        "summary": "批量项目评分",
        "description": "一次评分多个不同赛道的项目",
        "value": {
            "projects": [
                {
                    "name": "LayerX",
                    "sector": "L2",
                    "stage": "testnet",
                    "has_testnet": True,
                    "has_points_program": True,
                    "no_token_yet": True,
                },
                {
                    "name": "RestakeDAO",
                    "sector": "Restaking",
                    "stage": "mainnet",
                    "has_points_program": True,
                    "no_token_yet": True,
                },
                {
                    "name": "GameFi Protocol",
                    "sector": "Gaming",
                    "stage": "ideation",
                    "has_testnet": False,
                },
            ],
            "enable_llm": False,
        },
    },
    "minimal_project": {
        "summary": "最小项目信息",
        "description": "仅提供项目名称进行评分",
        "value": {
            "projects": [
                {
                    "name": "MinimalProject",
                }
            ],
            "enable_llm": False,
        },
    },
}


# ══════════════════════════════════════════════════════════════
# Response Examples
# ══════════════════════════════════════════════════════════════

RUN_RESPONSE_EXAMPLE = {
    "ok": True,
    "data": {
        "run_id": "api-run-20260709-120000",
        "status": "completed",
        "project_count": 1,
        "scored_count": 1,
        "error_count": 0,
        "top_score": 85,
        "top_projects": [
            {
                "id": "layerx-l2-001",
                "name": "LayerX",
                "sector": "L2",
                "stage": "testnet",
                "score": 85,
                "label": "FARM",
                "confidence": 1.0,
                "reason": [
                    "strong airdrop signal (testnet + points + no token)",
                    "early narrative timing",
                    "credible team (tier-1 backed)",
                    "acceptable risk profile",
                ],
                "narrative": {"sector": "L2", "stage": "growth", "heat_score": 0.94, "timing": "early"},
                "team": {"team_score": 0.75, "team_type": "semi_anon", "team_flags": ["tier-1 vc backed"]},
                "risk": {"token_risk": 0.37, "unlock_pressure": "medium", "risk_flags": ["risk estimate uncertain"]},
                "tokenomics": {"vc_share": 0.30, "team_share": 0.25, "unlock_penalty": 0.35},
            }
        ],
    },
}


PROJECTS_LIST_RESPONSE_EXAMPLE = {
    "ok": True,
    "data": {
        "projects": [
            {
                "id": "layerx-001",
                "name": "LayerX",
                "sector": "L2",
                "stage": "testnet",
                "score": 85,
                "label": "FARM",
                "confidence": 1.0,
            },
            {
                "id": "restake-002",
                "name": "RestakeDAO",
                "sector": "Restaking",
                "stage": "mainnet",
                "score": 78,
                "label": "FARM",
                "confidence": 1.0,
            },
        ],
        "total": 2,
        "page": 1,
        "page_size": 20,
        "filters": {"label": "FARM", "sector": None, "stage": None, "min_score": 65},
        "sort": {"by": "score", "order": "desc"},
    },
}


# ══════════════════════════════════════════════════════════════
# Error Response Examples
# ══════════════════════════════════════════════════════════════

ERROR_RESPONSE_EXAMPLES = {
    "validation_error": {
        "summary": "输入验证错误",
        "value": {
            "detail": [
                {
                    "type": "missing",
                    "loc": ["body", "projects"],
                    "msg": "Field required",
                }
            ]
        },
    },
    "pipeline_error": {
        "summary": "Pipeline 执行错误",
        "value": {
            "ok": False,
            "error": {"code": "PIPELINE_ERROR", "message": "Pipeline execution failed: unexpected error"},
        },
    },
    "not_found": {
        "summary": "项目未找到",
        "value": {"detail": {"code": "NOT_FOUND", "message": "Project abc-123 not found"}},
    },
}


# ══════════════════════════════════════════════════════════════
# Custom OpenAPI Schema
# ══════════════════════════════════════════════════════════════


def customize_openapi_schema(app: FastAPI) -> dict[str, Any]:
    """自定义 OpenAPI schema.

    Args:
        app: FastAPI 应用实例

    Returns:
        自定义后的 OpenAPI schema
    """
    if app.openapi_schema:
        return app.openapi_schema

    from fastapi.openapi.utils import get_openapi

    openapi_schema = get_openapi(
        title=app.title,
        version=app.version,
        description=app.description,
        routes=app.routes,
        tags=app.openapi_tags,
        servers=[
            {
                "url": "http://localhost:8002",
                "description": "本地开发环境",
            },
            {
                "url": "https://api.example.com",
                "description": "生产环境（示例）",
            },
        ],
        contact=app.contact,
        license_info=app.license_info,
    )

    # Add security schemes (for future authentication)
    openapi_schema["components"]["securitySchemes"] = {
        "ApiKeyAuth": {
            "type": "apiKey",
            "in": "header",
            "name": "X-API-Key",
            "description": "API Key 认证（V2 实现）",
        }
    }

    # Add custom info
    openapi_schema["info"]["x-logo"] = {
        "url": "https://fastapi.tiangolo.com/img/logo-margin/logo-teal.png",
        "altText": "Web3 Airdrop Alpha System",
    }

    app.openapi_schema = openapi_schema
    return openapi_schema
