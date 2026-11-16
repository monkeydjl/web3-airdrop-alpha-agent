# ──────────────────────────────────────────────
# Makefile — Development Task Runner
# ──────────────────────────────────────────────
# 使用方法：make <target>
# 查看所有可用任务：make help
# ──────────────────────────────────────────────

.PHONY: help setup dev test test-llm test-golden test-cov test-fast lint format typecheck clean docker-build docker-run

# ── 默认目标 ──────────────────────────────────
.DEFAULT_GOAL := help

# ── 变量 ──────────────────────────────────────
PYTHON := python3
PIP := pip3
PYTEST := pytest
RUFF := ruff
MYPY := mypy
DOCKER := docker
COMPOSE := docker-compose

# ── 帮助 ──────────────────────────────────────
help: ## 显示所有可用任务
	@echo "Web3 Airdrop Alpha Agent System — 可用命令"
	@echo "=========================================="
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-20s\033[0m %s\n", $$1, $$2}'
	@echo ""

# ── 环境设置 ──────────────────────────────────
# 依赖的唯一真相源是 backend/requirements*.txt（CI 与 Docker 同源）；
# 根 pyproject 的 dependencies 已知漂移，不要用 `pip install -e .` 装依赖。
setup: ## 初始化开发环境（安装依赖 + pre-commit）
	$(PIP) install -r backend/requirements.txt -r backend/requirements-dev.txt
	pre-commit install
	@echo "✅ 开发环境初始化完成"

setup-venv: ## 创建虚拟环境
	$(PYTHON) -m venv .venv
	@echo "✅ 虚拟环境已创建，请执行：source .venv/bin/activate"

# ── 开发 ──────────────────────────────────────
dev: ## 启动开发服务器（热重载，绑定本机回环）
	cd backend && uvicorn app.main:app --reload --host 127.0.0.1 --port 8002

dev-debug: ## 启动开发服务器（调试模式）
	cd backend && LOG_LEVEL=DEBUG $(PYTHON) -m app.main

seed: ## 导入种子数据
	cd backend && PYTHONPATH=. $(PYTHON) scripts/seed.py

rescore: ## 用当前评分规则重算全部 projects
	cd backend && PYTHONPATH=. $(PYTHON) scripts/rescore_all.py

purge-noise: ## 删除 denylist 噪声 projects / mark raw
	cd backend && PYTHONPATH=. $(PYTHON) scripts/purge_noise_projects.py

feedback-stats: ## 反馈样本计数（校准门槛）
	cd backend && PYTHONPATH=. $(PYTHON) scripts/feedback_snapshot.py

e2e-collect: ## 多源采集 + 评分全链路
	cd backend && PYTHONPATH=. $(PYTHON) scripts/e2e_collect_score.py

seed-feedback: ## 写入演示反馈样本
	cd backend && PYTHONPATH=. $(PYTHON) scripts/seed_demo_feedback.py

calibrate: ## 权重校准报告（样本不足则 gate block）
	cd backend && PYTHONPATH=. $(PYTHON) scripts/calibrate_weights.py

calibrate-search: ## 样本达标后记录 baseline（不改生产权重）
	cd backend && PYTHONPATH=. $(PYTHON) scripts/calibrate_weights.py --search

quarantine-list: ## 列出隔离 raw_projects
	cd backend && PYTHONPATH=. $(PYTHON) scripts/quarantine_cli.py list

# ── 测试 ──────────────────────────────────────
# ⚠️ 2026-11-13 对账：test-unit/contract/api 曾引用未注册的 pytest marker
# （--strict-markers 下直接报错），test-all 曾引用不存在的 tests/unit、
# tests/contracts、tests/e2e 目录 —— 全部是"从未兑现的地图"，已删除。
# 现存真实分层：全量（test）、golden 回归（tests/golden）、覆盖率（test-cov）、
# 并行快速（test-fast）。要加分层先注册 marker（backend/pyproject.toml）。
test: ## 运行全部测试
	cd backend && $(PYTEST)

# 仅模板校验模式可用；默认评估模式的样本路径指向 backend/tests/golden（已知断裂）。
test-llm: ## 运行 LLM 模板校验（详见 evaluation/llm/template_validation.py）
	$(PYTHON) evaluation/llm/template_validation.py --validate-templates-only

test-golden: ## 运行 golden 回归测试
	cd backend && $(PYTEST) tests/golden -v

test-cov: ## 运行测试并生成覆盖率报告
	cd backend && $(PYTEST) --cov=app --cov-report=html --cov-report=term-missing

test-fast: ## 快速测试（并行，遇错即停）
	cd backend && $(PYTEST) -x -n auto

# ── 代码质量 ──────────────────────────────────
lint: ## 运行 linter
	$(RUFF) check .

lint-fix: ## 自动修复 lint 问题
	$(RUFF) check --fix .

format: ## 格式化代码
	$(RUFF) format .

format-check: ## 检查格式（不修改）
	$(RUFF) format --check .

typecheck: ## 类型检查（CI 同口径：只查 backend/app）
	cd backend && $(MYPY) app

# ⚠️ 与 CI 口径不同：CI 不查 tests/，这里的存量错误不在门禁内（见 HANDOFF）。
typecheck-all: ## 类型检查（含测试，非 CI 口径）
	cd backend && $(MYPY) app tests

# ── 安全 ──────────────────────────────────────
security-audit: ## 安全审计（依赖 + 代码）
	pip-audit
	$(RUFF) check --select S .

secret-scan: ## 密钥扫描
	detect-secrets scan --all-files --baseline .secrets.baseline

# ── Docker ────────────────────────────────────
docker-build: ## 构建 Docker 镜像
	$(DOCKER) build -f docker/Dockerfile -t web3-airdrop-alpha:latest .

docker-run: ## 运行 Docker 容器（后端实际监听 8002）
	$(DOCKER) run -p 8002:8002 --env-file .env web3-airdrop-alpha:latest

docker-up: ## 启动完整服务（docker-compose）
	$(COMPOSE) -f docker-compose.prod.yml up -d

docker-down: ## 停止服务
	$(COMPOSE) -f docker-compose.prod.yml down

docker-logs: ## 查看日志
	$(COMPOSE) -f docker-compose.prod.yml logs -f

# ── 数据库 ────────────────────────────────────
db-init: ## 初始化数据库
	cd backend && $(PYTHON) -c "from app.db import init_db; init_db()"

db-migrate: ## 运行数据库迁移（V2+）
	alembic upgrade head

db-rollback: ## 回滚最后一次迁移
	alembic downgrade -1

# ── 清理 ──────────────────────────────────────
clean: ## 清理临时文件
	rm -rf .pytest_cache .mypy_cache .ruff_cache
	rm -rf htmlcov .coverage
	rm -rf build dist *.egg-info
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name "*.pyc" -delete 2>/dev/null || true
	@echo "✅ 清理完成"

clean-all: clean ## 深度清理（含虚拟环境）
	rm -rf .venv venv
	@echo "✅ 深度清理完成"

# ── CI 本地模拟 ──────────────────────────────
ci-local: ## 在本地模拟 CI 流程
	$(MAKE) lint
	$(MAKE) format-check
	$(MAKE) typecheck
	$(MAKE) test
	@echo "✅ CI 本地模拟通过"

# ── 文档 ──────────────────────────────────────
docs-serve: ## 本地预览文档（需 mkdocs）
	mkdocs serve

docs-build: ## 构建文档站点
	mkdocs build

# ── 发布 ──────────────────────────────────────
version-patch: ## 版本号 patch 递增
	bump2version patch

version-minor: ## 版本号 minor 递增
	bump2version minor

version-major: ## 版本号 major 递增
	bump2version major

# ── 项目状态 ──────────────────────────────────
status: ## 显示项目状态
	@echo "Python: $$(python3 --version)"
	@echo "Ruff: $$(ruff --version)"
	@echo "Mypy: $$(mypy --version)"
	@echo "Pytest: $$(pytest --version | head -1)"
	@echo ""
	@echo "测试文件: $$(find tests -name 'test_*.py' | wc -l) 个"
	@echo "源代码: $$(find backend/app -name '*.py' | wc -l) 个"
	@echo "文档: $$(find docs -name '*.md' | wc -l) 份"
