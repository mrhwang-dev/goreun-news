"""기사 품질 필터 알고리즘 — 광고성 기사·우라까이(전재/복제) 대응.

1) 광고성(보도자료·홍보) 감지 — 가중 마커 점수:
   강신호(가중 2): ㈜ 표기, 프로모션·특가·체험단·협찬 등 홍보 전용 어휘
   약신호(가중 1): 이벤트·출시·기념·수상 등 (진성 뉴스에도 나올 수 있는 어휘)
   합계 3점 이상이면 홍보성으로 판단해 수집 단계에서 제외한다.
   ('신제품 출시'=1점 유지, '㈜OO 출시 기념 이벤트'=2+2+1=5점 제외)

2) 우라까이(전재) 감지 — 클러스터 안 제목 다양성:
   통신사 기사를 그대로 받아쓴 전재 클러스터는 매체 수는 많아도
   정규화 제목이 사실상 한 종류다. distinct 제목 수가 매체 수의 1/3
   미만이면 전재성으로 보고, 랭킹용 매체 수를 distinct 수준으로 감쇠한다
   (표시는 그대로, 점수만 — 전재로 이슈 중요도가 부풀지 않게).
"""

from __future__ import annotations

from cluster import normalize_title

AD_STRONG = (
    "㈜", "프로모션", "특가", "체험단", "협찬", "브랜드데이", "앰배서더",
    "런칭 기념", "출시 기념", "사전예약 혜택", "쿠폰 지급", "경품", "할인전",
    "공식 스토어", "완판", "역대급 혜택",
)
AD_WEAK = (
    "이벤트", "출시", "기념", "혜택", "업무협약", "MOU", "선정", "수상",
    "캠페인", "페스티벌", "공모", "런칭", "봉사활동", "기부",
)

PROMO_THRESHOLD = 3


def ad_score(title: str) -> int:
    score = 0
    for marker in AD_STRONG:
        if marker in title:
            score += 2
    for marker in AD_WEAK:
        if marker in title:
            score += 1
    return score


def is_promotional(title: str) -> bool:
    return ad_score(title) >= PROMO_THRESHOLD


def distinct_title_count(titles: list[str]) -> int:
    """정규화 후 서로 다른 제목 수 — 전재(우라까이) 클러스터 판별 재료."""
    return len({normalize_title(t) for t in titles})


def rank_outlet_count(outlet_count: int, titles: list[str]) -> int:
    """랭킹용 매체 수. 전재성 클러스터면 distinct 제목 수 수준으로 감쇠."""
    distinct = distinct_title_count(titles)
    if distinct * 3 < outlet_count:
        return max(1, distinct)
    return outlet_count
