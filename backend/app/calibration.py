"""权重校准引擎（Weight Calibration Engine）。

实现 WEIGHT_CALIBRATION.md §4 定义的目标函数与搜索：

1. 从 feedback + projects 表提取校准样本（固定子分，仅重加权）
2. 门禁检查（≥ 200 有效样本，≥ 30 FARM 相关）
3. 目标函数 J = recall(FARM) − 2 × false_positive_rate(FARM)
4. 搜索：Dirichlet 随机 + 局部爬山，约束 Σ=1.0 且单维变化 ≤ 0.10
5. 候选权重写入 weight_changelog（status='candidate'）

Reference:
- WEIGHT_CALIBRATION.md §3-§7
- ADR-006 权重校准
- ENGINEERING_ROADMAP.md §7.9 / §24
"""

from __future__ import annotations

import json
import random
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Literal

import structlog

from app.agents.scorer import LABEL_THRESHOLDS, WEIGHTS
from app.config import settings
from app.db import DbConnection

logger = structlog.get_logger(__name__)

# ── 常量 ────────────────────────────────────────

MIN_VALID_SAMPLES = 200  # §3.3 最小有效样本
MIN_FARM_SAMPLES = 30  # §3.3 其中 FARM 相关
MAX_DIM_CHANGE = 0.10  # §4.2 单维最大变化
SEARCH_STEP = 0.05  # §4.2 步长
DIRICHLET_SAMPLES = 2000  # 随机搜索采样数
# 标注成 Literal 而非裸 str：这三个常量会流入 `-> Literal[...] | None` 的返回值，
# 推断成 str 会让 mypy 在 _outcome_to_label 处报 return-value。
ScoreLabel = Literal["FARM", "WATCH", "IGNORE"]
LABEL_FARM: ScoreLabel = "FARM"
LABEL_WATCH: ScoreLabel = "WATCH"
LABEL_IGNORE: ScoreLabel = "IGNORE"

# 八个权重维度
WEIGHT_KEYS: list[str] = [
    "airdrop_signal",
    "narrative_timing",
    "team_reputation",
    "risk",
    "tokenomics",
    "competition",
    "execution",
    "transparency",
]


# 样本来源分桶（ACTION_LOOP_DESIGN §4.3）。
# live = 真实使用留痕（feedback + 人工录入的 roi_outcomes）；
# backtest = 历史回测导出。**两类分开统计、分开算门槛，绝不混算** ——
# 回测样本是历史分布，live 是当前分布；混起来凑数等于用几年前的项目
# 结构给今天的判断背书，门槛数字会好看但结论不成立。
SampleSource = Literal["live", "backtest"]
SOURCE_LIVE: SampleSource = "live"
SOURCE_BACKTEST: SampleSource = "backtest"

# roi_outcomes.event → 真实标签（§4.3）。
# 只有"领到了"和"确认没领到"构成监督信号；token_launched / campaign_ended
# 只是时间线事件，**不能**当正负样本 —— 发了币不代表你领到了。
_OUTCOME_EVENT_LABELS: dict[str, str] = {
    "airdrop_received": "FARM",
    "airdrop_missed": "IGNORE",
}


@dataclass
class CalibrationSample:
    """单个校准样本：项目子分 + 真实标签。

    子分从 projects.sub_scores（JSON）读取，固定不变；
    真实标签来自 feedback.correct_label / outcome 映射，或
    roi_outcomes 的实际到账结果（§4.3）。
    """

    project_id: str
    subscores: dict[str, float]
    true_label: Literal["FARM", "WATCH", "IGNORE"]
    current_label: str
    signal: str  # feedback.signal，或 roi_outcomes 派生时的事件名
    outcome: str | None  # feedback.outcome
    source: SampleSource = SOURCE_LIVE


@dataclass
class GateResult:
    """门禁检查结果。

    ``*_by_source`` 是分桶明细：门禁只看 live 桶（回测样本不能替代真实
    反馈去解锁权重切换），但两个桶的计数都要暴露出来 —— 否则"回测跑了
    50 条"这件事在报告里完全看不见，读的人会以为回测没生效。
    """

    passed: bool
    reason: str
    total_samples: int
    strong_samples: int
    farm_samples: int
    total_by_source: dict[str, int] = field(default_factory=dict)
    farm_by_source: dict[str, int] = field(default_factory=dict)


