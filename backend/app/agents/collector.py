"""Collector Agent - Data collection and deduplication.

Collects projects from multiple sources, normalizes names/sectors,
deduplicates across sources, and generates deterministic UUIDs.

Reference:
- ENGINEERING_ROADMAP.md §6.2 Collector
- TASK_BREAKDOWN.md W2-03
- ADR-012-system-direction-auto-scan.md
"""

import json
import re
import time
from datetime import datetime
from typing import TYPE_CHECKING, Any

import structlog

from app.agents.base import AgentError, BaseAgent, PipelineState, RawProject
from app.collectors.noise import (
    is_listed_brand_subproduct,
    is_listed_token_no_airdrop_signals,
    is_noise_raw_project,
    is_tooling_repo,
)
from app.services.token_registry import RegistryIndex, registry_confirms_launch
from app.utils.normalize import (
    create_dedup_key,
    generate_deterministic_id,
    merge_raw_records,
    normalize_sector,
)

if TYPE_CHECKING:
    from app.collectors.base import CollectorResult
    from app.collectors.persistence import CollectionRepository
    from app.collectors.registry import CollectorRegistry

logger = structlog.get_logger(__name__)

# 归一化后代表"赛道未知"的键（create_dedup_key 对 None/空值归一到 "Unknown"）
_UNKNOWN_SECTOR_KEY = "Unknown"


def _fold_sectorless_groups(groups: dict[str, list[dict[str, Any]]]) -> dict[str, list[dict[str, Any]]]:
    """把"赛道未知"的分组并入同名且赛道已知的分组。

    dedup_key 是 `name::sector`。任务门户(galxe/layer3)、链上活动(etherscan)、
    推文(twitter)、行情(coingecko)这些**信号补充源**根本不掌握赛道，它们的记录
    只能落在 `name::Unknown` 上，与 defillama 给出的 `name::Lending` 永不相撞——
    真实库里 702 个项目 `source_count>=2` 的比例因此恒为 0%。

    这里在合并前做一次归并：若某个 `name::Unknown` 分组恰好只对应一个同名且赛道
    已知的分组，就并进去。**只在唯一匹配时归并**——同名但落在多个赛道时无从判断
    该归给谁，保持原样比猜错安全。
    """
    by_name: dict[str, list[str]] = {}
    for key_str in groups:
        name_key, _, sector_key = key_str.partition("::")
        if sector_key != _UNKNOWN_SECTOR_KEY:
            by_name.setdefault(name_key, []).append(key_str)

    folded = dict(groups)
    for key_str in list(folded):
        name_key, _, sector_key = key_str.partition("::")
        if sector_key != _UNKNOWN_SECTOR_KEY or not name_key:
            continue
        candidates = by_name.get(name_key) or []
        if len(candidates) != 1:
            continue
        target = candidates[0]
        folded[target] = folded[target] + folded.pop(key_str)
        logger.info("collector.dedup.folded_sectorless", name=name_key, into=target)
    return folded


# 文本融资信号：必须出现真实的融资语境，而非裸词 "funding"/"raised"。
# 反例（应判否）："hourly funding rate settlement"、"raised the block gas limit"。
_FUNDING_TEXT_RE = re.compile(
    r"""(
        raised\s+(?:\$|usd|us\$|€|£)?\s*[\d.,]+\s*(?:k|m|b|million|billion|万|亿)?  # raised $12M
        | (?:seed|pre-seed|angel|strategic|private)\s+round
        | series\s+[a-e]\b
        | funding\s+round
        | (?:closed|announced|secured|completed)\s+(?:a\s+|its\s+|our\s+)?
          (?:\$|usd)?\s*[\d.,]*\s*(?:k|m|b|million|billion)?\s*
          (?:seed|series|funding|round|financing|raise)
        | backed\s+by\s+(?:a16z|paradigm|sequoia|binance\s+labs|coinbase\s+ventures|polychain|multicoin)
        | (?:融资|轮融资|领投|种子轮|天使轮|战略投资)
    )""",
    re.IGNORECASE | re.VERBOSE,
)

# "空投已结束"的负向语境（2026-09 修复）：回顾性报道里 "airdrop" 同样与
# "snapshot"/"eligible" 共现（"符合条件的用户已领取"），不设此门会让
# 已发币项目借文本残留通过 is_listed_token_no_airdrop_signals 与
# eligibility veto。命中即认定该文本描述的是历史空投，非 upcoming 证据。
_AIRDROP_COMPLETED_RE = re.compile(
    r"""(
        airdrop\s+(?:has\s+been\s+|is\s+|was\s+|has\s+)?
        (?:completed|ended|concluded|closed|distributed|fully\s+claimed)
        | (?:completed|concluded|ended)\s+airdrop
        | airdrop\s+claim(?:s|\s+window|\s+period)?\s+(?:is\s+)?(?:closed|over|ended|concluded)
        | already\s+claimed
        | (?:空投|快照)\s*(?:已|完成|结束|结束领取|发放完毕)
    )""",
    re.IGNORECASE | re.VERBOSE,
)

# 官方否认发币/空投（ADR-015）。只认永久否定。
# "no token yet" / "there will be no token yet" / "还不会发币" 是「还没发」，
# 正是要找的机会，不能写成否认 —— 否则资格门会把真 FARM 打成 IGNORE。
_EXPLICIT_NO_AIRDROP_RE = re.compile(
    r"""(
        \b(?:no|not|never|without)\s+plans?\s+to\s+(?:ever\s+)?
          (?:launch|issue|have|introduce|release)\s+(?:a\s+|an\s+|any\s+)?
          (?:token|airdrop)\b(?!\s+yet\b)
      | \bwill\s+(?:not|never)\s+(?:launch|issue|have|introduce|do)\s+
          (?:a\s+|an\s+|any\s+)?(?:token|airdrop)\b(?!\s+yet\b)
      | \b(?:is\s+)?not\s+launching\s+(?:a\s+|an\s+)?(?:token|airdrop)\b(?!\s+yet\b)
      | \bthere\s+will\s+(?:be\s+no|never\s+be\s+(?:a|an))\s+
          (?:token|airdrop)\b(?!\s+yet\b)
      | \bno\s+intention\s+(?:of|to)\s+(?:launching|launch|issuing|issue)\s+
          (?:a\s+|an\s+)?(?:token|airdrop)\b(?!\s+yet\b)
      | \b(?:ruled|rules)\s+out\s+(?:a\s+|an\s+|any\s+)?(?:token|airdrop)\b
      | \bno\s+token\s+incentives?\b(?!\s+yet\b)
      | \b(?:remain|remains|remaining)\s+tokenless\b
      | \bintentionally\s+tokenless\b
      | (?<!目前)(?<![还暂未])不会发行代币
      | (?<!目前)(?<![还暂未])不会发币
      | (?<!目前)(?<![还暂未])不打算(?:发行)?(?:代币|空投)
      | (?:没有|无)发币计划
      | 不会(?:做|有)空投
      | 明确(?:否认|拒绝)(?:发币|空投|代币)
    )""",
    re.IGNORECASE | re.VERBOSE,
)


