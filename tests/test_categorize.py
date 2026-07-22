"""categorize.py 분야 분류 알고리즘 테스트."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from categorize import classify  # noqa: E402


def test_politics_not_society():
    # 특검·수사 어휘가 섞여도 정치 어휘가 강하면 정치
    cat, margin = classify(
        ["김건희 특검, 관저 이전 의혹 수사 확대", "특검 '관저 의혹' 대통령실 압수수색",
         "여야, 특검 수사 놓고 공방"],
        ["조선일보", "경향신문", "MBN"],
    )
    assert cat == "정치", (cat, margin)


def test_economy():
    cat, _ = classify(
        ["한은 기준금리 동결", "코스피 급등…환율 하락", "가계부채 우려 지속"],
        ["한국경제", "머니투데이"],
    )
    assert cat == "경제"


def test_it_outlet_prior():
    # 키워드가 약해도 IT 전문지가 다수면 IT·과학
    cat, _ = classify(
        ["삼성, 미스트랄에 대규모 투자 검토", "신형 갤럭시 공개 임박"],
        ["전자신문", "블로터", "IT조선"],
    )
    assert cat == "IT·과학"


def test_ambiguous_falls_back_to_llm():
    cat, margin = classify(["오늘의 주요 단신 모음"], ["조선일보"])
    assert cat is None, (cat, margin)


def test_society_disaster():
    cat, _ = classify(
        ["수도권 폭우로 지하철 지연", "출근길 침수 피해 속출"],
        ["경향신문", "세계일보"],
    )
    assert cat == "사회"


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"ok {name}")
    print("categorize 테스트 전체 통과")
