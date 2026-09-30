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

## 2026-09-30：库文件探测逻辑的回归钉

backup.sh / health-check.sh 的本地分支都靠「读 `.env` 的 DB_PATH」
定位真正的库。解析管道 `grep ^DB_PATH= | tail -1 | cut -d= -f2- |
tr -d space` 每个环节都有语义（`tail -1` = 多行取最后一条；`f2-`
= 值里可以带 `=`），任何一个环节被"顺手改短"，脚本都会安静地去
错文件——2026-08-24 那次事故（备份了 94 项目的过期副本还报成功）
就是这么来的。两层钉子：

- **静态钉**（全平台）：解析管道、候选顺序（`$DB_PATH_ENV` 必须排
  在具名回退候选之前）、相对路径 `backend/` 回退分支、回退候选
  警告的触发条件，全部钉在**非注释代码行**上；backup.sh 禁止重新
  长出猜文件名的候选清单（"不猜其它文件名"契约）。
- **行为钉**（CI Linux，本机 Windows skip）：tmp 沙箱里真跑脚本，
  假 `docker` / 假 `curl` 定住容器分支，断言 exit code、备份产物、
  「源: …」行与回退警告。期望值已在 Git Bash 沙箱人工预演锁定
  （含一个坑：Windows Store 的 `python3` 存根退出码 49，曾被误认
  为脚本缺陷——那不是）。
- **deploy.sh 预检的行为钉**（`TestDeployPreflightBehavior`，同日）：
  静态 `TestProductionPreflight` 只能证明"检查代码存在且位置对"，
  证明不了"配错的 .env 真的会被拦下"。沙箱里**复制脚本进去跑**
  （`PROJECT_ROOT` 取自脚本自身位置，不复制则读写的是真实仓库的
  `.env`），假 docker 记录每次调用、假 curl/假 sleep 让预检通过后
  的全流程瞬时完成。八场景锁死：无 .env 先创建模板再停下、模板值
  四项全挂、短 API_KEY 单项挂、CORS 的 127.0.0.1 别名分支、有效配
  置全流程（真实 compose 动作此时才出现）、dev 路径不预检、dev 存
  量 .env 跳过预检、未知环境参数；每个失败场景都断言 compose 零
  真实动作（down/build/up）——"预检失败还启动"在动态层也不放过。
- **Windows 脚本的行为钉**（`TestStopBatBehavior` /
  `TestAutoBackupBehavior`，与 bash 钉互为镜像：nt 才跑，CI Linux
  skip）：auto_backup.ps1 经 `-ProjectRoot` 天然沙箱化，假 docker
  （.cmd shim）+ 故障注入旗标钉住容器离线 / custom / SQL 失败 / 成功
  四条退出路径与工作目录清理契约；Stop.bat 的 taskkill **故意不
  shim**（for 体内裸调 .cmd 会移交控制权终止循环——harness 保真 exe
  语义，假 PID 取非 4 倍数保证不存在），断言脚本回显的 kill 目标。
  **两个真实缺陷是行为钉预演时挖出来的**：Stop.bat 带 BOM
  （`@echo off` 失效、全脚本回显执行）+ `chcp 65001` 与 UTF-8 中文
  注释叠加让 cmd 解析器字节错位（把注释当命令执行），脚本在第一个
  taskkill 后静默中断——前端循环从未运行过。已修复：纯 ASCII 重写
  （与 auto_backup.ps1 相反，PS 5.1 必须 BOM、批处理必须禁 BOM，
  见 `test_stop_bat_has_no_bom`）。
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import ClassVar

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


class TestWindowsBatchScripts:
    """Start/Stop.bat 的门禁 —— Stop.bat 的后端停止步骤曾长期空转。

    `tasklist | findstr "uvicorn"` 永远匹配不到任何进程：uvicorn 跑在
    python.exe 里，"uvicorn" 只是命令行参数，tasklist 的映像名列看不到它。
    后果是「重启后端」实际变成「再起一个实例绑同一个端口」，流量仍进旧
    进程 —— 2026-09-06 排查「缓存明明写完却不生效」时实测：8002 上同时
    挂着两个 LISTENING PID，接客的是改动**前**启动的那个。
    """

    def test_stop_bat_kills_backend_by_port(self) -> None:
        text = _text("Stop.bat")
        assert re.search(r'findstr ":8002"', text), (
            "Stop.bat 必须按端口 8002 定位后端进程 —— tasklist 的映像名是 "
            'python.exe，按 "uvicorn" 找永远匹配不到，等于从不停止后端。'
        )
        port_line = next(line for line in text.splitlines() if '":8002"' in line)
        assert "LISTENING" in port_line, "按端口定位后必须过滤 LISTENING 行，别把 established 连接的 PID 也杀了。"
        assert not re.search(r'findstr\s+/i\s+"uvicorn"', text), (
            '按映像名 findstr "uvicorn" 的空转写法不要回归 —— 它看起来在做事，实际什么都没停。'
        )

    def test_stop_bat_has_no_bom(self) -> None:
        """批处理禁带 BOM：BOM 会毒化第一行（`@echo off` 失效，全脚本回显执行）。

        2026-09-30 行为钉预演时实锤：Stop.bat 一直带着 BOM，cmd 不识别
        `\ufeff@echo off`，脚本以回显模式逐行执行——能跑，但 for 循环行为
        变了。注意与 auto_backup.ps1 相反：PS 5.1 无 BOM 会按 GBK 解码，
        那边是**必须**带 BOM；批处理是**必须不带**。
        """
        raw = (REPO_ROOT / "Stop.bat").read_bytes()
        assert not raw.startswith(b"\xef\xbb\xbf"), (
            "Stop.bat 带 UTF-8 BOM —— cmd 会把 `\ufeff@echo off` 当陌生命令，@echo off 失效、全脚本回显执行。"
        )

    def test_stop_bat_does_not_kill_established_connections(self) -> None:
        """杀 :3002 前必须过滤 LISTENING —— 否则会把持有 established 连接的
        进程（典型：用户自己的浏览器）一起 taskkill 掉。"""
        text = _text("Stop.bat")
        for line in text.splitlines():
            if '":3002"' in line:
                assert "LISTENING" in line, f"杀 :3002 前必须过滤 LISTENING 行。该行：{line.strip()}"


