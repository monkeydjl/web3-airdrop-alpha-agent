"""`GET /api/v1/scheduler/jobs` —— 调度器任务表只读诊断端点。

## 这个端点存在的理由

归档功能从上线到 2026-08-24 **一次都没被触发过**，而这件事是靠翻数据库
（`archive_runs` 表 0 行）才发现的。`UnifiedScheduler.get_jobs()` 一直存在，
返回每个任务的 `next_run_time` —— 但没有任何路由暴露它，
所以运维台看不到任务表，"`archive_cleanup` 不在列表里"这个一眼可见的事实
没有任何地方可见。

## 本文件的核心断言：三种"空"必须分得开

「任务表是空的」有三种原因，处置动作完全不同：

| 原因 | `scheduler_state` | 该怎么办 |
|---|---|---|
| 没构造调度器（testing） | `not_initialized` | 正常 |
| 三个开关全关 | `disabled` | 查 `.env` |
| 开关开了但注册出错 | `running` + `jobs` 空 | **真故障**，查启动日志 |
| 读取本身失败 | `read_error` | 诊断接口自己坏了 |

只返回 `{"jobs": []}` 的话这几种长得一模一样 —— 而其中一种是生产事故。
这是本项目反复出现的同一条教训：**静默的错误状态比明确的空状态坏得多。**

`job_count` 与 `missing_jobs` 在 `read_error` 时必须是 `None` 而不是
`0` / `[]`：读不出来和"确实没有"是两件事，两者都返回 0 会让一个坏掉的
诊断接口看起来像一个空闲的调度器。
"""

from __future__ import annotations

import re
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from app.config import settings
from app.db import init_db
from app.main import create_app

ADMIN_KEY = "test-admin-key-0123456789abcdef"
TOKEN_SECRET = "test-hmac-secret-for-scheduler-jobs"

ENDPOINT = "/api/v1/scheduler/jobs"


@pytest.fixture
def client(tmp_path, monkeypatch):
    """无鉴权客户端（MVP 模式），用于测响应内容本身。"""
    monkeypatch.setattr(settings, "db_path", str(tmp_path / "sched_jobs.db"))
    monkeypatch.setattr(settings, "api_key", "")
    monkeypatch.setattr(settings, "app_env", "testing")
    init_db()
    app = create_app(db_override=lambda: None)
    return TestClient(app)


@pytest.fixture
def auth_client(tmp_path, monkeypatch):
    """开启鉴权的客户端，用于测管理员锁。"""
    monkeypatch.setattr(settings, "db_path", str(tmp_path / "sched_jobs_auth.db"))
    monkeypatch.setattr(settings, "api_key", ADMIN_KEY)
    monkeypatch.setattr(settings, "auth_token_secret", TOKEN_SECRET)
    monkeypatch.setattr(settings, "auth_token_ttl_hours", 72)
    monkeypatch.setattr(settings, "app_env", "testing")
    init_db()
    app = create_app(db_override=lambda: None)
    return TestClient(app)


def _fake_scheduler(jobs, *, running=True):
    """构造一个只提供 get_jobs() / scheduler.running 的替身。"""
    fake = MagicMock()
    fake.get_jobs.return_value = jobs
    fake.scheduler.running = running
    return fake


def _install(monkeypatch, client, scheduler) -> None:
    """把替身装到 `app.state` 上。

    必须带 `raising=False`：`app_env == "testing"` 时启动流程根本不构造
    调度器，`app.state` 上**没有** `unified_scheduler` 这个属性，
    默认的 `monkeypatch.setattr` 会直接 AttributeError。

    （本会话另一处踩过反向的坑：`raising=False` 用在**拼错的属性名**上会
    静默无事发生，测试照样绿。所以这个 helper 只用于一个已知会缺失的属性，
    且集中在一处 —— 不在九个测试里各写一遍 `raising=False`。）
    """
    monkeypatch.setattr(client.app.state, "unified_scheduler", scheduler, raising=False)


def _data(response) -> dict:
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["ok"] is True
    return payload["data"]


class TestEndpointIsRegistered:
    def test_endpoint_exists(self, client):
        """先确认路由真的挂上了 —— 404 会让下面每条断言都变成空转。"""
        assert client.get(ENDPOINT).status_code == 200

    def test_endpoint_is_in_openapi(self, client):
        paths = client.get("/openapi.json").json()["paths"]
        assert ENDPOINT in paths, f"{ENDPOINT} 没进 OpenAPI —— 前端与文档都看不到它。"
        assert "get" in paths[ENDPOINT]


