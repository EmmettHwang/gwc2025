# 📱 모바일 PWA 배포 가이드 (m.kdt2025.com)

## 🎯 개요

모바일 전용 도메인 `m.kdt2025.com`으로 PWA(Progressive Web App) 배포

### ✨ 주요 기능
- ✅ 홈 화면 바로가기 추가
- ✅ 주소창 없는 전체화면 모드 (Standalone)
- ✅ 오프라인 지원 (Service Worker)
- ✅ 네이티브 앱과 유사한 UX

---

## 📋 사전 준비

### 1. 아이콘 파일 생성 (필수)

다음 크기의 PNG 아이콘 파일을 생성하여 `/frontend/mobile/` 디렉토리에 배치:

```
/frontend/mobile/
├── icon-180x180.png  (Apple Touch Icon)
├── icon-192x192.png  (Android 홈 화면)
└── icon-512x512.png  (Android 스플래시 스크린)
```

**아이콘 생성 방법**:
1. 512x512 원본 이미지 준비 (우송대학교 로고 사용 권장)
2. 온라인 도구 사용: https://realfavicongenerator.net/
3. 또는 직접 리사이즈:
   ```bash
   # ImageMagick 사용
   convert logo.png -resize 180x180 icon-180x180.png
   convert logo.png -resize 192x192 icon-192x192.png
   convert logo.png -resize 512x512 icon-512x512.png
   ```

### 2. 스크린샷 생성 (선택사항)

앱 소개용 스크린샷:
```
/frontend/mobile/screenshot1.png  (540x720)
```

---

## 🚀 Cloudflare Pages 배포

### 1단계: 빌드 설정

**wrangler.jsonc 또는 Cloudflare Dashboard 설정**:

```json
{
  "name": "biohealth-mobile",
  "pages_build_output_dir": "./frontend",
  "compatibility_date": "2024-01-01"
}
```

### 2단계: 커스텀 도메인 설정

Cloudflare Dashboard에서:

1. **Pages 프로젝트** → **Custom domains**
2. **Add a custom domain**: `m.kdt2025.com`
3. DNS 설정:
   ```
   Type: CNAME
   Name: m
   Target: [your-project].pages.dev
   Proxy: Enabled (오렌지 클라우드)
   ```

### 3단계: HTTPS 강제 리다이렉트

Cloudflare Dashboard → **SSL/TLS** → **Edge Certificates**:
- **Always Use HTTPS**: ON ✅
- **Automatic HTTPS Rewrites**: ON ✅

### 4단계: 배포

```bash
# 프로젝트 루트에서
wrangler pages deploy frontend --project-name biohealth-mobile

# 또는 npm script
npm run deploy
```

---

## 📱 PWA 설치 방법

### iOS (Safari)

1. `m.kdt2025.com` 접속
2. 하단 공유 버튼 (⬆️) 탭
3. **"홈 화면에 추가"** 선택
4. 앱 이름 확인: "바이오헬스"
5. **추가** 탭

**결과**: 
- ✅ 홈 화면에 아이콘 생성
- ✅ 주소창 없는 전체화면 모드
- ✅ 네이티브 앱처럼 실행

### Android (Chrome)

**방법 1: 자동 프롬프트**
1. `m.kdt2025.com` 접속
2. "홈 화면에 추가" 배너 표시
3. **설치** 탭

**방법 2: 수동 설치**
1. `m.kdt2025.com` 접속
2. 우측 상단 메뉴 (⋮) → **"홈 화면에 추가"**
3. **설치** 탭

**결과**:
- ✅ 홈 화면에 아이콘 생성
- ✅ 주소창 없는 전체화면 모드
- ✅ 앱 서랍에 등록

---

## 🔧 주소창 제거 원리

### manifest.json 설정

```json
{
  "display": "standalone"
}
```

**display 모드 옵션**:
- `fullscreen` - 완전한 전체화면 (상태바도 숨김)
- `standalone` - 브라우저 UI 없음 (상태바 유지) ✅ **권장**
- `minimal-ui` - 최소한의 브라우저 UI
- `browser` - 일반 브라우저 탭

### HTML Meta 태그

```html
<!-- 주소창 제거 -->
<meta name="mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-capable" content="yes">

<!-- 상태바 스타일 -->
<meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">

<!-- 전체화면 영역 사용 (노치 대응) -->
<meta name="viewport" content="viewport-fit=cover">
```

---

## 🎨 테마 색상 설정

```json
{
  "theme_color": "#3B82F6",      // 상태바 색상
  "background_color": "#FFFFFF"  // 스플래시 배경색
}
```

---

## ✅ 배포 후 확인사항

### 1. PWA 체크리스트

Chrome DevTools → **Lighthouse** → **Progressive Web App** 실행

**필수 항목**:
- ✅ HTTPS로 제공됨
- ✅ Service Worker 등록됨
- ✅ manifest.json 유효함
- ✅ 아이콘 모든 크기 제공
- ✅ 뷰포트 메타 태그 설정
- ✅ 테마 색상 설정

### 2. 설치 테스트

**iOS**:
```bash
# Safari에서 확인
1. m.kdt2025.com 접속
2. 홈 화면 추가
3. 홈 화면 아이콘 탭
4. 주소창 없는지 확인 ✅
```

**Android**:
```bash
# Chrome에서 확인
1. m.kdt2025.com 접속
2. 설치 배너 확인
3. 설치 후 실행
4. 주소창 없는지 확인 ✅
```

### 3. Service Worker 확인

Chrome DevTools → **Application** → **Service Workers**
- ✅ Status: Activated and running
- ✅ Scope: /mobile/

---

## 🔍 문제 해결

### Q1. 주소창이 여전히 보임

**원인**: 일반 브라우저 탭으로 열림

**해결**:
1. 홈 화면 아이콘으로 실행 (브라우저 직접 접속 X)
2. manifest.json 확인: `"display": "standalone"`
3. 캐시 삭제 후 재설치

### Q2. 아이콘이 안 보임

**원인**: 아이콘 파일 경로 오류

**해결**:
1. 아이콘 파일 존재 확인: `/mobile/icon-*.png`
2. manifest.json 경로 확인
3. HTTPS 제공 확인

### Q3. "홈 화면 추가" 버튼 없음

**원인**: PWA 요구사항 미충족

**해결**:
1. HTTPS 확인
2. manifest.json 유효성 검사
3. Service Worker 등록 확인

---

## 📚 참고 자료

- [Web.dev PWA 가이드](https://web.dev/progressive-web-apps/)
- [MDN PWA 문서](https://developer.mozilla.org/en-US/docs/Web/Progressive_web_apps)
- [Apple PWA 가이드](https://developer.apple.com/library/archive/documentation/AppleApplications/Reference/SafariWebContent/ConfiguringWebApplications/ConfiguringWebApplications.html)

---

## 🎉 완료!

이제 `m.kdt2025.com`이 완전한 PWA로 동작합니다:
- ✅ 홈 화면 바로가기
- ✅ 주소창 없는 전체화면
- ✅ 오프라인 지원
- ✅ 네이티브 앱 경험