# ── Windows 脚本的行为钉（os.name == "nt" 才跑，与 bash 钉互为镜像）──────
# 假 netstat 固定输出四个 PID：1111/3333 是 LISTENING（后端/前端），
# 4444/2222 是 ESTABLISHED（对端是用户浏览器）。findstr 是真的，
# 由它完成 :8002/:3002 与 LISTENING 两道过滤——钉的就是这个管道的结果。
_FAKE_NETSTAT = (
    "@echo off\r\n"
    "echo TCP    0.0.0.0:8002    0.0.0.0:0    LISTENING    1111\r\n"
    "echo TCP    127.0.0.1:8002    1.2.3.4:6666    ESTABLISHED    2222\r\n"
    "echo TCP    0.0.0.0:3002    0.0.0.0:0    LISTENING    3333\r\n"
    "echo TCP    127.0.0.1:3002    1.2.3.4:55555    ESTABLISHED    5555\r\n"
    "exit /b 0\r\n"
)
# 假 docker：ps/cp/exec 分派，故障注入走环境变量（OFFLINE / FAIL_CUSTOM /
# FAIL_SQL），cp 落一个真文件让 Compress-Archive 走真实路径。
_FAKE_DOCKER_PS1 = (
    "@echo off\r\n"
    'if "%OFFLINE%"=="1" goto fail_offline\r\n'
    'if "%~1"=="ps" goto do_ps\r\n'
    'if "%~1"=="cp" goto do_cp\r\n'
    'echo %* | findstr /C:"-F c" >nul\r\n'
    "if not errorlevel 1 goto do_custom\r\n"
    'echo %* | findstr /C:"pg_dump" >nul\r\n'
    "if not errorlevel 1 goto do_sql\r\n"
    "exit /b 0\r\n"
    ":do_ps\r\n"
    "echo airdrop-db\r\n"
    "exit /b 0\r\n"
    ":do_cp\r\n"
    'echo dump > "%~3"\r\n'
    "exit /b 0\r\n"
    ":do_custom\r\n"
    'if "%FAIL_CUSTOM%"=="1" exit /b 1\r\n'
    "exit /b 0\r\n"
    ":do_sql\r\n"
    'if "%FAIL_SQL%"=="1" exit /b 1\r\n'
    "exit /b 0\r\n"
    ":fail_offline\r\n"
    "exit /b 1\r\n"
)


def _windows_env(bin_dir: str, **flags: str) -> dict[str, str]:
    """子进程 env：shim 目录插到 PATH 最前（压过 System32 的真命令）+ 故障注入旗标。"""
    env = {
        **os.environ,
        "PATH": bin_dir + os.pathsep + os.environ.get("PATH", ""),
        "PYTHONUTF8": "1",
    }
    env.update(flags)
    return env