class TestThreeKindsOfEmptyAreDistinguishable:
    """本文件最重要的一组。四种状态两两之间必须能区分。"""

    def test_not_initialized_when_scheduler_absent(self, client):
        """testing 环境不构造调度器 → 必须报 not_initialized，而不是空数组。"""
        data = _data(client.get(ENDPOINT))
        expected_state = "not_initialized"
        assert data["scheduler_state"] == expected_state
        assert data["jobs"] == []
        assert data["note"], "not_initialized 必须附一句说明，否则读的人不知道这是否正常。"

    def test_disabled_is_distinct_from_not_initialized(self, client, monkeypatch):
        """调度器存在但没 running（三个开关全关）→ disabled。"""
        _install(monkeypatch, client, _fake_scheduler([], running=False))
        data = _data(client.get(ENDPOINT))
        expected_state = "disabled"
        assert data["scheduler_state"] == expected_state
        assert data["running"] is False
        # 与 not_initialized 必须不是同一个值
        assert data["scheduler_state"] != "not_initialized"

    def test_running_but_empty_is_the_real_failure(self, client, monkeypatch):
        """开关开着、调度器在跑，却一个任务都没注册 —— 这是真故障。

        它必须与"全关了"区分得开，否则一次注册失败会被读成"配置就是这样"。
        """
        monkeypatch.setattr(settings, "scheduler_enabled", True)
        monkeypatch.setattr(settings, "archive_scheduler_enabled", True)
        monkeypatch.setattr(settings, "collection_scheduler_enabled", False)
        _install(monkeypatch, client, _fake_scheduler([], running=True))

        data = _data(client.get(ENDPOINT))
        expected_state = "running"
        expected_missing = 2
        assert data["scheduler_state"] == expected_state
        assert data["job_count"] == 0
        # 应当注册 2 个（分析 + 归档），实际 0 个 → missing 必须点出来
        assert data["expected_job_count"] == expected_missing
        assert sorted(data["missing_jobs"]) == ["analysis_run_queue", "archive_cleanup"]

    def test_read_error_never_looks_like_zero(self, client, monkeypatch):
        """读取失败时 job_count 必须是 None，missing_jobs 也是 None。

        这是 `/api/v1/llm/status` 那条教训的复用：读不出来返回 0，
        会让一个坏掉的账本看起来像一个还没花钱的账本。
        """
        broken = MagicMock()
        broken.scheduler.running = True
        broken.get_jobs.side_effect = RuntimeError("scheduler is wedged")
        _install(monkeypatch, client, broken)

        data = _data(client.get(ENDPOINT))
        expected_state = "read_error"
        assert data["scheduler_state"] == expected_state
        assert data["read_error"] and "wedged" in data["read_error"]
        assert data["job_count"] is None, "读失败时 job_count 返回 0 会被当成「没有任务」。"
        assert data["missing_jobs"] is None, "读失败时 missing_jobs 返回 [] 会被当成「什么都不缺」。"


