"""Unit tests for Sybil Defense Dossier Generator Service and API."""

from app.services.sybil_defense_dossier import generate_sybil_defense_dossier


def test_generate_sybil_defense_dossier():
    """验证生成的自证报告包含独立评分与规范 Markdown."""
    addr = "0xd8dA6BF26964aF9D7eEd9e03E53415D37aA96045"
    dossier = generate_sybil_defense_dossier(
        wallet_address=addr,
        project_name="LayerZero Foundation",
        appeal_reason="False positive cluster tag",
    )

    assert dossier["ok"] is True
    assert dossier["wallet_address"] == addr
    assert dossier["independence_score"] >= 40
    assert "markdown_dossier" in dossier

    md = dossier["markdown_dossier"]
    assert "# Web3 Airdrop Sybil Defense" in md
    assert "LayerZero Foundation" in md
    assert addr in md
    assert "Rebuttal of Sybil Cluster Patterns" in md