@pytest.mark.skipif(os.name != "nt", reason="Windows 行为钉只在 nt 上跑（CI Linux 跳过，与 bash 钉互为镜像）")
class TestStopBatBehavior:
    """沙箱真跑 Stop.bat，断言两道 findstr 过滤管道只放行 LISTENING 的 PID。

    taskkill **故意不做 shim**。实测（2026-09-30，矩阵六组变体）：for 体内
    裸调一个 .cmd 会把控制权整体移交给它，调用者的 for 循环就地终止
    （与 shim 以 exit /b、goto :eof 还是自然结束收尾无关；加 call 才
    能返回——但被测脚本不能为迁就 harness 插 call，生产里 taskkill 是
    真 .exe 本无此问题）。所以 harness 必须保真 exe 语义：不拦截
    taskkill，让它打在**不可能存在的 PID** 上（Windows PID 恒为 4 的
    倍数，假数据全取非 4 倍数），输出被脚本自己的 `>nul 2>&1` 吞掉。
    断言证据用脚本自己的回显行 `[INFO] Stopping … %%a`——它就是循环
    传给 taskkill 的目标。pause 是 cmd 内建命令无法 shim，用
    stdin=DEVNULL 喂 EOF 直接返回。

    netstat 必须 shim 且**跑之前先做接管预检**（沙箱 PATH 直接调一次
    netstat 确认输出是假数据）：没有这层防护，shim 一旦失效，循环看到
    的就是真 netstat 的端口表——那才是真危险。shim 文件必须带 .cmd
    扩展名（cmd 按 PATHEXT 解析，无扩展名直接落空、跑到 System32
    真命令——预演时真发生过，预检当场拦住）。
    """

    _LISTENING: ClassVar[set[str]] = {"1111", "3333"}
    _ESTABLISHED: ClassVar[set[str]] = {"2222", "5555"}

    def _preflight(self, bin_dir: str) -> None:
        cmd = shutil.which("cmd")
        assert cmd, "nt 上 cmd.exe 一定存在"
        probe = subprocess.run(
            [cmd, "/c", "netstat", "-ano"],
            env=_windows_env(bin_dir),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=30,
            check=False,
        )
        assert self._LISTENING.issubset(set(re.findall(r"\b(\d{4})\b", probe.stdout))), (
            f"netstat shim 未接管（PATH 解析失效）——拒跑 Stop.bat。\n{probe.stdout[:300]}"
        )

    def test_kills_only_listening_pids_on_both_ports(self, tmp_path: Path) -> None:
        bin_dir = _write_shims(tmp_path, {"netstat.cmd": _FAKE_NETSTAT}, newline="\r\n")
        self._preflight(bin_dir)
        cmd = shutil.which("cmd")
        assert cmd
        proc = subprocess.run(
            [cmd, "/c", str(REPO_ROOT / "Stop.bat")],
            cwd=tmp_path,
            env=_windows_env(bin_dir),
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=60,
            check=False,
        )
        assert proc.returncode == 0, proc.stdout + proc.stderr
        killed = set(re.findall(r"Stopping \w+ process (\d+)", proc.stdout))
        assert killed == self._LISTENING, (
            f"回显的 taskkill 目标应是 LISTENING 集合 {sorted(self._LISTENING)}，实际 {sorted(killed)}——"
            "漏杀 = 停止失效（第二个循环没跑？），多杀 = established 的另一端（浏览器）被误杀。"
        )
        assert "[OK] Frontend service stopped" in proc.stdout and "All services stopped" in proc.stdout, (
            f"两个循环都必须跑完（for 体内控制权移交会静默截断脚本）：{proc.stdout[-400:]}"
        )


@pytest.mark.skipif(
    os.name != "nt" or shutil.which("powershell") is None,
    reason="PowerShell 行为钉只在 nt 上跑（CI Linux 跳过，与 bash 钉互为镜像）",
)
class TestAutoBackupBehavior:
    """沙箱真跑 auto_backup.ps1，钉 2026-08-24 三个修复的行为面。

    -ProjectRoot 指向 tmp 沙箱（backups 目录与日志全落沙箱），假 docker
    经 PATH 前缀接管（先预检确认，理由同 Stop.bat 那层防护）。钉住：
    容器离线 → exit 1 且**零工作目录残留**（修复 1：旧版每次失败留一
    个无人回收的空目录）；pg_dump custom / SQL 失败 → exit 2 / 3 且
    工作目录被清掉；成功 → zip 生成、源目录删除、exit 0（修复 2 的
    成功路径）；遗留空目录被回收、非空目录保留（Remove-StaleWorkDirs
    的判据）。压缩失败路径（exit 4、源目录保留）依赖真实 Compress-
    Archive 失败，沙箱里无法可靠注入，未钉——静态门禁盖住它的存在。
    """

    def _preflight(self, bin_dir: str) -> None:
        ps = shutil.which("powershell")
        assert ps
        probe = subprocess.run(
            [ps, "-NoProfile", "-Command", "docker ps --filter name=airdrop-db --format '{{.Names}}'"],
            env=_windows_env(bin_dir),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=60,
            check=False,
        )
        assert probe.stdout.strip() == "airdrop-db", (
            f"docker shim 未接管（PATH 解析失效）——拒跑 auto_backup.ps1。\n{probe.stdout[:300]}{probe.stderr[:300]}"
        )

    def _run_backup(self, tmp_path: Path, **flags: str) -> subprocess.CompletedProcess[str]:
        bin_dir = _write_shims(tmp_path, {"docker.cmd": _FAKE_DOCKER_PS1}, newline="\r\n")
        self._preflight(bin_dir)
        ps = shutil.which("powershell")
        assert ps
        return subprocess.run(
            [
                ps,
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(REPO_ROOT / "scripts" / "auto_backup.ps1"),
                "-ProjectRoot",
                str(tmp_path),
            ],
            cwd=tmp_path,
            env=_windows_env(bin_dir, **flags),
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=120,
            check=False,
        )

    @staticmethod
    def _work_dirs(tmp_path: Path) -> list[str]:
        auto = tmp_path / "backups" / "auto"
        if not auto.is_dir():
            return []
        return [p.name for p in auto.iterdir() if p.is_dir() and p.name.startswith("airdrop_auto_")]

    def test_container_offline_exits_1_without_workdir(self, tmp_path: Path) -> None:
        proc = self._run_backup(tmp_path, OFFLINE="1")
        assert proc.returncode == 1, proc.stdout[-500:]
        assert self._work_dirs(tmp_path) == [], "容器离线的失败路径不得留下工作目录（修复 1 的直接回归）。"

    def test_pg_dump_custom_failure_cleans_up_with_exit_2(self, tmp_path: Path) -> None:
        proc = self._run_backup(tmp_path, FAIL_CUSTOM="1")
        assert proc.returncode == 2, proc.stdout[-500:]
        assert self._work_dirs(tmp_path) == [], "custom 失败路径必须清掉自己的空工作目录。"

    def test_pg_dump_sql_failure_keeps_usable_dump_with_exit_3(self, tmp_path: Path) -> None:
        """SQL 导出失败：exit 3，但工作目录**必须保留** —— 里面有成功的 custom dump。

        这是 Remove-BackupWorkDir 的设计行为：目录非空 = 有可用备份
        （custom 格式可直接 pg_restore），删掉它比留一个目录严重得多。
        所以断言方向与 custom 失败（目录为空 → 清理）相反。
        """
        proc = self._run_backup(tmp_path, FAIL_SQL="1")
        assert proc.returncode == 3, proc.stdout[-500:]
        dirs = self._work_dirs(tmp_path)
        assert len(dirs) == 1, f"应保留恰好一个含 custom dump 的工作目录：{dirs}"
        assert (tmp_path / "backups" / "auto" / dirs[0] / "airdrop_pg.dump").is_file(), (
            "保留的目录里应当有 custom 格式 dump（可用的那份备份）。"
        )

    def test_success_makes_zip_and_removes_source_dir(self, tmp_path: Path) -> None:
        proc = self._run_backup(tmp_path)
        assert proc.returncode == 0, proc.stdout[-500:]
        auto = tmp_path / "backups" / "auto"
        zips = list(auto.glob("airdrop_auto_*.zip"))
        assert len(zips) == 1 and zips[0].stat().st_size > 0, f"应产出一个非空 zip：{zips}"
        assert self._work_dirs(tmp_path) == [], "压缩成功后源目录必须删除（保留两份会误导读的人）。"

    def test_recycles_stale_empty_dirs_but_keeps_non_empty(self, tmp_path: Path) -> None:
        auto = tmp_path / "backups" / "auto"
        auto.mkdir(parents=True)
        stale_empty = auto / "airdrop_auto_20200101_000000"
        stale_full = auto / "airdrop_auto_20200202_000000"
        stale_empty.mkdir()
        stale_full.mkdir()
        (stale_full / "airdrop_pg.dump").write_bytes(b"x")
        proc = self._run_backup(tmp_path)
        assert proc.returncode == 0, proc.stdout[-500:]
        assert not stale_empty.exists(), "遗留空目录必须被回收（修复 1 的清扫部分）。"
        assert stale_full.exists(), "非空目录里是可用备份，一律不碰。"


