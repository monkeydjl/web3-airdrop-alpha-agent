"""自有地址登记 / watched wallets（F4，ACTION_LOOP_DESIGN §5）。

领取监控的地址清单。webhook 收到链上事件后拿它做匹配，命中就提示
「疑似空投到账」（`app/services/claim_watch.py`）。

**整前缀管理员锁**（`auth.ADMIN_ONLY_PREFIXES`）：钱包地址是资金隐私。
一份「这个人有哪些钱包」的清单，配合公开的链上数据就能还原出完整持仓与
交易史 —— 匿名角色不可见不可写。这与 `/notify`、`/settings` 同一口径。

三条实施约束（详见 §5.3.1 / §5.3.3）：

1. **地址小写归一**，写入侧与匹配侧同时做。只做一侧则 UNIQUE 形同虚设
   （`0xAbC` 与 `0xabc` 各占一行），而 Alchemy payload 返回的是 EIP-55
   混合大小写。同 competition 分组的教训：同一实体的多种写法必须在唯一
   入口归一，否则各处静默失配。
2. **只校验形状**（`^0x[0-9a-fA-F]{40}$`），不做 EIP-55 checksum 验证 ——
   checksum 校验会拒绝全小写地址，而那是链上工具与区块浏览器的常见输出，
   拒了会让用户以为自己填错了。
3. **地址不可改**：改地址等于换成另一个钱包，而历史命中是按地址关联的，
   原地改会让既有通知指向一个从未监控过的地址。要换就删了重建。

Reference:
- docs/ACTION_LOOP_DESIGN.md §5.3 / §5.4
- app/services/claim_watch.py（匹配与事件构造）
"""

from __future__ import annotations

import re
from typing import Any

import structlog
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.db import get_connection

logger = structlog.get_logger(__name__)
router = APIRouter(tags=["watched-wallets"])

# 只校验形状，不校验 EIP-55 checksum（见模块 docstring 第 2 条）。
_ADDRESS_RE = re.compile(r"^0x[0-9a-fA-F]{40}$")

# 支持的链。收成闭表而不是任意字符串：chain 会进通知文案，
# 拼写不一致（ethereum / Ethereum / eth）会让同一条链看起来像三条。
SUPPORTED_CHAINS = ("ethereum", "arbitrum", "optimism", "base", "polygon")


class WalletCreate(BaseModel):
    """登记一个自有地址。"""

    address: str = Field(..., description="0x + 40 位十六进制。存储时统一转小写")
    label: str = Field(..., min_length=1, max_length=64, description="自定义备注，通知里回显它")
    chain: str = Field("ethereum", description=f"取值范围 {SUPPORTED_CHAINS}")


class WalletUpdate(BaseModel):
    """改 label / chain / active。地址刻意不可改（见模块 docstring 第 3 条）。"""

    label: str | None = Field(None, min_length=1, max_length=64)
    chain: str | None = None
    active: bool | None = None


def _normalize_address(address: str) -> str:
    """归一为小写并校验形状。

    归一与校验放在同一个函数里是刻意的：分开写迟早会出现「校验了但没归一」
    或「归一了但没校验」的调用点，而这两种漏法都不会立即报错 —— 前者让
    UNIQUE 失效，后者让垃圾数据进表。
    """
    candidate = address.strip()
    if not _ADDRESS_RE.match(candidate):
        raise HTTPException(
            status_code=422,
            detail={
                "code": "INVALID_ADDRESS",
                "message": "地址必须是 0x + 40 位十六进制字符",
            },
        )
    return candidate.lower()


def _validate_chain(chain: str) -> str:
    if chain not in SUPPORTED_CHAINS:
        raise HTTPException(
            status_code=422,
            detail={
                "code": "UNSUPPORTED_CHAIN",
                "message": f"chain 必须是 {', '.join(SUPPORTED_CHAINS)} 之一",
            },
        )
    return chain


def _row_to_wallet(row: Any) -> dict[str, Any]:
    """行 → 响应形状。

    `active` 两个方言类型不同（SQLite INTEGER / PG BOOLEAN），转换统一在
    读取侧做，API 出去一律是 bool。
    """
    return {
        "id": int(row["id"]),
        "address": row["address"],
        "label": row["label"],
        "chain": row["chain"],
        "active": bool(row["active"]),
        "created_at": row["created_at"],
    }


def _not_found(wallet_id: int) -> None:
    raise HTTPException(
        status_code=404,
        detail={"code": "NOT_FOUND", "message": f"watched wallet {wallet_id} not found"},
    )


@router.get(
    "/watched-wallets",
    summary="列出已登记的自有地址",
    description="含 inactive。管理员专属 —— 钱包清单是资金隐私。",
)
def list_watched_wallets() -> dict[str, Any]:
    """全量列出，按登记时间倒序。"""
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT id, address, label, chain, active, created_at "
            "FROM watched_wallets ORDER BY created_at DESC, id DESC"
        ).fetchall()

    wallets = [_row_to_wallet(r) for r in rows]
    return {
        "ok": True,
        "data": {
            "wallets": wallets,
            "total": len(wallets),
            "active_count": sum(1 for w in wallets if w["active"]),
        },
    }