# 能对「已发币」给出正面证据的来源：上市行情源本身即证据；defillama 的
# no_token_yet=False 来自真实 ticker / gecko_id；manual/api/seed 是刻意断言。
# 严格积分证据（2026-10-08）：has_points_program 的宽松推断把 restaking / incentive /
# vaults / liquidity mining 都算作积分计划，20 个确认已发币的项目全靠这类通用词
# 躲过了 already_launched 否决与默认列表隐藏。已发币项目的「后续空投路径」只认
# 明确的积分措辞；宽松版保留给 airdrop_signal 子分，不改评分口径。
_POINTS_PHRASE_RE = re.compile(r"\bpoints?\s+(?:program|programme|system|campaign|season)s?\b")
_POINTS_WORD_RE = re.compile(r"\bpoints\b")
_POINTS_CONTEXT_RE = re.compile(r"\b(?:airdrops?|loyalty|rewards?|portals?)\b")
# defillama 采集器自己用宽松关键词（staking / vault / rewards…）写 has_points_program，
# 它的显式值不能当严格证据。
_LOOSE_POINTS_SOURCES = frozenset({"defillama"})


def _infer_explicit_points_program(source_id: str, raw_data: dict[str, Any], text: str, *, completed: bool) -> bool:
    """明确的积分计划证据：显式字段，或「points program / points + airdrop·rewards」措辞。"""
    if raw_data.get("explicit_points_program") is not None:
        return bool(raw_data["explicit_points_program"])
    if source_id not in _LOOSE_POINTS_SOURCES and raw_data.get("has_points_program") is not None:
        return bool(raw_data["has_points_program"])
    if completed:
        return False
    return bool(_POINTS_PHRASE_RE.search(text) or (_POINTS_WORD_RE.search(text) and _POINTS_CONTEXT_RE.search(text)))


_LAUNCH_EVIDENCE_SOURCES = frozenset({"manual", "api", "seed", "defillama", "coingecko", "cryptorank", "etherscan"})
_SYMBOL_PLACEHOLDERS = frozenset({"", "-", "--", "n/a", "none", "null"})
_ROOTDATA_LAUNCHED_STATUS = frozenset({"listed", "issued", "launched", "tge", "trading", "yes"})


def _infer_token_launch_confirmed(source_id: str, raw_data: dict[str, Any], *, no_token: bool) -> bool:
    """是否有**正面证据**表明代币已发行（2026-10-08，ADR-015 补充）。

    no_token_yet=False 只说明「没确认未发币」：RootData 只在明确写了未发币时
    才置 True，token 字段为空也落到 False。把这当成已发币，会把 token_symbol
    为空的早期项目（Bloctopus / Pier Two / Project Eleven……）打成已发币。
    显式字段优先；其余按来源取证据。
    """
    if "token_launch_confirmed" in raw_data and raw_data["token_launch_confirmed"] is not None:
        return bool(raw_data["token_launch_confirmed"]) and not no_token
    if no_token:
        return False
    name = str(raw_data.get("name") or raw_data.get("full_name") or "")
    if is_listed_brand_subproduct(name=name, slug=str(raw_data.get("slug") or "")):
        return True
    if source_id in _LAUNCH_EVIDENCE_SOURCES:
        return True
    if source_id == "rootdata":
        symbol = str(raw_data.get("token_symbol") or raw_data.get("symbol") or "").strip().lower()
        status = str(raw_data.get("token_status") or "").strip().lower()
        tge = raw_data.get("tge")
        return (
            symbol not in _SYMBOL_PLACEHOLDERS or status in _ROOTDATA_LAUNCHED_STATUS or tge in (True, "true", 1, "1")
        )
    # github / 文本类来源 / 任务门户：给不出发币证据，状态未知
    return False


