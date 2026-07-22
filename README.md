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
| `llm.py` | **다중 모델 오케스트레이션** — 지수 백오프 재시도 + Claude↔Gemini 무중단 폴백 |
| `summarize.py` | 3단계 AI 라우팅: ① Gemini 2.5 Flash 1차 분류(노이즈 필터·분야·임시 라벨) ② Claude 상위 12개 이슈 정밀 요약(성향 교차 검증 3문장 리포트) ③ Claude 정책뉴스 요약 (`data/cache.json` 캐시) |
| `fetch_community.py` | 커뮤니티 인기글 수집 — 게시글 제목·링크만 (루리웹 베스트·더쿠 HOT) |
| `build_site.py` | Tailwind 기반 페이지 렌더링 — 뉴스 대시보드(index) + 커뮤니티(community) |
| `og_image.py` | SNS 공유용 OG 카드(1200×630) 자동 생성 — 자체 그래픽 |
| `run.py` | 오케스트레이터 (`--mock`으로 API 없이 미리보기) |
| `.github/workflows/daily.yml` | 매시간 자동 빌드·GitHub Pages 배포 |
| `assets/` | 브랜드 로고 (mark.svg / logo.svg — '고르게 정렬된 세 줄') |

## 운영 안정성

- **빌드 타임 Tailwind**: Play CDN 대신 Actions에서 Tailwind CLI로 정적 CSS(~25KB)를
  생성해 첫 렌더링과 Core Web Vitals를 개선 (CLI 실패 시 CDN 자동 폴백).
- **아카이브·영구 링크**: 매시간 브리핑을 `archive/<stamp>.json`으로 저장소에 커밋하고
  `/archive/<stamp>/` 정적 스냅샷 페이지(최근 72개)로 렌더링. 공유 버튼·RSS 링크는
  해당 시각 스냅샷을 가리켜 다음 갱신에도 깨지지 않으며, 사이트맵에 실제 URL로 등재됨.
- **실패 알림**: Sentry Cron Monitor 체크인(시작/성공/실패) + 실패 시 GitHub 이슈 자동
  생성. 스케줄 미실행(missed)도 Sentry가 감지.
- **AI 캐시 안정 키**: 클러스터 캐시 키를 제목 해시 대신 '최초 기사 링크'(정밀 요약은
  +규모 버킷)로 바꿔, 새 기사 합류마다 재라벨링되던 비용 누수를 제거.
- **자동 테스트**: `tests/test_cluster.py` (정규화·유사도·군집·슬롯 배분) — CI에서
  빌드 전에 실행.

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
  키워드(단독·후기·레전드 등) 포함 또는 1시간 내 신규 진입 글에 🔥 HOT 하이라이트.
- **성향 스펙트럼 바**: 이슈 카드를 펼치면 보도 매체의 진보(파랑)-중도(회색)-보수(빨강)
  분포를 얇은 바로 표시. 분류 근거가 약한 매체(경제지·지역지·IT지 등)는 '중도'로
  뭉개지 않고 **'분류 없음'으로 별도 표기** (`config.OUTLET_BIAS` 주석에 분류 기준).
- **스크랩북** (`scrapbook.html`): 카드/게시글의 ☆를 누르면 localStorage에 저장,
  전용 페이지에서 모아보기·해제.
- **공유하기**: 모바일은 OS 공유 시트(navigator.share), 데스크톱은 링크 복사 + 토스트.
- **뉴스레터 폼**: 사이드바 구독 폼 → 구글 폼 AJAX 제출
  (`NEWSLETTER_FORM_ACTION`/`NEWSLETTER_FORM_ENTRY` 설정 필요, 미설정 시 안내 토스트).
- **접근성/편의**: 글자 크기 조절(가/가+, 저장 유지), 모바일 스크롤 시 헤더 자동 숨김,
  Top 플로팅 버튼, 정책 브리핑 예상 읽기 시간(약 500자/분) 표시.
- **오프라인 페일세이프**: 서비스워커가 마지막 성공 응답을 캐시, 네트워크 실패 시
  이전 데이터를 보여주며 상단에 경고 배너 표시.
- **무한 스크롤**: 최초 12개 카드만 렌더링, IntersectionObserver로 스크롤 시 12개씩
  추가 공개 (분야 필터 사용 시 전체 공개).
- **타임라인 뷰**: '매체별 헤드라인' 펼치면 송고 시간순(1보→최신) 수직 타임라인으로
  사건의 흐름 표시 (이슈당 최대 20건).
- **광고 슬롯 모듈** (`ad_slot()`): 피드 4~5번째 카드 사이 + 사이드바 + 커뮤니티,
  `min-h-[250px]` 고정과 스켈레톤 배경으로 CLS 방지.
- **SEO 자동화**: 매시간 `sitemap.xml`·`rss.xml`(중요도순 이슈 피드)·`robots.txt` 생성.
- 라이트/다크 모드, 10분 주기 새 데이터 감지 자동 새로고침.

## 뉴스레터 폼 연결 (구글 폼)

1. 구글 폼 생성 (이메일 단답 질문 1개)
2. 폼 미리보기에서 `<form action>`의 `formResponse` URL과 이메일 입력의 `entry.XXXXXXX` 필드명 확인
3. Actions **Variables**에 `NEWSLETTER_FORM_ACTION`, `NEWSLETTER_FORM_ENTRY` 등록 후 재배포

## 핵심 알고리즘 (cluster.py)

1. **유사 기사 묶기** — 제목 정규화([속보]·[단독] 말머리 제거 등) → 문자 2-그램 집합 →
   자카드(≥0.30) 또는 겹침 계수(≥0.40)로 판정한 쌍을 union-find로 연결해
   '같은 사건' 클러스터 생성. 수집 풀: **검증된 22개 매체 RSS**
   (종합지·방송·경제지·IT·주간지·지역지, `config.PRESS_FEEDS`).
2. **랭킹 (Cluster Size 최우선)** — 이슈 점수 = (매체 수)²×e^(-경과시간/6h).
   매체 수에 제곱 가중을 걸어 많은 언론사가 다룬 대형 이슈일수록 압도적으로
   높은 점수를 받고, **점수 상위 3개는 분야 배분과 무관하게 그리드 최상단 고정**.
3. **핫 분야 슬롯 배분** — 나머지 슬롯(총 48개)은 분야별 열기 비례 동트(D'Hondt)
   배분 (분야당 최소 1개·최대 12개).
4. **속보 란** — `[속보]/[1보]/[긴급]` 말머리 + 6시간 이내 기사를 상단 티커로.
   대응 이슈 카드가 있으면 클릭 시 카드로 스크롤.

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

1. **Settings → Secrets and variables → Actions → Secrets**: `ANTHROPIC_API_KEY`, `GEMINI_API_KEY` 등록
   (Gemini 키가 없어도 Claude 폴백으로 동작하지만 1차 분류 비용이 올라간다)
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
