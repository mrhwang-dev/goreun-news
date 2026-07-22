# 오늘의 중립 브리핑

여러 언론사의 보도를 AI가 교차 확인해 사실 중심으로 정리하는 무료 뉴스 브리핑 사이트.
매일 아침 7시(KST) GitHub Actions가 자동으로 생성해 GitHub Pages에 배포한다.

## 구조

```
네이버 뉴스 검색 API ──▶ Claude (중립 요약·교차 확인) ──▶ 정적 HTML ──▶ GitHub Pages
   (제목·요약·링크만)        (구조화 출력 JSON)              (광고 슬롯 포함)
```

- `fetch_news.py` — 네이버 뉴스 검색 API에서 기사 메타데이터 수집 (본문 크롤링 없음)
- `summarize.py` — Claude로 이슈 클러스터링 + 중립 브리핑 생성 (구조화 출력)
- `build_site.py` — 정적 HTML 렌더링 (라이트/다크, 광고 슬롯, 원문 링크)
- `run.py` — 파이프라인 오케스트레이터 (`--mock`으로 API 없이 미리보기 가능)
- `.github/workflows/daily.yml` — 매일 07:00 KST 자동 빌드·배포

## 저작권 안전선

- 기사 **본문을 수집·저장·복제하지 않는다.** 네이버 API가 반환하는 제목·짧은 요약문(description)·링크만 사용한다.
- 모든 이슈에 **원문 기사 링크**를 언론사명과 함께 표기한다.
- 브리핑 문장은 여러 매체의 메타데이터를 교차 확인해 AI가 새로 작성한 것으로, 기사 문장을 전재하지 않는다.
- 상세 소스 검토는 `SOURCES.md` 참고.

## 로컬 실행

```bash
pip install -r requirements.txt

# 1) API 키 없이 레이아웃 미리보기
python run.py --mock
open site/index.html

# 2) 실제 파이프라인
cp .env.example .env   # 키 채우기
python run.py
```

## 배포 설정 (GitHub)

1. GitHub에 저장소 생성 후 푸시
2. **Settings → Secrets and variables → Actions** 에 등록:
   - `NAVER_CLIENT_ID`, `NAVER_CLIENT_SECRET` — [developers.naver.com](https://developers.naver.com)에서 애플리케이션 등록 → "검색" API 선택
   - `ANTHROPIC_API_KEY` — [console.anthropic.com](https://console.anthropic.com)
3. **Settings → Pages → Source**를 **GitHub Actions**로 변경
4. **Actions 탭 → daily-briefing → Run workflow**로 첫 배포 실행 (이후 매일 자동)

## 광고 (수익화)

`build_site.py`의 `AD_SLOT` 위치(상단 1개, 본문 중간 1개)에 광고 코드를 삽입한다.

- **Google AdSense** — 자체 도메인 연결 후 신청 권장 (github.io 서브도메인은 승인 불리). 승인 후 `<head>` 주석 자리에 스크립트 삽입.
- **카카오 AdFit** — 국내 트래픽 대상 대안. 심사가 상대적으로 빠름.
- 초기 트래픽 단계에서는 **쿠팡 파트너스** 링크도 병행 가능.

## 운영 비용

- 호스팅: GitHub Pages 무료
- Claude API: 하루 4개 카테고리 요약 기준 월 수 달러 수준.
  `BRIEFING_MODEL=claude-haiku-4-5`로 바꾸면 약 1/5로 절감된다.
- 네이버 검색 API: 무료 (일 25,000회 한도, 본 파이프라인은 하루 12회 호출)
