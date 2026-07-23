"""AI 단계 — 다중 모델(Multi-LLM) 라우팅.

1) 1차 분류 (Gemini 2.5 Flash, 폴백 Claude):
   후보 클러스터 전체를 대상으로 노이즈 필터링(만평·고정 코너 등 제외),
   분야 지정, 임시 라벨·요약 생성. 대규모 단순 분류라 가성비 모델에 할당.
2) 정밀 요약 (Claude, 폴백 Gemini):
   점수 상위 핫이슈(config.REFINE_TOP_ISSUES)만 제한 호출 —
   매체 성향 분포를 참고한 편향 교차 검증 + 최종 중립 3문장 리포트.
3) 정책뉴스 요약 (Claude, 폴백 Gemini): 공공누리 본문 기반 정밀 요약.

- 캐시(data/cache.json): 내용이 바뀌지 않은 클러스터·기사는 재호출하지 않는다.
- 개별 단계가 모두 실패해도 예외를 삼켜 파이프라인(전체 Actions)은 계속 돈다.
- 근거 데이터는 기존과 동일: 언론사 기사는 '제목'만, 정책뉴스만 본문 사용.
"""

from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path

import config
from llm import call_with_fallback

from db import get_connection
CACHE_TTL_SECONDS = 3 * 24 * 3600

TRIAGE_SCHEMA = {
    "type": "object",
    "properties": {
        "clusters": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "integer", "description": "입력에 표시된 클러스터 번호"},
                    "keep": {
                        "type": "boolean",
                        "description": "뉴스 이슈면 true. 만평·운세·날씨 코너, 광고성, 의미 없는 묶음이면 false",
                    },
                    "label": {"type": "string", "description": "중립적 이슈 제목(명사형)"},
                    "summary": {"type": "string", "description": "2~3문장 중립 요약"},
                    "category": {"type": "string", "enum": config.ISSUE_CATEGORIES},
                },
                "required": ["id", "keep", "label", "summary", "category"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["clusters"],
    "additionalProperties": False,
}

REFINE_SCHEMA = {
    "type": "object",
    "properties": {
        "issues": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "integer", "description": "입력에 표시된 이슈 번호"},
                    "label": {"type": "string", "description": "최종 중립 이슈 제목(명사형)"},
                    "summary": {"type": "string", "description": "편향 교차 검증을 거친 3문장 중립 리포트"},
                    "framing": {
                        "type": "object",
                        "description": "프레임 체크 — 매체별 제목의 단어 선택 차이 관찰",
                        "properties": {
                            "note": {
                                "type": "string",
                                "description": "제목들의 단어 선택 차이를 1~2문장으로 관찰 서술. 평가어(교묘히, 노골적 등) 금지, 사실 관찰만.",
                            },
                            "words": {
                                "type": "array",
                                "description": "제목에 실제로 등장한 프레임 단어 최대 4개",
                                "items": {
                                    "type": "object",
                                    "properties": {
                                        "word": {"type": "string", "description": "제목 속 표현 그대로"},
                                        "side": {
                                            "type": "string",
                                            "enum": ["progressive", "conservative", "moderate", "common"],
                                            "description": "그 단어를 쓴 매체 성향. 여러 성향 공통이면 common",
                                        },
                                        "sentiment": {
                                            "type": "string",
                                            "enum": ["positive", "negative", "neutral"],
                                            "description": "그 표현이 대상에 담은 감성 톤 (긍정/부정/중립)",
                                        },
                                    },
                                    "required": ["word", "side"],
                                    "additionalProperties": False,
                                },
                            },
                        },
                        "required": ["note", "words"],
                        "additionalProperties": False,
                    },
                    "constructive": {
                        "type": "object",
                        "description": "건설적 쟁점 — 진보·보수가 모두 보도하고 프레이밍이 갈리는 이슈에서만. 아니면 이 필드 생략.",
                        "properties": {
                            "progressive_concern": {"type": "string", "description": "진보 성향 매체 제목에서 드러나는 핵심 우려 1문장"},
                            "conservative_claim": {"type": "string", "description": "보수 성향 매체 제목에서 드러나는 핵심 주장 1문장"},
                            "common_ground": {"type": "string", "description": "양측 공유 사실 또는 검증이 필요한 지점 1문장"},
                        },
                        "required": ["progressive_concern", "conservative_claim", "common_ground"],
                        "additionalProperties": False,
                    },
                },
                "required": ["id", "label", "summary", "framing"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["issues"],
    "additionalProperties": False,
}