@dataclass
class CalibrationReport:
    """校准报告。"""

    gate: GateResult
    baseline_j: float
    best_j: float
    best_weights: dict[str, float] | None
    current_weights: dict[str, float]
    improvement: float
    changelog_id: int | None = None
    metrics: dict[str, Any] = field(default_factory=dict)


# ── 样本提取 ────────────────────────────────────


def _outcome_to_label(outcome: str) -> ScoreLabel | None:
    """将 feedback.outcome 映射为真实标签（§3.1）。

    outcome=airdropped/pumped → FARM（空投或拉升 = 值得参与）
    outcome=not_airdropped/dumped → IGNORE（未空投或暴跌 = 不值得）
    """
    mapping = {
        "airdropped": LABEL_FARM,
        "pumped": LABEL_FARM,
        "not_airdropped": LABEL_IGNORE,
        "dumped": LABEL_IGNORE,
    }
    return mapping.get(outcome)


def extract_samples(conn: DbConnection) -> list[CalibrationSample]:
    """从 DB 提取校准样本。

    JOIN feedback ↔ projects，仅保留有监督信号的样本：
    - signal='wrong_label' 且 correct_label 非空 → 用 correct_label
    - outcome 非空 → 用 outcome 映射

    同一 user+project 7 日内重复只保留最新一条（§3.2）。
    """
    rows = conn.execute(
        """
        SELECT f.project_id, f.signal, f.outcome, f.note,
               p.sub_scores, p.label, p.score
        FROM feedback f
        JOIN projects p ON f.project_id = p.id
        WHERE (f.signal = 'wrong_label' AND f.note IS NOT NULL)
           OR f.outcome IS NOT NULL
        ORDER BY f.created_at DESC, f.id DESC
        """,
    ).fetchall()

    seen: set[str] = set()
    samples: list[CalibrationSample] = []

    for row in rows:
        project_id = row["project_id"]
        if project_id in seen:
            continue
        seen.add(project_id)

        sub_scores_raw = row["sub_scores"]
        if not sub_scores_raw:
            continue
        try:
            subscores = json.loads(sub_scores_raw)
        except (json.JSONDecodeError, TypeError):
            continue

        # 确保所有维度都存在
        if not all(k in subscores for k in WEIGHT_KEYS):
            continue

        signal = row["signal"] or ""
        outcome = row["outcome"]

        # 确定真实标签
        true_label: Literal["FARM", "WATCH", "IGNORE"] | None = None
        if signal == "wrong_label":
            # correct_label 存在 note 字段（feedback 表无独立列）
            # 实际可能从 note 或单独的 correct_label 列读取
            note = row["note"] or ""
            for label in (LABEL_FARM, LABEL_WATCH, LABEL_IGNORE):
                if label.lower() in note.lower():
                    true_label = label
                    break

        if true_label is None and outcome:
            true_label = _outcome_to_label(outcome)

        if true_label is None:
            continue

        samples.append(
            CalibrationSample(
                project_id=project_id,
                subscores={k: float(subscores[k]) for k in WEIGHT_KEYS},
                true_label=true_label,
                current_label=row["label"] or LABEL_IGNORE,
                signal=signal,
                outcome=outcome,
                source=SOURCE_LIVE,
            ),
        )

    # 台账派生样本（§4.3）。feedback 已覆盖的项目不再重复计入 —— 同一项目
    # 两条样本会让它在目标函数里获得双倍权重。
    samples.extend(extract_roi_samples(conn, exclude_project_ids=seen))

    by_source: dict[str, int] = {}
    for s in samples:
        by_source[s.source] = by_source.get(s.source, 0) + 1
    logger.info("calibration.samples_extracted", count=len(samples), by_source=by_source)
    return samples


