"""고른뉴스 (goreunnews.cloud) — 설정."""

import os

# ── 소스 구성 (저작권 검토 결과: SOURCES.md) ─────────────────────────────
# 언론사 RSS: '제목 + 원문 링크' 큐레이션만 사용. 본문 수집·요약 금지.
#   - 제목은 저작물성 부정(판례), 링크는 침해 아님(대법원 2009다4343)
#   - 제외: SBS(비상업 한정 명시), 한겨레(피드에 AI 활용 금지 명시),
#           매일경제(봇 차단), 중앙일보(RSS 중단), 연합뉴스(미제공)
# 2026-07-22 전수 응답 테스트로 검증된 피드만 등록 (미제공·차단·금지 명시 매체 제외)
PRESS_FEEDS = [
    # 종합 일간지
    {"outlet": "조선일보", "url": "https://www.chosun.com/arc/outboundfeeds/rss/?outputType=xml"},
    {"outlet": "경향신문", "url": "https://www.khan.co.kr/rss/rssdata/total_news.xml"},
    {"outlet": "동아일보", "url": "https://rss.donga.com/total.xml"},
    {"outlet": "세계일보", "url": "https://www.segye.com/Articles/RSSList/segye_recent.xml"},
    {"outlet": "서울신문", "url": "https://www.seoul.co.kr/xml/rss/rss_total.xml"},
    # 방송·통신
    {"outlet": "MBN", "url": "https://www.mbn.co.kr/rss/"},
    {"outlet": "연합뉴스TV", "url": "https://www.yonhapnewstv.co.kr/browse/feed/"},
    {"outlet": "노컷뉴스", "url": "https://rss.nocutnews.co.kr/nocutnews.xml"},
    {"outlet": "JTBC", "url": "https://fs.jtbc.co.kr/RSS/newsflash.xml"},
    # 경제지
    {"outlet": "한국경제", "url": "https://www.hankyung.com/feed/all-news"},
    {"outlet": "머니투데이", "url": "https://rss.mt.co.kr/mt_news.xml"},
    {"outlet": "이데일리", "url": "https://rss.edaily.co.kr/edaily_news.xml"},
    {"outlet": "매일경제", "url": "https://www.mk.co.kr/rss/30000001/"},
    {"outlet": "아이뉴스24", "url": "http://www.inews24.com/rss/news_all.xml"},
    {"outlet": "매일일보", "url": "https://www.m-i.kr/rss/allArticle.xml"},
    # IT·과학 (분야 풍성화)
    {"outlet": "전자신문", "url": "https://rss.etnews.com/Section901.xml"},
    {"outlet": "블로터", "url": "https://www.bloter.net/rss/allArticle.xml"},
    {"outlet": "디지털투데이", "url": "https://www.digitaltoday.co.kr/rss/allArticle.xml"},
    {"outlet": "테크M", "url": "https://www.techm.kr/rss/allArticle.xml"},
    {"outlet": "IT조선", "url": "https://it.chosun.com/rss/allArticle.xml"},
    {"outlet": "벤처스퀘어", "url": "https://www.venturesquare.net/feed"},
    {"outlet": "보안뉴스", "url": "https://www.boannews.com/media/news_rss.xml"},
    {"outlet": "스마트에프엔", "url": "https://www.smartfn.co.kr/rss/allArticle.xml"},
    {"outlet": "핀포인트뉴스", "url": "https://www.pinpointnews.co.kr/rss/allArticle.xml"},
    # 인터넷·주간지·전문지
    {"outlet": "오마이뉴스", "url": "http://rss.ohmynews.com/rss/ohmynews.xml"},
    {"outlet": "미디어오늘", "url": "http://www.mediatoday.co.kr/rss/allArticle.xml"},
    {"outlet": "시사인", "url": "https://www.sisain.co.kr/rss/allArticle.xml"},
    {"outlet": "시사저널", "url": "http://www.sisajournal.com/rss/allArticle.xml"},
    {"outlet": "더스쿠프", "url": "https://www.thescoop.co.kr/rss/allArticle.xml"},
    {"outlet": "환경일보", "url": "https://www.hkbs.co.kr/rss/allArticle.xml"},
    {"outlet": "청년의사", "url": "https://www.docdocdoc.co.kr/rss/allArticle.xml"},
    {"outlet": "스트레이트뉴스", "url": "https://www.straightnews.co.kr/rss/allArticle.xml"},
    {"outlet": "신아일보", "url": "https://www.shinailbo.co.kr/rss/allArticle.xml"},
    # 인터넷 언론
    {"outlet": "폴리뉴스", "url": "https://www.polinews.co.kr/rss/allArticle.xml"},
    {"outlet": "뉴스프리존", "url": "https://www.newsfreezone.co.kr/rss/allArticle.xml"},
    {"outlet": "시사위크", "url": "https://www.sisaweek.com/rss/allArticle.xml"},
    {"outlet": "투데이신문", "url": "https://www.ntoday.co.kr/rss/allArticle.xml"},
    {"outlet": "천지일보", "url": "https://www.newscj.com/rss/allArticle.xml"},
    {"outlet": "여성신문", "url": "https://www.womennews.co.kr/rss/allArticle.xml"},
    {"outlet": "데일리임팩트", "url": "https://www.dailyimpact.co.kr/rss/allArticle.xml"},
    {"outlet": "그린포스트코리아", "url": "https://www.greenpostkorea.co.kr/rss/allArticle.xml"},
    {"outlet": "법률방송뉴스", "url": "https://www.ltn.kr/rss/allArticle.xml"},
    {"outlet": "코리아IT타임스", "url": "https://www.koreaittimes.com/rss/allArticle.xml"},
    # 지역지
    {"outlet": "경남신문", "url": "http://www.knnews.co.kr/rss/rss.php"},
    {"outlet": "경북일보", "url": "https://www.kyongbuk.co.kr/rss/allArticle.xml"},
    {"outlet": "대전일보", "url": "https://www.daejonilbo.com/rss/allArticle.xml"},
    {"outlet": "인천일보", "url": "https://www.incheonilbo.com/rss/allArticle.xml"},
    {"outlet": "울산매일", "url": "https://www.iusm.co.kr/rss/allArticle.xml"},
    {"outlet": "충청투데이", "url": "https://www.cctoday.co.kr/rss/allArticle.xml"},
    {"outlet": "제주의소리", "url": "https://www.jejusori.net/rss/allArticle.xml"},
    {"outlet": "중부일보", "url": "https://www.joongboo.com/rss/allArticle.xml"},
    {"outlet": "충청일보", "url": "https://www.ccdailynews.com/rss/allArticle.xml"},
    {"outlet": "강원도민일보", "url": "http://www.kado.net/rss/allArticle.xml"},
    {"outlet": "경남도민일보", "url": "https://www.idomin.com/rss/allArticle.xml"},
    {"outlet": "전북도민일보", "url": "https://www.domin.co.kr/rss/allArticle.xml"},
    {"outlet": "남도일보", "url": "https://www.namdonews.com/rss/allArticle.xml"},
    {"outlet": "전남일보", "url": "https://www.jnilbo.com/rss/allArticle.xml"},
    {"outlet": "충청신문", "url": "https://www.dailycc.net/rss/allArticle.xml"},
    {"outlet": "제주일보", "url": "https://www.jejunews.com/rss/allArticle.xml"},
    # 확장 배치 (2026-07-22 2차 검증: 일간·주간·월간·지역·외신 한국어판)
    {"outlet": "국민일보", "url": "https://www.kmib.co.kr/rss/data/kmibRssAll.xml"},  # 일간지
    {"outlet": "BBC코리아", "url": "https://feeds.bbci.co.uk/korean/rss.xml"},  # 외신(한국어판)
    {"outlet": "주간조선", "url": "https://weekly.chosun.com/rss/allArticle.xml"},  # 주간지
    {"outlet": "일요서울", "url": "https://www.ilyoseoul.co.kr/rss/allArticle.xml"},  # 주간지
    {"outlet": "신동아", "url": "https://shindonga.donga.com/rss"},  # 월간지
    {"outlet": "매일노동뉴스", "url": "https://www.labortoday.co.kr/rss/allArticle.xml"},  # 전문지
    {"outlet": "통일뉴스", "url": "https://www.tongilnews.com/rss/allArticle.xml"},  # 전문지
    {"outlet": "광주드림", "url": "https://www.gjdream.com/rss/allArticle.xml"},  # 지역지
]

