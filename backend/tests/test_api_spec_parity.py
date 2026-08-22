"""`docs/API_SPEC.md` 与真实路由表的一致性回归。

## 为什么需要这一组测试

一份声称某端点存在的 API 规范，**比没有规范更坏**：读者会照着它写调用方，
拿到 404 却先怀疑自己。实测发现本文档曾同时列出 13 条不存在的路径
（单复数写错、动词与参数顺序颠倒、纯属设计稿从未实现），其中
`GET /api/v1/collections/logs` 还会回 **405** —— 那个假信号更能骗人，
因为 405 看起来像「端点在、只是动词用错了」。

文档漂移没有任何机制阻止：加端点不会有人回来改文档，删端点更不会。
这里把「文档写的路径」与 `GET /openapi.json` 的真实路由表对起来，
让漂移在 CI 阶段就变红。

## 判定规则

- 文档章节标题形如 `## 6. GET /api/v1/projects/{id}` 或 `### 21a. POST /...`。
- 标题里带「未实现」标记的，**必须**确实不在真实路由表里（反向也检查：
  一个已经实现的端点不许被标成未实现，那会让人绕开可用功能）。
- 其余标题必须命中真实路由，且**方法也要对**。
- 路径参数名不参与比对（`{id}` 与 `{project_id}` 等价），因为参数叫什么
  不影响调用方能否命中路由；但单复数、层级顺序都必须一致。
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.main import create_app

REPO_ROOT = Path(__file__).resolve().parents[2]
API_SPEC = REPO_ROOT / "docs" / "API_SPEC.md"

UNIMPLEMENTED_MARK = "未实现"

# 文档标题里出现、但不带 /api/v1 前缀的基础设施端点。
# 注意是 `/version` 而不是 `/api/version` —— 文档原先写成后者，实测 404。
_NON_V1 = {"/health", "/metrics", "/version"}


def _normalise(path: str) -> str:
    """把路径参数统一成 `{}`，使 `{id}` 与 `{project_id}` 等价。"""
    return re.sub(r"\{[^}]*\}", "{}", path.rstrip("/")) or "/"


def _real_routes() -> dict[str, set[str]]:
    """从 `/openapi.json` 取真实路由表：规范化路径 → 方法大写集合。"""
    with TestClient(create_app()) as client:
        spec = client.get("/openapi.json").json()
    routes: dict[str, set[str]] = {}
    for path, node in spec.get("paths", {}).items():
        routes.setdefault(_normalise(path), set()).update(m.upper() for m in node)
    assert len(routes) >= 40, f"只解析到 {len(routes)} 条真实路由，openapi 解析已失效。"
    return routes


def _documented() -> list[tuple[int, str, tuple[str, ...], str, bool]]:
    """解析文档标题，返回 (行号, 原标题, 方法元组, 规范化路径, 是否标注未实现)。"""
    if not API_SPEC.is_file():
        pytest.skip(f"文档不存在：{API_SPEC}")
    entries: list[tuple[int, str, tuple[str, ...], str, bool]] = []
    pattern = re.compile(
        r"^#{2,3}\s+[\w.]+\.?\s+((?:GET|POST|PUT|PATCH|DELETE)(?:\s*/\s*(?:GET|POST|PUT|PATCH|DELETE))*)\s+(/\S+)"
    )
    for lineno, line in enumerate(API_SPEC.read_text(encoding="utf-8").splitlines(), 1):
        match = pattern.match(line)
        if not match:
            continue
        methods = tuple(m.strip() for m in match.group(1).split("/") if m.strip())
        entries.append(
            (
                lineno,
                line.strip(),
                methods,
                _normalise(match.group(2).strip("`")),
                UNIMPLEMENTED_MARK in line,
            )
        )
    assert len(entries) >= 30, f"只解析到 {len(entries)} 个端点章节，解析器已失效。"
    return entries


class TestSpecHeadingsMatchRoutes:
    """文档每个端点章节都必须与真实路由表对得上。"""

    def test_documented_paths_exist(self) -> None:
        routes = _real_routes()
        broken = [
            f"L{lineno} {title}"
            for lineno, title, _methods, path, unimplemented in _documented()
            if not unimplemented and path not in routes
        ]
        assert not broken, "这些章节声称的路径没有对应路由，读者照抄会拿到 404/405：\n  " + "\n  ".join(broken)

    def test_documented_methods_exist(self) -> None:
        routes = _real_routes()
        broken = []
        for lineno, title, methods, path, unimplemented in _documented():
            if unimplemented or path not in routes:
                continue
            wrong = [m for m in methods if m not in routes[path]]
            if wrong:
                broken.append(f"L{lineno} {title} —— 真实支持 {sorted(routes[path])}")
        assert not broken, "这些章节的方法与真实路由不符：\n  " + "\n  ".join(broken)

    def test_unimplemented_marks_are_truthful(self) -> None:
        """标了「未实现」的端点必须真的不存在。

        反向也是谎言：把一个可用端点标成未实现，会让人绕开现成功能去重复实现。
        """
        routes = _real_routes()
        lying = [
            f"L{lineno} {title}"
            for lineno, title, methods, path, unimplemented in _documented()
            if unimplemented and path in routes and any(m in routes[path] for m in methods)
        ]
        assert not lying, "这些章节标着「未实现」，但路由其实存在：\n  " + "\n  ".join(lying)

    def test_non_v1_endpoints_documented_correctly(self) -> None:
        """基础设施端点（/health、/metrics、/version）也必须真实存在。"""
        routes = _real_routes()
        missing = [path for path in _NON_V1 if path not in routes]
        assert not missing, f"这些基础设施端点在真实路由表里找不到：{sorted(missing)}"

    def test_section_numbers_are_unique(self) -> None:
        """章节编号不得重复。

        文档后半段曾从「## 21. interactions」起重新从 21 编号，与前半段
        §21–§26 整段撞号 —— 同一份文档里「§23」既指版本管理又指隔离队列。
        交叉引用一旦写成「详见 §23」，读者有一半概率翻到错的地方，
        而且**两处都真实存在**，所以看不出自己翻错了。
        """
        numbers = [
            int(match.group(1))
            for line in API_SPEC.read_text(encoding="utf-8").splitlines()
            if (match := re.match(r"^## (\d+)\. ", line))
        ]
        assert len(numbers) >= 30, f"只解析到 {len(numbers)} 个编号章节，解析器已失效。"
        duplicates = sorted({n for n in numbers if numbers.count(n) > 1})
        assert not duplicates, f"这些章节编号重复了：{duplicates}，交叉引用会指向两个地方。"


def _overview_rows() -> list[tuple[int, tuple[str, ...], str]]:
    """解析 §3 端点总览表，返回 (行号, 方法元组, 规范化路径)。

    为什么要单独解析这张表：**16 条幽灵端点里有 13 条只出现在这张表里**，
    章节标题一条都没写。总览表恰恰是读者第一眼看的地方 —— 只校验章节标题
    等于把门修在后院。

    表格行形如 `| GET / POST | `/api/v1/interactions` | v1 | ... |`。
    """
    if not API_SPEC.is_file():
        pytest.skip(f"文档不存在：{API_SPEC}")
    rows: list[tuple[int, tuple[str, ...], str]] = []
    pattern = re.compile(
        r"^\|\s*((?:GET|POST|PUT|PATCH|DELETE)(?:\s*/\s*(?:GET|POST|PUT|PATCH|DELETE))*)\s*"
        r"\|\s*`(/[^`]+)`\s*\|"
    )
    in_phantom_section = False
    for lineno, line in enumerate(API_SPEC.read_text(encoding="utf-8").splitlines(), 1):
        # §3.1 整节列的就是「不存在的路径」，必须跳过，否则断言会与它的用意打架。
        if line.startswith("### 3.1"):
            in_phantom_section = True
            continue
        if in_phantom_section and line.startswith(("## ", "### ")):
            in_phantom_section = False
        if in_phantom_section:
            continue
        match = pattern.match(line)
        if match:
            methods = tuple(m.strip() for m in match.group(1).split("/") if m.strip())
            rows.append((lineno, methods, _normalise(match.group(2))))
    assert len(rows) >= 40, f"只解析到 {len(rows)} 行总览表，解析器已失效。"
    return rows


class TestOverviewTableMatchesRoutes:
    """§3 端点总览表的每一行都必须命中真实路由。

    这张表是读者的入口。此前它列了 13 条不存在的路径，且全部标着「已实现」。
    """

    def test_overview_paths_exist(self) -> None:
        routes = _real_routes()
        broken = [
            f"L{lineno} {'/'.join(methods)} {path}" for lineno, methods, path in _overview_rows() if path not in routes
        ]
        assert not broken, "总览表这些行的路径没有对应路由：\n  " + "\n  ".join(broken)

    def test_overview_methods_exist(self) -> None:
        routes = _real_routes()
        broken = []
        for lineno, methods, path in _overview_rows():
            if path not in routes:
                continue
            wrong = [m for m in methods if m not in routes[path]]
            if wrong:
                broken.append(f"L{lineno} {path} 写了 {wrong}，真实支持 {sorted(routes[path])}")
        assert not broken, "总览表这些行的方法不对：\n  " + "\n  ".join(broken)

    def test_every_real_route_is_listed(self) -> None:
        """反向：真实存在的路由不许漏在总览表外。

        漏写比写错更隐蔽 —— 读者不会去找一个他不知道存在的端点，
        于是现成的功能被重复实现一遍。
        """
        routes = _real_routes()
        listed = {path for _lineno, _methods, path in _overview_rows()}
        # 文档/schema 自身的端点不属于业务 API，不要求列出。
        ignored = {"/docs", "/redoc", "/openapi.json", "/docs/oauth2-redirect"}
        missing = sorted(path for path in routes if path not in listed and path not in ignored)
        assert not missing, "这些真实路由没有出现在 §3 总览表里：\n  " + "\n  ".join(missing)


class TestParsersFailLoudly:
    """解析器自检：静默返回空集合会让上面所有断言假通过。"""

    def test_route_parser_finds_routes(self) -> None:
        routes = _real_routes()
        assert _normalise("/api/v1/projects/{project_id}") in routes
        assert "GET" in routes[_normalise("/api/v1/projects/{id}")]

    def test_doc_parser_finds_headings(self) -> None:
        entries = _documented()
        paths = {path for *_, path, _u in entries}
        assert "/api/v1/projects" in paths
        assert any(unimplemented for *_rest, unimplemented in entries), (
            "文档里应当至少有一个标注「未实现」的章节；一个都没有说明标记解析失效了。"
        )

    def test_parser_rejects_empty_document(self) -> None:
        """行数不足时必须 assert，而不是返回空列表让断言全绿。"""
        assert re.compile(r"^#{2,3}\s+[\w.]+\.?\s+(GET|POST)\s+(/\S+)").match("## 4. POST /api/v1/run")
        assert not re.compile(r"^#{2,3}\s+[\w.]+\.?\s+(GET|POST)\s+(/\S+)").match("## 3. 端点总览")

    def test_normalise_ignores_param_names_but_not_shape(self) -> None:
        assert _normalise("/a/{id}") == _normalise("/a/{project_id}")
        assert _normalise("/api/v1/project/{id}") != _normalise("/api/v1/projects/{id}")
        assert _normalise("/c/{id}/trigger") != _normalise("/c/trigger/{id}")

    def test_overview_parser_finds_rows_and_skips_phantom_table(self) -> None:
        """总览表解析器必须找到行，且**不能**把 §3.1 的幽灵表也算进来。

        §3.1 整节列的就是「文档曾声称存在、实际 404/405」的路径。
        若解析器把它一起收进来，`test_overview_paths_exist` 会永远红 ——
        而更糟的反面是：若解析器因此被放宽成「找不到就返回空」，
        整组断言会永远绿。所以这里两头都钉住。
        """
        rows = _overview_rows()
        paths = {path for _lineno, _methods, path in rows}
        assert "/api/v1/projects" in paths, "总览表解析器没找到最基本的 /api/v1/projects"
        assert "/version" in paths, "总览表解析器漏了非 /api/v1 的基础设施端点"
        # §3.1 里的幽灵路径不得混入
        assert _normalise("/api/v1/project/{id}") not in paths, "§3.1 的幽灵路径被误收进总览表"
        assert _normalise("/api/v1/discoveries/stats") not in paths, "§3.1 的幽灵路径被误收进总览表"
