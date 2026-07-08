# ──────────────────────────────────────────────
# Golden 回归测试
# 对应 docs/GOLDEN_TEST_CASES.md 定义的黄金用例
# 评分逻辑（scorer.py）实现后取消注释断言
# ──────────────────────────────────────────────

import json
from pathlib import Path

GOLDEN_PATH = Path(__file__).parent / "projects.jsonl"


def _load_cases() -> list[dict]:
    return [json.loads(line) for line in GOLDEN_PATH.read_text(encoding="utf-8").splitlines() if line.strip()]


class TestGoldenDataset:
    def test_dataset_present_and_well_formed(self):
        cases = _load_cases()
        assert len(cases) >= 3, "golden 集至少需要 3 个用例"
        for c in cases:
            assert "id" in c and "input" in c and "expected" in c
            assert c["expected"]["label"] in ("FARM", "WATCH", "IGNORE")

    def test_each_case_has_reason_contains(self):
        for c in _load_cases():
            assert isinstance(c["expected"]["reason_contains"], list)
            assert len(c["expected"]["reason_contains"]) >= 1


# ── 以下用例待 scorer 实现后启用 ──────────────
# def test_golden_gt001():
#     from app.agents.scorer import score_project
#     case = next(c for c in _load_cases() if c["id"] == "GT-001")
#     result = score_project(case["input"])
#     assert result.score == case["expected"]["score"]
#     assert result.label == case["expected"]["label"]
#     for token in case["expected"]["reason_contains"]:
#         assert any(token in r for r in result.reason)
