"""quality.py 광고성·우라까이 필터 테스트."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from quality import is_promotional, rank_outlet_count  # noqa: E402


def test_promotional_detected():
    assert is_promotional("㈜엔씨 '아이온2' 출시 기념 이벤트 시작")
    assert is_promotional("OO카드, 여름 특가 프로모션 경품 증정")


def test_genuine_news_kept():
    assert not is_promotional("삼성전자, 신형 반도체 양산 출시")
    assert not is_promotional("정부, 소상공인 지원 대책 발표")
    assert not is_promotional("한은 기준금리 동결")


def test_syndication_dampens_rank():
    # 8개 매체가 사실상 같은 제목(전재) → 랭킹용 매체 수 감쇠
    titles = ["[속보] 코스피 급락"] * 5 + ["코스피 급락!"] * 3
    assert rank_outlet_count(8, titles) <= 2
    # 제목이 다양하면 그대로
    varied = [f"코스피 급락 관련 분석 {i}" for i in range(8)]
    assert rank_outlet_count(8, varied) == 8


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"ok {name}")
    print("quality 테스트 전체 통과")