# 피드당 최대 수집 기사 수 (전체 볼륨 상한 관리)
MAX_ITEMS_PER_FEED = 40

# 정책 브리핑: 대한민국 정책브리핑(korea.kr) 정책뉴스.
# 공공누리 제1유형 — 출처표시 조건으로 상업적 이용·변형(AI 요약) 허용.
POLICY_LIST_URL = "https://www.korea.kr/news/policyNewsList.do"
POLICY_VIEW_URL = "https://www.korea.kr/news/policyNewsView.do?newsId={news_id}"
POLICY_COUNT = 4  # 요약할 정책뉴스 수 (사이드바 과밀 방지)

# ── 클러스터링·배분 파라미터 (알고리즘: cluster.py) ─────────────────────
MAX_ITEM_AGE_HOURS = 24    # 이 시간 이내 기사만 사용
JACCARD_THRESHOLD = 0.30   # 문자 2-그램 자카드 유사도 임계값
OVERLAP_THRESHOLD = 0.40   # 겹침 계수 임계값 (제목 길이 차이 보완)
CANDIDATE_ISSUES = 60      # AI 라벨링 대상 상위 클러스터 수
TOP_ISSUES = 48            # 사이트에 노출할 최종 이슈 수
MAX_ISSUES_PER_CATEGORY = 12  # 핫 분야라도 이 이상은 배분하지 않음
MIN_SLOTS_PER_CATEGORY = 3    # 분야별 최소 노출 보장 (후보가 있으면)
HEAT_DECAY_HOURS = 6.0     # 열기 계산의 최신성 감쇠 상수(시간)
MAX_HEADLINES_PER_ISSUE = 20

