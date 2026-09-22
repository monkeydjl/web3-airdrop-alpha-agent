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
        estimated_gas: str | None = None,
        recommended_asset: str | None = None,
        dapp_url: str | None = None,
        execution_steps: list[str] | None = None,
        anti_sybil_tip: str | None = None,
        protocol_highlight: str | None = None,
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
                "estimated_gas": estimated_gas,
                "recommended_asset": recommended_asset,
                "dapp_url": dapp_url or link,
                "execution_steps": execution_steps or [],
                "anti_sybil_tip": anti_sybil_tip,
                "protocol_highlight": protocol_highlight,
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
        estimated_gas="0 USD (纯信息检索)",
        recommended_asset="无",
        execution_steps=[
            "1. 打开官方网站，核验浏览器 SSL 证书与推特认证入口；",
            "2. 检查是否有假冒域名，书签收藏正规入口；",
            "3. 确认产品白皮书与安全审计报告。",
        ],
        anti_sybil_tip="切勿点击搜索引擎赞助广告推广链接，谨防钓鱼授权风险。",
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
            link=url,
            estimated_gas="< $0.50 或免费 (社交/签名任务免 Gas)",
            recommended_asset="无或少量签名 Gas",
            execution_steps=[
                "1. 进入官方 Galxe / Layer3 / 任务中心活动主页；",
                "2. 绑定常用社交媒体账号并完成基础关注/转推任务；",
                "3. 提交链上验证动作并领取对应的积分或 OAT 勋章；",
                "4. 关注活动截止日期（Deadline），及时 Claim 奖励。",
            ],
            anti_sybil_tip="社交账号需有日常真实使用痕迹，避免同一 IP 下批量绑定全新白号。",
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
            estimated_gas="0 USD",
            recommended_asset="无",
            execution_steps=[
                "1. 检索官方公告与 Mirror / Medium 博文；",
                "2. 确认是否有合格快照高度（Snapshot Block）或倒计时；",
                "3. 检查是否有 KYC 或特定地区 IP 排除条款。",
            ],
            anti_sybil_tip="如项目明确要求 KYC，请评估成本与多号风险，切勿盲目扩大规模。",
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
            task_id="testnet-faucet-guide",
            category="testnet",
            title="领取免费测试网水龙头 (Faucet)",
            description="通过官方或公共水龙头获取免费测试币（如 Sepolia ETH / 专属 Testnet 代币），无需充值任何真实本金即可开展全套交互。",
            priority=1,
            effort="low",
            why="测试网交互核心是 0 本金获取资格，水龙头是第一步且完全免费。",
            action_hint="优先访问官方文档中的 Faucet 链接或公共水龙头平台（如 Alchemy Faucet、Infura、QuickNode 等）",
            link=url,
            required=True,
            estimated_gas="0 USD (完全免费零本金)",
            recommended_asset="测试网水龙头代币 (Sepolia ETH / 专属 Testnet Token)",
            execution_steps=[
                "1. 访问项目官方文档或水龙头页面获取领水地址；",
                "2. 输入 EVM / Cosmos / Solana 对应钱包地址；",
                "3. 如遇官方水龙头排队，可使用 Alchemy 或 QuickNode 公共水龙头领水；",
                "4. 收到测试币后记录余额并准备核心交互。",
            ],
            anti_sybil_tip="水龙头通常有每日限额，按天错开领取时间；避免同 IP 批量请求。",
        )
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
            link=url,
            estimated_gas="0 USD (测试网 Gas 代币)",
            recommended_asset="测试币 (Testnet Tokens)",
            execution_steps=[
                "1. 切换钱包 RPC 到对应测试网网络；",
                "2. 访问测试网 dApp，完成至少 1 笔核心业务交易（Swap / Stake / Mint）；",
                "3. 记录交易 Tx Hash 作为活动完成证明；",
                "4. 周期性（如每周）重复一次交互保持月度活跃。",
            ],
            anti_sybil_tip="不同钱包间交易金额使用随机非整数（如 0.137 而非 0.1），交互时间间隔 2-6 小时以上。",
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
            estimated_gas="0 USD",
            recommended_asset="无",
            execution_steps=[
                "1. 在测试网使用过程中记录界面异常、合约报错或流程不畅之处；",
                "2. 前往项目 Discord 的 #feedback 或 #testnet-bugs 频道；",
                "3. 附带钱包地址、TxHash 与截图提交条理清晰的体验反馈。",
            ],
            anti_sybil_tip="真实反馈比无意义 GM/GN 更容易被团队标记为活跃贡献者甚至给予专属身份组。",
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
            estimated_gas="$1.00 - $8.00 (取决于所在主链)",
            recommended_asset="ETH / USDC / 原生代币",
            execution_steps=[
                "1. 在官方文档确认已审计的核心合约地址；",
                "2. 从安全源准备适量资金，建议单笔金额保持在 $50 - $200 区间；",
                "3. 完成核心业务交互（如兑换或存入金库），并记录交易凭据；",
                "4. 保持小额资金留存至少 7-14 天，避免「即存即提」被判定为清洗交易。",
            ],
            anti_sybil_tip="金额务必随机化（带小数位）；避免同一批钱包在同一区块内向同一合约集中交互。",
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
    # ── Curated Protocol & Sector Precision Guides ──
    name_l = name.lower()
    proj_id_l = str(project.get("id") or "").lower()
    sector_l = str(project.get("sector") or "").lower()

    # 1. Symbiotic
    if "symbiotic" in name_l or "symbiotic" in proj_id_l:
        add(
            task_id="curated-symbiotic-vault-deposit",
            category="mainnet",
            title="Symbiotic 抵押金库交互与额度监控",
            description="存入 wstETH / mETH / cbETH 至 Symbiotic 官方或 Mellow 联合金库，获取 Restaking 凭证与积分。",
            priority=1,
            effort="medium",
            why="Symbiotic 是以太坊核心去中心化 Restaking 基础设施，顶级风投领投，金库质押是空投资格的核心凭据。",
            action_hint="关注官方 Cap 开放窗口，优先存入未满额金库",
            link="https://app.symbiotic.fi",
            required=True,
            estimated_gas="$3 - $10 (Ethereum Mainnet)",
            recommended_asset="wstETH / mETH / cbETH",
            dapp_url="https://app.symbiotic.fi",
            execution_steps=[
                "1. 准备 wstETH / mETH / cbETH 至以太坊主网钱包；",
                "2. 访问 Symbiotic 官方 App (app.symbiotic.fi)，核对官方域名与合约；",
                "3. 寻找有开放额度（Cap Available）的抵押金库（如 Mellow 联合金库）；",
                "4. 授权并存入代币，获得对应 Restaked 凭证；",
                "5. 关注官方 Discord 与公告，及时在金库额度释放窗口进行质押。",
            ],
            anti_sybil_tip="单钱包质押金额建议保持在 0.05 ETH 以上避免被认定为尘埃；质押周期建议保持 30 天以上，切勿在同一天内跨多钱包同金额操作。",
            protocol_highlight="重点 Restaking 协议",
        )

    # 2. Mantle Restaking / mETH
    if "mantle" in name_l or "meth" in name_l or "mantle" in proj_id_l:
        add(
            task_id="curated-mantle-restaking",
            category="mainnet",
            title="质押 ETH 铸造 mETH 并参与 Mantle Restaking 季",
            description="在以太坊主网质押 ETH 获得 mETH，并参与 cmETH 质押与 Mantle 生态 DEX 流动性。",
            priority=1,
            effort="medium",
            why="Mantle Restaking 提供了业内领先的原生收益与生态加权积分，同时享受双重奖励。",
            action_hint="优先质押 cmETH 并在 Mantle 网络留存 Gas 交互",
            link="https://meth.mantle.xyz",
            required=True,
            estimated_gas="$2 - $6 (Ethereum Mainnet) / < $0.05 (Mantle L2)",
            recommended_asset="ETH / mETH / cmETH",
            dapp_url="https://meth.mantle.xyz",
            execution_steps=[
                "1. 在以太坊主网进入 mETH 官方页面 (meth.mantle.xyz)，将 ETH 质押换取 mETH；",
                "2. 进入 cmETH 模块，将 mETH 升级为 cmETH 享受 Restaking 与积分加权；",
                "3. 利用 Mantle 官方跨链桥，跨入小额资产体验 Mantle L2 生态 DEX（如 Merchant Moe）；",
                "4. 定期在质押看板查看积分累积状态。",
            ],
            anti_sybil_tip="跨链与质押时保留少量原生 MNT 与 ETH 作为 Gas；多号操作时打乱时间与金额比例。",
            protocol_highlight="重点 Restaking 协议",
        )

    # 3. Mellow Restaking
    if "mellow" in name_l or "mellow" in proj_id_l:
        add(
            task_id="curated-mellow-vault-deposit",
            category="mainnet",
            title="Mellow Protocol 质押与流动性金库交互",
            description="挑选由顶级风险管理机构（Steakhouse / MEV Capital）打理的金库，存入 wstETH 或 ETH 获取 LRT 凭证并同步累积 Symbiotic 积分。",
            priority=1,
            effort="medium",
            why="Mellow 是 Symbiotic 生态的核心金库管理协议，存入可获得 Mellow 与 Symbiotic 双重积分。",
            action_hint="存入未满额的优质风险金库",
            link="https://mellow.finance",
            required=True,
            estimated_gas="$2 - $8 (Ethereum Mainnet)",
            recommended_asset="wstETH / ETH",
            dapp_url="https://mellow.finance",
            execution_steps=[
                "1. 访问 Mellow Finance 官方金库；",
                "2. 挑选未满额度且风险评级优秀的金库；",
                "3. 存入 wstETH 或 ETH，获取对应流动性质押凭证；",
                "4. 持续保留仓位享受双重积分增长。",
            ],
            anti_sybil_tip="质押后长期持有享受复合收益，避免短期内频繁进出损耗 Gas。",
            protocol_highlight="双重积分协议",
        )

    # 4. Berachain
    if "berachain" in name_l or "bera" in name_l or "berachain" in proj_id_l:
        add(
            task_id="curated-berachain-artio-loop",
            category="testnet",
            title="Berachain 测试网全套生态闭环交互",
            description="领取 $BERA 测试币，并在 BEX、Honey、BEND、BERPS 体验全套流动性证明（PoL）与 DeFi 闭环。",
            priority=1,
            effort="medium",
            why="Berachain 是顶级估值 L1，流动性证明（PoL）龙头，高额融资且测试网完全零本金参与。",
            action_hint="每天领水，每周保持 1-2 次全套 dApp 交互",
            link="https://artio.faucet.berachain.com",
            required=True,
            estimated_gas="0 USD (免费测试网)",
            recommended_asset="BERA (测试币) / HONEY (测试币)",
            dapp_url="https://artio.faucet.berachain.com",
            execution_steps=[
                "1. 访问 Berachain 官方水龙头，输入 EVM 钱包地址领取测试网 $BERA；",
                "2. 打开 BEX (bex.berachain.com)，将部分 BERA 兑换为 STGUSDC 与 HONEY；",
                "3. 打开 Honey dApp (honey.berachain.com)，通过抵押铸造 HONEY 稳定币；",
                "4. 前往 BEND 借贷市场，存入抵押品借出 HONEY 并完成一次还款测试；",
                "5. 访问 BERPS 合约平台，使用小额 HONEY 体验一次多空开平仓；",
                "6. 加入官方 Discord 领取角色，并完成 Galxe 官方系列任务。",
            ],
            anti_sybil_tip="水龙头每 8 小时可领一次，建议连续多天领取形成真实用户行为周期；多钱包操作切忌在同一时间段连续触发相同交易对。",
            protocol_highlight="重点零成本 L1 测试网",
        )

    # 5. Babylon
    if "babylon" in name_l or "babylon" in proj_id_l:
        add(
            task_id="curated-babylon-btc-staking",
            category="mainnet" if has_contract else "testnet",
            title="Babylon BTC 质押与时间锁体验",
            description="连接 BTC 钱包，将比特币质押锁定至 Babylon 协议为 PoS 链提供安全性。",
            priority=1,
            effort="medium",
            why="Babylon 是比特币生态最核心的 Staking 协议，Polychain 与 Binance Labs 顶级投资，是 BTC 资产生息第一入口。",
            action_hint="选择优质 Finality Provider，留意质押 Cap 上限",
            link="https://btcstaking.babylonlabs.io",
            required=True,
            estimated_gas="0 USD (测试网) / $2 - $8 (Bitcoin L1)",
            recommended_asset="Signet BTC (测试网) / Mainnet BTC",
            dapp_url="https://btcstaking.babylonlabs.io",
            execution_steps=[
                "1. 安装支持 BTC 的钱包（OKX Web3 钱包或 Unisat），切换至相应网络；",
                "2. 连接 Babylon 质押前端，挑选信誉良好、佣金合理的 Finality Provider；",
                "3. 输入 BTC 质押数量并设置锁定区块周期；",
                "4. 签署时间锁交易，等待比特币主网/测试网确认生效。",
            ],
            anti_sybil_tip="多号交互时切勿从同一个中心化交易所或同一 BTC 聚合地址同区块分发资金。",
            protocol_highlight="比特币生态核心",
        )

    # 6. Story Protocol
    if "story" in name_l or "story" in proj_id_l:
        add(
            task_id="curated-story-protocol-ip",
            category="testnet",
            title="Story Protocol IP 资产注册与生态交互",
            description="领取测试币，在 Story 网络上注册独创 IP 资产、设定商业许可并铸造许可证。",
            priority=1,
            effort="medium",
            why="Story Protocol 是 a16z 领投超 1.4 亿美元的 IP 资产区块链龙头，当前测试网完全免费零成本参与。",
            action_hint="注册带真实元数据的原创作品，体验母子 IP 组合",
            link="https://story.foundation",
            required=True,
            estimated_gas="0 USD (免费测试网)",
            recommended_asset="Story Testnet IP / Sepolia ETH",
            dapp_url="https://story.foundation",
            execution_steps=[
                "1. 通过官方水龙头或水龙头聚合平台获取测试网 $IP 代币；",
                "2. 在 Story 生态平台（如 Story Hunt / Unleash）注册独创 IP 资产（图片、音频或文本元数据）；",
                "3. 配置该 IP 的商业许可证（License Terms）并铸造许可代币；",
                "4. 尝试将衍生作品绑定到已有母 IP 上体验可组合性。",
            ],
            anti_sybil_tip="注册具有真实辨识度的 IP 元数据，避免机械脚本批量生成纯乱码内容。",
            protocol_highlight="超高融资 0 成本测试网",
        )

    # 7. Accountable
    if "accountable" in name_l or "accountable" in proj_id_l:
        add(
            task_id="curated-accountable-workflow",
            category="testnet" if has_testnet else "official",
            title="Accountable 验证机制与早期用户任务",
            description="完成官方 Waitlist 注册与社群验证，测试合规数据与链上凭据工作流。",
            priority=1,
            effort="low",
            why="Accountable 拥有顶级早期融资，当前处于早期准入阶段，早期交互成本极低。",
            action_hint="绑定高活跃度社交账号，提交合规体验",
            link=url or "https://accountable.com",
            required=True,
            estimated_gas="0 USD (免费)",
            recommended_asset="无需充值本金",
            dapp_url=url or "https://accountable.com",
            execution_steps=[
                "1. 访问官网完成早期 Waitlist / 测试资格申请；",
                "2. 绑定常用社交账号与 GitHub，完成社区合规认证；",
                "3. 在开放的沙盒/测试网环境中完成一笔合规证明流程体验。",
            ],
            anti_sybil_tip="确保社交账号活跃度高，避免使用新注册的白号。",
            protocol_highlight="早期高分潜力项目",
        )

    # 8. EigenLayer
    if "eigen" in name_l or "eigen" in proj_id_l:
        add(
            task_id="curated-eigenlayer-restaking",
            category="mainnet",
            title="EigenLayer 再质押与 AVS 委托交互",
            description="连接钱包存入支持的 LST 代币或原生以太坊，委托给顶级 AVS 节点运营商。",
            priority=1,
            effort="medium",
            why="EigenLayer 是共享安全机制的先驱，支持多种 LST/LRT 再质押。",
            action_hint="挑选高信誉 Operator 并保持稳定质押",
            link="https://app.eigenlayer.xyz",
            required=True,
            estimated_gas="$3 - $10 (Ethereum Mainnet)",
            recommended_asset="stETH / rETH / ETH",
            dapp_url="https://app.eigenlayer.xyz",
            execution_steps=[
                "1. 连接钱包至 app.eigenlayer.xyz；",
                "2. 存入支持的 LST 代币或通过原生提款凭据质押；",
                "3. 委托给有信誉的 AVS 节点运营商（Operator）。",
            ],
            anti_sybil_tip="保持稳定质押，单钱包委托金额建议 > 0.05 ETH。",
            protocol_highlight="再质押生态基石",
        )

    # 9. Generic Sector Archetypes (if not already matched curated above)
    has_curated_task = any(t["id"].startswith("curated-") for t in tasks)
    if not has_curated_task:
        if any(w in sector_l or w in name_l for w in ("restak", "staking", "yield", "vault", "collateral")):
            add(
                task_id="archetype-restaking-vault",
                category="mainnet" if has_contract else "official",
                title="Restaking 核心金库与流动性质押交互",
                description="核对官方金库合约，存入 LST/LRT 或原生代币，获取质押凭证与积分加权。",
                priority=1,
                effort="medium",
                why="该项目属于质押/再质押/收益聚合赛道，存入资产并获取凭证通常为主要权重来源。",
                action_hint="优先选择未满额度金库，避免频繁存取",
                link=url,
                required=True,
                estimated_gas="$2 - $8 (Ethereum / L2)",
                recommended_asset="LST / LRT (如 wstETH, mETH, ezETH) 或原生资产",
                dapp_url=url,
                execution_steps=[
                    "1. 在官网确认受支持的抵押资产列表；",
                    "2. 选择开放额度的高收益金库；",
                    "3. 授权并存入资产，留存对应质押凭证；",
                    "4. 保持质押状态并关注官方快照公告。",
                ],
                anti_sybil_tip="质押周期建议在 30 天以上，保持长期用户画像，避免同日跨钱包同额度操作。",
            )
        elif any(w in sector_l for w in ("l2", "rollup", "layer 2")):
            add(
                task_id="archetype-l2-ecosystem",
                category="mainnet" if has_contract else "testnet",
                title="L2 生态跨链与核心 DEX/合约交互",
                description="使用官方跨链桥转入启动资金，并在生态 DEX / 借贷完成多笔核心交易。",
                priority=1,
                effort="medium",
                why="L2 网络空投考核关键指标：跨链桥使用、独立活跃周数/月数、累计 Tx 笔数与交互金额。",
                action_hint="定期跨链，分散在不同周次完成交互",
                link=url,
                required=True,
                estimated_gas="< $0.30 (L2 低成本)",
                recommended_asset="原生跨链代币 (ETH / USDC)",
                dapp_url=url,
                execution_steps=[
                    "1. 使用官方跨链桥或主流跨链桥转入资金；",
                    "2. 在生态官方推荐的 DEX 完成至少 2 次兑换；",
                    "3. 提供小额 LP 流动性；",
                    "4. 每隔 1-2 周保持 1 笔链上活跃记录。",
                ],
                anti_sybil_tip="各钱包操作时间间隔 3 小时以上，跨链金额随机化，避免资金闭环回流。",
            )

    # Sort: priority asc, then required first
    tasks.sort(key=lambda t: (t["priority"], 0 if t["required"] else 1, t["id"]))

    summary: dict[str, Any] = {
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
