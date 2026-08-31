"""回测执行器与校准分桶的 golden 断言（ACTION_LOOP_DESIGN §6 T3.2-3）。

这批测试守三件事：

1. **回测确实跑通并给出合理结论** —— 数据集里的知名空投项目不能被引擎判成
   IGNORE。这不是「凑绿」，而是最低限度的清醒检查：如果 EigenLayer /
   LayerZero 这种级别的项目都拿不到 FARM，说明规则引擎的默认权重已经跑偏，
   任何线上分数都不可信。

2. **门槛常量没被偷偷调低** —— 引入 backtest 桶之后，最大的诱惑是「反正
   有 200 条回测样本了，把门槛降一点就能切权重」。见 test_calibration.py
   的 test_gate_constants_not_lowered，这里再补一层：确认门禁只数 live 桶。

3. **两个桶不会混算** —— 这是 §4.3 的核心约束。回测样本能验证引擎在历史
   项目上的表现，但不能替代真实用户反馈去解锁权重切换。
"""

from __future__ import annotations

import asyncio
import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

import pytest

from app.calibration import (
    MIN_FARM_SAMPLES,
    MIN_VALID_SAMPLES,
    SOURCE_BACKTEST,
    SOURCE_LIVE,
    CalibrationSample,
    check_gate,
    count_by_source,
)

BACKEND_DIR = Path(__file__).resolve().parents[1]
SCRIPT_PATH = BACKEND_DIR / "scripts" / "run_backtest.py"
DATASET_PATH = BACKEND_DIR / "data" / "backtest" / "airdrops_2024_2025.json"


