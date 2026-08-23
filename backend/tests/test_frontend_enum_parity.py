"""前端硬编码常量与后端枚举/上限的一致性回归。

## 为什么需要这一组测试

前端有若干「必须与后端保持一致」的常量：结果枚举、状态枚举、批量上限。
它们没有任何机制保证同步——后端改了，前端不会报错，只会**静默错**：

- 结果/状态枚举漏一项 → 界面直接显示英文原文（如 `not_airdropped`），
  中文界面里突然冒出一个原始枚举值。
- 批量上限比后端大 → 整个请求被 422 拒绝，用户看到"保存失败"却不知为何。
- 批量上限比后端小 → 不报错，但白白多发几轮请求。

这类问题在 `test_frontend_flag_parity.py` 里已经出现过一次实例
（洞察页漏了 `wash-trading VC`，被渲染成中性灰）。这里把同样的思路
推广到剩下几张表。

解析方式与 flag parity 那份一致：解析 TSX 源文本，零新增依赖，
且每个解析函数找不到目标时**显式失败**而不是返回空值——
返回空值会让断言假通过，那比没有测试更糟。
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import get_args

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
FRONTEND = REPO_ROOT / "frontend-next"
PORTFOLIO_PAGE = FRONTEND / "app" / "portfolio" / "page.tsx"
REVIEW_PAGE = FRONTEND / "app" / "review" / "page.tsx"
NOTIFICATIONS_PAGE = FRONTEND / "app" / "notifications" / "page.tsx"
NOTIFICATIONS_ROUTER = REPO_ROOT / "backend" / "app" / "routers" / "v1" / "notifications.py"
FORMAT_LIB = FRONTEND / "lib" / "format.ts"
DISCOVERIES_PAGE = FRONTEND / "app" / "discoveries" / "page.tsx"
WORKFLOW_PANEL = FRONTEND / "components" / "OpportunityWorkflowPanel.tsx"
COLLECTORS_DIR = REPO_ROOT / "backend" / "app" / "collectors"


def _read(path: Path) -> str:
    if not path.is_file():
        pytest.skip(f"前端源文件不存在（可能是仅后端的检出）：{path}")
    return path.read_text(encoding="utf-8")


def _object_keys(src: str, decl: str, where: Path) -> set[str]:
    """取 `const <decl>: Record<string, string> = { a: '..', 'b-c': '..' }` 的键。

    键可能带引号也可能不带（`airdropped:` vs `'wash-trading VC':`），两种都要认。
    """
    match = re.search(rf"const\s+{re.escape(decl)}\s*:[^=]*=\s*\{{(.*?)\n\}};", src, re.S)
    assert match, (
        f"在 {where.name} 里找不到 `const {decl} = {{...}}`。"
        "这张表若被改名或改写，请同步更新本测试，不要让它静默地什么都不检查。"
    )
    body = match.group(1)
    quoted = set(re.findall(r"^\s*'([^']+)'\s*:", body, re.M))
    bare = set(re.findall(r"^\s*([A-Za-z_][\w]*)\s*:", body, re.M))
    return quoted | bare


def _number_const(src: str, decl: str, where: Path) -> int:
    """取 `const <decl> = 50;` 的数值。"""
    match = re.search(rf"const\s+{re.escape(decl)}\s*=\s*(\d+)\s*;", src)
    assert match, f"在 {where.name} 里找不到 `const {decl} = <数字>;`"
    return int(match.group(1))


def _literal_union(src: str, decl: str, where: Path) -> set[str]:
    """取 `type <decl> = 'a' | 'b' | 'c';` 的成员。"""
    match = re.search(rf"type\s+{re.escape(decl)}\s*=\s*([^;]+);", src, re.S)
    assert match, f"在 {where.name} 里找不到 `type {decl} = ...;`"
    return set(re.findall(r"'([^']+)'", match.group(1)))


def _inline_map_keys(src: str, func: str, where: Path) -> set[str]:
    """取函数体内 `const map: Record<string, string> = { a: '..' }` 的键。

    `format.ts` 里这些映射写在函数内部而不是模块级常量，所以先切到函数体
    再找那一个 `map` 声明。
    """
    fn = re.search(rf"export function {re.escape(func)}\([^)]*\)[^{{]*\{{(.*?)\n\}}", src, re.S)
    assert fn, f"在 {where.name} 里找不到 `export function {func}(...)`。函数若被改名或改写，请同步更新本测试。"
    body = re.search(r"const map: Record<string, string> = \{(.*?)\n  \};", fn.group(1), re.S)
    assert body, f"{func} 里找不到 `const map: Record<string, string> = {{...}}`"
    return set(re.findall(r"^\s*([A-Za-z_][\w]*)\s*:", body.group(1), re.M))


def _option_ids(src: str, decl: str, where: Path) -> set[str]:
    """取 `const <decl>: {...}[] = [{ id: 'a', label: '..' }, ...]` 的全部 id。

    空字符串 id 是「不选」占位（渲染成「—」），不参与枚举比对。
    """
    match = re.search(rf"const\s+{re.escape(decl)}\s*:[^=]*=\s*\[(.*?)\n\];", src, re.S)
    assert match, f"在 {where.name} 里找不到 `const {decl}: ...[] = [...]`。这张表若被改名或改写，请同步更新本测试。"
    ids = set(re.findall(r"id:\s*'([^']*)'", match.group(1)))
    assert ids, f"{where.name} 的 {decl} 里没解析到任何 `id: '...'`，解析器已失效。"
    return ids - {""}


def _backend_literal_args(name: str) -> set[str]:
    """从 `app.routers.v1.interactions` 取一个 Literal 别名的全部取值。"""
    from typing import get_args

    from app.routers.v1 import interactions

    alias = getattr(interactions, name)
    return set(get_args(alias))


class TestPortfolioEnums:
    """投资组合页的 outcome / status 中文表必须覆盖后端枚举全集。"""

    def test_outcome_labels_cover_backend_enum(self) -> None:
        backend = _backend_literal_args("OutcomeType")
        labelled = _object_keys(_read(PORTFOLIO_PAGE), "OUTCOME_LABEL", PORTFOLIO_PAGE)
        missing = backend - labelled
        assert not missing, f"这些后端 outcome 在 portfolio 页没有中文名：{sorted(missing)}。界面会直接显示英文枚举值。"

    def test_outcome_colors_cover_backend_enum(self) -> None:
        """颜色也要齐：缺色会退回中性灰，把「下跌」显示得和「未知」一样。"""
        backend = _backend_literal_args("OutcomeType")
        coloured = _object_keys(_read(PORTFOLIO_PAGE), "OUTCOME_COLOR", PORTFOLIO_PAGE)
        missing = backend - coloured
        assert not missing, (
            f"这些后端 outcome 在 portfolio 页没有配色：{sorted(missing)}，会退回中性灰，看不出是好结果还是坏结果。"
        )

    def test_no_frontend_only_outcomes(self) -> None:
        """前端不能给后端不产生的 outcome 编中文名——那会让人以为系统会输出它。"""
        backend = _backend_literal_args("OutcomeType")
        labelled = _object_keys(_read(PORTFOLIO_PAGE), "OUTCOME_LABEL", PORTFOLIO_PAGE)
        extra = labelled - backend
        assert not extra, f"portfolio 页 OUTCOME_LABEL 里这些值后端并不产生：{sorted(extra)}"

    def test_status_labels_cover_backend_enum(self) -> None:
        backend = _backend_literal_args("StatusType")
        labelled = _object_keys(_read(PORTFOLIO_PAGE), "STATUS_LABEL", PORTFOLIO_PAGE)
        missing = backend - labelled
        assert not missing, f"这些后端 status 在 portfolio 页没有条目：{sorted(missing)}"


class TestReviewBatchLimit:
    """复盘页的批量上限必须与后端 `FeedbackBatchRequest.items` 的 max_length 一致。"""

    def test_batch_limit_matches_backend(self) -> None:
        from app.routers.v1.feedback import FeedbackBatchRequest

        field = FeedbackBatchRequest.model_fields["items"]
        backend_max = next((m.max_length for m in field.metadata if hasattr(m, "max_length")), None)
        assert backend_max is not None, (
            "后端 FeedbackBatchRequest.items 没有 max_length 约束了？若上限改为不限，请同步删除前端分批逻辑与本测试。"
        )

        frontend_max = _number_const(_read(REVIEW_PAGE), "BATCH_LIMIT", REVIEW_PAGE)
        assert frontend_max == backend_max, (
            f"前端 BATCH_LIMIT={frontend_max}，后端 max_length={backend_max}。"
            "前端偏大会让整个请求被 422 拒绝（用户只看到「保存失败」）；"
            "偏小则白白多发几轮请求。"
        )

    def test_review_outcomes_are_valid_backend_values(self) -> None:
        """复盘页只提供后端 feedback 接受的 outcome 子集。

        注意这里**不要求覆盖全集**：复盘页刻意只让用户标三种最明确的结果，
        这是产品选择。但提供的每一种都必须是后端认的值，否则提交会 422。
        """
        from typing import Literal, get_args, get_origin

        from app.routers.v1.feedback import FeedbackRequest

        # 后端标注是 `Literal[...] | None`，get_args 会先给出
        # (Literal[...], NoneType)，得再往里拆一层才拿到真正的取值。
        annotation = FeedbackRequest.model_fields["outcome"].annotation
        backend: set[str] = set()
        for arg in get_args(annotation):
            if get_origin(arg) is Literal:
                backend |= set(get_args(arg))
        assert backend, (
            "没能从后端 FeedbackRequest.outcome 解出 Literal 取值 —— "
            "标注结构变了，请更新本测试；否则下面的断言会因空集合而假通过。"
        )

        frontend = _literal_union(_read(REVIEW_PAGE), "Outcome", REVIEW_PAGE)
        invalid = frontend - backend
        assert not invalid, f"复盘页提供了后端不接受的 outcome：{sorted(invalid)}，提交会被 422 拒绝。"


class TestNotificationTypes:
    """通知中心的分类入口必须与后端真的会产出的通知类型完全一致。

    后端 `notifications.py` 只聚合三类：`new_project` / `score` / `collector`。
    前端此前还列了 `deadline` / `funding` / `ai`，后端从不产出——于是侧栏常驻
    三个永远显示 0 的入口，点进去永远是空列表。

    **一个永远为空的入口不是「暂时没数据」，而是在承诺一个不存在的功能**。
    这里双向断言：既不能漏（后端有而前端没有 → 该类通知没有分类可看），
    也不能多（前端有而后端没有 → 承诺了不存在的功能）。
    """

    @staticmethod
    def _backend_types() -> set[str]:
        """从路由源码里取出所有 `"type": "<x>"` 字面量。

        比起在这里再抄一份清单，解析源码的好处是后端加新类型时这里会自动跟上，
        只在前端漏掉时才失败。
        """
        src = NOTIFICATIONS_ROUTER.read_text(encoding="utf-8")
        kinds = set(re.findall(r'"type":\s*"(\w+)"', src))
        assert kinds, (
            f"没能从 {NOTIFICATIONS_ROUTER.name} 解出任何 type 字面量 —— "
            "写法变了，请更新本测试；否则下面的断言会因空集合而假通过。"
        )
        return kinds

    def test_frontend_covers_every_backend_type(self) -> None:
        frontend = _literal_union(_read(NOTIFICATIONS_PAGE), "NtfType", NOTIFICATIONS_PAGE)
        missing = self._backend_types() - frontend
        assert not missing, f"后端会产出这些通知类型但前端没有分类：{sorted(missing)}，这类通知在侧栏无处可看。"

    def test_frontend_has_no_phantom_types(self) -> None:
        frontend = _literal_union(_read(NOTIFICATIONS_PAGE), "NtfType", NOTIFICATIONS_PAGE)
        # 'all' 是前端自己的「全部」聚合视图，不对应后端类型
        phantom = frontend - self._backend_types() - {"all"}
        assert not phantom, (
            f"前端列了后端从不产出的通知类型：{sorted(phantom)}。"
            "它们会成为永远显示 0 的入口 —— 那是在承诺一个不存在的功能，"
            "要么后端补上，要么前端删掉。"
        )

    def test_type_label_and_dot_tables_match_types(self) -> None:
        """中文名表与配色表必须覆盖后端类型，且不含幽灵条目。"""
        src = _read(NOTIFICATIONS_PAGE)
        backend = self._backend_types()
        for table in ("TYPE_TAG", "TYPE_DOT"):
            keys = _object_keys(src, table, NOTIFICATIONS_PAGE)
            assert not (backend - keys), f"{table} 缺这些后端类型：{sorted(backend - keys)}"
            assert not (keys - backend), f"{table} 含后端不产出的类型：{sorted(keys - backend)}"


class TestSourceLabels:
    """`sourceZh()` 必须覆盖后端真的会写进 `projects.source` 的全部取值。

    后端写入 source 的地方有三类：
    1. 各采集器的 `source_id`（`app/collectors/*.py`）
    2. 种子数据 `seed`
    3. Excel/CSV 导入 `import`

    实测这张表曾漏掉 `rootdata` 和 `import`，多出一个后端从不产出的 `manual`。
    漏掉 → 中文界面里直接显示原始标识；多出来 → 让人以为系统支持手动录入。
    """

    @staticmethod
    def _backend_sources() -> set[str]:
        ids: set[str] = set()
        for path in COLLECTORS_DIR.glob("*.py"):
            ids |= set(re.findall(r'source_id="(\w+)"', path.read_text(encoding="utf-8")))
        assert ids, (
            f"没能从 {COLLECTORS_DIR.name}/ 解出任何 source_id —— "
            "采集器写法变了，请更新本测试；否则断言会因空集合而假通过。"
        )
        # 非采集器来源：种子数据与文件导入，两者都会写进 projects.source
        return ids | {"seed", "import"}

    def test_covers_every_backend_source(self) -> None:
        labelled = _inline_map_keys(_read(FORMAT_LIB), "sourceZh", FORMAT_LIB)
        missing = self._backend_sources() - labelled
        assert not missing, f"这些后端来源在 sourceZh 里没有中文名：{sorted(missing)}，界面会直接显示原始标识。"

    def test_no_phantom_sources(self) -> None:
        """允许一个例外：裸 `twitter`。

        采集器只声明 `twitter_kol` / `twitter_keyword`，但 `agents/collector.py`
        在归类时会同时匹配裸 `twitter`（历史数据里存在这个值），所以它的中文名
        必须保留。其余多出来的条目都是死条目。
        """
        labelled = _inline_map_keys(_read(FORMAT_LIB), "sourceZh", FORMAT_LIB)
        phantom = labelled - self._backend_sources() - {"twitter"}
        assert not phantom, f"sourceZh 里这些来源后端并不产出：{sorted(phantom)}。死条目会让人以为系统支持这种来源。"


class TestNoHardcodedSourceList:
    """发现页的来源下拉不得再私藏一份采集器清单。

    实测那份硬编码清单当时确实与后端一致 —— 但这属于「碰巧对上」：后端加一个
    采集器，下拉就会漏掉它，而漏掉的表现是「筛选不到」，不是报错。
    现已改为读 `GET /collections/sources`；这条断言防止有人把清单加回来。
    """

    def test_page_reads_sources_from_backend(self) -> None:
        src = _read(DISCOVERIES_PAGE)
        # 必须匹配真正的调用，不能只搜路径字符串 —— 文件顶部的注释里也写着
        # 「GET /collections/sources」，只搜路径的话把调用改坏了测试仍会绿。
        # 这是本仓反复出现的坑：描述规则的文本与遵守规则的代码长得一模一样。
        assert re.search(r"apiFetch<[^>]*>\(\s*'/collections/sources'", src), (
            "发现页没有真的调用 apiFetch('/collections/sources') —— "
            "一旦回到硬编码，后端新增采集器时这个下拉会静默漏掉它。"
        )

    def test_no_hardcoded_source_id_list(self) -> None:
        src = _read(DISCOVERIES_PAGE)
        # 一行里同时出现 3 个以上已知 source_id，基本可断定是一份硬编码清单
        known = TestSourceLabels._backend_sources()
        for line_no, line in enumerate(src.splitlines(), 1):
            hits = {name for name in known if f"'{name}'" in line or f'"{name}"' in line}
            assert len(hits) < 3, (
                f"{DISCOVERIES_PAGE.name}:{line_no} 看起来又写死了一份采集源清单"
                f"（同行出现 {sorted(hits)}）。真值是 GET /collections/sources。"
            )


class TestOpportunityWorkflowEnums:
    """旁路机会引擎面板的三张中文表必须与后端枚举一致。

    这个面板是全前端最大的一处枚举集中地（工作流状态 7 个、资格 3 个、存活 3 个）。
    漏一项的表现与其它页一样：界面上突然冒出一个英文枚举值。
    多一项更隐蔽 —— 它承诺了一个后端永远不会给出的状态。
    """

    @staticmethod
    def _backend_workflow_states() -> set[str]:
        from app.opportunity.workflow import WorkflowState

        values = set(get_args(WorkflowState))
        assert values, "解析 WorkflowState 失败，取到空集合。"
        return values

    def test_state_labels_match_backend(self) -> None:
        src = _read(WORKFLOW_PANEL)
        labelled = _object_keys(src, "STATE_ZH", WORKFLOW_PANEL)
        backend = self._backend_workflow_states()
        assert not backend - labelled, f"这些工作流状态没有中文名：{sorted(backend - labelled)}"
        assert not labelled - backend, f"STATE_ZH 里这些状态后端不产出：{sorted(labelled - backend)}"

    @pytest.mark.parametrize(
        ("decl", "alias"),
        [("ELIGIBILITY_OPTS", "EligibilityResult"), ("SURVIVAL_OPTS", "SurvivalResult")],
    )
    def test_option_lists_match_backend(self, decl: str, alias: str) -> None:
        ids = _option_ids(_read(WORKFLOW_PANEL), decl, WORKFLOW_PANEL)
        backend = _backend_literal_args(alias)
        assert not backend - ids, f"{decl} 漏了后端取值：{sorted(backend - ids)}"
        assert not ids - backend, f"{decl} 里这些取值后端不接受：{sorted(ids - backend)}，提交会被 422 拒绝。"


class TestStageVocabularies:
    """两套「阶段」词汇必须分开，且各自不得收录对方的取值。

    系统里有两个都叫 stage 的东西，含义完全不同：

    - `projects.stage` —— **部署阶段**，采集器写入，取值 ideation/testnet/mainnet
      （「代码上到哪张网了」）
    - `NarrativeResult.stage` —— **叙事生命周期**，取值 early/growth/peak/mature
      （「赛道热度处在周期哪一段」）

    此前前端只有一个 `stageZh`，同时收录两套词汇。一张表接受两套取值，
    等于把口径错配变成了**看不出来的**错配：传错词汇不会显示原文
    （那样反倒能被发现），而是显示另一套口径下一个看着很合理的中文。
    """

    @staticmethod
    def _deployment_stages() -> set[str]:
        """采集器与种子数据实际写入 `projects.stage` 的字面量。"""
        found: set[str] = set()
        for path in sorted(COLLECTORS_DIR.glob("*.py")):
            found |= set(re.findall(r'stage\s*=\s*"(\w+)"', path.read_text(encoding="utf-8")))
            found |= set(re.findall(r'"stage":\s*"(\w+)"', path.read_text(encoding="utf-8")))
        seed = (COLLECTORS_DIR.parent / "seed.py").read_text(encoding="utf-8")
        found |= set(re.findall(r'"stage":\s*"(\w+)"', seed))
        # defillama 的 _infer_stage 只返回这两个，用返回语句核对
        defillama = (COLLECTORS_DIR / "defillama.py").read_text(encoding="utf-8")
        infer = re.search(r"def _infer_stage\(.*?\n(?=\s{4}def )", defillama, re.S)
        assert infer, "defillama.py 里找不到 _infer_stage —— 部署阶段的取值来源变了，请同步本测试。"
        found |= set(re.findall(r'return "(\w+)"', infer.group(0)))
        assert len(found) >= 3, f"没解析到部署阶段字面量（只拿到 {sorted(found)}），解析器已失效。"
        return found

    @staticmethod
    def _lifecycle_stages() -> set[str]:
        """`NarrativeResult.stage` 的 pattern 允许的取值。"""
        from app.models import NarrativeResult

        for meta in NarrativeResult.model_fields["stage"].metadata:
            pattern = getattr(meta, "pattern", None)
            if pattern:
                values = set(re.findall(r"\w+", pattern.strip("^$()")))
                assert values, f"解析 NarrativeResult.stage 的 pattern 失败：{pattern}"
                return values
        raise AssertionError("NarrativeResult.stage 没有 pattern 约束了 —— 真值来源变了，请同步本测试。")

    @staticmethod
    def _timings() -> set[str]:
        """穷举 `stage_to_timing()` 的全部合法输入，得到 timing 的可达取值。

        不读 pattern 而是真的调用函数：pattern 说的是「允许什么」，
        这里要的是「实际会产出什么」。曾有一个 `growth` 中文名，
        pattern 允许不了它、函数也永远不返回它 —— 是纯死条目。
        """
        from app.agents.narrative import stage_to_timing

        reachable = {stage_to_timing(s) for s in TestStageVocabularies._lifecycle_stages()}
        assert reachable, "stage_to_timing 没有产出任何取值，解析器已失效。"
        return reachable

    def test_stage_zh_covers_deployment_only(self) -> None:
        labelled = _inline_map_keys(_read(FORMAT_LIB), "stageZh", FORMAT_LIB)
        deployment = self._deployment_stages()
        missing = deployment - labelled
        assert not missing, f"stageZh 漏了这些部署阶段：{sorted(missing)}，界面会显示英文原文。"
        intruders = labelled & (self._lifecycle_stages() - deployment)
        assert not intruders, (
            f"stageZh 收录了叙事生命周期的取值 {sorted(intruders)}。"
            "两套词汇必须分开，否则口径传错时会显示一个看着合理的错答案。"
        )

    def test_lifecycle_stage_zh_covers_lifecycle_only(self) -> None:
        labelled = _inline_map_keys(_read(FORMAT_LIB), "lifecycleStageZh", FORMAT_LIB)
        lifecycle = self._lifecycle_stages()
        missing = lifecycle - labelled
        assert not missing, f"lifecycleStageZh 漏了这些生命周期取值：{sorted(missing)}。"
        intruders = labelled & (self._deployment_stages() - lifecycle)
        assert not intruders, f"lifecycleStageZh 收录了部署阶段的取值 {sorted(intruders)}。"

    def test_timing_zh_has_no_unreachable_entry(self) -> None:
        labelled = _inline_map_keys(_read(FORMAT_LIB), "timingZh", FORMAT_LIB)
        reachable = self._timings()
        missing = reachable - labelled
        assert not missing, f"timingZh 漏了这些时机取值：{sorted(missing)}。"
        dead = labelled - reachable
        assert not dead, (
            f"timingZh 里这些取值后端永远不会产出：{sorted(dead)}。死条目会让人以为系统还有额外的判断档位。"
        )

    def test_detail_page_does_not_cross_vocabularies(self) -> None:
        """详情页叙事面板的「阶段」不得兜底到部署阶段。

        兜底看起来贴心，实际是拿另一套口径的答案填这一格：
        7 个没有叙事结果的项目会在生命周期这一格显示「主网」。
        """
        src = _read(FRONTEND / "app" / "project" / "[id]" / "page.tsx")
        assert "lifecycleStageZh(String(narrative.stage ?? ''))" in src, (
            "详情页叙事面板的「阶段」不再是「只读 narrative.stage、缺了显示 —」。"
            "一旦兜底到 project.stage，就会用部署阶段冒充生命周期。"
        )


class TestRiskLevelVocabulary:
    """`riskLevelZh` 必须覆盖它真实收到的取值，且不含不可达的死条目。

    系统里有**两套风险档位**，取值范围不同，这是最容易出错的地方：

    - 评分管道侧（三档）：`team.risk_level` 由 `score_to_risk_level()` 产出，
      `risk.sybil_difficulty` / `farming_cost` / `unlock_pressure` 由
      `RiskResult` 的 pattern 约束 —— 全都只有 `low/medium/high`
    - Opportunity 侧（**四档**）：`opportunity.models.RiskLevel` 多一个
      `critical`，用于 `OpportunityAssessment.risks` 的 5 个维度

    `riskLevelZh` 的 4 个调用点全部来自第一套。此前它多写了一个
    `unknown: '未知'` —— **不可达的死条目**：缺值走的是函数开头
    `if (!level) return '—'`，永远到不了那张表。这跟 `timingZh` 里那个
    `growth` 是同一类问题：**死条目会让人以为系统还有额外的判断档位。**

    而 `critical` 是反方向的风险：真值存在、只是前端还没渲染。
    一旦有人开始展示 `risks`，`critical` 会**直接渲染成英文原文**。
    所以这里同时钉两头：多的要没有，少的要有人管。
    """

    @staticmethod
    def _pipeline_risk_values() -> set[str]:
        """评分管道侧真实可达的取值（穷举 + 读 pattern，不抄字面量）。"""
        from app.agents.team import score_to_risk_level
        from app.models import RiskResult

        reachable = {score_to_risk_level(i / 100) for i in range(101)}
        assert reachable, "score_to_risk_level 没产出任何取值，解析器已失效。"
        for field in ("unlock_pressure", "sybil_difficulty", "farming_cost"):
            pattern = next(
                (p for p in (getattr(m, "pattern", None) for m in RiskResult.model_fields[field].metadata) if p),
                None,
            )
            assert pattern, f"RiskResult.{field} 没有 pattern 约束了 —— 真值来源变了，请同步本测试。"
            values = set(re.findall(r"\w+", pattern.strip("^$()")))
            assert values, f"解析 RiskResult.{field} 的 pattern 失败：{pattern}"
            reachable |= values
        assert len(reachable) == 3, f"评分管道侧的风险档位不再是 3 档，而是 {sorted(reachable)} —— 请同步前端与本测试。"
        return reachable

    def test_covers_every_reachable_pipeline_value(self) -> None:
        labelled = _inline_map_keys(_read(FORMAT_LIB), "riskLevelZh", FORMAT_LIB)
        missing = self._pipeline_risk_values() - labelled
        assert not missing, f"riskLevelZh 漏了这些风险档位：{sorted(missing)}，界面会直接显示英文原文。"

    def test_has_no_unreachable_entry(self) -> None:
        labelled = _inline_map_keys(_read(FORMAT_LIB), "riskLevelZh", FORMAT_LIB)
        dead = labelled - self._pipeline_risk_values()
        assert not dead, (
            f"riskLevelZh 里这些取值它的 4 个调用点永远不会收到：{sorted(dead)}。"
            "缺值走的是 `if (!level) return '—'`，到不了这张表；死条目会让人以为系统还有额外档位。"
        )

    def test_critical_is_not_silently_renderable(self) -> None:
        """`critical` 只属于 Opportunity 侧，前端一旦开始渲染 `risks` 就必须先补它。

        判据是「前端有没有读 `risks` 的 5 个维度」：
        - 没读 → `critical` 到不了 `riskLevelZh`，当前状态是安全的
        - 读了 → `riskLevelZh` 必须已经有 `critical` 条目，否则渲染英文原文

        这条不写死"前端不能渲染 risks"（那会挡住正常开发），
        而是把两件事绑在一起：**要渲染就得先把词补齐。**
        """
        from app.opportunity.models import RiskLevel

        opp_values = {e.value for e in RiskLevel}
        assert "critical" in opp_values, "Opportunity 侧不再有 critical 档 —— 这条测试的前提变了，请同步。"

        dimensions = ("capital_security", "eligibility", "project_failure", "reward_dilution", "liquidity")
        renderers: list[str] = []
        for path in sorted(FRONTEND.rglob("*.tsx")) + sorted(FRONTEND.rglob("*.ts")):
            if "node_modules" in path.parts or ".next" in path.parts:
                continue
            src = path.read_text(encoding="utf-8")
            # 只认「读出来渲染」的形态（`risks.x` / `risks?.x`），
            # 不认 fixture 里的对象字面量（`risks: { capital_security: ... }`）——
            # 那是造测试数据，不会进 riskLevelZh。
            if any(re.search(rf"risks\??\.{d}\b", src) for d in dimensions):
                renderers.append(path.name)

        labelled = _inline_map_keys(_read(FORMAT_LIB), "riskLevelZh", FORMAT_LIB)
        if renderers:
            assert "critical" in labelled, (
                f"{renderers} 开始渲染 opportunity 的 risks 维度了，但 riskLevelZh 没有 `critical` 条目 —— "
                "后端 RiskLevel 有四档，会直接显示英文 `critical`。请补中文名（并检查配色是否也要补）。"
            )
        else:
            assert "critical" not in labelled, (
                "riskLevelZh 里有 `critical`，但前端没有任何地方渲染 opportunity 的 risks 维度 —— "
                "这会变成一个不可达的死条目。真要渲染时再补。"
            )


class TestParsersFailLoudly:
    """解析器自检：永远返回空值的解析器会让上面全部断言假通过。"""

    def test_parsers_find_real_tables(self) -> None:
        portfolio = _read(PORTFOLIO_PAGE)
        assert len(_object_keys(portfolio, "OUTCOME_LABEL", PORTFOLIO_PAGE)) >= 5
        assert len(_object_keys(portfolio, "STATUS_LABEL", PORTFOLIO_PAGE)) >= 3
        review = _read(REVIEW_PAGE)
        assert _number_const(review, "BATCH_LIMIT", REVIEW_PAGE) > 0
        assert len(_literal_union(review, "Outcome", REVIEW_PAGE)) >= 2
        notifications = _read(NOTIFICATIONS_PAGE)
        assert len(_literal_union(notifications, "NtfType", NOTIFICATIONS_PAGE)) >= 3
        assert len(TestNotificationTypes._backend_types()) >= 3
        assert len(_inline_map_keys(_read(FORMAT_LIB), "sourceZh", FORMAT_LIB)) >= 8
        assert len(TestSourceLabels._backend_sources()) >= 8
        assert len(TestStageVocabularies._deployment_stages()) >= 3
        assert len(TestStageVocabularies._lifecycle_stages()) == 4
        assert len(TestStageVocabularies._timings()) == 3
        assert len(_inline_map_keys(_read(FORMAT_LIB), "riskLevelZh", FORMAT_LIB)) == 3
        assert TestRiskLevelVocabulary._pipeline_risk_values() == {"low", "medium", "high"}
        panel = _read(WORKFLOW_PANEL)
        assert len(_object_keys(panel, "STATE_ZH", WORKFLOW_PANEL)) >= 5
        assert len(_option_ids(panel, "ELIGIBILITY_OPTS", WORKFLOW_PANEL)) >= 3
        assert len(TestOpportunityWorkflowEnums._backend_workflow_states()) >= 5

    def test_missing_declarations_raise(self) -> None:
        with pytest.raises(AssertionError):
            _object_keys("const OTHER = {};", "OUTCOME_LABEL", PORTFOLIO_PAGE)
        with pytest.raises(AssertionError):
            _number_const("const OTHER = 1;", "BATCH_LIMIT", REVIEW_PAGE)
        with pytest.raises(AssertionError):
            _literal_union("type Other = 'a';", "Outcome", REVIEW_PAGE)
        with pytest.raises(AssertionError):
            _inline_map_keys("export function other() {\n}\n", "sourceZh", FORMAT_LIB)
        with pytest.raises(AssertionError):
            _option_ids("const OTHER = [];", "ELIGIBILITY_OPTS", WORKFLOW_PANEL)
        with pytest.raises(AssertionError):
            # 声明找得到但里面没有任何 id → 也必须炸，不能返回空集合
            _option_ids(
                "const ELIGIBILITY_OPTS: X[] = [\n  { label: '无 id' },\n];",
                "ELIGIBILITY_OPTS",
                WORKFLOW_PANEL,
            )
