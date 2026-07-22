"""유사 기사 클러스터링 알고리즘.

여러 언론사 헤드라인 중 '같은 사건'을 다룬 기사를 결정론적으로 묶는다.
AI 호출 없이 코드로만 동작하므로 시간당 실행에도 비용이 들지 않고,
AI는 이후 단계에서 클러스터의 라벨·요약만 담당한다.

절차:
1) 제목 정규화 — [단독]·[속보] 등 말머리, 따옴표·구두점 제거, 공백 정리,
   영문 소문자화. 매체마다 다른 장식 요소를 걷어내 비교 가능하게 만든다.
2) 특징 추출 — 정규화된 제목의 '문자 2-그램(bigram)' 집합.
   한국어는 조사·어미 변형이 많아 단어 단위 비교가 잘 깨지는데,
   문자 n-그램은 "금리 동결했다/금리 동결 결정"처럼 표현이 달라도
   공통 부분 문자열을 안정적으로 잡아낸다.
3) 유사도 — 두 지표를 함께 쓴다.
   - 자카드 계수 J(A,B) = |A∩B| / |A∪B|
   - 겹침 계수 OV(A,B) = |A∩B| / min(|A|,|B|)
   자카드는 "한은, 금리 동결"(짧은 속보)과 "한국은행 기준금리 동결…배경은"
   (긴 해설)처럼 길이가 크게 다른 같은 사건 쌍에서 낮게 나오는데,
   겹침 계수는 짧은 쪽 기준 포함 비율이라 이런 쌍을 잡아낸다.
   → J ≥ 0.30 또는 OV ≥ 0.40 이면 같은 사건으로 판정.
4) 군집화 — 판정된 쌍을 간선으로 보고 union-find(서로소 집합)로
   연결 요소를 하나의 클러스터로 묶는다. O(n²) 비교지만 24시간치
   헤드라인은 수백 건 수준이라 충분히 빠르다.
5) 랭킹 — (참여 매체 수 내림차순, 최신 기사 시각 내림차순).
   여러 매체가 동시에 다룬 사건일수록 중요한 이슈로 본다.
"""

from __future__ import annotations

import math
import re
from collections import defaultdict
from datetime import datetime, timezone


def normalize_title(title: str) -> str:
    t = re.sub(r"\[[^\]]{1,14}\]|【[^】]{1,14}】", " ", title)  # 말머리 제거
    t = re.sub(r"[\"'“”‘’`·…‥,\.\!\?~〈〉<>()\{\}|/\\\-—–:;]", " ", t)
    return re.sub(r"\s+", " ", t).strip().lower()


def char_bigrams(text: str) -> frozenset:
    s = text.replace(" ", "")
    if len(s) < 2:
        return frozenset({s} if s else set())
    return frozenset(s[i : i + 2] for i in range(len(s) - 1))


def jaccard(a: frozenset, b: frozenset) -> float:
    if not a or not b:
        return 0.0
    inter = len(a & b)
    if inter == 0:
        return 0.0
    return inter / (len(a) + len(b) - inter)


def overlap(a: frozenset, b: frozenset) -> float:
    """겹침 계수: 짧은 쪽 집합 기준 교집합 비율 (길이 차이에 견고)."""
    if not a or not b:
        return 0.0
    return len(a & b) / min(len(a), len(b))


def is_same_event(a: frozenset, b: frozenset, jaccard_th: float, overlap_th: float) -> bool:
    return jaccard(a, b) >= jaccard_th or overlap(a, b) >= overlap_th


class _UnionFind:
    def __init__(self, n: int):
        self.parent = list(range(n))

    def find(self, x: int) -> int:
        while self.parent[x] != x:
            self.parent[x] = self.parent[self.parent[x]]  # 경로 압축
            x = self.parent[x]
        return x

    def union(self, a: int, b: int) -> None:
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.parent[rb] = ra


def cluster_items(
    items: list[dict], jaccard_th: float, overlap_th: float = 0.40
) -> list[list[dict]]:
    """헤드라인 목록을 유사도 기준으로 군집화해 랭킹 순으로 반환한다.

    items: [{"title", "link", "outlet", "ts": datetime}, ...]
    """
    feats = [char_bigrams(normalize_title(it["title"])) for it in items]
    uf = _UnionFind(len(items))

    for i in range(len(items)):
        for j in range(i + 1, len(items)):
            if is_same_event(feats[i], feats[j], jaccard_th, overlap_th):
                uf.union(i, j)

    groups: dict[int, list[int]] = defaultdict(list)
    for i in range(len(items)):
        groups[uf.find(i)].append(i)

    clusters = []
    for idxs in groups.values():
        members = [items[i] for i in idxs]
        # 같은 매체가 같은 사건을 여러 번 송고한 경우 최신 1건만 유지
        by_outlet: dict[str, dict] = {}
        for m in members:
            prev = by_outlet.get(m["outlet"])
            if prev is None or m["ts"] > prev["ts"]:
                by_outlet[m["outlet"]] = m
        clusters.append(sorted(by_outlet.values(), key=lambda m: m["ts"], reverse=True))

    epoch = datetime.fromtimestamp(0, tz=timezone.utc)

    def rank_key(cluster: list[dict]):
        outlets = len({m["outlet"] for m in cluster})
        latest = max((m["ts"] for m in cluster), default=epoch)
        return (outlets, latest)

    clusters.sort(key=rank_key, reverse=True)
    return clusters


