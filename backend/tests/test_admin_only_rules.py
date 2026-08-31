"""管理员专属规则的门禁：写操作要么受保护，要么**显式登记**为匿名可写。

## 这个文件为什么存在

2026-08-23 实测发现两个口子：`POST /api/v1/collections/{id}/trigger` 和
`PATCH /api/v1/projects/{id}/funding` 匿名 token 都返回 **200**，
而且不是"能看"而是"能做"——前者真的跑了一次采集（写三张表、消耗第三方 API
配额），后者改数据并触发重算。

它们不是被谁故意放开的，是**从来没人列一张完整的写操作清单去核对**。
`ADMIN_ONLY_PREFIXES` 是一张"记得来登记才会生效"的白名单，
而这类白名单的失效方式是沉默的：漏了一条，没有任何东西会变红。

所以这里不再逐条列"该锁哪些"，而是反过来：
**把 OpenAPI 里所有写操作枚举出来，每一条都必须有归属。**

## 双向登记表

一个方向不够（这是本仓反复出现的教训）：

- 只查"登记的都还在" → 新增一个未受保护的写端点不会被发现。
- 只查"存在的都登记了" → 端点删掉之后，登记条目会永远留着骗人。

所以两个方向都查：
1. `ANON_WRITABLE` 里的每一条都必须在 OpenAPI 里真实存在（防陈旧条目）。
2. OpenAPI 里每一个写操作，要么受管理员保护，要么在 `ANON_WRITABLE` 里
   带一句为什么（防新增漏网）。

登记只允许**逐条 (方法, 路径)**，不允许按前缀或按文件豁免 ——
**豁免的粒度就是漏洞的大小。**
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.auth import ADMIN_ONLY_METHOD_RULES, ADMIN_ONLY_PREFIXES, PUBLIC_PREFIXES, requires_admin
from app.main import create_app

WRITE_METHODS = ("post", "patch", "put", "delete")

REPO_ROOT = Path(__file__).resolve().parents[2]
API_SPEC = REPO_ROOT / "docs" / "API_SPEC.md"
OPERATIONS = REPO_ROOT / "docs" / "OPERATIONS.md"


# ═══════════════════════════════════════════════════════════════
# 显式登记：匿名可写，且写清为什么可以
# ═══════════════════════════════════════════════════════════════
#
# 判断标准是**这个写操作会不会造成花钱、改别人数据、或改系统行为**：
#   - 记录"我自己"的行为/反馈/关注 → 可以匿名（本来就是给匿名用户用的）
#   - 花钱、改采集配置、改项目事实数据 → 必须管理员
#
# 每一条都必须写一句理由。没有理由的条目在评审时无法判断对错，
# 而一张无法评审的白名单等于没有白名单。
ANON_WRITABLE: dict[tuple[str, str], str] = {
    ("POST", "/api/v1/auth/anonymous"): "签发匿名 token 本身 —— 它就是匿名入口，锁了没人能进来。",
    ("POST", "/api/v1/webhook/alchemy"): "第三方 webhook 回调，由签名校验而非 token 保护（见 PUBLIC_PREFIXES）。",
    ("POST", "/api/v1/events"): "前端埋点上报，只写自己的事件流。",
    ("POST", "/api/v1/feedback"): "用户对评分打反馈 —— 这是反馈闭环的入口，必须匿名可用。",
    ("POST", "/api/v1/feedback/batch"): "同上，批量版本。",
    ("POST", "/api/v1/interactions"): "记录「我」对某项目做过的交互，按 user_id 隔离。",
    ("PATCH", "/api/v1/interactions/{interaction_id}"): "改自己的交互记录。",
    ("DELETE", "/api/v1/interactions/{interaction_id}"): "删自己的交互记录。",
    ("POST", "/api/v1/notifications/read"): "把自己的通知标记已读，只影响自己的未读状态。",
    ("POST", "/api/v1/watchlist/{project_id}"): "把项目加进自己的关注列表，按 user_id 隔离。",
    ("DELETE", "/api/v1/watchlist/{project_id}"): "从自己的关注列表里移除，按 user_id 隔离。",
    # ⚠️ 下面两条**消耗 LLM 额度**，属于"会花钱"那一类，但本轮刻意没有锁：
    # 所有者已决定给 LLM_DAILY_BUDGET_USD 实现真正的拦截，届时成本由预算门
    # 统一挡住，比按角色锁更贴合真实风险（管理员刷同样会花钱）。
    # 这两行留在这里是为了让"它们没被锁"成为一个**显式的、写着理由的决定**，
    # 而不是又一个没人注意到的口子。
    ("POST", "/api/v1/projects/{project_id}/ai-brief"): (
        "会走 LLM（有额度成本）。刻意不按角色锁：改由 LLM 每日预算门统一拦截，"
        "见 LLM_DAILY_BUDGET_USD。锁角色挡不住管理员自己刷爆额度。"
    ),
    ("POST", "/api/v1/projects/{project_id}/opportunity/evaluate"): (
        "同上 —— 旁路机会引擎评估会走 LLM，由预算门而非角色控制成本。"
    ),
    ("POST", "/api/v1/projects/{project_id}/opportunity/evidence"): "只追加证据条目，不花钱、不改评分事实。",
    # ── 参与流水（F2，ACTION_LOOP_DESIGN §3，2026-08-31）──
    # 与 feedback / watchlist 同一设计意图：参与记录本来就要让普通使用者写。
    # user_id 一律来自 token（get_current_user），请求体自报被忽略；
    # 归属不匹配的资源按 404 处理，不确认存在性。
    (
        "POST",
        "/api/v1/projects/{project_id}/participation",
    ): "创建自己的参与 plan，按 token 身份隔离，请求体自报 user_id 被忽略。",
    ("PATCH", "/api/v1/participation/{plan_id}"): "改自己的参与 plan（状态机闭表迁移），跨 token 一律 404。",
    ("PATCH", "/api/v1/participation/tasks/{task_id}"): "改自己 plan 下的任务状态，归属校验同 plan。",
    ("DELETE", "/api/v1/participation/{plan_id}"): "删自己的参与 plan（级联删任务），跨 token 一律 404。",
    # ── 收益台账（F3，ACTION_LOOP_DESIGN §4，2026-08-31）──
    # 与 feedback / watchlist 同一设计意图：台账记的是「我自己投了多少、拿回
    # 多少」，本来就要让普通使用者写。录入只是留痕，不触发任何花钱动作
    # （没有链上取价、没有代签），也不改系统行为 —— 唯一影响是校准样本池。
    (
        "POST",
        "/api/v1/projects/{project_id}/roi/entries",
    ): "记自己的投入（gas/时间），按 token 身份隔离，请求体自报 user_id 被忽略。",
    (
        "POST",
        "/api/v1/projects/{project_id}/roi/outcomes",
    ): "记自己的产出（空投到账/未领），同上隔离；是校准正负样本的来源。",
    ("DELETE", "/api/v1/roi/entries/{entry_id}"): "删错记的投入，跨 token 一律 404。",
    ("DELETE", "/api/v1/roi/outcomes/{outcome_id}"): "删错记的产出，跨 token 一律 404。",
}


@pytest.fixture(scope="module")
def openapi_spec() -> dict:
    with TestClient(create_app()) as client:
        response = client.get("/openapi.json")
    assert response.status_code == 200, f"取 OpenAPI 失败：HTTP {response.status_code}"
    spec = response.json()
    assert spec.get("paths"), "OpenAPI 没有 paths —— 解析器已失效，本文件所有断言都会空转。"
    return spec


def _write_operations(spec: dict) -> set[tuple[str, str]]:
    """OpenAPI 里所有会改变状态的操作，形如 `("POST", "/api/v1/run")`。"""
    ops = {(method.upper(), path) for path, item in spec["paths"].items() for method in item if method in WRITE_METHODS}
    assert len(ops) >= 15, f"只枚举出 {len(ops)} 个写操作，远少于预期（≥15）—— 枚举逻辑可能已失效。"
    return ops


def _is_public(path: str) -> bool:
    return any(path == p or path.startswith(p + "/") for p in PUBLIC_PREFIXES)


def _concrete(path: str) -> str:
    """把 `{param}` 替换成一个具体值，好让前缀/正则规则能真实匹配。"""
    return re.sub(r"\{[^}]+\}", "sample-id", path)


class TestEveryWriteOperationHasAnOwner:
    """每个写操作要么受管理员保护，要么显式登记为匿名可写 —— 没有第三种。"""

    def test_no_unclaimed_write_operation(self, openapi_spec) -> None:
        unclaimed = []
        for method, path in sorted(_write_operations(openapi_spec)):
            if requires_admin(method, _concrete(path)):
                continue
            if (method, path) in ANON_WRITABLE:
                continue
            if _is_public(path):
                continue
            unclaimed.append(f"{method} {path}")

        assert not unclaimed, (
            f"这 {len(unclaimed)} 个写操作既没受管理员保护、也没登记为匿名可写：{unclaimed}。\n"
            "写操作的默认归属必须是显式的：要么加进 ADMIN_ONLY_PREFIXES / "
            "ADMIN_ONLY_METHOD_RULES，要么加进本文件的 ANON_WRITABLE 并写一句为什么。\n"
            "上一次漏登记的代价：匿名 token 能触发真实采集（花第三方配额）"
            "并改融资数据。它不是被谁放开的，是从来没人核对过完整清单。"
        )

    def test_registry_has_no_stale_entries(self, openapi_spec) -> None:
        """反方向：登记表里不能有 OpenAPI 里已经不存在的条目。

        单查一个方向永远发现不了缺行 —— 这是本仓的老教训
        （SECURITY.md 的域名白名单就漏了 RootData 整整一行）。
        陈旧条目更坏一点：它会让人以为"这个端点是审过的"。
        """
        real = _write_operations(openapi_spec)
        stale = sorted(f"{m} {p}" for m, p in ANON_WRITABLE if (m, p) not in real)
        assert not stale, (
            f"ANON_WRITABLE 里这 {len(stale)} 条在 OpenAPI 里已不存在：{stale}。\n"
            "陈旧的豁免条目会让人以为对应端点已经审过了。端点删掉时请一并删掉登记。"
        )

    def test_every_registry_entry_states_a_reason(self) -> None:
        """每条登记必须有理由 —— 一张无法评审的白名单等于没有白名单。"""
        empty = sorted(f"{m} {p}" for (m, p), reason in ANON_WRITABLE.items() if len(reason.strip()) < 8)
        assert not empty, f"这些登记条目没写清理由：{empty}。"


class TestMethodLevelRulesAreCorrectlyScoped:
    """按方法锁的规则必须**只**锁该锁的，不能顺手锁掉只读接口。

    只验证"锁住了"是半个断言：把整个 `/api/v1/collections` 前缀塞进
    `ADMIN_ONLY_PREFIXES` 也能让所有"应当 403"的断言全绿，
    代价是首页和 /discoveries 页对匿名角色直接空掉。
    **一个只验证「锁住了」的测试，无法区分「锁对了」和「锁多了」。**
    """

    # (方法, 路径, 是否应当只给管理员)
    CASES = (
        ("POST", "/api/v1/collections/defillama/trigger", True),
        ("PATCH", "/api/v1/collections/defillama", True),
        ("PUT", "/api/v1/collections/defillama", True),
        ("DELETE", "/api/v1/collections/defillama", True),
        ("GET", "/api/v1/collections/sources", False),
        ("HEAD", "/api/v1/collections/sources", False),
        ("PATCH", "/api/v1/projects/abc/funding", True),
        ("GET", "/api/v1/projects/abc/funding", False),
        ("GET", "/api/v1/projects", False),
        ("POST", "/api/v1/feedback", False),
        ("POST", "/api/v1/run", True),
        ("GET", "/api/v1/settings/config", True),
    )

    @pytest.mark.parametrize(("method", "path", "admin_only"), CASES)
    def test_decision_matches_intent(self, method: str, path: str, admin_only: bool) -> None:
        actual = requires_admin(method, path)
        if admin_only:
            assert actual, f"`{method} {path}` 应当只给管理员，但判定为放行。"
        else:
            assert not actual, f"`{method} {path}` 是普通只读/自助操作，不该被锁（会让页面对匿名角色空掉）。"

    def test_options_preflight_is_not_blocked(self) -> None:
        """CORS 预检必须放行 —— 否则浏览器连真实请求都发不出去。

        ⚠️ 这条第一版写错了，值得记下来：我断言的是
        `requires_admin("OPTIONS", path) is False`，结果 `/api/v1/run` 直接挂了。

        挂得对。整前缀锁**故意**不看方法（`/api/v1/settings` 的 GET 也要锁），
        放行 `OPTIONS` 是中间件里一条更早的分支干的，不是判定函数的职责。
        我那条断言在要求代码符合我脑子里的分层，而不是它真实的分层 ——
        **断言要对着代码，不是对着我以为的代码。**

        改成断言真正的不变量：一个 OPTIONS 预检请求**不会**被鉴权挡下来。
        这是端到端的行为，与哪一层实现它无关，所以将来重排分支顺序也照样有效。
        """
        from app.config import settings

        original = settings.api_key
        try:
            settings.api_key = "test-admin-key-for-preflight-check"
            with TestClient(create_app(db_override=lambda: None)) as client:
                for path in (
                    "/api/v1/run",  # 整前缀锁
                    "/api/v1/collections/defillama/trigger",  # 按方法锁
                    "/api/v1/projects/abc/funding",  # 按方法锁
                ):
                    response = client.options(
                        path,
                        headers={
                            "Origin": "http://localhost:3002",
                            "Access-Control-Request-Method": "POST",
                        },
                    )
                    assert response.status_code not in (401, 403), (
                        f"`OPTIONS {path}` 被鉴权挡下来了（{response.status_code}）—— "
                        "预检不带自定义头，挡掉它会让浏览器连真实请求都发不出去，"
                        "表现是整个页面跨域失败而不是某个接口 403。"
                    )
        finally:
            settings.api_key = original

    def test_rules_use_anchored_patterns(self) -> None:
        """按方法锁的正则必须锚定开头，且不能被相似路径蒙过去。

        没有 `^` 的话，`/api/v1/foo/api/v1/collections/x` 之类的路径也会命中；
        没有 `(?:/|$)` 的话，`/api/v1/collectionsfoo` 会被误锁。
        两种错误方向相反，但都来自"用子串当路径判定"。
        """
        assert ADMIN_ONLY_METHOD_RULES, "按方法锁的规则表是空的 —— 那两个口子等于没关。"
        for methods, pattern in ADMIN_ONLY_METHOD_RULES:
            assert pattern.pattern.startswith("^"), f"规则 `{pattern.pattern}` 没锚定开头，可能被中间匹配蒙过。"
            assert methods, f"规则 `{pattern.pattern}` 的方法集合是空的 —— 永远不会命中。"
            assert "GET" not in methods, f"规则 `{pattern.pattern}` 把 GET 也锁了 —— 按方法锁的意义就是放开只读。"

        # 相邻但不同的路径不能被误锁
        assert not requires_admin("POST", "/api/v1/collectionsfoo"), (
            "`/api/v1/collectionsfoo` 被 `/api/v1/collections` 的规则误锁了 —— 边界没写对。"
        )
        assert not requires_admin("POST", "/api/v1/projects/abc/fundingXX"), (
            "`/api/v1/projects/{id}/fundingXX` 被 funding 规则误锁了 —— 边界没写对。"
        )

    def test_prefix_rules_still_apply(self) -> None:
        """新增按方法锁不能削弱原有的整前缀锁。"""
        for prefix in ADMIN_ONLY_PREFIXES:
            assert requires_admin("GET", prefix), f"整前缀锁 `{prefix}` 失效了 —— GET 也应当被拦。"
            assert requires_admin("POST", prefix + "/anything"), f"整前缀锁 `{prefix}` 对子路径失效了。"


class TestMiddlewareActuallyEnforcesTheRules:
    """判定函数被中间件真正调用了 —— 端到端发请求验证。

    ⚠️ 这一组是变异测试逼出来的。上面所有断言都只调 `requires_admin(...)`，
    于是把中间件里那一行 `if requires_admin(...)` 改成 `if False:`
    （等于整个管理员鉴权失效、匿名可以打任何端点）之后，**18 条测试全绿**。

    这和本轮早先在 `check_encoding.py` 上踩的坑是同一个：
    **判据写得再对，没接进主流程就等于门禁不存在。**
    区别只是那次删的是 `main()` 里的分支，这次删的是中间件里的分支。

    所以这一组不碰判定函数，只看"发一个真实请求会不会被拦"。
    """

    ADMIN_KEY = "test-admin-key-for-middleware-enforcement"
    TOKEN_SECRET = "test-hmac-secret-for-middleware-enforcement"

    @pytest.fixture
    def auth_client(self, tmp_path, monkeypatch) -> TestClient:
        from app.config import settings
        from app.db import init_db

        monkeypatch.setattr(settings, "db_path", str(tmp_path / "admin_rules.db"))
        monkeypatch.setattr(settings, "api_key", self.ADMIN_KEY)
        monkeypatch.setattr(settings, "auth_token_secret", self.TOKEN_SECRET)
        monkeypatch.setattr(settings, "app_env", "testing")
        init_db()
        return TestClient(create_app(db_override=lambda: None))

    def _anon_token(self, client: TestClient) -> str:
        response = client.post("/api/v1/auth/anonymous", json=None)
        assert response.status_code == 200, f"签发匿名 token 失败：{response.text[:200]}"
        return response.json()["access_token"]

    # (方法, 路径, 请求体) —— 本轮关掉的两个口子，走真实中间件
    CLOSED_HOLES = (
        ("POST", "/api/v1/collections/defillama/trigger", {}),
        ("PATCH", "/api/v1/collections/defillama", {"enabled": False}),
        ("PATCH", "/api/v1/projects/sample-id/funding", {"total_funding_usd": 1}),
    )

    @pytest.mark.parametrize(("method", "path", "body"), CLOSED_HOLES)
    def test_anonymous_request_is_actually_rejected(self, auth_client, method, path, body) -> None:
        token = self._anon_token(auth_client)
        response = auth_client.request(
            method,
            path,
            json=body,
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 403, (
            f"`{method} {path}` 用匿名 token 拿到 {response.status_code}，应当 403。\n"
            "这些端点会花第三方 API 配额或改项目事实数据 —— 实测证据见 app/auth.py 的规则注释。"
        )
        assert response.json()["error"]["code"] == "FORBIDDEN"

    @pytest.mark.parametrize(("method", "path", "body"), CLOSED_HOLES)
    def test_admin_key_still_gets_through(self, auth_client, method, path, body) -> None:
        """反向：管理员必须仍然能用。

        只测"匿名被拦"会让"把这三个端点彻底关掉"也算通过 ——
        那是另一种坏法（运维手动触发采集的能力被无声移除）。
        403/401 才是回归；404/422/500 都说明鉴权已放行、只是业务层的结果。
        """
        response = auth_client.request(method, path, json=body, headers={"X-API-Key": self.ADMIN_KEY})
        assert response.status_code not in (401, 403), (
            f"管理员 key 打 `{method} {path}` 被鉴权挡住了（{response.status_code}）—— 锁多了。"
        )

    def test_read_paths_stay_open_through_the_middleware(self, auth_client) -> None:
        """只读接口在真实请求里也必须对匿名保持开放。"""
        token = self._anon_token(auth_client)
        for path in ("/api/v1/collections/sources", "/api/v1/projects/sample-id/funding"):
            response = auth_client.get(path, headers={"Authorization": f"Bearer {token}"})
            assert response.status_code not in (401, 403), (
                f"匿名 GET `{path}` 被挡住了（{response.status_code}）—— 只有写操作该锁。"
            )


class TestApiSpecDocMatchesReality:
    """`docs/API_SPEC.md` §2.1 那张分布表必须等于实测数字。

    这张表是所有者判断"上线前还要不要收紧"的唯一依据。
    它上一版写着"只有 4 个要求管理员、剩下 17 个匿名可调" —— 那是收紧之前的真相，
    收紧之后如果不同步，读的人会以为口子还开着，或者反过来以为已经全锁了。

    **一份描述安全边界的文档，过时的方向不重要，两个方向都有实际代价。**
    """

    ANCHORS = ("<!-- write-auth-split:begin -->", "<!-- write-auth-split:end -->")

    def _split_block(self) -> str:
        text = API_SPEC.read_text(encoding="utf-8")
        begin, end = self.ANCHORS
        assert begin in text and end in text, (
            f"`{API_SPEC.name}` 里找不到 `{begin}` / `{end}` 锚点 —— 解析器已失效，本组门禁在空转。"
        )
        body = text[text.index(begin) + len(begin) : text.index(end)]
        assert body.strip(), "分布表锚点之间是空的。"
        return body

    def _documented_counts(self) -> dict[str, int]:
        rows = re.findall(r"^\|\s*([^|]+?)\s*\|\s*(\d+)\s*\|\s*$", self._split_block(), re.MULTILINE)
        assert len(rows) >= 3, f"分布表只解析出 {len(rows)} 行（预期 ≥3）—— 表格格式可能已变化。"
        return {label.strip(): int(count) for label, count in rows}

    def test_documented_counts_match_measured(self, openapi_spec) -> None:
        admin = anon = public = 0
        for method, path in _write_operations(openapi_spec):
            if requires_admin(method, _concrete(path)):
                admin += 1
            elif _is_public(path):
                public += 1
            else:
                anon += 1

        documented = self._documented_counts()
        expected = {"管理员专用": admin, "无鉴权（公开）": public, "匿名 token 可调": anon}

        missing = sorted(set(expected) - set(documented))
        assert not missing, f"§2.1 分布表缺少这些行：{missing}。实测分布：{expected}"

        wrong = {k: (documented[k], v) for k, v in expected.items() if documented[k] != v}
        assert not wrong, (
            f"§2.1 分布表与实测不符（文档值, 实际值）：{wrong}。\n"
            "这张表是所有者判断要不要继续收紧的唯一依据，错一个数字就会让人以为口子还开着（或已经全锁了）。"
        )

    def test_total_write_count_in_doc_matches(self, openapi_spec) -> None:
        """正文写的"共 N 个写端点"也必须对。

        分布表三行加起来对、但正文的总数写错，读者第一眼看到的就是错的。
        """
        total = len(_write_operations(openapi_spec))
        text = API_SPEC.read_text(encoding="utf-8")
        section = text[text.index("### 2.1") : text.index("<!-- write-auth-split:end -->")]
        found = re.findall(r"共\s*\*\*(\d+)\s*个\*\*写端点", section)
        assert found, "§2.1 正文里找不到「共 **N 个**写端点」—— 解析器已失效或句式已改。"
        wrong = sorted({n for n in found if int(n) != total})
        assert not wrong, f"§2.1 正文写的写端点总数 {wrong} 与实测 {total} 不符。"

    def test_documented_admin_endpoints_are_actually_admin(self) -> None:
        """§2.1 点名的三个"新收紧"端点，必须真的被锁住。

        反向断言：文档说锁了，代码就必须锁了。
        只比数字的话，"7 个管理员端点"里换掉一个也照样对得上。
        """
        text = API_SPEC.read_text(encoding="utf-8")
        section = text[text.index("#### 收紧的是哪三个") : text.index("#### 剩下 12 个")]
        rows = re.findall(r"^\|\s*`(POST|PATCH|PUT|DELETE)\s+(/[^`]+)`\s*\|", section, re.MULTILINE)
        assert len(rows) == 3, f"§2.1 收紧清单解析出 {len(rows)} 行（预期 3）—— 解析器已失效。"
        for method, path in rows:
            concrete = _concrete("/api/v1" + path if not path.startswith("/api/v1") else path)
            assert requires_admin(method, concrete), (
                f"§2.1 声称 `{method} {path}` 已收紧为管理员专用，但 `requires_admin` 判定放行。"
                "文档说锁了而代码没锁，比两边都没锁更危险 —— 评估风险时会把它算成已处理。"
            )


class TestOperationsRunbookMatchesRules:
    """`docs/OPERATIONS.md` §5.2 的按方法规则表必须与代码一致。

    运维手册里的鉴权表是值班判断"该用哪种凭据"的依据。
    写错的话代价很具体：故障时白试一轮，或者反过来 ——
    以为某个操作匿名就能做，于是把排障步骤写成任何人都能执行。
    """

    ANCHORS = ("<!-- admin-method-rules:begin -->", "<!-- admin-method-rules:end -->")

    def _rules_block(self) -> str:
        text = OPERATIONS.read_text(encoding="utf-8")
        begin, end = self.ANCHORS
        assert begin in text and end in text, (
            f"`{OPERATIONS.name}` 里找不到 `{begin}` / `{end}` 锚点 —— 解析器已失效，本组门禁在空转。"
        )
        body = text[text.index(begin) + len(begin) : text.index(end)]
        assert body.strip(), "按方法规则表的锚点之间是空的。"
        return body

    def test_documented_rules_cover_every_code_rule(self) -> None:
        """代码里每条按方法规则都必须在表里 —— 正向单查发现不了缺行。"""
        block = self._rules_block()
        rows = re.findall(r"^\|\s*`([^`]+)`\s*\|([^|]*)\|([^|]*)\|", block, re.MULTILINE)
        assert len(rows) == len(ADMIN_ONLY_METHOD_RULES), (
            f"§5.2 规则表有 {len(rows)} 行，代码里有 {len(ADMIN_ONLY_METHOD_RULES)} 条规则。\n"
            "少一行意味着值班看不到某个受限路径；多一行意味着他会以为某个操作需要管理员而白绕一圈。"
        )

        documented_paths = [path for path, _, _ in rows]
        for _, pattern in ADMIN_ONLY_METHOD_RULES:
            # 正则形如 `^/api/v1/collections(?:/|$)`；取出可读的路径主干去表里找
            trunk = pattern.pattern.lstrip("^").split("(?:")[0]
            trunk = trunk.replace(r"[^/]+", "{project_id}")
            hit = any(trunk in documented for documented in documented_paths)
            assert hit, (
                f"代码规则 `{pattern.pattern}` 对应的路径 `{trunk}` 在 §5.2 规则表里找不到。\n"
                f"表里现有：{documented_paths}"
            )

    def test_documented_methods_match_code(self) -> None:
        """表里写的"受限方法/开放方法"必须与代码一致。

        只核对路径不核对方法，等于把这张表最有用的那一列放过去 ——
        值班要知道的恰恰是"GET 能不能匿名打"。
        """
        rows = re.findall(r"^\|\s*`([^`]+)`\s*\|([^|]*)\|([^|]*)\|", self._rules_block(), re.MULTILINE)
        assert rows, "§5.2 规则表解析不到任何行 —— 解析器已失效。"
        for path_text, restricted_col, open_col in rows:
            concrete = _concrete(path_text.rstrip("*").rstrip("/"))
            for method in re.findall(r"[A-Z]{3,7}", restricted_col):
                assert requires_admin(method, concrete), (
                    f"§5.2 说 `{method} {path_text}` 受限，但代码放行 —— 文档说锁了而代码没锁。"
                )
            for method in re.findall(r"[A-Z]{3,7}", open_col):
                assert not requires_admin(method, concrete), (
                    f"§5.2 说 `{method} {path_text}` 开放，但代码拦了 —— 值班会以为匿名能打，实际拿 403 却找不到原因。"
                )

    def test_the_hole_is_recorded_as_fixed_not_pending(self) -> None:
        """§12.7 那条"尚未修改"必须已经改掉。

        遗留清单里一条**已经修好但仍写着待办**的记录，会让人重复评估同一个问题；
        更糟的是它会稀释整张清单的可信度 —— 如果这条是假的，其余几条也值得怀疑。
        """
        text = OPERATIONS.read_text(encoding="utf-8")
        anchor = "### 12.7"
        assert anchor in text, f"`{OPERATIONS.name}` 里找不到 §12.7 —— 解析器已失效。"
        start = text.index(anchor)
        end = text.index("### 12.8", start)
        section = text[start:end]
        assert "尚未修改" not in section, (
            "§12.7 仍写着「尚未修改」，但这三个端点已经收紧了。已修好却仍列为待办会被重复评估。"
        )
        assert "已修" in section, "§12.7 没写清它已经修好了 —— 读者无法判断当前状态。"
