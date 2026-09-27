"""结构化 Anti-PUA 信号的推断词表（采集侧唯一来源）。

消费方：`app.opportunity.evidence` 的 fatigue/friction 输入（opportunity-v2.0
Shadow 旁路），键在 `services.project_signals.SIGNAL_KEYS` 登记，随
`meta.signals` 落库。

为什么独立成模块：存量回填（`scripts/backfill_structured_signals.py`）与
采集侧（`agents.collector._infer_airdrop_flags`）必须使用**同一套词形与
置信度规则**——两套实现迟早漂移，届时同一项目在回填与采集之间会得到
不同的 is_perp/season/tge 结论。这里的每个公开函数都被两侧直接调用。

置信度契约（与回填脚本一致）：
- ``is_perp``            高置信 → 采集侧直接写入 True；False 不写（默认档等价）
- ``tge_clarity``        中置信 → 仅 confirmed_quarter 有可靠词形；vague/unannounced 不写
- ``points_season_count`` 低置信 → 回填侧只进人工审核清单；采集侧同样**不自动写**
  （误报面大，采集到的描述只是营销文案，人工核对成本高于收益）

词形细节：
- ``"s3x"`` 不命中 ``s3``（数字后必须非字母数字）；裸 sN 只在文本无
  "season" 全词时作兜底；
- 中文无双字节词边界，用前后数字断言代替 ``\\b``。
"""

from __future__ import annotations

import re

TGE_CLARITY_VALUES = ("confirmed_quarter", "vague_soon", "unannounced")
MAX_SEASON = 10  # 与 evidence._signal_season_count 的钳制上限一致

# season 词形（低置信）：
#   "season 2" / "season 2-3" / "seasons 3" / "第 N 季" / "sN"（词边界）
# 刻意**不**匹配裸数字（"support 3"）与文字数字（"third season"）。
_SEASON_PATTERNS = (
    (re.compile(r"\bseasons?\s+(\d{1,2})(?:\s*[-~–]\s*(\d{1,2}))?\b", re.IGNORECASE), "word"),
    # 中文无双字节词边界（\b 对 CJK 无效），改用前后数字断言。
    (re.compile(r"(?<!\d)第\s*(\d{1,2})\s*季(?!\d)"), "zh"),
)
# "sN" 短词形兜底：数字后必须紧跟非字母数字（避免 s3x），且只在文本
# 无 "season" 全词时采信——真正的积分季表述几乎总会写出 season 全词。
_SEASON_SHORT = re.compile(r"(?:^|[^a-z0-9])s(\d{1,2})(?![a-z0-9])", re.IGNORECASE)

# tge 高置信词形（中置信）：confirmed 与 TGE/季度锚词共现（双向），或裸季度。
_TGE_CONFIRMED = re.compile(
    r"\bconfirmed\b.*\b(tge|token\s*generation|q[1-4]\s*20\d{2}|20\d{2}\s*q[1-4])\b"
    r"|\b(tge|token\s*generation)\b.*\bconfirmed\b"
    r"|\bq[1-4]\s*20\d{2}\b",
    re.IGNORECASE,
)

# is_perp 词形（高置信）：与 agents.risk.is_perp_dex 的口径保持一致——
# sector/description 上的 perp dex / perpetual / derivative，**不**匹配项目名
# （"PerpX" 这类品牌名不算），也不被 "perplexity" 这类子串误伤。
_PERP_PATTERNS = (re.compile(r"\bperp\s*dex\b|\bperps?\b|\bperpetual(s)?\b|\bderivatives?\b", re.IGNORECASE),)


def extract_season_count(text: str) -> tuple[int, str] | None:
    """提取积分季数候选。返回 (值, 命中文本) 或 None。

    低置信：多季才有信息量（=1 与默认档等价，不值得写），因此只返回 >=2。
    多段命中取最大；超过 MAX_SEASON 拒绝。
    """
    best: tuple[int, str] | None = None
    word_hits = 0
    for pattern, _kind in _SEASON_PATTERNS:
        for match in pattern.finditer(text):
            word_hits += 1
            groups = [g for g in match.groups() if g]
            numbers = [int(g) for g in groups if g.isdigit()]
            if not numbers:
                continue
            value = max(numbers)
            if value < 2 or value > MAX_SEASON:
                continue
            candidate = (value, match.group(0))
            if best is None or candidate[0] > best[0]:
                best = candidate
    if best is not None or word_hits:
        return best
    for match in _SEASON_SHORT.finditer(text):
        value = int(match.group(1))
        if 2 <= value <= MAX_SEASON:
            return (value, match.group(0).strip())
    return None


def extract_tge_clarity(text: str) -> str | None:
    """提取 TGE 清晰度。仅高置信命中时返回 confirmed_quarter，否则 None。

    "未确认/模糊" 不写：evidence.py 对缺失与 unannounced 等价处理。
    """
    return "confirmed_quarter" if _TGE_CONFIRMED.search(text) else None


def extract_is_perp(sector: str, description: str) -> bool:
    """判定是否永续合约/衍生品协议（高置信，采集侧可直接写入 True）。"""
    text = f"{sector} {description}".lower()
    return any(pattern.search(text) for pattern in _PERP_PATTERNS)
