"""네이버 데이터랩 검색어트렌드 API로 키워드의 검색량 추이를 조회한다.

트렌드 키워드가 '실제로 검색이 늘고 있는지(📈 상승)'를 판별해 상승 키워드를
우선 노출한다. NAVER API HUB 게이트웨이 + X-NCP-APIGW 인증(검색 API와 동일 계열).
자격증명(NAVER_CLIENT_ID/SECRET) 미설정이면 빈 결과를 반환한다.
"""

from __future__ import annotations

import json
import os
import urllib.request
from datetime import datetime, timedelta, timezone

# 데이터랩(통합 검색어 트렌드)은 검색 API와 달리 클래식 도메인 openapi.naver.com 사용.
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
                    # 엔드포인트가 게이트웨이(NCP)/클래식(openapi) 중 어느 인증을
                    # 검증하든 통과하도록 두 방식 헤더를 함께 싣는다.
                    "X-Naver-Client-Id": cid,
                    "X-Naver-Client-Secret": csec,
                    "X-NCP-APIGW-API-KEY-ID": cid,
                    "X-NCP-APIGW-API-KEY": csec,
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
