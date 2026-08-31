"""历史回测执行器（F3 / T3.2，ACTION_LOOP_DESIGN §4.4）。

把已知历史空投项目在「发币前 T0」时刻的公开数据灌进评分决策引擎，检验当年
是否会给出 FARM。**回测的价值不是自证正确，而是暴露引擎在哪一维失分。**

用法::

    cd backend
    PYTHONPATH=. python scripts/run_backtest.py
    PYTHONPATH=. python scripts/run_backtest.py --json          # 机器可读
    PYTHONPATH=. python scripts/run_backtest.py --export-samples  # 写入 roi_outcomes

诚实边界（照 §4.4 与数据集自带的 honesty_notice）：

- 数据集只收 T0 前公开可得的信息。用 T0 后的信息构造样本是自欺。
- 融资额 / TVL 是**量级近似**，引擎只用它们做分档，不做精确计算。
- 走**规则引擎**路径（``enable_llm=False``，ADR-001 口径）：LLM 输出不可复现，
  回测必须可复现才有比较意义。
- 当前数据集 15 条（目标 ≥50，``pending_expansion=true``）。样本量不足时
  命中率的置信区间很宽，结论只能当方向性参考 —— 报告会显式打印这个警告。
- ``--export-samples`` 写入的产出行 ``source='backtest'``，校准侧**分桶统计、
  不计入门禁**（app/calibration.py::check_gate）。回测不能替代真实反馈去
  解锁权重切换。

Reference:
- docs/ACTION_LOOP_DESIGN.md §4.4
- app/calibration.py（source 分桶消费本脚本产出）
- backend/data/backtest/airdrops_2024_2025.json
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(BACKEND_DIR) not in sys.path:  # pragma: no cover - 脚本入口
    sys.path.insert(0, str(BACKEND_DIR))

# 这几个 import 必须在 sys.path 调整之后 —— 本仓 ruff 没启 E402，
# 所以不需要 noqa（加了会被 RUF100 判为多余）。
from app.agents.base import AgentContext, RawProject
from app.agents.orchestrator_simple import SimpleOrchestrator
from app.calibration import WEIGHT_KEYS

DEFAULT_DATASET = BACKEND_DIR / "data" / "backtest" / "airdrops_2024_2025.json"

# 命中判定：引擎给 FARM 且实际有空投 = 命中。
# WATCH 不算命中也不算完全错 —— 它表达的是"再看看"，单独统计。
LABEL_FARM = "FARM"
LABEL_WATCH = "WATCH"

# 误报率至少要几个负样本才勉强可读。
#
# 这个阈值是防误读的，不是统计推断：数据集是「按已知空投倒查」攒的，
# 天然偏向正样本，负样本（强融资强技术但最终没发币）本来就难找。
# 负样本不足 5 个时，1 个误报就能把 fpr 顶到 20%~100%，那个百分数
# 只会误导人去调权重。报告必须明说这一点，而不是把数字干净地印出来。
MIN_NEGATIVE_SAMPLES = 5


@dataclass
class CaseResult:
    """单个回测样本的评分结果。"""

    name: str
    sector: str | None
    airdropped: bool
    magnitude: str
    confidence: str
    score: int | None
    label: str | None
    sub_scores: dict[str, float] = field(default_factory=dict)
    reason: list[str] = field(default_factory=list)

    @property
    def hit(self) -> bool:
        """引擎判 FARM 且确有空投。"""
        return self.label == LABEL_FARM and self.airdropped

    @property
    def miss(self) -> bool:
        """确有空投但引擎没判 FARM —— 漏掉真机会，是最贵的错。"""
        return self.label != LABEL_FARM and self.airdropped

    @property
    def false_positive(self) -> bool:
        """判 FARM 但实际没空投 —— 白投入。"""
        return self.label == LABEL_FARM and not self.airdropped


def load_dataset(path: Path) -> dict[str, Any]:
    """读数据集。缺文件直接报错 —— 静默跑空会产出"0 条全绿"的假报告。"""
    if not path.exists():
        raise FileNotFoundError(
            f"回测数据集不存在：{path}\n"
            "它不是可选输入 —— 没有数据集的回测会输出「0 条、命中率 0%」这种毫无意义的假报告。"
        )
    with path.open(encoding="utf-8") as fh:
        # json.load 返回 Any；显式收窄成 dict 并校验，顺手挡掉「文件里是个数组」
        # 这种手改数据集时常见的形态错误。
        data: dict[str, Any] = json.load(fh)
    if not isinstance(data, dict):
        raise ValueError(f"回测数据集 {path} 顶层应为对象，实际是 {type(data).__name__}")
    if not data.get("projects"):
        raise ValueError(f"回测数据集 {path} 里没有 projects")
    return data


def to_raw_project(case: dict[str, Any], index: int) -> RawProject:
    """把数据集条目构造成 RawProject。

    id 用 ``backtest-<序号>-<名字>`` 而非随机 UUID：回测必须可复现，
    随机 id 会让 golden 断言每次都变。
    """
    signals = case.get("signals") or {}
    name = str(case.get("name") or f"case-{index}")
    slug = name.lower().replace(" ", "-")

    return RawProject(
        id=f"backtest-{index:02d}-{slug}",
        name=name,
        sector=case.get("sector"),
        stage=signals.get("stage"),
        source="backtest",
        has_testnet=bool(signals.get("has_testnet")),
        has_points_program=bool(signals.get("has_points_program")),
        no_token_yet=bool(signals.get("no_token_yet")),
        recent_funding=bool(signals.get("funding_rounds")),
        has_docs=bool(signals.get("has_docs")),
        has_whitepaper=bool(signals.get("has_whitepaper")),
        has_roadmap=bool(signals.get("has_roadmap")),
        has_github=bool(signals.get("has_github")),
        has_twitter=bool(signals.get("has_twitter")),
        has_discord=bool(signals.get("has_discord")),
        github_stars=int(signals.get("github_stars") or 0),
        github_recent_push_days=signals.get("github_recent_push_days"),
        explicit_airdrop_mention=bool(signals.get("explicit_airdrop_mention")),
        tvl_usd=signals.get("tvl_usd"),
        has_task_portal=bool(signals.get("has_task_portal")),
        has_contract=bool(signals.get("has_contract")),
        source_count=int(signals.get("source_count") or 1),
        roadmap_delivery=str(signals.get("roadmap_delivery") or "unknown"),
        sybil_friction=str(signals.get("sybil_friction") or "unknown"),
        funding_total_usd=signals.get("funding_total_usd"),
        funding_rounds=int(signals.get("funding_rounds") or 0),
        funding_last_date=signals.get("funding_last_date"),
        funding_investors=list(signals.get("funding_investors") or []),
        funding_lead_investors=list(signals.get("funding_lead_investors") or []),
        funding_tier=str(signals.get("funding_tier") or "unknown"),
        funding_quality=float(signals.get("funding_quality") or 0.0),
        discovery_source="backtest",
        auto_discovered=False,
        # 走规则引擎：低于 LLM 阈值，确保可复现（见模块 docstring）
        discovery_score=0.0,
    )


async def run_cases(dataset: dict[str, Any]) -> list[CaseResult]:
    """对全部样本跑一遍规则引擎评分。

    ``save_to_db=False`` —— 回测绝不能污染生产库：这些项目的分数不是对当前
    机会的判断，混进 projects 表会让 Dashboard 显示一堆早已发币的项目。
    """
    cases = dataset["projects"]
    projects = [to_raw_project(case, i + 1) for i, case in enumerate(cases)]

    context = AgentContext(run_id="backtest", enable_llm=False)
    orchestrator = SimpleOrchestrator()
    response = await orchestrator.run_pipeline(projects, context, save_to_db=False)

    # 结果载体是 response.states（PipelineState 列表），不是 results —— RunResponse
    # 只有 run_id/status/project_count/top_score/elapsed_ms/errors/states 这几个字段，
    # 且 states 标了 exclude=True（不进 JSON，只给进程内调用方用），正是这里要的。
    #
    # 按名字对齐结果与原始样本：run_pipeline 的返回顺序不保证与输入一致。
    by_name: dict[str, Any] = {}
    for state in response.states:
        item_name = getattr(state.project, "name", None)
        if item_name:
            by_name[str(item_name)] = state

    out: list[CaseResult] = []
    for case in cases:
        name = str(case.get("name"))
        scored = by_name.get(name)
        outcome = case.get("outcome") or {}
        out.append(
            CaseResult(
                name=name,
                sector=case.get("sector"),
                airdropped=bool(outcome.get("airdropped")),
                magnitude=str(outcome.get("magnitude") or "unknown"),
                confidence=str(case.get("confidence") or "unknown"),
                score=_attr(scored, "score"),
                label=_attr(scored, "label"),
                sub_scores=_attr(scored, "sub_scores") or {},
                reason=_attr(scored, "reason") or [],
            )
        )
    return out


def _attr(obj: Any, key: str) -> Any:
    """结果条目可能是 dataclass 也可能是 dict，两种都取得到。"""
    if obj is None:
        return None
    if isinstance(obj, dict):
        return obj.get(key)
    return getattr(obj, key, None)


def summarize(results: list[CaseResult]) -> dict[str, Any]:
    """汇总命中率、分数分布与按维度的失分归因。"""
    airdropped = [r for r in results if r.airdropped]
    not_airdropped = [r for r in results if not r.airdropped]

    hits = [r for r in results if r.hit]
    misses = [r for r in results if r.miss]
    false_positives = [r for r in results if r.false_positive]
    watch_on_airdropped = [r for r in airdropped if r.label == LABEL_WATCH]

    scores = [r.score for r in results if r.score is not None]

    # 失分归因：只看"确有空投但没判 FARM"的样本，统计它们各维度的平均子分。
    # 与整体均值对比才能看出是哪一维把它们压下去的 —— 单看绝对值没有信息。
    attribution: dict[str, dict[str, float]] = {}
    if misses:
        for key in WEIGHT_KEYS:
            miss_vals = [float(r.sub_scores.get(key, 0.0)) for r in misses if r.sub_scores]
            all_vals = [float(r.sub_scores.get(key, 0.0)) for r in results if r.sub_scores]
            if miss_vals and all_vals:
                miss_avg = sum(miss_vals) / len(miss_vals)
                all_avg = sum(all_vals) / len(all_vals)
                attribution[key] = {
                    "miss_avg": round(miss_avg, 2),
                    "overall_avg": round(all_avg, 2),
                    "gap": round(miss_avg - all_avg, 2),
                }

    return {
        "total": len(results),
        "airdropped_count": len(airdropped),
        "not_airdropped_count": len(not_airdropped),
        "farm_hits": len(hits),
        "farm_misses": len(misses),
        "false_positives": len(false_positives),
        "watch_on_airdropped": len(watch_on_airdropped),
        # 召回率：确有空投的项目里有多少被判 FARM
        "recall_farm": round(len(hits) / len(airdropped), 4) if airdropped else None,
        # 误报率：没空投的项目里有多少被判 FARM。
        # 注意分母就是 not_airdropped_count —— 当前数据集里只有个位数负样本，
        # 这个比率在统计上几乎没有意义（见 format_report 的选择偏差警告）。
        "fpr_farm": round(len(false_positives) / len(not_airdropped), 4) if not_airdropped else None,
        # 负样本过少时误报率不可读，交给报告层决定是否打警告，而不是在这里
        # 悄悄把数字藏掉 —— 汇总结构对导出/测试都是可见契约。
        "negative_sample_shortage": len(not_airdropped) < MIN_NEGATIVE_SAMPLES,
        "score_min": min(scores) if scores else None,
        "score_max": max(scores) if scores else None,
        "score_avg": round(sum(scores) / len(scores), 2) if scores else None,
        "label_distribution": _label_distribution(results),
        "miss_attribution": attribution,
    }


def _label_distribution(results: list[CaseResult]) -> dict[str, int]:
    dist: dict[str, int] = {}
    for r in results:
        key = r.label or "UNSCORED"
        dist[key] = dist.get(key, 0) + 1
    return dist


def format_report(dataset: dict[str, Any], results: list[CaseResult], summary: dict[str, Any]) -> str:
    """人读报告。风格对齐 opportunity/calibration/report.py。"""
    lines = [
        "=" * 64,
        "历史回测报告（Backtest Report）",
        "=" * 64,
        "",
        f"数据集: {len(results)} 条（目标 {dataset.get('target_size', '?')} 条）",
    ]

    if dataset.get("pending_expansion"):
        lines.extend(
            [
                "",
                "⚠️  数据集未补全（pending_expansion=true）。样本量不足时命中率的",
                "    置信区间很宽 —— 下面的数字只能当方向性参考，不足以支撑权重调整。",
            ]
        )

    # 选择偏差警告：数据集是按「已知发过空投」倒查攒的，正负样本严重失衡。
    # 不点出来的话，"fpr 100%" 会被读成"引擎误报率极高"，而真相是分母只有 1。
    fpr_caveat = ""
    if summary.get("negative_sample_shortage"):
        fpr_caveat = f"  ← 分母仅 {summary['not_airdropped_count']} 条，不可读"
        lines.extend(
            [
                "",
                "⚠️  选择偏差：数据集按「已知空投」倒查构建，正样本"
                f"{summary['airdropped_count']} / 负样本{summary['not_airdropped_count']}。",
                f"    负样本少于 {MIN_NEGATIVE_SAMPLES} 条时误报率无统计意义，只看召回率。",
                "    补全到 50 条时必须专门补「强融资强技术但最终没发币」的负样本。",
            ]
        )

    lines.extend(
        [
            "",
            "── 命中情况 ──",
            f"  确有空投:        {summary['airdropped_count']}",
            f"  其中判为 FARM:   {summary['farm_hits']}  ← 命中",
            f"  其中判为 WATCH:  {summary['watch_on_airdropped']}",
            f"  漏判（非 FARM）: {summary['farm_misses']}  ← 最贵的错：漏掉真机会",
            f"  无空投却判 FARM: {summary['false_positives']}  ← 白投入",
            "",
            f"  召回率 recall(FARM): {_pct(summary['recall_farm'])}",
            f"  误报率 fpr(FARM):    {_pct(summary['fpr_farm'])}{fpr_caveat}",
            "",
            "── 分数分布 ──",
            f"  min / avg / max: {summary['score_min']} / {summary['score_avg']} / {summary['score_max']}",
            f"  标签分布: {summary['label_distribution']}",
            "",
            "── 逐条明细 ──",
        ]
    )

    for r in sorted(results, key=lambda x: x.score or 0, reverse=True):
        mark = "✓" if r.hit else ("✗" if r.miss else ("!" if r.false_positive else "·"))
        actual = f"空投({r.magnitude})" if r.airdropped else "无空投"
        conf = "" if r.confidence == "high" else f" [{r.confidence}]"
        lines.append(
            f"  {mark} {r.score if r.score is not None else '--':>3} {r.label or 'UNSCORED':<8} {r.name:<18} {actual}{conf}"
        )

    if summary["miss_attribution"]:
        lines.extend(
            [
                "",
                "── 漏判归因（漏判样本各维度均分 vs 全体均分）──",
                "  gap 为负说明该维度把漏判样本压了下去。",
            ]
        )
        ranked = sorted(summary["miss_attribution"].items(), key=lambda kv: kv[1]["gap"])
        for key, vals in ranked:
            lines.append(
                f"  {key:<20} 漏判 {vals['miss_avg']:>6} / 全体 {vals['overall_avg']:>6}  gap {vals['gap']:>+7}"
            )
    elif summary["airdropped_count"]:
        lines.extend(["", "── 漏判归因 ──", "  无漏判样本，跳过归因。"])

    lines.extend(
        [
            "",
            "注：走规则引擎（LLM 关闭，ADR-001），结果可复现。",
            "    导出的校准样本 source=backtest，分桶统计、不计入校准门禁。",
            "=" * 64,
        ]
    )
    return "\n".join(lines)


def _pct(v: float | None) -> str:
    return "—" if v is None else f"{v * 100:.1f}%"


def export_samples(results: list[CaseResult], user_id: str) -> int:
    """把回测结论写进 roi_outcomes（``source='backtest'``）。

    需要 projects 表里有对应行 —— 回测项目本身不入 projects（见 run_cases 的
    save_to_db=False），所以这里只写**已存在**的项目，其余跳过并报数。
    真要全量导出，得先决定是否把历史项目落进生产库，那是另一个决定。
    """
    from app.db import get_connection

    written = 0
    with get_connection() as conn:
        for r in results:
            row = conn.execute("SELECT id FROM projects WHERE name = ?", (r.name,)).fetchone()
            if row is None:
                continue
            event = "airdrop_received" if r.airdropped else "airdrop_missed"
            conn.execute(
                """
                INSERT INTO roi_outcomes (user_id, project_id, event, source)
                VALUES (?, ?, ?, 'backtest')
                """,
                (user_id, row["id"], event),
            )
            written += 1
        conn.commit()
    return written


def _redirect_logs_to_stderr() -> None:
    """`--json` 模式下把 structlog 输出改到 stderr。

    app.utils.redact 的 configure 默认写 stdout（跑服务时是对的），但那会让
    `run_backtest.py --json | jq` 直接崩掉 —— 15 个项目的评分日志和 JSON
    混在同一个流里，下游没法解析。

    只覆盖 logger_factory，**不动 processors 链**：脱敏 processor 必须原样
    保留（SECURITY.md §3.3），换整条链等于新开一条渲染路径、多一处可能漏
    脱敏的地方。
    """
    import structlog

    structlog.configure(logger_factory=structlog.WriteLoggerFactory(file=sys.stderr))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="历史回测：把 T0 前数据灌进评分引擎")
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET, help="数据集路径")
    parser.add_argument("--json", action="store_true", help="输出机器可读 JSON")
    parser.add_argument(
        "--export-samples",
        action="store_true",
        help="把结论写入 roi_outcomes（source=backtest），仅对已在 projects 表的项目生效",
    )
    parser.add_argument("--user-id", default="backtest", help="导出样本时使用的 user_id")
    args = parser.parse_args(argv)

    if args.json:
        _redirect_logs_to_stderr()

    dataset = load_dataset(args.dataset)
    results = asyncio.run(run_cases(dataset))
    summary = summarize(results)

    if args.json:
        print(
            json.dumps(
                {
                    "summary": summary,
                    "cases": [
                        {
                            "name": r.name,
                            "sector": r.sector,
                            "score": r.score,
                            "label": r.label,
                            "airdropped": r.airdropped,
                            "magnitude": r.magnitude,
                            "confidence": r.confidence,
                            "hit": r.hit,
                            "miss": r.miss,
                            "false_positive": r.false_positive,
                        }
                        for r in results
                    ],
                },
                ensure_ascii=False,
                indent=2,
            )
        )
    else:
        print(format_report(dataset, results, summary))

    if args.export_samples:
        written = export_samples(results, args.user_id)
        skipped = len(results) - written
        print(f"\n已导出 {written} 条 source=backtest 样本；跳过 {skipped} 条（projects 表无对应项目）。")

    return 0


if __name__ == "__main__":  # pragma: no cover - 脚本入口
    raise SystemExit(main())
