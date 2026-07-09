"""Test Docker deployment configuration.

Reference:
- Dockerfile
- docker-compose.yml
"""

import pytest
import os


# Get project root directory (one level up from backend)
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class TestDockerConfiguration:
    """Test Docker configuration files."""

    def test_dockerfile_exists(self):
        """Test that Dockerfile exists."""
        dockerfile = os.path.join(PROJECT_ROOT, "backend", "Dockerfile")
        assert os.path.exists(dockerfile)

    def test_dockerfile_has_healthcheck(self):
        """Test that Dockerfile includes HEALTHCHECK."""
        dockerfile = os.path.join(PROJECT_ROOT, "backend", "Dockerfile")
        with open(dockerfile, "r", encoding="utf-8") as f:
            content = f.read()
            assert "HEALTHCHECK" in content
            assert "/health" in content

    def test_dockerfile_uses_non_root_user(self):
        """Test that Dockerfile uses non-root user."""
        dockerfile = os.path.join(PROJECT_ROOT, "backend", "Dockerfile")
        with open(dockerfile, "r", encoding="utf-8") as f:
            content = f.read()
            assert "useradd" in content
            assert "USER appuser" in content

    def test_dockerfile_exposes_port(self):
        """Test that Dockerfile exposes port 8000."""
        dockerfile = os.path.join(PROJECT_ROOT, "backend", "Dockerfile")
        with open(dockerfile, "r", encoding="utf-8") as f:
            content = f.read()
            assert "EXPOSE 8000" in content


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
        with open(compose_file, "r", encoding="utf-8") as f:
            config = yaml.safe_load(f)
            assert config is not None
            assert "services" in config

    def test_docker_compose_has_backend_service(self):
        """Test that docker-compose defines backend service."""
        import yaml
        compose_file = os.path.join(PROJECT_ROOT, "docker-compose.yml")
        with open(compose_file, "r", encoding="utf-8") as f:
            config = yaml.safe_load(f)
            assert "backend" in config["services"]

    def test_docker_compose_has_healthcheck(self):
        """Test that backend service has healthcheck."""
        import yaml
        compose_file = os.path.join(PROJECT_ROOT, "docker-compose.yml")
        with open(compose_file, "r", encoding="utf-8") as f:
            config = yaml.safe_load(f)
            backend = config["services"]["backend"]
            assert "healthcheck" in backend

    def test_docker_compose_has_volumes(self):
        """Test that backend service has volume mappings."""
        import yaml
        compose_file = os.path.join(PROJECT_ROOT, "docker-compose.yml")
        with open(compose_file, "r", encoding="utf-8") as f:
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
        with open(compose_file, "r", encoding="utf-8") as f:
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
        with open(env_file, "r", encoding="utf-8") as f:
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

    @pytest.mark.skipif(os.name == 'nt', reason="Executable test not reliable on Windows")
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
        with open(doc, "r", encoding="utf-8") as f:
            content = f.read()
            assert "快速开始" in content or "Quick Start" in content

    def test_deployment_doc_has_troubleshooting(self):
        """Test that DEPLOYMENT.md has troubleshooting section."""
        doc = os.path.join(PROJECT_ROOT, "DEPLOYMENT.md")
        with open(doc, "r", encoding="utf-8") as f:
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
        with open(nginx_conf, "r", encoding="utf-8") as f:
            content = f.read()
            assert "upstream backend" in content
            assert "server backend:8000" in content

    def test_nginx_conf_has_gzip(self):
        """Test that nginx.conf enables gzip."""
        nginx_conf = os.path.join(PROJECT_ROOT, "nginx.conf")
        with open(nginx_conf, "r", encoding="utf-8") as f:
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
        with open(dockerignore, "r", encoding="utf-8") as f:
            content = f.read()
            sensitive = [".env", "*.db", "__pycache__"]
            for pattern in sensitive:
                assert pattern in content
