"""生产配置的硬约束门禁：种子开关强制关闭 + 日志轮转真的会轮转。

## 这个文件为什么存在

这两项在 2026-08-24 之前都是**文档里的"建议"**：

- `.env.example` 写着「生产环境建议设为 false」；
- `docs/OPERATIONS.md` 记着「完全没有日志轮转」。

而"建议"的执行率是不可观测的。更糟的是这两项的失败方式都**不报错**：

- 种子开关开着 → 采集全挂时库里仍然有 8 个内置假项目，Dashboard 仍有数字。
  **它让故障看起来像正常，而没人会去查一个看起来有数据的系统。**
- 日志无上限 → 实测 6 天 3.97 MB（约 240 MB/年）。写满盘的真实后果不是
  "日志丢了"，是**数据库写入开始失败** —— DB 和日志在同一块盘上。

所以两项都改成代码强制，并在这里锁死。

## 为什么种子开关是"强制改成 false"而不是"拒绝启动"

生产自检里另外几条（空 `API_KEY`、localhost `CORS_ORIGINS`）拒绝启动，
是因为它们**无法自动修正**：密钥和域名只有部署者知道。
种子开关不一样 —— 生产环境的正确值只有一个，就是关。
忘了改不代表配置冲突，只代表用了默认值，为此拒绝启动是把一个能自动
修好的问题变成一次上线失败。
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from app.config import Settings

REPO_ROOT = Path(__file__).resolve().parents[2]

# 一组能通过生产自检的最小合法配置（否则构造 Settings 会先因别的原因报错）
_PROD_BASE = {
    "_env_file": None,
    "api_key": "a" * 32,
    "auth_token_secret": "b" * 48,
    "cors_origins": "https://app.example.com",
}


def _prod(**overrides) -> Settings:
    return Settings(app_env="production", **{**_PROD_BASE, **overrides})  # type: ignore[arg-type]


class TestSeedSwitchesAreForcedOffInProduction:
    """生产环境下两个种子开关必须是 False，无论配置里写了什么。"""

    def test_defaults_are_forced_off(self) -> None:
        settings = _prod()
        assert settings.seed_on_startup is False, "生产环境 seed_on_startup 应被强制关闭。"
        assert settings.seed_fallback_enabled is False, "生产环境 seed_fallback_enabled 应被强制关闭。"

    def test_explicit_true_is_still_forced_off(self) -> None:
        """有人显式写 `SEED_FALLBACK_ENABLED=true` 也不行。

        这条是关键：只测默认值的话，"把默认值改成 False"也能让上一条通过，
        而那和"强制"是两件事 —— 部署时一个环境变量就能把它打开。
        **区分「默认安全」和「无法配错」，只能靠显式传 True 的用例。**
        """
        settings = _prod(seed_on_startup=True, seed_fallback_enabled=True)
        assert settings.seed_on_startup is False, (
            "显式 seed_on_startup=true 在生产环境仍应被强制关闭 —— 否则这只是默认值安全，不是强制。"
        )
        assert settings.seed_fallback_enabled is False, "显式 seed_fallback_enabled=true 在生产环境仍应被强制关闭。"

    @pytest.mark.parametrize("app_env", ["production", "PRODUCTION", "prod", " Production "])
    def test_all_production_spellings_are_covered(self, app_env: str) -> None:
        """`is_production` 归一化过大小写与 `prod` 别名，强制关闭必须跟着覆盖。

        docker-compose 里 `APP_ENV=${APP_ENV:-production}` 直接取操作员的 shell
        变量，大小写完全不受控。只覆盖小写 `production` 等于漏掉真实部署路径。
        """
        settings = Settings(app_env=app_env, seed_fallback_enabled=True, **_PROD_BASE)  # type: ignore[arg-type]
        assert settings.seed_fallback_enabled is False, f"APP_ENV={app_env!r} 属于生产，种子回退应被强制关闭。"

    @pytest.mark.parametrize("app_env", ["development", "staging", "testing"])
    def test_non_production_keeps_the_switches_usable(self, app_env: str) -> None:
        """反向断言：非生产环境必须仍然能用种子数据。

        只验证"生产关掉了"分不清"关对了"和"到处都关了" ——
        后者会让本地开箱演示和 `/run` 的空库兜底一起失效，
        而那正是这两个开关存在的理由。
        """
        settings = Settings(_env_file=None, app_env=app_env)  # type: ignore[arg-type]
        assert settings.seed_on_startup is True, f"APP_ENV={app_env} 不该被强制关掉种子开关。"
        assert settings.seed_fallback_enabled is True, f"APP_ENV={app_env} 不该被强制关掉种子回退。"

    def test_forced_values_are_written_back_to_the_fields(self) -> None:
        """强制值必须写回字段本身，而不是只在使用处判断。

        `/api/v1/settings/config` 直接回显字段值。如果强制只发生在读取点，
        运维看到的会是"配置说开着"，实际行为却是关着 ——
        **一个和真实行为不一致的配置快照，会让排障从第一步就走错方向。**
        """
        settings = _prod(seed_fallback_enabled=True)
        # 走 model_dump（即端点回显用的路径）而不是属性访问
        dumped = settings.model_dump()
        assert dumped["seed_fallback_enabled"] is False, "model_dump 里仍是 True —— 强制没写回字段。"
        assert dumped["seed_on_startup"] is False, "model_dump 里仍是 True —— 强制没写回字段。"


class TestLogRotationIsReal:
    """日志轮转必须真的换文件、真的删旧文件、真的有上限。"""

    def _write_lines(self, stream, count: int, payload: str) -> None:
        for _ in range(count):
            stream.write(payload + "\n")

    def test_rotation_creates_backup_and_truncates_current(self, tmp_path) -> None:
        from app.utils.redact import _RotatingLogStream

        log_path = tmp_path / "backend.log"
        stream = _RotatingLogStream(log_path, max_bytes=200, backup_count=3)
        try:
            self._write_lines(stream, 20, "x" * 40)
            stream.flush()
        finally:
            stream.close()

        assert log_path.exists(), "轮转后当前日志文件必须存在。"
        assert log_path.stat().st_size <= 200, (
            f"当前日志文件 {log_path.stat().st_size} 字节，超过 max_bytes=200 —— 轮转没生效。"
        )
        assert (log_path.with_name("backend.log.1")).exists(), "轮转后应当留下 .1 备份文件。"

    def test_backup_count_caps_total_files(self, tmp_path) -> None:
        """历史文件数必须有上限 —— 否则只是把一个大文件换成无数小文件。

        这条抓的是最容易写错的一种"轮转"：换文件但从不删旧的，
        磁盘占用完全没有上界，和不轮转的区别只是 `ls` 更难看。
        """
        from app.utils.redact import _RotatingLogStream

        log_path = tmp_path / "backend.log"
        stream = _RotatingLogStream(log_path, max_bytes=100, backup_count=2)
        try:
            self._write_lines(stream, 60, "y" * 50)
            stream.flush()
        finally:
            stream.close()

        produced = sorted(p.name for p in tmp_path.iterdir())
        # 当前文件 + 最多 backup_count 个历史文件
        assert len(produced) <= 3, f"产生了 {len(produced)} 个文件：{produced}，超过 backup_count=2 的上限。"
        assert "backend.log.3" not in produced, f"出现了第 3 个历史文件 —— backup_count 没有生效：{produced}"

    def test_existing_file_size_is_counted_on_startup(self, tmp_path) -> None:
        """进程重启后必须按**已有文件大小**继续计数，不能从 0 重新开始。

        从 0 计数的话，一个已经 900 MB 的文件会被认为"还没到上限"，
        于是永远不轮转 —— 而这恰好是长期运行的服务最常见的状态：
        它重启过很多次，每次都从 0 开始数。
        """
        from app.utils.redact import _RotatingLogStream

        log_path = tmp_path / "backend.log"
        log_path.write_text("z" * 500, encoding="utf-8")

        stream = _RotatingLogStream(log_path, max_bytes=200, backup_count=2)
        try:
            stream.write("one more line\n")
            stream.flush()
        finally:
            stream.close()

        assert (log_path.with_name("backend.log.1")).exists(), (
            "已有 500 字节的文件在 max_bytes=200 下写第一行就该轮转 —— 说明启动时没读现有大小。"
        )

    def test_zero_max_bytes_disables_rotation(self, tmp_path) -> None:
        """`LOG_MAX_BYTES=0` 明确表示不轮转，必须尊重这个显式选择。"""
        from app.utils.redact import _RotatingLogStream

        log_path = tmp_path / "backend.log"
        stream = _RotatingLogStream(log_path, max_bytes=0, backup_count=5)
        try:
            self._write_lines(stream, 50, "w" * 60)
            stream.flush()
        finally:
            stream.close()

        assert not (log_path.with_name("backend.log.1")).exists(), "max_bytes=0 应当完全不轮转。"
        assert log_path.stat().st_size > 1000, "不轮转时内容应当全部留在当前文件里。"

    def test_rotation_failure_does_not_break_logging(self, tmp_path, monkeypatch) -> None:
        """轮转失败**不能**让写日志抛异常。

        轮转发生在 `write()` 里，而 `write()` 抛异常会让每一条日志调用
        都炸掉，进而打断正在处理的业务请求。
        **一个为了保护磁盘而存在的机制，绝不该成为线上故障的来源。**
        磁盘满是慢性问题，请求 500 是即时问题。
        """
        from app.utils.redact import _RotatingLogStream

        log_path = tmp_path / "backend.log"
        stream = _RotatingLogStream(log_path, max_bytes=50, backup_count=2)

        def boom(*_args, **_kwargs):
            raise OSError("simulated rename failure")

        # 打 `pathlib.Path.rename` 而不是 `redact.Path`：`redact` 只在
        # `configure_logging()` 里局部 import Path，模块层没有这个名字。
        # 一个打在不存在的属性上的 monkeypatch（`raising=False`）会**静默什么都不做**，
        # 于是测试测的是正常路径，却看起来在测失败路径。
        monkeypatch.setattr(Path, "rename", boom)
        try:
            # 不应抛异常
            stream.write("a" * 100 + "\n")
            stream.flush()
        finally:
            monkeypatch.undo()
            stream.close()

        assert log_path.exists(), "轮转失败后当前日志文件仍应可用。"
        assert not (log_path.with_name("backend.log.1")).exists(), (
            "rename 被打成必失败，却仍产出了 .1 —— 说明这条测试根本没走到失败路径。"
        )

    def test_configure_logging_installs_the_rotating_stream(self, tmp_path, monkeypatch) -> None:
        """判据必须接进真正的入口 —— 光有 `_RotatingLogStream` 不等于它被用上了。

        ⚠️ 这条是本轮反复踩过的坑：`check_encoding.py` 的四型判据写对了却
        没接进 `main()`，变异掉那段代码时 36 条测试全绿。
        所以这里走 `configure_logging()`，断言它装上的确实是轮转流，
        而不是回到 `path.open("a")`。
        """
        from app.config import settings as live_settings
        from app.utils import redact
        from app.utils.redact import _RotatingLogStream, configure_logging

        log_path = tmp_path / "rotate-check.log"
        monkeypatch.setattr(live_settings, "log_file", str(log_path))
        monkeypatch.setattr(live_settings, "log_max_bytes", 128)
        monkeypatch.setattr(live_settings, "log_backup_count", 2)

        configure_logging()
        try:
            installed = redact._open_log_file
            assert isinstance(installed, _RotatingLogStream), (
                f"configure_logging() 装上的是 {type(installed).__name__}，不是轮转流 —— 轮转配置没有接进主流程。"
            )
        finally:
            monkeypatch.setattr(live_settings, "log_file", "")
            configure_logging()


class TestContainerLogsAreCapped:
    """docker 的 stdout 日志也必须有上限 —— 这是与应用内轮转**独立的第二条**无界路径。

    ⚠️ 这一条差点被漏掉：应用侧把 `LOG_FILE` 的轮转补好之后，很容易以为
    「日志无上限」这个问题解决了。但 docker 默认的 `json-file` 驱动
    **完全没有大小上限**，容器打的每一行 stdout 都无限追加到
    `/var/lib/docker/containers/<id>/<id>-json.log`，只有删容器才释放 ——
    而后端**同时**往 stdout 和文件写（`_TeeWriter`），所以这条路径的流量
    和应用日志一样大。

    修好一条路径就宣布问题解决，是"部分修复被当成完整修复"的典型：
    留下的那条会在完全相同的症状下再次发生，而清单上已经打了勾。
    """

    @pytest.fixture(scope="class")
    @classmethod
    def compose(cls) -> dict:
        yaml = pytest.importorskip("yaml")
        path = REPO_ROOT / "docker-compose.prod.yml"
        assert path.is_file(), f"{path} 不存在 —— 生产 compose 文件找不到了。"
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        services = data.get("services") or {}
        # 解析器自证：服务数塌下来说明 YAML 结构变了，而不是"恰好全都合规"
        assert len(services) >= 8, f"只解析出 {len(services)} 个服务，结构可能已变 —— 解析器失效。"
        return services

    def test_every_service_caps_its_stdout_log(self, compose: dict) -> None:
        missing = []
        for name, cfg in compose.items():
            options = ((cfg or {}).get("logging") or {}).get("options") or {}
            if not options.get("max-size") or not options.get("max-file"):
                missing.append(name)
        assert not missing, (
            f"这些服务没有配置 stdout 日志上限：{sorted(missing)}。"
            "docker 默认 json-file 驱动无上限，容器日志会一直涨到写满宿主盘 —— "
            "届时失败的不是日志，是 PostgreSQL 的写入。"
        )

    def test_the_backend_service_is_covered(self, compose: dict) -> None:
        """单独钉后端：它是日志量最大的那个，也是最容易被 `env_file` 段落挤走的。

        `test_every_service_caps_its_stdout_log` 在服务字典意外变空时会假通过
        （空集合上「全部合规」恒真），所以必须有一条钉住具体服务名。
        """
        options = ((compose.get("web") or {}).get("logging") or {}).get("options") or {}
        assert options.get("max-size") == "10m", f"web 服务的 max-size 是 {options.get('max-size')!r}，期望 '10m'。"
        assert options.get("max-file") == "3", f"web 服务的 max-file 是 {options.get('max-file')!r}，期望 '3'。"


class TestRotationSettingsAreDocumented:
    """新配置键必须出现在 `.env.example`，且值与代码默认值一致。

    `.env.example` 是新人和部署脚本唯一的配置起点，漏了新键
    等于这两项永远用不上（没人知道可以调）。
    """

    def test_keys_are_in_env_example(self) -> None:
        text = (REPO_ROOT / ".env.example").read_text(encoding="utf-8")
        assert len(text) > 2000, ".env.example 短得不正常 —— 读错文件了。"
        for key, field in (("LOG_MAX_BYTES", "log_max_bytes"), ("LOG_BACKUP_COUNT", "log_backup_count")):
            match = re.search(rf"^{key}=(.*)$", text, re.MULTILINE)
            assert match, f".env.example 里找不到 `{key}=` —— 新增的轮转配置没有写进模板。"
            expected = str(Settings.model_fields[field].default)
            assert match.group(1).strip() == expected, (
                f".env.example 的 {key}={match.group(1).strip()!r} 与代码默认值 {expected!r} 不一致。"
            )

    def test_runbook_no_longer_claims_there_is_no_rotation(self) -> None:
        """`OPERATIONS.md` §12.6 那条「完全没有日志轮转」必须已经改掉。

        遗留清单里一条已经修好却仍写着待办的记录，会让人重复评估同一个问题，
        并稀释整张清单的可信度 —— 如果这条是假的，其余几条也值得怀疑。
        """
        doc = REPO_ROOT / "docs" / "OPERATIONS.md"
        text = doc.read_text(encoding="utf-8")
        anchor = "### 12.6"
        assert anchor in text, f"{doc.name} 里找不到 §12.6 —— 解析器已失效。"
        section = text[text.index(anchor) : text.index("### 12.7", text.index(anchor))]
        assert "完全没有日志轮转" not in section, "§12.6 仍写着「完全没有日志轮转」，但轮转已经实现了。"
        assert "LOG_MAX_BYTES" in section, "§12.6 没提到 `LOG_MAX_BYTES` —— 读者无从知道怎么调。"
        # 容器 stdout 是独立的第二条路径，文档必须两条都写清楚。
        # 只写应用侧的话，读者会以为"日志无上限"整件事已经解决。
        #
        # ⚠️ 不能只钉 `max-size` 出现过：这一节的**问题描述**段落本来就写着
        # 「compose 里也没有 docker logging 驱动的 max-size / max-file」。
        # 变异掉修复说明那一句时，这个断言照样绿 —— 实测如此。
        # **钉"某个词出现过"永远不够，只能钉只可能出自那一句的内容。**
        assert "`max-size: 10m` / `max-file: 3`" in section, (
            "§12.6 没写出实际配置的容器日志上限值 —— 只写应用侧轮转会让人以为问题全解决了，"
            "而 docker json-file 驱动那条无界路径还在。"
        )
        assert "json-file" in section, "§12.6 没说明 docker 默认驱动无上限这件事 —— 读者不会知道为什么需要配 max-size。"
