"""Application Configuration.

使用 pydantic-settings 集中管理所有配置。
遵循 12-Factor App 配置管理原则：
  1. 代码默认值（最低优先级）
  2. .env 文件覆盖
  3. 环境变量（最高优先级）

参考：CONVENTIONS.md §12 配置管理
"""

from math import isfinite
from pathlib import Path

from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# 优先仓库根 .env，其次 backend/.env（从 backend 启动时也能读到根配置）
_BACKEND_DIR = Path(__file__).resolve().parent.parent
_ROOT_DIR = _BACKEND_DIR.parent
_ENV_FILES = tuple(str(p) for p in (_ROOT_DIR / ".env", _BACKEND_DIR / ".env") if p.is_file()) or (".env",)


# SECURITY.md §4.2：生产环境 API_KEY 长度下限
MIN_PRODUCTION_API_KEY_LENGTH = 32


class Settings(BaseSettings):
    """应用全局配置单例。

    使用方式：
        from app.config import settings
        print(settings.port)
    """

    model_config = SettingsConfigDict(
        env_file=_ENV_FILES,
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
    port: int = 8002  # 本地默认 8002（避免与其他项目 8000 冲突）
    debug: bool = False
    log_level: str = "INFO"
    log_format: str = "json"  # json | text

    # ── 数据库 ────────────────────────────────────
    db_path: str = "data/airdrop.db"
    # 设置后走 PostgreSQL（测试: docker-compose.postgres.yml → :5433）
    # 例: postgresql://airdrop:airdrop_test@127.0.0.1:5433/airdrop_test
    database_url: str | None = None
    # 同步路由在线程池并发执行，SQLite 写锁需要等待窗口而非立即报错
    sqlite_busy_timeout_seconds: float = 10.0

    # ── API 鉴权 ──────────────────────────────────
    api_key: str = ""  # 空 = 无鉴权（MVP 模式）

    # ── LLM 配置 (ADR-001, ADR-012 分级使用) ─────
    openai_api_key: str = ""
    openai_base_url: str = "https://api.openai.com/v1"
    llm_model: str = "gpt-4o-mini"
    llm_temperature: float = 0.3
    llm_max_tokens: int = 512
    llm_daily_budget_usd: float = 1.0
    llm_semaphore_size: int = 5
    # v2.0 分级使用：仅 discovery_score ≥ 此阈值的项目启用 LLM（ADR-012）
    llm_discovery_score_threshold: float = 0.7

    # ── 采集质量阈值 (ADR-012) ───────────────────
    discovery_score_analysis_threshold: float = 0.3
    raw_projects_retention_days: int = 30
    project_signals_retention_days: int = 90
    collection_logs_retention_days: int = 90

    # ── 评分权重 v1.2 (Σ=1.0) ───────────────────
    weight_airdrop_signal: float = 0.18
    weight_narrative_timing: float = 0.15
    weight_team_reputation: float = 0.12
    weight_risk: float = 0.12
    weight_tokenomics: float = 0.10
    weight_competition: float = 0.10
    weight_execution: float = 0.13  # GitHub/路线图/推进
    weight_transparency: float = 0.10  # 文档/白皮书/社媒
    # 生效权重版本，随每条评分写入 projects.weight_version（WEIGHT_CALIBRATION §1.2）
    weight_version: str = "v1.2"

    # ── 并发控制 (ADR-007) ───────────────────────
    max_concurrent_projects: int = 10

    # ── 调度配置 (ADR-005, ADR-012 双调度) ──────
    scheduler_enabled: bool = True
    cron_expression: str = "0 8 * * *"  # 分析调度：空队列 /run
    timezone: str = "UTC"
    # APScheduler 默认 misfire_grace_time=1 秒：日更任务只要错过 1 秒就整天不跑。
    # 一次分析运行本身可能占用数秒（500 条队列实测 2.8 秒），足以自造 misfire。
    # 1 小时的补跑窗口对日更/时更任务都足够，且配 coalesce=True 只补跑一次。
    scheduler_misfire_grace_seconds: int = 3600
    # 采集调度器（v2.0，ADR-012）
    collection_scheduler_enabled: bool = True
    # 采集成功后是否自动触发分析（handoff；默认关，由分析 cron / 手动 /run 消费）
    collection_auto_run_enabled: bool = False
    analysis_run_limit: int = 100
    defillama_cron: str = "0 8 * * *"
    github_cron: str = "30 8 * * *"
    coingecko_cron: str = "0 9 * * *"
    cryptorank_cron: str = "15 9 * * *"
    twitter_kol_cron: str = "0 * * * *"
    twitter_keyword_cron: str = "*/15 * * * *"
    etherscan_cron: str = "0 */6 * * *"
    galxe_cron: str = "0 10 * * *"
    layer3_cron: str = "30 10 * * *"

    # ── 外部数据源 (ADR-012) ─────────────────────
    # DefiLlama（P0，免费）
    defillama_enabled: bool = True
    defillama_base_url: str = "https://api.llama.fi"
    defillama_timeout: int = 30
    defillama_retry: int = 3
    # GitHub（P0，免费）
    github_enabled: bool = True
    github_token: str = ""
    github_api_base_url: str = "https://api.github.com"
    github_timeout: int = 30
    github_retry: int = 3
    # CoinGecko（P0，免费）
    coingecko_enabled: bool = True
    coingecko_api_key: str = ""
    coingecko_api_base_url: str = "https://api.coingecko.com/api/v3"
    coingecko_timeout: int = 30
    coingecko_retry: int = 3
    # CryptoRank（可选，需 API key）
    cryptorank_enabled: bool = False
    cryptorank_api_key: str = ""
    cryptorank_base_url: str = "https://api.cryptorank.io/v1"
    cryptorank_timeout: int = 30
    cryptorank_retry: int = 3
    # RootData（融资/项目库，需 API key — 官网申请免费 Basic）
    rootdata_enabled: bool = False
    rootdata_api_key: str = ""
    rootdata_base_url: str = "https://api.rootdata.com"
    rootdata_timeout: int = 30
    rootdata_retry: int = 3
    rootdata_cron: str = "45 9 * * *"
    # Twitter/X（P0，付费）
    twitter_enabled: bool = False
    twitter_bearer_token: str = ""
    twitter_api_key: str = ""
    twitter_api_secret: str = ""
    twitter_timeout: int = 30
    twitter_retry: int = 3
    twitter_kol_accounts: str = (
        "a16z,paradigm,VitalikButerin,cz_binance,BinanceLabs,"
        "coinbase,panteracapital,dragonfly_xyz,polychaincap,1kxnetwork"
    )
    twitter_keywords: str = "#airdrop,#testnet,#points,#mainnet,points program,no token yet,TGE soon"
    # 链上数据（P1）
    etherscan_enabled: bool = False
    etherscan_api_key: str = ""
    etherscan_timeout: int = 30
    etherscan_retry: int = 3
    alchemy_api_key: str = ""
    alchemy_webhook_url: str = ""
    # Galxe / Layer3（P1，任务平台）
    galxe_enabled: bool = False
    galxe_api_key: str = ""
    galxe_timeout: int = 30
    galxe_retry: int = 3
    layer3_enabled: bool = False
    layer3_api_key: str = ""
    layer3_timeout: int = 30
    layer3_retry: int = 3
    # Dune Analytics（可选）
    dune_enabled: bool = False
    dune_api_key: str = ""

    # ── Feature Flags ─────────────────────────────
    enable_llm_enhancement: bool = False
    enable_feedback_system: bool = True  # default on for sample collection
    enable_events_tracking: bool = False
    enable_user_system: bool = False
    enable_competition_cache: bool = True
    opportunity_shadow_enabled: bool = True
    opportunity_shadow_sample_rate: float = 1.0
    opportunity_economic_snapshot_enabled: bool = False
    opportunity_economic_source_defillama_enabled: bool = False
    opportunity_economic_source_coingecko_enabled: bool = False
    opportunity_economic_source_cryptorank_enabled: bool = False
    opportunity_economic_evidence_emit_enabled: bool = False
    opportunity_economic_resolver_enabled: bool = False

    # ── 缓存配置 ──────────────────────────────────
    competition_cache_ttl: int = 3600
    competition_cache_max_size: int = 1000

    # ── 数据质量 ──────────────────────────────────
    missing_fields_threshold: int = 3
    confidence_threshold: float = 0.5

    # ── 安全配置 ──────────────────────────────────
    cors_origins: str = "http://localhost:3002,http://localhost:8002"
    cors_credentials: bool = True
    rate_limit_enabled: bool = True
    rate_limit_requests: int = 100
    rate_limit_window: int = 60
    # 前置可信代理层数。0 = 直连（默认，忽略 X-Forwarded-For）。
    # 只有确实经过 N 层受控代理时才设为 N——否则伪造该头即可绕过限流。
    trusted_proxy_count: int = 0

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
        """是否为生产环境。

        必须归一化：原实现是精确比较 `== "production"`，于是 `Production`、
        `PRODUCTION`、`prod`、`"production "` 全部绕过下面的生产安全自检——
        而 docker-compose 里 `APP_ENV=${APP_ENV:-production}` 直接取自操作员
        的 shell 变量，大小写完全不受控。
        """
        return (self.app_env or "").strip().lower() in {"production", "prod"}

    @property
    def cors_origins_list(self) -> list[str]:
        """CORS 来源列表。"""
        if self.cors_origins == "*":
            return ["*"]
        return [origin.strip() for origin in self.cors_origins.split(",")]

    # ── 验证器 ────────────────────────────────────
    @field_validator(
        "weight_airdrop_signal",
        "weight_narrative_timing",
        "weight_team_reputation",
        "weight_risk",
        "weight_tokenomics",
        "weight_competition",
        "weight_execution",
        "weight_transparency",
    )
    @classmethod
    def validate_weight_range(cls, v: float) -> float:
        """验证单个权重在 [0, 1] 范围内。"""
        if not 0.0 <= v <= 1.0:
            raise ValueError(f"Weight must be between 0 and 1, got {v}")
        return v

    @field_validator("opportunity_shadow_sample_rate")
    @classmethod
    def validate_opportunity_shadow_sample_rate(cls, value: float) -> float:
        if not isfinite(value) or not 0.0 <= value <= 1.0:
            raise ValueError("sample rate must be finite and between 0 and 1")
        return value

    @model_validator(mode="after")
    def validate_opportunity_economic_flag_rollout(self):
        """Upstream economic rollout gates: evidence_emit⇒snapshot, resolver⇒evidence."""
        if self.opportunity_economic_evidence_emit_enabled and not self.opportunity_economic_snapshot_enabled:
            raise ValueError(
                "opportunity_economic_evidence_emit_enabled requires "
                "opportunity_economic_snapshot_enabled"
            )
        if self.opportunity_economic_resolver_enabled and not self.opportunity_economic_evidence_emit_enabled:
            raise ValueError(
                "opportunity_economic_resolver_enabled requires "
                "opportunity_economic_evidence_emit_enabled"
            )
        return self

    def model_post_init(self, __context) -> None:
        """启动时断言权重和为 1.0。"""
        total = sum(
            [
                self.weight_airdrop_signal,
                self.weight_narrative_timing,
                self.weight_team_reputation,
                self.weight_risk,
                self.weight_tokenomics,
                self.weight_competition,
                self.weight_execution,
                self.weight_transparency,
            ]
        )
        if abs(total - 1.0) > 0.001:
            raise ValueError(f"Weights sum to {total:.4f}, expected 1.0. Check your configuration.")

        # 生产环境安全自检：不安全组合直接拒绝启动，避免默认放行式部署上线
        if self.is_production:
            errors: list[str] = []
            # 按解析后的列表判断：原先只比较整串是否等于 "*"，于是 "*,*" 或
            # "*,https://evil.com" 配 credentials=true 能通过校验（虽然
            # main.py 会再兜一次底，但校验器给出的是虚假保证）
            if "*" in self.cors_origins_list and self.cors_credentials:
                errors.append("CORS_ORIGINS='*' 与 CORS_CREDENTIALS=true 不能同时用于生产环境")
            api_key = (self.api_key or "").strip()
            if not api_key:
                errors.append("生产环境必须设置 API_KEY（当前为空 = 无鉴权）")
            elif len(api_key) < MIN_PRODUCTION_API_KEY_LENGTH:
                # SECURITY.md §4.2：API_KEY 长度 >= 32 字符、随机生成。
                # 原实现只校验非空，一个字符也能过——且系统没有任何接入限流，
                # 等于可以按线速爆破。
                errors.append(
                    f"生产环境 API_KEY 长度必须 >= {MIN_PRODUCTION_API_KEY_LENGTH}"
                    f"（当前 {len(api_key)}，见 SECURITY.md §4.2）"
                )
            if self.host == "0.0.0.0" and not api_key:
                errors.append("生产环境绑定 0.0.0.0 时必须设置 API_KEY")
            if errors:
                raise ValueError("不安全的生产配置: " + "; ".join(errors))


# ── 全局配置单例 ──────────────────────────────────
settings = Settings()