# 랭킹: 클러스터 크기(참여 매체 수)에 최우선 가중치
SIZE_EXPONENT = 2.0        # 이슈 점수 = 매체수^지수 × e^(-경과시간/감쇠)
TOP_PIN_COUNT = 3          # 점수 상위 N개는 분야 배분과 무관하게 최상단 고정

# 프론트: 최초 렌더링 카드 수 (이후 무한 스크롤로 12개씩 추가)
INITIAL_CARDS = 12

# 이슈 분류 카테고리 (AI가 이 중 하나를 지정)
ISSUE_CATEGORIES = ["정치", "경제", "사회", "국제", "IT·과학", "생활·문화", "게임"]

# 매체 성향 분류 — 이슈 카드의 성향 스펙트럼 바에 사용.
# 분류 근거: 국내 언론학 연구·한국언론진흥재단 수용자 조사에서 반복 확인되는
# 통념적 분류(사설·논조 기준)만 담는다. 경제지·통신·IT지·지역지는 정파성
# 근거가 약해 분류하지 않으며, 미분류 매체는 '중도'가 아니라 '분류 없음'으로
# 집계·표시한다 (스펙트럼 왜곡 방지).
OUTLET_BIAS = {
    "조선일보": "conservative",
    "동아일보": "conservative",
    "세계일보": "conservative",
    "MBN": "conservative",
    "경향신문": "progressive",
    "오마이뉴스": "progressive",
    "시사인": "progressive",
    "미디어오늘": "progressive",
    "뉴스프리존": "progressive",
    "주간조선": "conservative",
    "신동아": "conservative",
    "매일노동뉴스": "progressive",
    "통일뉴스": "progressive",
    "스트레이트뉴스": "progressive",
    # 나머지 매체는 '분류 없음'으로 집계되며, 관측 모델(bias_model.py)이 추정한다
    "한국경제": "moderate",
}

# 뉴스레터 구독 폼 (구글 폼 연동). 폼 생성 후 두 값을 채우면 실제 제출된다.
# ACTION 예: https://docs.google.com/forms/d/e/<FORM_ID>/formResponse
# ENTRY  예: entry.123456789  (이메일 질문 항목의 필드명)
NEWSLETTER_FORM_ACTION = os.environ.get("NEWSLETTER_FORM_ACTION", "")
NEWSLETTER_FORM_ENTRY = os.environ.get("NEWSLETTER_FORM_ENTRY", "")

# 구글 애드센스 연동 설정 (예: ca-pub-XXXXXXXXXXXXXXXX)
# GitHub Actions Variables 또는 .env에 ADSENSE_CLIENT_ID 등록 시 자동 반영
ADSENSE_CLIENT_ID = os.environ.get("ADSENSE_CLIENT_ID", "")
# Google Search Console HTML 태그 확인용 content 값 (vars.GOOGLE_SITE_VERIFICATION)
GOOGLE_SITE_VERIFICATION = os.environ.get("GOOGLE_SITE_VERIFICATION", "")

# ── 모델/사이트 ─────────────────────────────────────────────────────────
# 다중 모델 라우팅: Gemini(대규모 1차 분류) + Claude(상위 이슈 정밀 요약)
# 비용을 줄이려면 BRIEFING_MODEL=claude-haiku-4-5 로 변경.
# or 사용: CI에서 빈 문자열로 주입돼도 기본값이 적용되도록
MODEL = os.environ.get("BRIEFING_MODEL") or "claude-opus-4-8"
# 별칭 사용: 세대 교체 시 구모델 404(no longer available)를 피한다
GEMINI_MODEL = os.environ.get("GEMINI_MODEL") or "gemini-flash-latest"

# Claude(Anthropic) 사용 여부. Anthropic 크레딧이 없을 땐 꺼두고 전 구간 Gemini로만
# 돌린다(정밀 요약·정책 요약도 Gemini가 담당). 크레딧 확보 후 ENABLE_CLAUDE=1 로
# 다시 켜면 상위 이슈 Claude 정밀 요약(편향 교차 검증)이 복원된다.
ENABLE_CLAUDE = os.environ.get("ENABLE_CLAUDE", "").strip().lower() in ("1", "true", "yes", "on")

