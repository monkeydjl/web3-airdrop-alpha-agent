"""Unit tests for user preferences schema and validation (W12-08)."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.routers.v1.user_preferences import (
    UserPreferencesData,
    UserPreferencesPatchPayload,
    UserPreferencesPutPayload,
    _parse_preferences_dict,
)


def test_user_preferences_defaults() -> None:
    """验证默认用户偏好结构与取值符合 ROADMAP §25.6。"""
    prefs = UserPreferencesData()
    assert prefs.sector_preferences == {}
    assert prefs.risk_tolerance == 0.5
    assert prefs.preferred_stage == []
    assert prefs.notifications == {}
    assert prefs.language == "zh"
    assert prefs.theme == "dark"


def test_user_preferences_validation() -> None:
    """验证风险偏好取值范围 [0.0, 1.0]。"""
    # 正常边界
    p0 = UserPreferencesData(risk_tolerance=0.0)
    assert p0.risk_tolerance == 0.0
    p1 = UserPreferencesData(risk_tolerance=1.0)
    assert p1.risk_tolerance == 1.0

    # 越界失败
    with pytest.raises(ValidationError):
        UserPreferencesData(risk_tolerance=-0.1)

    with pytest.raises(ValidationError):
        UserPreferencesData(risk_tolerance=1.01)


def test_user_preferences_extra_fields() -> None:
    """验证支持扩展字段（extra='allow'），便于未来 UI 前端个性化项扩展。"""
    data = {
        "sector_preferences": {"L2": 1.2},
        "risk_tolerance": 0.8,
        "custom_dashboard_layout": "grid",
        "hide_zero_scores": True,
    }
    prefs = UserPreferencesData(**data)
    dumped = prefs.model_dump()
    assert dumped["custom_dashboard_layout"] == "grid"
    assert dumped["hide_zero_scores"] is True


def test_put_payload_validation() -> None:
    """验证 PUT 载荷校验。"""
    with pytest.raises(ValidationError):
        UserPreferencesPutPayload(risk_tolerance=2.0)

    valid = UserPreferencesPutPayload(
        sector_preferences={"Restaking": 1.5},
        risk_tolerance=0.7,
        language="en",
    )
    assert valid.sector_preferences["Restaking"] == 1.5
    assert valid.risk_tolerance == 0.7
    assert valid.language == "en"


def test_patch_payload_validation() -> None:
    """验证 PATCH 增量载荷支持全字段可选。"""
    empty_patch = UserPreferencesPatchPayload()
    assert empty_patch.sector_preferences is None
    assert empty_patch.risk_tolerance is None

    with pytest.raises(ValidationError):
        UserPreferencesPatchPayload(risk_tolerance=1.5)

    valid_patch = UserPreferencesPatchPayload(theme="light")
    assert valid_patch.theme == "light"


def test_parse_preferences_dict() -> None:
    """验证 JSON 解析容错与降级。"""
    assert _parse_preferences_dict(None) == {}
    assert _parse_preferences_dict("") == {}
    assert _parse_preferences_dict("invalid-json") == {}
    assert _parse_preferences_dict("[1, 2, 3]") == {}
    parsed = _parse_preferences_dict('{"language": "en", "risk_tolerance": 0.9}')
    assert parsed["language"] == "en"
    assert parsed["risk_tolerance"] == 0.9
