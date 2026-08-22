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

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
FRONTEND = REPO_ROOT / "frontend-next"
PORTFOLIO_PAGE = FRONTEND / "app" / "portfolio" / "page.tsx"
REVIEW_PAGE = FRONTEND / "app" / "review" / "page.tsx"


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


class TestParsersFailLoudly:
    """解析器自检：永远返回空值的解析器会让上面全部断言假通过。"""

    def test_parsers_find_real_tables(self) -> None:
        portfolio = _read(PORTFOLIO_PAGE)
        assert len(_object_keys(portfolio, "OUTCOME_LABEL", PORTFOLIO_PAGE)) >= 5
        assert len(_object_keys(portfolio, "STATUS_LABEL", PORTFOLIO_PAGE)) >= 3
        review = _read(REVIEW_PAGE)
        assert _number_const(review, "BATCH_LIMIT", REVIEW_PAGE) > 0
        assert len(_literal_union(review, "Outcome", REVIEW_PAGE)) >= 2

    def test_missing_declarations_raise(self) -> None:
        with pytest.raises(AssertionError):
            _object_keys("const OTHER = {};", "OUTCOME_LABEL", PORTFOLIO_PAGE)
        with pytest.raises(AssertionError):
            _number_const("const OTHER = 1;", "BATCH_LIMIT", REVIEW_PAGE)
        with pytest.raises(AssertionError):
            _literal_union("type Other = 'a';", "Outcome", REVIEW_PAGE)
