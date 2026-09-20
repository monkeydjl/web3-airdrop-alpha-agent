"""Test Docker deployment configuration.

Reference:
- Dockerfile
- docker-compose.yml
"""

import os
import re
import shlex
from pathlib import Path

import pytest
import yaml

ANY_HOST = ".".join(["0", "0", "0", "0"])

# Get project root directory (one level up from backend)
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def load_workflow(filename):
    """Load a GitHub Actions workflow without coercing the ``on`` key."""
    content = Path(PROJECT_ROOT, ".github", "workflows", filename).read_text(encoding="utf-8")
    return yaml.safe_load(re.sub(r"(?m)^on:", '"on":', content, count=1))


def test_ci_supports_master_and_main_branches():
    workflow = load_workflow("ci.yml")
    assert "on" in workflow
    assert workflow["on"]["push"]["branches"] == [
        "master",
        "main",
        "feat/**",
        "fix/**",
        "docs/**",
    ]
    assert workflow["on"]["pull_request"]["branches"] == ["master", "main"]


def test_ci_health_smoke_is_bounded_and_has_cleanup():
    workflow = load_workflow("ci.yml")
    smoke_step = next(
        step for step in workflow["jobs"]["docker-build"]["steps"] if step.get("name") == "Smoke test — health check"
    )
    script = smoke_step["run"]
    assert "set -euo pipefail" in script
    assert script.index("trap cleanup EXIT") < script.index("docker run")
    assert script.index("curl --fail") < script.index("sleep 1")
    assert script.index("exit 0") < script.index("done")
    assert "seq 1 30" in script
    assert script.index("docker logs") > script.index("done")
    assert "docker rm -f" in script


def test_release_demo_health_probe_is_bounded_and_diagnostic():
    workflow = load_workflow("release.yml")
    deploy_demo = workflow["jobs"]["deploy-demo"]
    assert deploy_demo["if"] is False
    deploy_step = next(step for step in deploy_demo["steps"] if step.get("name") == "Deploy via SSH")
    script = deploy_step["run"]
    assert script.startswith("ssh deploy@demo-server 'bash -se' <<'EOF'\n")
    assert script.endswith("\nEOF\n")
    assert "seq 1 30" in script
    assert "sleep 1" in script
    assert "/health" in script
    assert script.index("docker compose up") < script.index("for attempt")
    assert script.index("for attempt") < script.index("curl --fail")
    assert script.index("curl --fail") < script.index("sleep 1")
    assert script.index("sleep 1") < script.index("done")
    assert script.index("done") < script.index("docker compose logs backend")
    assert script.index("docker compose logs backend") < script.index("exit 1")
    assert all(command not in script for command in ("docker compose down", "docker compose stop", "docker compose rm"))


def test_release_remains_tag_driven_with_root_docker_context():
    workflow = load_workflow("release.yml")
    assert set(workflow["on"]) == {"push"}
    assert set(workflow["on"]["push"]) == {"tags"}
    assert workflow["on"]["push"]["tags"] == ["v*"]
    build_step = next(
        step for step in workflow["jobs"]["release"]["steps"] if step.get("name") == "Build and push Docker image"
    )
    assert build_step["with"]["context"] == "."
    assert build_step["with"]["file"] == "docker/Dockerfile"