class TestDbPathResolutionPins:
    """库文件探测逻辑的静态钉（全平台）：.env 解析契约不许被"顺手改短"。

    backup.sh / health-check.sh 的本地分支靠「读 .env 的 DB_PATH」定位
    真正的库，解析管道 `grep ^DB_PATH= | tail -1 | cut -d= -f2- |
    tr -d space` 每个环节都有语义。任何一个环节被改掉，脚本都会安静地
    去错文件——2026-08-24 备份过期副本还报成功的事故就是这类分家。
    判据全部落在 _code_lines（非注释行）上：注释里提过的词不算实现
    （本文件已有的教训，见 TestHealthCheckCoversTheBudgetLedger）。
    """

    _PIPELINE = "grep -E '^DB_PATH=' .env | tail -1 | cut -d= -f2- | tr -d '[:space:]'"

    def test_backup_env_parse_pipeline_is_intact(self) -> None:
        assert self._PIPELINE in self._backup_code(), (
            "backup.sh 的 .env 解析管道被改动了。契约：`tail -1`（多行取最后一条）、"
            "`cut -d= -f2-`（值里可以带 =）、`tr -d '[:space:]'`（去空白含 \\r）。"
            "任何一环改短都会安静地去错文件——宁可整条保留。"
        )

    def test_health_check_env_parse_pipeline_is_intact(self) -> None:
        assert self._PIPELINE in self._health_code(), "health-check.sh 的 .env 解析管道被改动了（契约同 backup.sh）。"

    def test_backup_keeps_backend_relative_fallback(self) -> None:
        """DB_PATH 是相对路径时，服务的工作目录是 backend/ —— CWD 解析回退分支必须活着。"""
        assert '[ -f "backend/$DB_PATH_ENV" ]' in self._backup_code(), (
            "backup.sh 丢了相对路径的 backend/ 回退分支 —— .env 里 DB_PATH=data/… "
            "这种最常见的写法会直接判成「找不到库」而失败。"
        )

    def test_backup_must_not_guess_file_names(self) -> None:
        """backup.sh 的显式契约：找不到 DB_PATH 就失败，不许重新长出猜文件名的候选清单。

        2026-08-24 事故的根源就是「猜中一个文件名」——猜中的是过期副本，
        备份看起来成功了。health-check 的候选清单 + 警告是**只读检查**的
        合理形态，但对备份不够：备份必须要么是正确的库，要么明确失败。
        """
        code = self._backup_code()
        assert "不猜其它文件名" in code, "backup.sh 丢了「不猜文件名」的失败说明 —— 那是契约的一部分。"
        assert "DB_CANDIDATES" not in code, "backup.sh 长出了候选清单 —— 备份不许在候选里挑一个可能过期的库。"

    def test_health_check_candidate_order_puts_db_path_first(self) -> None:
        """候选清单里 $DB_PATH_ENV 必须排第一 —— 顺序漂移 = 又在猜文件名。"""
        line = next(ln for ln in self._health_code().splitlines() if "DB_CANDIDATES=" in ln)
        assert line.strip() == (
            'DB_CANDIDATES="$DB_PATH_ENV data/airdrop.db backend/data/airdrop.db data/app.db backend/data/app.db"'
        ), f"health-check.sh 的探测候选顺序漂移了：{line.strip()} —— $DB_PATH_ENV 必须排第一。"

    def test_health_check_fallback_warning_is_gated_on_mismatch(self) -> None:
        """回退候选警告必须由「命中 ≠ DB_PATH」这个条件触发，而不是无条件打印。"""
        code = self._health_code()
        assert '[ "$DB_FOUND" != "$DB_PATH_ENV" ]' in code, (
            "health-check.sh 的回退警告没有挂在「命中 ≠ DB_PATH」条件上。"
        )
        assert "找到的是回退候选，不是 .env 里的 DB_PATH=" in code, (
            "health-check.sh 丢了回退候选警告文案 —— 用户将无法察觉自己对着过期副本做判断。"
        )

    def _backup_code(self) -> str:
        return "\n".join(_code_lines("scripts/backup.sh"))

    def _health_code(self) -> str:
        return "\n".join(_code_lines("scripts/health-check.sh"))


