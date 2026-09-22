"""Unit tests for Security Sentinel Service and API."""

from app.services.security_sentinel import (
    check_domain_safety,
    scan_dust_poison_tokens,
    scan_token_approvals,
)


def test_check_domain_safety_normal_https():
    """验证正常的官方 HTTPS 域名被判定为安全."""
    res = check_domain_safety("https://story.foundation")
    assert res["is_safe"] is True
    assert res["risk_level"] == "safe"


def test_check_domain_safety_insecure_http():
    """验证不安全的 HTTP 协议触发预警."""
    res = check_domain_safety("http://airdrop-claim-test.com")
    assert res["is_safe"] is False
    assert "HTTPS" in res["reasons"][0]


def test_check_domain_safety_punycode():
    """验证 Punycode 同形异义词仿冒域名被判定为高危."""
    res = check_domain_safety("https://xn--berachn-wxa.com")
    assert res["is_safe"] is False
    assert res["risk_level"] == "dangerous"


def test_scan_token_approvals():
    """验证钱包授权扫描返回得分与撤销链接."""
    addr = "0xd8dA6BF26964aF9D7eEd9e03E53415D37aA96045"
    res = scan_token_approvals(addr)
    assert res["wallet_address"] == addr.lower()
    assert 0 <= res["security_score"] <= 100
    assert "revoke.cash" in res["revoke_url"]
    assert len(res["approvals"]) > 0


def test_scan_dust_poison_tokens():
    """验证嗅探下毒代币输出结构."""
    addr = "0xd8dA6BF26964aF9D7eEd9e03E53415D37aA96045"
    res = scan_dust_poison_tokens(addr)
    assert "poison_tokens_detected" in res
    assert "warning" in res