# ── 이슈 점수·핫 분야 슬롯 배분 알고리즘 ────────────────────────────────
#
# 1) 이슈 점수 (Cluster Size 최우선):
#    score(이슈) = (참여 매체 수)^SIZE_EXPONENT × e^(-경과시간/감쇠상수)
#    - 매체 수에 지수(기본 2.0)를 걸어, 많은 언론사가 동시에 다룬 대형
#      사건일수록 압도적으로 높은 점수를 받는다. (12개 매체 이슈는
#      3개 매체 이슈의 4배가 아니라 16배)
#    - 최신성은 지수 감쇠로 유지 — 오래된 대형 이슈는 서서히 내려간다.
# 2) 최상단 고정: 점수 상위 TOP_PIN_COUNT(기본 3)개는 분야 배분과
#    무관하게 무조건 그리드 1~3위를 차지한다.
# 3) 분야별 열기: heat(분야) = Σ (매체 수 × e^(-경과시간/감쇠상수)) —
#    필터 칩의 🔥 표시와 나머지 슬롯의 비례 배분에 쓴다.
# 4) 나머지 슬롯 배분: 동트(D'Hondt) 방식.
#    다음 슬롯을 heat/(이미 받은 슬롯 수 + 1)이 가장 큰 분야에 준다.
#    - 이슈가 있는 분야는 최소 1슬롯 보장 (완전히 묻히지 않게)
#    - 분야당 상한(cap)으로 한 분야의 독식 방지


def issue_score(issue: dict, decay_hours: float, size_exponent: float) -> float:
    """이슈 점수: (매체 수)^지수 × 최신성 감쇠. 클러스터 크기가 지배한다."""
    now = datetime.now(timezone.utc)
    age_h = max(0.0, (now - issue["latest_ts"]).total_seconds() / 3600)
    return (issue["outlet_count"] ** size_exponent) * math.exp(-age_h / decay_hours)


def category_heat(issues: list[dict], decay_hours: float) -> dict[str, float]:
    """분야별 열기 점수를 계산한다. issues 항목은 category/outlet_count/latest_ts 필요."""
    now = datetime.now(timezone.utc)
    heat: dict[str, float] = defaultdict(float)
    for issue in issues:
        age_h = max(0.0, (now - issue["latest_ts"]).total_seconds() / 3600)
        heat[issue["category"]] += issue["outlet_count"] * math.exp(-age_h / decay_hours)
    return dict(heat)


def allocate_slots(
    issues: list[dict],
    total: int,
    cap: int,
    decay_hours: float,
    size_exponent: float = 2.0,
    pin_top: int = 3,
) -> tuple[list[dict], dict[str, float], dict[str, int]]:
    """이슈 점수순 정렬 + 상위 고정 + 나머지는 열기 비례 분야 배분.

    반환: (선택된 이슈 목록 — 점수 내림차순, 분야별 열기, 분야별 슬롯 수)
    """
    heat = category_heat(issues, decay_hours)

    # 점수순 정렬 — 클러스터 크기가 큰 대형 이슈가 앞으로 온다
    ranked = sorted(
        issues, key=lambda i: issue_score(i, decay_hours, size_exponent), reverse=True
    )

    # 점수 상위 pin_top개는 분야와 무관하게 무조건 최상단 고정
    pinned = ranked[: min(pin_top, total)]
    rest = ranked[len(pinned):]
    remaining_total = total - len(pinned)

    avail: dict[str, int] = defaultdict(int)
    for issue in rest:
        avail[issue["category"]] += 1

    cats = sorted(avail, key=lambda c: heat.get(c, 0.0), reverse=True)
    slots = {c: 1 for c in cats[:remaining_total]}
    remaining = remaining_total - len(slots)

    # 동트 방식: heat/(현재 슬롯+1)이 가장 큰 분야에 다음 슬롯
    while remaining > 0:
        candidates = [c for c in slots if slots[c] < min(cap, avail[c])]
        if not candidates:
            break
        best = max(candidates, key=lambda c: heat.get(c, 0.0) / (slots[c] + 1))
        slots[best] += 1
        remaining -= 1

    taken: dict[str, int] = defaultdict(int)
    selected_rest = []
    for issue in rest:  # rest는 이미 점수순
        cat = issue["category"]
        if cat in slots and taken[cat] < slots[cat]:
            selected_rest.append(issue)
            taken[cat] += 1

    # 고정 이슈도 분야 슬롯 집계에 반영 (탭 뱃지 표시용)
    for issue in pinned:
        slots[issue["category"]] = slots.get(issue["category"], 0) + 1

    return pinned + selected_rest, heat, slots
