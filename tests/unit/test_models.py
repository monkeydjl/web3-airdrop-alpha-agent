# ──────────────────────────────────────────────
# 单元测试 — Pydantic 模型行为
# 对应 CONVENTIONS.md §9.1 单元测试规范
# ──────────────────────────────────────────────

from app.models import ScoreResult, NarrativeResult


class TestScoreResultBehavior:
    def test_farm_requires_strong_reason(self):
        """可解释性测试：FARM 项目 reason >= 2 条且含正向信号"""
        r = ScoreResult(
            score=88,
            label="FARM",
            confidence=0.9,
            reason=["strong airdrop signal", "doxxed team", "low token risk"],
        )
        assert len(r.reason) >= 2
        assert any("airdrop" in s.lower() or "signal" in s.lower() for s in r.reason)

    def test_ignore_requires_negative_signal(self):
        r = ScoreResult(
            score=20,
            label="IGNORE",
            confidence=0.7,
            reason=["anon team", "high rug risk"],
        )
        assert r.label == "IGNORE"
        assert any("risk" in s.lower() or "anon" in s.lower() for s in r.reason)

    def test_confidence_range(self):
        assert 0.0 <= ScoreResult(score=50, label="WATCH", confidence=0.5, reason=["a", "b"]).confidence <= 1.0


class TestNarrativeResultBehavior:
    def test_frozen_model_immutable(self):
        r = NarrativeResult(sector="L2", stage="growth", heat_score=0.8, timing="peak")
        try:
            r.heat_score = 0.9
            assert False, "frozen model must not be mutable"
        except Exception:
            pass
