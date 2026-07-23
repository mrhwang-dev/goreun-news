"""제목 임베딩 수집 — CLOVA Studio 임베딩 v2 + sqlite 캐시 + 동시성.

임베딩 API는 단건 호출이라, 신규 제목만 병렬로 임베딩하고 결과를 캐시해
시간당 실행 비용을 최소화한다(같은 제목은 재호출하지 않음).
"""

from __future__ import annotations

import hashlib
import json
from concurrent.futures import ThreadPoolExecutor

from db import get_connection

MAX_WORKERS = 6


def _key(text: str) -> str:
    return hashlib.sha1(text.encode("utf-8")).hexdigest()


def fetch_embeddings(texts: list[str]) -> dict[str, list[float]]:
    """texts의 {제목: 벡터} 매핑을 반환한다. 캐시 우선, 미보유분만 API 호출."""
    from llm import clova_embed

    uniq = list(dict.fromkeys(t for t in texts if t))
    out: dict[str, list[float]] = {}

    # 1) 캐시 로드
    keys = {t: _key(t) for t in uniq}
    try:
        with get_connection() as conn:
            placeholders = ",".join("?" * len(keys)) or "''"
            rows = conn.execute(
                f"SELECT k, v FROM embedding_cache WHERE k IN ({placeholders})",
                list(keys.values()),
            ).fetchall()
            cached = {row["k"]: row["v"] for row in rows}
    except Exception as e:
        print(f"[경고] 임베딩 캐시 로드 실패: {e}")
        cached = {}

    todo: list[str] = []
    for t in uniq:
        hit = cached.get(keys[t])
        if hit is not None:
            out[t] = json.loads(hit)
        else:
            todo.append(t)

    # 2) 미보유분 병렬 임베딩
    if todo:
        def _one(t: str) -> tuple[str, list[float] | None]:
            try:
                return t, clova_embed(t)
            except Exception as e:
                print(f"[경고] 임베딩 실패: {e}")
                return t, None

        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
            results = list(pool.map(_one, todo))

        fresh = [(t, v) for t, v in results if v is not None]
        for t, v in fresh:
            out[t] = v
        # 3) 캐시 저장
        try:
            with get_connection() as conn:
                conn.executemany(
                    "INSERT OR REPLACE INTO embedding_cache (k, v) VALUES (?, ?)",
                    [(keys[t], json.dumps(v)) for t, v in fresh],
                )
                conn.commit()
        except Exception as e:
            print(f"[경고] 임베딩 캐시 저장 실패: {e}")
        print(f"[임베딩] 신규 {len(fresh)}건 / 캐시 {len(out) - len(fresh)}건")

    return out
