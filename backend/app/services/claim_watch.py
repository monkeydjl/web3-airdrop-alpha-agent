"""领取监控：把链上事件匹配到自有地址（F4，ACTION_LOOP_DESIGN §5）。

webhook 收到 Alchemy 事件后调 `evaluate_claim_candidate()`：命中 active 的
自有地址、且形状像"收到了某种代币"，就产出一条 `airdrop_candidate` 事件。

**启发式只做提示，不承诺语义**（§5.3）。判定条件是 `category=erc20` 且
`asset != ETH` —— 这挡掉纯 ETH 转账（大概率是自己在操作，不是空投到账），
但挡不掉任何一笔正常的代币转入。所以文案是"疑似"，用户自己确认。
把这个启发式包装成"已确认到账"是虚假的确定性。

三条硬约束：

1. **绝不抛异常给调用方。** webhook 处理器必须返回 200（非 200 会让 Alchemy
   反复重投），而领取监控是"附加价值"，它挂掉不该影响原有的 RawDiscovery
   入库。所以本模块所有失败都吞掉并记日志，返回 None。
2. **地址匹配前先归一。** payload 里的地址大小写取决于上游（Alchemy 实际
   返回 EIP-55 混合大小写），表里存的是小写。不归一就永远匹配不上，而且
   **不会报错** —— 只是静默地什么都不发生，这类失效最难发现。
3. **通知内容只含 label + 地址前 10 位。** 截断做在事件构造这一步，不能只
   做在 API 响应层：事件一旦带完整地址进了 notify_log，任何 sender 都会把
   它原样发到 Telegram/Discord 那些不受本系统控制的地方（§5.4.1）。

Reference:
- docs/ACTION_LOOP_DESIGN.md §5.3 / §5.4
- app/routers/v1/webhook.py（调用方）
- app/notify/service.py（insert_event 消费本模块产出）
"""

from __future__ import annotations

import contextlib
from typing import Any

import structlog

from app.notify.evaluator import NotifyEvent

logger = structlog.get_logger(__name__)

# 事件类型，必须已登记进 metrics.NOTIFY_EVENT_TYPES（词表闭合）。
CLAIM_EVENT_TYPE = "airdrop_candidate"

# 地址在通知里的截断长度：`0x` + 8 位十六进制。
# 足够用户认出是哪个钱包，不足以让第三方去链上反查完整持仓。
ADDRESS_DISPLAY_CHARS = 10


def _normalize(value: Any) -> str:
    """地址归一：非字符串或空值一律返回空串（而不是抛错）。"""
    if not isinstance(value, str):
        return ""
    return value.strip().lower()


def _active_watched(conn: Any) -> dict[str, str]:
    """active 自有地址 → label。地址已是小写（写入侧归一）。"""
    rows = conn.execute(
        "SELECT address, label FROM watched_wallets WHERE active = ?",
        (True,),
    ).fetchall()
    return {str(r["address"]): str(r["label"]) for r in rows}


def _looks_like_token_inflow(data: dict[str, Any]) -> bool:
    """形状是否像"收到了某种代币"。

    `category == erc20` 且 `asset != ETH`。两个条件都要：
    - 只看 category：某些 payload 的 erc20 事件 asset 仍写 ETH（包装代币场景）。
    - 只看 asset：external 类别的普通转账也会带非 ETH 的 asset 字段。

    刻意**不看金额**：空投的数量单位取决于代币精度，没有一个跨代币可比的
    阈值。用金额过滤等于按精度歧视代币。
    """
    category = _normalize(data.get("category"))
    asset = _normalize(data.get("asset"))
    return category == "erc20" and asset != "eth" and bool(asset)


def build_claim_event(*, label: str, address: str, asset: str, tx_hash: str) -> NotifyEvent:
    """构造 airdrop_candidate 事件。

    `event_key` = `claim:{address}:{tx_hash}:{asset}` —— 三段都必须在（§5.3.2）：
    - 只用 address：同一钱包第二次收到空投被去重吃掉。
    - 只用 tx_hash：一笔交易转给多个自有地址时只提示一个（批量领取常见）。
    - 不含 asset：同一交易内多种代币只提示一种。

    地址在 title/body 里都截断 —— 见模块 docstring 第 3 条。
    """
    short = address[:ADDRESS_DISPLAY_CHARS]
    return NotifyEvent(
        event_type=CLAIM_EVENT_TYPE,
        event_key=f"claim:{address}:{tx_hash}:{asset}",
        title=f"疑似空投到账：{label}",
        body=(
            f"钱包 {label}（{short}…）收到 {asset}。\n"
            f"这是基于链上事件形状的**提示**，不是到账确认 —— 请自行核对后再操作。"
        ),
    )