@router.post(
    "/watched-wallets",
    summary="登记一个自有地址",
    description="地址小写归一后唯一。重复登记返回 409。",
)
def create_watched_wallet(body: WalletCreate) -> dict[str, Any]:
    """插入一行 watched_wallets。"""
    address = _normalize_address(body.address)
    chain = _validate_chain(body.chain)

    with get_connection() as conn:
        existing = conn.execute(
            "SELECT id FROM watched_wallets WHERE address = ?",
            (address,),
        ).fetchone()
        if existing is not None:
            # 显式先查再报 409，而不是依赖 UNIQUE 抛 IntegrityError：
            # 两个方言的完整性异常类型与消息都不同，靠捕获异常来区分
            # 「重复地址」和「其它写入失败」不可靠。
            raise HTTPException(
                status_code=409,
                detail={
                    "code": "ADDRESS_EXISTS",
                    "message": "该地址已登记（地址比较不区分大小写）",
                },
            )

        row = conn.execute(
            "INSERT INTO watched_wallets (address, label, chain) VALUES (?, ?, ?) RETURNING id",
            (address, body.label, chain),
        ).fetchone()
        wallet_id = int(row["id"])
        conn.commit()

    # 日志里只记前 10 位 —— 日志会进文件、可能被采集到集中式日志系统，
    # 与推送内容同一口径（§5.4.1）。
    logger.info("claim_watch.wallet_registered", wallet_id=wallet_id, address_prefix=address[:10], chain=chain)
    return {"ok": True, "data": {"wallet_id": wallet_id, "address": address, "chain": chain}}


@router.patch(
    "/watched-wallets/{wallet_id}",
    summary="改备注 / 链 / 启用状态",
    description="地址不可改 —— 换地址请删除后重新登记。",
)
def update_watched_wallet(wallet_id: int, body: WalletUpdate) -> dict[str, Any]:
    """局部更新。三个字段都为空时按 422 拒绝，不做空写。

    SQL 是**固定语句**，用 `COALESCE(?, col)` 表达"给了就改、没给就保留"，
    而不是按传入字段拼 SET 子句。拼接版本会触发 ruff S608（SQL 注入向量）——
    这里的片段确实都是代码里的字面量、注入不了，但把「安全」建立在「凑巧
    没有用户输入流进拼接串」上是脆的：下一个人加一个字段时很自然就会写成
    `updates.append(f"{col} = ?")`，那一步就真的开口子了。固定语句从形状上
    就没有这个可能。
    """
    if body.label is None and body.chain is None and body.active is None:
        raise HTTPException(
            status_code=422,
            detail={
                "code": "NOTHING_TO_UPDATE",
                "message": "label / chain / active 至少要给一个",
            },
        )

    chain = _validate_chain(body.chain) if body.chain is not None else None
    changed = sum(1 for value in (body.label, body.chain, body.active) if value is not None)

    with get_connection() as conn:
        current = conn.execute(
            "SELECT id FROM watched_wallets WHERE id = ?",
            (wallet_id,),
        ).fetchone()
        if current is None:
            _not_found(wallet_id)

        conn.execute(
            """
            UPDATE watched_wallets
               SET label  = COALESCE(?, label),
                   chain  = COALESCE(?, chain),
                   active = COALESCE(?, active)
             WHERE id = ?
            """,
            (body.label, chain, body.active, wallet_id),
        )
        conn.commit()
        row = conn.execute(
            "SELECT id, address, label, chain, active, created_at FROM watched_wallets WHERE id = ?",
            (wallet_id,),
        ).fetchone()

    logger.info("claim_watch.wallet_updated", wallet_id=wallet_id, fields=changed)
    return {"ok": True, "data": _row_to_wallet(row)}


@router.delete(
    "/watched-wallets/{wallet_id}",
    summary="删除一个登记地址",
    description="硬删。只想临时停止匹配请用 PATCH active=false。",
)
def delete_watched_wallet(wallet_id: int) -> dict[str, Any]:
    """物理删除。

    与 `active=false` 的区别：后者保留登记但停止匹配（临时静音）。
    做成硬删是因为这张表没有历史价值 —— 命中记录存在 notify_log 里，
    不依赖本表存活。
    """
    with get_connection() as conn:
        row = conn.execute(
            "SELECT address FROM watched_wallets WHERE id = ?",
            (wallet_id,),
        ).fetchone()
        if row is None:
            _not_found(wallet_id)
        conn.execute("DELETE FROM watched_wallets WHERE id = ?", (wallet_id,))
        conn.commit()

    logger.info("claim_watch.wallet_deleted", wallet_id=wallet_id)
    return {"ok": True, "data": {"wallet_id": wallet_id, "deleted": True}}
