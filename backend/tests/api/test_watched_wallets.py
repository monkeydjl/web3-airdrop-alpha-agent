"""领取监控（F4，ACTION_LOOP_DESIGN §5）测试：登记 / 匹配 / 脱敏 / 权限。

四个重点：

1. **地址大小写归一的正反断言都要有**。只验证"能登记"是半个断言 —— 真正
   要钉住的是"混合大小写与全小写视为同一地址"，写入侧和匹配侧**都要验**。
   只验一侧的话，另一侧漏归一时 UNIQUE 失效或永远匹配不上，而且**不报错**。
2. **地址不能出现完整值**。通知内容、日志字段都只给前 10 位。推送目的地
   （Telegram/Discord）不受本系统控制，`/watched-wallets` 的管理员锁护不住
   已经发出去的消息。
3. **匿名访问必须 403**。钱包清单是资金隐私，读写都锁 —— 泄露风险主要在读侧。
4. **领取监控挂掉不能影响 webhook 主职责**。webhook 必须返回 200（非 200
   会让 Alchemy 反复重投），且原有 RawDiscovery 入库路径不受影响。
"""

from __future__ import annotations

import hashlib
import hmac
import json

import pytest
from fastapi.testclient import TestClient

from app.config import settings
from app.db import get_connection, init_db
from app.main import create_app

ADMIN_KEY = "test-admin-key-ww-000000000001"
ADMIN_HEADERS = {"X-API-Key": ADMIN_KEY}
SIGNING_KEY = "sk_test_watched_wallets"

# 两个形状合法的地址。刻意用混合大小写的自有地址 —— Alchemy 实际返回
# EIP-55 校验和格式，全小写的测试数据会让归一缺陷蒙混过关。
MINE_MIXED = "0xAaAa111122223333444455556666777788889999"
MINE_LOWER = MINE_MIXED.lower()
OTHER = "0xbbbb111122223333444455556666777788889999"


@pytest.fixture
def client(tmp_path):
    db_path = tmp_path / "test.db"
    prev_db_path = settings.db_path
    prev_signing = settings.alchemy_webhook_signing_key
    settings.db_path = str(db_path)
    settings.alchemy_webhook_signing_key = SIGNING_KEY
    init_db()
    app = create_app(db_override=lambda: None)
    yield TestClient(app)
    settings.db_path = prev_db_path
    settings.alchemy_webhook_signing_key = prev_signing


@pytest.fixture
def admin(client):
    """开启鉴权，返回带管理员密钥的 client。"""
    prev_key = settings.api_key
    settings.api_key = ADMIN_KEY
    try:
        yield client
    finally:
        settings.api_key = prev_key


def _register(client: TestClient, address: str, label: str = "主钱包", chain: str = "ethereum"):
    return client.post(
        "/api/v1/watched-wallets",
        json={"address": address, "label": label, "chain": chain},
        headers=ADMIN_HEADERS,
    )


def _sign(body: bytes) -> str:
    return hmac.new(SIGNING_KEY.encode(), body, hashlib.sha256).hexdigest()


def _activity_payload(
    *,
    to: str,
    frm: str = OTHER,
    asset: str = "ARB",
    category: str = "erc20",
    tx_hash: str = "0x" + "d" * 64,
    event_id: str = "evt_claim_001",
) -> dict:
    return {
        "webhookId": "wh_ww_001",
        "id": event_id,
        "type": "ADDRESS_ACTIVITY",
        "event": {
            "data": {
                "address": to,
                "transactionHash": tx_hash,
                "blockNumber": "0x1234567",
                "from": frm,
                "to": to,
                "value": "0x1",
                "asset": asset,
                "category": category,
            }
        },
    }


def _post_webhook(client: TestClient, payload: dict):
    body = json.dumps(payload).encode()
    return client.post(
        "/api/v1/webhook/alchemy",
        content=body,
        headers={"x-alchemy-signature": _sign(body)},
    )


