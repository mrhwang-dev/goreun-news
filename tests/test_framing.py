"""프레임 체크 알고리즘 골든셋 테스트 — CI에서 빌드 전에 실행된다.

실행: python tests/test_framing.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from cluster import (  # noqa: E402
    detect_honorifics,
    extract_frame_candidates,
    stem_token,
)
from summarize import framing_passes_gate  # noqa: E402


def test_stem_token():
    assert stem_token("동결했다") == "동결"
    assert stem_token("매도에") == "매도"
    assert stem_token("규제를") == "규제"
    assert stem_token("에서") == "에서"  # 어근 2자 미달이면 벗기지 않음
    assert stem_token("증명") == "증명"


def test_candidates_merge_variants():
    heads = [
        {"title": "한은 기준금리 동결했다", "bias": "conservative"},
        {"title": "한은, 기준금리 동결 결정", "bias": "progressive"},
        {"title": "기준금리 동결에 시장 안도", "bias": "moderate"},
    ]
    c = extract_frame_candidates(heads)
    assert "동결" in c["common"], f"어근 병합 실패: {c}"


def test_side_only_substring_guard():
    heads = [
        {"title": '오세훈 "규제 실패 몸소 증명"', "bias": "conservative"},
        {"title": '오세훈, "규제 실패" 공세', "bias": "progressive"},
    ]
    c = extract_frame_candidates(heads)
    assert "규제 실패" not in c["progressive"], "상대 제목 부분 문자열 오판"
    assert any("증명" in w or "몸소" in w for w in c["conservative"])


def test_detect_honorifics():
    heads = [
        {"title": "李대통령, 근저당 매도 논란", "bias": "conservative"},
        {"title": "이재명 대통령 근저당 해명", "bias": "progressive"},
        {"title": "李대통령 발언 파장", "bias": "conservative"},
    ]
    found = {h["text"]: h for h in detect_honorifics(heads)}
    assert "李대통령" in found and found["李대통령"]["sides"].get("conservative") == 2
    assert "이재명 대통령" in found
    # 좌측 경계: 단어 중간을 인명으로 오인하지 않아야 한다
    bogus = detect_honorifics([{"title": "국민의힘 대표 경선 시작", "bias": "conservative"},
                               {"title": "더불어민주당 대표 발언", "bias": "progressive"}])
    assert not [b for b in bogus if b["style"] == "이름+직함"], bogus


def test_framing_gate():
    assert framing_passes_gate("보수 매체는 발언 인용을, 진보 매체는 판결 내용을 제목에 올렸다.")
    assert not framing_passes_gate("보수 매체가 교묘하게 발언을 배치했다.")
    assert not framing_passes_gate("진보 매체의 노골적 프레임이다.")


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"ok {name}")
    print("framing 테스트 전체 통과")