_FAKE_DOCKER = "#!/bin/bash\nexit 1\n"
_FAKE_CURL = (
    "#!/bin/bash\n"
    'for arg in "$@"; do\n'
    '  case "$arg" in\n'
    '    */health) echo \'{"ok":true,"status":"healthy"}\'; exit 0 ;;\n'
    '    */version) echo \'{"version":"test"}\'; exit 0 ;;\n'
    "  esac\n"
    "done\n"
    "exit 1\n"
)


def _write_shims(tmp_path: Path, scripts: dict[str, str], newline: str = "\n") -> str:
    """把假命令写进 tmp_path/bin 并返回 PATH 前缀（行为钉共用的 shim 工厂）。

    newline：sh 脚本用 \n；.cmd/.bat 必须 \r\n（cmd 对仅 LF 的某些构造
    —— if/for 块、goto 标签 —— 行为不可靠）。字节写入且先把体内的
    \r\n 归一成 \n 再统一转换，避免文本模式二次翻译产生 \r\r\n
    （曾真踩过：文件里隔行出空行，if 块行为诡异）。
    """
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    for name, body in scripts.items():
        p = bin_dir / name
        data = body.replace("\r\n", "\n").replace("\n", newline)
        p.write_bytes(data.encode("utf-8"))
        p.chmod(0o755)
    return str(bin_dir)