class TestWatchedWalletCrud:
    def test_address_is_stored_lowercase(self, admin: TestClient) -> None:
        """混合大小写登记后存储为小写。

        归一在写入侧生效是 UNIQUE 能工作的前提 —— 见
        test_case_variant_is_rejected_as_duplicate 的另一半。
        """
        response = _register(admin, MINE_MIXED)
        assert response.status_code == 200
        assert response.json()["data"]["address"] == MINE_LOWER

    def test_case_variant_is_rejected_as_duplicate(self, admin: TestClient) -> None:
        """同一地址的不同大小写写法视为重复，返回 409。

        这是归一的**反向断言**：漏了写入侧归一时 `0xAaAa…` 与 `0xaaaa…` 会
        各占一行，两条都能登记成功、UNIQUE 形同虚设，而匹配时只有一条命中。
        """
        assert _register(admin, MINE_MIXED).status_code == 200
        duplicate = _register(admin, MINE_LOWER, label="另一个备注")
        assert duplicate.status_code == 409
        assert duplicate.json()["error"]["code"] == "ADDRESS_EXISTS"

    def test_malformed_address_is_rejected(self, admin: TestClient) -> None:
        """形状不合法返回 422。"""
        for bad in ("0xzz", "abc", "0x" + "1" * 39, "0x" + "1" * 41, ""):
            response = _register(admin, bad)
            assert response.status_code == 422, f"{bad!r} 应被拒绝"
            assert response.json()["error"]["code"] == "INVALID_ADDRESS"

    def test_all_lowercase_address_is_accepted(self, admin: TestClient) -> None:
        """全小写地址必须能登记。

        钉住"只校验形状、不做 EIP-55 checksum 验证"这个决定：checksum 校验会
        拒绝全小写地址，而那是区块浏览器与链上工具的常见输出形式 —— 拒了会让
        用户以为自己填错了。
        """
        assert _register(admin, MINE_LOWER).status_code == 200

    def test_unsupported_chain_is_rejected(self, admin: TestClient) -> None:
        """chain 是闭表，表外取值 422。"""
        response = _register(admin, MINE_MIXED, chain="solana")
        assert response.status_code == 422
        assert response.json()["error"]["code"] == "UNSUPPORTED_CHAIN"

    def test_patch_toggles_active_and_keeps_address(self, admin: TestClient) -> None:
        """PATCH 能改 active，地址保持不变。"""
        wallet_id = _register(admin, MINE_MIXED).json()["data"]["wallet_id"]
        response = admin.patch(
            f"/api/v1/watched-wallets/{wallet_id}",
            json={"active": False, "label": "冷钱包"},
            headers=ADMIN_HEADERS,
        )
        assert response.status_code == 200
        data = response.json()["data"]
        assert data["active"] is False
        assert data["label"] == "冷钱包"
        assert data["address"] == MINE_LOWER

    def test_patch_without_fields_is_rejected(self, admin: TestClient) -> None:
        """空 PATCH 按 422 拒绝，不做空写。"""
        wallet_id = _register(admin, MINE_MIXED).json()["data"]["wallet_id"]
        response = admin.patch(f"/api/v1/watched-wallets/{wallet_id}", json={}, headers=ADMIN_HEADERS)
        assert response.status_code == 422
        assert response.json()["error"]["code"] == "NOTHING_TO_UPDATE"

    def test_patch_cannot_change_address(self, admin: TestClient) -> None:
        """地址不可改 —— 请求体里带 address 也不生效。

        改地址等于换成另一个钱包，而历史命中是按地址关联的，原地改会让既有
        通知指向一个从未监控过的地址。要换就删了重建。
        """
        wallet_id = _register(admin, MINE_MIXED).json()["data"]["wallet_id"]
        admin.patch(
            f"/api/v1/watched-wallets/{wallet_id}",
            json={"address": OTHER, "label": "试图改地址"},
            headers=ADMIN_HEADERS,
        )
        listing = admin.get("/api/v1/watched-wallets", headers=ADMIN_HEADERS).json()["data"]
        assert listing["wallets"][0]["address"] == MINE_LOWER

    def test_delete_removes_and_missing_is_404(self, admin: TestClient) -> None:
        wallet_id = _register(admin, MINE_MIXED).json()["data"]["wallet_id"]
        assert admin.delete(f"/api/v1/watched-wallets/{wallet_id}", headers=ADMIN_HEADERS).status_code == 200
        assert admin.get("/api/v1/watched-wallets", headers=ADMIN_HEADERS).json()["data"]["total"] == 0
        assert admin.delete("/api/v1/watched-wallets/9999", headers=ADMIN_HEADERS).status_code == 404

    def test_list_counts_active_separately(self, admin: TestClient) -> None:
        """active_count 与 total 分开 —— 停用的仍在清单里。"""
        first = _register(admin, MINE_MIXED).json()["data"]["wallet_id"]
        _register(admin, OTHER, label="第二个")
        admin.patch(f"/api/v1/watched-wallets/{first}", json={"active": False}, headers=ADMIN_HEADERS)
        data = admin.get("/api/v1/watched-wallets", headers=ADMIN_HEADERS).json()["data"]
        assert data["total"] == 2
        assert data["active_count"] == 1


