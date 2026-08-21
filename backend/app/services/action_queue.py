"""跨项目「今日行动」队列。

评分决策引擎会给出上百个 FARM/WATCH 项目，但参与清单此前只存在于**单个项目
详情页** —— 用户必须逐个点进去才看得到任务，没有任何视图回答「今天该做什么」。
实测结果是：162 个 FARM 项目，watchlist / interactions / feedback 全为 0 条，
即评分结果一条都没被跟进。

本模块把已有的 `generate_participation_tasks()` 跨项目聚合，输出一份有限、
有序、可执行的清单。它**不产生新的评分**，只是排序与筛选既有结论。

设计约束：
- 复用参与清单生成器，不重写任务规则（单一事实来源）
- 完成状态复用 `interactions` 表：用户在这里标「已做」= 写一条交互记录，
  参与复盘页能看到同一份数据，不引入第二套状态
- 只读聚合：本模块不写库

Reference: docs/GLOSSARY.md §2（评分决策引擎 / 规则引擎边界）
"""

from __future__ import annotations

from typing import Any

from app.services.participation_tasks import generate_participation_tasks
from app.services.project_signals import signals_view

# 只对这两类标签排行动 —— IGNORE 的建议本身就是「别投入时间」。
ACTIONABLE_LABELS = ("FARM", "WATCH")

# 标签权重：FARM 优先于 WATCH。
_LABEL_BONUS = {"FARM": 12.0, "WATCH": 0.0}

# 只有这些类别算「真正推进空投资格」的动作。track/social 类偏辅助，
# 不应该挤占今日名额（track-log-interaction 每个项目都有，否则清单会被它刷满）。
_ADVANCING_CATEGORIES = ("official", "testnet", "mainnet", "research", "risk", "dev")


def _priority_weight(priority: int) -> float:
    """P1 最紧急。权重随优先级递减，P4+ 几乎不进今日清单。"""
    return max(0.0, 40.0 - 10.0 * (int(priority) - 1))


def score_action(
    *,
    project_score: float,
    label: str,
    priority: int,
    required: bool,
    already_engaged: bool,
    watchlisted: bool,
) -> float:
    """给单条行动打排序分。分数越高越该今天做。

    刻意保持线性可解释：用户问「为什么这条排第一」时能直接说清，
    而不是"模型觉得"。这里不复用评分决策引擎的权重（那是项目价值，
    与"今天该做哪一步"是两回事，混用会让两边都难解释）。
    """
    total = _priority_weight(priority)
    total += _LABEL_BONUS.get(str(label).upper(), 0.0)
    # 项目本身分数（0-100）折算，占比刻意小于优先级：
    # 高分项目的 P3 任务不该压过中分项目的 P1 必做项。
    total += float(project_score or 0) * 0.15
    if required:
        total += 15.0
    if watchlisted:
        total += 8.0  # 用户已明确表达兴趣
    if already_engaged:
        total -= 25.0  # 已参与过：降权但不剔除（可能还有未做完的步骤）
    return round(total, 2)


def _round_robin(candidates: list[dict[str, Any]], *, limit: int) -> list[dict[str, Any]]:
    """按项目轮转取样，保证今日清单横向覆盖多个项目。

    candidates 必须已按 rank_score 降序排好；本函数只做分配，不改变相对优劣：
    第一轮每个项目出 1 条（项目间仍按其最高分行动的顺序），第二轮再补第 2 条。
    """
    if limit <= 0:
        return []

    by_project: dict[str, list[dict[str, Any]]] = {}
    order: list[str] = []
    for c in candidates:
        pid = str(c["project_id"])
        if pid not in by_project:
            by_project[pid] = []
            order.append(pid)
        by_project[pid].append(c)

    picked: list[dict[str, Any]] = []
    round_index = 0
    while len(picked) < limit:
        added_this_round = False
        for pid in order:
            if len(picked) >= limit:
                break
            bucket = by_project[pid]
            if round_index < len(bucket):
                picked.append(bucket[round_index])
                added_this_round = True
        if not added_this_round:
            break  # 所有项目都取空了
        round_index += 1
    return picked


