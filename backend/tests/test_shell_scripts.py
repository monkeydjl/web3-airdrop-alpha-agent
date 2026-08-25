"""部署脚本的门禁：不能再出现"跑成功了但什么都没做"的形态。

`scripts/deploy.sh` / `health-check.sh` / `backup.sh` 在 2026-08-24 之前
各带一个**不会报错**的缺陷：

| 脚本 | 缺陷 | 表现 |
|---|---|---|
| `deploy.sh` | 健康检查打 8000（真实 8002）、5 行 `s/X/X/` 空操作 sed、生产用空 API_KEY 直接启动 | 报「服务启动超时」，而真因是探测地址错 / 配置缺失 |
| `health-check.sh` | 默认 `API_URL` 是 8000、硬查 `data/app.db` | 健康的系统被持续报成不健康 |
| `backup.sh` | 本地回退 `cp data/airdrop.db`（一个 94 项目的过期副本，真库 288 项目） | **报告"备份完成"，产出一份没用的备份** |

三个的共同点：**都不是功能缺失，而是把真实原因掩盖成另一个原因。**
这类缺陷最贵的地方不是它失败，而是它指错方向。

## 为什么用 `bash -n` 而不是自己数关键字

CI 跑在 Linux 上，`bash -n` 是**真正的解析器**。
本地 Windows 上 bash 不可用（Git bash `CreateFileMapping` Win32 error 5，
WSL `E_ACCESSDENIED`），所以那部分自动跳过。

写这套检查的过程里，我自己手写的 `if`/`fi` 计数器**错了两次**，
两次都报出「backup.sh 不配平」这个不存在的问题（一次是正则吃掉了分隔符，
一次是多减了 `elif`）。**解析器出错时的表现，和被测对象真有问题
长得一模一样** —— 所以能用真解析器的时候就别自己写一个。
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ("scripts/deploy.sh", "scripts/health-check.sh", "scripts/backup.sh")

# 真实端口。写死一个常量而不是 import settings：这些脚本是给
# 还没起服务的机器用的，判据应该是"文件里写的值"，不是"当前进程的配置"。
REAL_PORT = "8002"


def _text(rel: str) -> str:
    path = REPO_ROOT / rel
    assert path.is_file(), f"{rel} 不存在 —— 被测对象没了。"
    text = path.read_text(encoding="utf-8")
    assert len(text) > 500, f"{rel} 只有 {len(text)} 字符，疑似被截断 —— 解析器已失效。"
    return text


def _code_lines(rel: str) -> list[str]:
    """只保留非注释行。

    注释里会**故意**引用旧的错误写法（修复记录），不先剔掉的话门禁会把
    「记录了这个坑」当成「还有这个坑」。这个错误今天在文档门禁上踩过两次。
    """
    return [ln for ln in _text(rel).splitlines() if not ln.strip().startswith("#")]


class TestScriptsParse:
    """能用真解析器就用真解析器。"""

    @pytest.mark.parametrize("rel", SCRIPTS)
    @pytest.mark.skipif(shutil.which("bash") is None or os.name == "nt", reason="本机无可用 bash")
    def test_bash_syntax_is_valid(self, rel: str) -> None:
        bash = shutil.which("bash")
        assert bash, "skipif 应该已经跳过了这一条"
        proc = subprocess.run(
            [bash, "-n", str(REPO_ROOT / rel)],
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
        assert proc.returncode == 0, f"{rel} 语法错误：\n{proc.stderr}"

    @pytest.mark.parametrize("rel", SCRIPTS)
    def test_no_crlf_and_no_bom(self, rel: str) -> None:
        """CRLF 会让 shebang 变成 `/bin/bash\\r`，BOM 会被当成命令的一部分。

        两者都在**执行时**才失败，且报错信息（`bad interpreter` /
        `command not found`）完全不提编码。今天上午刚在 PowerShell 侧
        踩过同一类问题的镜像版本（缺 BOM 导致按 GBK 解码）。
        """
        raw = (REPO_ROOT / rel).read_bytes()
        assert b"\r\n" not in raw, f"{rel} 含 CRLF —— shebang 会带上 \\r 导致 exec 失败。"
        assert not raw.startswith(b"\xef\xbb\xbf"), f"{rel} 带 UTF-8 BOM —— sh 会把它当命令的一部分。"
        assert raw.startswith(b"#!/bin/bash"), f"{rel} 的 shebang 不是 #!/bin/bash。"


class TestNoSilentNoOps:
    """空操作是这三个脚本最典型的失效形态。"""

    def test_no_identity_sed(self) -> None:
        """`sed 's/X/X/'` 把 X 换成 X，永远 exit 0，永远什么也不改。

        原 `deploy.sh` 有 **5 行**这种 sed，一个都没生效，也一个都没报错。
        """
        offenders: list[str] = []
        for rel in SCRIPTS:
            for ln in _code_lines(rel):
                for m in re.finditer(r"s/([^/]+)/([^/]+)/", ln):
                    if m.group(1) == m.group(2):
                        offenders.append(f"{rel}: {m.group(0)}")
        assert not offenders, f"仍有把 X 替换成 X 的空操作 sed：{offenders}"

    def test_backup_does_not_hardcode_the_stale_copy(self) -> None:
        """`data/airdrop.db` 在这台机器上是过期副本，不能硬编码去备份它。

        备份的失败方式里最坏的一种，就是它看起来成功了。
        """
        code = "\n".join(_code_lines("scripts/backup.sh"))
        assert 'cp "data/airdrop.db"' not in code, "backup.sh 仍在硬编码 cp data/airdrop.db（过期副本）。"
        assert "DB_PATH=" in code, "backup.sh 没有从 .env 读 DB_PATH —— 又会去猜文件名。"

    def test_backup_fails_when_no_database_found(self) -> None:
        """找不到库必须 exit 1，不能"跳过并报成功"。

        原脚本是 `echo "⚠️ 跳过数据库备份"` 然后继续走到「✅ 备份成功！」，
        最后打包出一个只含 `backup-info.txt` 的压缩包。
        """
        code = "\n".join(_code_lines("scripts/backup.sh"))
        marker = "sqlite-local"
        assert marker in code, "backup.sh 的本地回退分支不见了 —— 解析器已失效。"
        tail = code[code.index(marker) :]
        assert "exit 1" in tail, "backup.sh 在找不到数据库时没有失败退出。"


class TestRealPortIsUsed:
    """端口写错的代价：把"探测地址错了"报成"服务起不来"。"""

    @pytest.mark.parametrize("rel", SCRIPTS)
    def test_no_executable_port_8000(self, rel: str) -> None:
        stray = [ln.strip() for ln in _code_lines(rel) if re.search(r"(?:localhost|127\.0\.0\.1):8000\b", ln)]
        assert not stray, f"{rel} 非注释行仍有 :8000（真实端口 {REAL_PORT}）：{stray[:3]}"

    def test_health_check_defaults_to_the_real_port(self) -> None:
        text = _text("scripts/health-check.sh")
        assert f"API_URL:-http://localhost:{REAL_PORT}" in text, (
            f"health-check.sh 的默认 API_URL 不是 {REAL_PORT}。这个脚本是给监控告警用的 —— "
            "默认值错了的后果是一个健康的系统被持续报成不健康。"
        )

    def test_deploy_does_not_hardcode_a_port(self) -> None:
        text = _text("scripts/deploy.sh")
        assert f"DEFAULT_PORT={REAL_PORT}" in text, "deploy.sh 没有一个正确的默认端口。"
        assert "grep -E '^PORT='" in text, "deploy.sh 没有从 .env 读真实端口 —— 硬编码就是上次出错的原因。"


class TestProductionPreflight:
    """生产路径必须在启动前停下，而不是等超时。

    从 `.env.example` 复制出的 `.env` 里 `API_KEY` / `AUTH_TOKEN_SECRET` 都是空的，
    `CORS_ORIGINS` 是 localhost —— 三项都会让 `app/config.py` **拒绝启动**。
    原脚本会打印「✅ .env 文件已创建」，然后容器 CrashLoop，
    60 秒后报「服务启动超时」。
    """

    _REQUIRED = ("APP_ENV", "API_KEY", "AUTH_TOKEN_SECRET", "CORS_ORIGINS")

    @pytest.mark.parametrize("key", _REQUIRED)
    def test_deploy_checks_the_keys_that_block_startup(self, key: str) -> None:
        text = _text("scripts/deploy.sh")
        assert key in text, f"deploy.sh 的生产预检没有涉及 {key} —— 它配错会让容器直接退出。"

    def test_deploy_exits_before_starting_containers(self) -> None:
        """预检必须在 `up -d` **之前**。

        判据落在位置上而不是"有没有这段代码"：一段写在启动之后的预检
        等于没有预检，而它照样能让"包含 API_KEY 检查"这类断言通过。

        判据用的是**代码里的实际控制流**（`PRECHECK_FAILED` 的赋值与
        `exit 1`），不是段落标题 —— 第一版拿中文标题「生产配置预检」当锚点，
        结果只要改个标题这条就静默跳过了（变异实测漏掉）。
        **锚点选在能被无痛改掉的字符串上，等于没有锚点。**
        """
        code_lines = _code_lines("scripts/deploy.sh")
        code = "\n".join(code_lines)

        # 三样都要有，缺一个这段预检就是坏的：
        #   初始化（缺了 `[ "$PRECHECK_FAILED" -eq 1 ]` 会在未定义变量上比较）
        #   至少一处置位
        #   收尾的 exit
        # 只断言"出现过 PRECHECK_FAILED"是不够的 —— 变异实测：把初始化行删掉、
        # 只留下置位行，那条断言照样绿，而脚本已经坏了。
        assert "PRECHECK_FAILED=0" in code, "deploy.sh 的预检变量没有初始化 —— 未定义变量参与数值比较，预检形同虚设。"
        assert "PRECHECK_FAILED=1" in code, "deploy.sh 的预检从不置位 —— 检查出问题也不会被记下来。"

        first_check = code.index("PRECHECK_FAILED=0")
        up_at = code.index("up -d")
        assert first_check < up_at, (
            f"生产预检出现在 `up -d` 之后（预检 @{first_check} vs 启动 @{up_at}）—— 等于没有预检。"
        )

        # 预检失败必须真的退出，而不只是打印
        preflight = code[first_check:up_at]
        assert "exit 1" in preflight, "预检发现问题后没有 exit 1 —— 打印一句警告然后照样启动，等于没有预检。"
        assert 'PRECHECK_FAILED" -eq 1' in preflight, "预检结果从没被读取 —— 置位了但没人看，和不检查一样。"

    def test_deploy_does_not_invent_secret_values(self) -> None:
        """脚本不能自动生成密钥。

        密钥和域名的正确值只有部署者知道；自动塞一个值进去，
        会让一个配错的生产环境**看起来部署成功了**。
        这条与 `config.py` 里"强制修正 vs 拒绝启动"的判据一致：
        能推断出唯一正确值的（种子开关）强制改，推断不出的（密钥）拒绝启动。
        """
        code = "\n".join(_code_lines("scripts/deploy.sh"))
        # 只禁"生成后写回 .env"，不禁在提示里告诉用户怎么生成
        offenders = [
            ln.strip() for ln in code.splitlines() if "token_urlsafe" in ln and (">>" in ln or ">" in ln or "sed" in ln)
        ]
        assert not offenders, f"deploy.sh 在自动生成并写入密钥：{offenders}"


class TestComposeInvocationIsConsistent:
    def test_deploy_uses_one_compose_command_everywhere(self) -> None:
        """原脚本检测了 `docker compose` 和 `docker-compose` 两种，
        但后面**只调 `docker-compose`** —— 在只装了 v2 的机器上
        检测能过、执行会 command not found。
        """
        text = _text("scripts/deploy.sh")
        assert "COMPOSE=" in text, "deploy.sh 没有把 compose 调用方式统一到一个变量。"
        offenders = [
            ln.strip()
            for ln in _code_lines("scripts/deploy.sh")
            if "docker-compose" in ln and "command -v" not in ln and 'COMPOSE="docker-compose"' not in ln
        ]
        assert not offenders, f"deploy.sh 仍直接调用 docker-compose：{offenders}"


class TestHealthCheckCoversTheBudgetLedger:
    """账本读不出来时，LLM 会被 fail-closed 拦住 —— 值班要能一眼看到。

    判据是 `ledger_error` 而不是花费数字：**一个坏掉的账本和一个还没花钱的
    账本，在数字上都是 0。**
    """

    def test_health_check_looks_at_ledger_error(self) -> None:
        """判据必须落在**代码行**上，不能是"文件里提到过这个词"。

        第一版写的是 `assert "ledger_error" in _text(...)`，而这个文件的注释里
        本来就解释了为什么要看 `ledger_error` —— 于是把代码里的检查全删掉、
        只留注释，这条断言照样绿。**注释提到 ≠ 代码在做。**
        这是今天第三次栽在"词出现过就算实现了"这个判据上。
        """
        code = "\n".join(_code_lines("scripts/health-check.sh"))
        assert "ledger_error" in code, "health-check.sh 的**代码**里没有检查预算账本状态（只在注释里提到不算）。"
        # 还要求它区分"读到了 null"和"读到了错误字符串"两个分支 ——
        # 只 grep 一个 `ledger_error` 字样，改成 grep `"ok":true` 也能过（变异实测）。
        assert '"ledger_error":null' in code, "health-check.sh 没有判断账本可读（`ledger_error` 为 null）的分支。"
        assert '"ledger_error":"' in code, "health-check.sh 没有判断账本报错（`ledger_error` 有值）的分支。"

    def test_health_check_does_not_judge_by_the_spend_number(self) -> None:
        """反向断言：不能用"花费是否为 0"当判据。"""
        code = "\n".join(_code_lines("scripts/health-check.sh"))
        assert 'spend_today_usd":0' not in code, (
            "health-check.sh 在用花费是否为 0 做判断 —— 坏掉的账本和没花钱的账本都是 0，分不开。"
        )
