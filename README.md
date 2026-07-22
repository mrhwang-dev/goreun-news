# 고른뉴스 (goreun.news)

**골라 담아, 고르게 전합니다.**
여러 언론사의 헤드라인을 교차 확인해 매시간 정리하는 무료 중립 뉴스 브리핑 사이트.

- 브랜드: **고른뉴스** — "고르다"의 이중 의미(골라 담다 + 치우침 없이 고르게)
- 도메인 1순위: `goreun.news` (예비: `goreunnews.com`, `goreun.kr`) — 2026-07-22 DNS 기준 미등록, 등록은 별도 진행 필요

## 구조

```
언론사 RSS (제목·링크만) ─┐
                          ├─▶ 클러스터링·핫분야 배분 ─▶ Claude 라벨/요약 ─▶ 정적 HTML + /briefing.json
korea.kr 정책뉴스 (본문) ─┘        (cluster.py)          (구조화 출력·캐시)      (GitHub Pages, 매시간)
```

| 파일 | 역할 |
|---|---|
| `fetch_feeds.py` | 언론사 RSS에서 헤드라인(제목·링크·시각)만 수집 |
| `fetch_policy.py` | korea.kr 정책뉴스 본문 수집 (공공누리 1유형) |
| `cluster.py` | **유사 기사 클러스터링**(문자 2-그램 자카드 + union-find) · **핫 분야 슬롯 배분**(열기 지수 + 동트 방식) |
| `summarize.py` | Claude 라벨·중립 요약·분야 지정 (구조화 출력, `data/cache.json` 캐시) |
| `build_site.py` | 인터랙티브 멀티 컬럼 페이지 렌더링 (속보 티커·분야 필터·Sentry 버그 제보) |
| `run.py` | 오케스트레이터 (`--mock`으로 API 없이 미리보기) |
| `.github/workflows/daily.yml` | 매시간 자동 빌드·GitHub Pages 배포 |

## 핵심 알고리즘 (cluster.py)

1. **유사 기사 묶기** — 제목 정규화([속보]·[단독] 말머리 제거 등) → 문자 2-그램 집합 →
   자카드 유사도 ≥ 0.30인 쌍을 union-find로 연결해 '같은 사건' 클러스터 생성.
   랭킹은 (참여 매체 수, 최신성) 순.
2. **핫 분야 슬롯 배분** — 분야별 열기 = Σ(매체 수 × e^(-경과시간/6h)).
   총 12개 이슈 슬롯을 동트(D'Hondt) 방식으로 열기에 비례 배분
   (분야당 최소 1개·최대 5개). 지금 뜨거운 분야일수록 꼭지가 많아진다.
3. **속보 란** — `[속보]/[1보]/[긴급]` 말머리 + 6시간 이내 기사를 상단 티커로.

## 저작권 안전선 (상세: SOURCES.md)

- 언론사 기사는 **제목 + 원문 링크만** 사용 (제목: 저작물성 부정 / 링크: 대법원 2009다4343).
  본문·발췌 수집 금지. 비상업 한정·AI 금지 명시 피드(SBS·한겨레)는 제외.
- 이슈 요약문은 헤드라인 정보만으로 AI가 새로 작성.
- 정책 브리핑은 korea.kr 공공누리 제1유형 — 출처표시 조건으로 본문 요약 허용.
- 네이버 뉴스 검색 API는 약관상(광고 병행 노출·가공 금지) 사용 불가 판정 → 미사용.

## 로컬 실행

```bash
pip install -r requirements.txt

# 1) API 키 없이 레이아웃 미리보기
python run.py --mock
open site/index.html

# 2) 실제 파이프라인
cp .env.example .env   # ANTHROPIC_API_KEY 채우기
python run.py
```

## 배포 설정 (GitHub)

1. **Settings → Secrets and variables → Actions → Secrets**: `ANTHROPIC_API_KEY` 등록
2. (선택) **Variables**: `BRIEFING_MODEL=claude-haiku-4-5` — 비용 약 1/5 절감
3. **Settings → Pages → Source**: GitHub Actions (설정 완료됨)
4. **Actions → hourly-briefing → Run workflow**로 첫 배포, 이후 매시간 자동

## 공개 API

사이트의 모든 데이터는 `GET /briefing.json`으로 제공된다 (매시간 갱신).
필드: `generated_at`, `heat`(분야별 열기), `slots`, `breaking`, `issues`, `policy`.

## 버그 제보 (Sentry)

우측 상단 "버그 제보" 버튼 → Sentry Feedback 위젯.
프로젝트: `cwworks/goreun-news` (sentry.io) · 로더 키는 `config.SENTRY_LOADER_KEY`.

## 운영 비용

- 호스팅: GitHub Pages 무료 · 정적 사이트라 서버 비용 없음
- Claude API: 캐시 덕에 시간당 신규 이슈 분량만 호출. 기본 모델 기준 월 십수 달러 수준,
  `BRIEFING_MODEL=claude-haiku-4-5`로 약 1/5 절감 가능
- 수익화: `build_site.py`의 광고 슬롯(피드 중간 1 + 레일 1)에 AdSense/카카오 AdFit 코드 삽입.
  AdSense는 자체 도메인 연결 후 신청 권장
