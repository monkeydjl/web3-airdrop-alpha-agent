"""`Test DB Isolation Gate` PR 门禁的接线回归 —— 防止这道第二防线被悄悄摘掉。

背景见 `.github/workflows/ci.yml` 里 `test-db-isolation` job 的注释，以及
`tests/test_db_isolation_enumeration.py`（枚举器本身的回归钉子）。
本文件只钉「门禁接线」四件事：job 名、是否每次都报、关键路径判定、跑哪一桶。

## 为什么值得单独钉

这道门禁的全部价值在于「当某次 PR 的改动落在静态守卫的盲区里时，它真的会跑」。
它一旦被删、被改名、或被加错条件（最典型：把 `Detect DB-relevant changes`
步骤也加上 `if`），CI 依旧全绿 —— 而下一次同类隐式默认库依赖就又能溜过去。
所以下面每条断言对应的都是一个「静默失效」的具体入口：

- **job 名**：分支保护按名字匹配。改名 = required check 永远 pending。
- **detect 步骤无条件**：带条件就会被提前跳过，job 不报 → pending。
- **关键路径正则**：漏一条路径 = 那类改动上永远不跑。
- **`--bucket indirect`**：跑错桶（比如只跑探针）等于没跑。

与 `tests/test_deployment.py` 同一套 YAML 读取方式（`on` 会被 PyYAML
解析成布尔，需就地替换掉）。
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
CI_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "ci.yml"

GATE_JOB_KEY = "test-db-isolation"
GATE_CHECK_NAME = "Test DB Isolation Gate"
DETECT_STEP_NAME = "Detect DB-relevant changes"
ACID_STEP_NAME = "Run indirect-bucket acid test"
RELEVANT_CONDITION = "steps.detect.outputs.relevant == 'true'"

# 关键路径前缀：改动落在这些路径下才触发酸测。少一条就是一类改动上的静默盲区。
KEY_PATH_TOKENS = (
    "backend/(app|tests|scripts)/",
    ".github/workflows/ci.yml",
)


def _load_ci() -> dict[str, Any]:
    assert CI_WORKFLOW.is_file(), f"{CI_WORKFLOW} 不存在 —— 被测对象没了，请同步。"
    content = CI_WORKFLOW.read_text(encoding="utf-8")
    # `on` 是 YAML 1.1 布尔字面量，会被 safe_load 解析成 True；就地替换掉。
    # 只替换行首第一个 `on:`，与 tests/test_deployment.py 同一做法。
    workflow = yaml.safe_load(re.sub(r"(?m)^on:", '"on":', content, count=1))
    assert isinstance(workflow, dict) and "jobs" in workflow, "ci.yml 解析不成带 jobs 的映射 —— 解析器已失效。"
    return workflow


def _gate_job() -> dict[str, Any]:
    workflow = _load_ci()
    assert GATE_JOB_KEY in workflow["jobs"], (
        f"ci.yml 里没有 `{GATE_JOB_KEY}` job —— 间接触库空库酸测的 PR 门禁被删了。\n"
        "它是静态守卫盲区（CONVENTIONS §13.4）的唯一动态防线，别静默摘掉。"
    )
    return workflow["jobs"][GATE_JOB_KEY]


def _step(job: dict[str, Any], name: str) -> dict[str, Any]:
    matches = [step for step in job["steps"] if step.get("name") == name]
    assert len(matches) == 1, f"job 里应恰好有一个名为 `{name}` 的步骤，实际找到 {len(matches)} 个。"
    return matches[0]


class TestCheckNameIsStable:
    """job 名就是分支保护匹配的 required check 名，不能悄悄改。"""

    def test_job_name_matches_the_required_check_name(self) -> None:
        assert _gate_job().get("name") == GATE_CHECK_NAME, (
            f"gate job 的 name 变成了 {_gate_job().get('name')!r}，而分支保护登记的是 {GATE_CHECK_NAME!r}。\n"
            "改名会让 required check 找不到对应 job → 永远 pending（`Coverage Gate` 那次卡了 5 天）。"
        )

    def test_check_name_is_unique_across_jobs(self) -> None:
        """同名 job 会让分支保护匹配到错误的那一个。"""
        names = [job.get("name") for job in _load_ci()["jobs"].values()]
        dupes = {name for name in names if names.count(name) > 1}
        assert not dupes, f"ci.yml 里有重名 job：{sorted(dupes)} —— required check 会匹配到错误的那一个。"


class TestGateAlwaysReports:
    """路径过滤靠「探测步骤无条件 + 重活带条件」实现 job 每次都报。"""

    def test_workflow_has_no_pull_request_path_filter(self) -> None:
        """整个 workflow 若加 paths 过滤，不匹配的 PR 上 job 根本不跑 → pending。

        这正是本 job 用「步内探测」而不是 workflow/paths 过滤的原因。
        """
        trigger = _load_ci()["on"]["pull_request"]
        assert "paths" not in trigger and "paths-ignore" not in trigger, (
            f"ci.yml 的 pull_request 触发器加了路径过滤：{trigger}。\n"
            "带 paths 过滤的 workflow 在不匹配的 PR 上不触发，required check 会永久 pending。"
            "路径判定必须留在 `Detect DB-relevant changes` 步骤里。"
        )

    def test_detect_step_is_unconditional(self) -> None:
        detect = _step(_gate_job(), DETECT_STEP_NAME)
        assert "if" not in detect, (
            f"`{DETECT_STEP_NAME}` 步骤被加上了 `if` 条件（{detect.get('if')!r}）。\n"
            "它是「本 job 每次都报」的实现；带条件就会在部分 PR 上提前跳过、required check 挂 pending。"
        )

    def test_heavy_steps_are_gated_on_relevant_output(self) -> None:
        job = _gate_job()
        for name in ("Setup Python", ACID_STEP_NAME, "Install dependencies"):
            matches = [s for s in job["steps"] if str(s.get("name", "")).startswith(name)]
            assert matches, f"gate job 里找不到 `{name}` 步骤 —— 门禁被改动了，请同步本测试。"
            assert matches[0].get("if") == RELEVANT_CONDITION, (
                f"`{matches[0].get('name')}` 的 if 条件是 {matches[0].get('if')!r}，期望 {RELEVANT_CONDITION!r}。\n"
                "重活步骤必须只在探测命中时才跑，否则每个 PR 都要付全量间接触库酸测的代价。"
            )


class TestGateRunsTheIndirectBucket:
    """门禁跑的必须正是间接触库桶 —— 这是它存在的全部理由。"""

    def test_acid_step_invokes_the_isolation_script_on_indirect_bucket(self) -> None:
        run = _step(_gate_job(), ACID_STEP_NAME)["run"]
        assert "scripts/verify_test_db_isolation.py" in run, f"`{ACID_STEP_NAME}` 没有调用酸测脚本：{run!r}"
        assert "--bucket indirect" in run, (
            f"`{ACID_STEP_NAME}` 跑的桶变了：{run!r}。\n"
            "门禁存在的理由就是覆盖 `indirect`（间接触库）桶 —— 换成别的桶等于把盲区又露出来。"
        )

    def test_gate_depends_on_lint(self) -> None:
        """与流水线阶段顺序一致：lint 红时不该再花几分钟跑酸测。"""
        assert _gate_job().get("needs") == "lint", (
            f"gate job 的 needs 变成了 {_gate_job().get('needs')!r}，期望 'lint'。"
        )


class TestKeyPathsAreCovered:
    """探测步骤的正则必须覆盖全部关键路径，且确实写 GITHUB_OUTPUT。"""

    def test_detect_script_covers_every_key_path(self) -> None:
        script = _step(_gate_job(), DETECT_STEP_NAME)["run"]
        # 去掉正则转义（`\.`）后再查 token，避免断言对 YAML 里的反斜杠写法过敏。
        normalized = script.replace("\\", "")
        missing = [token for token in KEY_PATH_TOKENS if token.replace("\\", "") not in normalized]
        assert not missing, f"关键路径判定漏了这些前缀：{missing}。\n漏一条 = 那类改动上永远不会触发酸测（静默盲区）。"

    def test_detect_script_emits_both_outcomes(self) -> None:
        script = _step(_gate_job(), DETECT_STEP_NAME)["run"]
        assert script.count('>> "$GITHUB_OUTPUT"') >= 2, (
            "探测步骤没有把 relevant=true/false 两个分支都写进 $GITHUB_OUTPUT —— "
            "少一个分支会让后续步骤的条件读到空字符串。"
        )
        assert "relevant=true" in script and "relevant=false" in script, (
            f"探测步骤没有同时产出 relevant 的真/假值：{script!r}"
        )


@pytest.mark.parametrize("token", KEY_PATH_TOKENS)
def test_key_path_tokens_are_still_valid_regex(token: str) -> None:
    """token 本身就是正则片段：编译一下，防止写成坏正则让 grep -E 静默失效。"""
    re.compile(token)