def _load_script() -> Any:
    """scripts/ 不是包，用 spec 直接加载模块文件。

    不走 `from scripts.run_backtest import ...` —— scripts 目录没有
    __init__.py，且脚本自身会改 sys.path，import 顺序容易踩坑。
    """
    spec = importlib.util.spec_from_file_location("run_backtest_mod", SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["run_backtest_mod"] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def bt() -> Any:
    return _load_script()


@pytest.fixture(scope="module")
def dataset(bt: Any) -> dict[str, Any]:
    return bt.load_dataset(DATASET_PATH)


@pytest.fixture(scope="module")
def run_output(bt: Any, dataset: dict[str, Any]) -> tuple[list[Any], dict[str, Any]]:
    """跑一次真实回测，全模块共享结果。

    规则引擎是纯函数（enable_llm=False），同一数据集必然给同一结果，
    所以缓存到 module 级别没有隔离问题，也省掉 15 次重复评分。
    """
    results = asyncio.run(bt.run_cases(dataset))
    return results, bt.summarize(results)


# ── 数据集自身的完整性 ────────────────────


class TestDataset:
    def test_dataset_file_exists(self) -> None:
        """数据集缺失必须报错，不能静默跑出「0 条全绿」的假报告。"""
        assert DATASET_PATH.exists(), f"回测数据集丢失: {DATASET_PATH}"

    def test_missing_dataset_raises(self, bt: Any, tmp_path: Path) -> None:
        with pytest.raises(FileNotFoundError):
            bt.load_dataset(tmp_path / "nope.json")

    def test_every_case_has_provenance(self, dataset: dict[str, Any]) -> None:
        """每条样本都要能追溯来源与置信度。

        没有 provenance 的历史数据等于凭记忆编的，用它调权重就是拿噪声
        当信号。confidence 标 medium 的样本在报告里会被显式标注。
        """
        for case in dataset["projects"]:
            assert case.get("provenance"), f"{case.get('name')} 缺 provenance"
            assert case.get("confidence") in {"high", "medium"}, case.get("name")

    def test_pending_expansion_is_declared(self, dataset: dict[str, Any]) -> None:
        """15 条 ≠ 50 条，数据集必须自己承认没补全。

        这个标记会让报告打警告。哪天真补到 target_size，改掉标记的人
        自然会看到这条测试，不会出现「悄悄改成 true 就当补全了」。
        """
        assert dataset.get("target_size") == 50
        if len(dataset["projects"]) < dataset["target_size"]:
            assert dataset.get("pending_expansion") is True

    def test_has_negative_sample(self, dataset: dict[str, Any]) -> None:
        """至少要有一个「看起来很强但没发币」的负样本。

        全正样本的数据集只能验证召回，测不出误报 —— 那样的回测会给出
        虚高的安全感。
        """
        negatives = [c for c in dataset["projects"] if not (c.get("outcome") or {}).get("airdropped")]
        assert negatives, "数据集缺负样本，无法评估误报"


# ── 回测结论的 golden 断言 ────────────────────


class TestBacktestGolden:
    def test_all_cases_scored(self, run_output: tuple[list[Any], dict[str, Any]], dataset: dict[str, Any]) -> None:
        results, _ = run_output
        assert len(results) == len(dataset["projects"])
        unscored = [r.name for r in results if r.score is None]
        assert not unscored, f"未评分样本: {unscored}"

    def test_no_known_airdrop_is_ignored(self, run_output: tuple[list[Any], dict[str, Any]]) -> None:
        """确有空投的项目一个都不能判 IGNORE。

        漏判是这个系统最贵的错 —— WATCH 还算「再看看」，IGNORE 是直接
        把机会扔掉。这条红了说明权重跑偏，先查引擎再改测试。
        """
        results, _ = run_output
        ignored = [r.name for r in results if r.airdropped and r.label == "IGNORE"]
        assert not ignored, f"知名空投被判 IGNORE: {ignored}"

    def test_recall_is_high(self, run_output: tuple[list[Any], dict[str, Any]]) -> None:
        """召回率下限 0.7。

        数据集全是事后已知的大空投，引擎在这批上的召回本该很高。定
        0.7 而不是 1.0 是留出权重迭代的空间：单个项目掉到 WATCH 可以
        接受，成批掉下去不行。
        """
        _, summary = run_output
        assert summary["recall_farm"] is not None
        assert summary["recall_farm"] >= 0.7, f"召回率过低: {summary['recall_farm']}"

    def test_scores_in_valid_range(self, run_output: tuple[list[Any], dict[str, Any]]) -> None:
        results, _ = run_output
        for r in results:
            assert r.score is not None
            assert 0 <= r.score <= 100, f"{r.name} 分数越界: {r.score}"

    def test_hit_miss_fp_are_mutually_exclusive(self, run_output: tuple[list[Any], dict[str, Any]]) -> None:
        """一条样本不能同时是命中和漏判。

        三个属性都是从 airdropped + label 推的，逻辑写错时会同时为真，
        那样命中率统计会凭空多算。
        """
        results, _ = run_output
        for r in results:
            flags = [r.hit, r.miss, r.false_positive]
            assert sum(1 for f in flags if f) <= 1, f"{r.name} 状态互斥性被破坏: {flags}"

    def test_summary_counts_are_consistent(self, run_output: tuple[list[Any], dict[str, Any]]) -> None:
        """汇总数字之间要自洽，不能各算各的。"""
        results, summary = run_output
        assert summary["total"] == len(results)
        assert summary["airdropped_count"] + summary["not_airdropped_count"] == summary["total"]
        assert summary["farm_hits"] + summary["farm_misses"] == summary["airdropped_count"]

    def test_negative_shortage_is_flagged(self, run_output: tuple[list[Any], dict[str, Any]]) -> None:
        """负样本不足时汇总必须自己举手。

        当前 14 正 / 1 负，fpr 分母是 1，那个百分数毫无意义。报告靠这个
        标记打警告；标记丢了，误报率就会被当成真数字去调权重。
        """
        _, summary = run_output
        expected = summary["not_airdropped_count"] < 5
        assert summary["negative_sample_shortage"] is expected


class TestExportIdempotency:
    """导出必须幂等（同一结论重复跑不重复写）。

    回测是会被反复执行的：换数据集、调权重后都要再跑一遍。不去重的话每跑
    一次 backtest 桶就多一份相同结论，分桶计数随执行次数虚增。门禁只数
    live 桶所以不会污染权重切换，但统计会失真到没法用。
    """

    def test_repeat_export_writes_nothing_new(self, bt: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        import app.db as db_module
        from app.config import settings

        # 与 test_admin_only_rules.py 同款写法：patch settings.db_path 到 tmp_path，
        # 绝不让测试碰生产库。
        monkeypatch.setattr(settings, "db_path", str(tmp_path / "export_probe.db"))
        db_module.init_db()

        # 造一个 projects 行让导出有落点：export_samples 只写已存在于 projects
        # 表的项目（回测项目本身不入库）。
        with db_module.get_connection() as conn:
            conn.execute(
                "INSERT INTO projects (id, name, source, score, label) VALUES (?, ?, ?, ?, ?)",
                ("p-eigen", "EigenLayer", "test", 84, "FARM"),
            )
            conn.commit()

        results = [
            bt.CaseResult(
                name="EigenLayer",
                sector="restaking",
                airdropped=True,
                magnitude="large",
                confidence="high",
                score=84,
                label="FARM",
                sub_scores={},
                reason=[],
            )
        ]

        assert bt.export_samples(results, "backtest") == 1
        # 第二次同样输入必须一条都不写
        assert bt.export_samples(results, "backtest") == 0

        with db_module.get_connection() as conn:
            n = conn.execute("SELECT COUNT(*) AS n FROM roi_outcomes").fetchone()["n"]
        assert n == 1, f"重复导出产生了 {n} 行"

    def test_exported_rows_are_backtest_source(self, bt: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """导出的行必须落在 backtest 桶。

        写成 live 会让回测结论混进门禁统计 —— 那正是 §4.3 要防的事。
        """
        import app.db as db_module
        from app.config import settings

        monkeypatch.setattr(settings, "db_path", str(tmp_path / "source_probe.db"))
        db_module.init_db()
        with db_module.get_connection() as conn:
            conn.execute(
                "INSERT INTO projects (id, name, source, score, label) VALUES (?, ?, ?, ?, ?)",
                ("p-x", "Celestia", "test", 81, "FARM"),
            )
            conn.commit()

        results = [
            bt.CaseResult(
                name="Celestia",
                sector="DA",
                airdropped=True,
                magnitude="large",
                confidence="high",
                score=81,
                label="FARM",
                sub_scores={},
                reason=[],
            )
        ]
        bt.export_samples(results, "backtest")

        with db_module.get_connection() as conn:
            rows = conn.execute("SELECT source, event FROM roi_outcomes").fetchall()
        assert len(rows) == 1
        assert rows[0]["source"] == "backtest"
        assert rows[0]["event"] == "airdrop_received"


class TestReportOutput:
    def test_report_warns_on_pending_dataset(
        self, bt: Any, dataset: dict[str, Any], run_output: tuple[list[Any], dict[str, Any]]
    ) -> None:
        results, summary = run_output
        text = bt.format_report(dataset, results, summary)
        assert "pending_expansion" in text
        assert "选择偏差" in text
        assert "source=backtest" in text

    def test_report_marks_medium_confidence(
        self, bt: Any, dataset: dict[str, Any], run_output: tuple[list[Any], dict[str, Any]]
    ) -> None:
        """medium 置信度的样本要在明细里被标出来。"""
        results, summary = run_output
        text = bt.format_report(dataset, results, summary)
        if any(r.confidence == "medium" for r in results):
            assert "[medium]" in text

    def test_json_mode_restores_log_config(self, bt: Any) -> None:
        """`--json` 跑完必须把 structlog 全局配置还原。

        这条守的是一个已经踩过的坑：`_logs_to_stderr` 早期版本不还原，
        结果本文件跑完就把全局 logger 钉死在 pytest 的临时 stderr 捕获
        对象上；用例结束后该对象关闭，后面 test_calibration.py 的 14 个
        用例集体炸 `ValueError: I/O operation on closed file`。

        单跑 test_backtest.py 或单跑 test_calibration.py 都是绿的 ——
        这种只在特定文件顺序下暴露的污染，必须在这里钉死。
        """
        import structlog

        before = structlog.get_config()["logger_factory"]
        bt.main(["--json"])
        assert structlog.get_config()["logger_factory"] is before, "--json 跑完没还原 logger_factory，会污染后续测试"

    def test_json_mode_is_parseable(self, bt: Any, capsys: pytest.CaptureFixture[str]) -> None:
        """--json 输出必须是干净可解析的 JSON。

        日志走 stderr，stdout 只有 JSON —— 否则下游脚本没法直接管道消费。
        """
        rc = bt.main(["--json"])
        assert rc == 0
        payload = json.loads(capsys.readouterr().out)
        assert payload["summary"]["total"] > 0
        assert len(payload["cases"]) == payload["summary"]["total"]


# ── 校准分桶：门禁只数 live ────────────────────


def _sample(idx: int, source: str, label: str = "FARM") -> CalibrationSample:
    return CalibrationSample(
        project_id=f"p-{source}-{idx}",
        subscores={
            "airdrop_signal": 80.0,
            "narrative_timing": 60.0,
            "team_reputation": 70.0,
            "risk": 60.0,
            "tokenomics": 60.0,
            "competition": 70.0,
            "execution": 70.0,
            "transparency": 70.0,
        },
        true_label=label,
        current_label=label,
        signal="useful",
        outcome=None,
        source=source,
    )


class TestSourceBucketing:
    def test_gate_constants_unchanged(self) -> None:
        """引入 backtest 桶不是调低门槛的理由。

        test_calibration.py 已经钉了一遍，这里重复钉一次是因为分桶改动
        直接碰了 check_gate —— 改坏它的人应该在两个地方都被拦住。
        """
        assert MIN_VALID_SAMPLES == 200
        assert MIN_FARM_SAMPLES == 30

    def test_count_by_source_splits_buckets(self) -> None:
        samples = [_sample(i, SOURCE_LIVE) for i in range(3)] + [_sample(i, SOURCE_BACKTEST) for i in range(5)]
        counts = count_by_source(samples)
        assert counts[SOURCE_LIVE] == 3
        assert counts[SOURCE_BACKTEST] == 5

    def test_backtest_samples_do_not_unlock_gate(self) -> None:
        """这是 §4.3 的核心断言：灌回测样本不能让门禁通过。

        造 500 条 backtest 样本（远超 200/30 门槛），门禁必须仍然不过。
        如果哪天这条红了，意味着有人可以通过扩充历史数据集来解锁权重
        切换 —— 那校准协议就形同虚设。
        """
        samples = [_sample(i, SOURCE_BACKTEST) for i in range(500)]
        result = check_gate(samples)
        assert result.passed is False
        assert result.total_by_source[SOURCE_BACKTEST] == 500
        assert result.total_by_source[SOURCE_LIVE] == 0

    def test_backtest_count_is_still_visible(self) -> None:
        """不计入门禁 ≠ 不可见。

        回测样本量要照实报出来，否则运维只看到「live 3 条」会以为回测
        根本没跑。分桶是分开算，不是藏起来。
        """
        samples = [_sample(i, SOURCE_LIVE) for i in range(3)] + [_sample(i, SOURCE_BACKTEST) for i in range(40)]
        result = check_gate(samples)
        assert result.total_by_source[SOURCE_LIVE] == 3
        assert result.total_by_source[SOURCE_BACKTEST] == 40
        assert result.passed is False

    def test_mixed_buckets_count_live_only(self) -> None:
        """混合样本下门禁只看 live 的计数。"""
        live = [_sample(i, SOURCE_LIVE) for i in range(210)]
        backtest = [_sample(i, SOURCE_BACKTEST) for i in range(100)]
        result = check_gate(live + backtest)
        assert result.total_by_source[SOURCE_LIVE] == 210
        assert result.farm_by_source[SOURCE_LIVE] == 210
        # live 侧 210 ≥ 200 且 FARM 210 ≥ 30 → 通过；backtest 的 100 条不参与判定
        assert result.passed is True

    def test_default_source_is_live(self) -> None:
        """不显式给 source 时算 live。

        真实用户反馈是默认来源；如果默认成 backtest，历史反馈会被整批
        踢出门禁统计，校准进度会凭空倒退。
        """
        s = CalibrationSample(
            project_id="p-default",
            subscores={},
            true_label="FARM",
            current_label="FARM",
            signal="useful",
            outcome=None,
        )
        assert s.source == SOURCE_LIVE