class TestDockerConfiguration:
    """Test Docker configuration files."""

    @staticmethod
    def _workflow_dockerfile() -> Path:
        return Path(PROJECT_ROOT, "docker", "Dockerfile")

    @staticmethod
    def _dockerignore() -> Path:
        return Path(PROJECT_ROOT, ".dockerignore")

    def test_dockerfile_exists(self):
        """Test that the workflow Dockerfile exists."""
        assert self._workflow_dockerfile().exists()

    def test_dockerfile_has_healthcheck(self):
        """Test that the workflow Dockerfile includes HEALTHCHECK."""
        content = self._workflow_dockerfile().read_text(encoding="utf-8")
        assert "HEALTHCHECK" in content
        assert "/health" in content

    def test_dockerfile_uses_non_root_user(self):
        """Test that the workflow Dockerfile uses non-root user."""
        content = self._workflow_dockerfile().read_text(encoding="utf-8")
        assert "useradd" in content
        assert "USER appuser" in content

    def test_dockerfile_exposes_port(self):
        """Test that the workflow Dockerfile exposes port 8002."""
        content = self._workflow_dockerfile().read_text(encoding="utf-8")
        assert "EXPOSE 8002" in content

    def test_dockerfile_does_not_copy_ignored_data_directory(self):
        """When .dockerignore excludes data/, workflow Dockerfile must not COPY data/."""
        dockerignore = self._dockerignore().read_text(encoding="utf-8")
        assert re.search(r"(?m)^data/$", dockerignore)

        content = self._workflow_dockerfile().read_text(encoding="utf-8")
        assert "COPY data/" not in content

    def test_dockerfile_cmd_uses_valid_fastapi_module_entrypoint(self):
        """Docker runtime must launch the real FastAPI module, not a missing script."""
        content = self._workflow_dockerfile().read_text(encoding="utf-8")
        workdirs = re.findall(r"(?m)^WORKDIR\s+(.+)$", content)
        assert workdirs[-1] == "/app/backend"

        cmd_match = re.search(r"(?m)^CMD\s+(.+)$", content)
        assert cmd_match is not None
        cmd = shlex.split(cmd_match.group(1).strip().strip("[]").replace(",", " "))

        assert cmd[:3] == ["python", "-m", "uvicorn"]
        assert "app.main:app" in cmd
        assert cmd[cmd.index("--host") + 1] == ANY_HOST
        assert cmd[cmd.index("--port") + 1] == "8002"


class TestDockerCompose:
    """Test docker-compose configuration."""

    def test_docker_compose_exists(self):
        """Test that docker-compose.yml exists."""
        compose_file = os.path.join(PROJECT_ROOT, "docker-compose.yml")
        assert os.path.exists(compose_file)

    def test_docker_compose_valid_yaml(self):
        """Test that docker-compose.yml is valid YAML."""
        import yaml

        compose_file = os.path.join(PROJECT_ROOT, "docker-compose.yml")
        with open(compose_file, encoding="utf-8") as f:
            config = yaml.safe_load(f)
            assert config is not None
            assert "services" in config

    def test_docker_compose_has_backend_service(self):
        """Test that docker-compose defines backend service."""
        import yaml

        compose_file = os.path.join(PROJECT_ROOT, "docker-compose.yml")
        with open(compose_file, encoding="utf-8") as f:
            config = yaml.safe_load(f)
            assert "backend" in config["services"]

    def test_docker_compose_has_healthcheck(self):
        """Test that backend service has healthcheck."""
        import yaml

        compose_file = os.path.join(PROJECT_ROOT, "docker-compose.yml")
        with open(compose_file, encoding="utf-8") as f:
            config = yaml.safe_load(f)
            backend = config["services"]["backend"]
            assert "healthcheck" in backend

    def test_docker_compose_has_volumes(self):
        """Test that backend service has volume mappings."""
        import yaml

        compose_file = os.path.join(PROJECT_ROOT, "docker-compose.yml")
        with open(compose_file, encoding="utf-8") as f:
            config = yaml.safe_load(f)
            backend = config["services"]["backend"]
            assert "volumes" in backend
            volumes = backend["volumes"]
            # Check for data and logs volumes
            assert any("data" in v for v in volumes)
            assert any("logs" in v for v in volumes)

    def test_docker_compose_has_restart_policy(self):
        """Test that backend service has restart policy."""
        import yaml

        compose_file = os.path.join(PROJECT_ROOT, "docker-compose.yml")
        with open(compose_file, encoding="utf-8") as f:
            config = yaml.safe_load(f)
            backend = config["services"]["backend"]
            assert "restart" in backend
            assert backend["restart"] == "unless-stopped"


