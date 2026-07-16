"""Project AI brief: natural-language interpretation of score factors.

Always has a high-quality rule-based brief. Optionally enhances with LLM
when OPENAI_API_KEY is configured (OpenAI-compatible base URL).
"""

from __future__ import annotations

import json
from typing import Any

import httpx
import structlog

from app.config import settings

logger = structlog.get_logger(__name__)

LABEL_ZH = {
    "FARM": "重点参与",
    "WATCH": "持续观察",
    "IGNORE": "建议忽略",
}

TIMING_ZH = {
    "early": "叙事仍处早期窗口，进入成本相对友好",
    "growth": "叙事处于上升期，关注度在抬升",
    "peak": "叙事偏热，竞争与预期已抬高",
    "late": "叙事偏晚，增量空间可能有限",
}

STAGE_ZH = {
    "ideation": "构想/极早期",
    "testnet": "测试网阶段",
    "mainnet": "已上主网",
    "growth": "成长期",
    "peak": "高峰期",
    "mature": "成熟期",
}


def _num(v: Any, default: float = 0.0) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def _parse_json(value: Any) -> Any:
    if value is None or value == "":
        return None
    if isinstance(value, (dict, list)):
        return value
    try:
        return json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return None


def build_rule_brief(project: dict[str, Any]) -> dict[str, Any]:
    """Compose a multi-section Chinese brief from stored project fields."""
    name = project.get("name") or "该项目"
    label = (project.get("label") or "WATCH").upper()
    score = int(project.get("score") or 0)
    confidence = _num(project.get("confidence"), 0.5)
    sector = project.get("sector") or "未知赛道"
    stage = project.get("stage") or ""
    source = project.get("source") or ""

    reasons = _parse_json(project.get("reason")) or []
    if isinstance(reasons, str):
        reasons = [reasons]
    narrative = _parse_json(project.get("narrative_json")) or {}
    team = _parse_json(project.get("team_json")) or {}
    risk = _parse_json(project.get("risk_json")) or {}
    tokenomics = _parse_json(project.get("tokenomics_json")) or {}

    label_zh = LABEL_ZH.get(label, label)
    timing = str(narrative.get("timing") or "")
    heat = _num(narrative.get("heat_score"), 0.5)
    n_stage = str(narrative.get("stage") or stage)
    team_score = _num(team.get("score", team.get("team_score")), 0.5)
    team_type = str(team.get("team_type") or "unknown")
    risk_level = str(team.get("risk_level") or "")
    flags = team.get("flags") if isinstance(team.get("flags"), list) else []
    sybil = str(risk.get("sybil_difficulty") or "medium")
    farming = str(risk.get("farming_cost") or "medium")
    token_risk = _num(risk.get("token_risk"), 0.5)
    unlock = str(risk.get("unlock_pressure") or tokenomics.get("unlock_pressure") or "medium")
    vc = _num(tokenomics.get("vc_share"), 0.25)
    team_share = _num(tokenomics.get("team_share"), 0.2)

    # ── headline ──
    if label == "FARM":
        headline = f"「{name}」综合评分 {score}，系统建议「{label_zh}」——更值得优先研究交互路径。"
    elif label == "IGNORE":
        headline = f"「{name}」综合评分 {score}，系统建议「{label_zh}」——当前信号偏弱或风险/竞争不划算。"
    else:
        headline = f"「{name}」综合评分 {score}，系统建议「{label_zh}」——有机会但尚不构成强参与信号。"

    conf_note = (
        "各分析模块输出较完整，结论可信度中等偏上。"
        if confidence >= 0.75
        else (
            "部分模块数据偏少，结论仅供参考，建议结合一手资料复核。"
            if confidence < 0.5
            else "置信度中等，适合作为筛选漏斗而非唯一依据。"
        )
    )

    # ── narrative ──
    timing_txt = TIMING_ZH.get(timing, "叙事时机信息有限")
    stage_txt = STAGE_ZH.get(n_stage, n_stage or "阶段未知")
    if heat >= 0.7:
        heat_txt = f"热度分约 {heat:.2f}，赛道讨论热度偏高，容易吸引资金与交互，但也意味着竞争加剧。"
    elif heat >= 0.45:
        heat_txt = f"热度分约 {heat:.2f}，关注度适中，尚未完全拥挤。"
    else:
        heat_txt = f"热度分约 {heat:.2f}，市场声量偏低，可能是早期机会，也可能是叙事尚未验证。"
    narrative_para = f"【叙事与时机】项目归属「{sector}」赛道，阶段为{stage_txt}。{timing_txt}。{heat_txt}"

    # ── team ──
    type_map = {
        "doxxed": "团队偏实名/可追溯",
        "semi_anon": "团队半匿名",
        "anon": "团队匿名",
        "unknown": "团队信息公开有限",
    }
    team_bits = [type_map.get(team_type, "团队信息不足")]
    if team_score >= 0.7:
        team_bits.append(f"团队分 {team_score:.2f}，信誉侧相对加分")
    elif team_score < 0.4:
        team_bits.append(f"团队分仅 {team_score:.2f}，可信度拉低整体判断")
    else:
        team_bits.append(f"团队分 {team_score:.2f}，中性")
    if flags:
        team_bits.append("标记：" + "、".join(str(f) for f in flags[:4]))
    if risk_level:
        team_bits.append(f"团队风险档：{risk_level}")
    team_para = "【团队】" + "；".join(team_bits) + "。"

    # ── risk ──
    sybil_map = {"high": "女巫成本高（更难刷）", "medium": "女巫难度中等", "low": "女巫成本偏低（易被刷量）"}
    farm_map = {"high": "交互成本偏高", "medium": "交互成本中等", "low": "交互成本较低"}
    unlock_map = {"high": "解锁压力大", "medium": "解锁压力中等", "low": "解锁压力可控"}
    if token_risk >= 0.6:
        tr_txt = f"代币风险启发式 {token_risk:.2f}，结构或阶段风险偏高"
    elif token_risk <= 0.35:
        tr_txt = f"代币风险启发式 {token_risk:.2f}，结构风险相对可控"
    else:
        tr_txt = f"代币风险启发式 {token_risk:.2f}，中性"
    risk_para = (
        f"【风险与成本】{sybil_map.get(sybil, sybil)}；{farm_map.get(farming, farming)}；"
        f"{unlock_map.get(unlock, unlock)}。{tr_txt}。"
        "请结合合约审计、多签与实际交互门槛自行判断。"
    )

    # ── tokenomics ──
    tok_para = (
        f"【代币结构】VC 占比约 {vc:.0%}、团队占比约 {team_share:.0%}（启发式/默认值，非链上最终数据）。"
        "若 VC/团队份额过高且解锁集中，空投预期与盘面压力需打折；占比温和则更利于中长期叙事。"
    )

    # ── execution & transparency (v1.2) ──
    has_gh = bool(project.get("has_github") or project.get("github"))
    has_docs = bool(project.get("has_docs") or project.get("has_whitepaper"))
    has_rm = bool(project.get("has_roadmap"))
    has_tw = bool(project.get("has_twitter") or project.get("twitter"))
    has_dc = bool(project.get("has_discord"))
    stars = project.get("github_stars") or 0
    push_days = project.get("github_recent_push_days")
    exec_bits = []
    if has_gh:
        exec_bits.append("有公开代码仓库")
        if stars:
            exec_bits.append(f"约 {stars} stars")
        if push_days is not None:
            if int(push_days) <= 30:
                exec_bits.append(f"近 {push_days} 天有提交/更新")
            else:
                exec_bits.append(f"仓库约 {push_days} 天未更新")
    if has_rm:
        exec_bits.append("提及公开路线图")
    if not exec_bits:
        exec_bits.append("公开执行信号不足（无可靠 GitHub/路线图字段）")
    exec_para = "【执行与推进】" + "；".join(exec_bits) + "。这影响「是否在按路线图推进」，而不只是概念热度。"

    tr_bits = []
    if project.get("has_whitepaper"):
        tr_bits.append("有白皮书/litepaper 线索")
    elif has_docs:
        tr_bits.append("有文档站/说明文档线索")
    if has_tw:
        tr_bits.append("有 Twitter/X")
    if has_dc:
        tr_bits.append("有 Discord")
    if project.get("url"):
        tr_bits.append("有官网")
    if not tr_bits:
        tr_bits.append("透明度信号偏弱（文档/社媒不全）")
    tr_para = "【透明度】" + "；".join(tr_bits) + "。便于交叉验证承诺与交付，而非只看分数。"

    # v1.3 verifiable path / multi-source / delivery
    task_portal = bool(project.get("has_task_portal"))
    has_contract = bool(project.get("has_contract"))
    source_count = int(project.get("source_count") or 1)
    delivery = str(project.get("roadmap_delivery") or "unknown")
    friction = str(project.get("sybil_friction") or "unknown")
    evid_bits = []
    if task_portal:
        evid_bits.append("存在可验证的任务/积分入口（Galxe/Layer3/Quest 等线索）")
    if has_contract or (project.get("tvl_usd") not in (None, 0)):
        evid_bits.append("有链上产品/TVL/合约侧信号，不只是概念")
    if source_count >= 2:
        evid_bits.append(f"至少 {source_count} 个数据源交叉印证")
    if delivery == "aligned":
        evid_bits.append("路线图与交付信号较对齐（测试网/仓库/TVL）")
    elif delivery == "unclear":
        evid_bits.append("路线图偏纸面，交付信号弱")
    if friction == "high":
        evid_bits.append("女巫门槛偏高（KYC/唯一身份等），适合真人、不适合无脑多号")
    elif friction == "low":
        evid_bits.append("交互门槛可能偏低，需警惕刷量竞争")
    if not evid_bits:
        evid_bits.append("可验证证据仍偏少，建议优先核对官网任务页与合约")
    evid_para = "【可验证性与证据】" + "；".join(evid_bits) + "。"

    # Funding (RootData / structured)
    fq = _num(project.get("funding_quality"), 0)
    tier = str(project.get("funding_tier") or "unknown")
    total_f = project.get("funding_total_usd")
    inv = project.get("funding_investors") or []
    if not isinstance(inv, list):
        inv = []
    if fq > 0.15 or project.get("recent_funding"):
        amt = f"${float(total_f):,.0f}" if total_f else "金额未披露"
        leads = "、".join(str(x) for x in inv[:5]) if inv else "投资方未结构化"
        fund_para = (
            f"【融资】质量分约 {fq:.2f}（档位 {tier}），累计约 {amt}；"
            f"关联投资方线索：{leads}。"
            "融资强不代表一定空投，但通常提升项目存活与活动预算概率。"
        )
    else:
        fund_para = "【融资】暂无结构化融资数据（可配置 RootData API 补全）。"

    # ── reasons ──
    pos = [
        r
        for r in reasons
        if any(k in str(r).lower() for k in ("strong", "early", "low competition", "moderate airdrop", "useful"))
    ]
    neg = [
        r
        for r in reasons
        if any(k in str(r).lower() for k in ("high", "weak", "no airdrop", "late", "uncertain", "missing"))
    ]
    reason_lines: list[str] = []
    if reasons:
        reason_lines.append("【系统打分要点】")
        for r in reasons[:6]:
            reason_lines.append(f"· {r}")
    else:
        reason_lines.append("【系统打分要点】暂无明细理由，主要依赖默认启发式。")

    # ── recommendation ──
    if label == "FARM":
        rec = (
            f"【怎么用这个结论】可优先做信息核实（官网/合约/任务平台）与小额试交互，"
            f"关注测试网/积分/社交任务是否真实可追踪。评分 {score} 表示在当前规则下优于多数观察池，"
            f"但不是保证有空投。"
        )
    elif label == "IGNORE":
        rec = (
            "【怎么用这个结论】可先移出主观察列表，除非你有独特信息源。"
            "若后续出现明确积分活动或未发币信号增强，再重新跑分。"
        )
    else:
        rec = (
            "【怎么用这个结论】适合加入观察清单：定期回看 TVL/任务/融资/社交热度。"
            "只有在空投信号（未发币 + 测试网/积分）变强时，再升格为优先参与。"
        )

    source_line = f"数据来源：{source or '混合/未知'}。"
    paragraphs = [
        headline + conf_note,
        narrative_para,
        team_para,
        risk_para,
        tok_para,
        exec_para,
        tr_para,
        evid_para,
        fund_para,
        "\n".join(reason_lines),
        rec + source_line,
    ]

    bullets: list[str] = []
    bullets.append(f"综合标签：{label_zh}（{score} 分）")
    bullets.append(f"赛道 {sector} · {stage_txt}")
    bullets.append(timing_txt)
    if pos:
        bullets.append("利好侧：" + "；".join(str(x) for x in pos[:3]))
    if neg:
        bullets.append("谨慎侧：" + "；".join(str(x) for x in neg[:3]))
    bullets.append(f"置信度 {confidence:.0%}")

    return {
        "mode": "rule",
        "headline": headline,
        "summary": paragraphs[0],
        "paragraphs": paragraphs,
        "bullets": bullets,
        "label": label,
        "label_zh": label_zh,
        "score": score,
        "confidence": confidence,
    }