POLICY_SCHEMA = {
    "type": "object",
    "properties": {
        "briefs": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "integer", "description": "입력에 표시된 기사 번호"},
                    "summary": {"type": "string", "description": "2~3문장 핵심 요약"},
                },
                "required": ["id", "summary"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["briefs"],
    "additionalProperties": False,
}

SYSTEM_TRIAGE = """너는 뉴스 애그리게이터 '고른뉴스'의 1차 분류기다. 같은 사건을 다룬 여러 언론사의 기사 '제목'들이 클러스터로 묶여 주어진다.

각 클러스터에 대해:
- keep: 실제 뉴스 사건이면 true. 만평·오늘의운세·날씨 고정 코너, 부고·인사 단신 모음, 광고성 기사, 서로 무관한 제목이 잘못 묶인 경우는 false.
- label: 중립적인 이슈 제목을 명사형으로 새로 쓴다. 특정 매체의 제목을 그대로 옮기지 않는다.
- summary: 제목들에 공통으로 담긴 정보만으로 2~3문장 요약. 제목에 없는 사실을 추가하지 않는다. 감정적·평가적 표현을 걷어낸다.
- category: 지정된 분야 중 하나."""

SYSTEM_REFINE = """너는 '고른뉴스'의 최종 편집자다. 여러 언론사가 다룬 상위 핫이슈가 매체별 제목·매체 성향 분포(진보/중도/보수)와 함께 주어진다.

각 이슈에 대해:
- 성향이 다른 매체들의 제목을 교차 검증해, 특정 진영의 프레이밍이 아닌 공통 사실만 남긴다. 성향에 따라 서술이 엇갈리면 "…라는 보도와 …라는 보도가 엇갈린다"처럼 병기한다.
- label: 최종 중립 이슈 제목(명사형).
- summary: 정확히 3문장의 중립 리포트. 감정적·평가적 표현 금지, 제목에 없는 사실 추가 금지, 주체·행위·수치·일정 중심.
- framing(프레임 체크): 제목들의 '단어 선택' 차이를 해부한다.
  - 대상은 성향이 분류된 매체([진보]/[중도]/[보수])의 제목뿐이다. [분류 없음] 매체는 진영 대비의 근거가 아니므로 그 표현을 하나의 집단처럼 서술하지 않는다("분류 없음 매체들은 ~을 올렸다" 금지).
  - note: 어느 성향 매체가 어떤 표현을 제목에 올렸는지 1~2문장으로 관찰만 서술한다. 매체를 심판하는 평가어(교묘히, 노골적으로, 왜곡 등)는 절대 쓰지 않는다. 분류된 매체가 한쪽 성향뿐이거나 성향별 차이가 뚜렷하지 않으면, 진영 대비 대신 여러 매체 공통의 핵심 표현만 짚거나 "제목 표현에서 성향 간 차이를 판단할 근거가 부족하다"고 쓴다.
  - words: 분류된 매체의 제목에 실제로 등장한 표현만, 표기 그대로 최대 4개. 여러 성향이 공통으로 쓴 핵심어는 side=common. 각 단어에는 그 표현이 대상에 담은 감성 톤 sentiment(positive/negative/neutral)를 함께 표시한다(예: '참사'=negative, '성과'=positive, '발표'=neutral).
- constructive(건설적 쟁점, 선택): 진보·보수 매체가 모두 실제로 보도했고 제목 프레이밍이 뚜렷이 갈리는 이슈에서만 작성한다. 한쪽 성향뿐이거나 대립이 약하면 이 필드를 아예 생략한다.
  - progressive_concern: 진보 성향 매체 제목에서 드러나는 핵심 우려를 1문장으로. 제목에 근거 없는 입장을 지어내지 않는다.
  - conservative_claim: 보수 성향 매체 제목에서 드러나는 핵심 주장을 1문장으로.
  - common_ground: 양측이 공유하는 사실, 또는 아직 검증이 필요해 판단을 유보할 지점을 1문장으로.
  - 어느 쪽이 옳다고 편들지 않으며, 억지 양비론·양시론을 만들지 않는다."""

