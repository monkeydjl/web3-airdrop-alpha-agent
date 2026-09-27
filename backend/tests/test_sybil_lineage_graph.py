"""Tests for Sybil Lineage — 诚实口径契约.

2026-09-23 审计后，此服务不再用哈希取模编造资金关联，也不生成假地址：
- 服务端不猜测链上事实，只处理用户显式声明的 declared_links
- 输出不含任何服务端捏造的地址（如 0xfa1100...funder）
- 教学红线作为 education 字段返回
"""

from app.services.sybil_lineage_graph import analyze_wallet_lineage

WALLETS = [
    "0xaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
    "0xbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
    "0xcccccccccccccccccccccccccccccccccccccccc",
]


def test_single_or_empty_insufficient_input():
    res_single = analyze_wallet_lineage(["0x1111111111111111111111111111111111111111"])
    assert res_single["ok"] is True
    assert res_single["lineage_status"] == "insufficient_input"
    assert res_single["isolation_score"] is None
    assert res_single["sybil_cluster_detected"] is False

    res_empty = analyze_wallet_lineage([])
    assert res_empty["ok"] is True
    assert res_empty["lineage_status"] == "insufficient_input"


def test_no_fabricated_findings_without_declared_links():
    """无声明关联时，不得出现任何服务端编造的「发现」与假地址."""
    res = analyze_wallet_lineage(WALLETS)
    assert res["ok"] is True
    assert res["lineage_status"] == "no_declared_links"
    assert res["sybil_cluster_detected"] is False
    assert res["fatal_red_flags"] == []
    assert res["links"] == []
    # 节点只包含用户输入的真实地址，无 0xfa1100/0xce8000 类捏造节点
    for node in res["nodes"]:
        assert node["id"] in [w.lower() for w in WALLETS]


def test_declared_links_are_reflected_but_not_invented():
    """只有用户显式声明的关联才出现在结果中."""
    declared = [{"source": WALLETS[0], "target": WALLETS[1], "label": "误转"}]
    res = analyze_wallet_lineage(WALLETS, declared_links=declared)
    assert res["sybil_cluster_detected"] is True
    assert res["lineage_status"] == "user_declared_links_found"
    assert len(res["links"]) == 1
    assert res["links"][0]["source"] == WALLETS[0]
    assert res["links"][0]["target"] == WALLETS[1]
    assert "误转" in res["fatal_red_flags"][0]

    # 未声明的第三钱包不得被牵连
    linked_ids = {res["links"][0]["source"], res["links"][0]["target"]}
    assert WALLETS[2] not in linked_ids


def test_education_rules_present():
    res = analyze_wallet_lineage(WALLETS)
    rules = res["education"]["critical_rules"]
    assert isinstance(rules, list)
    assert len(rules) >= 4
    assert any("互转" in r for r in rules)