@pytest.mark.skipif(
    shutil.which("bash") is None or os.name == "nt",
    reason="本机无可用 bash；行为钉在 CI Linux 上真跑（期望值已 Git Bash 沙箱预演锁定）",
)
class TestDbProbeBehavior:
    """沙箱真跑 backup.sh / health-check.sh，断言库文件探测的实际行为。

    场景矩阵与期望值已在 Git Bash 沙箱人工预演锁定（2026-09-30）：
    backup 四场景（精确命中 / tail-1 双向 / 无 .env 必须失败）+
    health-check 四场景（精确命中 / 回退警告 / 无 .env 静默回退 /
    全缺失仅警告）。假 `docker`（exit 1）定死容器分支让脚本必然走
    本地分支；假 `curl` 喂 /health 与 /version，健康检查不依赖真服务。
    预演时的一个坑：Windows Store 的 python3 存根退出码 49，曾被误认
    为脚本缺陷——那不是，CI Linux 上无此问题。
    """

    def _shim(self, tmp_path: Path, scripts: dict[str, str]) -> str:
        return _write_shims(tmp_path, scripts)

    def _run(self, sandbox: Path, script_rel: str, bin_dir: str) -> subprocess.CompletedProcess[str]:
        bash = shutil.which("bash")
        assert bash, "skipif 应该已经跳过了这一条"
        env = {
            **os.environ,
            "PATH": bin_dir + os.pathsep + os.environ.get("PATH", ""),
            "PYTHONUTF8": "1",
        }
        return subprocess.run(
            [bash, str(REPO_ROOT / script_rel)],
            cwd=sandbox,
            env=env,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=120,
            check=False,
        )

    @staticmethod
    def _make_sqlite(path: Path, marker: str) -> None:
        import sqlite3

        path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(path)
        try:
            conn.execute(f"CREATE TABLE {marker} (x INTEGER)")
            conn.commit()
        finally:
            conn.close()

    # ── backup.sh：本地分支行为 ──

    def test_backup_backs_up_the_db_db_path_points_to(self, tmp_path: Path) -> None:
        """精确命中：备份产物必须真的是 DB_PATH 指向的那个库（用 marker 表验证内容）。"""
        self._make_sqlite(tmp_path / "data" / "local.db", "probe_backup_src")
        (tmp_path / ".env").write_text("DB_PATH=data/local.db\n", encoding="utf-8", newline="\n")
        proc = self._run(tmp_path, "scripts/backup.sh", self._shim(tmp_path, {"docker": _FAKE_DOCKER}))
        assert proc.returncode == 0, proc.stdout + proc.stderr
        assert "源: data/local.db" in proc.stdout, proc.stdout[-800:]
        assert "来自 .env 的 DB_PATH" in proc.stdout, proc.stdout[-800:]
        tars = list((tmp_path / "backups").glob("airdrop-alpha-backup-*.tar.gz"))
        assert len(tars) == 1, f"应产出恰好一个备份压缩包：{tars}"
        import sqlite3
        import tarfile

        with tarfile.open(tars[0]) as tf:
            app_db = next(name for name in tf.getnames() if name.endswith("/app.db"))
            restored = tmp_path / "restored.db"
            restored.write_bytes(tf.extractfile(app_db).read())
        conn = sqlite3.connect(restored)
        try:
            tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        finally:
            conn.close()
        assert "probe_backup_src" in tables, (
            f"备份产物里没有源库的 marker 表（{tables}）—— 备的不是 DB_PATH 指向的那个库。"
        )

    def test_backup_takes_the_last_db_path_line(self, tmp_path: Path) -> None:
        """tail -1 契约（失败向）：最后一行缺失 → 必须失败，不能静默用第一行的库。"""
        self._make_sqlite(tmp_path / "data" / "local.db", "probe_first_line")
        (tmp_path / ".env").write_text(
            "DB_PATH=data/local.db\nDB_PATH=data/missing.db\n", encoding="utf-8", newline="\n"
        )
        proc = self._run(tmp_path, "scripts/backup.sh", self._shim(tmp_path, {"docker": _FAKE_DOCKER}))
        assert proc.returncode == 1, f"最后一行缺失却备份成功（用的是第一行的库？）：{proc.stdout[-500:]}"
        assert "DB_PATH=data/missing.db" in proc.stdout, proc.stdout[-500:]

    def test_backup_last_line_wins_when_it_exists(self, tmp_path: Path) -> None:
        """tail -1 契约（成功向）：第一行缺失、最后一行存在 → 备份最后一行的库。"""
        self._make_sqlite(tmp_path / "data" / "local.db", "probe_last_wins")
        (tmp_path / ".env").write_text(
            "DB_PATH=data/missing.db\nDB_PATH=data/local.db\n", encoding="utf-8", newline="\n"
        )
        proc = self._run(tmp_path, "scripts/backup.sh", self._shim(tmp_path, {"docker": _FAKE_DOCKER}))
        assert proc.returncode == 0, proc.stdout + proc.stderr
        assert "源: data/local.db" in proc.stdout, proc.stdout[-800:]

    def test_backup_fails_without_guessing_when_no_env(self, tmp_path: Path) -> None:
        """无 .env：必须 exit 1 且不猜文件名 —— 哪怕 data/local.db 就躺在那里。"""
        self._make_sqlite(tmp_path / "data" / "local.db", "probe_unreferenced")
        proc = self._run(tmp_path, "scripts/backup.sh", self._shim(tmp_path, {"docker": _FAKE_DOCKER}))
        assert proc.returncode == 1, f"无 .env 却备份成功（猜到了某个文件名？）：{proc.stdout[-500:]}"
        assert "不猜其它文件名" in proc.stdout, proc.stdout[-500:]
        assert not list((tmp_path / "backups").glob("*.tar.gz")), "失败的备份不该产出压缩包。"

    # ── health-check.sh：探测顺序与回退警告 ──

    def test_health_check_reports_the_db_db_path_points_to(self, tmp_path: Path) -> None:
        self._make_sqlite(tmp_path / "data" / "local.db", "probe_hc_direct")
        (tmp_path / ".env").write_text("DB_PATH=data/local.db\n", encoding="utf-8", newline="\n")
        proc = self._run(tmp_path, "scripts/health-check.sh", self._shim(tmp_path, {"curl": _FAKE_CURL}))
        assert proc.returncode == 0, proc.stdout + proc.stderr
        assert "数据库文件存在: data/local.db" in proc.stdout, proc.stdout[-800:]
        assert "回退候选" not in proc.stdout, "精确命中不该出回退警告。"

    def test_health_check_warns_when_falling_back(self, tmp_path: Path) -> None:
        """DB_PATH 缺失、具名候选命中 → 必须出「回退候选」警告，别对着过期副本做判断。"""
        (tmp_path / "data").mkdir(parents=True, exist_ok=True)
        (tmp_path / "data" / "airdrop.db").touch()
        (tmp_path / ".env").write_text("DB_PATH=data/missing.db\n", encoding="utf-8", newline="\n")
        proc = self._run(tmp_path, "scripts/health-check.sh", self._shim(tmp_path, {"curl": _FAKE_CURL}))
        assert proc.returncode == 0, proc.stdout + proc.stderr
        assert "数据库文件存在: data/airdrop.db" in proc.stdout, proc.stdout[-800:]
        assert "找到的是回退候选" in proc.stdout, proc.stdout[-800:]
        assert "DB_PATH=data/missing.db" in proc.stdout, proc.stdout[-800:]

    def test_health_check_silent_fallback_without_env(self, tmp_path: Path) -> None:
        """无 .env：具名候选命中属预期行为，不该误发回退警告。"""
        (tmp_path / "data").mkdir(parents=True, exist_ok=True)
        (tmp_path / "data" / "airdrop.db").touch()
        proc = self._run(tmp_path, "scripts/health-check.sh", self._shim(tmp_path, {"curl": _FAKE_CURL}))
        assert proc.returncode == 0, proc.stdout + proc.stderr
        assert "数据库文件存在: data/airdrop.db" in proc.stdout, proc.stdout[-800:]
        assert "回退候选" not in proc.stdout, "无 .env 时命中候选不算回退。"

    def test_health_check_reports_missing_db_nonfatally(self, tmp_path: Path) -> None:
        """全缺失：仅警告不致命（PG / 容器场景本来就没有本地文件）。"""
        (tmp_path / ".env").write_text("DB_PATH=data/missing.db\n", encoding="utf-8", newline="\n")
        proc = self._run(tmp_path, "scripts/health-check.sh", self._shim(tmp_path, {"curl": _FAKE_CURL}))
        assert proc.returncode == 0, proc.stdout + proc.stderr
        assert "数据库文件未找到" in proc.stdout, proc.stdout[-800:]


