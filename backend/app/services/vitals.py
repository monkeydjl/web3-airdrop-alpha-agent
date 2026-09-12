"""网站活性探测（vitals）：不死项目与僵尸项目之间的廉价分水岭。

点子来源（2026-09-08）：「发现里有些项目 X 账号很久不更新、官网也打不开」
—— 前面采集器没一个管这个，而这信号**不需要任何付费 key**，一个 HEAD
请求就能拿到。对高分但概念型的「空壳」项目而言，官网活着是最低门槛。

### 判定口径（三态）

- **ok**：拿到 HTTP 200-399，或者是 401/403（Cloudflare/防火墙拦 bot，不算站没了）
- **dead**：拿到 404/410（域名摘牌、内容撤下）或 5xx 之类 —— **设备回了话，回答是没有**
- **unknown**：连接超时/传输错误/SSL 手误之类 —— 这一档**不写库**

这个分法是关键：实测一轮 237 个项目上，第一次跑有 39 个是「传输错误」，
前两轮都能看到同一地址返回 200 —— 那是抖动，不能当「挂了」。「没给出
判断」和「判断出挂了」是两回事，必须分开。

### 探测原则

- HEAD 优先；服务器明确回 405（不支持 HEAD）时落 GET
- 跟随重定向（301/302 跳到 https 是惯常，不应算挂）
- 超时 5s，探测并行，不阻塞主循环

### 写库口径

- 只在判定**变化**（None / ok / dead 之间互变）时写 `meta.signals`
- unknown 不写任何字段 —— 抖动不配弄脏数据库
- 写的时候连带写上 `site_checked_at`（入场时间）与 `site_http_status`
  （诊断只读，前端不展示），免得将来不知道是哪天踢的

字段落位（详见 `services/project_signals.py` 的 SIGNAL_KEYS）:

- `site_alive`: True | False | None（None = 还没探过 / 上次未知不翻页）
- `site_http_status`: number | null — 最近一次确定判定时的 HTTP 状态码
- `site_checked_at`: ISO 8601 — 判定写入时间
"""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from typing import Any

import httpx
import structlog

from app.repository import ProjectRepository

logger = structlog.get_logger(__name__)

_TIMEOUT = 5.0
_UA = {"User-Agent": "Mozilla/5.0 (compatible; airdrop-alpha/1.0; site-probe)"}

# 判定 verdict 的三个取值
_OK = "ok"
_DEAD = "dead"
_UNKNOWN = "unknown"


async def probe_site(url: str) -> tuple[str, int | None]:
    """对一个 URL 探测一次。返回 (verdict, http_status)。"""
    timeout = httpx.Timeout(_TIMEOUT)
    async with httpx.AsyncClient(follow_redirects=True, timeout=timeout, headers=_UA) as client:
        try:
            resp = await client.head(url)
            if resp.status_code == 405:
                resp = await client.get(url)
            code = resp.status_code
            # 401/403: 拦 bot（Cloudflare 之类），站活着，只是数据源不受欢迎；
            # 429: 被限流 —— 服务器明确回了「在的，但你别太快」，同样不算死
            if code in (401, 403, 429):
                return (_OK, code)
            if code < 400:
                return (_OK, code)
            return (_DEAD, code)
        except (httpx.TransportError, httpx.InvalidURL):
            return (_UNKNOWN, None)


def _state_from_alive(alive: Any) -> bool | None:
    """读库里 `site_alive`（None / True / False）。写库那里只允许这三个值。"""
    if isinstance(alive, bool):
        return alive
    return None


async def run_vitals_probe(repo: ProjectRepository | None = None) -> dict[str, int]:
    """跑一轮探测（无 ``repo`` 参数时从默认库读取）。

    判定三态：ok / dead / unknown。unknown（超时、传输错）**不写库** ——
    那一回合没给出判断，抖动不能把项目记录在案。只有状态变化（含首探）
    才写信号；同样的结论重复一百次，``updated_at`` 一格不动。
    """
    repo = repo or ProjectRepository()
    stats = {"probed": 0, "changed": 0, "down": 0, "skipped_no_url": 0, "inconclusive": 0}

    rows: list[dict[str, Any]] = []
    page = 1
    while True:
        batch, _total = repo.list_projects(page=page, page_size=100)
        if not batch:
            break
        rows.extend(batch)
        if len(batch) < 100:
            break
        page += 1

    pending: list[tuple[str, str, bool | None]] = []  # (project_id, url, prev alive)
    for row in rows:
        url = row.get("url")
        if not url:
            stats["skipped_no_url"] += 1
            continue

        prev: bool | None = None
        meta = row.get("meta")
        if isinstance(meta, str) and meta:
            try:
                prev = _state_from_alive(json.loads(meta).get("signals", {}).get("site_alive"))
            except (json.JSONDecodeError, TypeError):
                prev = None
        pending.append((str(row["id"]), str(url), prev))

    async def _one(pid: str, url: str) -> tuple[str, str, int | None]:
        verdict, status = await probe_site(url)
        return pid, verdict, status

    # 多个探测并行；总数是量级不大的几百，5s 超时 + httpx 贴跑很轻松
    results = await asyncio.gather(*[_one(pid, url) for pid, url, _ in pending])

    now = datetime.now(UTC).isoformat()
    for (pid, _url, prev), (_pid, verdict, http_status) in zip(pending, results, strict=True):
        if verdict == _UNKNOWN:
            stats["inconclusive"] += 1
            continue
        stats["probed"] += 1  # 只算「这一次判出结论」的项目
        alive = verdict == _OK
        if not alive:
            stats["down"] += 1
        if prev == alive:
            continue  # 状态没变，忍住不写库
        stats["changed"] += 1
        repo.update_meta_signals(
            pid,
            {
                "site_alive": alive,
                "site_http_status": http_status,
                "site_checked_at": now,
            },
        )

    logger.info(
        "vitals.probe_completed",
        probed=stats["probed"],
        changed=stats["changed"],
        down=stats["down"],
        skipped_no_url=stats["skipped_no_url"],
        inconclusive=stats["inconclusive"],
    )
    return stats
