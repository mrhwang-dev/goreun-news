# 고른뉴스 모바일 앱 (iOS / Android)

Python 정적 사이트(`site/`)를 **Capacitor**로 감싸 App Store / Google Play에 올릴 수 있는
네이티브 앱으로 패키징합니다. 웹 코드는 그대로 두고, 네이티브 기능은 `native.js` 브리지가 담당합니다.

```
run.py (Python)  ──빌드──►  site/  ──cap sync──►  ios/  ·  android/  ──Xcode/Studio──►  .ipa / .aab
                          (webDir)                (네이티브 셸)
```

- **웹에서는** `native.js`가 전부 no-op → 기존 사이트 동작 100% 유지
- **앱에서만** 햅틱·네이티브 공유·푸시·상태바/세이프에어리어·오프라인 캐시가 켜짐

---

## 1. 사전 준비

| 대상 | 필요 도구 |
|------|-----------|
| 공통 | Node.js **22+** (`@capacitor/cli` 요구), Python 3.9+ (사이트 빌드) |
| iOS  | **Xcode 15+** (필수 — 이 저장소를 만든 머신엔 Command Line Tools만 있어 iOS **빌드는 불가**했습니다), Apple Developer 계정 |
| Android | **Android Studio** + **JDK 17** |

> Capacitor 8은 iOS 의존성을 **Swift Package Manager**로 관리합니다. **CocoaPods는 필요 없습니다.**

앱 메타데이터: 이름 **고른뉴스**, App ID **`cloud.goreunnews.app`** (`capacitor.config.json`).

---

## 2. 빌드 명령어 (`package.json`)

```bash
npm install              # 최초 1회 — Capacitor + 플러그인 설치

npm run app:web          # site/ 를 예시 데이터로 생성 (python run.py --mock)
npm run app:build        # npx cap sync — 현재 site/ 를 네이티브 프로젝트로 복사 + 플러그인 반영
npm run app:ios          # cap sync ios + Xcode 열기
npm run app:android      # cap sync android + Android Studio 열기
npm run app:assets       # 앱 아이콘/스플래시 생성 (아래 4-D 참고)
```

**콘텐츠 갱신 흐름**: 실제 뉴스로 배포하려면 먼저 파이프라인으로 `site/`를 만든 뒤 동기화합니다.

```bash
python run.py            # 실제 뉴스 브리핑 생성 (ANTHROPIC_API_KEY 필요)  ← 콘텐츠의 원천
npm run app:build        # site/ → ios/·android/ 로 복사
```

> ⚠️ `app:build`는 웹을 다시 만들지 않고 **현재 `site/`를 그대로 동기화**합니다.
> 최신 콘텐츠를 담으려면 `python run.py`(또는 `npm run app:web`)를 **먼저** 실행하세요.

---

## 3. 애플 지침 4.2 준수 — 추가된 네이티브 기능

단순 웹뷰 래퍼(4.2 거절)를 넘어서기 위해 다음을 네이티브로 구현했습니다. 구현은
`build_site.py`의 `NATIVE_SCRIPT` 상수 → 빌드 시 `site/native.js`로 출력됩니다.

| 기능 | 플러그인 | 동작 |
|------|----------|------|
| 햅틱 피드백 | `@capacitor/haptics` | 탭 전환·카드 펼치기·스크랩·공유 시 진동 (위임 리스너) |
| 네이티브 공유 | `@capacitor/share` | 공유 버튼 → iOS/Android OS 공유 시트 (웹 클립보드 폴백 대체) |
| 푸시 알림 | `@capacitor/push-notifications` | 속보/시간별 브리핑 알림 구조, 토큰 저장, 탭 시 딥링크 이동 |
| 오프라인 캐시 | `@capacitor/preferences` | `briefing.json`을 로컬 저장 → 오프라인에서도 읽기 가능 |
| 노치/상태바 | `@capacitor/status-bar` + Safe Area CSS | 상태바 오버레이 + `env(safe-area-inset-*)` 패딩 (다이내믹 아일랜드 대응) |
| 앱 생명주기 | `@capacitor/app` | 포그라운드 복귀 시 갱신, Android 하드웨어 뒤로가기 |

권한 최소화: 카메라·위치·마이크 등을 쓰지 않으므로 `NS*UsageDescription` 문자열은
**의도적으로 넣지 않았습니다** (미사용 권한 선언은 오히려 심사 거절 사유).

---

## 4. 앱 빌드 전 남은 수동 단계

이 저장소엔 Xcode/Studio가 없어 **네이티브 컴파일은 검증하지 못했습니다.** 아래는
개발자 머신에서 열었을 때 필요한 계정 종속·GUI 단계입니다.