class TestEnvironmentConfiguration:
    """Test environment configuration."""

    def test_env_example_exists(self):
        """Test that .env.example exists."""
        env_file = os.path.join(PROJECT_ROOT, ".env.example")
        assert os.path.exists(env_file)

    def test_env_example_has_required_vars(self):
        """Test that .env.example has required variables."""
        env_file = os.path.join(PROJECT_ROOT, ".env.example")
        with open(env_file, encoding="utf-8") as f:
            content = f.read()
            required_vars = [
                "APP_ENV",
                "APP_VERSION",
                "LOG_LEVEL",
                "PORT",
                "DB_PATH",
            ]
            for var in required_vars:
                assert var in content


class TestDeploymentScripts:
    """Test deployment scripts."""

    def test_deploy_script_exists(self):
        """Test that deploy.sh exists."""
        script = os.path.join(PROJECT_ROOT, "scripts", "deploy.sh")
        assert os.path.exists(script)

    @pytest.mark.skipif(os.name == "nt", reason="Executable test not reliable on Windows")
    def test_deploy_script_is_executable(self):
        """Test that deploy.sh is executable."""
        import stat

        script = os.path.join(PROJECT_ROOT, "scripts", "deploy.sh")
        st = os.stat(script)
        assert st.st_mode & stat.S_IXUSR

    def test_health_check_script_exists(self):
        """Test that health-check.sh exists."""
        script = os.path.join(PROJECT_ROOT, "scripts", "health-check.sh")
        assert os.path.exists(script)

    def test_backup_script_exists(self):
        """Test that backup.sh exists."""
        script = os.path.join(PROJECT_ROOT, "scripts", "backup.sh")
        assert os.path.exists(script)


class TestDeploymentDocumentation:
    """Test deployment documentation."""

    def test_deployment_doc_exists(self):
        """Test that DEPLOYMENT.md exists."""
        doc = os.path.join(PROJECT_ROOT, "docs", "DEPLOYMENT.md")
        assert os.path.exists(doc)

    def test_deployment_doc_has_quick_start(self):
        """Test that DEPLOYMENT.md has quick start section."""
        doc = os.path.join(PROJECT_ROOT, "docs", "DEPLOYMENT.md")
        with open(doc, encoding="utf-8") as f:
            content = f.read()
            assert "快速开始" in content or "Quick Start" in content or "本地运行" in content

    def test_deployment_doc_has_troubleshooting(self):
        """Test that DEPLOYMENT.md has troubleshooting section."""
        doc = os.path.join(PROJECT_ROOT, "docs", "DEPLOYMENT.md")
        with open(doc, encoding="utf-8") as f:
            content = f.read()
            assert "故障排查" in content or "Troubleshooting" in content or "常见问题" in content


class TestNginxConfiguration:
    """Test Nginx configuration."""

    def test_nginx_conf_exists(self):
        """Test that nginx.conf exists."""
        nginx_conf = os.path.join(PROJECT_ROOT, "nginx.conf")
        assert os.path.exists(nginx_conf)

    def test_nginx_conf_has_upstream(self):
        """Test that nginx.conf defines upstream backend."""
        nginx_conf = os.path.join(PROJECT_ROOT, "nginx.conf")
        with open(nginx_conf, encoding="utf-8") as f:
            content = f.read()
            assert "upstream backend" in content
            assert "server backend:8002" in content

    def test_nginx_conf_has_gzip(self):
        """Test that nginx.conf enables gzip."""
        nginx_conf = os.path.join(PROJECT_ROOT, "nginx.conf")
        with open(nginx_conf, encoding="utf-8") as f:
            content = f.read()
            assert "gzip on" in content


REPO_ROOT = Path(PROJECT_ROOT)
PROD_COMPOSE = REPO_ROOT / "docker-compose.prod.yml"
PROD_NGINX = REPO_ROOT / "docker" / "nginx" / "nginx-http.conf"


