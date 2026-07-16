"""Test Docker deployment configuration.

Reference:
- Dockerfile
- docker-compose.yml
"""

import os
import re
from pathlib import Path

import pytest
import yaml

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
                "API_PORT",
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
        doc = os.path.join(PROJECT_ROOT, "DEPLOYMENT.md")
        assert os.path.exists(doc)

    def test_deployment_doc_has_quick_start(self):
        """Test that DEPLOYMENT.md has quick start section."""
        doc = os.path.join(PROJECT_ROOT, "DEPLOYMENT.md")
        with open(doc, encoding="utf-8") as f:
            content = f.read()
            assert "快速开始" in content or "Quick Start" in content

    def test_deployment_doc_has_troubleshooting(self):
        """Test that DEPLOYMENT.md has troubleshooting section."""
        doc = os.path.join(PROJECT_ROOT, "DEPLOYMENT.md")
        with open(doc, encoding="utf-8") as f:
            content = f.read()
            assert "故障排查" in content or "Troubleshooting" in content


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
