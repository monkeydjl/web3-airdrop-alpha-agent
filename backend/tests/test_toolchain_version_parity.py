"""工具链版本口径一致性 —— 「支持哪个 Python」必须只有一个答案。

## 这个文件在防什么

版本号散落在 5 处：`requires-python`（两份 pyproject）、ruff 的
`target-version`、mypy 的 `python_version`、CI 的 `PYTHON_VERSION`、
Dockerfile 的基础镜像。它们不一致时**没有任何东西会报错** ——
所有检查照常绿，直到某个环境上抛运行时异常。

## 2026-08-24 实测出来的判据（不是推的）

原来 `backend/pyproject.toml` 的 mypy 写 `python_version = "3.12"`，
而两份 `requires-python` 都写 `>=3.11`。用 `itertools.batched`
（3.12 新增的标准库 API）做探针，四道门的反应：

| 门 | 结果 |
|---|---|
| `mypy --python-version 3.11` | `error: Module has no attribute "batched"` ✅ |
| `mypy --python-version 3.12` | `Success: no issues found` ❌ |
| `ruff --target-version py311` | `All checks passed` ❌ |
| 真 3.11.9 解释器 | `AttributeError: module 'itertools' has no attribute 'batched'` |

结论有两条，方向相反，两条都重要：

1. **ruff 的 `target-version` 拦得住 3.12 专属语法**（实测能拦 PEP 695
   的 `type X = int` 与 `def f[T]()`），所以它不是无用的。
2. **但它拦不住标准库 API 的版本差** —— 那只有类型检查器管。

所以 mypy 配 3.12 的后果是：`requires-python = ">=3.11"` 这句承诺
**一道门都没有**。而失效方式是运行时 AttributeError，
报错信息完全不提 Python 版本 —— 又一个"不指向真实原因"的错误。

## 为什么钉「下限」而不是「统一成同一个数」

直觉会说"三处都写 3.12 就一致了"。那是错的：
声明 `>=3.11` 的项目必须**按 3.11 检查**，否则声明就是空话。
在 3.12 上跑 3.11 的检查完全安全（多拦），反之才危险（少拦）。

真要只支持 3.12，该改的是 `requires-python`，
而不是把检查器放宽到跟运行时镜像一样。
"""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
ROOT_PYPROJECT = REPO_ROOT / "pyproject.toml"
BACKEND_PYPROJECT = REPO_ROOT / "backend" / "pyproject.toml"
CI_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "ci.yml"
DOCKERFILE = REPO_ROOT / "docker" / "Dockerfile"


def _toml(path: Path) -> dict:
    data = tomllib.loads(path.read_text(encoding="utf-8"))
    assert data, f"{path.name} 解析成空字典 —— 解析器失效，先修这里再看断言。"
    return data


def _minimum_supported() -> tuple[int, int]:
    """`requires-python` 声明的下限，形如 (3, 11)。"""
    spec = _toml(ROOT_PYPROJECT)["project"]["requires-python"]
    m = re.fullmatch(r">=\s*(\d+)\.(\d+)", spec.strip())
    assert m, (
        f"根 pyproject 的 requires-python 是 {spec!r}，本文件只认 `>=X.Y` 这一种形状。\n"
        "改成了区间或复合约束的话，先更新这里的解析，别让门禁静默失效。"
    )
    return int(m.group(1)), int(m.group(2))


class TestDeclaredSupportFloor:
    """两份 pyproject 的 requires-python 必须一致 —— 否则"支持哪个版本"没有答案。"""

    def test_both_pyprojects_declare_the_same_floor(self):
        root = _toml(ROOT_PYPROJECT)["project"]["requires-python"]
        backend = _toml(BACKEND_PYPROJECT)["project"]["requires-python"]
        assert root == backend, (
            f"根 pyproject 写 {root!r}，backend/pyproject.toml 写 {backend!r}。\n"
            "两份都会被安装工具读到，不一致时哪份生效取决于从哪个目录构建 —— 没有答案。"
        )

    def test_versions_also_match(self):
        root = _toml(ROOT_PYPROJECT)["project"]["version"]
        backend = _toml(BACKEND_PYPROJECT)["project"]["version"]
        assert root == backend, f"版本号不一致：根 {root!r} vs backend {backend!r}"


