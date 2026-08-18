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
import math
import random
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Literal

import structlog

from app.agents.scorer import LABEL_THRESHOLDS, WEIGHTS
from app.config import settings

logger = structlog.get_logger(__name__)

# ── 常量 ────────────────────────────────────────

MIN_VALID_SAMPLES = 200  # §3.3 最小有效样本
MIN_FARM_SAMPLES = 30  # §3.3 其中 FARM 相关
MAX_DIM_CHANGE = 0.10  # §4.2 单维最大变化
SEARCH_STEP = 0.05  # §4.2 步长
DIRICHLET_SAMPLES = 2000  # 随机搜索采样数
LABEL_FARM = "FARM"
LABEL_WATCH = "WATCH"
LABEL_IGNORE = "IGNORE"

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


@dataclass
class CalibrationSample:
    """单个校准样本：项目子分 + 真实标签。

    子分从 projects.sub_scores（JSON）读取，固定不变；
    真实标签从 feedback.correct_label 或 outcome 映射推断。
    """

    project_id: str
    subscores: dict[str, float]
    true_label: Literal["FARM", "WATCH", "IGNORE"]
    current_label: str
    signal: str  # feedback.signal
    outcome: str | None  # feedback.outcome


@dataclass
class GateResult:
    """门禁检查结果。"""

    passed: bool
    reason: str
    total_samples: int
    strong_samples: int
    farm_samples: int


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


def _outcome_to_label(outcome: str) -> Literal["FARM", "WATCH", "IGNORE"] | None:
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


def extract_samples(conn) -> list[CalibrationSample]:
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
                    true_label = label  # type: ignore[assignment]
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
            ),
        )

    logger.info("calibration.samples_extracted", count=len(samples))
    return samples


# ── 门禁检查 ────────────────────────────────────


def check_gate(samples: list[CalibrationSample]) -> GateResult:
    """检查是否满足首次校准门槛（§3.3）。

    - 最小有效样本 ≥ 200
    - 其中 FARM 相关 ≥ 30
    """
    total = len(samples)
    strong = sum(1 for s in samples if s.signal == "wrong_label" or s.outcome is not None)
    farm = sum(1 for s in samples if s.true_label == LABEL_FARM)

    if total < MIN_VALID_SAMPLES:
        return GateResult(
            passed=False,
            reason=f"GATE_NOT_MET: 有效样本 {total} < {MIN_VALID_SAMPLES}",
            total_samples=total,
            strong_samples=strong,
            farm_samples=farm,
        )

    if farm < MIN_FARM_SAMPLES:
        return GateResult(
            passed=False,
            reason=f"GATE_NOT_MET: FARM 相关样本 {farm} < {MIN_FARM_SAMPLES}",
            total_samples=total,
            strong_samples=strong,
            farm_samples=farm,
        )

    return GateResult(
        passed=True,
        reason=f"GATE_MET: {total} samples ({farm} FARM)",
        total_samples=total,
        strong_samples=strong,
        farm_samples=farm,
    )


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


def compute_j(
    samples: list[CalibrationSample], weights: dict[str, float]
) -> dict[str, float]:
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


def _within_constraint(
    candidate: dict[str, float], baseline: dict[str, float]
) -> bool:
    """检查候选权重是否满足单维变化 ≤ 0.10 约束（§4.2）。"""
    for k in WEIGHT_KEYS:
        if abs(candidate[k] - baseline[k]) > MAX_DIM_CHANGE + 1e-9:
            return False
    return True


def _dirichlet_sample(alpha: float = 2.0) -> dict[str, float]:
    """从 Dirichlet 分布采样一个权重向量。"""
    raw = {k: random.gammavariate(alpha, 1.0) for k in WEIGHT_KEYS}
    return _normalize_weights(raw)


def _snap_to_grid(weights: dict[str, float]) -> dict[str, float]:
    """将权重对齐到 0.05 步长，然后重新归一化。"""
    snapped = {
        k: round(weights[k] / SEARCH_STEP) * SEARCH_STEP for k in WEIGHT_KEYS
    }
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
        for i, key in enumerate(WEIGHT_KEYS):
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
    conn,
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
    conn,
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
        f"  有效样本: {report.gate.total_samples}",
        f"  强监督样本: {report.gate.strong_samples}",
        f"  FARM 相关: {report.gate.farm_samples}",
        "",
        f"Baseline J: {report.baseline_j:.4f}",
    ]

    if report.best_weights is not None:
        lines.extend([
            "",
            "候选权重（Candidate Weights）:",
            "-" * 40,
        ])
        for k in WEIGHT_KEYS:
            old = report.current_weights[k]
            new = report.best_weights[k]
            delta = new - old
            arrow = "↑" if delta > 0 else ("↓" if delta < 0 else "=")
            lines.append(f"  {k:25s} {old:.2f} → {new:.2f}  ({arrow} {abs(delta):.2f})")

        lines.extend([
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
            f"Status: candidate（需灰度双跑 ≥ 7 天后 PR 切换）",
        ])
    else:
        lines.extend([
            "",
            "未执行搜索（未传 --search 或门禁未通过）",
        ])

    lines.extend([
        "",
        "=" * 60,
    ])

    return "\n".join(lines)
