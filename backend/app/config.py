"""Application Configuration.

使用 pydantic-settings 集中管理所有配置。
遵循 12-Factor App 配置管理原则：
  1. 代码默认值（最低优先级）
  2. .env 文件覆盖
  3. 环境变量（最高优先级）

参考：CONVENTIONS.md §12 配置管理
"""

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """应用全局配置单例。

    使用方式：
        from app.config import settings
        print(settings.port)
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_nested_delimiter="__",
        extra="ignore",
        case_sensitive=False,
    )

    # ── 应用基础 ──────────────────────────────────
    app_name: str = "web3-airdrop-alpha-agent"
    app_env: str = "development"
    app_version: str = "0.1.0"
    host: str = "0.0.0.0"
    port: int = 8000
    debug: bool = False
    log_level: str = "INFO"
    log_format: str = "json"  # json | text

    # ── 数据库 ────────────────────────────────────
    db_path: str = "data/airdrop.db"
    database_url: str | None = None  # 设置后使用 PostgreSQL

    # ── API 鉴权 ──────────────────────────────────
    api_key: str = ""  # 空 = 无鉴权（MVP 模式）

    # ── LLM 配置 (ADR-001) ───────────────────────
    openai_api_key: str = ""
    openai_base_url: str = "https://api.openai.com/v1"
    llm_model: str = "gpt-4o-mini"
    llm_temperature: float = 0.3
    llm_max_tokens: int = 512
    llm_daily_budget_usd: float = 1.0
    llm_semaphore_size: int = 5

    # ── 评分权重 (Σ=1.0) ─────────────────────────
    weight_airdrop_signal: float = 0.20
    weight_narrative_timing: float = 0.20
    weight_team_reputation: float = 0.15
    weight_risk: float = 0.15
    weight_tokenomics: float = 0.15
    weight_competition: float = 0.15

    # ── 并发控制 (ADR-007) ───────────────────────
    max_concurrent_projects: int = 10

    # ── 调度配置 (ADR-005) ───────────────────────
    scheduler_enabled: bool = True
    cron_expression: str = "0 8 * * *"
    timezone: str = "UTC"

    # ── Feature Flags ─────────────────────────────
    enable_llm_enhancement: bool = False
    enable_feedback_system: bool = False
    enable_events_tracking: bool = False
    enable_user_system: bool = False
    enable_competition_cache: bool = True

    # ── 缓存配置 ──────────────────────────────────
    competition_cache_ttl: int = 3600
    competition_cache_max_size: int = 1000

    # ── 数据质量 ──────────────────────────────────
    missing_fields_threshold: int = 3
    confidence_threshold: float = 0.5

    # ── 安全配置 ──────────────────────────────────
    cors_origins: str = "http://localhost:3000,http://localhost:8000"
    cors_credentials: bool = True
    rate_limit_enabled: bool = True
    rate_limit_requests: int = 100
    rate_limit_window: int = 60

    # ── 监控 ──────────────────────────────────────
    metrics_enabled: bool = True
    metrics_path: str = "/metrics"
    health_check_path: str = "/health"

    # ── 种子数据 ──────────────────────────────────
    seed_on_startup: bool = True
    seed_data_path: str = "scripts/seed.py"

    # ── 计算属性 ──────────────────────────────────
    @property
    def is_llm_enabled(self) -> bool:
        """LLM 是否启用（需配置 API key + Feature Flag）。"""
        return bool(self.openai_api_key) and self.enable_llm_enhancement

    @property
    def is_production(self) -> bool:
        """是否为生产环境。"""
        return self.app_env == "production"

    @property
    def cors_origins_list(self) -> list[str]:
        """CORS 来源列表。"""
        if self.cors_origins == "*":
            return ["*"]
        return [origin.strip() for origin in self.cors_origins.split(",")]

    # ── 验证器 ────────────────────────────────────
    @field_validator("weight_airdrop_signal", "weight_narrative_timing",
                     "weight_team_reputation", "weight_risk",
                     "weight_tokenomics", "weight_competition")
    @classmethod
    def validate_weight_range(cls, v: float) -> float:
        """验证单个权重在 [0, 1] 范围内。"""
        if not 0.0 <= v <= 1.0:
            raise ValueError(f"Weight must be between 0 and 1, got {v}")
        return v

    def model_post_init(self, __context) -> None:
        """启动时断言权重和为 1.0。"""
        total = sum([
            self.weight_airdrop_signal,
            self.weight_narrative_timing,
            self.weight_team_reputation,
            self.weight_risk,
            self.weight_tokenomics,
            self.weight_competition,
        ])
        if abs(total - 1.0) > 0.001:
            raise ValueError(
                f"Weights sum to {total:.4f}, expected 1.0. "
                f"Check your configuration."
            )


# ── 全局配置单例 ──────────────────────────────────
settings = Settings()