SYSTEM_POLICY = """너는 '고른뉴스'의 정책 브리핑 편집자다. 대한민국 정책브리핑(korea.kr)의 정책뉴스 본문이 주어진다.

각 기사에 대해 국민 생활에 실제로 영향을 주는 핵심 정보(무엇이, 언제부터, 누구에게) 중심으로 1~2문장, 공백 포함 120자 이내로 요약한다. 홍보성 수식어는 걷어내고 사실만 남긴다."""


def _load_cache() -> dict:
    cache = {"clusters": {}, "refined": {}, "policy": {}}
    try:
        with get_connection() as conn:
            for row in conn.execute("SELECT section, k, v, t FROM cache"):
                if row["section"] in cache:
                    cache[row["section"]][row["k"]] = {"v": json.loads(row["v"]), "t": row["t"]}
    except Exception as e:
        print(f"[경고] SQLite 캐시 로드 실패: {e}")
    return cache


def _save_cache(cache: dict) -> None:
    now = time.time()
    try:
        with get_connection() as conn:
            # 오래된 캐시 정리
            conn.execute("DELETE FROM cache WHERE t < ?", (now - CACHE_TTL_SECONDS,))
            for section in ("clusters", "refined", "policy"):
                for k, v_dict in cache.get(section, {}).items():
                    if now - v_dict.get("t", 0) < CACHE_TTL_SECONDS:
                        conn.execute(
                            "INSERT OR REPLACE INTO cache (section, k, v, t) VALUES (?, ?, ?, ?)",
                            (section, k, json.dumps(v_dict["v"], ensure_ascii=False), v_dict["t"])
                        )
            conn.commit()
    except Exception as e:
        print(f"[경고] SQLite 캐시 저장 실패: {e}")


def _cluster_key(titles: list[str]) -> str:
    return hashlib.md5("|".join(sorted(titles)).encode()).hexdigest()


def _stable_cluster_key(cluster: list[dict]) -> str:
    """클러스터의 안정 앵커 키 — 최초(가장 이른) 기사 링크.

    제목 집합 해시는 새 기사 1건 합류에도 캐시 미스가 나서 같은 이슈를
    매시간 재라벨링하게 된다. 최초 기사 링크는 클러스터가 커져도 불변.
    """
    earliest = min(cluster, key=lambda m: m["ts"])
    return hashlib.md5(earliest["link"].encode()).hexdigest()


def _stable_issue_key(issue: dict) -> str:
    """이슈(정밀 요약)용 안정 키 — 최초 기사 링크 + 규모 버킷.

    headlines는 시간 오름차순이라 [0]이 최초 기사. 매체 수가 5단위로
    크게 늘면(속보→대형 이슈 성장) 한 번은 다시 요약한다.
    """
    anchor = issue["headlines"][0]["link"] if issue.get("headlines") else issue["label"]
    bucket = issue.get("outlet_count", 0) // 5
    return hashlib.md5(f"{anchor}|{bucket}".encode()).hexdigest()


# ── 1단계: Gemini 1차 분류 (노이즈 필터 + 분야 + 임시 라벨) ─────────────