_FAKE_DOCKER_LOGGING = '#!/bin/bash\necho "$*" >> "$PWD/docker_calls.log"\nexit 0\n'
_FAKE_CURL_OK = "#!/bin/bash\nexit 0\n"
_FAKE_SLEEP = "#!/bin/bash\nexit 0\n"


@pytest.mark.skipif(
    shutil.which("bash") is None or os.name == "nt",
    reason="本机无可用 bash；deploy 预检行为钉在 CI Linux 上真跑（期望值已 Git Bash 沙箱预演锁定）",
)
class TestDeployPreflightBehavior:
    """沙箱真跑 deploy.sh，断言生产预检真的拦得住配错的 .env。

    静态 `TestProductionPreflight` 只能证明"检查代码存在且位置对"，
    证明不了"配错的 .env 真的会被拦下"——判据漂移（比如把比较符改反）
    静态钉全绿、脚本已放行。本类把脚本**复制**进沙箱跑：`PROJECT_ROOT`
    取自脚本自身位置，不复制则读写的是真实仓库的 `.env`。假 `docker`
    记录每次调用到沙箱内 docker_calls.log（"compose version" 探测属于
    正常检测，真实动作指 down/build/up）；假 `curl` 让健康探测一次成功、
    假 `sleep` 让等待瞬时完成——预检通过后的全流程秒级走完。

    八场景已在 Git Bash 沙箱预演锁定（2026-09-30）：无 .env 先创建模板
    再停下（⛔ 停止 + 重新执行提示 + .env 落盘）、模板值四项全挂、短
    API_KEY 单项挂（其余三项不误报）、CORS 的 127.0.0.1 别名分支、
    有效配置全流程（预检通过 + 部署成功 + 真实 compose 动作出现）、
    dev 无 .env 直用模板不预检、dev 存量 .env 跳过预检、未知环境参数。
    每个失败场景都断言 compose 零真实动作——"预检失败还启动"在动态层
    也不放过。
    """

    _VALID_PROD_ENV = (
        "APP_ENV=production\nAPI_KEY=" + "a" * 40 + "\nAUTH_TOKEN_SECRET=abc\nCORS_ORIGINS=https://api.example.com\n"
    )

    def _deploy_sandbox(self, tmp_path: Path, env_text: str | None = None) -> str:
        """搭沙箱：脚本复制进来（PROJECT_ROOT 从脚本位置推导）+ 受控 .env + shims。"""
        scripts_dir = tmp_path / "scripts"
        scripts_dir.mkdir()
        shutil.copyfile(REPO_ROOT / "scripts" / "deploy.sh", scripts_dir / "deploy.sh")
        shutil.copyfile(REPO_ROOT / ".env.example", tmp_path / ".env.example")
        if env_text is not None:
            (tmp_path / ".env").write_text(env_text, encoding="utf-8", newline="\n")
        return _write_shims(tmp_path, {"docker": _FAKE_DOCKER_LOGGING, "curl": _FAKE_CURL_OK, "sleep": _FAKE_SLEEP})

    def _run_deploy(self, sandbox: Path, bin_dir: str, *args: str) -> subprocess.CompletedProcess[str]:
        bash = shutil.which("bash")
        assert bash, "skipif 应该已经跳过了这一条"
        env = {
            **os.environ,
            "PATH": bin_dir + os.pathsep + os.environ.get("PATH", ""),
            "PYTHONUTF8": "1",
        }
        return subprocess.run(
            [bash, str(sandbox / "scripts" / "deploy.sh"), *args],
            cwd=sandbox,
            env=env,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=120,
            check=False,
        )

    @staticmethod
    def _compose_actions(sandbox: Path) -> list[str]:
        """返回真实 compose 动作（down/build/up）行；`compose version` 探测不算。"""
        log = sandbox / "docker_calls.log"
        if not log.exists():
            return []
        return [
            ln
            for ln in log.read_text(encoding="utf-8").splitlines()
            if re.match(r"compose (down|build|up|--profile)", ln)
        ]

    def test_prod_without_env_stops_after_creating_the_template(self, tmp_path: Path) -> None:
        """prod 无 .env：先从模板创建（部署者要有一份可填的文件），然后立刻停下。"""
        bin_dir = self._deploy_sandbox(tmp_path)
        proc = self._run_deploy(tmp_path, bin_dir, "prod")
        assert proc.returncode == 1, proc.stdout[-800:]
        assert "已从 .env.example 创建 .env" in proc.stdout, proc.stdout[-600:]
        assert "⛔ 停止" in proc.stdout, proc.stdout[-600:]
        assert "重新执行" in proc.stdout, "必须告诉部署者填完后怎么重跑。"
        assert (tmp_path / ".env").is_file(), "模板应已落盘。"
        assert self._compose_actions(tmp_path) == [], "停在模板检查就不能有任何 compose 动作。"

    def test_prod_with_template_values_fails_all_four_prechecks(self, tmp_path: Path) -> None:
        """模板值 .env（从 .env.example 复制出来的形态）：四项预检全部报出，启动前停下。"""
        env = "APP_ENV=development\nAPI_KEY=\nAUTH_TOKEN_SECRET=\nCORS_ORIGINS=http://localhost:3000\n"
        bin_dir = self._deploy_sandbox(tmp_path, env)
        proc = self._run_deploy(tmp_path, bin_dir, "prod")
        assert proc.returncode == 1, proc.stdout[-800:]
        for marker in (
            "❌ APP_ENV",
            "❌ API_KEY 长度",
            "❌ AUTH_TOKEN_SECRET 为空",
            "❌ CORS_ORIGINS 仍含 localhost",
        ):
            assert marker in proc.stdout, f"缺 {marker}：{proc.stdout[-600:]}"
        assert "预检未通过" in proc.stdout, proc.stdout[-600:]
        assert self._compose_actions(tmp_path) == [], "预检失败后 compose 零真实动作。"

    def test_prod_short_api_key_fails_even_when_rest_is_valid(self, tmp_path: Path) -> None:
        """长度门是独立的：API_KEY 8 字符挂、其余三项不得误报。"""
        env = "APP_ENV=production\nAPI_KEY=shortkey8\nAUTH_TOKEN_SECRET=abc\nCORS_ORIGINS=https://api.example.com\n"
        bin_dir = self._deploy_sandbox(tmp_path, env)
        proc = self._run_deploy(tmp_path, bin_dir, "prod")
        assert proc.returncode == 1, proc.stdout[-800:]
        assert "❌ API_KEY 长度 8" in proc.stdout, proc.stdout[-600:]
        for absent in ("❌ APP_ENV", "❌ AUTH_TOKEN_SECRET", "❌ CORS_ORIGINS"):
            assert absent not in proc.stdout, f"{absent} 不该被报出（其余项是有效的）：{proc.stdout[-600:]}"
        assert self._compose_actions(tmp_path) == []

    def test_prod_rejects_loopback_cors_via_127_alias(self, tmp_path: Path) -> None:
        """CORS 检查必须同时覆盖 localhost 和 127.0.0.1 两个别名（case 分支的第二支）。"""
        env = self._VALID_PROD_ENV.replace("https://api.example.com", "http://127.0.0.1:3000")
        bin_dir = self._deploy_sandbox(tmp_path, env)
        proc = self._run_deploy(tmp_path, bin_dir, "prod")
        assert proc.returncode == 1, proc.stdout[-800:]
        assert "❌ CORS_ORIGINS" in proc.stdout, proc.stdout[-600:]
        assert self._compose_actions(tmp_path) == []

    def test_prod_with_valid_config_runs_the_full_flow(self, tmp_path: Path) -> None:
        """有效配置：预检通过 → 全流程跑完；真实 compose 动作此时才允许出现。"""
        bin_dir = self._deploy_sandbox(tmp_path, self._VALID_PROD_ENV)
        proc = self._run_deploy(tmp_path, bin_dir, "prod")
        assert proc.returncode == 0, proc.stdout[-800:]
        assert "生产配置预检通过" in proc.stdout, proc.stdout[-600:]
        assert "部署成功" in proc.stdout, proc.stdout[-600:]
        actions = "\n".join(self._compose_actions(tmp_path))
        assert "down" in actions and "build" in actions and "up" in actions, (
            f"有效配置应走完 down/build/up 全流程，实际：{actions}"
        )

    def test_dev_without_env_uses_template_without_precheck(self, tmp_path: Path) -> None:
        """dev 无 .env：模板默认值本身就能跑，不预检、直接部署。"""
        bin_dir = self._deploy_sandbox(tmp_path)
        proc = self._run_deploy(tmp_path, bin_dir, "dev")
        assert proc.returncode == 0, proc.stdout[-800:]
        assert "已从 .env.example 创建 .env" in proc.stdout, proc.stdout[-600:]
        assert "预检" not in proc.stdout, "dev 路径不该触发生产预检。"
        assert self._compose_actions(tmp_path), "dev 应真实执行 compose 流程。"

    def test_dev_with_existing_env_skips_precheck(self, tmp_path: Path) -> None:
        """dev 且 .env 已存在：整段预检跳过（哪怕里面是 production 值——dev 不管它们）。"""
        bin_dir = self._deploy_sandbox(tmp_path, self._VALID_PROD_ENV)
        proc = self._run_deploy(tmp_path, bin_dir, "dev")
        assert proc.returncode == 0, proc.stdout[-800:]
        assert "生产配置预检" not in proc.stdout, proc.stdout[-600:]
        assert "已从 .env.example 创建" not in proc.stdout, "存量 .env 不该被模板覆盖。"

    def test_unknown_environment_is_rejected_before_docker_detection(self, tmp_path: Path) -> None:
        """未知环境参数：立刻拒绝（此校验在 docker 检测之前，连 compose 探测都不发生）。"""
        bin_dir = self._deploy_sandbox(tmp_path)
        proc = self._run_deploy(tmp_path, bin_dir, "staging")
        assert proc.returncode == 1, proc.stdout[-800:]
        assert "未知环境" in proc.stdout, proc.stdout[-600:]
        assert self._compose_actions(tmp_path) == []