### A. iOS 서명 (필수)
Xcode ▸ Target `App` ▸ **Signing & Capabilities** ▸ Team 선택 (자동 서명). 시뮬레이터 실행엔 팀 없이도 가능.

### B. iOS 푸시 활성화 (푸시를 실제로 테스트할 때)
Signing & Capabilities ▸ **+ Capability ▸ Push Notifications** 추가 →
Xcode가 준비된 `ios/App/App/App.entitlements`(`aps-environment`)를 자동 연결합니다.
Apple Developer 포털에서 App ID에 Push 활성화 + APNs 키 발급이 필요합니다.
> 푸시 미설정 상태에서도 앱은 정상 빌드/실행됩니다(등록만 조용히 실패).

### C. Android 푸시 (FCM)
`@capacitor/push-notifications`의 Android는 **Firebase**를 씁니다. Firebase 콘솔에서
`google-services.json`을 받아 `android/app/`에 넣어야 푸시 등록이 됩니다.
> 이 파일이 없어도 **일반 빌드·실행은 정상**입니다(푸시 등록만 실패). Play 배포 자체엔 불필요.

### D. 앱 아이콘 / 스플래시 생성
브랜드 소스는 `assets/app/`에 준비돼 있습니다
(`icon-only`, `icon-foreground`, `icon-background`, `splash`, `splash-dark`).

```bash
npm run app:assets       # @capacitor/assets 가 iOS/Android 전 사이즈 자동 생성
```

> `@capacitor/assets`는 내부적으로 `sharp`(네이티브 모듈)를 씁니다. 설치 환경에 따라
> `npm rebuild sharp` 또는 `npm install --include=optional sharp`가 필요할 수 있습니다.
> 생성기를 돌리기 전에도 iOS AppIcon엔 브랜드 1024 아이콘이 이미 들어가 있어 앱은 브랜딩된 채로 빌드됩니다.

---

## 5. 콘텐츠 모드 — 번들(오프라인 우선) vs 라이브

현재 기본값은 **번들 모드**: `webDir: "site"`를 앱에 동봉 → 네트워크 없이도 완전히 동작하며,
`native.js`가 백그라운드로 원격 `briefing.json`을 받아 캐시를 갱신합니다. 4.2 심사에
가장 안전한 형태(자체 완결형 + 진짜 네이티브 기능)입니다.

**라이브 모드**(항상 최신 웹을 로드)로 바꾸려면 `capacitor.config.json`에 추가:

```jsonc
"server": {
  "url": "https://goreunnews.cloud",
  "cleartext": false
}
```

라이브 모드에선 원격 사이트도 동일한 `native.js`를 포함하므로 네이티브 기능은 그대로 작동합니다.
다만 URL만 감싸는 형태는 4.2 위험이 더 크므로, 네이티브 기능 유지가 중요합니다.

---

## 6. 개인정보 · 보안

- **`ios/App/App/PrivacyInfo.xcprivacy`** (개인정보 매니페스트): 추적 없음, 수집 데이터 없음,
  Required Reason API는 UserDefaults(`CA92.1`, Capacitor 코어 + Preferences)만 선언. Xcode 프로젝트에 이미 연결됨.
- **ATS**: `NSAllowsArbitraryLoads=false` — 전 트래픽 HTTPS 강제(모든 엔드포인트가 HTTPS).
- **`ITSAppUsesNonExemptEncryption=false`**: 표준 HTTPS만 사용 → 수출 규정 면제(업로드 시 문항 자동 통과).
- 계정/스크랩/설정은 모두 기기 로컬 저장이며 서버로 전송되지 않습니다.

---

## 7. 저장소 구조

```
capacitor.config.json          앱 ID·이름·webDir·플러그인 설정
package.json                   app:* 빌드 스크립트 + Capacitor 의존성
assets/app/                    아이콘·스플래시 소스 (커밋됨)
ios/                           Xcode 프로젝트 (네이티브 설정 커밋, 빌드 산출물은 ios/.gitignore)
  App/App/Info.plist           ATS·백그라운드 모드·암호화 선언
  App/App/PrivacyInfo.xcprivacy 개인정보 매니페스트
  App/App/App.entitlements     푸시 엔타이틀먼트(수동 연결 대기)
android/                       Android Studio 프로젝트 (동일 원칙)
build_site.py                  NATIVE_SCRIPT/SAFE_AREA_STYLE → site/native.js 및 head 주입
site/native.js                 (생성물) Capacitor 네이티브 브리지
```

`site/`, `node_modules/`, 네이티브 빌드 산출물은 `.gitignore` 처리됩니다.
