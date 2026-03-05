#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
KoreaWorkingVisa 독립 서버
- 기존 RISELMS 서버와 별도로 실행 가능
"""

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, RedirectResponse
import os

# FastAPI 앱 생성
app = FastAPI(
    title="Korea Working Visa API",
    description="비자 신청자 및 관리자 포털",
    version="0.2.20260305"
)

# CORS 설정
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# KWV API 라우터 추가
from kwv_api import router as kwv_router
app.include_router(kwv_router)

# 프론트엔드 디렉토리
frontend_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "frontend")

# 정적 파일 서빙
if os.path.exists(frontend_dir):
    admin_dir = os.path.join(frontend_dir, "admin")
    if os.path.exists(admin_dir):
        app.mount("/admin", StaticFiles(directory=admin_dir, html=True), name="admin")

    applicant_dir = os.path.join(frontend_dir, "applicant")
    if os.path.exists(applicant_dir):
        app.mount("/applicant", StaticFiles(directory=applicant_dir, html=True), name="applicant")

    js_dir = os.path.join(frontend_dir, "js")
    if os.path.exists(js_dir):
        app.mount("/js", StaticFiles(directory=js_dir), name="js")

    videos_dir = os.path.join(frontend_dir, "videos")
    if os.path.exists(videos_dir):
        app.mount("/videos", StaticFiles(directory=videos_dir), name="videos")

    # 프론트엔드 루트 정적 파일 (이미지, CSS 등) 서빙
    app.mount("/static", StaticFiles(directory=frontend_dir), name="static")

# 로고 파일 직접 서빙
@app.get("/woosong-logo.png")
async def serve_logo():
    logo_path = os.path.join(frontend_dir, "woosong-logo.png")
    if os.path.exists(logo_path):
        return FileResponse(logo_path, media_type="image/png")
    raise HTTPException(status_code=404, detail="Logo not found")

# 루트 페이지 -> 랜딩 페이지로 리다이렉트
@app.get("/")
async def root():
    return RedirectResponse(url="/kwv-landing.html")

# 랜딩 페이지
@app.get("/kwv-landing.html")
async def serve_landing():
    landing_path = os.path.join(frontend_dir, "kwv-landing.html")
    if os.path.exists(landing_path):
        return FileResponse(landing_path, media_type="text/html")
    return RedirectResponse(url="/kwv-login.html")

# 통합 로그인 페이지
@app.get("/kwv-login.html")
async def serve_login():
    login_path = os.path.join(frontend_dir, "kwv-login.html")
    if os.path.exists(login_path):
        return FileResponse(login_path, media_type="text/html")
    return {"error": "Login page not found"}

# 회원가입 페이지
@app.get("/kwv-register.html")
async def serve_register():
    register_path = os.path.join(frontend_dir, "kwv-register.html")
    if os.path.exists(register_path):
        return FileResponse(register_path, media_type="text/html")
    return RedirectResponse(url="/kwv-login.html")

# Google OAuth 콜백 페이지
@app.get("/kwv-google-callback.html")
async def serve_google_callback():
    callback_path = os.path.join(frontend_dir, "kwv-google-callback.html")
    if os.path.exists(callback_path):
        return FileResponse(callback_path, media_type="text/html")
    return RedirectResponse(url="/kwv-login.html")

# MOU 쇼케이스 페이지
@app.get("/kwv-mou-showcase.html")
async def serve_mou_showcase():
    mou_path = os.path.join(frontend_dir, "kwv-mou-showcase.html")
    if os.path.exists(mou_path):
        return FileResponse(mou_path, media_type="text/html")
    return RedirectResponse(url="/kwv-landing.html")

# 개인정보처리방침 페이지
@app.get("/kwv-privacy.html")
async def serve_privacy():
    privacy_path = os.path.join(frontend_dir, "kwv-privacy.html")
    if os.path.exists(privacy_path):
        return FileResponse(privacy_path, media_type="text/html")
    return RedirectResponse(url="/kwv-landing.html")

# 대시보드 페이지
@app.get("/kwv-dashboard.html")
async def serve_dashboard():
    dashboard_path = os.path.join(frontend_dir, "kwv-dashboard.html")
    if os.path.exists(dashboard_path):
        return FileResponse(dashboard_path, media_type="text/html")
    return RedirectResponse(url="/kwv-login.html")

if __name__ == "__main__":
    import uvicorn
    print("=" * 50)
    print("  Korea Working Visa Server")
    print("=" * 50)
    print(f"  Login: http://localhost:8000/kwv-login.html")
    print(f"  Register: http://localhost:8000/kwv-register.html")
    print(f"  Admin: http://localhost:8000/admin/dashboard.html")
    print(f"  Applicant: http://localhost:8000/applicant/dashboard.html")
    print("=" * 50)
    uvicorn.run(app, host="0.0.0.0", port=8000)
