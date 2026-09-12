"""AI project chat endpoint — grounded multi-turn Q&A (追问对话).

与 ai_brief.py 同一套响应约定：`{ok, data}` 包裹、降级原因透传、
异常原文只进日志不进响应体（可能带密钥/DSN）。
"""

from __future__ import annotations

from typing import Any, Literal

import structlog
from fastapi import APIRouter, HTTPException, Path
from pydantic import BaseModel

from app.config import settings
from app.repository import ProjectRepository
from app.services.ai_chat import (
    CHAT_MAX_MESSAGE_CHARS,
    CHAT_MAX_MESSAGES,
    generate_chat_reply,
)

logger = structlog.get_logger(__name__)
router = APIRouter(tags=["ai"])


class ChatMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str


class AiChatRequest(BaseModel):
    messages: list[ChatMessage]


def _validate_messages(messages: list[ChatMessage]) -> str | None:
    """返回第一条校验失败的原因；合法返回 None。

    校验放在路由层而不是 Pydantic 字段约束：空列表、条数、末条角色、
    空白内容都是跨字段的语义约束，放字段上会散成多个 422，前端没法
    用统一的「INVALID_MESSAGES」分支处理。
    """
    if not messages:
        return "messages 不能为空"
    if len(messages) > CHAT_MAX_MESSAGES:
        return f"messages 最多 {CHAT_MAX_MESSAGES} 条"
    for m in messages:
        if not m.content.strip():
            return "消息内容不能为空"
        if len(m.content) > CHAT_MAX_MESSAGE_CHARS:
            return f"单条消息最多 {CHAT_MAX_MESSAGE_CHARS} 字"
    if messages[-1].role != "user":
        return "最后一条消息必须是用户提问"
    return None


@router.post("/projects/{project_id}/ai-chat")
async def project_ai_chat(
    req: AiChatRequest,
    project_id: str = Path(..., description="项目 ID"),
) -> dict[str, Any]:
    """Multi-turn Q&A about a project, grounded on its stored score factors.

    会话历史由前端持有并随请求传入（最近若干轮），服务端无状态。
    纯 LLM 功能，无规则引擎回退；降级时 `reply` 为 null 并给出 `degraded_reason`。
    """
    # 校验先于查库：请求不合法与项目存不存在无关，也不必为坏请求碰数据库。
    error = _validate_messages(req.messages)
    if error:
        raise HTTPException(
            status_code=400,
            detail={"code": "INVALID_MESSAGES", "message": error},
        )

    repo = ProjectRepository()
    project = repo.get_by_id(project_id)
    if not project:
        raise HTTPException(
            status_code=404,
            detail={"code": "NOT_FOUND", "message": f"Project {project_id} not found"},
        )

    history = [{"role": m.role, "content": m.content} for m in req.messages]
    try:
        result = await generate_chat_reply(dict(project), history)
    except Exception as e:
        # 异常原文只进日志、不进响应体（可能带密钥/DSN），与 ai_brief 同策略。
        logger.error("ai_chat.failed", project_id=project_id, error=str(e), exc_info=True)
        raise HTTPException(
            status_code=500,
            detail={"code": "CHAT_FAILED", "message": "Failed to generate chat reply"},
        ) from e

    return {
        "ok": True,
        "data": {
            "project_id": project_id,
            "project_name": project.get("name"),
            "reply": result.get("reply"),
            # llm_disabled / budget_exceeded / llm_error；reply 非 null 时为 None。
            "degraded_reason": result.get("degraded_reason"),
            "llm_available": settings.is_llm_enabled,
        },
    }