class TestJobsArePresentedUsefully:
    def test_jobs_carry_owner_switch(self, client, monkeypatch):
        """每个任务要说明它由哪个开关控制。

        运维看到"任务不在表里"后，下一个问题必然是"那我该开哪个开关" ——
        答案直接放进响应，而不是让人回去翻文档。
        """
        jobs = [
            {"id": "archive_cleanup", "name": "归档清理", "next_run_time": "2026-08-26T03:00:00+00:00"},
            {"id": "collect_defillama", "name": "采集 defillama", "next_run_time": "2026-08-26T08:00:00+00:00"},
            {"id": "analysis_run_queue", "name": "每日分析", "next_run_time": "2026-08-26T08:00:00+00:00"},
        ]
        _install(monkeypatch, client, _fake_scheduler(jobs))

        data = _data(client.get(ENDPOINT))
        by_id = {job["id"]: job for job in data["jobs"]}
        assert by_id["archive_cleanup"]["owner_switch"] == "ARCHIVE_SCHEDULER_ENABLED"
        assert by_id["collect_defillama"]["owner_switch"] == "COLLECTION_SCHEDULER_ENABLED"
        assert by_id["analysis_run_queue"]["owner_switch"] == "SCHEDULER_ENABLED"

    def test_jobs_sorted_by_next_run(self, client, monkeypatch):
        """按下次运行时间排序 —— 运维想知道的是"接下来会发生什么"。"""
        jobs = [
            {"id": "late", "name": "b", "next_run_time": "2026-08-26T20:00:00+00:00"},
            {"id": "early", "name": "a", "next_run_time": "2026-08-26T03:00:00+00:00"},
        ]
        _install(monkeypatch, client, _fake_scheduler(jobs))
        data = _data(client.get(ENDPOINT))
        assert [job["id"] for job in data["jobs"]] == ["early", "late"]

    def test_job_with_no_next_run_sorts_last_and_does_not_crash(self, client, monkeypatch):
        """`next_run_time` 可以是 None（paused job）—— 不能因此 500。"""
        jobs = [
            {"id": "paused", "name": "p", "next_run_time": None},
            {"id": "active", "name": "a", "next_run_time": "2026-08-26T03:00:00+00:00"},
        ]
        _install(monkeypatch, client, _fake_scheduler(jobs))
        data = _data(client.get(ENDPOINT))
        assert [job["id"] for job in data["jobs"]] == ["active", "paused"]

    def test_switches_report_real_config(self, client, monkeypatch):
        """四个开关的值必须来自 settings，不是写死的。"""
        monkeypatch.setattr(settings, "scheduler_enabled", False)
        monkeypatch.setattr(settings, "collection_scheduler_enabled", True)
        monkeypatch.setattr(settings, "archive_scheduler_enabled", False)
        monkeypatch.setattr(settings, "collection_auto_run_enabled", True)

        data = _data(client.get(ENDPOINT))
        assert data["switches"] == {
            "SCHEDULER_ENABLED": False,
            "COLLECTION_SCHEDULER_ENABLED": True,
            "ARCHIVE_SCHEDULER_ENABLED": False,
            "COLLECTION_AUTO_RUN_ENABLED": True,
        }

    def test_timezone_is_reported(self, client):
        """cron 时刻没有时区就没有意义 —— 一个 `0 3 * * *` 在不同时区差好几小时。"""
        data = _data(client.get(ENDPOINT))
        assert data["timezone"] == settings.timezone


class TestMissingJobsDetection:
    """ "应当注册却没注册"是这个端点最有价值的一栏 —— 归档那次事故的形态。"""

    def test_archive_missing_is_reported(self, client, monkeypatch):
        """开关开着但归档任务不在表里 → 必须出现在 missing_jobs。"""
        monkeypatch.setattr(settings, "archive_scheduler_enabled", True)
        monkeypatch.setattr(settings, "scheduler_enabled", False)
        monkeypatch.setattr(settings, "collection_scheduler_enabled", False)
        jobs = [{"id": "analysis_run_queue", "name": "x", "next_run_time": None}]
        _install(monkeypatch, client, _fake_scheduler(jobs))

        data = _data(client.get(ENDPOINT))
        assert "archive_cleanup" in data["missing_jobs"], (
            "归档开关开着、任务没注册，却没报缺失 —— 这正是 2026-08-24 之前查不出来的那个状态。"
        )

    def test_nothing_missing_when_all_registered(self, client, monkeypatch):
        monkeypatch.setattr(settings, "archive_scheduler_enabled", True)
        monkeypatch.setattr(settings, "scheduler_enabled", True)
        monkeypatch.setattr(settings, "collection_scheduler_enabled", False)
        jobs = [
            {"id": "analysis_run_queue", "name": "x", "next_run_time": None},
            {"id": "archive_cleanup", "name": "y", "next_run_time": None},
        ]
        _install(monkeypatch, client, _fake_scheduler(jobs))

        data = _data(client.get(ENDPOINT))
        assert data["missing_jobs"] == []

    def test_disabled_switch_means_not_missing(self, client, monkeypatch):
        """开关关掉时，任务不在表里是**正常**的，不该报缺失。

        方向搞反会让这一栏天天亮红灯，然后被人忽略 —— 那比没有这一栏更坏。
        """
        monkeypatch.setattr(settings, "archive_scheduler_enabled", False)
        monkeypatch.setattr(settings, "scheduler_enabled", False)
        monkeypatch.setattr(settings, "collection_scheduler_enabled", False)
        _install(monkeypatch, client, _fake_scheduler([], running=True))

        data = _data(client.get(ENDPOINT))
        assert data["missing_jobs"] == []
        assert data["expected_job_count"] == 0