def evaluate_claim_candidate(conn: Any, payload: dict[str, Any]) -> NotifyEvent | None:
    """匹配自有地址并产出 airdrop_candidate 事件；不命中返回 None。

    调用点在 webhook 处理器的**签名校验通过之后**。本函数不抛异常
    （见模块 docstring 第 1 条）—— 任何失败都返回 None 并记日志。
    """
    try:
        event = payload.get("event") or {}
        data = event.get("data") or {}
        if not isinstance(data, dict):
            return None

        if not _looks_like_token_inflow(data):
            return None

        # tx_hash 缺失时不发事件，而不是用时间戳兜底（§5.3.2）：
        # 没有交易哈希意味着这条 payload 不可追溯，用户收到提示也无从核对；
        # 用时间戳还会让 Alchemy 重投时重复推送（webhook 是 at-least-once）。
        tx_hash = _normalize(data.get("transactionHash"))
        if not tx_hash:
            logger.info("claim_watch.skipped_no_tx_hash")
            return None

        watched = _active_watched(conn)
        if not watched:
            return None

        # from 与 to 都查：to 命中是"收到"，from 命中是"转出"。
        # 只有 to 命中才算候选 —— 自己转出去的不是空投。
        # 但 from 也要归一比对，否则「自己转给自己」的场景会误报。
        to_address = _normalize(data.get("to"))
        from_address = _normalize(data.get("from"))

        if to_address not in watched:
            return None
        if from_address and from_address in watched:
            # 自有地址之间的转账：是自己在挪仓，不是空投到账。
            logger.info("claim_watch.skipped_internal_transfer", address_prefix=to_address[:ADDRESS_DISPLAY_CHARS])
            return None

        asset = str(data.get("asset") or "").strip()
        claim_event = build_claim_event(
            label=watched[to_address],
            address=to_address,
            asset=asset,
            tx_hash=tx_hash,
        )
        logger.info(
            "claim_watch.candidate_detected",
            address_prefix=to_address[:ADDRESS_DISPLAY_CHARS],
            asset=asset,
            event_key=claim_event.event_key,
        )
        return claim_event

    except Exception as exc:
        # 领取监控是附加价值，它挂掉不能影响 webhook 的既有职责。
        logger.error("claim_watch.evaluate_failed", error=str(exc), exc_info=True)
        return None


def record_claim_candidate(conn: Any, event: NotifyEvent, channel: str) -> bool:
    """把事件写进 notify_log，交给 F1 的 dispatch_pending 发出去。

    返回是否新插入（同 event_key+channel 会被 ON CONFLICT 忽略）。
    这里也不抛异常：入库失败不能连带让 webhook 返回非 200。
    """
    from app.notify.service import insert_event

    try:
        return insert_event(conn, event, channel)
    except Exception as exc:
        logger.error("claim_watch.record_failed", error=str(exc), event_key=event.event_key, exc_info=True)
        return False


def claim_notification_items(conn: Any, window_start: str) -> list[dict[str, Any]]:
    """站内通知条目（供 notifications.py 的派生视图聚合）。

    直接读 notify_log 里本窗口的 airdrop_candidate 行，而不是重新匹配一遍
    链上事件 —— 后者需要保存原始 payload，而且两条路径的判定一旦漂移，
    站内看到的和推送出去的就会不一致。

    `title` / `body` 在入库时已完成地址截断，这里原样透出即可。
    """
    items: list[dict[str, Any]] = []
    with contextlib.suppress(Exception):
        rows = conn.execute(
            "SELECT id, event_key, title, body, created_at FROM notify_log "
            "WHERE event_type = ? AND created_at >= ? ORDER BY id DESC LIMIT 20",
            (CLAIM_EVENT_TYPE, window_start),
        ).fetchall()
        for row in rows:
            items.append(
                {
                    "id": f"claim-{row['id']}",
                    "type": CLAIM_EVENT_TYPE,
                    "title": str(row["title"]),
                    "tag": "领取",
                    "text": str(row["body"]),
                    "project_id": "",
                    "created_at": str(row["created_at"]),
                    "link": {"label": "查看设置", "href": "/settings"},
                }
            )
    return items