# LLM 라벨링 사용 여부 (기본 OFF = 무-API 모드).
# OFF: LLM(Gemini/Claude)을 전혀 호출하지 않고 알고리즘만으로 이슈를 만든다 —
#      제목=대표 헤드라인 원문, 분야=키워드 분류(categorize). 정밀요약·정책요약도 생략.
#      RSS 수집·클러스터링·성향·속보는 원래 API가 필요 없으므로 그대로 동작한다.
#      → API 비용 0원, 매시간 신선한 뉴스가 안정적으로 배포된다(품질만 소폭 낮음).
# ON:  LLM으로 제목·요약을 다듬고, LLM이 못 단 클러스터만 알고리즘으로 보강한다.
#      Gemini 유료 티어나 Claude 크레딧이 있을 때 ENABLE_LLM_LABELING=1 로 켠다.
ENABLE_LLM_LABELING = os.environ.get("ENABLE_LLM_LABELING", "").strip().lower() in ("1", "true", "yes", "on")

# 네이버 CLOVA Studio(HyperCLOVA X) 라벨링 모델. CLOVA_API_KEY 시크릿이 있으면 활성.
CLOVA_MODEL = os.environ.get("CLOVA_MODEL") or "HCX-007"

# 라벨링/요약 LLM 시도 우선순위 (앞에서부터, 키/활성인 엔진만). 기본 CLOVA→Gemini→Claude.
# 환경변수 LLM_PRIORITY로 재정의(예: "gemini,clova"). 전부 실패하면 무-API 알고리즘 폴백.
LLM_PRIORITY = [
    e.strip() for e in (os.environ.get("LLM_PRIORITY") or "clova,gemini,claude").split(",") if e.strip()
]

# 네이버 뉴스 검색 API 보강 수집 (기본 OFF). NAVER_CLIENT_ID/SECRET 시크릿 필요.
# 켜면 분야별 최신 기사를 추가로 모아 교차확인(매체 수)을 강화한다.
ENABLE_NAVER_SEARCH = os.environ.get("ENABLE_NAVER_SEARCH", "").strip().lower() in ("1", "true", "yes", "on")
# SOURCES.md 기준 콘텐츠 이용이 제한된 매체 도메인 — 검색 보강 결과에서도 제외한다.
NAVER_EXCLUDE_DOMAINS = {"hani.co.kr", "sbs.co.kr"}

# 네이버 데이터랩 검색어트렌드 (기본 OFF). 트렌드 키워드의 실제 검색량 상승 여부 표시.
ENABLE_DATALAB = os.environ.get("ENABLE_DATALAB", "").strip().lower() in ("1", "true", "yes", "on")

# 의미 기반 클러스터 병합 (선택, 기본 OFF). CLOVA 임베딩으로 어휘가 달라도 같은
# 사건인 클러스터를 합친다. CLOVA_API_KEY 필요.
ENABLE_EMBEDDING = os.environ.get("ENABLE_EMBEDDING", "").strip().lower() in ("1", "true", "yes", "on")
EMBED_MERGE_TOP = 120         # 임베딩 대상 상위 클러스터 수 (대표 제목만 임베딩)
EMBED_MERGE_THRESHOLD = 0.82  # 코사인 유사도 임계값 (라이브 관측으로 튜닝)

# Claude 정밀 요약(편향 교차 검증 + 3문장 리포트)을 적용할 상위 이슈 수.
# 나머지 이슈는 Gemini 1차 분류의 라벨·요약을 그대로 쓴다.
REFINE_TOP_ISSUES = 12

SITE_TITLE = "고른뉴스"
SITE_TAGLINE = "골라 담아, 고르게 전합니다"
# 사이트 기본 설명 — 메타 description·OG·JSON-LD의 폴백값으로 사용 (분산 하드코딩 방지)
SITE_DESCRIPTION = "여러 언론사의 헤드라인을 교차 확인해 매시간 정리하는 중립 뉴스 브리핑"
# 연결 도메인 (가비아 정식 도메인)
SITE_DOMAIN = "goreunnews.cloud"

# Sentry 버그 제보 위젯 — 로더 스크립트 공개 키 (cwworks/goreun-news 프로젝트).
# 브라우저용 공개 DSN 키라 저장소에 포함해도 안전하다. 비우면 위젯 미노출.
SENTRY_LOADER_KEY = os.environ.get("SENTRY_LOADER_KEY", "d80edcd8a1167eecfe0d7ef5bdb37f7c")