class TestJobIdsMatchTheScheduler:
    """任务 id 必须与 `app/scheduler.py` 里 `add_job(id=...)` 的字面量一致。

    ## 这组测试是踩坑之后加的

    上面那些用 MagicMock 替身的测试全绿。然后拿真后端一打，立刻露出两个错：

    1. 分析任务的 id 我凭印象写成 `daily_analysis`，
       真实是 **`analysis_run_queue`**（`scheduler.py:246`）。
    2. `owner_switch` 因此对它返回 `unknown`。

    **替身会照着我的误解回答我** —— 我在假数据里写了 `daily_analysis`，
    断言就拿 `daily_analysis` 去比，两边同一个错，测试当然绿。

    所以这里不靠记性：直接从 `scheduler.py` 源码里抽出所有 `id="..."`，
    与本路由的映射表核对。判据来自被测对象本身，而不是我对它的记忆。
    """

    @staticmethod
    def _scheduler_job_ids() -> set[str]:
        """从 scheduler.py 源码里抽出所有静态 add_job id。

        采集任务的 id 是 f-string（`f"collect_{source_id}"`），抽不出字面量，
        所以这里只取静态的那些 —— 那也正是 `_JOB_OWNER` 该覆盖的部分。
        """
        source = (Path(__file__).resolve().parents[2] / "app" / "scheduler.py").read_text(encoding="utf-8")
        ids = set(re.findall(r'\n\s+id="([a-z_]+)"', source))
        assert ids, "从 scheduler.py 抽不到任何 add_job id —— 解析器失效，先修这里再信结论。"
        return ids

    def test_owner_map_covers_every_static_job_id(self):
        from app.routers.v1.scheduler import _JOB_OWNER

        real = self._scheduler_job_ids()
        unmapped = sorted(real - set(_JOB_OWNER))
        assert not unmapped, (
            f"这些任务在 scheduler.py 里注册，但 _JOB_OWNER 没有映射：{unmapped}\n"
            "缺映射的后果是 owner_switch 返回 'unknown'，运维不知道该去开哪个开关。"
        )

    def test_owner_map_has_no_phantom_ids(self):
        """反向：映射表里不能有 scheduler.py 根本不注册的 id。

        这一条抓的正是我犯的那个错 —— `daily_analysis` 是我编的名字。
        **一个幻影 id 比缺一个更坏**：它让 `missing_jobs` 永远报缺失。
        """
        from app.routers.v1.scheduler import _JOB_OWNER

        real = self._scheduler_job_ids()
        phantom = sorted(set(_JOB_OWNER) - real)
        assert not phantom, (
            f"_JOB_OWNER 里这些 id 在 scheduler.py 里并不存在：{phantom}\n"
            "它们会让 missing_jobs 永远报缺失 —— 一栏天天亮红灯等于没有这一栏。"
        )

    def test_analysis_job_id_is_the_real_one(self):
        """把这个具体的 id 钉死，因为它是实测抓出来的那个错。"""
        from app.routers.v1.scheduler import _JOB_OWNER

        assert "analysis_run_queue" in _JOB_OWNER
        assert _JOB_OWNER["analysis_run_queue"] == "SCHEDULER_ENABLED"
        assert "daily_analysis" not in _JOB_OWNER, "`daily_analysis` 是凭印象编出来的名字，scheduler.py 里没有。"


