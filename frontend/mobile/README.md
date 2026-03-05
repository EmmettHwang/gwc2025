# 바이오헬스교육관리 모바일 웹앱

## 📱 프로젝트 개요

바이오헬스 교육 관리를 위한 모바일 최적화 웹 애플리케이션입니다.
강사와 학생이 언제 어디서나 모바일 기기로 교육 관리 업무를 수행할 수 있습니다.

## 🎯 주요 기능

### 공통 메뉴 (3개)
1. **내 정보** (`profile.html`)
   - 프로필 사진 업로드 및 미리보기
   - 개인정보 수정 (연락처, 이메일, 전공/부서)
   - 비밀번호 변경

2. **SSIRN메모장** (`ssirn.html`)
   - 메모 작성, 수정, 삭제
   - 사진 첨부 (최대 5장)
   - 메모 검색 기능
   - 사진 썸네일 및 확대 보기

3. **공지사항** (`notices.html`)
   - 공지사항 조회 (전체/일반/긴급/중요 필터)
   - 강사: 공지사항 작성, 수정, 삭제
   - 학생: 공지사항 조회만 가능
   - NEW 배지 표시 (24시간 이내)

### 역할별 메뉴 (3개)

#### 강사 전용
- **상담관리** (`counseling.html`)
  - 학생별 상담 등록 및 관리
  - 상담 상태 관리 (예정/완료/취소)
  - 상담 유형 설정 (정기/긴급/학생요청)
  - 사진 첨부 기능

- **훈련일지** (`training.html`)
  - 학생별 훈련일지 작성 및 관리
  - 훈련 유형, 시간, 강도 기록
  - 월별 필터링
  - 사진 첨부 기능

- **팀 활동일지** (`team.html`)
  - 팀 활동 등록 및 관리
  - 활동 유형, 참여 인원, 소요 시간 기록
  - 성과 및 결과 기록
  - 월별 필터링

#### 학생 전용
- **상담신청** (`counseling.html`)
  - 상담 신청
  - 선호 강사 선택 (선택사항)
  - 신청 내역 조회
  - 사진 첨부 기능

- **훈련일지** (`training.html`)
  - 개인 훈련 기록 작성
  - 훈련 내용 및 특이사항 기록
  - 월별 조회
  - 사진 첨부 기능

- **팀 활동** (`team.html`)
  - 팀 활동 기록 작성
  - 팀명, 참여 인원, 활동 내용 기록
  - 월별 조회
  - 사진 첨부 기능

## 🏗️ 기술 스택

### Frontend
- **HTML5** - 웹 표준 마크업
- **TailwindCSS** - 유틸리티 기반 CSS 프레임워크
- **Vanilla JavaScript** - 프레임워크 없는 순수 JavaScript
- **Axios** - HTTP 클라이언트
- **Font Awesome** - 아이콘 라이브러리

### Backend
- 기존 FastAPI 백엔드 공유 사용 (포트 8000)
- RESTful API 통신

## 📂 파일 구조

```
mobile/
├── login.html          # 로그인 페이지
├── index.html          # 메인 메뉴 페이지
├── profile.html        # 내 정보
├── ssirn.html          # SSIRN메모장
├── notices.html        # 공지사항
├── counseling.html     # 상담관리/신청
├── training.html       # 훈련일지
├── team.html           # 팀 활동일지
└── README.md           # 프로젝트 문서
```

## 🎨 디자인 특징

### 모바일 최적화
- **반응형 디자인**: 다양한 모바일 화면 크기 지원
- **터치 최적화**: 터치 인터랙션에 최적화된 UI
- **폰트 크기**: iOS 자동 줌 방지 (최소 16px)
- **Tap Highlight**: 불필요한 탭 하이라이트 제거

### 컬러 시스템
- **내 정보**: Blue Gradient (from-blue-500 to-indigo-600)
- **SSIRN메모장**: Green Gradient (from-green-500 to-emerald-600)
- **공지사항**: Purple Gradient (from-purple-500 to-indigo-600)
- **상담**: Orange Gradient (from-orange-500 to-red-600)
- **훈련일지**: Indigo Gradient (from-indigo-500 to-blue-600)
- **팀 활동**: Pink Gradient (from-pink-500 to-rose-600)

### 사용자 경험 (UX)
- **애니메이션**: 부드러운 페이드인 및 트랜지션 효과
- **피드백**: 터치 시 시각적 피드백 제공
- **로딩 상태**: 데이터 로딩 중 명확한 상태 표시
- **에러 처리**: 사용자 친화적인 에러 메시지

## 🔐 인증 및 보안

### 인증 방식
- SessionStorage 기반 인증
- 통합 로그인 API 사용 (`/api/auth/login`)
- 자동 리다이렉트 (미인증 시 로그인 페이지로 이동)

### 데이터 저장
- `user`: 사용자 정보 객체 (JSON)
- `user_type`: 사용자 유형 ('instructor' 또는 'student')