class TestWatchedWalletsRequireAdmin:
    """整前缀管理员锁：匿名 token 读写都不行。"""

    def test_anonymous_token_is_forbidden_on_all_methods(self, admin: TestClient) -> None:
        """四个方法全部 403。

        读侧也必须锁：一份"这个人有哪些钱包"的清单配合公开链上数据就能还原
        完整持仓，泄露风险主要在读侧而不是写侧。
        """
        token = admin.post("/api/v1/auth/anonymous").json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}
        assert admin.get("/api/v1/watched-wallets", headers=headers).status_code == 403
        assert (
            admin.post(
                "/api/v1/watched-wallets", json={"address": MINE_MIXED, "label": "x"}, headers=headers
            ).status_code
            == 403
        )
        assert admin.patch("/api/v1/watched-wallets/1", json={"active": False}, headers=headers).status_code == 403
        assert admin.delete("/api/v1/watched-wallets/1", headers=headers).status_code == 403


class TestClaimMatching:
    def test_erc20_inflow_to_watched_address_matches(self, admin: TestClient) -> None:
        """erc20 转入自有地址 → 命中。

        payload 用**混合大小写**的 to：这是匹配侧归一的断言。漏了归一时不会
        报错，只是静默地什么都不发生 —— 这类失效最难发现。
        """
        _register(admin, MINE_LOWER)
        response = _post_webhook(admin, _activity_payload(to=MINE_MIXED))
        assert response.status_code == 200
        assert response.json()["data"]["claim_matched"] is True

    def test_same_event_is_deduplicated(self, admin: TestClient) -> None:
        """同 (address, tx_hash, asset) 重投只入库一次。

        Alchemy webhook 是 at-least-once，重投是正常现象而非异常。
        """
        _register(admin, MINE_LOWER)
        payload = _activity_payload(to=MINE_MIXED)
        assert _post_webhook(admin, payload).json()["data"]["claim_matched"] is True
        assert _post_webhook(admin, payload).json()["data"]["claim_matched"] is False

    def test_different_tx_is_a_new_event(self, admin: TestClient) -> None:
        """换 tx_hash 算新事件 —— 同一钱包第二次收到空投必须还能提示。

        这条钉住 event_key 里 tx_hash 那一段：只用 address 做 key 的话，
        用户永远只收到第一次通知。
        """
        _register(admin, MINE_LOWER)
        _post_webhook(admin, _activity_payload(to=MINE_MIXED))
        second = _post_webhook(admin, _activity_payload(to=MINE_MIXED, tx_hash="0x" + "e" * 64, event_id="evt_2"))
        assert second.json()["data"]["claim_matched"] is True

    def test_different_asset_same_tx_is_a_new_event(self, admin: TestClient) -> None:
        """同一交易内的不同代币各自提示 —— 钉住 event_key 里 asset 那一段。

        部分空投合约会在一笔交易里发多种代币，不含 asset 的 key 只会提示一种。
        """
        _register(admin, MINE_LOWER)
        _post_webhook(admin, _activity_payload(to=MINE_MIXED, asset="ARB"))
        second = _post_webhook(admin, _activity_payload(to=MINE_MIXED, asset="OP", event_id="evt_3"))
        assert second.json()["data"]["claim_matched"] is True

    def test_transfer_to_other_address_does_not_match(self, admin: TestClient) -> None:
        """转给非自有地址不命中。"""
        _register(admin, MINE_LOWER)
        response = _post_webhook(admin, _activity_payload(to=OTHER, frm=MINE_LOWER))
        assert response.json()["data"]["claim_matched"] is False

    def test_plain_eth_transfer_does_not_match(self, admin: TestClient) -> None:
        """纯 ETH 转入不算空投候选。

        大概率是自己在操作。启发式只做提示，但也不该在明显不是空投的场景吵人。
        """
        _register(admin, MINE_LOWER)
        response = _post_webhook(admin, _activity_payload(to=MINE_MIXED, asset="ETH", category="external"))
        assert response.json()["data"]["claim_matched"] is False

    def test_internal_transfer_between_own_wallets_does_not_match(self, admin: TestClient) -> None:
        """自有地址之间的转账是挪仓，不是空投到账。"""
        _register(admin, MINE_LOWER)
        _register(admin, OTHER, label="第二个钱包")
        response = _post_webhook(admin, _activity_payload(to=MINE_MIXED, frm=OTHER))
        assert response.json()["data"]["claim_matched"] is False

    def test_missing_tx_hash_does_not_match(self, admin: TestClient) -> None:
        """缺 transactionHash 不发事件，而不是用时间戳兜底。

        没有交易哈希意味着这条 payload 不可追溯，用户收到提示也无从核对；
        用时间戳还会让 Alchemy 重投时重复推送。
        """
        _register(admin, MINE_LOWER)
        response = _post_webhook(admin, _activity_payload(to=MINE_MIXED, tx_hash=""))
        assert response.json()["data"]["claim_matched"] is False

    def test_inactive_wallet_does_not_match(self, admin: TestClient) -> None:
        """active=false 停止匹配（临时静音），登记仍在。

        Alchemy 控制台侧的地址清单是手工维护的，所以停用后 webhook 仍会收到
        事件，只是不再产生 airdrop_candidate。
        """
        wallet_id = _register(admin, MINE_LOWER).json()["data"]["wallet_id"]
        admin.patch(f"/api/v1/watched-wallets/{wallet_id}", json={"active": False}, headers=ADMIN_HEADERS)
        response = _post_webhook(admin, _activity_payload(to=MINE_MIXED))
        assert response.json()["data"]["claim_matched"] is False
        assert admin.get("/api/v1/watched-wallets", headers=ADMIN_HEADERS).json()["data"]["total"] == 1

    def test_no_watched_wallets_does_not_break_webhook(self, admin: TestClient) -> None:
        """一个地址都没登记时 webhook 照常工作。"""
        response = _post_webhook(admin, _activity_payload(to=MINE_MIXED))
        assert response.status_code == 200
        assert response.json()["data"]["claim_matched"] is False