def label_clusters(clusters: list[list[dict]]) -> dict[int, dict]:
    """클러스터별 {label, summary, category}를 반환한다. 노이즈는 제외된다."""
    cache = _load_cache()
    results: dict[int, dict] = {}
    keys: dict[int, str] = {}
    to_ask: list[int] = []

    for ci, cluster in enumerate(clusters):
        key = _stable_cluster_key(cluster)
        keys[ci] = key
        hit = cache["clusters"].get(key)
        if hit:
            if hit.get("keep", True):
                results[ci] = {k: hit[k] for k in ("label", "summary", "category")}
        else:
            to_ask.append(ci)

    if to_ask:
        # 큰 배치(60개)를 한 요청에 보내면 일부 LLM(특히 추론모델 HCX-007)이
        # 앞부분 몇 개만 라벨링하고 나머지를 누락한다. 작은 청크로 나눠 각 응답을
        # 온전하게 받는다(무-API 알고리즘 폴백 비율을 낮춤). Gemini 응답 잘림도 완화.
        CHUNK = 15
        labeled = 0
        engine_used: str | None = None
        for start in range(0, len(to_ask), CHUNK):
            chunk = to_ask[start : start + CHUNK]
            lines = []
            for local_idx, ci in enumerate(chunk):
                heads = " / ".join(f"({m['outlet']}) {m['title']}" for m in clusters[ci][:8])
                lines.append(f"[{local_idx}] {heads}")
            user = (
                "다음 헤드라인 클러스터들을 분류하라. "
                f"분야는 {', '.join(config.ISSUE_CATEGORIES)} 중 하나.\n\n" + "\n".join(lines)
            )
            try:
                data, engine = call_with_fallback("gemini", SYSTEM_TRIAGE, user, TRIAGE_SCHEMA)
                engine_used = engine
            except Exception as e:
                print(f"[경고] 1차 분류 청크({start}~) 실패 — 건너뜀: {e}")
                continue

            for pos, entry in enumerate(data.get("clusters", [])):
                sub_id = entry.get("id")
                if isinstance(sub_id, int) and 0 <= sub_id < len(chunk):
                    ci = chunk[sub_id]
                elif 0 <= pos < len(chunk):
                    ci = chunk[pos]
                else:
                    continue

                keep = bool(entry.get("keep", True))
                meta = {
                    "keep": keep,
                    "label": entry.get("label", ""),
                    "summary": entry.get("summary", ""),
                    "category": entry.get("category")
                    if entry.get("category") in config.ISSUE_CATEGORIES
                    else "사회",
                }
                cache["clusters"][keys[ci]] = {**meta, "t": time.time()}
                if keep and meta["label"]:
                    results[ci] = {k: meta[k] for k in ("label", "summary", "category")}
                    labeled += 1

        if engine_used:
            print(f"[1차 분류] {len(to_ask)}개 요청 → {labeled}개 라벨 ({engine_used}, 청크 {CHUNK})")
        else:
            print("[경고] 1차 분류 전체 실패 — 알고리즘 폴백")
        _save_cache(cache)

    return results


# ── 2단계: Claude 정밀 요약 (상위 핫이슈 편향 교차 검증) ────────────────

BIAS_KO = {"progressive": "진보", "moderate": "중도", "conservative": "보수", "unknown": "분류 없음"}

# 품질 게이트: note가 매체를 '심판'하는 평가어를 쓰면 해당 framing을 폐기한다
_EVAL_BLACKLIST = ("교묘", "노골", "왜곡", "편파", "선동", "물타기", "궤변", "저열", "악의")


def framing_passes_gate(note: str) -> bool:
    return not any(word in note for word in _EVAL_BLACKLIST)