class CollectorAgent(BaseAgent):
    """Collector Agent - MVP implementation.

    Collects projects from seed data (MVP) or external sources (V2).
    Normalizes, deduplicates, and assigns deterministic UUIDs.

    MVP: Uses seed data from config/database
    V2: Fetches from DefiLlama, CryptoRank, Twitter
    """

    def __init__(self) -> None:
        super().__init__("collector")

    def _raw_to_record(self, raw: dict[str, Any]) -> dict[str, Any]:
        """Normalize a raw seed/API record and assign deterministic project_id."""
        name = raw.get("name", "")
        sector = raw.get("sector")
        dedup_key = create_dedup_key(name, sector)
        project_id = generate_deterministic_id(dedup_key)
        ext = self._infer_airdrop_flags(str(raw.get("source") or "seed"), raw)
        return {
            "project_id": project_id,
            "name": name,
            "url": raw.get("url"),
            "sector": normalize_sector(sector) if sector else None,
            "stage": raw.get("stage") or ext.get("stage"),
            "source": raw.get("source", "seed"),
            "has_testnet": bool(raw.get("has_testnet", ext.get("has_testnet", False))),
            "has_points_program": bool(raw.get("has_points_program", ext.get("has_points_program", False))),
            "explicit_points_program": ext.get("explicit_points_program"),
            "no_token_yet": bool(raw.get("no_token_yet", ext.get("no_token_yet", False))),
            "token_launch_confirmed": ext.get("token_launch_confirmed"),
            "recent_funding": bool(raw.get("recent_funding", ext.get("recent_funding", False))),
            "has_docs": bool(ext.get("has_docs", False)),
            "has_whitepaper": bool(ext.get("has_whitepaper", False)),
            "has_roadmap": bool(ext.get("has_roadmap", False)),
            "has_github": bool(ext.get("has_github", False)),
            "has_twitter": bool(ext.get("has_twitter", False)),
            "has_discord": bool(ext.get("has_discord", False)),
            "github_stars": int(ext.get("github_stars") or 0),
            "github_recent_push_days": ext.get("github_recent_push_days"),
            "explicit_airdrop_mention": bool(ext.get("explicit_airdrop_mention", False)),
            "explicit_no_airdrop": bool(ext.get("explicit_no_airdrop", False)),
            "tvl_usd": ext.get("tvl_usd"),
            "description": ext.get("description"),
            "has_task_portal": bool(ext.get("has_task_portal", False)),
            "has_contract": bool(ext.get("has_contract", False)),
            "source_count": int(ext.get("source_count") or 1),
            "roadmap_delivery": ext.get("roadmap_delivery") or "unknown",
            "sybil_friction": ext.get("sybil_friction") or "unknown",
            "points_season_count": ext.get("points_season_count"),
            "tge_clarity": ext.get("tge_clarity") or "unannounced",
            "is_perp": bool(ext.get("is_perp", False)),
            "funding_total_usd": ext.get("funding_total_usd"),
            "funding_rounds": int(ext.get("funding_rounds") or 0),
            "funding_last_date": ext.get("funding_last_date"),
            "funding_investors": list(ext.get("funding_investors") or []),
            "funding_lead_investors": list(ext.get("funding_lead_investors") or []),
            "funding_tier": ext.get("funding_tier") or "unknown",
            "funding_quality": float(ext.get("funding_quality") or 0),
            "discovery_score": raw.get("discovery_score", 0.0),
            "auto_discovered": raw.get("auto_discovered", False),
            "discovered_at": raw.get("discovered_at"),
            "_dedup_key": dedup_key,
        }

    @staticmethod
    def _infer_airdrop_flags(source_id: str, raw_data: dict[str, Any]) -> dict[str, Any]:
        """Map collector raw_data → scoring flags used by Scorer/Risk.

        DefiLlama unlisted protocols should set no_token_yet; GitHub text
        may hint testnet/points. Explicit fields in raw_data always win.

        v1.2 also infers docs/social/repo health for execution & transparency.
        """
        from datetime import UTC, datetime

        stage = (raw_data.get("stage") or "").lower()
        text = " ".join(
            str(raw_data.get(k) or "")
            for k in (
                "name",
                "description",
                # 推文正文存在 raw_data["text"]，此前不在取值范围内，
                # 于是两个 twitter 采集器（它们只有这一个载荷）贡献恒为零
                "text",
                "summary",
                "one_liner",
                "full_name",
                "slug",
                "category",
                "homepage",
                "url",
                "twitter",
                "github",
                "docs",
            )
        ).lower()

        def _explicit(key: str) -> bool | None:
            if key not in raw_data:
                return None
            return bool(raw_data.get(key))

        no_token = _explicit("no_token_yet")
        has_testnet = _explicit("has_testnet")
        has_points = _explicit("has_points_program")
        recent_funding = _explicit("recent_funding")

        # Source-aware defaults when flags missing
        if no_token is None:
            if source_id == "defillama":
                # 与 DefiLlamaCollector._is_unlisted 保持同一口径：真实 ticker 是
                # 已发币的正面证据，而 "-" 是 DefiLlama 表示"无代币"的哨兵值。
                # 两处不一致会让回填/重算写出与采集时相反的 no_token_yet。
                symbol = str(raw_data.get("symbol") or "").strip()
                if symbol and symbol not in {"-", "--", "n/a", "none"}:
                    no_token = False
                else:
                    no_token = not raw_data.get("gecko_id")
            elif source_id in ("coingecko", "cryptorank"):
                no_token = False
            elif source_id == "github":
                # 仓库文本给不出发币证据：此前 "airdrop" 一词就推出 no_token_yet，
                # 撸毛脚本因此全被当成 pre-TGE。现在只认已发币品牌名单这一条
                # 反证，其余保持中性（github 不参与 merge 的 token 状态投票）。
                repo_name = str(raw_data.get("name") or raw_data.get("full_name") or "")
                no_token = not is_listed_brand_subproduct(name=repo_name)
            else:
                no_token = False

        if has_testnet is None:
            has_testnet = stage == "testnet" or "testnet" in text

        completed_airdrop = bool(_AIRDROP_COMPLETED_RE.search(text))

        if has_points is None:
            has_points = not completed_airdrop and (
                "points program" in text
                or "points system" in text
                or "point system" in text
                or (
                    "points" in text
                    and ("airdrop" in text or "loyalty" in text or "reward" in text or "portal" in text)
                )
                or "incentive" in text
                or "restaking" in text
                or "stakers" in text
                or "staking rewards" in text
                or "vaults" in text
                or "liquidity mining" in text
            )

        if recent_funding is None:
            # 裸 "funding" / "raised" 会把 "hourly funding rate settlement"、
            # "raised the block gas limit" 之类的技术描述误判为融资信号。
            # 要求出现真正的融资语境词组。
            recent_funding = bool(_FUNDING_TEXT_RE.search(text))

        if not stage and source_id == "github":
            stage = "ideation"
        if not stage and source_id == "defillama":
            stage = raw_data.get("stage") or "mainnet"

        # ── v1.2 extended signals ──
        has_whitepaper = bool(
            raw_data.get("has_whitepaper") or "whitepaper" in text or "litepaper" in text or "white paper" in text
        )
        has_docs = bool(
            raw_data.get("has_docs")
            or has_whitepaper
            or "docs." in text
            or "documentation" in text
            or "/docs" in text
            or "gitbook" in text
            or raw_data.get("docs")
        )
        has_roadmap = bool(
            raw_data.get("has_roadmap") or "roadmap" in text or "milestones" in text or "timeline" in text
        )
        has_github = bool(
            raw_data.get("has_github")
            or raw_data.get("github")
            or raw_data.get("full_name")
            or source_id == "github"
            or "github.com" in text
        )
        has_twitter = bool(
            raw_data.get("has_twitter")
            or raw_data.get("twitter")
            or "twitter.com" in text
            or "x.com/" in text
            or source_id in ("twitter", "twitter_kol", "twitter_keyword")
        )
        has_discord = bool(
            raw_data.get("has_discord") or raw_data.get("discord") or "discord.gg" in text or "discord.com" in text
        )
        # 已结束的空投不是 upcoming 证据：先做负向门控，再匹配正向措辞。
        # 显式字段（raw_data["explicit_airdrop_mention"]）不受门控影响——
        # 刻意输入的断言优先于文本推断。
        explicit_airdrop = bool(
            raw_data.get("explicit_airdrop_mention")
            or (
                not completed_airdrop
                and (
                    "airdrop confirmed" in text
                    or "confirmed airdrop" in text
                    or "official airdrop" in text
                    or "token generation event" in text
                    or "tge soon" in text
                    or ("airdrop" in text and ("snapshot" in text or "eligible" in text))
                )
            )
        )
        if "explicit_no_airdrop" in raw_data:
            explicit_no_airdrop = bool(raw_data.get("explicit_no_airdrop"))
        else:
            explicit_no_airdrop = bool(_EXPLICIT_NO_AIRDROP_RE.search(text))

        # Verifiable task / quest / points portal (not just wording)
        has_task_portal = bool(
            raw_data.get("has_task_portal")
            or source_id in ("galxe", "layer3")
            or "galxe.com" in text
            or "layer3.xyz" in text
            or "zealy.io" in text
            or "questn.com" in text
            or "crew3" in text
            or "taskon" in text
            or "intract.io" in text
            or "quest." in text
            or "/quests" in text
            or "campaign portal" in text
            or ("points" in text and ("portal" in text or "dashboard" in text or "app." in text))
        )

        has_contract = bool(
            raw_data.get("has_contract")
            or raw_data.get("address")
            or raw_data.get("contract_address")
            or source_id == "etherscan"
            or "etherscan.io/address" in text
            or ("0x" in text and "contract" in text)
            or (tvl := raw_data.get("tvl") or raw_data.get("tvl_usd")) not in (None, 0, "0")
        )

        # Sybil friction: higher = harder to farm with many wallets (good for real users)
        sybil_friction = str(raw_data.get("sybil_friction") or "unknown").lower()
        if sybil_friction not in ("high", "medium", "low", "unknown"):
            sybil_friction = "unknown"
        if sybil_friction == "unknown":
            if any(
                k in text
                for k in (
                    "kyc",
                    "identity verification",
                    "passport",
                    "unique human",
                    "proof of humanity",
                    "gitcoin passport",
                    "world id",
                    "biometric",
                )
            ):
                sybil_friction = "high"
            elif any(
                k in text
                for k in (
                    "wallet screening",
                    "sybil",
                    "anti-sybil",
                    "one wallet",
                    "social account required",
                    "discord verify",
                    "twitter verify",
                )
            ):
                sybil_friction = "medium"
            elif has_points or has_task_portal:
                # open points campaigns are often easy to multi-wallet
                sybil_friction = "low"

        stars = raw_data.get("stars") or raw_data.get("stargazers_count") or raw_data.get("github_stars") or 0
        try:
            github_stars = int(stars)
        except (TypeError, ValueError):
            github_stars = 0

        push_days = raw_data.get("github_recent_push_days")
        if push_days is None:
            # pushed_at 优先：updated_at 会被 star/watch/改描述顶新，用它衡量
            # "代码是否还在推进"会把元数据churn 当成开发活跃度
            for key in ("pushed_at", "updated_at", "last_updated"):
                val = raw_data.get(key)
                if not val:
                    continue
                try:
                    if isinstance(val, str):
                        dt = datetime.fromisoformat(val.replace("Z", "+00:00"))
                    else:
                        continue
                    push_days = max(0, (datetime.now(UTC) - dt).days)
                    break
                except (TypeError, ValueError) as exc:
                    logger.debug("collector.invalid_push_timestamp", value=val, error=str(exc))
                    continue

        tvl = raw_data.get("tvl") or raw_data.get("tvl_usd")
        try:
            tvl_usd = float(tvl) if tvl is not None else None
        except (TypeError, ValueError):
            tvl_usd = None

        description = raw_data.get("description") or raw_data.get("about")

        # Lightweight roadmap delivery: does shipping signal align with claimed stage?
        roadmap_delivery = str(raw_data.get("roadmap_delivery") or "unknown").lower()
        if roadmap_delivery not in ("aligned", "partial", "unclear", "unknown"):
            roadmap_delivery = "unknown"
        if roadmap_delivery == "unknown":
            stage_l = (stage or "").lower()
            shipping = bool(
                has_testnet
                or stage_l in ("testnet", "mainnet", "growth")
                or (tvl_usd is not None and tvl_usd > 0)
                or (push_days is not None and push_days <= 45)
            )
            if has_roadmap and shipping:
                roadmap_delivery = "aligned"
            elif has_roadmap and not shipping and stage_l in ("ideation", ""):
                roadmap_delivery = "unclear"  # paper roadmap only
            elif has_roadmap:
                roadmap_delivery = "partial"
            elif shipping and (has_github or tvl_usd):
                roadmap_delivery = "partial"  # shipping without public roadmap text
            else:
                roadmap_delivery = "unknown"

        # source_count filled at merge time; single-source default 1
        source_count = int(raw_data.get("source_count") or 1)

        # ── v2.0 结构化 Anti-PUA 信号（app.opportunity.evidence 消费）──
        # 推断词表唯一来源是 services.structured_signals（与存量回填脚本同源）。
        # 显式字段优先；缺失时：is_perp 高置信直接写 True；tge 仅 confirmed
        # 有可靠词形；season 低置信不自动写（与回填脚本的审核清单策略一致）。
        from app.services.structured_signals import extract_is_perp, extract_tge_clarity

        sector_text = str(raw_data.get("sector") or "")
        description_text = str(raw_data.get("description") or raw_data.get("about") or "")
        is_perp = bool(raw_data.get("is_perp")) or extract_is_perp(sector_text, description_text)
        raw_tge = raw_data.get("tge_clarity")
        if isinstance(raw_tge, str) and raw_tge in ("confirmed_quarter", "vague_soon", "unannounced"):
            tge_clarity = raw_tge
        else:
            tge_clarity = extract_tge_clarity(f"{sector_text} {description_text}".lower()) or "unannounced"
        raw_season = raw_data.get("points_season_count")
        if isinstance(raw_season, int) and not isinstance(raw_season, bool) and 1 <= raw_season <= 10:
            points_season_count: int | None = raw_season
        else:
            points_season_count = None  # 低置信：文本推断的季数不自动采信

        # Funding quality (RootData / CryptoRank / manual)
        from app.services.funding import extract_funding_from_raw

        funding = extract_funding_from_raw(raw_data)
        if funding.get("funding_quality", 0) > 0.2:
            recent_funding = True

        return {
            "has_testnet": bool(has_testnet),
            "has_points_program": bool(has_points),
            "explicit_points_program": _infer_explicit_points_program(
                source_id, raw_data, text, completed=completed_airdrop
            ),
            "no_token_yet": bool(no_token),
            "token_launch_confirmed": _infer_token_launch_confirmed(source_id, raw_data, no_token=bool(no_token)),
            "recent_funding": bool(recent_funding),
            "stage": stage or raw_data.get("stage"),
            "has_docs": bool(has_docs),
            "has_whitepaper": bool(has_whitepaper),
            "has_roadmap": bool(has_roadmap),
            "has_github": bool(has_github),
            "has_twitter": bool(has_twitter),
            "has_discord": bool(has_discord),
            "github_stars": github_stars,
            "github_recent_push_days": push_days,
            "explicit_airdrop_mention": bool(explicit_airdrop),
            "explicit_no_airdrop": bool(explicit_no_airdrop),
            "tvl_usd": tvl_usd,
            "description": description,
            "has_task_portal": bool(has_task_portal),
            "has_contract": bool(has_contract),
            "source_count": source_count,
            "roadmap_delivery": roadmap_delivery,
            "sybil_friction": sybil_friction,
            "points_season_count": points_season_count,
            "tge_clarity": tge_clarity,
            "is_perp": is_perp,
            "funding_total_usd": funding.get("funding_total_usd"),
            "funding_rounds": int(funding.get("funding_rounds") or 0),
            "funding_last_date": funding.get("funding_last_date"),
            "funding_investors": list(funding.get("funding_investors") or []),
            "funding_lead_investors": list(funding.get("funding_lead_investors") or []),
            "funding_tier": funding.get("funding_tier") or "unknown",
            "funding_quality": float(funding.get("funding_quality") or 0),
        }

    def _dedup_records(self, records: list[dict[str, Any]]) -> list[RawProject]:
        """Group records by dedup key, merge conflicts, and return RawProjects."""
        groups: dict[str, list[dict[str, Any]]] = {}
        for rec in records:
            key = rec.pop("_dedup_key")
            key_str = key.to_string()
            groups.setdefault(key_str, []).append(rec)

        groups = _fold_sectorless_groups(groups)

        results: list[RawProject] = []
        for key_str, items in groups.items():
            merged = merge_raw_records(items, source_key="source")
            canonical = create_dedup_key(merged.get("name", ""), merged.get("sector"))
            # project_id 必须与合并后的 (name, sector) 一致。
            # merged["project_id"] 来自优先级最高的那条记录，而 sector 走的是
            # "最高可信已知值"——两者可能来自不同记录。归并了无赛道记录之后尤其
            # 容易错位：id 还挂在 name::Unknown 上，sector 却已是 Lending，于是
            # 同一真实项目多出一行，且 mark_raw_project_processed 的 dedup_key
            # 回退（create_dedup_key(name, sector)）也对不上。
            expected_id = generate_deterministic_id(canonical)
            project_id = merged.get("project_id")
            if not project_id or (key_str != canonical.to_string() and project_id != expected_id):
                project_id = expected_id

            if len(items) > 1:
                logger.info(
                    "collector.dedup",
                    project_id=project_id,
                    name=merged.get("name"),
                    dedup_key=key_str,
                    sources=merged.get("source"),
                    duplicates=len(items),
                )

            raw_ids: list[str] = []
            for item in items:
                rid = item.get("raw_id")
                if rid:
                    raw_ids.append(str(rid))
            for rid in merged.get("raw_ids") or []:
                if rid and rid not in raw_ids:
                    raw_ids.append(str(rid))

            results.append(
                RawProject(
                    id=project_id,
                    name=merged.get("name", ""),
                    url=merged.get("url"),
                    sector=merged.get("sector"),
                    stage=merged.get("stage"),
                    source=merged.get("source", "unknown"),
                    has_testnet=bool(merged.get("has_testnet", False)),
                    has_points_program=bool(merged.get("has_points_program", False)),
                    explicit_points_program=(
                        None
                        if merged.get("explicit_points_program") is None
                        else bool(merged["explicit_points_program"])
                    ),
                    no_token_yet=bool(merged.get("no_token_yet", False)),
                    token_launch_confirmed=(
                        None if merged.get("token_launch_confirmed") is None else bool(merged["token_launch_confirmed"])
                    ),
                    recent_funding=bool(merged.get("recent_funding", False)),
                    has_docs=bool(merged.get("has_docs", False)),
                    has_whitepaper=bool(merged.get("has_whitepaper", False)),
                    has_roadmap=bool(merged.get("has_roadmap", False)),
                    has_github=bool(merged.get("has_github", False)),
                    has_twitter=bool(merged.get("has_twitter", False)),
                    has_discord=bool(merged.get("has_discord", False)),
                    github_stars=int(merged.get("github_stars") or 0),
                    github_recent_push_days=merged.get("github_recent_push_days"),
                    explicit_airdrop_mention=bool(merged.get("explicit_airdrop_mention", False)),
                    explicit_no_airdrop=bool(merged.get("explicit_no_airdrop", False)),
                    tvl_usd=merged.get("tvl_usd"),
                    description=merged.get("description"),
                    has_task_portal=bool(merged.get("has_task_portal", False)),
                    has_contract=bool(merged.get("has_contract", False)),
                    # 取"显式 source_count"与"source 串里的去重源数"的较大者。
                    # 原写法 `int(...) or len(...)` 在 source_count==1 时短路，
                    # 而 _infer_airdrop_flags 恒返回 1，导致多源交叉验证加成永不触发。
                    source_count=max(
                        1,
                        int(merged.get("source_count") or 0),
                        len({s.strip() for s in str(merged.get("source") or "unknown").split(",") if s.strip()}),
                    ),
                    roadmap_delivery=str(merged.get("roadmap_delivery") or "unknown"),
                    sybil_friction=str(merged.get("sybil_friction") or "unknown"),
                    points_season_count=merged.get("points_season_count"),
                    tge_clarity=str(merged.get("tge_clarity") or "unannounced"),
                    is_perp=bool(merged.get("is_perp", False)),
                    funding_total_usd=merged.get("funding_total_usd"),
                    funding_rounds=int(merged.get("funding_rounds") or 0),
                    funding_last_date=merged.get("funding_last_date"),
                    funding_investors=list(merged.get("funding_investors") or [])
                    if isinstance(merged.get("funding_investors"), list)
                    else [],
                    funding_lead_investors=list(merged.get("funding_lead_investors") or [])
                    if isinstance(merged.get("funding_lead_investors"), list)
                    else [],
                    funding_tier=str(merged.get("funding_tier") or "unknown"),
                    funding_quality=float(merged.get("funding_quality") or 0),
                    discovery_source=merged.get("discovery_source") or merged.get("source", "unknown").split(",")[0],
                    auto_discovered=bool(merged.get("auto_discovered", False)),
                    discovered_at=merged.get("discovered_at"),
                    discovery_score=float(merged.get("discovery_score", 0.0)),
                    raw_ids=raw_ids,
                )
            )

        return results

    async def collect_from_registry(
        self,
        registry: "CollectorRegistry",
        repo: "CollectionRepository | None" = None,
    ) -> list[RawProject]:
        """Collect from all enabled collectors in registry.

        Args:
            registry: CollectorRegistry with registered collectors
            repo: Optional repository to persist raw results

        Returns:
            List of merged RawProject objects
        """
        logger.info("collector.registry.started", collector_count=len(registry.list_enabled()))
        start_time = time.time()

        records: list[dict[str, Any]] = []
        for collector in registry.list_enabled():
            try:
                result: CollectorResult = await collector.collect()
                for discovery in result.items:
                    raw_data = discovery.raw_data or {}
                    airdrop_signals = raw_data.get("airdrop_signals", {})
                    records.append(
                        {
                            "project_id": discovery.project_id,
                            "name": discovery.name,
                            "url": discovery.url,
                            "sector": normalize_sector(discovery.sector) if discovery.sector else None,
                            "stage": discovery.stage,
                            "source": discovery.source_id,
                            "has_testnet": airdrop_signals.get("has_testnet", False),
                            "has_points_program": airdrop_signals.get("has_points_program", False),
                            "no_token_yet": airdrop_signals.get("no_token_yet", False),
                            "recent_funding": airdrop_signals.get("recent_funding", False),
                            "discovery_score": discovery.discovery_score,
                            "auto_discovered": True,
                            "discovered_at": discovery.discovered_at,
                            "_dedup_key": create_dedup_key(discovery.name, discovery.sector),
                        }
                    )
                if repo is not None:
                    repo.persist_collection_result(result)
            except Exception as e:
                logger.error(
                    "collector.registry.error",
                    source_id=collector.source_id,
                    error=str(e),
                )

        projects = self._dedup_records(records)
        duration_ms = (time.time() - start_time) * 1000
        logger.info(
            "collector.registry.completed",
            input_count=len(records),
            output_count=len(projects),
            deduped=len(records) - len(projects),
            duration_ms=round(duration_ms, 2),
        )
        return projects

    def _quarantine_row(
        self,
        repo: "CollectionRepository",
        row: dict[str, Any],
        reason: str,
    ) -> str | None:
        """隔离一条原始记录并让它离开待分析队列。

        隔离写库失败时退化为直接标记 processed —— 坏行绝不能留在
        `get_unprocessed_raw_projects` 的结果里，否则每轮调度都会撞上同一行
        （队列中毒，2026-08-30 修复）。成功隔离返回 None，失败返回原因描述。

        成功/失败日志由调用方按各自的事件名记录 —— 事件名必须是调用点的
        字面量：OBSERVABILITY.md 的 parity 门禁静态扫描
        `logger.xxx("<事件名>")`（test_observability_doc_parity），
        经参数传进来的变量名扫不出来。
        """
        # Prefer same DB connection as repository (in-memory tests)
        repo_conn = getattr(repo, "_conn", None)
        try:
            from app.quarantine import quarantine_raw

            ok = quarantine_raw(row["raw_id"], reason, conn=repo_conn)
            if not ok:
                repo.mark_raw_project_processed(
                    raw_id=row["raw_id"],
                    project_id=row.get("project_id"),
                )
                return "quarantine_raw 返回 False（已退化标记 processed）"
            return None
        except Exception as e:
            try:
                repo.mark_raw_project_processed(
                    raw_id=row["raw_id"],
                    project_id=row.get("project_id"),
                )
            except Exception as e2:
                logger.warning(
                    "collector.quarantine_mark_failed",
                    raw_id=row.get("raw_id"),
                    reason=reason,
                    error=str(e2),
                )
            return str(e)

    def collect_from_repository(
        self,
        repo: "CollectionRepository",
        min_discovery_score: float = 0.3,
        limit: int = 100,
    ) -> list[RawProject]:
        """Collect unprocessed raw projects from repository.

        Args:
            repo: CollectionRepository to read raw_projects table
            min_discovery_score: Minimum discovery score to include
            limit: Maximum number of records to read

        Returns:
            List of merged RawProject objects
        """
        logger.info(
            "collector.repository.started",
            min_discovery_score=min_discovery_score,
            limit=limit,
        )
        start_time = time.time()

        # Over-fetch so denylist skips still leave enough for analysis
        fetch_limit = max(limit * 3, limit)
        rows = repo.get_unprocessed_raw_projects(
            min_discovery_score=min_discovery_score,
            limit=fetch_limit,
        )

        records: list[dict[str, Any]] = []
        noise_skipped = 0
        # 发币核实用的 CoinGecko 币表（2026-10-08）。表为空时核实不生效。
        registry = repo.load_token_registry() if rows else RegistryIndex()
        # limit 约束的是**项目数**而非原始行数。此前按 records 长度截断，而
        # `_corroborating_rows` 追加的低分佐证记录排在列表末尾，于是只要过线的
        # 主记录本身就有 limit 条，佐证记录一条都到不了——跨源合并依旧不发生。
        accepted_keys: set[str] = set()
        for row in rows:
            row_key = str(row.get("dedup_key") or row.get("raw_id") or "")
            if row_key not in accepted_keys and len(accepted_keys) >= limit:
                # 用 continue 而非 break：佐证记录（低分、同 dedup_key）被追加在
                # 列表末尾，一旦 break 就永远扫不到它们。已达 limit 时只是不再
                # 接纳**新项目**，仍继续为已接纳的项目收集佐证。
                continue
            try:
                raw_data = json.loads(row["raw_data"]) if row["raw_data"] else {}
            except (ValueError, TypeError) as e:
                # 队列中毒防护：一条损坏的 raw_data 曾让整批 collect 抛异常，
                # 而该行 processed=0 + ORDER BY discovery_score DESC 会每轮
                # 重新被取到，流水线永久卡死（只能手工修库）。隔离 + 放行。
                logger.warning(
                    "collector.corrupt_raw_data",
                    raw_id=row.get("raw_id"),
                    source_id=row.get("source_id"),
                    error=str(e),
                )
                err = self._quarantine_row(repo, row, f"corrupt_raw_data:{row.get('source_id')}")
                if err is not None:
                    logger.warning(
                        "collector.corrupt_row_quarantine_failed",
                        raw_id=row.get("raw_id"),
                        error=err,
                    )
                continue
            source_id = row["source_id"]
            name = raw_data.get("name", "") or ""
            sector = raw_data.get("sector")
            # 撸毛脚本 / bot / 水龙头仓库不是项目（2026-10-06）。采集器已在源头
            # 过滤，这里兜住过滤上线前就进了队列的存量 github 行。
            is_tooling = source_id == "github" and is_tooling_repo(
                name=name,
                description=str(raw_data.get("description") or ""),
                topics=raw_data.get("topics"),
            )
            if is_tooling or is_noise_raw_project(name, sector, raw_data):
                noise_skipped += 1
                reason_kind = "tooling_repo" if is_tooling else "denylist"
                err = self._quarantine_row(repo, row, f"{reason_kind}:{source_id}:{name[:80]}")
                if err is None:
                    logger.info(
                        "collector.noise_quarantined",
                        name=name,
                        source_id=source_id,
                        raw_id=row.get("raw_id"),
                        reason=reason_kind,
                    )
                else:
                    logger.warning(
                        "collector.noise_quarantined.quarantine_failed",
                        raw_id=row.get("raw_id"),
                        error=err,
                    )
                continue

            flags = self._infer_airdrop_flags(source_id, raw_data)
            if registry_confirms_launch(
                registry,
                name=name,
                symbol=raw_data.get("token_symbol") or raw_data.get("symbol"),
                no_token_yet=flags["no_token_yet"],
                token_launch_confirmed=flags["token_launch_confirmed"],
            ):
                flags["token_launch_confirmed"] = True

            # 入库门：已发币且没有后续空投路径（points / quest portal / 明确空投
            # 措辞）的项目不进 projects。testnet 不算后续路径 —— 与 ADR-015
            # already_launched 否决同一口径（2026-10-06）。
            if is_listed_token_no_airdrop_signals(
                no_token_yet=flags["no_token_yet"],
                has_points_program=flags["has_points_program"],
                explicit_points_program=flags["explicit_points_program"],
                has_task_portal=flags.get("has_task_portal", False),
                explicit_airdrop_mention=flags.get("explicit_airdrop_mention", False),
                source_id=source_id,
                token_launch_confirmed=flags["token_launch_confirmed"],
            ):
                noise_skipped += 1
                # Quarantine same as noise
                err = self._quarantine_row(repo, row, f"listed_token_no_airdrop:{source_id}:{name[:80]}")
                if err is None:
                    logger.info(
                        "collector.listed_token_filtered",
                        name=name,
                        source_id=source_id,
                        raw_id=row.get("raw_id"),
                    )
                else:
                    logger.warning(
                        "collector.listed_token_filtered.quarantine_failed",
                        raw_id=row.get("raw_id"),
                        error=err,
                    )
                continue

            discovered_at = row["discovered_at"]
            if isinstance(discovered_at, str):
                try:
                    discovered_at = datetime.fromisoformat(discovered_at)
                except ValueError as e:
                    # 同队列中毒防护：解析不了的 discovered_at 会让整批抛异常，
                    # 该行又永远留在队列头 —— 隔离后继续，不让一行坏数据
                    # 卡死整条流水线。
                    logger.warning(
                        "collector.corrupt_discovered_at",
                        raw_id=row.get("raw_id"),
                        source_id=source_id,
                        error=str(e),
                    )
                    err = self._quarantine_row(repo, row, f"corrupt_discovered_at:{source_id}")
                    if err is not None:
                        logger.warning(
                            "collector.corrupt_row_quarantine_failed",
                            raw_id=row.get("raw_id"),
                            error=err,
                        )
                    continue

            dedup = create_dedup_key(name, sector)
            project_id = row.get("project_id") or generate_deterministic_id(dedup)
            accepted_keys.add(row_key)
            records.append(
                {
                    "project_id": project_id,
                    "raw_id": row["raw_id"],
                    "name": name,
                    "url": raw_data.get("url") or raw_data.get("homepage"),
                    "sector": normalize_sector(sector) if sector else None,
                    "stage": raw_data.get("stage") or flags.get("stage"),
                    "source": source_id,
                    "has_testnet": flags["has_testnet"],
                    "has_points_program": flags["has_points_program"],
                    "explicit_points_program": flags["explicit_points_program"],
                    "no_token_yet": flags["no_token_yet"],
                    "token_launch_confirmed": flags["token_launch_confirmed"],
                    "recent_funding": flags["recent_funding"],
                    "has_docs": flags.get("has_docs", False),
                    "has_whitepaper": flags.get("has_whitepaper", False),
                    "has_roadmap": flags.get("has_roadmap", False),
                    "has_github": flags.get("has_github", False),
                    "has_twitter": flags.get("has_twitter", False),
                    "has_discord": flags.get("has_discord", False),
                    "github_stars": flags.get("github_stars") or 0,
                    "github_recent_push_days": flags.get("github_recent_push_days"),
                    "explicit_airdrop_mention": flags.get("explicit_airdrop_mention", False),
                    "explicit_no_airdrop": flags.get("explicit_no_airdrop", False),
                    "tvl_usd": flags.get("tvl_usd"),
                    "description": flags.get("description"),
                    "has_task_portal": flags.get("has_task_portal", False),
                    "has_contract": flags.get("has_contract", False),
                    "source_count": flags.get("source_count") or 1,
                    "roadmap_delivery": flags.get("roadmap_delivery") or "unknown",
                    "sybil_friction": flags.get("sybil_friction") or "unknown",
                    "funding_total_usd": flags.get("funding_total_usd"),
                    "funding_rounds": flags.get("funding_rounds") or 0,
                    "funding_last_date": flags.get("funding_last_date"),
                    "funding_investors": flags.get("funding_investors") or [],
                    "funding_lead_investors": flags.get("funding_lead_investors") or [],
                    "funding_tier": flags.get("funding_tier") or "unknown",
                    "funding_quality": flags.get("funding_quality") or 0,
                    "discovery_score": row["discovery_score"],
                    "auto_discovered": True,
                    "discovered_at": discovered_at,
                    "_dedup_key": dedup,
                }
            )

        projects = self._dedup_records(records)
        duration_ms = (time.time() - start_time) * 1000
        logger.info(
            "collector.repository.completed",
            input_count=len(rows),
            output_count=len(projects),
            noise_skipped=noise_skipped,
            deduped=len(records) - len(projects),
            duration_ms=round(duration_ms, 2),
        )
        return projects

    async def run(self, state: PipelineState) -> PipelineState:
        """Execute collector logic.

        Note: In normal pipeline flow, Collector runs once per batch,
        not per project. This method signature matches BaseAgent contract
        but Collector should be invoked differently in Orchestrator.

        For now, returns state unchanged (actual collection happens
        in Orchestrator's collect_projects() method).
        """
        self._log_start(state)
        start_time = time.time()

        try:
            # Collector doesn't modify individual project state
            # It runs once to produce the list of projects
            # This is here to satisfy BaseAgent contract
            pass

        except Exception as e:
            error = AgentError(
                agent_name=self.name, kind="collection_error", message=str(e), project_id=state.project.id
            )
            state.add_error(error)

        duration_ms = (time.time() - start_time) * 1000
        self._log_complete(state, duration_ms)

        return state

    def collect_from_seed(self, seed_projects: list[dict[str, Any]]) -> list[RawProject]:
        """Collect projects from seed data.

        Args:
            seed_projects: List of seed project dicts

        Returns:
            List of RawProject with deduplication applied

        Example seed_projects format:
        [
            {
                "name": "LayerX",
                "url": "https://layerx.xyz",
                "sector": "L2",
                "stage": "testnet",
                "has_testnet": True,
                "has_points_program": True,
                "no_token_yet": True,
            }
        ]
        """
        logger.info("collector.seed.started", count=len(seed_projects))
        start_time = time.time()

        records = [self._raw_to_record(raw) for raw in seed_projects]
        results = self._dedup_records(records)

        duration_ms = (time.time() - start_time) * 1000
        logger.info(
            "collector.seed.completed",
            input_count=len(seed_projects),
            output_count=len(results),
            deduped=len(seed_projects) - len(results),
            duration_ms=round(duration_ms, 2),
        )

        return results