class TestClaimEventRedaction:
    """脱敏：完整地址不得出现在通知内容里。"""

    def test_notify_log_entry_never_contains_full_address(self, admin: TestClient) -> None:
        """notify_log 的 title/body 只含前 10 位。

        截断必须做在**事件构造侧**：事件一旦带完整地址进了 notify_log，
        后续任何 sender 都会把它原样发到 Telegram/Discord —— 那些地方不受
        本系统控制，`/watched-wallets` 的管理员锁护不到。
        """
        _register(admin, MINE_LOWER, label="主钱包")
        _post_webhook(admin, _activity_payload(to=MINE_MIXED))

        with get_connection() as conn:
            rows = conn.execute(
                "SELECT title, body FROM notify_log WHERE event_type = ?",
                ("airdrop_candidate",),
            ).fetchall()

        assert len(rows) == 1
        content = f"{rows[0]['title']}{rows[0]['body']}"
        assert MINE_LOWER not in content, "完整地址泄露进了推送内容"
        assert MINE_MIXED not in content
        assert MINE_LOWER[:10] in content, "前 10 位应保留，否则用户认不出是哪个钱包"
        assert "主钱包" in content, "label 应回显 —— 它是用户识别钱包的主要依据"

    def test_in_app_notification_never_contains_full_address(self, admin: TestClient) -> None:
        """站内通知同样截断。

        `/notifications` 对匿名 token 开放（普通使用者要能看自己的提醒），
        这里回显完整地址等于绕过 watched-wallets 的管理员锁。
        """
        _register(admin, MINE_LOWER)
        _post_webhook(admin, _activity_payload(to=MINE_MIXED))

        items = admin.get("/api/v1/notifications", headers=ADMIN_HEADERS).json()["data"]["items"]
        claims = [i for i in items if i["type"] == "airdrop_candidate"]
        assert len(claims) == 1
        serialized = json.dumps(claims[0], ensure_ascii=False)
        assert MINE_LOWER not in serialized
        assert MINE_LOWER[:10] in serialized

    def test_claim_notification_sorts_first(self, admin: TestClient) -> None:
        """领取提示排在通知列表最前。

        它是四类通知里唯一有时效性的 —— 空投领取普遍有窗口期，过期归零。
        """
        _register(admin, MINE_LOWER)
        _post_webhook(admin, _activity_payload(to=MINE_MIXED))
        items = admin.get("/api/v1/notifications", headers=ADMIN_HEADERS).json()["data"]["items"]
        assert items[0]["type"] == "airdrop_candidate"


