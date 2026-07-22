"""cluster.py 순수 로직 자동 테스트 — CI에서 빌드 전에 실행된다.

실행: python tests/test_cluster.py
"""

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from cluster import (  # noqa: E402
    allocate_slots,
    char_bigrams,
    cluster_items,
    issue_score,
    jaccard,
    normalize_title,
    overlap,
)

NOW = datetime(2026, 7, 22, 9, 0, tzinfo=timezone.utc)


def test_normalize_title():
    assert normalize_title("[속보] 한은, 기준금리 동결!") == "한은 기준금리 동결"
    assert normalize_title("【단독】 A사 “B 인수”…업계 촉각") == "a사 b 인수 업계 촉각"


def test_similarity():
    a = char_bigrams(normalize_title("[속보] 한은, 기준금리 동결 결정"))
    b = char_bigrams(normalize_title("한국은행 기준금리 동결…가계부채 부담"))
    c = char_bigrams(normalize_title("프로야구 올스타전 개최"))
    assert overlap(a, b) >= 0.40, "같은 사건은 겹침 계수로 잡혀야 함"
    assert jaccard(a, c) == 0.0 and overlap(a, c) == 0.0, "무관한 기사는 0"


def test_cluster_items():
    items = [
        {"title": "[속보] 한은, 기준금리 동결 결정", "link": "a1", "outlet": "A", "ts": NOW},
        {"title": "한국은행 기준금리 동결…가계부채 부담", "link": "b1", "outlet": "B",
         "ts": NOW - timedelta(minutes=10)},
        {"title": "금통위, 기준금리 동결 만장일치", "link": "c1", "outlet": "C",
         "ts": NOW - timedelta(minutes=5)},
        {"title": "프로야구 올스타전 개최", "link": "c2", "outlet": "C",
         "ts": NOW - timedelta(hours=1)},
    ]
    clusters = cluster_items(items, 0.30, 0.40)
    assert len(clusters) == 2
    assert len(clusters[0]) == 3, "기준금리 3건이 한 클러스터"
    # 같은 매체 중복 송고는 최신 1건만
    items.append({"title": "한은 기준금리 동결 확정", "link": "a2", "outlet": "A",
                  "ts": NOW + timedelta(minutes=1)})
    clusters = cluster_items(items, 0.30, 0.40)
    outlets = [m["outlet"] for m in clusters[0]]
    assert outlets.count("A") == 1


def test_allocate_slots_pins_big_clusters():
    issues = [
        {"label": "대형", "category": "사회", "outlet_count": 12, "latest_ts": NOW - timedelta(hours=2)},
        {"label": "최신소형", "category": "경제", "outlet_count": 2, "latest_ts": NOW},
    ] + [
        {"label": f"중형{k}", "category": "정치", "outlet_count": 4, "latest_ts": NOW - timedelta(hours=1)}
        for k in range(6)
    ]
    selected, heat, slots = allocate_slots(issues, 6, 3, 6.0, size_exponent=2.0, pin_top=1, min_slots=1)
    assert selected[0]["label"] == "대형", "클러스터 크기 1위가 최상단 고정"
    assert issue_score(issues[0], 6.0, 2.0) > issue_score(issues[1], 6.0, 2.0) * 10


def test_allocate_slots_min_per_category():
    issues = [
        {"label": f"경제{k}", "category": "경제", "outlet_count": 8, "latest_ts": NOW}
        for k in range(10)
    ] + [
        {"label": "IT1", "category": "IT·과학", "outlet_count": 2, "latest_ts": NOW - timedelta(hours=3)},
        {"label": "IT2", "category": "IT·과학", "outlet_count": 2, "latest_ts": NOW - timedelta(hours=4)},
    ]
    selected, _, slots = allocate_slots(issues, 8, 5, 6.0, size_exponent=2.0, pin_top=0, min_slots=2)
    assert slots.get("IT·과학", 0) >= 2, "약세 분야도 최소 슬롯 보장"


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"ok {name}")
    print("cluster.py 테스트 전체 통과")