def refine_top_issues(issues: list[dict], top_n: int | None = None) -> None:
    """점수 상위 이슈의 label/summary를 Claude 정밀 리포트로 교체한다 (in-place)."""
    top_n = top_n or config.REFINE_TOP_ISSUES
    targets = issues[:top_n]
    if not targets:
        return

    cache = _load_cache()
    to_ask: list[int] = []
    keys: dict[int, str] = {}
    for i, issue in enumerate(targets):
        key = _stable_issue_key(issue)
        keys[i] = key
        hit = cache["refined"].get(key)
        if hit:
            issue["label"], issue["summary"] = hit["label"], hit["summary"]
            if hit.get("framing"):
                issue["framing"] = hit["framing"]
            if hit.get("constructive"):
                issue["constructive"] = hit["constructive"]
        else:
            to_ask.append(i)

    if not to_ask:
        return

    from cluster import detect_honorifics, extract_frame_candidates

    blocks = []
    for idx, i in enumerate(to_ask):
        issue = targets[i]
        bias = issue.get("bias", {})
        bias_line = ", ".join(f"{BIAS_KO[k]} {v}곳" for k, v in bias.items() if v)
        heads = "\n".join(
            f"  - [{BIAS_KO.get(h.get('bias', 'unknown'), '분류 없음')}] ({h['outlet']}) {h['title']}"
            for h in issue["headlines"][:12]
        )
        cands = extract_frame_candidates(issue["headlines"])
        cand_line = (
            f"공통={', '.join(cands['common']) or '없음'} / "
            f"진보만={', '.join(cands['progressive']) or '없음'} / "
            f"보수만={', '.join(cands['conservative']) or '없음'}"
        )
        honorifics = detect_honorifics(issue["headlines"])
        hono_line = ""
        if len(honorifics) >= 2:  # 표기가 2종 이상일 때만 프레임 신호
            hono_line = "호칭 표기(알고리즘 감지): " + ", ".join(
                f"{h['text']}({h['style']}: "
                + "·".join(f"{BIAS_KO.get(s, s)} {n}" for s, n in h["sides"].items())
                + ")"
                for h in honorifics
            ) + "\n"
        blocks.append(
            f"[{idx}] 매체 성향 분포: {bias_line or '정보 없음'}\n"
            f"프레임 후보(알고리즘 산출): {cand_line}\n{hono_line}{heads}"
        )
    user = (
        "다음 상위 핫이슈들의 최종 중립 리포트를 작성하라. "
        "framing.words는 '프레임 후보'와 제목 원문에 실제로 있는 표현에서만 고른다.\n\n"
        + "\n\n".join(blocks)
    )

    try:
        data, engine = call_with_fallback("claude", SYSTEM_REFINE, user, REFINE_SCHEMA)
        print(f"[정밀 요약] 상위 {len(to_ask)}개 이슈 — {engine} 처리")
    except Exception as e:
        print(f"[경고] 정밀 요약 실패 — 1차 분류 요약 유지: {e}")
        return

    entries = data.get("issues", [])
    for pos, entry in enumerate(entries):
        sub_id = entry.get("id")
        if isinstance(sub_id, int) and 0 <= sub_id < len(to_ask):
            i = to_ask[sub_id]
        elif 0 <= pos < len(to_ask):
            i = to_ask[pos]
        else:
            continue

        if not entry.get("summary"):
            continue
        targets[i]["label"] = entry.get("label") or targets[i]["label"]
        targets[i]["summary"] = entry["summary"]
        framing = entry.get("framing")
        if framing and framing.get("note"):
            if not framing_passes_gate(framing["note"]):
                print(f"[품질 게이트] 평가어 감지 — framing 폐기: {framing['note'][:50]}")
            else:
                # 사후 검증: 제목 원문에 실제로 존재하는 단어만 남긴다 (환각 차단)
                titles = " || ".join(h["title"] for h in targets[i]["headlines"])
                proposed = framing.get("words") or []
                framing["words"] = [
                    w for w in proposed if w.get("word") and w["word"] in titles
                ][:4]
                if proposed:
                    print(f"[프레임 적중률] {len(framing['words'])}/{len(proposed)}")
                targets[i]["framing"] = framing
        constructive = entry.get("constructive")
        if constructive and constructive.get("progressive_concern") and constructive.get("conservative_claim"):
            targets[i]["constructive"] = {
                k: constructive.get(k, "")
                for k in ("progressive_concern", "conservative_claim", "common_ground")
            }
        cache["refined"][keys[i]] = {
            "label": targets[i]["label"],
            "summary": targets[i]["summary"],
            "framing": targets[i].get("framing"),
            "constructive": targets[i].get("constructive"),
            "t": time.time(),
        }
    _save_cache(cache)


# ── 3단계: 정책뉴스 요약 (공공누리 본문 기반) ───────────────────────────


def summarize_policy(articles: list[dict]) -> list[dict]:
    """정책뉴스 요약 [{title, summary, link}] (캐시 활용)."""
    cache = _load_cache()
    results: dict[int, str] = {}
    to_ask: list[int] = []

    for ai, art in enumerate(articles):
        hit = cache["policy"].get(art["id"])
        if hit:
            results[ai] = hit["summary"]
        else:
            to_ask.append(ai)

    if to_ask:
        blocks = []
        for idx, ai in enumerate(to_ask):
            art = articles[ai]
            blocks.append(f"[{idx}] 제목: {art['title']}\n본문: {art['body'][:1500]}")
        user = "다음 정책뉴스들을 요약하라.\n\n" + "\n\n".join(blocks)
        try:
            data, engine = call_with_fallback("claude", SYSTEM_POLICY, user, POLICY_SCHEMA)
            print(f"[정책 요약] {len(to_ask)}건 — {engine} 처리")
        except Exception as e:
            print(f"[경고] 정책 요약 실패 — 신규 기사 건너뜀: {e}")
            data = {"briefs": []}
        entries = data.get("briefs", [])
        for pos, entry in enumerate(entries):
            sub_id = entry.get("id")
            if isinstance(sub_id, int) and 0 <= sub_id < len(to_ask):
                ai = to_ask[sub_id]
            elif 0 <= pos < len(to_ask):
                ai = to_ask[pos]
            else:
                continue

            if not entry.get("summary"):
                continue
            results[ai] = entry["summary"]
            cache["policy"][articles[ai]["id"]] = {
                "summary": entry["summary"],
                "t": time.time(),
            }
        _save_cache(cache)

    return [
        {"title": art["title"], "summary": results[ai], "link": art["link"]}
        for ai, art in enumerate(articles)
        if ai in results
    ]