class TestClaimWatchDoesNotBreakWebhook:
    """领取监控是附加价值，它挂掉不能影响 webhook 的既有职责。"""

    def test_webhook_returns_200_when_claim_watch_raises(self, admin: TestClient, monkeypatch) -> None:
        """匹配逻辑抛异常时 webhook 仍返回 200。

        非 200 会让 Alchemy 反复重投 —— 一个次要功能的 bug 会变成持续的
        重投风暴，连带把主职责（RawDiscovery 入库）一起拖垮。
        """
        from app.services import claim_watch

        def _boom(*args, **kwargs):
            raise RuntimeError("claim watch exploded")

        monkeypatch.setattr(claim_watch, "evaluate_claim_candidate", _boom)
        _register(admin, MINE_LOWER)
        response = _post_webhook(admin, _activity_payload(to=MINE_MIXED))
        assert response.status_code == 200
        assert response.json()["data"]["claim_matched"] is False

    def test_event_type_is_registered_in_metrics_vocabulary(self) -> None:
        """airdrop_candidate 必须在 NOTIFY_EVENT_TYPES 里。

        词表闭合：`insert_event` 会拒绝表外类型并抛 ValueError。漏登记的话
        事件永远入不了库，而 webhook 那层把异常吞掉了 —— 症状是"什么都没
        发生"，查不到原因。
        """
        from app.metrics import NOTIFY_EVENT_TYPES
        from app.services.claim_watch import CLAIM_EVENT_TYPE

        assert CLAIM_EVENT_TYPE in NOTIFY_EVENT_TYPES