def extract_roi_samples(
    conn: DbConnection,
    *,
    exclude_project_ids: set[str] | None = None,
) -> list[CalibrationSample]:
    """从 roi_outcomes 派生校准样本（ACTION_LOOP_DESIGN §4.3）。

    这是 F3 的核心价值：把「最后到底有没有领到钱」变成监督信号。
    反馈只有主观四档，学不到实际回报。

    - ``airdrop_received`` → FARM 正样本
    - ``airdrop_missed``   → IGNORE 负样本
    - 其它事件（token_launched / campaign_ended）**不产生样本** ——
      它们只是时间线，发了币不代表你领到了。

    ``roi_outcomes.source`` 直接映射到样本桶：``manual`` → live，
    ``backtest`` → backtest。同一项目同时有到账与未领记录时按「到账优先」
    （领到过就是领到过），避免同项目产出两条互相矛盾的样本。
    """
    excluded = exclude_project_ids or set()
    rows = conn.execute(
        """
        SELECT o.project_id, o.event, o.source, p.sub_scores, p.label
        FROM roi_outcomes o
        JOIN projects p ON o.project_id = p.id
        WHERE o.event IN ('airdrop_received', 'airdrop_missed')
        ORDER BY o.project_id, o.id DESC
        """,
    ).fetchall()

    # project_id → 已选中的样本。received 覆盖 missed，同类保留最新一条。
    chosen: dict[str, CalibrationSample] = {}
    for row in rows:
        project_id = row["project_id"]
        if project_id in excluded:
            continue

        subscores = _parse_subscores(row["sub_scores"])
        if subscores is None:
            continue

        event = row["event"]
        label_name = _OUTCOME_EVENT_LABELS.get(event)
        if label_name is None:  # pragma: no cover - SQL 已过滤
            continue
        true_label: ScoreLabel = LABEL_FARM if label_name == "FARM" else LABEL_IGNORE

        existing = chosen.get(project_id)
        if existing is not None and existing.true_label == LABEL_FARM:
            # 已经有"领到了"的样本，不让"未领到"把它盖掉
            continue

        chosen[project_id] = CalibrationSample(
            project_id=project_id,
            subscores=subscores,
            true_label=true_label,
            current_label=row["label"] or LABEL_IGNORE,
            signal=event,
            outcome=event,
            source=SOURCE_BACKTEST if row["source"] == "backtest" else SOURCE_LIVE,
        )

    return list(chosen.values())


def _parse_subscores(raw: object) -> dict[str, float] | None:
    """解析 projects.sub_scores，缺维度或解析失败返回 None。"""
    if not raw:
        return None
    try:
        parsed = json.loads(str(raw))
    except (json.JSONDecodeError, TypeError):
        return None
    if not isinstance(parsed, dict) or not all(k in parsed for k in WEIGHT_KEYS):
        return None
    try:
        return {k: float(parsed[k]) for k in WEIGHT_KEYS}
    except (TypeError, ValueError):
        return None


# ── 门禁检查 ────────────────────────────────────


def count_by_source(samples: list[CalibrationSample]) -> dict[str, int]:
    """按来源桶计数（缺席的桶显式给 0，方便报告与断言）。"""
    # 显式标注 dict[str, int]：字面量会被推成 dict[Literal["live","backtest"], int]，
    # 而返回类型是 dict[str, int]（调用方会用任意字符串键去查）。
    out: dict[str, int] = {SOURCE_LIVE: 0, SOURCE_BACKTEST: 0}
    for s in samples:
        out[s.source] = out.get(s.source, 0) + 1
    return out


