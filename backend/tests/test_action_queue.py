"""今日行动队列（跨项目聚合）测试。"""

import json

from app.services.action_queue import build_action_queue, score_action


def _project(
    pid: str,
    *,
    name: str | None = None,
    score: int = 80,
    label: str = "FARM",
    signals: dict | None = None,
) -> dict:
    """构造一行真实存储形态的项目：信号在 meta.signals，顶层没有这些列。

    精选门槛（2026-09-17）要求置信度与 curation_evidence 才能通过；
    旧 fixture 不带这些字段会让所有依赖「能产出行动项」的既有测试被门槛
    拦截，所以默认注入一份达标形态：confidence=1.0 + 有效活动证据。
    """
    now = None
    if signals is None or signals.get("__stale__") is not True:
        from datetime import UTC, datetime, timedelta

        now = datetime.now(UTC)
    signals = {k: v for k, v in (signals or {}).items() if k != "__stale__"}
    return {
        "id": pid,
        "name": name or f"Project {pid}",
        "url": f"https://{pid}.example",
        "score": score,
        "label": label,
        "confidence": 1.0,
        "sector": "ZK",
        "stage": "testnet",
        "meta": json.dumps(
            {
                "signals": signals
                if signals is not None
                else {
                    "has_testnet": True,
                    "has_task_portal": True,
                    "has_docs": True,
                    "explicit_airdrop_mention": True,
                },
                "curation_evidence": [
                    {
                        "kind": "development",
                        "source": "github",
                        "url": f"https://github.com/{pid}/repo",
                        "occurred_at": (now - timedelta(days=3)).isoformat(),
                    },
                    {
                        "kind": "campaign",
                        "source": "galxe",
                        "url": f"https://galxe.com/{pid}/campaign/1",
                        "status": "active",
                        "checked_at": now.isoformat(),
                    },
                ]
                if now is not None
                else [],
            },
            ensure_ascii=False,
        ),
    }


class TestScoreAction:
    def test_priority_dominates_project_score(self):
        """高分项目的 P3 任务不应压过中分项目的 P1 必做项。"""
        low_score_p1 = score_action(
            project_score=60,
            label="FARM",
            priority=1,
            required=True,
            already_engaged=False,
            watchlisted=False,
        )
        high_score_p3 = score_action(
            project_score=100,
            label="FARM",
            priority=3,
            required=False,
            already_engaged=False,
            watchlisted=False,
        )
        assert low_score_p1 > high_score_p3

    def test_farm_outranks_watch_all_else_equal(self):
        farm = score_action(
            project_score=70,
            label="FARM",
            priority=2,
            required=False,
            already_engaged=False,
            watchlisted=False,
        )
        watch = score_action(
            project_score=70,
            label="WATCH",
            priority=2,
            required=False,
            already_engaged=False,
            watchlisted=False,
        )
        assert farm > watch

    def test_engaged_is_penalized_and_watchlist_boosted(self):
        base = dict(
            project_score=70,
            label="FARM",
            priority=2,
            required=False,
            already_engaged=False,
            watchlisted=False,
        )
        assert score_action(**{**base, "already_engaged": True}) < score_action(**base)
        assert score_action(**{**base, "watchlisted": True}) > score_action(**base)