## 📸 사진 업로드 기능

### 특징
- 최대 5장까지 업로드 가능
- 자동 이미지 압축 (최대 800x800px, JPEG 80% 품질)
- 미리보기 기능
- 개별 사진 삭제 가능
- 기존 사진과 새 사진 구분 관리

### 지원 형식
- 이미지 파일만 업로드 가능 (`accept="image/*"`)
- Canvas API를 통한 클라이언트 사이드 압축

## 🚀 로컬 개발 환경

### 1. 백엔드 서버 시작
```bash
cd /home/user/webapp
pm2 start ecosystem.config.cjs
```

### 2. 프론트엔드 접속
```
http://localhost:3000/mobile/login.html
```

### 3. API 베이스 URL
- 개발 환경: `http://localhost:8000`
- 자동 포트 변환: 3000 → 8000

## 📱 테스트 계정

### 강사 계정
- 이름: (기존 강사 계정 사용)
- 비밀번호: (기존 비밀번호)
- 역할: instructor

### 학생 계정
- 이름: (기존 학생 계정 사용)
- 비밀번호: (기존 비밀번호)
- 역할: student

## 🔄 API 엔드포인트

### 인증
- `POST /api/auth/login` - 통합 로그인

### 사용자 관리
- `GET /api/instructors/{code}` - 강사 정보 조회
- `PUT /api/instructors/{code}` - 강사 정보 수정
- `GET /api/students/{id}` - 학생 정보 조회
- `PUT /api/students/{id}` - 학생 정보 수정

### SSIRN 메모
- `GET /api/class-notes?instructor_code={code}` - 강사 메모 조회
- `GET /api/class-notes?student_id={id}` - 학생 메모 조회
- `POST /api/class-notes` - 메모 생성
- `PUT /api/class-notes/{id}` - 메모 수정
- `DELETE /api/class-notes/{id}` - 메모 삭제

### 공지사항
- `GET /api/notices` - 공지사항 조회
- `POST /api/notices` - 공지사항 생성 (강사)
- `PUT /api/notices/{id}` - 공지사항 수정 (강사)
- `DELETE /api/notices/{id}` - 공지사항 삭제 (강사)

### 상담
- `GET /api/counselings?instructor_code={code}` - 강사 상담 조회
- `GET /api/counselings?student_id={id}` - 학생 상담 조회
- `POST /api/counselings` - 상담 생성
- `PUT /api/counselings/{id}` - 상담 수정
- `DELETE /api/counselings/{id}` - 상담 삭제

### 훈련일지
- `GET /api/training-logs?instructor_code={code}` - 강사 훈련일지 조회
- `GET /api/training-logs?student_id={id}` - 학생 훈련일지 조회
- `POST /api/training-logs` - 훈련일지 생성
- `PUT /api/training-logs/{id}` - 훈련일지 수정
- `DELETE /api/training-logs/{id}` - 훈련일지 삭제

### 팀 활동
- `GET /api/team-activities?instructor_code={code}` - 강사 팀 활동 조회
- `GET /api/team-activities?student_id={id}` - 학생 팀 활동 조회
- `POST /api/team-activities` - 팀 활동 생성
- `PUT /api/team-activities/{id}` - 팀 활동 수정
- `DELETE /api/team-activities/{id}` - 팀 활동 삭제

### 파일 업로드
- `POST /api/upload-photo` - 사진 업로드 (multipart/form-data)

## ✅ 구현 완료 사항

### 2024-11-24
- ✅ 로그인 페이지 (모바일 최적화)
- ✅ 메인 메뉴 페이지 (6개 메뉴 구조)
- ✅ 내 정보 페이지 (프로필 관리)
- ✅ SSIRN메모장 페이지 (메모 CRUD)
- ✅ 공지사항 페이지 (조회 및 관리)
- ✅ 상담관리/신청 페이지 (역할별 기능)
- ✅ 훈련일지 페이지 (월별 필터링)
- ✅ 팀 활동일지 페이지 (성과 기록)

## 🔮 향후 개선 사항

### 기능 개선
- [ ] 오프라인 모드 지원 (Service Worker)
- [ ] PWA 변환 (Progressive Web App)
- [ ] 푸시 알림 기능
- [ ] 다크 모드 지원

### UX/UI 개선
- [ ] 스켈레톤 로딩 화면
- [ ] 무한 스크롤 구현
- [ ] 드래그 앤 드롭 파일 업로드
- [ ] 이미지 편집 기능 (크롭, 회전)

### 성능 최적화
- [ ] 이미지 레이지 로딩
- [ ] API 응답 캐싱
- [ ] 번들 사이즈 최적화
- [ ] 코드 스플리팅

## 📞 문의 및 지원

프로젝트 관련 문의사항이나 버그 리포트는 개발팀에 문의해주세요.

---

**Version**: 1.0.0  
**Last Updated**: 2024-11-24  
**License**: Proprietary
