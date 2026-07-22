"""매체 성향 추정 알고리즘 — 관측 기반 (통념 사전의 한계 보완).

통념 분류는 근거가 확실한 소수 앵커 매체(config.OUTLET_BIAS)에만 사용하고,
나머지 매체는 데이터로 추정한다.

원리: 같은 사건을 보도하면 사실 골격은 같고, 제목에 남는 차이는 프레이밍이다.
어떤 매체의 제목이 꾸준히 한쪽 진영 앵커들의 제목과 더 높은 어휘 중첩을
보인다면, 그 매체는 그쪽 프레임을 공유한다고 볼 수 있다.

절차 (시간별 아카이브 스냅샷 전체에 대해):
1) 이슈에 진보·보수 앵커 제목이 모두 있으면 '판정 가능 이슈'로 삼는다
   (한쪽만 있으면 비교 기준이 없어 표를 만들지 않는다)
2) 비앵커 매체 제목 T에 대해
   s_p = max 겹침계수(T, 진보 앵커 제목들), s_c = max 겹침계수(T, 보수 앵커 제목들)
   — 겹침계수는 cluster.py의 문자 2-그램 overlap (제목 길이 차이에 견고)
3) |s_p − s_c| ≥ MARGIN 이면 가까운 쪽에 1표 (근소한 차이는 표로 치지 않음)
4) 매체 점수 = (진보표 − 보수표) / 총표.
   - 총표 < MIN_VOTES         → 분류 보류(None) — 데이터 부족을 중도로 뭉개지 않는다
   - 점수 ≥ +THRESHOLD        → progressive
   - 점수 ≤ −THRESHOLD        → conservative
   - 그 외                     → moderate (관측상 어느 쪽에도 치우치지 않음)

산출 모델은 /bias-model.json 으로 공개해 분류 근거를 투명하게 남긴다.
"""

from __future__ import annotations

from collections import defaultdict

import config
from cluster import char_bigrams, normalize_title, overlap

MARGIN = 0.08      # 이 이상 가까워야 1표
MIN_VOTES = 12     # 분류에 필요한 최소 표 (진입)
EXIT_VOTES = 8     # 이미 분류된 매체가 분류를 잃는 하한 (이탈 — 히스테리시스)
THRESHOLD = 0.25   # 진보/보수 판정 점수 경계 (진입)
EXIT_THRESHOLD = 0.15  # 기존 판정을 유지하는 완화 경계 (이탈 — 히스테리시스)


def _issue_key(issue: dict) -> str:
    """이슈 정체성 키 — 최초 기사 링크(없으면 라벨).

    같은 이슈가 시간별 스냅샷 수십 개에 반복 수록되므로, 스냅샷 단위가 아니라
    '이슈 단위'로 1표만 세어야 사건 1건의 우연한 유사가 표를 부풀리지 못한다.
    """
    heads = issue.get("headlines") or []
    if heads and heads[0].get("link"):
        return heads[0]["link"]
    return issue.get("label", "") or (heads[0]["title"] if heads else "")


def compute_bias_model(
    snapshots: list[tuple[str, dict]], prev_model: dict[str, dict] | None = None
) -> dict[str, dict]:
    """아카이브 스냅샷들로부터 {매체: {lean, score, votes}} 모델을 계산한다.

    - (이슈, 매체) 쌍당 1표: 스냅샷 반복 수록에 의한 표 부풀리기 차단
    - 히스테리시스: 경계(±0.25/12표)에 걸친 매체가 시간마다 플립하지 않도록,
      직전 판정은 완화 경계(±0.15/8표)를 지키는 한 유지된다
    """
    votes: dict[str, list[int]] = defaultdict(lambda: [0, 0])  # [진보표, 보수표]
    voted: set[tuple[str, str]] = set()  # (이슈 키, 매체) — 중복 투표 방지

    for _, briefing in snapshots:
        for issue in briefing.get("issues", []):
            heads = issue.get("headlines", [])
            issue_key = _issue_key(issue)
            prog_feats = [
                char_bigrams(normalize_title(h["title"]))
                for h in heads
                if config.OUTLET_BIAS.get(h["outlet"]) == "progressive"
            ]
            cons_feats = [
                char_bigrams(normalize_title(h["title"]))
                for h in heads
                if config.OUTLET_BIAS.get(h["outlet"]) == "conservative"
            ]
            if not prog_feats or not cons_feats:
                continue  # 비교 기준(양 진영 앵커)이 없으면 판정 불가
            for h in heads:
                if h["outlet"] in config.OUTLET_BIAS:
                    continue
                if (issue_key, h["outlet"]) in voted:
                    continue  # 같은 이슈에는 매체당 1표
                feat = char_bigrams(normalize_title(h["title"]))
                s_p = max(overlap(feat, f) for f in prog_feats)
                s_c = max(overlap(feat, f) for f in cons_feats)
                if s_p - s_c >= MARGIN:
                    votes[h["outlet"]][0] += 1
                    voted.add((issue_key, h["outlet"]))
                elif s_c - s_p >= MARGIN:
                    votes[h["outlet"]][1] += 1
                    voted.add((issue_key, h["outlet"]))

    prev_model = prev_model or {}
    model: dict[str, dict] = {}
    for outlet, (p, c) in sorted(votes.items()):
        n = p + c
        score = (p - c) / n if n else 0.0
        prev_lean = (prev_model.get(outlet) or {}).get("lean")

        if n >= MIN_VOTES:
            if score >= THRESHOLD:
                lean = "progressive"
            elif score <= -THRESHOLD:
                lean = "conservative"
            else:
                lean = "moderate"
        elif prev_lean and n >= EXIT_VOTES:
            lean = prev_lean  # 표가 다소 줄어도 기존 판정 유지
        else:
            model[outlet] = {"lean": None, "score": None, "votes": n}
            continue

        # 진보/보수였던 매체는 점수가 완화 경계 안쪽으로 무너질 때까지 유지
        if prev_lean in ("progressive", "conservative") and lean != prev_lean:
            keeps_direction = (prev_lean == "progressive" and score >= EXIT_THRESHOLD) or (
                prev_lean == "conservative" and score <= -EXIT_THRESHOLD
            )
            if keeps_direction:
                lean = prev_lean

        model[outlet] = {"lean": lean, "score": round(score, 3), "votes": n}
    return model


def effective_bias(outlet: str, model: dict[str, dict] | None) -> str:
    """앵커(통념) 우선, 없으면 관측 모델, 그것도 없으면 '분류 없음'."""
    anchor = config.OUTLET_BIAS.get(outlet)
    if anchor:
        return anchor
    rec = (model or {}).get(outlet)
    if rec and rec.get("lean"):
        return rec["lean"]
    return "unknown"
