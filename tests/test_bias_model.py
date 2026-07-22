"""bias_model.py 관측 기반 성향 추정 테스트."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from bias_model import MIN_VOTES, compute_bias_model, effective_bias  # noqa: E402


def _snapshot(issues):
    return [("t", {"issues": issues})]


def _issue(prog_title, cons_title, target_outlet, target_title):
    return {
        "headlines": [
            {"outlet": "경향신문", "title": prog_title},
            {"outlet": "조선일보", "title": cons_title},
            {"outlet": target_outlet, "title": target_title},
        ]
    }


def test_leans_progressive_when_titles_track_progressive_anchor():
    # 타깃 매체 제목이 매번 진보 앵커 제목과 거의 같음 → 진보 판정
    issues = [
        _issue(
            f"노동계 최저임금 재심의 요구 {i}차 집회",
            f"최저임금 갈등 격화 재계 반발 {i}",
            "테스트지",
            f"노동계 최저임금 재심의 요구 {i}차 집회 열려",
        )
        for i in range(MIN_VOTES + 2)
    ]
    model = compute_bias_model(_snapshot(issues))
    assert model["테스트지"]["lean"] == "progressive", model


def test_insufficient_votes_stays_unclassified():
    issues = [
        _issue("진보 앵커 제목 사례", "보수 앵커 제목 사례", "신생지", "진보 앵커 제목 사례 보도")
        for _ in range(3)  # MIN_VOTES 미달
    ]
    model = compute_bias_model(_snapshot(issues))
    assert model["신생지"]["lean"] is None
    assert effective_bias("신생지", model) == "unknown"


def test_no_vote_without_both_anchors():
    issues = [{
        "headlines": [
            {"outlet": "경향신문", "title": "진보 앵커만 있는 이슈"},
            {"outlet": "테스트지", "title": "진보 앵커만 있는 이슈 보도"},
        ]
    } for _ in range(MIN_VOTES + 5)]
    model = compute_bias_model(_snapshot(issues))
    assert "테스트지" not in model or model["테스트지"]["votes"] == 0


def test_effective_bias_anchor_first():
    assert effective_bias("조선일보", {"조선일보": {"lean": "progressive"}}) == "conservative"


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"ok {name}")
    print("bias_model 테스트 전체 통과")