def _load_prod_compose() -> dict:
    data = yaml.safe_load(PROD_COMPOSE.read_text(encoding="utf-8"))
    assert "services" in data, "生产 compose 解析不出 services，解析器和文件格式对不上了"
    return data


def _service_env(service: dict) -> dict[str, str]:
    """把 compose 的 `environment` 列表转成 dict（值保留 `${VAR:?...}` 原文）。"""
    raw = service.get("environment") or []
    result: dict[str, str] = {}
    for item in raw:
        key, _, value = str(item).partition("=")
        result[key.strip()] = value
    assert result, "该服务没有解析出任何 environment 项，断言会变成空转"
    return result


class TestProductionEntrypointIsWired:
    """生产入口的接线门禁 —— 这几条都是"本地全绿、公网全坏"的缺陷。

    2026-09-03 实测：这四条同时存在，任意一条都足以让公网部署整站不可用，
    而它们在 `npm run dev` + `uvicorn` 下**全都不会暴露** —— 那条路径上
    没有 nginx、没有容器边界、也没有生产环境变量校验。
    所以必须靠读配置文件的断言钉住，功能测试永远抓不到。
    """

    def test_nginx_routes_api_through_the_frontend_not_the_backend(self):
        """`/api/` 必须交给 Next，否则 proxy.ts 的凭据注入根本不执行。

        浏览器不持有任何后端凭据：凭据由 `frontend-next/proxy.ts` 在服务端
        按路径分档注入（管理端前缀 → X-API-Key，其余 → 匿名 Bearer）。
        `proxy_pass http://backend` 会让那段代码被完全绕过 ——
        后端 `API_KEY` 非空时全站 401、页面空白。
        """
        content = PROD_NGINX.read_text(encoding="utf-8")
        # 取 `location /api/ {` 到该块结束前的 proxy_pass 那一行
        block = re.search(r"location /api/ \{(.*?)\n        \}", content, re.S)
        assert block, "找不到 location /api/ 块 —— 配置结构变了，本断言已失效"
        target = re.search(r"proxy_pass\s+(\S+);", block.group(1))
        assert target, "location /api/ 里没有 proxy_pass，本断言已失效"
        assert target.group(1) == "http://frontend", (
            f"location /api/ 的 proxy_pass 是 {target.group(1)}，必须是 http://frontend。"
            "指向 backend 会绕过 Next 的 proxy.ts → 凭据注入不执行 → 全站 401。"
        )

    def test_nginx_defines_the_frontend_upstream_it_proxies_to(self):
        """指过去就得定义 upstream，否则 nginx 启动即 host not found。"""
        content = PROD_NGINX.read_text(encoding="utf-8")
        assert "upstream frontend" in content
        assert "server frontend:3002" in content

    def test_nginx_does_not_expose_metrics_publicly(self):
        """`/metrics` 在后端 PUBLIC_PREFIXES 里，从公网转发过来就是免鉴权公开。

        刻意断言"不含 proxy_pass"而不是"含 return 403"：将来换成别的拒绝
        方式（`deny all` 等）也应该通过，唯一不能接受的是又把它转发出去。
        """
        content = PROD_NGINX.read_text(encoding="utf-8")
        block = re.search(r"location /metrics \{(.*?)\n        \}", content, re.S)
        assert block, "找不到 location /metrics 块 —— 配置结构变了，本断言已失效"
        assert "proxy_pass" not in block.group(1), (
            "生产 nginx 又把 /metrics 转发出去了。它在后端 PUBLIC_PREFIXES 里，"
            "转发即公开内部指标；Prometheus 走 backend 网络直连容器，不需要这条路径。"
        )

    def test_frontend_service_gets_the_admin_key(self):
        """缺 BACKEND_API_KEY 时 proxy.ts 会静默按无鉴权模式放行 → 全站 401。

        断言用 `:?` 而不只是"这个键存在"：`${VAR}` 或 `${VAR:-}` 在未设置时
        展开成空串，`proxy.ts` 拿到空值同样走那条静默分支。
        """
        env = _service_env(_load_prod_compose()["services"]["frontend"])
        assert "BACKEND_API_KEY" in env, "生产前端服务没有 BACKEND_API_KEY，proxy.ts 拿不到管理员密钥"
        assert env["BACKEND_API_KEY"].startswith("${BACKEND_API_KEY:?"), (
            f"BACKEND_API_KEY 写成 {env['BACKEND_API_KEY']}，必须用 ${{VAR:?}} 强制必填 —— "
            "空值会让 proxy.ts 按 MVP 无鉴权模式放行，表现是全站 401 且前端日志无异常。"
        )

    def test_production_compose_pins_app_env_itself(self):
        """生产 compose 必须自己钉死 APP_ENV，不能靠 env_file 继承。

        `.env.example` 的值是 `development`；靠继承的话 `config.py` 的生产自检
        （API_KEY 长度 / AUTH_TOKEN_SECRET / CORS localhost / PG 弱口令）全部跳过，
        容器照样变绿但跑的不是生产安全口径。
        """
        env = _service_env(_load_prod_compose()["services"]["web"])
        assert env.get("APP_ENV") == "production", (
            f"生产 compose 的 web 服务 APP_ENV={env.get('APP_ENV')!r}，必须显式写成 production。"
        )

    @pytest.mark.parametrize("key", ["API_KEY", "POSTGRES_PASSWORD"])
    def test_security_critical_keys_are_required_not_bare_interpolation(self, key):
        """裸 `${VAR}` 展开成空串会**覆盖** env_file 的正确值，且只给一个 warning。

        对 `API_KEY` 而言那等于"鉴权中间件短路"——公网零鉴权的静默事故。
        """
        env = _service_env(_load_prod_compose()["services"]["web"])
        joined = "\n".join(f"{k}={v}" for k, v in env.items())
        assert f"${{{key}:?" in joined, (
            f"{key} 在生产 compose 的 web 服务里没有用 ${{{key}:?...}} 必填语法。"
            "裸插值在未设置时展开成空串并覆盖 env_file，Compose 只 warning 不报错。"
        )

    def test_frontend_dockerfile_bakes_the_proxy_target_at_build_time(self):
        """`next.config.js` 的 rewrites 在 build 时读 API_PROXY_TARGET 并写进产物。

        构建期漏掉 → production 构建得到空 rewrite → `/api` 被 Next 当自身路由
        处理而 404。这与运行时 compose 传的同名变量是两个用途，不能互相替代。
        """
        content = (REPO_ROOT / "frontend-next" / "Dockerfile").read_text(encoding="utf-8")
        builder = content.split("AS builder", 1)
        assert len(builder) == 2, "Dockerfile 里找不到 builder 阶段，本断言已失效"
        # 只看 builder 之后、runner 之前那段
        build_stage = builder[1].split("AS runner", 1)[0]
        assert "API_PROXY_TARGET" in build_stage, (
            "frontend-next/Dockerfile 的 builder 阶段没有 API_PROXY_TARGET，"
            "next.config.js 的 rewrites 会在构建期拿到空值 → 生产 /api 全部 404。"
        )


class TestDockerIgnore:
    """Test .dockerignore configuration."""

    def test_dockerignore_exists(self):
        """Test that .dockerignore exists."""
        dockerignore = os.path.join(PROJECT_ROOT, ".dockerignore")
        assert os.path.exists(dockerignore)

    def test_dockerignore_excludes_sensitive_files(self):
        """Test that .dockerignore excludes sensitive files."""
        dockerignore = os.path.join(PROJECT_ROOT, ".dockerignore")
        with open(dockerignore, encoding="utf-8") as f:
            content = f.read()
            sensitive = [".env", "*.db", "__pycache__"]
            for pattern in sensitive:
                assert pattern in content
