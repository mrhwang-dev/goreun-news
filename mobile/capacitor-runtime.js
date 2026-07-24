// 고른뉴스 앱 — Capacitor JS 런타임 번들 엔트리 (esbuild → site/capacitor.js).
//
// 이 프로젝트는 번들러 없는 정적 사이트라, 네이티브 앱 WebView에는 Capacitor의
// native-bridge.js만 주입되고 플러그인 JS는 로드되지 않는다. native-bridge.js는
// window.Capacitor.Plugins 를 "읽기만" 할 뿐 채우지 않으므로, 아무것도 하지 않으면
// window.Capacitor.Plugins.* 가 전부 undefined 가 되어 native.js의 모든 네이티브 기능이
// 조용히 무력화된다(= 앱이 사실상 단순 웹뷰).
//
// 각 플러그인을 import 하면 @capacitor/core 의 registerPlugin() 부수효과가 실행되어
// 기존 전역 window.Capacitor(native-bridge)에 병합되고 Capacitor.Plugins.* 프록시가
// 등록된다. native.js 는 이 전역 브리지를 사용한다.
import { Capacitor } from '@capacitor/core';
import { Haptics } from '@capacitor/haptics';
import { Share } from '@capacitor/share';
import { PushNotifications } from '@capacitor/push-notifications';
import { StatusBar } from '@capacitor/status-bar';
import { App } from '@capacitor/app';
import { Preferences } from '@capacitor/preferences';
import { SplashScreen } from '@capacitor/splash-screen';
import { AdMob } from '@capacitor-community/admob';

// import 만으로도 Plugins 가 채워지지만, 트리셰이킹 방지 + 명시적 노출을 위해 직접 할당한다.
const C = (typeof window !== 'undefined' && window.Capacitor) || Capacitor;
C.Plugins = C.Plugins || {};
Object.assign(C.Plugins, {
  Haptics,
  Share,
  PushNotifications,
  StatusBar,
  App,
  Preferences,
  SplashScreen,
  AdMob,
});
if (typeof window !== 'undefined') window.Capacitor = C;
