"""前端结构一致性回归：导航指向的页面必须存在，组件必须真的被用到。

## 为什么需要这一组测试

本轮清理时发现 `components/AppShell.tsx` —— 一个完整的 137 行导航外壳，
带自己的一套 `NAV_ITEMS`（只有 3 项）、健康指示灯、主题切换、移动端底栏 ——
**全仓没有任何文件 import 它**。真正在用的是 `components/Nav.tsx`（10 项导航）。

孤儿组件的危害不是占空间，而是**它会被当成现状读**：

- 我自己在审计导航时就先翻到了 `AppShell.tsx` 的 3 项 `NAV_ITEMS`，
  一度以为侧栏只有 3 个入口。任何人（或 AI）审这个仓库都会踩同一脚。
- 它带着一份**独立演化的旧逻辑**（健康探测、主题存 `aa-theme-v2`），
  与真正生效的 `Nav.tsx` / `ThemeProvider.tsx` 分道扬镳。改错文件不会有
  任何报错 —— 改完刷新页面毫无变化，最难查的那种。

`tsc` 和 `eslint` 都不会报孤儿文件：它自身语法正确、类型正确。
所以只能靠一条显式断言。

## 判定规则

- `components/*.tsx` 里每个组件都必须被 `app/` 或其他组件 import 到。
- 侧栏导航的每个 `href` 都必须对应一个真实的 `app/<path>/page.tsx`。
  一个指向 404 的导航项，用户点了才知道 —— 而且会以为是系统坏了。
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
FRONTEND = REPO_ROOT / "frontend-next"
COMPONENTS = FRONTEND / "components"
APP = FRONTEND / "app"
NAV = COMPONENTS / "Nav.tsx"


def _require_frontend() -> None:
    if not FRONTEND.is_dir():
        pytest.skip(f"前端目录不存在（可能是仅后端的检出）：{FRONTEND}")


def _all_source_text() -> str:
    """把 app/ 与 components/ 下所有 ts/tsx 源码拼成一段文本。"""
    _require_frontend()
    parts: list[str] = []
    for directory in (APP, COMPONENTS):
        for path in sorted(directory.rglob("*.ts*")):
            parts.append(path.read_text(encoding="utf-8"))
    assert parts, f"没有在 {APP} / {COMPONENTS} 下读到任何源文件，解析已失效。"
    return "\n".join(parts)


def _component_names() -> list[str]:
    _require_frontend()
    names = sorted(p.stem for p in COMPONENTS.glob("*.tsx"))
    assert len(names) >= 5, f"只找到 {len(names)} 个组件文件，解析已失效。"
    return names


def _nav_hrefs() -> list[str]:
    """取侧栏 `navItems` 里的全部 href。"""
    _require_frontend()
    if not NAV.is_file():
        pytest.skip(f"导航组件不存在：{NAV}")
    src = NAV.read_text(encoding="utf-8")
    match = re.search(r"const navItems = \[(.*?)\n\];", src, re.S)
    assert match, (
        f"在 {NAV.name} 里找不到 `const navItems = [...]`。导航若被改名或改写，请同步更新本测试，别让它静默什么都不查。"
    )
    hrefs = re.findall(r"href:\s*'([^']+)'", match.group(1))
    assert len(hrefs) >= 5, f"只解析到 {len(hrefs)} 个导航 href，解析器已失效。"
    return hrefs


class TestNoOrphanComponents:
    """每个组件文件都必须被真的 import。"""

    def test_every_component_is_imported(self) -> None:
        source = _all_source_text()
        orphans = []
        for name in _component_names():
            # 自身文件里必然出现组件名（定义处），所以按 import 语句判断
            imported = re.search(rf"from '@/components/{re.escape(name)}'", source) or re.search(
                rf"from '\./{re.escape(name)}'", source
            )
            if not imported:
                orphans.append(name)
        assert not orphans, (
            f"这些组件没有任何地方 import：{orphans}。\n"
            "孤儿组件不是无害的死代码 —— 它会被当成现状读："
            "审代码的人（或 AI）翻到它就以为那是生效的实现，"
            "改了半天却毫无效果，因为真正跑的是另一个文件。"
        )


class TestNavTargetsExist:
    """侧栏每个入口都必须对应一个真实页面。"""

    def test_every_nav_href_has_a_page(self) -> None:
        missing = []
        for href in _nav_hrefs():
            relative = href.strip("/")
            page = APP / "page.tsx" if not relative else APP / relative / "page.tsx"
            if not page.is_file():
                missing.append(f"{href} → 期望 {page.relative_to(FRONTEND)}")
        assert not missing, (
            "这些导航入口没有对应页面，点进去是 404：\n  "
            + "\n  ".join(missing)
            + "\n用户点了才知道，而且会以为是系统坏了而不是入口写错了。"
        )

    def test_every_page_is_reachable_from_nav(self) -> None:
        """反向：每个页面都要有入口能走到（动态路由除外）。

        一个没有入口的页面等于没做 —— 功能在仓库里，用户永远找不到。
        动态详情页（`project/[id]`）由列表项跳转，不该出现在侧栏。
        """
        _require_frontend()
        hrefs = {h.strip("/") for h in _nav_hrefs()}
        unreachable = []
        for page in sorted(APP.rglob("page.tsx")):
            relative = page.parent.relative_to(APP).as_posix()
            slug = "" if relative == "." else relative
            if "[" in slug:  # 动态路由靠列表跳转，不进侧栏
                continue
            if slug not in hrefs:
                unreachable.append(slug or "/")
        assert not unreachable, f"这些页面在侧栏里没有入口：{unreachable}。功能在仓库里，用户找不到。"


class TestParsersFailLoudly:
    """解析器自检：静默返回空集合会让上面所有断言假通过。"""

    def test_nav_parser_finds_known_entries(self) -> None:
        hrefs = _nav_hrefs()
        assert "/" in hrefs
        assert "/insights" in hrefs
        assert "/ops" in hrefs

    def test_component_scan_finds_known_files(self) -> None:
        names = _component_names()
        assert "Nav" in names
        assert "Charts" in names

    def test_nav_parser_rejects_missing_declaration(self) -> None:
        assert not re.search(r"const navItems = \[(.*?)\n\];", "const other = [];", re.S)