class TestBuildActionQueue:
    def test_ignores_non_actionable_labels(self):
        data = build_action_queue([_project("a", label="IGNORE")], limit=5)
        assert data["items"] == []
        assert data["summary"]["projects_considered"] == 0

    def test_excludes_engaged_projects_by_default(self):
        projects = [_project("a"), _project("b")]
        data = build_action_queue(projects, engaged_project_ids={"a"}, limit=10)
        assert {i["project_id"] for i in data["items"]} == {"b"}
        assert data["summary"]["projects_skipped_engaged"] == 1

    def test_include_engaged_brings_them_back_but_ranked_lower(self):
        # b 分数保持 75+（精选门槛），只靠已参与降权来排序
        projects = [_project("a", score=95), _project("b", score=80)]
        data = build_action_queue(
            projects,
            engaged_project_ids={"a"},
            limit=10,
            include_engaged=True,
        )
        pids = [i["project_id"] for i in data["items"]]
        assert "a" in pids and "b" in pids
        # a 分更高但已参与，应被降权到 b 之后
        assert pids.index("b") < pids.index("a")

    def test_round_robin_spreads_across_projects(self):
        """5 个名额应覆盖 5 个项目，而不是被最高分项目占满。"""
        projects = [_project(f"p{i}", score=90 - i) for i in range(8)]
        data = build_action_queue(projects, limit=5, per_project_limit=3)
        assert data["summary"]["returned"] == 5
        assert data["summary"]["projects_in_queue"] == 5

    def test_per_project_limit_is_respected(self):
        projects = [_project("solo")]
        data = build_action_queue(projects, limit=10, per_project_limit=2)
        assert len(data["items"]) == 2

    def test_only_advancing_categories_are_offered(self):
        """track/social 类不该占用今日名额（每个项目都有，会刷满清单）。"""
        projects = [_project(f"p{i}") for i in range(5)]
        data = build_action_queue(projects, limit=20, per_project_limit=10)
        cats = {i["category"] for i in data["items"]}
        assert "track" not in cats
        assert "social" not in cats
        assert cats  # 至少有推进类任务

    def test_result_is_deterministic(self):
        projects = [_project(f"p{i}", score=80) for i in range(6)]
        first = build_action_queue(projects, limit=5)
        second = build_action_queue(projects, limit=5)
        assert [i["task_id"] for i in first["items"]] == [i["task_id"] for i in second["items"]]
        assert [i["project_id"] for i in first["items"]] == [i["project_id"] for i in second["items"]]

    def test_meta_signals_drive_task_selection(self):
        """信号不同的项目应产出不同任务（回归：signals 曾恒被读成 False）。"""
        rich = _project(
            "rich",
            signals={
                "has_testnet": True,
                "has_task_portal": True,
                "explicit_airdrop_mention": True,
            },
        )
        bare = _project("bare", signals={})
        data = build_action_queue([rich, bare], limit=20, per_project_limit=10)
        rich_tasks = {i["task_id"] for i in data["items"] if i["project_id"] == "rich"}
        bare_tasks = {i["task_id"] for i in data["items"] if i["project_id"] == "bare"}
        assert rich_tasks != bare_tasks
        assert "official-task-portal" in rich_tasks
        assert "official-task-portal" not in bare_tasks

    def test_limit_zero_returns_empty(self):
        data = build_action_queue([_project("a")], limit=0)
        assert data["items"] == []
        assert data["summary"]["returned"] == 0

    def test_empty_input_is_safe(self):
        data = build_action_queue([], limit=5)
        assert data["items"] == []
        assert data["summary"]["candidates"] == 0

    def test_rows_without_id_are_skipped(self):
        data = build_action_queue([{"id": "", "label": "FARM", "score": 90}], limit=5)
        assert data["items"] == []


class TestSkipExclusion:
    """用户标记「不参与」的项目不得出现在今日行动里 —— 工作台列表已隐藏它，
    这里再钻进 action queue，等于把决定踩在用户脸上。"""

    def test_skipped_project_is_excluded(self):
        projects = [
            _project("a", signals={
                "has_testnet": True,
                "has_task_portal": True,
                "has_docs": True,
            }),
            {**_project(
                "b",
                signals={
                    "has_testnet": True,
                    "has_task_portal": True,
                    "has_docs": True,
                },
            ), "skipped": True},
        ]
        data = build_action_queue(projects, limit=10)
        names = {item["project_id"] for item in data["items"]}
        assert "a" in names
        assert "b" not in names, "skipped 项目不该出现在今日行动"


class TestCuratedGate:
    """精选门槛：未达精选标准的项目不得进入行动队列候选。

    用户诉求（2026-09-17）：所有项目都没达标时，推荐型卡片必须为空，
    而不是退而展示次优。build_action_queue 的输入由路由层给，这里直接断言
    「未达标行被过滤」这一层的行为。
    """

    def test_uncurated_project_produces_no_items(self):
        from app.services.project_signals import curation_reasons

        # 高分 FARM 但无活动证据（真实库的普遍形态）：
        # __stale__ 让 fixture 不注入 curation_evidence
        p = _project(
            "uncurated",
            score=95,
            signals={"__stale__": True, "has_testnet": True, "has_task_portal": True},
        )
        assert curation_reasons(p), "fixture 必须是未达标形态，否则测试无效"
        data = build_action_queue([p], limit=5)
        assert data["items"] == []

    def test_curated_project_still_produces_items(self):
        from datetime import UTC, datetime, timedelta

        now = datetime.now(UTC)
        p = _project(
            "curated",
            score=90,
            signals={
                "has_testnet": True,
                "has_task_portal": True,
                "has_docs": True,
                "explicit_airdrop_mention": True,
                "github_recent_push_days": 5,
                "has_github": True,
            },
        )
        import json as _json

        meta = _json.loads(p["meta"])
        meta["curation_evidence"] = [
            {
                "kind": "development",
                "source": "github",
                "url": "https://github.com/org/repo",
                "occurred_at": (now - timedelta(days=5)).isoformat(),
            },
            {
                "kind": "campaign",
                "source": "galxe",
                "url": "https://galxe.com/s/c/1",
                "status": "active",
                "checked_at": now.isoformat(),
            },
        ]
        p["meta"] = _json.dumps(meta)
        p["confidence"] = 0.9
        data = build_action_queue([p], limit=5)
        assert any(i["project_id"] == "curated" for i in data["items"])