if __name__ == "__main__":
    # Test collector
    import asyncio

    async def test() -> None:
        print("=== Testing Collector Agent ===\n")

        # Create test seed data with duplicates
        seed_data: list[dict[str, Any]] = [
            {
                "name": "LayerX",
                "url": "https://layerx.xyz",
                "sector": "L2",
                "stage": "testnet",
                "source": "seed",
                "has_testnet": True,
                "has_points_program": True,
                "no_token_yet": True,
            },
            {
                "name": "Layer-X Finance",  # Duplicate (different format)
                "url": "https://layer-x.com",
                "sector": "layer2",  # Different format
                "stage": "testnet",
                "source": "defillama",
                "has_testnet": True,
            },
            {
                "name": "UniswapX",
                "url": "https://uniswap.org",
                "sector": "DEX",
                "stage": "mainnet",
                "source": "cryptorank",
            },
        ]

        collector = CollectorAgent()
        projects = collector.collect_from_seed(seed_data)

        print(f"Input: {len(seed_data)} projects")
        print(f"Output: {len(projects)} projects (after dedup)\n")

        for p in projects:
            print(f"✓ {p.name}")
            print(f"  ID: {p.id}")
            print(f"  Sector: {p.sector}")
            print(f"  Source: {p.source}")
            print(f"  Signals: testnet={p.has_testnet}, points={p.has_points_program}")
            print()

        # Verify deduplication
        if len(projects) != 2:
            raise RuntimeError("Should dedupe LayerX variants")
        layerx = next(p for p in projects if "layer" in p.name.lower())
        if layerx.source != "seed,defillama":
            raise RuntimeError("Should merge sources")

        print("✓ All tests passed!")

    asyncio.run(test())
