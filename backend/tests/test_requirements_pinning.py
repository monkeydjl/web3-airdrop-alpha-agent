"""`requirements.txt` 必须精确锁定每一个依赖，传递依赖也不例外。

## 为什么需要这个测试

本文件开头就写着「版本已锁定（== 精确版本）」，理由是「本地测过的组合与
线上跑的组合必须是一回事」。但这条原则此前**只是注释，没有门禁** ——
而注释拦不住任何东西。

2026-09-04 的 CI 事故就是这么来的（run 33883265813）：`anyio` 与
`starlette` 是 fastapi 的传递依赖、没有写进 `requirements.txt`，于是
本机 venv 停在旧版、CI 每次全新安装都拉最新版 —— **两边跑的不是同一个
组合**，正是那段注释警告过的情形。当 anyio 4.15.0 把
`anyio.abc.BlockingPortal` 变成弃用别名，而 starlette 的 testclient
仍用这个别名做类型注解时，CI 的 `-W error::DeprecationWarning` 把它
升级为错误，32 个 import TestClient 的测试文件在**收集阶段**全部报错，
整套测试 exit code 2、**一个用例都没跑起来**。本机因为装着旧 anyio，
同样的命令全绿，完全看不到这个问题。

这类故障的共同点是**沉默**：不锁传递依赖不会报错、不会变红，只会让
「本机通过」这件事逐渐失去意义，直到某天上游发一个 deprecation 才一次性
爆开。而爆开的位置（第三方库内部的类型注解）是项目代码改不动的地方。

## 测什么

1. 曾经咬过人的 ASGI 传递依赖必须显式出现且用 `==` 锁定。
2. `requirements.txt` 里**每一行**依赖都必须是 `==` 精确锁定，不接受
   `>=` / `~=` / `<` / 裸包名。
3. 刻意不断言具体版本号：门禁要约束的是「必须锁」，而不是「锁在某个值」，
   否则每次合法升级都会无意义地变红，最后只会被人删掉。

`requirements-otel.txt` 不在本门禁范围内 —— 那 7 个可选包在锁定作业时
无法访问 PyPI，文件里已诚实说明保留区间约束，写一个没验证过的版本号
比不写更危险。
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
REQUIREMENTS = REPO_ROOT / "backend" / "requirements.txt"

# 已经在 CI 上真实咬过人的传递依赖。它们不是 fastapi 的实现细节：
# starlette 的 TestClient 是全部 API 测试的入口，anyio 是它的运行时基座，
# 任一方漂移都能让整套测试在收集阶段崩掉。
MUST_BE_PINNED = ("anyio", "starlette")

# 依赖名 + 可选 extras + == + 版本，例如：
#   fastapi==0.141.1
#   uvicorn[standard]==0.52.1
_PINNED = re.compile(r"^(?P<name>[A-Za-z0-9._-]+)(?:\[[A-Za-z0-9,._-]+\])?==[^\s;]+")


def _dependency_lines() -> list[str]:
    """requirements.txt 里真正声明依赖的那些行（去掉注释与空行）。"""
    lines = REQUIREMENTS.read_text(encoding="utf-8").splitlines()
    return [stripped for raw in lines if (stripped := raw.strip()) and not stripped.startswith("#")]


def _pinned_names() -> set[str]:
    """已经用 == 锁死的依赖名，统一小写便于比较。"""
    names: set[str] = set()
    for line in _dependency_lines():
        if match := _PINNED.match(line):
            names.add(match.group("name").lower())
    return names


def test_requirements_file_exists() -> None:
    """文件路径写错会让下面所有断言变成空集比较、静默通过。"""
    assert REQUIREMENTS.is_file(), f"找不到 {REQUIREMENTS}"
    assert _dependency_lines(), "requirements.txt 里没有解析到任何依赖行"


def test_asgi_transitive_deps_are_explicitly_pinned() -> None:
    """anyio / starlette 必须自己出现在文件里，不能只靠 fastapi 带进来。

    只要它们不在这里，版本就由安装时刻的 PyPI 决定 —— 本机与 CI 必然分叉。
    """
    pinned = _pinned_names()
    missing = [name for name in MUST_BE_PINNED if name not in pinned]
    assert not missing, (
        f"这些 ASGI 传递依赖没有在 backend/requirements.txt 里用 == 锁定：{missing}。"
        "它们不锁就会在 CI 上漂移到最新版，"
        "上游一个 deprecation 就能让整套 API 测试在收集阶段崩掉（见本文件 docstring）。"
    )


def test_every_dependency_uses_exact_version() -> None:
    """每一行都必须是 ==，不接受区间约束或裸包名。

    区间约束的危害与不写没有区别：`>=` 让每次安装都可能拿到不同版本，
    「本地实测通过的确切组合」这句话就不再成立。
    """
    unpinned = [line for line in _dependency_lines() if not _PINNED.match(line)]
    assert not unpinned, (
        f"backend/requirements.txt 里这些行没有用 == 精确锁定：{unpinned}。本文件开头声明的锁定原则要求逐个写死版本号。"
    )
