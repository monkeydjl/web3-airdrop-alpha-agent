"""
LLM Prompt Template Validation & Evaluation Script.

被以下文档引用：
- prompts/README.md §6.2
- evaluation/README.md
- docs/TESTING_FRAMEWORK.md §8.4
- docs/SECURITY.md §10.4

功能模式：
1. --validate-templates-only : 仅校验 prompt 模板结构（不需 API key）
2. 默认模式                  : 跑 LLM 评估（需 OPENAI_API_KEY）
3. --benchmark               : 对比多版本 Prompt 效果

用法示例：
    # 仅校验模板结构
    python evaluation/llm/template_validation.py --validate-templates-only

    # 跑 100 个样本的 LLM 评估
    python evaluation/llm/template_validation.py --samples 100 --agents narrative,team,risk,tokenomics

    # 对比 Prompt 版本
    python evaluation/llm/template_validation.py --benchmark --prompt-versions narrative/v1,narrative/v2
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# 项目根目录（假设本脚本位于 evaluation/llm/ 下）
PROJECT_ROOT = Path(__file__).resolve().parents[2]
PROMPTS_DIR = PROJECT_ROOT / "prompts"
GOLDEN_SAMPLES = PROJECT_ROOT / "tests" / "golden" / "projects.jsonl"
REPORT_DIR = PROJECT_ROOT / "evaluation" / "llm"
METRICS_HISTORY = REPORT_DIR / "metrics_history.json"

# 评估目标阈值（对齐 TESTING_FRAMEWORK.md §8.2）
THRESHOLDS = {
    "schema_compliance_rate": 0.95,   # 结构遵从率 ≥ 95%
    "value_range_compliance": 1.0,    # 数值合理性 100%
    "evidence_sufficiency": 1.0,      # 证据充分性 100%
    "rule_consistency_max": 0.2,      # 规则一致性 < 0.2
    "latency_p95_max": 30.0,          # 延迟 P95 < 30s
    "cost_per_call_max": 0.05,        # 单次成本 < $0.05
}


@dataclass
class PromptTemplate:
    """加载后的 Prompt 模板。"""

    path: Path
    meta: dict[str, Any]
    system_prompt: str
    user_prompt_template: str
    output_schema: dict[str, Any]

    @property
    def agent(self) -> str:
        return self.meta.get("agent", "unknown")

    @property
    def version(self) -> str:
        return self.meta.get("version", "unknown")

    @property
    def prompt_key(self) -> str:
        return self.meta.get("prompt_key", "unknown")

    @property
    def full_id(self) -> str:
        return f"{self.agent}/{self.version}"


@dataclass
class ValidationResult:
    """单次模板校验结果。"""

    template: PromptTemplate
    valid: bool
    errors: list[str] = field(default_factory=list)


@dataclass
class EvalSample:
    """单次 LLM 评估样本结果。"""

    template_id: str
    sample_id: str
    schema_valid: bool
    value_in_range: bool
    has_evidence: bool
    rule_deviation: float
    latency_sec: float
    token_usage: dict[str, int]
    cost_usd: float
    error: str | None = None


# ──────────────────────────────────────────────
# 1. 模板结构校验（不需 API key）
# ──────────────────────────────────────────────


def load_prompt_template(path: Path) -> PromptTemplate:
    """加载单个 Prompt JSON 模板。"""
    data = json.loads(path.read_text(encoding="utf-8"))
    return PromptTemplate(
        path=path,
        meta=data.get("_meta", {}),
        system_prompt=data.get("system_prompt", ""),
        user_prompt_template=data.get("user_prompt_template", ""),
        output_schema=data.get("output_schema", {}),
    )


def discover_prompt_templates(agent_filter: list[str] | None = None) -> list[PromptTemplate]:
    """发现所有 Prompt 模板文件。

    查找 prompts/agents/<agent>/v*.json 与 prompts/system/v*.json
    """
    templates: list[PromptTemplate] = []
    search_dirs = [PROMPTS_DIR / "agents", PROMPTS_DIR / "system"]
    for search_dir in search_dirs:
        if not search_dir.exists():
            continue
        for json_file in sorted(search_dir.rglob("v*.json")):
            try:
                tpl = load_prompt_template(json_file)
            except (json.JSONDecodeError, KeyError) as e:
                print(f"  [WARN] 跳过 {json_file}: 解析失败 {e}", file=sys.stderr)
                continue
            if agent_filter and tpl.agent not in agent_filter:
                continue
            templates.append(tpl)
    return templates


def validate_template_structure(tpl: PromptTemplate) -> ValidationResult:
    """校验单个模板结构完整性。"""
    errors: list[str] = []

    # 必填元数据
    required_meta = ["version", "agent", "prompt_key"]
    for key in required_meta:
        if key not in tpl.meta:
            errors.append(f"_meta 缺少必填字段: {key}")

    # system_prompt 非空
    if not tpl.system_prompt.strip():
        errors.append("system_prompt 为空")

    # user_prompt_template 非空
    if not tpl.user_prompt_template.strip():
        errors.append("user_prompt_template 为空")

    # output_schema 必须是 object 类型
    if not tpl.output_schema:
        errors.append("output_schema 为空")
    elif tpl.output_schema.get("type") != "object":
        errors.append("output_schema.type 必须为 'object'")

    # output_schema 必须有 required 字段
    if "required" not in tpl.output_schema:
        errors.append("output_schema 缺少 required 字段")

    # Prompt Injection 防御检查（SECURITY.md §10.1）
    injection_markers = ["ignore previous", "disregard above", "system:"]
    lower_prompt = tpl.system_prompt.lower()
    for marker in injection_markers:
        if marker in lower_prompt and "忽略" not in lower_prompt and "ignore" not in lower_prompt:
            # 允许防御性声明，但禁止直接出现可被利用的指令
            errors.append(f"system_prompt 含可疑指令片段: '{marker}'")

    # 变量占位符检查
    placeholder_count = tpl.user_prompt_template.count("{")
    if placeholder_count == 0:
        errors.append("user_prompt_template 无变量占位符（{var}）")

    return ValidationResult(template=tpl, valid=len(errors) == 0, errors=errors)


def run_template_validation(agent_filter: list[str] | None = None) -> list[ValidationResult]:
    """运行模板结构校验。"""
    templates = discover_prompt_templates(agent_filter)
    if not templates:
        print("未发现任何 Prompt 模板文件。", file=sys.stderr)
        return []

    results: list[ValidationResult] = []
    print(f"发现 {len(templates)} 个 Prompt 模板，开始结构校验...")
    for tpl in templates:
        result = validate_template_structure(tpl)
        status = "✅ PASS" if result.valid else "❌ FAIL"
        print(f"  {status} {tpl.full_id} ({tpl.path.name})")
        for err in result.errors:
            print(f"         - {err}")
        results.append(result)

    passed = sum(1 for r in results if r.valid)
    print(f"\n模板校验结果: {passed}/{len(results)} 通过")
    return results


# ──────────────────────────────────────────────
# 2. LLM 评估（需 OPENAI_API_KEY）
# ──────────────────────────────────────────────


def load_golden_samples(limit: int = 100) -> list[dict[str, Any]]:
    """加载 golden 测试样本。"""
    if not GOLDEN_SAMPLES.exists():
        print(f"样本文件不存在: {GOLDEN_SAMPLES}", file=sys.stderr)
        return []
    samples: list[dict[str, Any]] = []
    with GOLDEN_SAMPLES.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                samples.append(json.loads(line))
                if len(samples) >= limit:
                    break
    return samples


async def call_llm(tpl: PromptTemplate, variables: dict[str, Any]) -> dict[str, Any]:
    """调用 LLM（占位实现，实际接入 OpenAI SDK）。

    生产环境应替换为 backend/app/llm/client.py 的真实调用。
    这里返回 mock 结构供脚本骨架可用。
    """
    api_key = os.getenv("OPENAI_API_KEY", "")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY 未设置，无法运行 LLM 评估")

    # 占位：实际实现应使用 openai.AsyncOpenAI
    # from openai import AsyncOpenAI
    # client = AsyncOpenAI(api_key=api_key)
    # response = await client.chat.completions.create(
    #     model=tpl.meta.get("model", "gpt-4o-mini"),
    #     temperature=tpl.meta.get("temperature", 0.3),
    #     max_tokens=tpl.meta.get("max_tokens", 512),
    #     messages=[
    #         {"role": "system", "content": tpl.system_prompt},
    #         {"role": "user", "content": tpl.user_prompt_template.format(**variables)},
    #     ],
    #     response_format={"type": "json_object"},
    # )
    raise NotImplementedError(
        "LLM 调用需接入 openai SDK。运行时请实现本函数或复用 backend/app/llm/client.py。"
    )


def validate_output_schema(output: dict[str, Any], schema: dict[str, Any]) -> tuple[bool, bool, bool]:
    """校验 LLM 输出是否符合 schema。

    返回 (schema_valid, value_in_range, has_evidence)
    """
    schema_valid = True
    value_in_range = True
    has_evidence = False

    # 检查 required 字段
    required = schema.get("required", [])
    for field_name in required:
        if field_name not in output:
            schema_valid = False
            continue
        # 检查数值范围
        props = schema.get("properties", {}).get(field_name, {})
        if "minimum" in props and isinstance(output[field_name], (int, float)):
            if output[field_name] < props["minimum"]:
                value_in_range = False
        if "maximum" in props and isinstance(output[field_name], (int, float)):
            if output[field_name] > props["maximum"]:
                value_in_range = False
        # 检查 evidence 字段
        if field_name == "evidence" and isinstance(output[field_name], list):
            has_evidence = len(output[field_name]) >= 1

    return schema_valid, value_in_range, has_evidence


async def evaluate_template(
    tpl: PromptTemplate, samples: list[dict[str, Any]]
) -> list[EvalSample]:
    """对单个模板在样本集上跑评估。"""
    results: list[EvalSample] = []
    for sample in samples:
        start = time.monotonic()
        try:
            llm_output = await call_llm(tpl, sample)
            latency = time.monotonic() - start
            schema_valid, value_in_range, has_evidence = validate_output_schema(
                llm_output, tpl.output_schema
            )
            results.append(
                EvalSample(
                    template_id=tpl.full_id,
                    sample_id=sample.get("id", "unknown"),
                    schema_valid=schema_valid,
                    value_in_range=value_in_range,
                    has_evidence=has_evidence,
                    rule_deviation=0.0,  # 需规则引擎对比，占位
                    latency_sec=latency,
                    token_usage={},  # 从 LLM response 填充
                    cost_usd=0.0,  # 按 token 用量计算
                )
            )
        except Exception as e:  # noqa: BLE001
            latency = time.monotonic() - start
            results.append(
                EvalSample(
                    template_id=tpl.full_id,
                    sample_id=sample.get("id", "unknown"),
                    schema_valid=False,
                    value_in_range=False,
                    has_evidence=False,
                    rule_deviation=0.0,
                    latency_sec=latency,
                    token_usage={},
                    cost_usd=0.0,
                    error=str(e),
                )
            )
    return results


def aggregate_metrics(samples: list[EvalSample]) -> dict[str, float]:
    """汇总评估指标。"""
    if not samples:
        return {}
    total = len(samples)
    latencies = sorted(s.latency_sec for s in samples)
    p95_idx = int(total * 0.95)
    return {
        "schema_compliance_rate": sum(1 for s in samples if s.schema_valid) / total,
        "value_range_compliance": sum(1 for s in samples if s.value_in_range) / total,
        "evidence_sufficiency": sum(1 for s in samples if s.has_evidence) / total,
        "rule_consistency_mean": sum(s.rule_deviation for s in samples) / total,
        "latency_p95": latencies[min(p95_idx, total - 1)],
        "cost_per_call_mean": sum(s.cost_usd for s in samples) / total,
        "error_rate": sum(1 for s in samples if s.error) / total,
    }


def check_thresholds(metrics: dict[str, float]) -> list[str]:
    """检查指标是否超阈值，返回告警列表。"""
    alerts: list[str] = []
    if metrics.get("schema_compliance_rate", 1.0) < THRESHOLDS["schema_compliance_rate"]:
        alerts.append(
            f"结构遵从率 {metrics['schema_compliance_rate']:.2%} < "
            f"{THRESHOLDS['schema_compliance_rate']:.0%}"
        )
    if metrics.get("value_range_compliance", 1.0) < THRESHOLDS["value_range_compliance"]:
        alerts.append(f"数值合理性 {metrics['value_range_compliance']:.2%} 未达 100%")
    if metrics.get("evidence_sufficiency", 1.0) < THRESHOLDS["evidence_sufficiency"]:
        alerts.append(f"证据充分性 {metrics['evidence_sufficiency']:.2%} 未达 100%")
    if metrics.get("rule_consistency_mean", 0.0) > THRESHOLDS["rule_consistency_max"]:
        alerts.append(
            f"规则一致性偏差 {metrics['rule_consistency_mean']:.3f} > "
            f"{THRESHOLDS['rule_consistency_max']}"
        )
    if metrics.get("latency_p95", 0.0) > THRESHOLDS["latency_p95_max"]:
        alerts.append(
            f"延迟 P95 {metrics['latency_p95']:.1f}s > "
            f"{THRESHOLDS['latency_p95_max']}s"
        )
    return alerts


def generate_report(
    template_results: dict[str, list[EvalSample]],
    template_metrics: dict[str, dict[str, float]],
) -> str:
    """生成 Markdown 评估报告。"""
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    lines = [
        f"# LLM 评估报告 — {now}",
        "",
        f"评估时间: {datetime.now(timezone.utc).isoformat()}",
        f"样本数: {len(load_golden_samples(0))}",
        "",
        "## 指标汇总",
        "",
        "| Prompt | 结构遵从率 | 数值合理性 | 证据充分性 | 规则一致性 | 延迟 P95 | 成本/次 |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    for tpl_id, metrics in template_metrics.items():
        lines.append(
            f"| {tpl_id} | {metrics.get('schema_compliance_rate', 0):.2%} | "
            f"{metrics.get('value_range_compliance', 0):.2%} | "
            f"{metrics.get('evidence_sufficiency', 0):.2%} | "
            f"{metrics.get('rule_consistency_mean', 0):.3f} | "
            f"{metrics.get('latency_p95', 0):.1f}s | "
            f"${metrics.get('cost_per_call_mean', 0):.4f} |"
        )

    lines.append("")
    lines.append("## 告警")
    all_alerts: list[str] = []
    for tpl_id, metrics in template_metrics.items():
        alerts = check_thresholds(metrics)
        if alerts:
            lines.append(f"### {tpl_id}")
            for a in alerts:
                lines.append(f"- ⚠️ {a}")
            all_alerts.extend(alerts)
    if not all_alerts:
        lines.append("无告警，所有指标达标。")

    lines.append("")
    lines.append("## 阈值参考")
    lines.append("")
    lines.append("| 维度 | 目标 | 告警阈值 |")
    lines.append("| --- | --- | --- |")
    for key, val in THRESHOLDS.items():
        lines.append(f"| {key} | {val} | {val} |")

    return "\n".join(lines)


def save_metrics_history(template_metrics: dict[str, dict[str, float]]) -> None:
    """追加指标到历史时间序列。"""
    history: list[dict[str, Any]] = []
    if METRICS_HISTORY.exists():
        try:
            history = json.loads(METRICS_HISTORY.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            history = []
    entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "results": template_metrics,
    }
    history.append(entry)
    METRICS_HISTORY.write_text(
        json.dumps(history, indent=2, ensure_ascii=False), encoding="utf-8"
    )


async def run_evaluation(
    samples: int, agent_filter: list[str] | None
) -> int:
    """运行 LLM 评估主流程。返回退出码（0=成功，1=有告警）。"""
    templates = discover_prompt_templates(agent_filter)
    if not templates:
        print("未发现匹配的 Prompt 模板。", file=sys.stderr)
        return 1

    golden = load_golden_samples(samples)
    if not golden:
        print(f"无 golden 样本可用（{GOLDEN_SAMPLES}），无法跑评估。", file=sys.stderr)
        return 1

    print(f"开始评估 {len(templates)} 个 Prompt 模板，每个 {len(golden)} 样本...")
    template_results: dict[str, list[EvalSample]] = {}
    template_metrics: dict[str, dict[str, float]] = {}

    for tpl in templates:
        print(f"  评估 {tpl.full_id}...")
        try:
            results = await evaluate_template(tpl, golden)
        except NotImplementedError as e:
            print(f"    [SKIP] {e}", file=sys.stderr)
            continue
        template_results[tpl.full_id] = results
        metrics = aggregate_metrics(results)
        template_metrics[tpl.full_id] = metrics

    if not template_metrics:
        print("无评估结果（LLM 调用未实现）。", file=sys.stderr)
        return 1

    # 生成报告
    report = generate_report(template_results, template_metrics)
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    report_path = REPORT_DIR / f"{now}_benchmark.md"
    report_path.write_text(report, encoding="utf-8")
    print(f"\n报告已生成: {report_path}")

    # 保存历史指标
    save_metrics_history(template_metrics)
    print(f"历史指标已更新: {METRICS_HISTORY}")

    # 检查阈值
    has_alerts = False
    for tpl_id, metrics in template_metrics.items():
        alerts = check_thresholds(metrics)
        if alerts:
            has_alerts = True
            print(f"\n⚠️ {tpl_id} 告警:")
            for a in alerts:
                print(f"  - {a}")

    return 1 if has_alerts else 0


# ──────────────────────────────────────────────
# 3. CLI 入口
# ──────────────────────────────────────────────


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="LLM Prompt 模板校验与评估脚本",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--validate-templates-only",
        action="store_true",
        help="仅校验模板结构，不调用 LLM（不需 API key）",
    )
    parser.add_argument(
        "--samples",
        type=int,
        default=100,
        help="评估样本数（默认 100）",
    )
    parser.add_argument(
        "--agents",
        type=str,
        default=None,
        help="过滤 Agent（逗号分隔，如 narrative,team,risk,tokenomics）",
    )
    parser.add_argument(
        "--benchmark",
        action="store_true",
        help="Benchmark 模式：对比多版本 Prompt",
    )
    parser.add_argument(
        "--prompt-versions",
        type=str,
        default=None,
        help="指定对比的 Prompt 版本（逗号分隔，如 narrative/v1,narrative/v2）",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    agent_filter = None
    if args.agents:
        agent_filter = [a.strip() for a in args.agents.split(",")]

    if args.validate_templates_only:
        results = run_template_validation(agent_filter)
        failed = [r for r in results if not r.valid]
        return 1 if failed else 0

    if args.benchmark:
        if not args.prompt_versions:
            print("--benchmark 模式需指定 --prompt-versions", file=sys.stderr)
            return 1
        # benchmark 模式：过滤指定版本
        version_filter = [v.split("/")[0] for v in args.prompt_versions.split(",")]
        agent_filter = version_filter

    try:
        return asyncio.run(run_evaluation(args.samples, agent_filter))
    except KeyboardInterrupt:
        print("\n评估被中断。", file=sys.stderr)
        return 130


if __name__ == "__main__":
    sys.exit(main())
