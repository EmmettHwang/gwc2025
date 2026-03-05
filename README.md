# GWC2025 - Global Working Center

**v0.2.20260305** | 대한민국 계절근로자 통합 관리 플랫폼

## Overview

외국인 계절근로자(E-8 비자)의 모집, 배정, 근태관리, 상담 등을 통합 관리하는 웹 플랫폼입니다.

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Backend | Python 3.10, FastAPI, Uvicorn |
| Database | MariaDB (MySQL compatible) |
| Frontend | Vanilla JS, Tailwind CSS |
| AI/RAG | Groq/Gemini API, Sentence Transformers |

## Project Structure

```
gwc2025/
├── backend/
│   ├── main.py              # 메인 서버 (RISELMS + KWV 통합)
│   ├── kwv_api.py            # KWV 전용 API 라우터
│   ├── kwv_server.py         # KWV 독립 서버
│   ├── auth.py               # 인증 모듈
│   ├── rag/                  # RAG 챗봇 모듈
│   └── requirements.txt
├── frontend/
│   ├── kwv-dashboard.html    # 관리자 대시보드
│   ├── kwv-landing.html      # 랜딩 페이지
│   ├── kwv-login.html        # 로그인
│   ├── kwv-register.html     # 회원가입
│   ├── applicant/            # 지원자 포털
│   └── mobile/               # 모바일 앱
└── .env                      # 환경변수 (git 제외)
```

## Features

- **지자체 관리** - 국내 지자체, MOU 해외 기관, 구인 관리
- **근로자 관리** - 지원자 현황, 출퇴근(GPS/QR), 활동일지, 포인트
- **상담/보험** - 상담일지, 보험 관리
- **리포트 & AI** - 통계 리포트 내보내기, 이상감지
- **AI Helper** - 비자안내, FAQ, RAG 기반 AI 챗봇
- **다국어** - 한국어, English, Tiếng Việt, ภาษาไทย, Pilipino

## Setup

```bash
# 1. 환경변수 설정
cp .env.example .env
# .env 파일에 DB 접속정보 및 API 키 입력

# 2. 패키지 설치
pip install -r backend/requirements.txt

# 3. 서버 실행
cd backend
uvicorn main:app --host 0.0.0.0 --port 8080
```

## Environment Variables

| Key | Description |
|-----|------------|
| `DB_HOST` | 데이터베이스 호스트 |
| `DB_USER` | DB 사용자 |
| `DB_PASSWORD` | DB 비밀번호 |
| `DB_NAME` | DB 이름 (koreaworkingvisa) |
| `JWT_SECRET` | JWT 토큰 시크릿 키 |
| `GOOGLE_CLIENT_ID` | Google OAuth 클라이언트 ID |

## License

Private - All rights reserved