def build_action_queue(
    projects: list[dict[str, Any]],
    *,
    engaged_project_ids: set[str] | None = None,
    watchlisted_project_ids: set[str] | None = None,
    limit: int = 5,
    per_project_limit: int = 2,
    include_engaged: bool = False,
) -> dict[str, Any]:
    """聚合出今日行动清单。

    Args:
        projects: 项目行（原始存储形态即可，内部会走 signals_view 展平信号）
        engaged_project_ids: 已有交互记录的项目（默认从清单中排除）
        watchlisted_project_ids: 已收藏的项目（加权）
        limit: 返回的行动条数上限
        per_project_limit: 同一项目最多贡献几条，避免单个项目霸屏
        include_engaged: 是否包含已参与过的项目
    """
    engaged = engaged_project_ids or set()
    watched = watchlisted_project_ids or set()

    candidates: list[dict[str, Any]] = []
    considered = 0
    skipped_engaged = 0

    for row in projects:
        label = str(row.get("label") or "").upper()
        if label not in ACTIONABLE_LABELS:
            continue

        pid = str(row.get("id") or "")
        if not pid:
            continue

        is_engaged = pid in engaged
        if is_engaged and not include_engaged:
            skipped_engaged += 1
            continue

        considered += 1
        # 必须走 signals_view：信号存在 meta.signals，不展平会让任务退化为通用套话
        checklist = generate_participation_tasks(signals_view(row))
        project_score = float(row.get("score") or 0)

        picked = 0
        for task in checklist.get("tasks", []):
            if picked >= per_project_limit:
                break
            if task.get("category") not in _ADVANCING_CATEGORIES:
                continue

            candidates.append(
                {
                    "project_id": pid,
                    "project_name": row.get("name"),
                    "project_score": project_score,
                    "label": label,
                    "sector": row.get("sector"),
                    "stage": row.get("stage"),
                    "url": row.get("url"),
                    "task_id": task.get("id"),
                    "title": task.get("title"),
                    "description": task.get("description"),
                    "category": task.get("category"),
                    "category_zh": task.get("category_zh"),
                    "priority": task.get("priority"),
                    "effort": task.get("effort"),
                    "effort_zh": task.get("effort_zh"),
                    "why": task.get("why"),
                    "action_hint": task.get("action_hint"),
                    "link": task.get("link") or row.get("url"),
                    "required": bool(task.get("required")),
                    "already_engaged": is_engaged,
                    "watchlisted": pid in watched,
                    "rank_score": score_action(
                        project_score=project_score,
                        label=label,
                        priority=int(task.get("priority") or 3),
                        required=bool(task.get("required")),
                        already_engaged=is_engaged,
                        watchlisted=pid in watched,
                    ),
                }
            )
            picked += 1

    # 排序：分高优先；同分时 project_id+task_id 保证结果稳定（否则同分行会随
    # 字典顺序抖动，用户每次刷新看到的顺序都不一样）。
    candidates.sort(key=lambda c: (-c["rank_score"], str(c["project_id"]), str(c["task_id"])))

    # 轮转取样：先给每个项目取第 1 条，再回头取第 2 条。
    # 否则纯按分数排会让 5 个名额被 2~3 个高分项目占满（实测 limit=5 时只覆盖
    # 3 个项目），今日清单变成"盯着一个项目做"，失去横向铺开的意义。
    items = _round_robin(candidates, limit=max(0, int(limit)))

    return {
        "items": items,
        "summary": {
            "returned": len(items),
            "candidates": len(candidates),
            "projects_considered": considered,
            "projects_skipped_engaged": skipped_engaged,
            "required_count": sum(1 for c in items if c["required"]),
            "projects_in_queue": len({c["project_id"] for c in items}),
        },
        "notes": [
            "清单由参与清单规则跨项目聚合而成，非官方承诺；请以项目方最新公告为准。",
            "标记「已做」会写入你的交互记录，可在参与复盘页查看与补充成本/收益。",
        ],
    }