class TestTypeCheckerGuardsTheFloor:
    """mypy 的 python_version 必须等于声明下限，不是运行时镜像的版本。

    这是本文件最重要的一条 —— 它守的是 `requires-python` 那句承诺本身。

    2026-08-30 起根 pyproject 的 `[tool.mypy]` 已作为死配置删除（CI 只读
    backend 的那份），所以权威口径只剩 `backend/pyproject.toml` 一处。
    """

    def test_root_pyproject_no_longer_carries_dead_mypy_config(self):
        """根 pyproject 的 [tool.mypy] 已删 —— 别让人悄悄把它加回来造成口径漂移。"""
        config = _toml(ROOT_PYPROJECT).get("tool", {}).get("mypy", {})
        assert not config, (
            "根 pyproject.toml 又出现了 [tool.mypy] —— 它曾是死配置（CI 不读它）。\n"
            "mypy 的权威口径只在 backend/pyproject.toml，别在根目录重建第二份。"
        )

    def test_mypy_python_version_equals_declared_floor(self):
        major, minor = _minimum_supported()
        expected = f"{major}.{minor}"

        config = _toml(BACKEND_PYPROJECT).get("tool", {}).get("mypy", {})
        assert config, f"{BACKEND_PYPROJECT.name} 里没有 [tool.mypy] —— 解析锚点可能变了。"
        actual = config.get("python_version")
        assert actual == expected, (
            f"{BACKEND_PYPROJECT.name} 的 mypy python_version 是 {actual!r}，声明下限是 {expected!r}。\n"
            "\n"
            "配高了的实际后果（2026-08-24 实测）：用了 3.12 新标准库 API 的代码\n"
            "会通过全部 CI，然后在 3.11 环境上抛 AttributeError —— 而 ruff 的\n"
            "target-version 只拦语法、拦不住标准库差异，所以那时一道门都没有。\n"
            "\n"
            "真要只支持新版本，请改 requires-python，别放宽检查器。"
        )

    def test_ruff_target_version_equals_declared_floor(self):
        """ruff 的 target-version 同样按下限。

        它拦不住标准库 API 差异（实测），但**拦得住 3.12 专属语法**
        （PEP 695 的 `type X = int` / `def f[T]()`），所以它是第二道有效的门。
        """
        major, minor = _minimum_supported()
        expected = f"py{major}{minor}"

        actual = _toml(ROOT_PYPROJECT)["tool"]["ruff"]["target-version"]
        assert actual == expected, (
            f"ruff target-version 是 {actual!r}，声明下限对应 {expected!r}。\n"
            "配高了会放过 3.12 专属语法，而那种代码在 3.11 上连编译都过不了。"
        )


class TestRuntimeVersionIsAtLeastTheFloor:
    """CI 与镜像可以比下限**新**，但不能比下限**旧**。

    这个方向是刻意不对称的：跑在更新的解释器上是安全的（3.11 的代码在
    3.12 上能跑），跑在更旧的解释器上才会炸。所以这里断言的是 `>=`，
    不是相等 —— 强行要求相等会逼着人在升级镜像时改一堆无关配置。
    """

    def test_ci_python_version_is_not_below_the_floor(self):
        text = CI_WORKFLOW.read_text(encoding="utf-8")
        m = re.search(r'PYTHON_VERSION:\s*"(\d+)\.(\d+)"', text)
        assert m, "ci.yml 里解析不到 PYTHON_VERSION —— 写法可能变了，先修锚点。"
        ci = (int(m.group(1)), int(m.group(2)))
        assert ci >= _minimum_supported(), (
            f"CI 用 Python {ci[0]}.{ci[1]}，低于声明下限 {_minimum_supported()} —— CI 根本没在测你声明支持的版本。"
        )

    def test_docker_base_image_is_not_below_the_floor(self):
        text = DOCKERFILE.read_text(encoding="utf-8")
        versions = {(int(a), int(b)) for a, b in re.findall(r"FROM python:(\d+)\.(\d+)", text)}
        assert versions, "Dockerfile 里解析不到 `FROM python:X.Y` —— 基础镜像写法可能变了。"
        floor = _minimum_supported()
        too_old = sorted(v for v in versions if v < floor)
        assert not too_old, f"Dockerfile 基础镜像 {too_old} 低于声明下限 {floor}"

    def test_dockerfile_stages_agree_on_one_version(self):
        """多阶段构建的各阶段必须同一个 Python 版本。

        builder 与 production 不同版本时，虚拟环境里的
        `site-packages` 路径会对不上（`python3.12` vs `python3.11`），
        而这个错误发生在**容器启动时**，不是构建时 —— 构建全绿。
        """
        text = DOCKERFILE.read_text(encoding="utf-8")
        versions = {f"{a}.{b}" for a, b in re.findall(r"FROM python:(\d+)\.(\d+)", text)}
        expected_distinct = 1
        assert len(versions) == expected_distinct, (
            f"Dockerfile 各阶段的 Python 版本不一致：{sorted(versions)}。\n"
            "site-packages 路径写死在 python3.X 目录里，不一致会在容器启动时才炸。"
        )
