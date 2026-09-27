"""Simulated-data marking utilities (模拟数据打标工具).

审计背景（docs/EXPANSION_AUDIT_REPORT.md）：expansion v1~v7 批次中大量服务
输出硬编码或启发式生成的「看起来实时」的数据。与 seed 项目不同（seed 在
projects.source 里有显式 'seed' 标记、前端有「种子数据」角标），这些端点的
输出此前无任何标记，用户无法分辨真实计算与占位演示。

本模块提供统一契约：

- ``DATA_QUALITY_REAL`` / ``DATA_QUALITY_SIMULATED``：字段取值常量。
- ``simulated_meta()``：构造 ``data_quality`` 元数据块，含质量档、中文说明与
  可选备注。
- ``mark_simulated(payload, ...)``：把元数据块写入 dict 响应体。
- ``mark_simulated_list_response(...)``：包装「顶层为列表」的响应
  （``{"ok": True, "data": [...]}`` → ``{"ok": True, "data_quality": {...}, "data": [...]}``）。

约定：**新增扩展端点凡是返回非真实计算 / 非真实 I/O 的数据，必须打标**；
前端通过 ``data_quality.quality === "simulated"`` 渲染「模拟数据」角标
（``frontend-next/components/SimulatedDataBadge.tsx``）。
"""

from __future__ import annotations

from typing import Any

DATA_QUALITY_REAL = "real"
DATA_QUALITY_SIMULATED = "simulated"

"""默认说明文案：直接出现在 UI 角标的 tooltip 中。"""
DEFAULT_SIMULATED_NOTE = "本数据为演示/启发式生成，非实时链上或市场数据，请勿作为真实决策依据。"


def simulated_meta(note: str | None = None) -> dict[str, str]:
    """构造一个 ``data_quality`` 元数据块。

    Args:
        note: 该端点的具体占位说明；为空时使用通用默认文案。

    Returns:
        含 quality / note 两个字段的 dict。
    """
    return {
        "quality": DATA_QUALITY_SIMULATED,
        "note": note or DEFAULT_SIMULATED_NOTE,
    }


def mark_simulated(
    payload: dict[str, Any],
    note: str | None = None,
) -> dict[str, Any]:
    """在响应体顶层写入 ``data_quality`` 标记（in-place 修改并返回）。

    对 ``{...}``、``{"ok": True, "data": {...}}`` 两种形态都适用——
    标记统一放响应体顶层，前端只需看一层。
    """
    payload["data_quality"] = simulated_meta(note)
    return payload


def mark_simulated_list_response(
    items: list[dict[str, Any]] | list[Any],
    note: str | None = None,
    **extra: Any,
) -> dict[str, Any]:
    """包装「data 顶层为列表」的响应并打上模拟标记。

    形态：``{"ok": True, "data_quality": {...}, "data": [...], **extra}``。
    """
    resp: dict[str, Any] = {
        "ok": True,
        "data_quality": simulated_meta(note),
        "data": items,
    }
    resp.update(extra)
    return resp


def is_simulated(payload: dict[str, Any]) -> bool:
    """读取响应体的质量档位（后端测试与前端对齐用）。"""
    dq = payload.get("data_quality")
    if not isinstance(dq, dict):
        return False
    return bool(dq.get("quality") == DATA_QUALITY_SIMULATED)
