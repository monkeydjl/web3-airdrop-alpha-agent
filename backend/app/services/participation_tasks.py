"""Generate a prioritized participation / farm checklist for a project.

Tasks are rule-based from stored project fields (no live scraping).
Users can still mark completion client-side or via interactions.activities.
"""

from __future__ import annotations

from typing import Any


def _truthy(project: dict[str, Any], *keys: str) -> bool:
    for k in keys:
        v = project.get(k)
        if isinstance(v, bool) and v:
            return True
        if v not in (None, "", 0, "0", False):
            if k in ("tvl_usd", "tvl") and float(v or 0) <= 0:
                continue
            if isinstance(v, str) and not v.strip():
                continue
            if (
                k not in ("tvl_usd", "tvl")
                and isinstance(v, (int, float))
                and not isinstance(v, bool)
                and k in ("github_stars", "source_count")
            ):
                # numeric flags only count if used as bool-like elsewhere
                return int(v) > 0
            if isinstance(v, bool):
                return v
            if isinstance(v, str):
                return True
    return False


def _stage(project: dict[str, Any]) -> str:
    return str(project.get("stage") or "").lower()


def generate_participation_tasks(project: dict[str, Any]) -> dict[str, Any]:
    """Return checklist grouped by category with priority scores."""
    name = project.get("name") or "该项目"
    url = (project.get("url") or "").strip() or None
    stage = _stage(project)
    label = str(project.get("label") or "WATCH").upper()

    has_testnet = bool(project.get("has_testnet")) or stage == "testnet"
    has_points = bool(project.get("has_points_program"))
    no_token = bool(project.get("no_token_yet"))
    has_task_portal = bool(project.get("has_task_portal"))
    has_docs = bool(project.get("has_docs") or project.get("has_whitepaper"))
    has_roadmap = bool(project.get("has_roadmap"))
    has_github = bool(project.get("has_github"))
    has_twitter = bool(project.get("has_twitter"))
    has_discord = bool(project.get("has_discord"))
    has_contract = bool(project.get("has_contract")) or (project.get("tvl_usd") not in (None, 0, "0"))
    explicit = bool(project.get("explicit_airdrop_mention"))
    friction = str(project.get("sybil_friction") or "unknown").lower()
    delivery = str(project.get("roadmap_delivery") or "unknown").lower()

    tasks: list[dict[str, Any]] = []

    def add(
        *,
        task_id: str,
        category: str,
        title: str,
        description: str,
        priority: int,
        effort: str,
        why: str,
        action_hint: str | None = None,
        link: str | None = None,
        required: bool = False,
        enabled: bool = True,
    ) -> None:
        if not enabled:
            return
        tasks.append(
            {
                "id": task_id,
                "category": category,
                "category_zh": {
                    "research": "信息核实",
                    "official": "官方活动",
                    "testnet": "测试网",
                    "mainnet": "主网产品",
                    "social": "社群建设",
                    "dev": "开发者/GitHub",
                    "risk": "风险与门槛",
                    "track": "记录与复盘",
                }.get(category, category),
                "title": title,
                "description": description,
                "priority": priority,  # 1 = do first
                "effort": effort,  # low | medium | high
                "effort_zh": {"low": "低", "medium": "中", "high": "高"}.get(effort, effort),
                "why": why,
                "action_hint": action_hint,
                "link": link,
                "required": required,
                "status_suggested": "todo",
            }
        )

    # ── Research (always useful) ──
    add(
        task_id="research-official-site",
        category="research",
        title="核对官网与文档",
        description=f"打开「{name}」官网，确认产品说明、安全提示与最新公告是否一致。",
        priority=1,
        effort="low",
        why="避免钓鱼站；后续交互都以官方域名与文档为准。",
        action_hint="收藏官网，核对合约/应用入口是否来自官方",
        link=url,
        required=True,
    )
    if has_docs:
        add(
            task_id="research-docs-airdrop",
            category="research",
            title="通读文档中的积分/空投/资格说明",
            description="在 Docs / Whitepaper 中搜索 airdrop、points、snapshot、eligibility。",
            priority=1,
            effort="low",
            why="很多资格条件只写在文档里，不在 Twitter。",
            action_hint="记录 snapshot 时间、是否反女巫、是否需主网用量",
            link=url,
        )
    if has_roadmap:
        add(
            task_id="research-roadmap",
            category="research",
            title="对照公开路线图与当前阶段",
            description=f"当前阶段信号：{stage or '未知'}；履约判断：{delivery}。",
            priority=2,
            effort="low",
            why="判断项目是否还在推进，避免只蹭叙事。",
            action_hint="标出已完成/未完成里程碑",
        )

    # ── Official campaigns ──
    if has_task_portal or has_points or explicit:
        add(
            task_id="official-task-portal",
            category="official",
            title="完成官方任务/积分门户",
            description=("优先使用官方绑定的 Galxe / Layer3 / Quest / 积分面板完成任务，而不是第三方「代做」链接。"),
            priority=1,
            effort="medium",
            why="可验证任务入口比口头「可能空投」更有参与价值。",
            action_hint="同一钱包完成；截图任务进度；避免批量脚本",
            required=bool(has_task_portal or has_points),
            enabled=True,
        )
    if explicit:
        add(
            task_id="official-airdrop-rules",
            category="official",
            title="精读官方空投规则与时间表",
            description="查找 snapshot、TGE、区域限制、女巫条款等原文。",
            priority=1,
            effort="low",
            why="系统检测到明确空投相关表述，规则细节决定你做不做、做多少。",
            action_hint="写入日历提醒；不符合区域则直接放弃",
        )

    fq = float(project.get("funding_quality") or 0)
    tier = str(project.get("funding_tier") or "unknown")
    if fq >= 0.4 or project.get("recent_funding"):
        inv = project.get("funding_investors") or []
        inv_s = "、".join(str(x) for x in inv[:4]) if isinstance(inv, list) and inv else "见 RootData/公告"
        add(
            task_id="research-funding",
            category="research",
            title="核对融资轮次与领投方",
            description=f"融资质量约 {fq:.2f}（{tier}）。交叉验证 RootData / 官网 / 媒体稿。",
            priority=2,
            effort="low",
            why="融资与投资方影响项目存活与活动预算，但不等于空投保证。",
            action_hint=f"关注投资方：{inv_s}",
        )
    if no_token and not has_points and not has_task_portal:
        add(
            task_id="official-watch-announcement",
            category="official",
            title="订阅官方公告，等待积分/任务上线",
            description="当前偏「未发币但无可验证任务」。先观察，不要盲目刷交互。",
            priority=2,
            effort="low",
            why="无可验证入口时重仓交互往往性价比差。",
            action_hint="打开官网公告/博客 RSS；设周更提醒",
            link=url,
        )

    # ── Testnet ──
    if has_testnet or stage == "testnet":
        add(
            task_id="testnet-faucet-and-tx",
            category="testnet",
            title="测试网领水并完成核心交互",
            description="领取测试币，完成官方推荐路径：桥接、swap、mint、质押等（以文档为准）。",
            priority=1,
            effort="medium",
            why="测试网活跃是常见资格维度；系统已标记测试网信号。",
            action_hint="用主号认真做，保留 tx 哈希；勿用同一套路狂刷",
            required=True,
        )
        add(
            task_id="testnet-feedback-bug",
            category="testnet",
            title="提交有效反馈 / Bug（若官方开放）",
            description="在 Discord bug 频道或 GitHub issue 提交可复现问题，比无脑刷交易更像真实用户。",
            priority=2,
            effort="medium",
            why="部分项目对反馈者加权；也提升你对产品的理解。",
            action_hint="一条清晰复现步骤 > 十条灌水",
            enabled=has_discord or has_github,
        )
    elif stage in ("ideation", ""):
        add(
            task_id="testnet-wait",
            category="testnet",
            title="等待测试网开放后再参与",
            description="当前阶段偏早期，尚无稳定测试网信号。",
            priority=3,
            effort="low",
            why="过早交互可能浪费时间且无记录。",
            action_hint="关注路线图中的 testnet 节点",
        )

    # ── Mainnet product ──
    if has_contract or stage == "mainnet":
        add(
            task_id="mainnet-core-use",
            category="mainnet",
            title="主网产品小额真实使用",
            description="按官方文档做小额核心操作（提供流动性、交易、铸造等），控制 Gas 与本金风险。",
            priority=2,
            effort="high",
            why="链上真实用量常被用于资格；系统检测到合约/TVL 等产品信号。",
            action_hint="先小额；记录合约地址是否来自官方",
            link=url,
        )

    # ── Social / Discord ──
    if has_discord:
        add(
            task_id="social-discord-join",
            category="social",
            title="加入官方 Discord 并完成验证",
            description="完成 Verify、领取角色；关注 announcement / roles 频道。",
            priority=2,
            effort="low",
            why="角色与活动通知常在 Discord；建设者身份有时被单独加权。",
            action_hint="关闭无关频道噪音；只留公告与角色",
            required=False,
        )
        add(
            task_id="social-discord-contribute",
            category="social",
            title="参与建设型发言（非灌水）",
            description="回答新人问题、整理 FAQ、提交反馈；避免复制粘贴表情刷屏。",
            priority=3,
            effort="medium",
            why="Discord 建设比无意义刷屏更接近「社区贡献」叙事。",
            action_hint="每周 2～3 条有信息量的回复即可",
        )
    else:
        add(
            task_id="social-find-discord",
            category="social",
            title="从官网找到并加入官方社群",
            description="确认 Discord/Telegram 链接来自官网，谨防仿盘。",
            priority=3,
            effort="low",
            why="当前无明确 Discord 信号，但仍建议核实是否有官方社群。",
            link=url,
        )

    if has_twitter:
        add(
            task_id="social-twitter-follow",
            category="social",
            title="关注官方 Twitter/X 并打开通知",
            description="跟进 snapshot、任务上线、紧急暂停等公告。",
            priority=2,
            effort="low",
            why="很多任务与规则变更只发推。",
            action_hint="仅关注官方号；关闭无关营销号",
        )

    # ── Dev ──
    if has_github:
        add(
            task_id="dev-star-watch",
            category="dev",
            title="Star / Watch 官方仓库（可选）",
            description="关注 release 与 issue，了解是否在持续交付。",
            priority=4,
            effort="low",
            why="辅助判断执行力；本身通常不是强资格，但有助于你做决策。",
            action_hint="看最近 commit / release 日期",
        )
        if stage in ("testnet", "ideation") or has_testnet:
            add(
                task_id="dev-try-sdk",
                category="dev",
                title="尝试开发者路径（若开放）",
                description="跑官方 examples、提 PR 或写集成笔记（适合有开发能力的用户）。",
                priority=3,
                effort="high",
                why="部分协议对 builder 单独激励。",
                action_hint="只做官方 README 推荐步骤",
            )

    # ── Risk / friction ──
    if friction == "high":
        add(
            task_id="risk-kyc-decision",
            category="risk",
            title="评估 KYC / 唯一身份成本",
            description="系统检测到较高女巫门槛（如 KYC、World ID 等线索）。决定是否愿意实名参与。",
            priority=1,
            effort="medium",
            why="高门槛可能降低刷量，但增加你的隐私与时间成本。",
            action_hint="不接受实名则降低参与优先级",
            required=True,
        )
    elif friction == "low":
        add(
            task_id="risk-sybil-competition",
            category="risk",
            title="警惕低门槛刷量竞争",
            description="积分/任务可能较容易多号；控制投入，避免「看起来活跃」却无差异化。",
            priority=2,
            effort="low",
            why="低女巫门槛时，纯刷量回报常被摊薄。",
            action_hint="主号做深、少开号",
        )

    # ── Tracking (always) ──
    add(
        task_id="track-log-interaction",
        category="track",
        title="在本系统写入交互记录",
        description="在「我的交互记录」中登记开始日期、成本、活动类型；结束后补收益与结果。",
        priority=2,
        effort="low",
        why="用于个人复盘，并给后期权重校准提供真实样本。",
        action_hint="做完一批任务就记一条，别堆到月末",
        required=True,
    )
    if label == "FARM":
        add(
            task_id="track-weekly-review",
            category="track",
            title="每周复盘：任务进度 vs 官方公告",
            description="重点参与项目建议固定复盘，防止规则变更后无效劳动。",
            priority=3,
            effort="low",
            why=f"当前系统标签为 {label}，值得更高维护频率。",
        )
    elif label == "IGNORE":
        add(
            task_id="track-deprioritize",
            category="track",
            title="降低优先级或移出主清单",
            description="仅在出现新的任务门户/测试网公告时再回来。",
            priority=1,
            effort="low",
            why="系统当前建议忽略；默认不要重仓时间。",
        )

    # Sort: priority asc, then required first
    tasks.sort(key=lambda t: (t["priority"], 0 if t["required"] else 1, t["id"]))

    summary = {
        "total": len(tasks),
        "required_count": sum(1 for t in tasks if t["required"]),
        "by_category": {},
        "focus": [],
    }
    for t in tasks:
        summary["by_category"][t["category_zh"]] = summary["by_category"].get(t["category_zh"], 0) + 1
    summary["focus"] = [t["title"] for t in tasks if t["priority"] == 1][:5]

    tips: list[str] = []
    if has_task_portal:
        tips.append("优先官方任务门户，比无目标主网刷 gas 更清晰。")
    if has_testnet:
        tips.append("测试网：质量 > 数量，保留可验证记录。")
    if friction == "high":
        tips.append("高身份门槛：先决定是否接受 KYC，再投入时间。")
    if not has_task_portal and not has_testnet and no_token:
        tips.append("暂无可验证参与路径：以观察公告为主，避免盲目交互。")
    tips.append("以下清单由信号规则生成，非官方承诺；请以项目方最新公告为准。")

    return {
        "project_id": project.get("id"),
        "project_name": name,
        "label": label,
        "stage": stage or None,
        "summary": summary,
        "tips": tips,
        "tasks": tasks,
        "signals_used": {
            "has_testnet": has_testnet,
            "has_points_program": has_points,
            "no_token_yet": no_token,
            "has_task_portal": has_task_portal,
            "has_docs": has_docs,
            "has_roadmap": has_roadmap,
            "has_github": has_github,
            "has_twitter": has_twitter,
            "has_discord": has_discord,
            "has_contract": has_contract,
            "explicit_airdrop_mention": explicit,
            "sybil_friction": friction,
            "roadmap_delivery": delivery,
        },
    }
