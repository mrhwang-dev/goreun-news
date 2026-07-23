"""네이버 데이터랩 검색어트렌드 API로 키워드의 검색량 추이를 조회한다.

트렌드 키워드가 '실제로 검색이 늘고 있는지(📈 상승)'를 판별해 상승 키워드를
우선 노출한다. NAVER API HUB 게이트웨이 + X-NCP-APIGW 인증(검색 API와 동일 계열).
자격증명(NAVER_CLIENT_ID/SECRET) 미설정이면 빈 결과를 반환한다.
"""

from __future__ import annotations

import json
import os
import re
import urllib.request
from datetime import datetime, timedelta, timezone

# 데이터랩(통합 검색어 트렌드)은 검색 API(NCP 게이트웨이)와 달리 클래식 도메인 +
# 클래식 인증(X-Naver-Client-*)을 쓴다. 단독으로만 실어야 하며 NCP 헤더와 섞으면 401.
ENDPOINT = "https://openapi.naver.com/v1/datalab/search"
KST = timezone(timedelta(hours=9))
GROUP_MAX = 5   # 요청당 키워드 그룹 상한 (데이터랩 제약)
LOOKBACK_DAYS = 14


def _rising(series: list[dict]) -> tuple[bool, float]:
    """일별 ratio 시계열에서 최근 상승 여부와 점수(최근-이전 평균차)를 계산한다."""
    ratios = [d.get("ratio", 0.0) for d in series]
    if len(ratios) < 6:
        return False, 0.0
    recent = sum(ratios[-3:]) / 3
    earlier = sum(ratios[:-3]) / max(len(ratios) - 3, 1)
    if earlier <= 0:
        return recent > 0, recent
    return recent >= earlier * 1.3, recent - earlier


# 이슈 제목에서 검색어로 부적합한 일반 명사/서술어(고유성 낮음)를 제외.
_TREND_STOP = {
    "관련", "논란", "발표", "결정", "추진", "확대", "대책", "예시", "공개", "계획",
    "의혹", "방침", "조치", "입장", "우려", "전망", "가능성", "여부", "이유", "상황",
    "문제", "영향", "반응", "촉구", "요구", "합의", "협상", "경우", "이후", "이번",
    "오늘", "내일", "정부", "국회", "여야", "검토", "지적", "비판", "강조", "언급",
}


def trend_keyword(label: str) -> str:
    """이슈 제목(명사형)에서 검색어로 쓸 핵심 키워드 1개를 추출.

    괄호·기호를 제거하고 2자 이상 토큰 중 불용어를 걸러, 가장 긴(대개 고유명사·핵심어)
    토큰을 고른다. 마땅한 후보가 없으면 원 제목을 그대로 쓴다.
    """
    clean = re.sub(r"[()\[\]{}·…,.\"'’“”\-—~!?%:/]", " ", label)
    toks = [t for t in clean.split() if len(t) >= 2 and t not in _TREND_STOP]
    if not toks:
        return label.strip()
    toks.sort(key=lambda t: (-len(t), label.find(t)))
    return toks[0]


def enrich_issues(issues: list[dict], top_n: int = 15) -> int:
    """상위 이슈에 검색어 트렌드(상승 여부)를 in-place 로 부착. 반환: 상승 이슈 수.

    각 이슈의 핵심 키워드를 뽑아 데이터랩에 질의하고, 검색량이 최근 상승 중이면
    issue['search_rising']=True, issue['search_keyword']=키워드 를 설정한다.
    자격증명 없음/조회 실패 시 아무것도 하지 않는다(무중단).
    """
    top = [iss for iss in issues[:top_n] if iss.get("label")]
    kw_by_issue = [(iss, trend_keyword(iss["label"])) for iss in top]
    trends = fetch_trends([kw for _, kw in kw_by_issue])
    if not trends:
        return 0
    n = 0
    for iss, kw in kw_by_issue:
        info = trends.get(kw)
        if info and info.get("rising"):
            iss["search_rising"] = True
            iss["search_keyword"] = kw
            n += 1
    return n


def fetch_trends(keywords: list[str]) -> dict[str, dict]:
    """{keyword: {"rising": bool, "score": float}} 반환. 실패 시 빈 dict(무중단)."""
    cid = os.environ.get("NAVER_CLIENT_ID")
    csec = os.environ.get("NAVER_CLIENT_SECRET")
    kws = list(dict.fromkeys(k for k in keywords if k))
    if not (cid and csec) or not kws:
        return {}

    end = datetime.now(KST).date() - timedelta(days=1)   # 데이터랩은 하루 지연
    start = end - timedelta(days=LOOKBACK_DAYS)
    out: dict[str, dict] = {}

    for i in range(0, len(kws), GROUP_MAX):
        batch = kws[i : i + GROUP_MAX]
        body = json.dumps(
            {
                "startDate": start.isoformat(),
                "endDate": end.isoformat(),
                "timeUnit": "date",
                "keywordGroups": [{"groupName": k, "keywords": [k]} for k in batch],
            },
            ensure_ascii=False,
        ).encode("utf-8")
        try:
            req = urllib.request.Request(
                ENDPOINT,
                data=body,
                method="POST",
                headers={
                    "X-Naver-Client-Id": cid,
                    "X-Naver-Client-Secret": csec,
                    "Content-Type": "application/json",
                },
            )
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except Exception as e:
            print(f"[경고] 데이터랩 조회 실패: {e}")
            continue

        for result in data.get("results", []):
            rising, score = _rising(result.get("data", []))
            out[result.get("title", "")] = {"rising": rising, "score": score}

    if out:
        print(f"[데이터랩] {len(out)}개 키워드 추이 (상승 {sum(1 for v in out.values() if v['rising'])}건)")
    return out
