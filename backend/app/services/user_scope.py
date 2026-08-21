"""用户归属过滤的统一口径。

背景（实测确认，非推测）：两张用户关联表写入 `user_id` 的方式**不一致**——

  - `POST /api/v1/interactions` 直接落 `body.user_id`，不传即写入 **NULL**
  - `POST /api/v1/watchlist/{id}` 走 `body.user_id or "default"`，不传写入 **'default'**

于是"查某个用户的记录"没有单一正确写法：
  - 只用 `user_id = 'default'` → 漏掉 interactions 里那批 NULL（表现为用户刚
    标记过的项目仍反复出现在今日行动里）
  - 无条件加 `OR user_id IS NULL` → 多用户启用后会把归属未标注的历史数据
    算进**每个**用户名下

本模块把这个判断集中到一处，避免各路由各写一套逐渐漂移。

Reference: ADR-008-user-system.md §3 行级数据隔离
"""

from __future__ import annotations

from typing import Any

DEFAULT_USER = "default"

# 允许查询的表白名单。表名会拼进 SQL，必须限定取值，不接受外部输入。
_ALLOWED_TABLES = ("interactions", "watchlist", "feedback")


def _scope_clause(user_id: str) -> str:
    """归属条件片段。

    查默认用户时把 `user_id IS NULL` 视为"归属未标注的本机数据"一并纳入
    （单用户 MVP 下这些就是用户自己的记录）；查具体用户时严格匹配，
    不把 NULL 记录算进来，避免多用户启用后跨用户串数据。
    """
    return "(user_id = ? OR user_id IS NULL)" if user_id == DEFAULT_USER else "user_id = ?"


def owned_project_ids(conn: Any, table: str, user_id: str) -> set[str]:
    """返回该表中归属指定用户的 project_id 集合。"""
    return owned_project_ids_where(conn, table, user_id, None)


def owned_project_ids_where(
    conn: Any,
    table: str,
    user_id: str,
    extra_condition: str | None,
) -> set[str]:
    """同 owned_project_ids，但可附加一个**字面量** SQL 条件片段。

    extra_condition 只接受调用方硬编码的字面量（如 "outcome IS NOT NULL"），
    绝不可传入用户输入 —— 它会直接拼进 SQL。取值来自代码而非请求，
    与 repositories/v2.py 里既有的 where 片段拼接口径一致。
    """
    if table not in _ALLOWED_TABLES:
        raise ValueError(f"unsupported table: {table}")

    where = _scope_clause(user_id)
    if extra_condition:
        where = f"{where} AND {extra_condition}"

    # 表名来自白名单、条件片段来自调用方字面量，user_id 走绑定参数
    sql = f"SELECT DISTINCT project_id FROM {table} WHERE {where}"  # noqa: S608
    rows = conn.execute(sql, (user_id,)).fetchall()
    return {str(r[0]) for r in rows if r and r[0]}