def check_gate(samples: list[CalibrationSample]) -> GateResult:
    """检查是否满足首次校准门槛（§3.3）。

    - 最小有效样本 ≥ 200
    - 其中 FARM 相关 ≥ 30

    **门禁只数 live 桶**（ACTION_LOOP_DESIGN §4.3）：回测样本能验证引擎在
    历史项目上的表现，但不能替代真实反馈去解锁权重切换 —— 否则灌 200 条
    历史数据就能让门禁通过，而门槛本来是为了确保"当前分布下确实学到了东西"。
    门槛数值 200/30 不变（owner 拍板，有测试钉死）。

    两个桶的计数都会写进 ``GateResult``：回测跑了多少条必须在报告里看得见。
    """
    by_source = count_by_source(samples)
    live = [s for s in samples if s.source == SOURCE_LIVE]

    total = len(live)
    strong = sum(1 for s in live if s.signal == "wrong_label" or s.outcome is not None)
    farm = sum(1 for s in live if s.true_label == LABEL_FARM)
    farm_by_source: dict[str, int] = {SOURCE_LIVE: 0, SOURCE_BACKTEST: 0}
    for s in samples:
        if s.true_label == LABEL_FARM:
            farm_by_source[s.source] = farm_by_source.get(s.source, 0) + 1

    def _result(passed: bool, reason: str) -> GateResult:
        return GateResult(
            passed=passed,
            reason=reason,
            total_samples=total,
            strong_samples=strong,
            farm_samples=farm,
            total_by_source=by_source,
            farm_by_source=farm_by_source,
        )

    backtest_note = (
        f"（另有 {by_source[SOURCE_BACKTEST]} 条回测样本，不计入门禁）" if by_source[SOURCE_BACKTEST] else ""
    )

    if total < MIN_VALID_SAMPLES:
        return _result(
            False,
            f"GATE_NOT_MET: live 有效样本 {total} < {MIN_VALID_SAMPLES}{backtest_note}",
        )

    if farm < MIN_FARM_SAMPLES:
        return _result(
            False,
            f"GATE_NOT_MET: live FARM 相关样本 {farm} < {MIN_FARM_SAMPLES}{backtest_note}",
        )

    return _result(True, f"GATE_MET: {total} live samples ({farm} FARM){backtest_note}")


# ── 目标函数 ────────────────────────────────────


def recompute_score(subscores: dict[str, float], weights: dict[str, float]) -> int:
    """用给定权重重算加权总分（固定子分）。"""
    total = sum(subscores.get(k, 0.0) * weights.get(k, 0.0) for k in WEIGHT_KEYS)
    return round(max(0.0, min(100.0, total)))


def recompute_label(subscores: dict[str, float], weights: dict[str, float]) -> str:
    """用给定权重重算标签。"""
    score = recompute_score(subscores, weights)
    for threshold, label in LABEL_THRESHOLDS:
        if score >= threshold:
            return label
    return LABEL_IGNORE


def compute_j(samples: list[CalibrationSample], weights: dict[str, float]) -> dict[str, float]:
    """计算目标函数 J = recall(FARM) − 2 × false_positive_rate(FARM)。

    返回包含 J、recall、fpr 及混淆矩阵的字典。
    """
    tp = fp = fn = tn = 0

    for s in samples:
        predicted = recompute_label(s.subscores, weights)
        actual = s.true_label

        if predicted == LABEL_FARM and actual == LABEL_FARM:
            tp += 1
        elif predicted == LABEL_FARM and actual != LABEL_FARM:
            fp += 1
        elif predicted != LABEL_FARM and actual == LABEL_FARM:
            fn += 1
        else:
            tn += 1

    actual_farm = tp + fn
    actual_non_farm = fp + tn

    recall = tp / actual_farm if actual_farm > 0 else 0.0
    fpr = fp / actual_non_farm if actual_non_farm > 0 else 0.0
    j = recall - 2 * fpr

    return {
        "j": j,
        "recall_farm": recall,
        "fpr_farm": fpr,
        "tp": tp,
        "fp": fp,
        "fn": fn,
        "tn": tn,
        "precision_farm": tp / (tp + fp) if (tp + fp) > 0 else 0.0,
    }


# ── 搜索 ────────────────────────────────────────


def _normalize_weights(raw: dict[str, float]) -> dict[str, float]:
    """归一化权重使 Σ=1.0。"""
    total = sum(raw.values())
    if total <= 0:
        # 均匀分布
        n = len(WEIGHT_KEYS)
        return {k: 1.0 / n for k in WEIGHT_KEYS}
    return {k: raw[k] / total for k in WEIGHT_KEYS}


def _within_constraint(candidate: dict[str, float], baseline: dict[str, float]) -> bool:
    """检查候选权重是否满足单维变化 ≤ 0.10 约束（§4.2）。"""
    return all(abs(candidate[k] - baseline[k]) <= MAX_DIM_CHANGE + 1e-9 for k in WEIGHT_KEYS)


def _dirichlet_sample(alpha: float = 2.0) -> dict[str, float]:
    """从 Dirichlet 分布采样一个权重向量。"""
    raw = {k: random.gammavariate(alpha, 1.0) for k in WEIGHT_KEYS}
    return _normalize_weights(raw)


