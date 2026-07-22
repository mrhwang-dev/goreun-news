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


def test_snapshot_repetition_counts_once():
    # 같은 이슈가 14개 시간별 스냅샷에 반복 수록돼도 (이슈, 매체)당 1표
    issue = {
        "headlines": [
            {"outlet": "경향신문", "title": "노동계 최저임금 재심의 요구", "link": "https://khan/1"},
            {"outlet": "조선일보", "title": "최저임금 갈등 재계 반발", "link": "https://chosun/1"},
            {"outlet": "지역지A", "title": "노동계 최저임금 재심의 요구 집회", "link": "https://local/1"},
        ]
    }
    snapshots = [(f"2026-07-22-{h:02d}", {"issues": [issue]}) for h in range(14)]
    model = compute_bias_model(snapshots)
    assert model["지역지A"]["votes"] == 1, model
    assert model["지역지A"]["lean"] is None


def test_hysteresis_keeps_prior_lean_near_boundary():
    # 7:5 표(score≈0.167)는 신규 진입 기준(0.25) 미달이지만,
    # 직전 판정이 progressive면 완화 경계(0.15) 안이라 유지된다
    def _iss(i, target_title):
        return {"headlines": [
            {"outlet": "경향신문", "title": f"진보 앵커 제목 {i}", "link": f"p{i}"},
            {"outlet": "조선일보", "title": f"보수 앵커 제목 {i}", "link": f"c{i}"},
            {"outlet": "테스트지", "title": target_title, "link": f"t{i}"},
        ]}
    issues = [_iss(i, f"진보 앵커 제목 {i} 보도") for i in range(7)]
    issues += [_iss(100 + i, f"보수 앵커 제목 {100 + i} 보도") for i in range(5)]
    snapshots = [("s", {"issues": issues})]
    fresh = compute_bias_model(snapshots)
    assert fresh["테스트지"]["lean"] == "moderate", fresh  # 신규 기준으로는 중도
    kept = compute_bias_model(snapshots, {"테스트지": {"lean": "progressive"}})
    assert kept["테스트지"]["lean"] == "progressive", kept  # 히스테리시스로 유지


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"ok {name}")
    print("bias_model 테스트 전체 통과")
