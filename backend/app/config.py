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
from typing import Any, Self

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
    log_file: str = ""  # 可选：日志文件路径（空 = 仅 stdout）
    # ── 日志轮转（仅在 log_file 非空时生效）────────
    # 单个日志文件的字节上限，超过就轮转。默认 10 MiB。
    #
    # 为什么必须有：`log_file` 此前是**无上限追加写**。实测 `logs/backend.log`
    # 6 天长到 3.97 MB（约 240 MB/年），代码里没有轮转、compose 没配
    # docker `max-size`、宿主也没有 logrotate —— 三层都没有。
    #
    # 磁盘写满的后果不是"日志丢了"，而是**数据库写入开始失败**：
    # SQLite 与 PostgreSQL 都在同一块盘上。一个为了排障而存在的机制
    # 最终把服务本身弄挂，是最不划算的一种故障。
    #
    # 设为 0 = 不轮转（保留原行为，但必须是显式选择）。
    log_max_bytes: int = 10 * 1024 * 1024
    # 保留多少个历史文件（`backend.log.1` … `backend.log.N`）。
    # 默认 5 → 配合 10 MiB 上限，磁盘占用上限约 60 MiB（含当前文件），有界。
    log_backup_count: int = 5

    # ── 数据库 ────────────────────────────────────
    db_path: str = "data/airdrop.db"
    # 后端选择："sqlite"（默认）或 "postgres"（A2, ADR-004）
    # 设为 "postgres" 时若 DATABASE_URL 为空，则自动从 POSTGRES_* 组装连接串
    db_backend: str = "sqlite"
    # 直接指定完整 PG 连接串（优先级高于 POSTGRES_* 分项组装）
    # 例: postgresql://airdrop:airdrop_test@127.0.0.1:5433/airdrop_test
    database_url: str | None = None
    # PostgreSQL 连接分项（DB_BACKEND=postgres 且 DATABASE_URL 未设置时使用）
    postgres_host: str = "127.0.0.1"
    postgres_port: int = 5433
    postgres_user: str = "airdrop"
    # 本地开发默认值，生产必须由 POSTGRES_PASSWORD 覆盖（GO_LIVE_CHECKLIST P0-2.2）。
    # 非硬编码凭据：真实密码只经环境变量注入，从不入库/入镜像。
    postgres_password: str = "airdrop_test"  # noqa: S105
    postgres_db: str = "airdrop_test"
    # 同步路由在线程池并发执行，SQLite 写锁需要等待窗口而非立即报错
    sqlite_busy_timeout_seconds: float = 10.0

    # ── API 鉴权 ──────────────────────────────────
    api_key: str = ""  # 空 = 无鉴权（MVP 模式）
    # V2 匿名 token（ADR-008）：HMAC-SHA256 签名的 Bearer token
    # 当 api_key 非空时启用鉴权层：
    #   - api_key 本身作为管理员令牌（完整权限）
    #   - auth_token_secret 用于签发/校验匿名 token
    auth_token_secret: str = ""  # 空 = 随机生成（重启后失效，仅适合 MVP）
    auth_token_ttl_hours: int = 72  # 匿名 token 有效期

    # ── LLM 配置 (ADR-001, ADR-012 分级使用) ─────
    openai_api_key: str = ""
    openai_base_url: str = "https://api.openai.com/v1"
    llm_model: str = "gpt-4o-mini"
    llm_temperature: float = 0.3
    llm_max_tokens: int = 512
    # 日预算（美元）。**这个值现在真的会拦截调用** —— 在 2026-08-24 之前它只被
    # 两个只读接口读出来展示，没有任何累计与拦截。实现见 app/llm/budget.py。
    #
    # 0 或负数 = 不限额（而不是"全部拒绝"）：0 是"没配"的自然表达，
    # 把它解释成"一律禁止 LLM"会让一个漏填的配置静默关掉功能。
    # 真要关 LLM 用 ENABLE_LLM_ENHANCEMENT。
    #
    # 这是**软上限**：拦截在调用前，成本在调用后才知道，所以最后一次被放行的
    # 调用会把当日花费推过预算线，超出量最多是单次调用成本（由 LLM_MAX_TOKENS
    # 决定上界）。这不是 bug，是"事前拦截 + 事后计费"的必然结果。
    llm_daily_budget_usd: float = 1.0
    # 价格表里查不到的模型，按这个单价（美元/1M token，输入输出同价）估算。
    #
    # 故意定得偏高：**宁可高估导致提前熔断，也不要低估导致不熔断。**
    # 高估的后果是少花钱 + 一条明确的超预算日志；低估的后果是账单。
    # 如果这里返回 0，那么"换一个价格表里没有的模型名"就等于关掉预算 ——
    # 一个能被随手绕过的预算不是预算。
    llm_fallback_price_per_1m_usd: float = 10.0
    llm_semaphore_size: int = 5
    # v2.0 分级使用：仅 discovery_score ≥ 此阈值的项目启用 LLM（ADR-012）
    llm_discovery_score_threshold: float = 0.7

    # ── LLM 多接口/多模型故障转移 (v2.1) ──────────
    # 每个接口一组编号变量，格式直观，不会弄混：
    #   LLM_BASEURL_1=https://api.openai.com/v1
    #   LLM_API_KEY_1=sk-xxx
    #   LLM_MODELS_1_1=gpt-4o-mini
    #   LLM_MODELS_1_2=gpt-4o
    #
    #   LLM_BASEURL_2=https://api.deepseek.com/v1
    #   LLM_API_KEY_2=sk-yyy
    #   LLM_MODELS_2_1=deepseek-chat
    #   LLM_MODELS_2_2=deepseek-reasoner
    #
    # 故障转移：接口1连不上 → 切接口2；模型1失败 → 切模型2
    # 最多支持 5 个接口，每接口最多 5 个模型
    # 未配置编号接口时，回退到上方 OPENAI_API_KEY / OPENAI_BASE_URL / LLM_MODEL 单接口模式

    # ── 采集质量阈值 (ADR-012) ───────────────────
    discovery_score_analysis_threshold: float = 0.3
    raw_projects_retention_days: int = 30
    project_signals_retention_days: int = 90
    collection_logs_retention_days: int = 90

    # ── 归档保留期与调度 ─────────────────────────
    # 未过分析阈值的采集记录（processed=0）的保留期。
    # 实测这类记录占 raw_projects 的 73%（509/693），且**永远不会**被标记
    # processed=1（低于 discovery_score_analysis_threshold 就不立项），
    # 因此原来"只归档 processed=1"的条件让它们无限累积。
    # 单独给一个更长的保留期：它们仍是复盘"当时为什么没立项"的依据。
    unprocessed_raw_retention_days: int = 90
    # 归档表自身的保留期（此前 DATABASE_DDL.md 写了 180/365 天但零实现，
    # 归档表只进不出）。
    raw_archive_retention_days: int = 180
    signals_archive_retention_days: int = 365
    # 归档任务调度：默认每天 03:00，在所有采集 job（08:00-10:30）之前跑完
    archive_scheduler_enabled: bool = True
    archive_cron: str = "0 3 * * *"

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
    # fetcher 并发闸（§10.1）：限制全局 HTTP 并发请求数
    fetcher_semaphore_size: int = 10
    # fetcher 磁盘缓存目录（§10.1）：空 = 仅内存缓存
    fetcher_cache_dir: str = "cache"
    # fetcher 默认缓存 TTL（秒）
    fetcher_cache_ttl_seconds: int = 3600
    # fetcher 熔断器配置（§10.1）
    fetcher_circuit_breaker_threshold: int = 5
    fetcher_circuit_breaker_timeout_seconds: int = 60

    # ── 热度信号增强 (C3, §6.4 V2) ──────────────
    # 从 project_signals 表聚合 Twitter 讨论量 + VC 融资信号，
    # 动态调制 sector heat_score。失败时降级到静态 SECTOR_PROFILE。
    heat_signal_enabled: bool = True
    heat_signal_ttl_seconds: int = 300  # 缓存 TTL（5min）
    heat_signal_lookback_hours: int = 72  # 信号回溯窗口
    heat_signal_max_multiplier: float = 1.3  # 信号上限乘子
    heat_signal_min_multiplier: float = 0.7  # 信号下限乘子

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

    # Discord / Reddit / Medium / Mirror（P2，社区与内容源）
    # 门控规则与其它源一致（§4.1 三条件）：开关 ∧ Key ∧ data_sources.enabled。
    # Medium（RSS）/ Mirror（Arweave 公开读）无需 Key，默认开启；
    # Discord（bot token）/ Reddit（OAuth）需 Key，默认关闭。
    discord_enabled: bool = False
    discord_bot_token: str = ""
    discord_channel_id: str = ""
    discord_timeout: int = 30
    discord_retry: int = 3
    discord_cron: str = "0 */3 * * *"
    reddit_enabled: bool = False
    reddit_client_id: str = ""
    reddit_client_secret: str = ""
    reddit_username: str = ""
    reddit_user_agent: str = "web3-airdrop-alpha/1.0"
    reddit_timeout: int = 30
    reddit_retry: int = 3
    reddit_cron: str = "30 * * * *"
    medium_enabled: bool = True
    medium_timeout: int = 30
    medium_retry: int = 3
    medium_tags: str = "airdrop,web3,crypto"
    medium_cron: str = "0 */6 * * *"
    mirror_enabled: bool = True
    mirror_timeout: int = 30
    mirror_retry: int = 3
    mirror_cron: str = "30 */6 * * *"

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

    # ── OpenTelemetry 链路追踪 ────────────────────
    # 主开关：设为 true 则启用 OTel SDK + 自动埋点，通过 OTLP 导出到 OTel Collector
    otel_enabled: bool = False
    # 导出器端点（标准 OTEL_EXPORTER_OTLP_ENDPOINT 也生效，这里仅用于日志）
    otel_endpoint: str = "http://otel-collector:4317"
    # 服务名称（标准 OTEL_SERVICE_NAME 覆盖此值）
    otel_service_name: str = "airdrop-alpha"
    # 采样率，仅用于日志记录；实际采样由 SDK 环境变量 OTEL_TRACES_SAMPLER 控制
    otel_sample_rate: float = 1.0

    # ── 种子数据 ──────────────────────────────────
    # ⚠️ 这两个开关在**生产环境被强制关闭**（见文件末尾的生产自检）：
    # 默认 True 是为了本地开箱即演示，但生产环境开着它们会往真实库里灌
    # 8 个内置假项目（`source='seed'`、`fetched_at=NULL`），Dashboard 汇总
    # 会把它们算进去 —— 看起来像"已经采集过了"。
    #
    # 关键是**它们的失败方式是静默的**：不报错、不告警，只是让"采集全挂"
    # 这件事看起来像"系统在正常工作"。运维不会去查一个看起来有数据的系统。
    #
    # `seed_on_startup` / `seed_data_path` 目前**全仓没有任何代码读取**
    # （实测：除 config.py 的声明处外 0 处引用；启动灌种子靠手动跑
    # `scripts/seed.py`）。仍然保留并纳入生产自检，因为
    # `.env.example` 与 `configs/development/.env.development` 都在教人填它 ——
    # **一个能填但什么也不做的配置键，比缺一个更坏**：填的人以为生效了。
    # 真要删就得连模板、文档、部署脚本一起删，那是另一个 PR 的事。
    seed_on_startup: bool = True
    seed_data_path: str = "scripts/seed.py"
    # 外部采集源全量失败时回退到内置 seed 数据（§10.2 / V2 B2）
    seed_fallback_enabled: bool = True

    # ── 计算属性 ──────────────────────────────────
    @property
    def is_llm_enabled(self) -> bool:
        """LLM 是否启用（需配置至少一个接口的 API key + Feature Flag）。"""
        has_key = bool(self.openai_api_key)
        if not has_key:
            # 检查编号接口是否有 API key
            import os

            for i in range(1, 6):
                if os.environ.get(f"LLM_API_KEY_{i}", "").strip():
                    has_key = True
                    break
        return has_key and self.enable_llm_enhancement

    @property
    def llm_providers(self) -> list[dict[str, Any]]:
        """解析多接口配置，返回 provider 列表。

        每个接口一组编号环境变量：
            LLM_BASEURL_1, LLM_API_KEY_1, LLM_MODELS_1_1, LLM_MODELS_1_2, ...
            LLM_BASEURL_2, LLM_API_KEY_2, LLM_MODELS_2_1, ...

        返回格式：
            [{"base_url": ..., "api_key": ..., "name": "provider-1", "models": ["model1", "model2"]}, ...]

        未配置编号接口时，回退到单接口 OPENAI_API_KEY / OPENAI_BASE_URL / LLM_MODEL。
        """
        import os

        providers: list[dict[str, Any]] = []

        for i in range(1, 6):
            base_url = os.environ.get(f"LLM_BASEURL_{i}", "").strip()
            if not base_url:
                continue
            api_key = os.environ.get(f"LLM_API_KEY_{i}", "").strip()

            # 收集该接口下的所有模型（LLM_MODELS_{i}_1, LLM_MODELS_{i}_2, ...）
            models: list[str] = []
            for j in range(1, 6):
                model = os.environ.get(f"LLM_MODELS_{i}_{j}", "").strip()
                if model:
                    models.append(model)

            providers.append(
                {
                    "base_url": base_url,
                    "api_key": api_key,
                    "name": f"provider-{i}",
                    "models": models,
                }
            )

        if providers:
            return providers

        # 回退到单接口模式
        if self.openai_api_key:
            return [
                {
                    "base_url": self.openai_base_url,
                    "api_key": self.openai_api_key,
                    "name": "openai",
                    "models": [self.llm_model] if self.llm_model else [],
                }
            ]

        return []

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
    def _resolve_db_backend(self) -> Self:
        """DB_BACKEND=postgres 时自动组装 DATABASE_URL（A2, ADR-004）。

        两种 PG 激活路径：
        1. 直接设 DATABASE_URL=postgresql://…（已有行为，优先级最高）
        2. DB_BACKEND=postgres（验收标准用法）→ 从 POSTGRES_* 分项组装

        反向同步：若 DATABASE_URL 指向 PG 但 DB_BACKEND 未显式设为 postgres，
        自动修正 db_backend 以保持一致（is_postgres() 两端都对齐）。
        """
        url = (self.database_url or "").strip()
        is_pg_url = url.startswith("postgresql://") or url.startswith("postgres://")
        if self.db_backend == "postgres":
            if not url:
                self.database_url = (
                    f"postgresql://{self.postgres_user}:{self.postgres_password}"
                    f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
                )
        elif is_pg_url:
            self.db_backend = "postgres"
        return self

    @model_validator(mode="after")
    def validate_opportunity_economic_flag_rollout(self) -> Self:
        """Upstream economic rollout gates: evidence_emit⇒snapshot, resolver⇒evidence."""
        if self.opportunity_economic_evidence_emit_enabled and not self.opportunity_economic_snapshot_enabled:
            raise ValueError(
                "opportunity_economic_evidence_emit_enabled requires opportunity_economic_snapshot_enabled"
            )
        if self.opportunity_economic_resolver_enabled and not self.opportunity_economic_evidence_emit_enabled:
            raise ValueError(
                "opportunity_economic_resolver_enabled requires opportunity_economic_evidence_emit_enabled"
            )
        return self

    def model_post_init(self, __context: Any) -> None:
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
            # ── 种子数据：生产强制关闭，而不是"建议关闭" ──────────
            #
            # 为什么是强制改而不是拒绝启动：这两个开关的默认值 True 是为了本地
            # 开箱即演示，忘了改不代表配置**冲突**，只代表用了默认值。
            # 上面那几条（空 API_KEY、localhost CORS）拒绝启动是因为它们无法
            # 自动修正成一个正确的值 —— 密钥和域名只有部署者知道。
            # 种子开关不一样：生产环境的正确值只有一个，就是关。
            #
            # 这两个开关开着的危害不是"多了 8 条假数据"，而是**它让故障看起来
            # 像正常**：采集全挂时库里仍然有项目、Dashboard 仍然有数字，
            # 没人会去查一个看起来有数据的系统。
            # 静默的错误状态比明确的空状态坏得多。
            #
            # 强制关闭会被写回字段本身，所以 `/api/v1/settings/config` 回显的
            # 就是真实生效值 —— 不留"配置说开着、实际关着"的落差。
            self.seed_on_startup = False
            self.seed_fallback_enabled = False

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

            # P1-3：生产环境 AUTH_TOKEN_SECRET 必须设置（匿名 token 才稳定）
            if not self.auth_token_secret:
                errors.append(
                    "生产环境必须设置 AUTH_TOKEN_SECRET（匿名 token 每次重启后失效；"
                    "建议用 secrets.token_urlsafe(48) 生成固定值）"
                )

            # cors_origins 的默认值是 localhost（见字段定义）。生产忘配就会把真实
            # 前端域名全部挡在门外——表现为"上线后所有接口跨域失败"，而这种故障
            # 除了浏览器控制台几乎无迹可寻。宁可拒绝启动，也不要静默错配。
            localhost_origins = [o for o in self.cors_origins_list if "localhost" in o or "127.0.0.1" in o]
            if localhost_origins:
                errors.append(
                    "生产环境 CORS_ORIGINS 不能包含 localhost/127.0.0.1"
                    f"（当前 {', '.join(localhost_origins)}）——请设为实际前端域名"
                )

            if errors:
                raise ValueError("不安全的生产配置: " + "; ".join(errors))


# ── 全局配置单例 ──────────────────────────────────
settings = Settings()