def _snap_to_grid(weights: dict[str, float]) -> dict[str, float]:
    """将权重对齐到 0.05 步长，然后重新归一化。"""
    snapped = {k: round(weights[k] / SEARCH_STEP) * SEARCH_STEP for k in WEIGHT_KEYS}
    return _normalize_weights(snapped)


def grid_search(
    samples: list[CalibrationSample],
    current_weights: dict[str, float],
    *,
    n_random: int = DIRICHLET_SAMPLES,
) -> tuple[dict[str, float], float, dict[str, float]]:
    """搜索最大化 J 的权重组合。

    策略：Dirichlet 随机采样 + 局部爬山。
    约束：Σ=1.0，单维变化 ≤ 0.10（相对 current_weights）。

    Returns:
        (best_weights, best_j, best_metrics)
    """
    baseline_j = compute_j(samples, current_weights)["j"]
    best_weights = current_weights.copy()
    best_j = baseline_j
    best_metrics = compute_j(samples, current_weights)

    # 阶段 1：Dirichlet 随机搜索
    for _ in range(n_random):
        candidate = _snap_to_grid(_dirichlet_sample())
        if not _within_constraint(candidate, current_weights):
            continue
        metrics = compute_j(samples, candidate)
        if metrics["j"] > best_j:
            best_j = metrics["j"]
            best_weights = candidate
            best_metrics = metrics

    # 阶段 2：局部爬山
    improved = True
    iterations = 0
    max_iterations = 100
    while improved and iterations < max_iterations:
        improved = False
        iterations += 1
        for key in WEIGHT_KEYS:
            for delta in (SEARCH_STEP, -SEARCH_STEP):
                candidate = best_weights.copy()
                candidate[key] += delta
                candidate = _normalize_weights(candidate)
                candidate = _snap_to_grid(candidate)
                if not _within_constraint(candidate, current_weights):
                    continue
                metrics = compute_j(samples, candidate)
                if metrics["j"] > best_j + 1e-9:
                    best_j = metrics["j"]
                    best_weights = candidate
                    best_metrics = metrics
                    improved = True

    logger.info(
        "calibration.search_completed",
        baseline_j=baseline_j,
        best_j=best_j,
        improvement=best_j - baseline_j,
        iterations=iterations,
    )

    return best_weights, best_j, best_metrics


# ── Changelog 记录 ──────────────────────────────


def record_candidate(
    conn: DbConnection,
    from_version: str,
    to_version: str,
    weights: dict[str, float],
    sample_size: int,
    metrics: dict[str, Any],
    triggered_by: str = "human",
) -> int:
    """将候选权重写入 weight_changelog（status='candidate'）。

    Returns:
        changelog 行 ID
    """
    weights_json = json.dumps(weights, sort_keys=True)
    metrics_json = json.dumps(metrics, sort_keys=True)
    now = datetime.now(UTC).isoformat()

    cursor = conn.execute(
        """
        INSERT INTO weight_changelog
            (from_version, to_version, weights_json, sample_size,
             metrics_json, triggered_by, status, created_at)
        VALUES (?, ?, ?, ?, ?, ?, 'candidate', ?)
        """,
        (from_version, to_version, weights_json, sample_size, metrics_json, triggered_by, now),
    )
    conn.commit()
    changelog_id = cursor.lastrowid or 0

    logger.info(
        "calibration.candidate_recorded",
        changelog_id=changelog_id,
        from_version=from_version,
        to_version=to_version,
        sample_size=sample_size,
        j=metrics.get("j"),
    )

    return changelog_id


# ── 主入口 ──────────────────────────────────────


