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
| `fetch_community.py` | 커뮤니티 인기글 수집 — 게시글 제목·링크만 (루리웹 베스트·더쿠 HOT) |
| `build_site.py` | Tailwind 기반 페이지 렌더링 — 뉴스 대시보드(index) + 커뮤니티(community) |
| `og_image.py` | SNS 공유용 OG 카드(1200×630) 자동 생성 — 자체 그래픽 |
| `run.py` | 오케스트레이터 (`--mock`으로 API 없이 미리보기) |
| `.github/workflows/daily.yml` | 매시간 자동 빌드·GitHub Pages 배포 |
| `assets/` | 브랜드 로고 (mark.svg / logo.svg — '고르게 정렬된 세 줄') |

## UI (Tailwind CSS)

- **뉴스 대시보드** (`index.html`): 좌 70% 이슈 카드 그리드 / 우 30% 사이드바
  (정책 브리핑·광고·공개 API). 모바일은 1단으로 재배치.
- **카테고리 탭**: 헤더 아래 전체·정치·경제·사회·국제·IT·과학·생활·문화 탭 +
  기사 수 뱃지. 클릭 시 카드 그리드 필터링, 최고 열기 분야에 🔥 표시.
- **속보 티커**: 탭 아래에서 `[속보]/[1보]/[긴급]` 헤드라인이 5초 간격
  페이드 전환 (모션 최소화 설정 시 고정).
- **이슈 카드**: 카테고리 태그(좌) + 'N개 매체'(우) + 헤드라인 + AI 요약 +
  '매체별 헤드라인 N건' 펼치기 버튼. 매체 파비콘 표시.
- **커뮤니티 인기글** (`community.html`): 뉴스와 분리된 전용 페이지.
  소스 탭(루리웹·더쿠) 필터 + 순위 리스트. 게시글 제목·원문 링크만 표시.
- 라이트/다크 모드, 10분 주기 새 데이터 감지 자동 새로고침.

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

사이트의 모든 데이터는 JSON으로 제공된다 (매시간 갱신).

- `GET /briefing.json` — `generated_at`, `heat`(분야별 열기), `slots`, `breaking`, `issues`, `policy`
- `GET /community.json` — `generated_at`, `posts`(커뮤니티 인기글)

## 배포 도메인

- 현재: `고른뉴스.메인.한국` (내도메인.한국 무료 도메인, CNAME → mrhwang-dev.github.io)
- 1순위 후보: `goreun.news` (구매 시 Pages 커스텀 도메인만 교체)

## 버그 제보 (Sentry)

우측 상단 "버그 제보" 버튼 → Sentry Feedback 위젯.
프로젝트: `cwworks/goreun-news` (sentry.io) · 로더 키는 `config.SENTRY_LOADER_KEY`.

## 운영 비용

- 호스팅: GitHub Pages 무료 · 정적 사이트라 서버 비용 없음
- Claude API: 캐시 덕에 시간당 신규 이슈 분량만 호출. 기본 모델 기준 월 십수 달러 수준,
  `BRIEFING_MODEL=claude-haiku-4-5`로 약 1/5 절감 가능
- 수익화: `build_site.py`의 광고 슬롯(피드 중간 1 + 레일 1)에 AdSense/카카오 AdFit 코드 삽입.
  AdSense는 자체 도메인 연결 후 신청 권장