async def try_llm_brief(project: dict[str, Any], rule_brief: dict[str, Any]) -> str | None:
    """Optional LLM polish. Returns markdown/plain text or None."""
    api_key = (settings.openai_api_key or "").strip()
    if not api_key:
        return None

    name = project.get("name")
    payload_ctx = {
        "name": name,
        "sector": project.get("sector"),
        "stage": project.get("stage"),
        "score": project.get("score"),
        "label": project.get("label"),
        "confidence": project.get("confidence"),
        "reasons": _parse_json(project.get("reason")),
        "narrative": _parse_json(project.get("narrative_json")),
        "team": _parse_json(project.get("team_json")),
        "risk": _parse_json(project.get("risk_json")),
        "tokenomics": _parse_json(project.get("tokenomics_json")),
        "rule_brief_bullets": rule_brief.get("bullets"),
    }

    system = (
        "你是 Web3 空投研究助手。根据系统给出的结构化评分因子，用简洁、专业的中文写项目解读。"
        "要求：1) 不要编造未提供的融资额/审计/具体任务；2) 结合叙事、团队、风险、代币结构解释为什么是"
        "重点参与/观察/忽略；3) 给出可执行的下一步（查什么、交互注意什么）；4) 3～5 短段，口语化但专业；"
        "5) 明确「非投资建议」。"
    )
    user = f"请解读以下项目评分结果：\n```json\n{json.dumps(payload_ctx, ensure_ascii=False, indent=2)}\n```"

    url = settings.openai_base_url.rstrip("/") + "/chat/completions"
    body = {
        "model": settings.llm_model,
        "temperature": min(0.5, float(settings.llm_temperature) + 0.1),
        "max_tokens": max(400, int(settings.llm_max_tokens)),
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
    }

    try:
        async with httpx.AsyncClient(timeout=45.0) as client:
            resp = await client.post(
                url,
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json=body,
            )
            resp.raise_for_status()
            data = resp.json()
            content = data.get("choices", [{}])[0].get("message", {}).get("content")
            if content and str(content).strip():
                return str(content).strip()
    except Exception as e:
        logger.warning("ai_brief.llm_failed", error=str(e), project=name)
    return None


async def generate_project_brief(project: dict[str, Any]) -> dict[str, Any]:
    rule = build_rule_brief(project)
    llm_text = await try_llm_brief(project, rule)
    if llm_text:
        return {
            **rule,
            "mode": "llm",
            "llm_text": llm_text,
            "display_text": llm_text,
            "fallback_paragraphs": rule["paragraphs"],
        }
    return {
        **rule,
        "mode": "rule",
        "llm_text": None,
        "display_text": "\n\n".join(rule["paragraphs"]),
        "fallback_paragraphs": rule["paragraphs"],
    }