def run_calibration(
    conn: DbConnection,
    *,
    search: bool = False,
    triggered_by: str = "human",
) -> CalibrationReport:
    """运行校准流程。

    1. 提取样本
    2. 门禁检查
    3. 如果 search=True 且门禁通过：搜索 + 记录候选
    4. 返回报告

    Args:
        conn: DB 连接
        search: 是否执行搜索（--search 标志）
        triggered_by: 触发者（human / scheduled_job）

    Returns:
        CalibrationReport
    """
    current_weights = {k: WEIGHTS[k] for k in WEIGHT_KEYS}
    current_version = settings.weight_version

    # 1. 提取样本
    samples = extract_samples(conn)

    # 2. 门禁检查
    gate = check_gate(samples)

    # 3. 计算 baseline J
    baseline_metrics = compute_j(samples, current_weights)
    baseline_j = baseline_metrics["j"]

    if not gate.passed:
        logger.info("calibration.gate_not_met", reason=gate.reason)
        return CalibrationReport(
            gate=gate,
            baseline_j=baseline_j,
            best_j=baseline_j,
            best_weights=None,
            current_weights=current_weights,
            improvement=0.0,
            metrics=baseline_metrics,
        )

    if not search:
        logger.info("calibration.gate_met_no_search", reason=gate.reason)
        return CalibrationReport(
            gate=gate,
            baseline_j=baseline_j,
            best_j=baseline_j,
            best_weights=None,
            current_weights=current_weights,
            improvement=0.0,
            metrics=baseline_metrics,
        )

    # 4. 搜索
    best_weights, best_j, best_metrics = grid_search(samples, current_weights)

    # 5. 记录候选
    new_version = f"v1.{int(current_version.split('.')[-1]) + 1}" if "." in current_version else "v2"
    changelog_id = record_candidate(
        conn,
        from_version=current_version,
        to_version=new_version,
        weights=best_weights,
        sample_size=gate.total_samples,
        metrics=best_metrics,
        triggered_by=triggered_by,
    )

    return CalibrationReport(
        gate=gate,
        baseline_j=baseline_j,
        best_j=best_j,
        best_weights=best_weights,
        current_weights=current_weights,
        improvement=best_j - baseline_j,
        changelog_id=changelog_id,
        metrics=best_metrics,
    )


def format_report(report: CalibrationReport) -> str:
    """格式化校准报告为可读文本。"""
    lines = [
        "=" * 60,
        "权重校准报告（Weight Calibration Report）",
        "=" * 60,
        "",
        f"门禁状态: {'✅ PASS' if report.gate.passed else '❌ FAIL'}",
        f"  原因: {report.gate.reason}",
        f"  有效样本(live): {report.gate.total_samples}",
        f"  强监督样本: {report.gate.strong_samples}",
        f"  FARM 相关(live): {report.gate.farm_samples}",
        # 分桶必须显示：否则"回测跑了 N 条"在报告里完全看不见
        f"  样本分桶: live={report.gate.total_by_source.get(SOURCE_LIVE, 0)} "
        f"backtest={report.gate.total_by_source.get(SOURCE_BACKTEST, 0)}"
        "（门禁只数 live）",
        "",
        f"Baseline J: {report.baseline_j:.4f}",
    ]

    if report.best_weights is not None:
        lines.extend(
            [
                "",
                "候选权重（Candidate Weights）:",
                "-" * 40,
            ]
        )
        for k in WEIGHT_KEYS:
            old = report.current_weights[k]
            new = report.best_weights[k]
            delta = new - old
            arrow = "↑" if delta > 0 else ("↓" if delta < 0 else "=")
            lines.append(f"  {k:25s} {old:.2f} → {new:.2f}  ({arrow} {abs(delta):.2f})")

        lines.extend(
            [
                "",
                f"Best J:     {report.best_j:.4f}",
                f"Improvement: {report.improvement:.4f}",
                "",
                "混淆矩阵（Confusion Matrix）:",
                f"  TP={report.metrics.get('tp', 0)}  FP={report.metrics.get('fp', 0)}",
                f"  FN={report.metrics.get('fn', 0)}  TN={report.metrics.get('tn', 0)}",
                f"  Recall(FARM)={report.metrics.get('recall_farm', 0):.4f}",
                f"  FPR(FARM)={report.metrics.get('fpr_farm', 0):.4f}",
                f"  Precision(FARM)={report.metrics.get('precision_farm', 0):.4f}",
                "",
                f"Changelog ID: {report.changelog_id}",
                "Status: candidate（需灰度双跑 ≥ 7 天后 PR 切换）",
            ]
        )
    else:
        lines.extend(
            [
                "",
                "未执行搜索（未传 --search 或门禁未通过）",
            ]
        )

    lines.extend(
        [
            "",
            "=" * 60,
        ]
    )

    return "\n".join(lines)
