"""ADR 文件与 `docs/adr/README.md` 索引的双向一致性门禁。

## 为什么需要这个文件

`docs/adr/README.md` 的「何时新增 ADR」明确要求每个 ADR 都登记进索引表，
ADR-006 §5 更进一步要求「任何权重默认值 / 阈值初值变更都需新增或更新 ADR」。
但在 2026-09-01 之前，这两条约定**没有任何门禁**：

- 新增 `ADR-0xx-*.md` 却忘记登记索引 → 不报错，ADR 从此隐形
- 索引里写了一个不存在的 ADR 链接 → 不报错，点开 404

这与 `OBSERVABILITY.md §2.2` 事件统计数字腐化到落后一整批事件是同一类问题：
**文档里的清单只要没有门禁，就一定会腐化**。区别只在于多久。

## 双向检查

单向门禁（只查「文档提到的必须存在」）挡不住漏登记，所以这里做双向：

1. 每个 `ADR-0xx-*.md` 文件都必须出现在索引表里
2. 索引表里的每个链接目标都必须真实存在
3. 序号连续、无重复（漏号说明有 ADR 被删而未标 Superseded）
4. 每个 ADR 都有 `Status` 与 `Date` 元数据（TEMPLATE.md 要求的必填字段）
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
ADR_DIR = REPO_ROOT / "docs" / "adr"
INDEX = ADR_DIR / "README.md"

# ADR 正文文件名形如 `ADR-015-eligibility-gate-before-scoring.md`。
# TEMPLATE.md / README.md / ADR_CROSS_REFERENCE.md 不是 ADR 本体，排除。
_ADR_FILE_RE = re.compile(r"^ADR-(\d{3})-[a-z0-9-]+\.md$")

# 索引表里的链接形如 `[ADR-015](ADR-015-eligibility-gate-before-scoring.md)`
_INDEX_LINK_RE = re.compile(r"\[ADR-(\d{3})\]\((ADR-\d{3}-[a-z0-9-]+\.md)\)")


def _adr_files() -> dict[str, Path]:
    """磁盘上的 ADR 本体文件，按三位序号索引。"""
    out: dict[str, Path] = {}
    for path in sorted(ADR_DIR.glob("ADR-*.md")):
        m = _ADR_FILE_RE.match(path.name)
        if m:
            out[m.group(1)] = path
    return out


def _indexed_links() -> dict[str, str]:
    """索引表中登记的 ADR，按三位序号 → 链接目标文件名。"""
    text = INDEX.read_text(encoding="utf-8")
    out: dict[str, str] = {}
    for num, target in _INDEX_LINK_RE.findall(text):
        # 同一 ADR 可能在「按影响面分类」小节被再次引用，取首次即可
        out.setdefault(num, target)
    return out


class TestAdrIndexParity:
    """ADR 本体与索引的双向一致性。"""

    def test_every_adr_file_is_indexed(self) -> None:
        """磁盘上的每个 ADR 都必须登记进索引 —— 挡「新增但忘登记」。"""
        files = _adr_files()
        indexed = _indexed_links()

        missing = sorted(set(files) - set(indexed))
        assert not missing, (
            f"以下 ADR 存在文件但未登记进 docs/adr/README.md 索引表: "
            f"{[files[n].name for n in missing]}\n"
            f"未登记的 ADR 等于不存在 —— 没人会去 ls 目录找决策记录。"
        )

    def test_every_indexed_adr_file_exists(self) -> None:
        """索引里的每个链接都必须指向真实文件 —— 挡「删了/改名但没更新索引」。"""
        files = _adr_files()
        indexed = _indexed_links()

        broken: list[str] = []
        for num, target in sorted(indexed.items()):
            if num not in files:
                broken.append(f"ADR-{num} → {target}（文件不存在）")
            elif files[num].name != target:
                broken.append(f"ADR-{num} 索引指向 {target}，实际文件是 {files[num].name}")

        assert not broken, "docs/adr/README.md 索引存在失效链接:\n  " + "\n  ".join(broken)

    def test_adr_numbers_are_contiguous(self) -> None:
        """序号必须连续 —— 漏号说明有 ADR 被删而未标 Superseded。

        ADR 是决策的历史记录，被推翻的决策应当标 `Superseded by ADR-0xx`
        并留在原地，而不是删掉。删掉会让「当时为什么这么选」永久丢失。
        """
        nums = sorted(int(n) for n in _adr_files())
        assert nums, "docs/adr/ 下没有任何 ADR 文件，路径解析可能出错"

        expected = list(range(1, max(nums) + 1))
        gaps = sorted(set(expected) - set(nums))
        assert not gaps, (
            f"ADR 序号不连续，缺失: {[f'ADR-{n:03d}' for n in gaps]}\n被推翻的决策应标 Superseded 保留原地，不要删除。"
        )

    def test_every_adr_has_status_and_date(self) -> None:
        """每个 ADR 都要有 Status 与 Date —— TEMPLATE.md 的必填元数据。

        没有 Status 无法判断这条决策还生效吗；没有 Date 无法判断它有多旧。
        """
        problems: list[str] = []
        for num, path in sorted(_adr_files().items()):
            head = path.read_text(encoding="utf-8")[:1200]
            if "**Status**" not in head:
                problems.append(f"ADR-{num}（{path.name}）缺少 **Status** 元数据")
            if "**Date**" not in head:
                problems.append(f"ADR-{num}（{path.name}）缺少 **Date** 元数据")

        assert not problems, "ADR 元数据缺失:\n  " + "\n  ".join(problems)
