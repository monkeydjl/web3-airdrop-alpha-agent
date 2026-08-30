"""Shared signal detection for the P2 community/content collectors.

Discord / Reddit / Medium / Mirror 都是「内容里提到某项目」的二阶信号源，
不是项目目录。它们共用一个关键词 → 信号类型的映射，以及一套轻量项目名
启发式（与 twitter.py 的同源策略一致：宁可留 Unknown，也不臆造赛道）。

不属于采集器，勿当作数据源注册。
"""

from __future__ import annotations

import re

# 信号关键词 → 信号类型（与 twitter.py::SIGNAL_KEYWORDS 语义一致）
SIGNAL_KEYWORDS: dict[str, str] = {
    "testnet": "testnet",
    "mainnet": "mainnet",
    "points": "points",
    "airdrop": "airdrop",
    "funding": "funding",
    "raised": "funding",
    "invest": "funding",
    "tge": "tge",
    "token launch": "launch",
    "whitelist": "whitelist",
}


def detect_signal(text: str) -> tuple[str | None, str | None]:
    """从一段文本里探测首个命中的信号类型与命中词。"""
    lowered = text.lower()
    for keyword, signal_type in SIGNAL_KEYWORDS.items():
        if keyword in lowered:
            return signal_type, keyword
    return None, None


# 常见非项目词：内容标题里这些词不等于项目名。
NAME_STOP_WORDS: frozenset[str] = frozenset(
    {
        "airdrop",
        "airdropalpha",
        "crypto",
        "cryptocurrency",
        "blockchain",
        "web3",
        "token",
        "tokens",
        "testnet",
        "mainnet",
        "points",
        "guide",
        "list",
        "top",
        "best",
        "new",
        "how",
        "why",
        "what",
        "when",
        "the",
        "a",
        "an",
        "and",
        "for",
        "with",
        "your",
        "you",
        "this",
        "that",
    }
)


def extract_name(text: str) -> str | None:
    """从内容标题/正文里提取一个候选项目名（启发式，可能回退为 None）。

    优先级：URL 主域名 → CamelCase 词 → 首字母大写词。
    """
    url_match = re.search(r"https?://(?:www\.)?([^/\s]+)", text)
    if url_match:
        domain = url_match.group(1).lower()
        for noisy in ("medium.com", "mirror.xyz", "reddit.com", "discord.com", "discord.gg"):
            if noisy in domain:
                break
        else:
            parts = domain.split(".")
            if len(parts) >= 2 and len(parts[-2]) >= 3:
                return parts[-2].capitalize()

    camel = re.findall(r"\b[A-Z][a-z]+[A-Z][a-zA-Z0-9]+\b", text)
    for word in camel:
        if word.lower() not in NAME_STOP_WORDS:
            return str(word)

    capitalized = re.findall(r"\b[A-Z][a-zA-Z0-9]{2,}\b", text)
    for word in capitalized:
        if word.lower() not in NAME_STOP_WORDS:
            return str(word)

    return None