class TestExpectedCollectionJobsFollowRegistry:
    """采集任务的"应当注册"必须问 registry，不能只看总开关。

    第一版只要总开关为真就把 10 个源全列进"应当"，而
    `scheduler.py:121` 的真实条件是 `if collector and collector.is_enabled()` ——
    **没配 API key 的源不会注册，那是正常的**。实测因此报出 5 个假缺失。

    这个方向的错比漏报更坏：一栏天天亮红灯的告警，等于没有这一栏。
    人会先学会忽略它，然后在真出事那天照样忽略。
    """

    @staticmethod
    def _registry_with(*source_ids):
        registry = MagicMock()
        collectors = []
        for sid in source_ids:
            collector = MagicMock()
            collector.source_id = sid
            collectors.append(collector)
        registry.list_enabled.return_value = collectors
        return registry

    def test_only_enabled_collectors_count_as_expected(self, client, monkeypatch):
        monkeypatch.setattr(settings, "collection_scheduler_enabled", True)
        monkeypatch.setattr(settings, "scheduler_enabled", False)
        monkeypatch.setattr(settings, "archive_scheduler_enabled", False)
        monkeypatch.setattr(
            client.app.state,
            "collector_registry",
            self._registry_with("defillama", "github"),
            raising=False,
        )
        jobs = [
            {"id": "collect_defillama", "name": "x", "next_run_time": None},
            {"id": "collect_github", "name": "y", "next_run_time": None},
        ]
        _install(monkeypatch, client, _fake_scheduler(jobs))

        data = _data(client.get(ENDPOINT))
        expected_count = 2
        assert data["expected_job_count"] == expected_count, (
            "只有 2 个采集器启用，却期望更多 —— 未配置的源被误算成「应当注册」。"
        )
        assert data["missing_jobs"] == []

    def test_disabled_collector_is_not_reported_missing(self, client, monkeypatch):
        """registry 里没有 galxe（未配置）→ 它不在表里是正常的。"""
        monkeypatch.setattr(settings, "collection_scheduler_enabled", True)
        monkeypatch.setattr(settings, "scheduler_enabled", False)
        monkeypatch.setattr(settings, "archive_scheduler_enabled", False)
        monkeypatch.setattr(
            client.app.state,
            "collector_registry",
            self._registry_with("defillama"),
            raising=False,
        )
        _install(
            monkeypatch,
            client,
            _fake_scheduler([{"id": "collect_defillama", "name": "x", "next_run_time": None}]),
        )

        data = _data(client.get(ENDPOINT))
        assert "collect_galxe" not in (data["missing_jobs"] or []), (
            "未配置的采集源被报成缺失 —— 这一栏会天天亮红灯，然后被人忽略。"
        )

    def test_enabled_collector_missing_from_scheduler_is_reported(self, client, monkeypatch):
        """registry 说启用了，但调度器里没有 → 这是真缺失，必须报。"""
        monkeypatch.setattr(settings, "collection_scheduler_enabled", True)
        monkeypatch.setattr(settings, "scheduler_enabled", False)
        monkeypatch.setattr(settings, "archive_scheduler_enabled", False)
        monkeypatch.setattr(
            client.app.state,
            "collector_registry",
            self._registry_with("defillama", "github"),
            raising=False,
        )
        _install(
            monkeypatch,
            client,
            _fake_scheduler([{"id": "collect_defillama", "name": "x", "next_run_time": None}]),
        )

        data = _data(client.get(ENDPOINT))
        assert data["missing_jobs"] == ["collect_github"]

    def test_registry_failure_does_not_invent_missing_jobs(self, client, monkeypatch):
        """问不出 registry 时不猜 —— 宁可少报，也不报一堆不存在的缺失。"""
        monkeypatch.setattr(settings, "collection_scheduler_enabled", True)
        monkeypatch.setattr(settings, "scheduler_enabled", False)
        monkeypatch.setattr(settings, "archive_scheduler_enabled", False)
        broken_registry = MagicMock()
        broken_registry.list_enabled.side_effect = RuntimeError("registry exploded")
        monkeypatch.setattr(client.app.state, "collector_registry", broken_registry, raising=False)
        _install(monkeypatch, client, _fake_scheduler([]))

        data = _data(client.get(ENDPOINT))
        assert data["missing_jobs"] == []
        assert data["expected_job_count"] == 0


class TestEndpointIsAdminOnly:
    """这张表暴露全部 cron 时刻与哪些自动化是关着的 —— 与 /settings 同级。"""

    def test_no_token_returns_401(self, auth_client):
        assert auth_client.get(ENDPOINT).status_code == 401

    def test_anonymous_token_returns_403(self, auth_client):
        anon = auth_client.post("/api/v1/auth/anonymous")
        assert anon.status_code == 200, anon.text
        # 字段名是 `access_token`（不是 `token`）—— 这个端点是**扁平**响应，
        # 不走 {ok, data} 信封，所以也不能写 .json()["data"]["access_token"]。
        token = anon.json()["access_token"]

        r = auth_client.get(ENDPOINT, headers={"Authorization": f"Bearer {token}"})
        assert r.status_code == 403, (
            f"匿名 token 拿到 {r.status_code} —— 这张表是「系统几点在干活、哪些自动化关着」的地图。"
        )
        assert r.json()["error"]["code"] == "FORBIDDEN"

    def test_admin_key_allowed(self, auth_client):
        r = auth_client.get(ENDPOINT, headers={"X-API-Key": ADMIN_KEY})
        assert r.status_code == 200, r.text
        assert r.json()["ok"] is True
