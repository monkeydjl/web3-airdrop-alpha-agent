"""术语回退检查脚本的回归测试。

`scripts/check_terminology.py` 挂在 pre-commit 钩子上，是**唯一**防止
「评分决策引擎」术语回退的机械闸门（约定见 CLAUDE.md §1 / docs/GLOSSARY.md §2），
但此前**零测试覆盖**。2026-08-21 给它加了行级豁免机制后补上这组测试。

测试重点是**豁免机制不能被滥用**：豁免必须逐行显式，不能演变成整文件放行。
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = REPO_ROOT / "scripts"


def _load():
    path = SCRIPTS / "check_terminology.py"
    spec = importlib.util.spec_from_file_location("check_terminology_mod", path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules["check_terminology_mod"] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def checker():
    return _load()


def _write(tmp_path: Path, text: str, name: str = "sample.md") -> Path:
    p = tmp_path / name
    p.write_text(text, encoding="utf-8")
    return p


# 禁用术语在本文件里**只能拼接生成，不能写成字面量**。
# 否则这个测试文件自己就会被闸门拦下（实测：直接写字面量导致 12 处报错，
# 而且它是 tracked file，`--all` 与 pre-commit 都会扫到它）。
# 用 "分" 拆开是因为 FORBIDDEN 匹配的是完整词，拆点必须落在词内部。
BAD_CN = "评" + "分引擎"
BAD_BRAIN = "评" + "分大脑"
BAD_EN = "scoring" + " engine"
BAD_EN_TITLE = "Scoring" + " Engine"


# ── 拦截：禁用术语必须被抓到 ────────────────────────────────


@pytest.mark.parametrize(
    ("text", "expect_in_msg"),
    [
        (f"本节介绍{BAD_CN}的权重。\n", "评分决策引擎"),
        (f"所谓{BAD_BRAIN}就是这个。\n", "评分决策引擎"),
        (f"The {BAD_EN} computes weights.\n", "Scoring Decision Engine"),
        (f"大写也要抓 {BAD_EN_TITLE} 才对。\n", "Scoring Decision Engine"),
    ],
    # 必须显式给 id：默认 id 由参数文本派生，中文会被转义成 \uXXXX 塞进
    # tmp_path 目录名，路径超长导致 mkdir 报 WinError 3（实测踩过）。
    ids=["cn-scoring-engine", "cn-scoring-brain", "en-lowercase", "en-titlecase"],
)
def test_forbidden_terms_are_caught(checker, tmp_path, text, expect_in_msg):
    violations = checker.check_file(str(_write(tmp_path, text)))
    assert len(violations) == 1
    assert expect_in_msg in violations[0]


def test_reports_line_number(checker, tmp_path):
    path = _write(tmp_path, f"第一行没问题。\n第二行也好。\n第三行有{BAD_CN}。\n")
    violations = checker.check_file(str(path))
    assert len(violations) == 1
    assert ":3:" in violations[0]


def test_multiple_violations_on_one_line_all_reported(checker, tmp_path):
    """一行里同时出现多个禁用词，应逐个报出，不能只报第一个。"""
    path = _write(tmp_path, f"{BAD_CN}和{BAD_BRAIN}都不对。\n")
    violations = checker.check_file(str(path))
    assert len(violations) == 2


# ── 放行：正确写法不能被误伤 ────────────────────────────────


def test_correct_term_not_flagged(checker, tmp_path):
    """「评分决策引擎」含禁用子串吗？不含 —— 但必须实测确认，不能靠推理。"""
    path = _write(tmp_path, "评分决策引擎包含 LLM 增强与质量阈值。\n")
    assert checker.check_file(str(path)) == []


def test_rule_engine_is_legal_terminology(checker, tmp_path):
    """「规则引擎」是 ADR-001 定义的合法术语，不在禁用列表。"""
    path = _write(tmp_path, "LLM 关闭时走规则引擎，可离线演示。\n")
    assert checker.check_file(str(path)) == []


def test_opportunity_engine_is_legal(checker, tmp_path):
    path = _write(tmp_path, "旁路机会引擎是 v2.0 的影子评估，不参与决策。\n")
    assert checker.check_file(str(path)) == []


# ── 行级豁免：能用，但不能被滥用 ────────────────────────────


def test_allow_mark_exempts_that_line(checker, tmp_path):
    text = f"钩子会拦截「{BAD_CN}」等写法。<!-- {checker.ALLOW_MARK} -->\n"
    assert checker.check_file(str(_write(tmp_path, text))) == []


def test_allow_mark_only_exempts_its_own_line(checker, tmp_path):
    """豁免必须**只**作用于本行 —— 这是防滥用的核心断言。

    若哪天改成整文件豁免，这条会红。
    """
    text = f"第一行豁免了{BAD_CN}。<!-- {checker.ALLOW_MARK} -->\n第二行没有标记，写了{BAD_CN}，必须被拦。\n"
    violations = checker.check_file(str(_write(tmp_path, text)))
    assert len(violations) == 1
    assert ":2:" in violations[0]


def test_allow_mark_works_in_python_comment(checker, tmp_path):
    text = f'FORBIDDEN = ["{BAD_CN}"]  # {checker.ALLOW_MARK}\n'
    path = _write(tmp_path, text, name="sample.py")
    assert checker.check_file(str(path)) == []


# ── 扫描范围 ────────────────────────────────────────────────


@pytest.mark.parametrize("name", ["a.md", "a.py", "a.ts", "a.tsx", "a.json", "a.yml", "a.txt"])
def test_scanned_extensions(checker, name):
    assert checker.should_scan(name) is True


@pytest.mark.parametrize("name", ["a.png", "a.lock", "a.csv", "a.svg"])
def test_unscanned_extensions(checker, name):
    assert checker.should_scan(name) is False


def test_checker_script_itself_is_exempt(checker):
    """检查脚本自己定义了禁用模式，必须整文件豁免，否则永远自我报错。"""
    assert checker.should_scan("scripts/check_terminology.py") is False
    assert checker.should_scan("check_terminology.py") is False


# ── 全仓现状：闸门必须是绿的 ────────────────────────────────


def test_repo_wide_terminology_is_clean(checker):
    """把 `--all` 的结果固化成测试：全仓不得有未豁免的术语回退。

    等于让 CI 也守住这道闸门（此前只有 pre-commit 钩子守，绕过 `--no-verify`
    就失效了）。

    注意这里**不再**写 `if path.is_file(): ...` 跳过不存在的路径 —— 那个
    写法是 2026-09-02 那次门禁失效的直接成因：CI 的 cwd 是 `backend/`
    （ci.yml §31），旧 `iter_tracked_files()` 返回相对 cwd 的 `app/db.py`，
    拼成 `REPO_ROOT/app/db.py` 并不存在，于是**每个文件都被静默跳过**，
    这条测试扫了零个文件还一路绿灯。路径不存在是环境异常，必须报错而非跳过。
    """
    files = [f for f in checker.iter_tracked_files() if checker.should_scan(f)]
    assert files, "git ls-files 返回空，测试环境异常"
    violations: list[str] = []
    missing: list[str] = []
    for rel in files:
        path = REPO_ROOT / rel
        if not path.is_file():
            missing.append(rel)  # 可能是 symlink 或已删未提交，需人看一眼
            continue
        violations.extend(checker.check_file(str(path)))
    assert not missing, (
        f"{len(missing)} 个 tracked 路径在 REPO_ROOT 下不存在，"
        f"iter_tracked_files 的路径基准可能又退回相对 cwd：{missing[:5]}"
    )
    assert not violations, "发现术语回退：\n" + "\n".join(violations[:10])


# ── 扫描范围不得因 cwd 而缩水（2026-09-02 回归） ─────────────


def test_tracked_paths_are_repo_root_relative_regardless_of_cwd(checker, tmp_path, monkeypatch):
    """`iter_tracked_files()` 的路径基准必须是仓库根，与 cwd 无关。

    裸 `git ls-files` 返回相对 cwd 的路径且只列 cwd 子树。CI 在 `backend/`
    下跑 pytest，导致这道闸门实际只覆盖 backend 一个子树 —— `docs/` 的 69 个
    文档、根目录 CHANGELOG.md、frontend-next/ 合计 223 个待检文件从未被扫过，
    而术语约定主要就是给文档用的。修法是 `--full-name` + `cwd=REPO_ROOT`
    两个都加（缺一不可，理由见脚本 docstring）。
    """
    monkeypatch.chdir(REPO_ROOT / "backend")
    from_backend = checker.iter_tracked_files()
    monkeypatch.chdir(REPO_ROOT)
    from_root = checker.iter_tracked_files()

    assert from_backend == from_root, "换个 cwd 就返回不同清单，说明路径基准仍依赖 cwd"
    # backend/ 下的文件必须带前缀出现，否则就是又退回了子树相对路径
    assert "backend/app/db.py" in from_backend


def test_scan_covers_docs_and_repo_root_files(checker, monkeypatch):
    """闸门必须覆盖 backend/ 之外的目录 —— 尤其 docs/。

    这条是上一条的语义化补充：即便路径基准对了，若哪天有人给
    `iter_tracked_files` 加上 `backend/` 之类的路径参数来"提速"，
    覆盖面同样会缩水，而症状依旧是静默的（门禁绿，但什么都没守住）。
    """
    monkeypatch.chdir(REPO_ROOT / "backend")  # 刻意从子目录跑
    files = [f for f in checker.iter_tracked_files() if checker.should_scan(f)]

    assert any(f.startswith("docs/") for f in files), "docs/ 未被扫描"
    assert "CHANGELOG.md" in files, "仓库根的 CHANGELOG.md 未被扫描"
    assert any(f.startswith("frontend-next/") for f in files), "frontend-next/ 未被扫描"

    outside_backend = [f for f in files if not f.startswith("backend/")]
    # 实测 223 个；给足余量，只防"缩水到个位数"这种量级的回归
    assert len(outside_backend) > 150, f"backend/ 之外只扫到 {len(outside_backend)} 个文件，扫描范围疑似缩水"


def test_this_test_file_passes_the_gate(checker):
    """本测试文件自己必须过闸门。

    它含大量禁用术语样本，但全部**拼接生成**而非字面量 —— 否则它作为 tracked
    file 会被 `--all` 与 pre-commit 双双拦下（实测踩过：12 处报错）。
    这条断言把那个约束锁住，防止后人图省事改回字面量。
    """
    assert checker.check_file(__file__) == []


def test_exemption_marks_are_few_and_meaningful(checker):
    """审计豁免标记：每个**真正起作用**的豁免，其所在行必须确实含禁用术语。

    防的是"顺手贴个标记让检查闭嘴"。当前真豁免应当只有 2 处：
    CLAUDE.md 定义禁用词清单本身、SESSION_MEMORY_2026-07-26.md 引用历史
    commit message（改了就是篡改记录）。
    """
    real: list[str] = []
    for rel in checker.iter_tracked_files():
        if not checker.should_scan(rel):
            continue
        path = REPO_ROOT / rel
        if not path.is_file():
            continue
        for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if checker.ALLOW_MARK not in line:
                continue
            if any(p.search(line) for p, _ in checker.FORBIDDEN):
                real.append(f"{rel}:{lineno}")
    assert len(real) <= 3, f"豁免标记过多，请复核是否滥用：{real}"
