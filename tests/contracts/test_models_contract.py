# ──────────────────────────────────────────────
# 契约测试 — Pydantic 模型 Schema 校验
# 对应 CONVENTIONS.md §9.2 契约测试规范
# 任何 Pydantic 模型字段变更必须先更新本文件
# ──────────────────────────────────────────────

from app.models import (
    ApiResponse,
    NarrativeResult,
    TeamResult,
    RiskResult,
    TokenomicsResult,
    ScoreResult,
    RunRequest,
    RunResponse,
)


class TestApiResponseContract:
    def test_valid_ok_response(self):
        resp = ApiResponse(ok=True, data={"x": 1})
        assert resp.ok is True
        assert resp.data == {"x": 1}
        assert resp.error is None

    def test_error_response_requires_error_dict(self):
        resp = ApiResponse(ok=False, error={"code": "E1", "message": "boom"})
        assert resp.ok is False
        assert resp.error["code"] == "E1"


class TestNarrativeResultContract:
    def test_valid_narrative(self):
        r = NarrativeResult(sector="L2", stage="growth", heat_score=0.8, timing="peak")
        assert r.heat_score == 0.8

    def test_extra_fields_forbidden(self):
        import pydantic
        try:
            NarrativeResult(sector="L2", stage="growth", heat_score=0.8, timing="peak", extra=1)
            assert False, "extra field should be forbidden"
        except pydantic.ValidationError:
            pass

    def test_invalid_stage_rejected(self):
        import pydantic
        try:
            NarrativeResult(sector="L2", stage="invalid", heat_score=0.8, timing="peak")
            assert False, "invalid stage should be rejected"
        except pydantic.ValidationError:
            pass

    def test_heat_score_out_of_range(self):
        import pydantic
        try:
            NarrativeResult(sector="L2", stage="growth", heat_score=1.5, timing="peak")
            assert False, "heat_score > 1.0 should be rejected"
        except pydantic.ValidationError:
            pass


class TestTeamResultContract:
    def test_valid_team(self):
        r = TeamResult(team_score=0.7, team_type="doxxed")
        assert r.team_score == 0.7
        assert r.team_flags == []

    def test_invalid_team_type(self):
        import pydantic
        try:
            TeamResult(team_score=0.7, team_type="unknown_type")
            assert False
        except pydantic.ValidationError:
            pass


class TestRiskResultContract:
    def test_valid_risk(self):
        r = RiskResult(token_risk=0.3, risk_flags=["rug"], unlock_pressure="low")
        assert r.unlock_pressure == "low"


class TestTokenomicsResultContract:
    def test_valid_tokenomics(self):
        r = TokenomicsResult(vc_share=0.25, team_share=0.2, unlock_penalty=0.1)
        assert r.vc_share == 0.25


class TestScoreResultContract:
    def test_valid_score(self):
        r = ScoreResult(
            score=67,
            label="WATCH",
            confidence=0.8,
            reason=["strong airdrop signal", "early narrative"],
        )
        assert r.label == "WATCH"

    def test_reason_min_length(self):
        import pydantic
        try:
            ScoreResult(score=67, label="WATCH", confidence=0.8, reason=["only one"])
            assert False, "reason requires >= 2 items"
        except pydantic.ValidationError:
            pass

    def test_invalid_label(self):
        import pydantic
        try:
            ScoreResult(score=67, label="MAYBE", confidence=0.8, reason=["a", "b"])
            assert False
        except pydantic.ValidationError:
            pass


class TestRunRequestContract:
    def test_defaults(self):
        req = RunRequest()
        assert req.source == "seed"
        assert req.dry_run is False
        assert req.limit == 50

    def test_limit_bounds(self):
        import pydantic
        for bad in (0, 501):
            try:
                RunRequest(limit=bad)
                assert False, f"limit={bad} should be rejected"
            except pydantic.ValidationError:
                pass


class TestRunResponseContract:
    def test_valid(self):
        r = RunResponse(run_id="r1", status="completed", project_count=10, elapsed_ms=123.4)
        assert r.status == "completed"
