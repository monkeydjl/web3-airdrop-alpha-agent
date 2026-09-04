"""`.gitignore` 必须真的盖住所有装密钥的文件形态。

## 为什么需要这个测试

`.gitignore` 的漏洞是**沉默的**：漏掉一个形态不会报错、不会变红，
只会让那个文件安静地待在 `git add .` 的射程内，直到某次手滑把真实密钥
推上远程才被发现。而密钥泄露**不可撤销** —— 即使随后 force push 重写
历史，也必须假定已泄露并逐个轮换。

2026-09-03 实测：工作区里存在一个 `.env copy`（资源管理器「复制」的产物），
`git check-ignore` 返回 1，也就是**没有被忽略**。当时的三条规则

    .env
    .env.*
    .env.bak

一条都够不到它：`.env` 是精确匹配；`.env.*` 要求紧跟一个**点号**，而
`.env copy` 是空格加后缀；`.env.bak` 是另一个具体文件名。

这类文件名不是臆想出来的边界：
- Windows 资源管理器复制 → `.env copy`、`.env copy 2`
- macOS Finder 复制 → `.env copy`
- 编辑器/人手备份 → `.env_bak`、`.env-old`、`.env backup`

## 测什么

1. 各种真实会出现的 `.env` 变体都必须被忽略（用 `git check-ignore`
   问 git 本人，而不是自己解析 `.gitignore` 语法 —— 自己实现一遍
   glob 语义只会引入第二套判据）。
2. `.env.example` **必须仍然可见**且在版本控制内。它是部署者唯一的
   配置起点，被误忽略等于新部署者拿不到模板。
   这一条是反向约束：只断「变体被忽略」的话，一条 `.env*` 就能全过，
   却顺手把模板也埋了。
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]

# 与 `scripts/check_terminology.py` 同一口径：用 shutil.which 解析全路径，
# 不依赖 PATH 查找顺序（ruff S607）。找不到 git 就跳过整个模块 ——
# **不能静默当成通过**：这道闸门唯一的作用就是拦密钥，
# 「环境里没 git 所以算过」等于在最需要它的时候把它关掉。
GIT = shutil.which("git")
pytestmark = pytest.mark.skipif(GIT is None, reason="环境中找不到 git，无法查询忽略规则")


def _is_ignored(relative_path: str) -> bool:
    """问 git 这个路径会不会被忽略。

    刻意用 `git check-ignore` 而不是自己读 `.gitignore` 匹配：
    gitignore 的 glob 语义（`*` 不跨 `/`、`!` 取反的顺序、目录规则）
    有足够多的角落，自己实现一遍就等于维护第二套判据 —— 而两套判据
    不一致时，红的那个是测试，泄露的是真文件。

    文件不需要真实存在：`--no-index` 让 git 只按规则判断路径。
    """
    assert GIT is not None  # pytestmark 已保证，这里只是给类型收窄
    result = subprocess.run(
        [GIT, "check-ignore", "--no-index", "-q", "--", relative_path],
        cwd=REPO_ROOT,
        capture_output=True,
    )
    # rc=0 命中忽略规则，rc=1 未命中，rc>1 是真的出错了
    assert result.returncode in (0, 1), (
        f"git check-ignore 执行失败（rc={result.returncode}）：{result.stderr.decode('utf-8', 'replace')}"
    )
    return result.returncode == 0


@pytest.mark.parametrize(
    "name",
    [
        ".env",
        ".env.local",
        ".env.production",
        ".env.bak",
        # 资源管理器 / Finder「复制」的产物 —— 空格后缀，`.env.*` 够不到
        ".env copy",
        ".env copy 2",
        ".env backup",
        # 人手备份的常见写法
        ".env_bak",
        ".env-old",
    ],
)
def test_env_variants_are_ignored(name: str) -> None:
    """所有装真实密钥的 `.env` 变体都必须被忽略。

    失败意味着这个文件名现在**可以被 `git add .` 收进暂存区**。
    """
    assert _is_ignored(name), (
        f"`{name}` 没有被 .gitignore 覆盖 —— 它现在在 `git add .` 的射程内。"
        "密钥一旦推上远程就必须按已泄露处理并全部轮换，"
        "补规则的成本远低于轮换。"
    )


def test_env_example_stays_visible() -> None:
    """`.env.example` 必须**不**被忽略，且确实在版本控制内。

    反向约束：光断「变体被忽略」的话，一条粗暴的 `.env*` 就能让上面
    全部通过，同时把唯一的配置模板一起埋掉 —— 新部署者会拿不到模板，
    而这个失败要等到有人从零 clone 才暴露。
    """
    assert not _is_ignored(".env.example"), (
        ".env.example 被 .gitignore 忽略了 —— 它是部署者唯一的配置起点，"
        "必须留在版本控制内（检查是否有规则盖过了 `!.env.example`）。"
    )
    assert GIT is not None
    tracked = subprocess.run(
        [GIT, "ls-files", "--error-unmatch", ".env.example"],
        cwd=REPO_ROOT,
        capture_output=True,
    )
    assert tracked.returncode == 0, ".env.example 不在版本控制内"


def test_secret_material_patterns_are_ignored() -> None:
    """私钥、证书这类文件也必须被盖住。

    与 `.env` 同一个理由，只是形态不同：这些文件通常是运维在服务器上
    生成后拷回本地排查时带进工作区的。
    """
    for name in ("server.pem", "id_rsa.key", "token.secret"):
        assert _is_ignored(name), f"`{name}` 未被忽略 —— 密钥材料可能被提交"
