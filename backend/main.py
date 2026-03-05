# -*- coding: utf-8 -*-
import os
from pathlib import Path
from dotenv import load_dotenv

# .env 파일을 먼저 로드 (다른 모듈 import 전에 환경변수 설정)
env_path = Path(__file__).parent.parent / '.env'
load_dotenv(dotenv_path=env_path, override=True)

from fastapi import FastAPI, File, UploadFile, HTTPException, Query, Form, Request
# KWV Auth Module
from auth import router as auth_router
from kwv_api import router as kwv_router
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, FileResponse, HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from typing import Optional, List
import pymysql
import pandas as pd
import io
import logging
from logging.handlers import TimedRotatingFileHandler
from datetime import datetime, timedelta, date
from openai import OpenAI
import requests
from ftplib import FTP
import uuid
import threading
import base64
from PIL import Image
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak
from reportlab.lib import colors
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.lib.enums import TA_CENTER, TA_LEFT

app = FastAPI(
    title="학급 관리 시스템 API",
    # 요청 크기 제한 설정 (기본 10MB)
    # Cafe24 배포 시 nginx client_max_body_size도 조정 필요
)

# ========== 로깅 설정 (7일 로테이션) ==========
LOG_DIR = os.path.join(os.path.dirname(__file__), "logs")
os.makedirs(LOG_DIR, exist_ok=True)

# 로그 포맷 설정
log_formatter = logging.Formatter(
    '%(asctime)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)

# 파일 핸들러: 매일 자정에 로테이션, 7일치 보관
file_handler = TimedRotatingFileHandler(
    filename=os.path.join(LOG_DIR, "app.log"),
    when="midnight",
    interval=1,
    backupCount=7,
    encoding="utf-8"
)
file_handler.setFormatter(log_formatter)
file_handler.suffix = "%Y-%m-%d"

# 콘솔 핸들러
console_handler = logging.StreamHandler()
console_handler.setFormatter(log_formatter)

# 루트 로거 설정
logger = logging.getLogger("riselms")
logger.setLevel(logging.INFO)
logger.addHandler(file_handler)
logger.addHandler(console_handler)

# uvicorn 로거도 파일에 기록
uvicorn_logger = logging.getLogger("uvicorn.access")
uvicorn_logger.addHandler(file_handler)

logger.info("RISELMS 서버 시작 - 로그 로테이션 활성화 (7일 보관)")
# ================================================

# 정적 파일 서빙 (프론트엔드)
import os
frontend_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "frontend")
public_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "public")

if os.path.exists(frontend_dir):
    app.mount("/static", StaticFiles(directory=frontend_dir), name="static")

# public 폴더의 GLB 파일을 frontend에서 직접 접근 가능하도록 심볼릭 링크 또는 복사
# 또는 별도 라우트로 서빙

# KWV 인증 라우터 등록
app.include_router(auth_router)
app.include_router(kwv_router)

# CORS 설정
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 3D 모델 파일 (GLB) 서빙
from fastapi.responses import FileResponse
from fastapi import HTTPException

# 방법 1: 루트 경로에서 서빙 (프록시 서버와 충돌 가능)
@app.get("/{filename}.glb")
async def serve_glb_file_root(filename: str):
    """루트 경로에서 GLB 파일 서빙 (3D 모델용)"""
    glb_path = os.path.join(frontend_dir, f"{filename}.glb")
    if os.path.exists(glb_path):
        return FileResponse(glb_path, media_type="model/gltf-binary")
    else:
        raise HTTPException(status_code=404, detail=f"GLB file not found: {filename}.glb")

# 방법 2: /api/models/ 경로에서 서빙 (권장)
@app.get("/api/models/{filename}.glb")
async def serve_glb_file_api(filename: str):
    """API 경로에서 GLB 파일 서빙 (3D 모델용)"""
    glb_path = os.path.join(frontend_dir, f"{filename}.glb")
    if os.path.exists(glb_path):
        return FileResponse(glb_path, media_type="model/gltf-binary")
    else:
        raise HTTPException(status_code=404, detail=f"GLB file not found: {filename}.glb")

# README.md 파일 서빙
@app.get("/README.md")
async def serve_readme():
    """README.md 파일 서빙"""
    readme_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "README.md")
    if os.path.exists(readme_path):
        return FileResponse(readme_path, media_type="text/markdown; charset=utf-8")
    else:
        raise HTTPException(status_code=404, detail="README.md not found")

# 버전 정보 API (README.md에서 자동 추출)
@app.get("/api/version")
async def get_version():
    """README.md에서 버전 정보 추출"""
    import re
    readme_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "README.md")
    try:
        with open(readme_path, 'r', encoding='utf-8') as f:
            content = f.read()
            # **버전**: v2.1.202601080520 형식에서 버전 추출
            match = re.search(r'\*\*버전\*\*:\s*v?([\d.]+)', content)
            if match:
                return {"version": match.group(1)}
            return {"version": "unknown"}
    except Exception as e:
        return {"version": "unknown", "error": str(e)}


# 데이터베이스 연결 설정 (환경 변수에서 로드)
DB_CONFIG = {
    'host': os.getenv('DB_HOST', 'localhost'),
    'user': os.getenv('DB_USER', 'iyrc'),
    'passwd': os.getenv('DB_PASSWORD', 'dodan1004'),
    'db': os.getenv('DB_NAME', 'minilms'),
    'charset': 'utf8',
    'port': int(os.getenv('DB_PORT', '3306'))
}

def get_db_connection():
    """데이터베이스 연결"""
    return pymysql.connect(**DB_CONFIG)

def ensure_photo_urls_column(cursor, table_name: str):
    """photo_urls 컬럼이 없으면 추가"""
    try:
        cursor.execute(f"SHOW COLUMNS FROM {table_name} LIKE 'photo_urls'")
        if not cursor.fetchone():
            cursor.execute(f"ALTER TABLE {table_name} ADD COLUMN photo_urls TEXT")
    except:
        pass  # 이미 존재하거나 권한 문제

def ensure_career_path_column(cursor):
    """students 테이블에 career_path 컬럼이 없으면 추가하고 기본값 설정"""
    try:
        cursor.execute("SHOW COLUMNS FROM students LIKE 'career_path'")
        if not cursor.fetchone():
            # 컬럼 추가
            cursor.execute("ALTER TABLE students ADD COLUMN career_path VARCHAR(50) DEFAULT '4. 미정'")
            # 기존 데이터의 NULL 값을 '4. 미정'으로 업데이트
            cursor.execute("UPDATE students SET career_path = '4. 미정' WHERE career_path IS NULL")
    except Exception as e:
        pass  # 이미 존재하거나 권한 문제

def ensure_career_decision_column(cursor):
    """consultations 테이블에 career_decision 컬럼이 없으면 추가"""
    try:
        cursor.execute("SHOW COLUMNS FROM consultations LIKE 'career_decision'")
        if not cursor.fetchone():
            cursor.execute("ALTER TABLE consultations ADD COLUMN career_decision VARCHAR(50) DEFAULT NULL")
    except Exception as e:
        pass

def ensure_profile_photo_columns(cursor, table_name: str):
    """profile_photo와 attachments 컬럼이 없으면 추가"""
    try:
        # profile_photo 컬럼 확인 및 추가 (단일 프로필 사진)
        cursor.execute(f"SHOW COLUMNS FROM {table_name} LIKE 'profile_photo'")
        if not cursor.fetchone():
            cursor.execute(f"ALTER TABLE {table_name} ADD COLUMN profile_photo VARCHAR(500) DEFAULT NULL")

        # attachments 컬럼 확인 및 추가 (첨부 파일 배열, 최대 20개)
        cursor.execute(f"SHOW COLUMNS FROM {table_name} LIKE 'attachments'")
        if not cursor.fetchone():
            cursor.execute(f"ALTER TABLE {table_name} ADD COLUMN attachments TEXT DEFAULT NULL")
    except Exception as e:
        pass  # 이미 존재하거나 권한 문제

def ensure_menu_permissions_column(cursor):
    """instructor_codes 테이블에 menu_permissions 컬럼이 없으면 추가"""
    try:
        cursor.execute("SHOW COLUMNS FROM instructor_codes LIKE 'menu_permissions'")
        if not cursor.fetchone():
            cursor.execute("ALTER TABLE instructor_codes ADD COLUMN menu_permissions TEXT DEFAULT NULL")
    except Exception as e:
        pass

# FTP 설정 (환경 변수에서 로드)
FTP_CONFIG = {
    'host': os.getenv('FTP_HOST', 'bitnmeta2.synology.me'),
    'port': int(os.getenv('FTP_PORT', '2121')),
    'user': os.getenv('FTP_USER', 'ha'),
    'passwd': os.getenv('FTP_PASSWORD', 'dodan1004~')
}

# FTP 경로 설정
FTP_PATHS = {
    'guidance': '/home/minilms_ftp/minilms/guidance',  # 상담일지
    'train': '/home/minilms_ftp/minilms/train',        # 훈련일지
    'student': '/home/minilms_ftp/minilms/student',    # 학생
    'teacher': '/home/minilms_ftp/minilms/teacher',    # 강사
    'team': '/home/minilms_ftp/minilms/team'           # 팀(프로젝트)
}

def create_thumbnail(file_data: bytes, filename: str) -> str:
    """
    이미지 썸네일 생성 및 로컬 저장
    
    Args:
        file_data: 원본 이미지 바이트 데이터
        filename: 파일명
    
    Returns:
        썸네일 파일명
    """
    try:
        # 이미지 열기
        image = Image.open(io.BytesIO(file_data))
        
        # EXIF 방향 정보 처리
        try:
            from PIL import ImageOps
            image = ImageOps.exif_transpose(image)
        except:
            pass
        
        # RGB로 변환 (PNG 투명도 처리)
        if image.mode in ('RGBA', 'LA', 'P'):
            background = Image.new('RGB', image.size, (255, 255, 255))
            if image.mode == 'P':
                image = image.convert('RGBA')
            background.paste(image, mask=image.split()[-1] if image.mode == 'RGBA' else None)
            image = background
        elif image.mode != 'RGB':
            image = image.convert('RGB')
        
        # 썸네일 크기 (최대 200x200)
        image.thumbnail((200, 200), Image.Resampling.LANCZOS)
        
        # 썸네일 저장 경로 (크로스 플랫폼 지원)
        thumb_filename = f"thumb_{filename}"
        backend_dir = os.path.dirname(os.path.abspath(__file__))
        thumbnails_dir = os.path.join(backend_dir, 'thumbnails')
        os.makedirs(thumbnails_dir, exist_ok=True)
        thumb_path = os.path.join(thumbnails_dir, thumb_filename)
        
        # 썸네일 저장
        image.save(thumb_path, 'JPEG', quality=85, optimize=True)
        
        return thumb_filename
        
    except Exception as e:
        print(f"썸네일 생성 실패: {str(e)}")
        return None

def upload_to_ftp(file_data: bytes, filename: str, category: str) -> str:
    """
    FTP 서버에 파일 업로드 및 썸네일 생성 (기존 함수 - base64 업로드용)
    
    Args:
        file_data: 파일 바이트 데이터
        filename: 저장할 파일명 (확장자 포함)
        category: 카테고리 (guidance, train, student, teacher)
    
    Returns:
        업로드된 파일의 FTP URL
    """
    try:
        # 썸네일 생성 (백그라운드에서 실행, 실패해도 업로드는 계속)
        try:
            create_thumbnail(file_data, filename)
        except Exception as e:
            print(f"썸네일 생성 중 오류 (무시): {str(e)}")
        
        # FTP 연결
        ftp = FTP()
        ftp.encoding = 'utf-8'  # 한글 파일명 지원
        ftp.connect(FTP_CONFIG['host'], FTP_CONFIG['port'])
        ftp.login(FTP_CONFIG['user'], FTP_CONFIG['passwd'])
        
        # 경로 이동
        target_path = FTP_PATHS.get(category)
        if not target_path:
            raise ValueError(f"Invalid category: {category}")
        
        try:
            ftp.cwd(target_path)
        except:
            # 경로가 없으면 생성
            path_parts = target_path.split('/')
            current_path = ''
            for part in path_parts:
                if not part:
                    continue
                current_path += '/' + part
                try:
                    ftp.cwd(current_path)
                except:
                    ftp.mkd(current_path)
                    ftp.cwd(current_path)
        
        # 파일 업로드
        ftp.storbinary(f'STOR {filename}', io.BytesIO(file_data))
        
        # URL 생성 (FTP URL)
        file_url = f"ftp://{FTP_CONFIG['host']}:{FTP_CONFIG['port']}{target_path}/{filename}"
        
        ftp.quit()
        return file_url
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"FTP 업로드 실패: {str(e)}")


async def upload_stream_to_ftp(file: UploadFile, filename: str, category: str) -> str:
    """
    FTP 서버에 파일 스트리밍 업로드 (메모리 절약형 - 대용량 파일용)
    
    Args:
        file: FastAPI UploadFile 객체
        filename: 저장할 파일명 (확장자 포함)
        category: 카테고리 (guidance, train, student, teacher)
    
    Returns:
        업로드된 파일의 FTP URL
    """
    try:
        # FTP 연결
        ftp = FTP()
        ftp.encoding = 'utf-8'  # 한글 파일명 지원
        ftp.connect(FTP_CONFIG['host'], FTP_CONFIG['port'])
        ftp.login(FTP_CONFIG['user'], FTP_CONFIG['passwd'])
        
        # 경로 이동
        target_path = FTP_PATHS.get(category)
        if not target_path:
            raise ValueError(f"Invalid category: {category}")
        
        try:
            ftp.cwd(target_path)
        except:
            # 경로가 없으면 생성
            path_parts = target_path.split('/')
            current_path = ''
            for part in path_parts:
                if not part:
                    continue
                current_path += '/' + part
                try:
                    ftp.cwd(current_path)
                except:
                    ftp.mkd(current_path)
                    ftp.cwd(current_path)
        
        # 파일 스트리밍 업로드 (1MB 청크 단위로 읽어서 전송)
        # 메모리에 전체 파일을 올리지 않음
        await file.seek(0)  # 파일 포인터를 처음으로
        ftp.storbinary(f'STOR {filename}', file.file, blocksize=1024*1024)
        
        # URL 생성 (FTP URL)
        file_url = f"ftp://{FTP_CONFIG['host']}:{FTP_CONFIG['port']}{target_path}/{filename}"
        
        ftp.quit()
        
        # 썸네일 생성 (백그라운드에서, 실패해도 무시)
        # 이미지 파일인 경우에만 썸네일 생성 시도
        if filename.lower().endswith(('.jpg', '.jpeg', '.png', '.gif', '.bmp', '.webp')):
            try:
                # 썸네일용으로 파일 일부만 읽기 (처음 10MB만)
                await file.seek(0)
                thumbnail_data = await file.read(10 * 1024 * 1024)
                if thumbnail_data:
                    create_thumbnail(thumbnail_data, filename)
            except Exception as e:
                print(f"썸네일 생성 실패: {str(e)}")
        
        return file_url
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"FTP 스트리밍 업로드 실패: {str(e)}")

# ==================== 학생 관리 API ====================

@app.get("/api/students")
async def get_students(
    course_code: Optional[str] = None,
    search: Optional[str] = None
):
    """학생 목록 조회"""
    conn = get_db_connection()
    try:
        cursor = conn.cursor(pymysql.cursors.DictCursor)
        
        # career_path 컬럼 확인 및 추가
        ensure_career_path_column(cursor)
        
        # profile_photo, attachments 컬럼 확인 및 추가
        ensure_profile_photo_columns(cursor, 'students')
        
        query = "SELECT * FROM students WHERE 1=1"
        params = []
        
        if course_code:
            query += " AND course_code = %s"
            params.append(course_code)
        
        if search:
            query += " AND (name LIKE %s OR code LIKE %s OR phone LIKE %s)"
            search_pattern = f"%{search}%"
            params.extend([search_pattern, search_pattern, search_pattern])
        
        query += " ORDER BY code"
        
        cursor.execute(query, params)
        students = cursor.fetchall()
        
        # datetime 객체를 문자열로 변환
        for student in students:
            for key, value in student.items():
                if isinstance(value, (datetime, date)):
                    student[key] = value.isoformat()
                elif isinstance(value, bytes):
                    student[key] = None  # thumbnail은 제외
        
        return students
    finally:
        conn.close()

@app.get("/api/students/{student_id}")
async def get_student(student_id: int):
    """특정 학생 조회 (과정 정보 포함)"""
    conn = get_db_connection()
    try:
        cursor = conn.cursor(pymysql.cursors.DictCursor)
        
        # profile_photo, attachments 컬럼 확인 및 추가
        ensure_profile_photo_columns(cursor, 'students')
        
        # 학생 정보와 과정 정보를 JOIN하여 가져오기
        query = """
            SELECT s.*, c.name as course_name
            FROM students s
            LEFT JOIN courses c ON s.course_code = c.code
            WHERE s.id = %s
        """
        cursor.execute(query, (student_id,))
        student = cursor.fetchone()
        
        if not student:
            raise HTTPException(status_code=404, detail="학생을 찾을 수 없습니다")
        
        # datetime 변환
        for key, value in student.items():
            if isinstance(value, (datetime, date)):
                student[key] = value.isoformat()
            elif isinstance(value, bytes):
                student[key] = None
        
        return student
    finally:
        conn.close()

@app.post("/api/students")
async def create_student(data: dict):
    """학생 생성 (프로필/첨부 파일 분리)"""
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        
        # profile_photo와 attachments 컬럼이 없으면 자동 생성
        ensure_profile_photo_columns(cursor, 'students')
        
        # 자동으로 학생 코드 생성
        cursor.execute("SELECT MAX(CAST(SUBSTRING(code, 2) AS UNSIGNED)) as max_code FROM students WHERE code LIKE 'S%'")
        result = cursor.fetchone()
        next_num = (result[0] or 0) + 1
        code = data.get('code', f"S{next_num:03d}")
        
        # 필수 필드 검증
        name = data.get('name')
        if not name:
            raise HTTPException(status_code=400, detail="이름은 필수입니다")
        
        # phone 필드 기본값 처리 (NULL 방지)
        phone = data.get('phone', '')
        if not phone:
            phone = ''
        
        # course_code 유효성 검증
        course_code = data.get('course_code')
        if course_code and course_code.strip():
            cursor.execute("SELECT COUNT(*) FROM courses WHERE code = %s", (course_code.strip(),))
            if cursor.fetchone()[0] == 0:
                course_code = None  # 유효하지 않은 과정 코드는 NULL로
        else:
            course_code = None  # 빈 문자열도 NULL로 처리
        
        query = """
            INSERT INTO students 
            (code, name, birth_date, gender, phone, email, address, interests, education, 
             introduction, campus, course_code, notes, profile_photo, attachments, career_path)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """
        
        cursor.execute(query, (
            code,
            name,
            data.get('birth_date'),
            data.get('gender'),
            phone,
            data.get('email'),
            data.get('address'),
            data.get('interests'),
            data.get('education'),
            data.get('introduction'),
            data.get('campus'),
            course_code,
            data.get('notes'),
            data.get('profile_photo'),
            data.get('attachments'),
            data.get('career_path', '4. 미정')
        ))
        
        conn.commit()
        return {"id": cursor.lastrowid, "code": code}
    finally:
        conn.close()

@app.put("/api/students/{student_id}")
async def update_student(student_id: int, data: dict):
    """학생 수정 (JSON 데이터 지원 - 프로필/첨부 파일 분리)"""
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        
        # 새로운 컬럼 자동 생성 (profile_photo, attachments)
        ensure_profile_photo_columns(cursor, 'students')
        
        # 데이터 추출
        name = data.get('name')
        if not name:
            raise HTTPException(status_code=400, detail="이름은 필수입니다")
        
        birth_date = data.get('birth_date')
        gender = data.get('gender')
        phone = data.get('phone')
        email = data.get('email')
        address = data.get('address')
        interests = data.get('interests')
        education = data.get('education')
        introduction = data.get('introduction')
        campus = data.get('campus')
        course_code = data.get('course_code')
        notes = data.get('notes')
        career_path = data.get('career_path', '4. 미정')
        
        # 프로필 사진 (단일 URL)
        profile_photo = data.get('profile_photo')
        
        # 첨부 파일 (JSON 배열, 최대 20개)
        attachments = data.get('attachments')
        if attachments:
            import json
            try:
                attachment_list = json.loads(attachments) if isinstance(attachments, str) else attachments
                if len(attachment_list) > 20:
                    raise HTTPException(status_code=400, detail="첨부 파일은 최대 20개까지 가능합니다")
                attachments = json.dumps(attachment_list)
            except json.JSONDecodeError:
                attachments = None
        
        # type 컬럼 확인 및 기본값 처리
        cursor.execute("SHOW COLUMNS FROM students LIKE 'type'")
        has_type_column = cursor.fetchone() is not None
        
        if has_type_column:
            # type 컬럼이 있으면 포함
            query = """
                UPDATE students 
                SET name = %s, birth_date = %s, gender = %s, phone = %s, email = %s,
                    address = %s, interests = %s, education = %s, introduction = %s,
                    campus = %s, course_code = %s, notes = %s, career_path = %s, 
                    profile_photo = %s, attachments = %s,
                    type = %s, updated_at = NOW()
                WHERE id = %s
            """
            cursor.execute(query, (
                name, birth_date, gender, phone, email,
                address, interests, education, introduction,
                campus, course_code, notes, career_path,
                profile_photo, attachments,
                '1',  # 기본값: 일반 학생
                student_id
            ))
        else:
            # type 컬럼이 없으면 제외
            query = """
                UPDATE students 
                SET name = %s, birth_date = %s, gender = %s, phone = %s, email = %s,
                    address = %s, interests = %s, education = %s, introduction = %s,
                    campus = %s, course_code = %s, notes = %s, career_path = %s,
                    profile_photo = %s, attachments = %s, updated_at = NOW()
                WHERE id = %s
            """
            cursor.execute(query, (
                name, birth_date, gender, phone, email,
                address, interests, education, introduction,
                campus, course_code, notes, career_path,
                profile_photo, attachments,
                student_id
            ))
        
        conn.commit()
        return {"id": student_id}
    finally:
        conn.close()

@app.delete("/api/students/{student_id}")
async def delete_student(student_id: int):
    """학생 삭제"""
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM students WHERE id = %s", (student_id,))
        conn.commit()
        return {"message": "학생이 삭제되었습니다"}
    finally:
        conn.close()

@app.post("/api/students/upload-excel")
async def upload_excel(file: UploadFile = File(...)):
    """Excel 파일로 학생 일괄 등록"""
    if not file.filename.endswith(('.xlsx', '.xls')):
        raise HTTPException(status_code=400, detail="Excel 파일만 업로드 가능합니다")
    
    try:
        # Excel 파일 읽기
        contents = await file.read()
        df = pd.read_excel(io.BytesIO(contents))
        
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # 현재 최대 학생 코드 조회
        cursor.execute("SELECT MAX(CAST(SUBSTRING(code, 2) AS UNSIGNED)) as max_code FROM students WHERE code LIKE 'S%'")
        result = cursor.fetchone()
        next_num = (result[0] or 0) + 1
        
        success_count = 0
        error_list = []
        
        for idx, row in df.iterrows():
            try:
                code = f"S{next_num:03d}"
                
                # 컬럼명 매핑
                name = row.get('이름', '')
                birth_date = str(row.get('생년월일(78.01.12)', ''))
                gender = row.get('성별\n(선택)', '')
                phone = str(row.get('휴대폰번호', ''))
                email = row.get('이메일', '')
                address = row.get('주소', '')
                interests = row.get('관심 있는 분야(2개)', '')
                education = row.get('최종 학교/학년(졸업)', '')
                introduction = row.get('자기소개 (200자 내외)', '')
                campus = row.get('지원하고자 하는 캠퍼스를 선택하세요', '')
                
                query = """
                    INSERT INTO students 
                    (code, name, birth_date, gender, phone, email, address, interests, education, introduction, campus)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """
                
                cursor.execute(query, (
                    code, name, birth_date, gender, phone, email, 
                    address, interests, education, introduction, campus
                ))
                
                next_num += 1
                success_count += 1
                
            except Exception as e:
                error_list.append(f"행 {idx+2}: {str(e)}")
        
        conn.commit()
        conn.close()
        
        return {
            "success": True,
            "message": f"{success_count}명의 학생이 등록되었습니다",
            "success_count": success_count,
            "errors": error_list
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"파일 처리 중 오류: {str(e)}")

@app.get("/api/template/students")
async def download_template():
    """학생 등록 템플릿 다운로드"""
    template_path = "/home/user/webapp/student_template.xlsx"
    if os.path.exists(template_path):
        return FileResponse(
            template_path,
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            filename="학생등록양식.xlsx"
        )
    raise HTTPException(status_code=404, detail="템플릿 파일을 찾을 수 없습니다")

# ==================== 과목 관리 API ====================

@app.get("/api/subjects")
async def get_subjects():
    """과목 목록 조회"""
    conn = get_db_connection()
    try:
        cursor = conn.cursor(pymysql.cursors.DictCursor)
        cursor.execute("""
            SELECT s.*, i.name as instructor_name
            FROM subjects s
            LEFT JOIN instructors i ON s.main_instructor = i.code
            ORDER BY s.code
        """)
        subjects = cursor.fetchall()
        
        for subject in subjects:
            for key, value in subject.items():
                if isinstance(value, (datetime, date)):
                    subject[key] = value.isoformat()
        
        return subjects
    finally:
        conn.close()

@app.get("/api/subjects/{subject_code}")
async def get_subject(subject_code: str):
    """특정 과목 조회"""
    conn = get_db_connection()
    try:
        cursor = conn.cursor(pymysql.cursors.DictCursor)
        cursor.execute("""
            SELECT s.*, i.name as instructor_name
            FROM subjects s
            LEFT JOIN instructors i ON s.main_instructor = i.code
            WHERE s.code = %s
        """, (subject_code,))
        subject = cursor.fetchone()
        
        if not subject:
            raise HTTPException(status_code=404, detail="과목을 찾을 수 없습니다")
        
        for key, value in subject.items():
            if isinstance(value, (datetime, date)):
                subject[key] = value.isoformat()
        
        return subject
    finally:
        conn.close()

@app.post("/api/subjects")
async def create_subject(data: dict):
    """과목 생성"""
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        
        query = """
            INSERT INTO subjects 
            (code, name, main_instructor, day_of_week, is_biweekly, week_offset, hours, description,
             sub_subject_1, sub_hours_1, sub_subject_2, sub_hours_2, sub_subject_3, sub_hours_3,
             sub_subject_4, sub_hours_4, sub_subject_5, sub_hours_5)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """
        
        cursor.execute(query, (
            data.get('code'),
            data.get('name'),
            data.get('main_instructor'),
            data.get('day_of_week', 0),
            data.get('is_biweekly', 0),
            data.get('week_offset', 0),
            data.get('hours', 0),
            data.get('description', ''),
            data.get('sub_subject_1', ''),
            data.get('sub_hours_1', 0),
            data.get('sub_subject_2', ''),
            data.get('sub_hours_2', 0),
            data.get('sub_subject_3', ''),
            data.get('sub_hours_3', 0),
            data.get('sub_subject_4', ''),
            data.get('sub_hours_4', 0),
            data.get('sub_subject_5', ''),
            data.get('sub_hours_5', 0)
        ))
        
        conn.commit()
        return {"code": data.get('code')}
    except pymysql.err.OperationalError as e:
        raise HTTPException(status_code=500, detail=f"데이터베이스 오류: {str(e)}")
    finally:
        conn.close()

@app.put("/api/subjects/{subject_code}")
async def update_subject(subject_code: str, data: dict):
    """과목 수정"""
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        
        # 업데이트할 필드 동적 구성
        update_fields = []
        update_values = []
        
        if 'name' in data:
            update_fields.append("name = %s")
            update_values.append(data['name'])
        
        if 'main_instructor' in data:
            update_fields.append("main_instructor = %s")
            update_values.append(data['main_instructor'])
        
        if 'assistant_instructor' in data:
            update_fields.append("assistant_instructor = %s")
            update_values.append(data['assistant_instructor'])
        
        if 'reserve_instructor' in data:
            update_fields.append("reserve_instructor = %s")
            update_values.append(data['reserve_instructor'])
        
        if 'instructor_code' in data:
            update_fields.append("instructor_code = %s")
            update_values.append(data['instructor_code'])
        
        if 'day_of_week' in data:
            update_fields.append("day_of_week = %s")
            update_values.append(data['day_of_week'])
        
        if 'is_biweekly' in data:
            update_fields.append("is_biweekly = %s")
            update_values.append(data['is_biweekly'])
        
        if 'week_offset' in data:
            update_fields.append("week_offset = %s")
            update_values.append(data['week_offset'])
        
        if 'hours' in data:
            update_fields.append("hours = %s")
            update_values.append(data['hours'])
        
        if 'description' in data:
            update_fields.append("description = %s")
            update_values.append(data['description'])
        
        # 세부 과목들
        for i in range(1, 6):
            if f'sub_subject_{i}' in data:
                update_fields.append(f"sub_subject_{i} = %s")
                update_values.append(data[f'sub_subject_{i}'])
            if f'sub_hours_{i}' in data:
                update_fields.append(f"sub_hours_{i} = %s")
                update_values.append(data[f'sub_hours_{i}'])
        
        if not update_fields:
            return {"code": subject_code, "message": "No fields to update"}
        
        query = f"UPDATE subjects SET {', '.join(update_fields)} WHERE code = %s"
        update_values.append(subject_code)
        
        cursor.execute(query, tuple(update_values))
        conn.commit()
        return {"code": subject_code}
    except Exception as e:
        import traceback
        print(f"교과목 수정 오류: {str(e)}")
        print(traceback.format_exc())
        raise HTTPException(status_code=500, detail=f"교과목 수정 실패: {str(e)}")
    finally:
        conn.close()

@app.delete("/api/subjects/{subject_code}")
async def delete_subject(subject_code: str):
    """과목 삭제"""
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM subjects WHERE code = %s", (subject_code,))
        conn.commit()
        return {"message": "과목이 삭제되었습니다"}
    finally:
        conn.close()

@app.get("/api/instructors/{instructor_code}/subjects")
async def get_instructor_subjects(instructor_code: str):
    """강사의 담당 교과목 조회"""
    conn = get_db_connection()
    try:
        cursor = conn.cursor(pymysql.cursors.DictCursor)
        cursor.execute("""
            SELECT code, name, description, hours
            FROM subjects
            WHERE main_instructor = %s
            ORDER BY name
        """, (instructor_code,))
        subjects = cursor.fetchall()
        return subjects
    finally:
        conn.close()

@app.post("/api/courses/{course_code}/subjects")
async def save_course_subjects(course_code: str, data: dict):
    """과정-교과목 관계 저장"""
    subject_codes = data.get('subject_codes', [])
    
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        
        # 기존 과정-교과목 관계 삭제
        cursor.execute("DELETE FROM course_subjects WHERE course_code = %s", (course_code,))
        
        # 새로운 관계 추가
        for idx, subject_code in enumerate(subject_codes, start=1):
            cursor.execute("""
                INSERT INTO course_subjects (course_code, subject_code, display_order)
                VALUES (%s, %s, %s)
            """, (course_code, subject_code, idx))
        
        conn.commit()
        return {
            "message": f"{len(subject_codes)}개의 교과목이 저장되었습니다",
            "course_code": course_code,
            "subject_count": len(subject_codes)
        }
    except Exception as e:
        conn.rollback()
        raise HTTPException(status_code=500, detail=f"교과목 저장 실패: {str(e)}")
    finally:
        conn.close()

# ==================== 유틸리티 함수 ====================

def convert_datetime(obj):
    """datetime 객체를 문자열로 변환 + internship → workship 컬럼명 매핑"""
    from datetime import timedelta
    
    # DB 컬럼명 → 프론트엔드 필드명 매핑
    if 'internship_hours' in obj:
        obj['workship_hours'] = obj.pop('internship_hours')
    if 'internship_end_date' in obj:
        obj['workship_end_date'] = obj.pop('internship_end_date')
    
    for key, value in obj.items():
        if isinstance(value, (datetime, date)):
            obj[key] = value.isoformat()
        elif isinstance(value, timedelta):
            # timedelta를 HH:MM:SS 형식으로 변환
            total_seconds = int(value.total_seconds())
            hours = total_seconds // 3600
            minutes = (total_seconds % 3600) // 60
            seconds = total_seconds % 60
            obj[key] = f"{hours:02d}:{minutes:02d}:{seconds:02d}"
        elif isinstance(value, bytes):
            obj[key] = None
    return obj

# ==================== 강사코드 관리 API ====================

@app.get("/api/instructor-codes")
async def get_instructor_codes():
    """강사코드 목록 조회"""
    conn = get_db_connection()
    try:
        cursor = conn.cursor(pymysql.cursors.DictCursor)
        
        # menu_permissions 컬럼 확인 및 추가
        ensure_menu_permissions_column(cursor)
        conn.commit()
        
        # permissions 컬럼 존재 여부 확인 및 추가
        cursor.execute("SHOW COLUMNS FROM instructor_codes LIKE 'permissions'")
        if not cursor.fetchone():
            cursor.execute("ALTER TABLE instructor_codes ADD COLUMN permissions TEXT DEFAULT NULL")
            conn.commit()

        # "0. 관리자" 타입이 없으면 추가
        cursor.execute("SELECT * FROM instructor_codes WHERE code = '0'")
        if not cursor.fetchone():
            cursor.execute("""
                INSERT INTO instructor_codes (code, name, type, permissions)
                VALUES ('0', '관리자', '0', NULL)
            """)
            conn.commit()
        
        cursor.execute("SELECT * FROM instructor_codes ORDER BY code")
        codes = cursor.fetchall()
        
        # permissions와 menu_permissions를 JSON으로 파싱
        import json
        for code in codes:
            if code.get('permissions'):
                try:
                    code['permissions'] = json.loads(code['permissions'])
                except:
                    code['permissions'] = None
            if code.get('menu_permissions'):
                try:
                    code['menu_permissions'] = json.loads(code['menu_permissions'])
                except:
                    code['menu_permissions'] = None
        
        return [convert_datetime(code) for code in codes]
    finally:
        conn.close()

@app.post("/api/instructor-codes")
async def create_instructor_code(data: dict):
    """강사코드 생성"""
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        
        # menu_permissions 컬럼 확인 및 추가
        ensure_menu_permissions_column(cursor)
        conn.commit()
        
        # default_screen 컬럼이 없으면 추가
        cursor.execute("SHOW COLUMNS FROM instructor_codes LIKE 'default_screen'")
        if not cursor.fetchone():
            cursor.execute("ALTER TABLE instructor_codes ADD COLUMN default_screen VARCHAR(50) DEFAULT NULL")
            conn.commit()

        import json
        permissions_json = json.dumps(data.get('permissions', {})) if data.get('permissions') else None
        menu_permissions_json = json.dumps(data.get('menu_permissions', [])) if data.get('menu_permissions') else None
        default_screen = data.get('default_screen')
        
        query = """
            INSERT INTO instructor_codes (code, name, type, permissions, menu_permissions, default_screen)
            VALUES (%s, %s, %s, %s, %s, %s)
        """
        cursor.execute(query, (data['code'], data['name'], data['type'], permissions_json, menu_permissions_json, default_screen))
        conn.commit()
        return {"code": data['code']}
    finally:
        conn.close()

@app.put("/api/instructor-codes/{code}")
async def update_instructor_code(code: str, data: dict):
    """강사코드 수정 (권한 설정 포함)"""
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        
        # menu_permissions 컬럼 확인 및 추가
        ensure_menu_permissions_column(cursor)
        conn.commit()
        
        # default_screen 컬럼이 없으면 추가
        cursor.execute("SHOW COLUMNS FROM instructor_codes LIKE 'default_screen'")
        if not cursor.fetchone():
            cursor.execute("ALTER TABLE instructor_codes ADD COLUMN default_screen VARCHAR(50) DEFAULT NULL")
            conn.commit()

        import json
        permissions_json = json.dumps(data.get('permissions', {})) if data.get('permissions') else None
        menu_permissions_json = json.dumps(data.get('menu_permissions', [])) if data.get('menu_permissions') else None
        default_screen = data.get('default_screen')
        
        query = """
            UPDATE instructor_codes
            SET name = %s, type = %s, permissions = %s, menu_permissions = %s, default_screen = %s
            WHERE code = %s
        """
        cursor.execute(query, (data['name'], data['type'], permissions_json, menu_permissions_json, default_screen, code))
        conn.commit()
        return {"code": code}
    finally:
        conn.close()

@app.delete("/api/instructor-codes/{code}")
async def delete_instructor_code(code: str):
    """강사코드 삭제"""
    conn = get_db_connection()
    try:
        cursor = conn.cursor(pymysql.cursors.DictCursor)
        
        # 사용 중인지 확인
        cursor.execute("SELECT COUNT(*) as cnt FROM instructors WHERE instructor_type = %s", (code,))
        result = cursor.fetchone()
        if result and result['cnt'] > 0:
            raise HTTPException(status_code=400, detail=f"이 강사코드는 {result['cnt']}명의 강사가 사용 중입니다. 먼저 강사의 타입을 변경하세요.")
        
        cursor.execute("DELETE FROM instructor_codes WHERE code = %s", (code,))
        if cursor.rowcount == 0:
            raise HTTPException(status_code=404, detail="강사코드를 찾을 수 없습니다")
        
        conn.commit()
        return {"message": "강사코드가 삭제되었습니다"}
    except HTTPException:
        raise
    except Exception as e:
        conn.rollback()
        raise HTTPException(status_code=500, detail=f"삭제 실패: {str(e)}")
    finally:
        conn.close()

@app.post("/api/admin/migrate-admin-code")
async def migrate_admin_code():
    """관리자 코드를 0에서 IC-999로 마이그레이션"""
    conn = get_db_connection()
    try:
        cursor = conn.cursor(pymysql.cursors.DictCursor)
        
        # 0. type 컬럼 길이 확인 및 확장
        cursor.execute("SHOW COLUMNS FROM instructor_codes LIKE 'type'")
        type_column = cursor.fetchone()
        if type_column:
            # VARCHAR(10) 또는 더 작은 경우 VARCHAR(50)으로 확장
            cursor.execute("ALTER TABLE instructor_codes MODIFY COLUMN type VARCHAR(50)")
            conn.commit()
        
        # 1. code='0' 확인
        cursor.execute("SELECT * FROM instructor_codes WHERE code = '0'")
        old_admin = cursor.fetchone()
        
        if not old_admin:
            # code='0'이 없으면 IC-999가 이미 존재하는지 확인
            cursor.execute("SELECT * FROM instructor_codes WHERE code = 'IC-999'")
            existing_ic999 = cursor.fetchone()
            if existing_ic999:
                return {
                    "success": True,
                    "message": "이미 마이그레이션되었습니다",
                    "admin_code": existing_ic999,
                    "instructor_count": 0
                }
            else:
                raise HTTPException(status_code=404, detail="관리자 코드 '0'을 찾을 수 없습니다")
        
        # 2. IC-999가 이미 있는지 확인하고 삭제
        cursor.execute("SELECT * FROM instructor_codes WHERE code = 'IC-999'")
        existing = cursor.fetchone()
        if existing:
            cursor.execute("DELETE FROM instructor_codes WHERE code = 'IC-999'")
            conn.commit()
        
        # 3. code='0'의 모든 데이터 가져오기
        old_data = {
            'name': old_admin['name'],
            'type': '0. 관리자',
            'permissions': old_admin.get('permissions'),
            'default_screen': old_admin.get('default_screen'),
            'created_at': old_admin.get('created_at'),
            'updated_at': old_admin.get('updated_at')
        }
        
        # 4. code='0' 삭제
        cursor.execute("DELETE FROM instructor_codes WHERE code = '0'")
        conn.commit()
        
        # 5. IC-999로 새로 삽입
        import json as json_module
        permissions_json = json_module.dumps(old_data['permissions']) if old_data['permissions'] else None
        
        cursor.execute("""
            INSERT INTO instructor_codes (code, name, type, permissions, default_screen, created_at, updated_at)
            VALUES (%s, %s, %s, %s, %s, %s, NOW())
        """, ('IC-999', old_data['name'], old_data['type'], permissions_json, old_data['default_screen'], old_data['created_at']))
        
        # 6. instructors 테이블의 instructor_type도 업데이트
        cursor.execute("""
            UPDATE instructors
            SET instructor_type = 'IC-999'
            WHERE instructor_type = '0'
        """)
        
        conn.commit()
        
        # 7. 결과 확인
        cursor.execute("SELECT * FROM instructor_codes WHERE code = 'IC-999'")
        new_admin = cursor.fetchone()
        
        cursor.execute("SELECT COUNT(*) as cnt FROM instructors WHERE instructor_type = 'IC-999'")
        instructor_count = cursor.fetchone()
        
        return {
            "success": True,
            "message": "관리자 코드가 성공적으로 마이그레이션되었습니다",
            "admin_code": new_admin,
            "instructor_count": instructor_count['cnt']
        }
    except HTTPException:
        raise
    except Exception as e:
        conn.rollback()
        raise HTTPException(status_code=500, detail=f"마이그레이션 실패: {str(e)}")
    finally:
        conn.close()

# ==================== 강사 관리 API ====================

@app.get("/api/instructors")
async def get_instructors(search: Optional[str] = None):
    """강사 목록 조회 (검색 기능 포함)"""
    conn = get_db_connection()
    try:
        cursor = conn.cursor(pymysql.cursors.DictCursor)
        
        # password 컬럼 존재 여부 확인
        cursor.execute("SHOW COLUMNS FROM instructors LIKE 'password'")
        has_password = cursor.fetchone() is not None
        
        # profile_photo와 attachments 컬럼 자동 생성
        ensure_profile_photo_columns(cursor, 'instructors')
        
        if has_password:
            query = """
                SELECT i.code, TRIM(i.name) as name, i.phone, i.major, i.instructor_type, 
                       i.email, i.created_at, i.updated_at, i.profile_photo, i.attachments, i.password,
                       ic.name as instructor_type_name, ic.type as instructor_type_type
                FROM instructors i
                LEFT JOIN instructor_codes ic ON i.instructor_type = ic.code
                WHERE 1=1
            """
        else:
            query = """
                SELECT i.code, TRIM(i.name) as name, i.phone, i.major, i.instructor_type, 
                       i.email, i.created_at, i.updated_at, i.profile_photo, i.attachments,
                       ic.name as instructor_type_name, ic.type as instructor_type_type
                FROM instructors i
                LEFT JOIN instructor_codes ic ON i.instructor_type = ic.code
                WHERE 1=1
            """
        params = []
        
        if search:
            query += " AND (i.name LIKE %s OR i.code LIKE %s OR i.phone LIKE %s)"
            search_pattern = f"%{search}%"
            params.extend([search_pattern, search_pattern, search_pattern])
        
        query += " ORDER BY i.code"
        
        cursor.execute(query, params)
        instructors = cursor.fetchall()
        return [convert_datetime(inst) for inst in instructors]
    finally:
        conn.close()

@app.get("/api/instructors/{code}")
async def get_instructor(code: str):
    """특정 강사 조회"""
    conn = get_db_connection()
    try:
        cursor = conn.cursor(pymysql.cursors.DictCursor)
        cursor.execute("""
            SELECT i.*, ic.name as type_name
            FROM instructors i
            LEFT JOIN instructor_codes ic ON i.instructor_type = ic.code
            WHERE i.code = %s
        """, (code,))
        instructor = cursor.fetchone()
        if not instructor:
            raise HTTPException(status_code=404, detail="강사를 찾을 수 없습니다")
        return convert_datetime(instructor)
    finally:
        conn.close()

@app.post("/api/instructors")
async def create_instructor(data: dict):
    """강사 생성 (프로필/첨부 파일 분리)"""
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        
        # profile_photo와 attachments 컬럼이 없으면 자동 생성
        ensure_profile_photo_columns(cursor, 'instructors')
        
        query = """
            INSERT INTO instructors (code, name, phone, major, instructor_type, email, profile_photo, attachments)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        """
        cursor.execute(query, (
            data['code'], data['name'], data.get('phone'),
            data.get('major'), data.get('instructor_type'), data.get('email'),
            data.get('profile_photo'), data.get('attachments')
        ))
        conn.commit()
        return {"code": data['code']}
    finally:
        conn.close()

@app.put("/api/instructors/{code}")
async def update_instructor(code: str, data: dict):
    """강사 수정 (JSON 데이터 지원 - 프로필/첨부 파일 분리)"""
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        
        # 새로운 컬럼 자동 생성 (profile_photo, attachments)
        ensure_profile_photo_columns(cursor, 'instructors')
        
        # 데이터 추출
        name = data.get('name')
        if not name:
            raise HTTPException(status_code=400, detail="이름은 필수입니다")
        
        phone = data.get('phone')
        major = data.get('major')
        email = data.get('email')
        
        # 프로필 사진 (단일 URL)
        profile_photo = data.get('profile_photo')
        
        # 첨부 파일 (JSON 배열, 최대 20개)
        attachments = data.get('attachments')
        if attachments:
            import json
            try:
                attachment_list = json.loads(attachments) if isinstance(attachments, str) else attachments
                if len(attachment_list) > 20:
                    raise HTTPException(status_code=400, detail="첨부 파일은 최대 20개까지 가능합니다")
                attachments = json.dumps(attachment_list)
            except json.JSONDecodeError:
                attachments = None
        
        # instructor_type은 MyPage에서 변경하지 않음 (외래 키 제약 조건)
        query = """
            UPDATE instructors
            SET name = %s, phone = %s, major = %s, email = %s, 
                profile_photo = %s, attachments = %s
            WHERE code = %s
        """
        cursor.execute(query, (
            name, phone, major, email, profile_photo, attachments, code
        ))
        conn.commit()
        return {"code": code}
    finally:
        conn.close()

@app.delete("/api/instructors/{code}")
async def delete_instructor(code: str):
    """강사 삭제"""
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM instructors WHERE code = %s", (code,))
        conn.commit()
        return {"message": "강사가 삭제되었습니다"}
    finally:
        conn.close()

# ==================== 공휴일 관리 API ====================

@app.get("/api/holidays")
async def get_holidays(year: Optional[int] = None):
    """공휴일 목록 조회 (연도별 필터)"""
    conn = get_db_connection()
    try:
        cursor = conn.cursor(pymysql.cursors.DictCursor)
        
        if year:
            cursor.execute("""
                SELECT * FROM holidays
                WHERE YEAR(holiday_date) = %s
                ORDER BY holiday_date
            """, (year,))
        else:
            cursor.execute("SELECT * FROM holidays ORDER BY holiday_date")
        
        holidays = cursor.fetchall()
        return [convert_datetime(h) for h in holidays]
    finally:
        conn.close()

@app.post("/api/holidays")
async def create_holiday(data: dict):
    """공휴일 생성 (중복 시 조용히 무시)"""
    conn = get_db_connection()
    try:
        cursor = conn.cursor(pymysql.cursors.DictCursor)
        
        # 중복 체크: 같은 날짜에 같은 이름의 공휴일이 있는지 확인
        cursor.execute("""
            SELECT id FROM holidays 
            WHERE holiday_date = %s AND name = %s
        """, (data['holiday_date'], data['name']))
        existing = cursor.fetchone()
        
        if existing:
            # 이미 존재하는 경우 조용히 기존 ID 반환 (에러 없이)
            print(f"ℹ️  이미 등록된 공휴일: {data['holiday_date']} - {data['name']}")
            return {"id": existing['id'], "message": "이미 등록된 공휴일입니다"}
        
        # 새로 등록
        query = """
            INSERT INTO holidays (holiday_date, name, is_legal)
            VALUES (%s, %s, %s)
        """
        cursor.execute(query, (data['holiday_date'], data['name'], data.get('is_legal', 0)))
        conn.commit()
        return {"id": cursor.lastrowid, "message": "공휴일이 추가되었습니다"}
    finally:
        conn.close()

@app.put("/api/holidays/{holiday_id}")
async def update_holiday(holiday_id: int, data: dict):
    """공휴일 수정"""
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        query = """
            UPDATE holidays
            SET holiday_date = %s, name = %s, is_legal = %s
            WHERE id = %s
        """
        cursor.execute(query, (data['holiday_date'], data['name'], data.get('is_legal', 0), holiday_id))
        conn.commit()
        return {"id": holiday_id}
    finally:
        conn.close()

@app.delete("/api/holidays/{holiday_id}")
async def delete_holiday(holiday_id: int):
    """공휴일 삭제"""
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM holidays WHERE id = %s", (holiday_id,))
        conn.commit()
        return {"message": "공휴일이 삭제되었습니다"}
    finally:
        conn.close()

@app.post("/api/holidays/auto-add/{year}")
async def auto_add_holidays(year: int):
    """법정공휴일 자동 추가"""
    from datetime import datetime, timedelta
    import korean_lunar_calendar
    
    conn = get_db_connection()
    try:
        cursor = conn.cursor(pymysql.cursors.DictCursor)
        
        # 법정공휴일 정의 (양력)
        solar_holidays = [
            (1, 1, "신정"),
            (3, 1, "삼일절"),
            (5, 5, "어린이날"),
            (6, 6, "현충일"),
            (8, 15, "광복절"),
            (10, 3, "개천절"),
            (10, 9, "한글날"),
            (12, 25, "성탄절"),
        ]
        
        # 음력 공휴일 (설날, 추석, 부처님오신날)
        lunar_holidays = [
            # 설날: 음력 12/30, 1/1, 1/2
            ((12, 30), "설날 연휴"),
            ((1, 1), "설날"),
            ((1, 2), "설날 연휴"),
            # 부처님오신날: 음력 4/8
            ((4, 8), "부처님오신날"),
            # 추석: 음력 8/14, 8/15, 8/16
            ((8, 14), "추석 연휴"),
            ((8, 15), "추석"),
            ((8, 16), "추석 연휴"),
        ]
        
        added = 0
        skipped = 0
        
        # 양력 공휴일 추가
        for month, day, name in solar_holidays:
            holiday_date = f"{year}-{month:02d}-{day:02d}"
            
            # 중복 체크
            cursor.execute("""
                SELECT id FROM holidays 
                WHERE holiday_date = %s AND name = %s
            """, (holiday_date, name))
            
            if cursor.fetchone():
                skipped += 1
                print(f"ℹ️  이미 등록됨: {holiday_date} - {name}")
            else:
                cursor.execute("""
                    INSERT INTO holidays (holiday_date, name, is_legal)
                    VALUES (%s, %s, 1)
                """, (holiday_date, name))
                added += 1
                print(f"[OK] 추가됨: {holiday_date} - {name}")
        
        # 음력 공휴일 추가
        try:
            for (lunar_month, lunar_day), name in lunar_holidays:
                # 음력을 양력으로 변환
                calendar = korean_lunar_calendar.KoreanLunarCalendar()
                
                # 설날 전날(음력 12/30)의 경우 전년도 기준
                if lunar_month == 12 and lunar_day == 30:
                    calendar.setLunarDate(year - 1, lunar_month, lunar_day, False)
                else:
                    calendar.setLunarDate(year, lunar_month, lunar_day, False)
                
                solar_date = calendar.SolarIsoFormat()
                
                # 중복 체크
                cursor.execute("""
                    SELECT id FROM holidays 
                    WHERE holiday_date = %s AND name = %s
                """, (solar_date, name))
                
                if cursor.fetchone():
                    skipped += 1
                    print(f"ℹ️  이미 등록됨: {solar_date} - {name} (음력)")
                else:
                    cursor.execute("""
                        INSERT INTO holidays (holiday_date, name, is_legal)
                        VALUES (%s, %s, 1)
                    """, (solar_date, name))
                    added += 1
                    print(f"[OK] 추가됨: {solar_date} - {name} (음력)")
        except Exception as e:
            print(f"[WARN]  음력 변환 실패 (korean_lunar_calendar 라이브러리 필요): {e}")
            print("ℹ️  음력 공휴일은 추가되지 않았습니다. 수동으로 추가해주세요.")
        
        conn.commit()
        
        total = added + skipped
        return {
            "year": year,
            "added": added,
            "skipped": skipped,
            "total": total,
            "message": f"{year}년 법정공휴일 자동 추가 완료"
        }
    finally:
        conn.close()

# ==================== 과정(학급) 관리 API ====================

@app.get("/api/courses")
async def get_courses():
    """과정 목록 조회 (학생수, 과목수, 교과목 목록 포함)"""
    conn = get_db_connection()
    try:
        cursor = conn.cursor(pymysql.cursors.DictCursor)
        cursor.execute("""
            SELECT c.*, 
                   COUNT(DISTINCT s.id) as student_count,
                   COUNT(DISTINCT cs.subject_code) as subject_count
            FROM courses c
            LEFT JOIN students s ON c.code = s.course_code
            LEFT JOIN course_subjects cs ON c.code = cs.course_code
            GROUP BY c.code
            ORDER BY c.code
        """)
        courses = cursor.fetchall()
        
        # 각 과정의 교과목 목록 조회
        for course in courses:
            cursor.execute("""
                SELECT subject_code
                FROM course_subjects
                WHERE course_code = %s
                ORDER BY subject_code
            """, (course['code'],))
            subjects = cursor.fetchall()
            course['subjects'] = [s['subject_code'] for s in subjects]
        
        return [convert_datetime(course) for course in courses]
    finally:
        conn.close()

@app.get("/api/courses/{code}")
async def get_course(code: str):
    """특정 과정 조회 (교과목 포함)"""
    conn = get_db_connection()
    try:
        cursor = conn.cursor(pymysql.cursors.DictCursor)
        cursor.execute("""
            SELECT c.*,
                   COUNT(DISTINCT s.id) as student_count
            FROM courses c
            LEFT JOIN students s ON c.code = s.course_code
            WHERE c.code = %s
            GROUP BY c.code
        """, (code,))
        course = cursor.fetchone()
        if not course:
            raise HTTPException(status_code=404, detail="과정을 찾을 수 없습니다")
        
        # 과정의 교과목 조회
        cursor.execute("""
            SELECT subject_code
            FROM course_subjects
            WHERE course_code = %s
            ORDER BY subject_code
        """, (code,))
        subjects = cursor.fetchall()
        course['subjects'] = [s['subject_code'] for s in subjects]
        
        return convert_datetime(course)
    finally:
        conn.close()

@app.post("/api/courses")
async def create_course(data: dict):
    """과정 생성"""
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        
        # 이모지 제거 (utf8mb4 미지원 DB 컬럼 대응)
        def remove_emoji(text):
            if not text:
                return text
            try:
                # 4바이트 UTF-8 문자 모두 제거 (이모지 포함)
                return ''.join(c for c in text if len(c.encode('utf-8')) < 4)
            except:
                return text
        
        # morning_hours, afternoon_hours 컬럼이 없으면 추가
        try:
            cursor.execute("""
                ALTER TABLE courses 
                ADD COLUMN morning_hours INT DEFAULT 4
            """)
        except:
            pass  # 이미 존재하면 무시
        
        try:
            cursor.execute("""
                ALTER TABLE courses 
                ADD COLUMN afternoon_hours INT DEFAULT 4
            """)
        except:
            pass  # 이미 존재하면 무시
        
        # notes 필드 이모지 제거
        notes_cleaned = remove_emoji(data.get('notes'))
        
        query = """
            INSERT INTO courses (code, name, lecture_hours, project_hours, internship_hours,
                                capacity, location, notes, start_date, lecture_end_date,
                                project_end_date, internship_end_date, final_end_date, total_days,
                                morning_hours, afternoon_hours)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """
        cursor.execute(query, (
            data['code'], data['name'], data['lecture_hours'], data['project_hours'],
            data.get('workship_hours', 0), data['capacity'], data.get('location'),  # workship_hours → DB에는 internship_hours
            notes_cleaned, data.get('start_date'), data.get('lecture_end_date'),
            data.get('project_end_date'), data.get('workship_end_date'),  # workship_end_date → DB에는 internship_end_date
            data.get('final_end_date'), data.get('total_days'),
            data.get('morning_hours', 4), data.get('afternoon_hours', 4)
        ))
        conn.commit()
        return {"code": data['code']}
    except Exception as e:
        conn.rollback()
        import traceback
        print(f"[ERROR] 과정 생성 에러: {e}")
        print(traceback.format_exc())
        raise HTTPException(status_code=500, detail=f"과정 생성 실패: {str(e)}")
    finally:
        conn.close()

@app.put("/api/courses/{code}")
async def update_course(code: str, data: dict):
    """과정 수정"""
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        
        # 이모지 제거 (utf8mb4 미지원 DB 컬럼 대응)
        def remove_emoji(text):
            if not text:
                return text
            try:
                # 4바이트 UTF-8 문자 모두 제거 (이모지 포함)
                return ''.join(c for c in text if len(c.encode('utf-8')) < 4)
            except:
                return text
        
        # 동적 UPDATE 쿼리 생성
        update_fields = []
        values = []
        
        field_mapping = {
            'name': 'name',
            'lecture_hours': 'lecture_hours',
            'project_hours': 'project_hours',
            'workship_hours': 'internship_hours',  # DB 컬럼명은 아직 internship_hours
            'capacity': 'capacity',
            'location': 'location',
            'notes': 'notes',
            'start_date': 'start_date',
            'lecture_end_date': 'lecture_end_date',
            'project_end_date': 'project_end_date',
            'workship_end_date': 'internship_end_date',  # DB 컬럼명은 아직 internship_end_date
            'final_end_date': 'final_end_date',
            'total_days': 'total_days',
            'morning_hours': 'morning_hours',
            'afternoon_hours': 'afternoon_hours'
        }
        
        for field_name, db_column in field_mapping.items():
            if field_name in data:
                value = data[field_name]
                # notes 필드만 이모지 제거
                if field_name == 'notes':
                    value = remove_emoji(value)
                update_fields.append(f"{db_column} = %s")
                values.append(value)
        
        if not update_fields:
            return {"code": code, "message": "업데이트할 필드가 없습니다"}
        
        query = f"UPDATE courses SET {', '.join(update_fields)} WHERE code = %s"
        values.append(code)
        
        cursor.execute(query, tuple(values))
        conn.commit()
        return {"code": code}
    except Exception as e:
        import traceback
        print(f"과정 업데이트 에러: {str(e)}")
        print(traceback.format_exc())
        raise HTTPException(status_code=500, detail=f"과정 업데이트 실패: {str(e)}")
    finally:
        conn.close()

@app.delete("/api/courses/{code}")
async def delete_course(code: str):
    """과정 삭제 (관련 데이터 cascade) - [WARN] 위험: 시간표, 훈련일지 모두 삭제됨!"""
    conn = get_db_connection()
    try:
        cursor = conn.cursor(pymysql.cursors.DictCursor)
        
        # 삭제될 데이터 개수 확인 (경고용)
        cursor.execute("SELECT COUNT(*) as count FROM timetables WHERE course_code = %s", (code,))
        timetable_count = cursor.fetchone()['count']
        
        cursor.execute("SELECT COUNT(*) as count FROM training_logs WHERE course_code = %s", (code,))
        training_log_count = cursor.fetchone()['count']
        
        # 모든 과정 삭제 차단 (데이터 보호)
        raise HTTPException(
            status_code=403, 
            detail=f"[ERROR] 과정 삭제 기능이 비활성화되었습니다. 데이터 손실 방지를 위해 관리자에게 문의하세요. (과정: {code}, 영향: 시간표 {timetable_count}건, 훈련일지 {training_log_count}건)"
        )
        
        # 삭제가 정말 필요한 경우, 아래 주석을 해제하고 위 raise를 주석 처리
        # if code in ['C-001', 'C-002']:
        #     raise HTTPException(
        #         status_code=403, 
        #         detail=f"[ERROR] 주요 과정({code})은 삭제할 수 없습니다. 관리자에게 문의하세요."
        #     )
        
        # 데이터가 많을 경우 경고 로그
        if timetable_count > 0 or training_log_count > 0:
            print(f"[WARN] 과정 삭제 경고: {code} - 시간표 {timetable_count}건, 훈련일지 {training_log_count}건 함께 삭제됨!")
        
        # 1. 시간표 삭제
        cursor.execute("DELETE FROM timetables WHERE course_code = %s", (code,))
        
        # 2. 훈련일지 삭제
        cursor.execute("DELETE FROM training_logs WHERE course_code = %s", (code,))
        
        # 3. 과정-교과목 연결 삭제
        cursor.execute("DELETE FROM course_subjects WHERE course_code = %s", (code,))
        
        # 4. 과정 삭제
        cursor.execute("DELETE FROM courses WHERE code = %s", (code,))
        
        conn.commit()
        return {
            "message": "과정 및 관련 데이터가 삭제되었습니다",
            "deleted": {
                "timetables": timetable_count,
                "training_logs": training_log_count
            }
        }
    except Exception as e:
        conn.rollback()
        import traceback
        print(f"과정 삭제 오류: {str(e)}")
        print(traceback.format_exc())
        raise HTTPException(status_code=500, detail=f"과정 삭제 실패: {str(e)}")
    finally:
        conn.close()

# ==================== 프로젝트 관리 API ====================

@app.get("/api/projects")
async def get_projects(course_code: Optional[str] = None):
    """팀 목록 조회 (과정별 필터)"""
    conn = get_db_connection()
    try:
        cursor = conn.cursor(pymysql.cursors.DictCursor)
        
        # Check if new columns exist, if not, add them
        try:
            cursor.execute("SHOW COLUMNS FROM projects LIKE 'group_type'")
            if not cursor.fetchone():
                # Add new columns
                cursor.execute("ALTER TABLE projects ADD COLUMN group_type VARCHAR(50)")
                cursor.execute("ALTER TABLE projects ADD COLUMN instructor_code VARCHAR(50)")
                cursor.execute("ALTER TABLE projects ADD COLUMN mentor_code VARCHAR(50)")
                conn.commit()
        except:
            pass  # Columns might already exist
        
        # Check if account columns exist, if not, add them
        try:
            cursor.execute("SHOW COLUMNS FROM projects LIKE 'account1_name'")
            if not cursor.fetchone():
                # Add shared account columns (5 sets of 3 fields = 15 columns)
                for i in range(1, 6):
                    cursor.execute(f"ALTER TABLE projects ADD COLUMN account{i}_name VARCHAR(100)")
                    cursor.execute(f"ALTER TABLE projects ADD COLUMN account{i}_id VARCHAR(100)")
                    cursor.execute(f"ALTER TABLE projects ADD COLUMN account{i}_pw VARCHAR(100)")
                conn.commit()
        except:
            pass  # Columns might already exist
        
        # Check if photo_urls column exists, if not, add it
        ensure_photo_urls_column(cursor, 'projects')
        
        query = """
            SELECT p.*, 
                   c.name as course_name,
                   i1.name as instructor_name,
                   i2.name as mentor_name
            FROM projects p
            LEFT JOIN courses c ON p.course_code = c.code
            LEFT JOIN instructors i1 ON p.instructor_code = i1.code
            LEFT JOIN instructors i2 ON p.mentor_code = i2.code
            WHERE 1=1
        """
        params = []
        
        if course_code:
            query += " AND p.course_code = %s"
            params.append(course_code)
        
        query += " ORDER BY p.code"
        
        cursor.execute(query, params)
        projects = cursor.fetchall()
        return [convert_datetime(proj) for proj in projects]
    finally:
        conn.close()

@app.get("/api/projects/{code}")
async def get_project(code: str):
    """특정 팀 조회"""
    conn = get_db_connection()
    try:
        cursor = conn.cursor(pymysql.cursors.DictCursor)
        cursor.execute("""
            SELECT p.*, 
                   c.name as course_name,
                   i1.name as instructor_name,
                   i2.name as mentor_name
            FROM projects p
            LEFT JOIN courses c ON p.course_code = c.code
            LEFT JOIN instructors i1 ON p.instructor_code = i1.code
            LEFT JOIN instructors i2 ON p.mentor_code = i2.code
            WHERE p.code = %s
        """, (code,))
        project = cursor.fetchone()
        if not project:
            raise HTTPException(status_code=404, detail="팀을 찾을 수 없습니다")
        return convert_datetime(project)
    finally:
        conn.close()

@app.post("/api/projects")
async def create_project(data: dict):
    """팀 생성 (5명의 팀원 정보)"""
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        
        # Check if new columns exist, if not, add them
        try:
            cursor.execute("SHOW COLUMNS FROM projects LIKE 'member1_code'")
            if not cursor.fetchone():
                # Add new columns
                for i in range(1, 6):
                    cursor.execute(f"ALTER TABLE projects ADD COLUMN member{i}_code VARCHAR(50)")
                cursor.execute("ALTER TABLE projects ADD COLUMN group_type VARCHAR(50)")
                cursor.execute("ALTER TABLE projects ADD COLUMN instructor_code VARCHAR(50)")
                cursor.execute("ALTER TABLE projects ADD COLUMN mentor_code VARCHAR(50)")
                conn.commit()
        except:
            pass  # Columns might already exist
        
        # Check if account columns exist, if not, add them
        try:
            cursor.execute("SHOW COLUMNS FROM projects LIKE 'account1_name'")
            if not cursor.fetchone():
                # Add shared account columns (5 sets of 3 fields = 15 columns)
                for i in range(1, 6):
                    cursor.execute(f"ALTER TABLE projects ADD COLUMN account{i}_name VARCHAR(100)")
                    cursor.execute(f"ALTER TABLE projects ADD COLUMN account{i}_id VARCHAR(100)")
                    cursor.execute(f"ALTER TABLE projects ADD COLUMN account{i}_pw VARCHAR(100)")
                conn.commit()
        except:
            pass  # Columns might already exist
        
        # Ensure photo_urls column exists
        ensure_photo_urls_column(cursor, 'projects')
        
        # Ensure description column exists (TEXT type for markdown support)
        try:
            cursor.execute("SHOW COLUMNS FROM projects LIKE 'description'")
            result = cursor.fetchone()
            if not result:
                print("[INFO] Adding description column to projects table...")
                cursor.execute("ALTER TABLE projects ADD COLUMN description TEXT")
                conn.commit()
                print("[OK] Description column added successfully")
        except Exception as e:
            print(f"[WARN] Description column check failed: {e}")
            # Column might already exist, continue anyway
            pass
        
        query = """
            INSERT INTO projects (code, name, description, group_type, course_code, instructor_code, mentor_code,
                                 member1_name, member1_phone, member1_code,
                                 member2_name, member2_phone, member2_code,
                                 member3_name, member3_phone, member3_code,
                                 member4_name, member4_phone, member4_code,
                                 member5_name, member5_phone, member5_code,
                                 member6_name, member6_phone, member6_code,
                                 account1_name, account1_id, account1_pw,
                                 account2_name, account2_id, account2_pw,
                                 account3_name, account3_id, account3_pw,
                                 account4_name, account4_id, account4_pw,
                                 account5_name, account5_id, account5_pw,
                                 photo_urls)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                    %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """
        cursor.execute(query, (
            data['code'], data['name'], data.get('description'), data.get('group_type'), data.get('course_code'),
            data.get('instructor_code'), data.get('mentor_code'),
            data.get('member1_name'), data.get('member1_phone'), data.get('member1_code'),
            data.get('member2_name'), data.get('member2_phone'), data.get('member2_code'),
            data.get('member3_name'), data.get('member3_phone'), data.get('member3_code'),
            data.get('member4_name'), data.get('member4_phone'), data.get('member4_code'),
            data.get('member5_name'), data.get('member5_phone'), data.get('member5_code'),
            data.get('member6_name'), data.get('member6_phone'), data.get('member6_code'),
            data.get('account1_name'), data.get('account1_id'), data.get('account1_pw'),
            data.get('account2_name'), data.get('account2_id'), data.get('account2_pw'),
            data.get('account3_name'), data.get('account3_id'), data.get('account3_pw'),
            data.get('account4_name'), data.get('account4_id'), data.get('account4_pw'),
            data.get('account5_name'), data.get('account5_id'), data.get('account5_pw'),
            data.get('photo_urls', '[]')
        ))
        conn.commit()
        return {"code": data['code']}
    finally:
        conn.close()

@app.put("/api/projects/{code}")
async def update_project(code: str, data: dict):
    """팀 수정"""
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        # Ensure photo_urls column exists
        ensure_photo_urls_column(cursor, 'projects')
        
        # Ensure description column exists (TEXT type for markdown support)
        try:
            cursor.execute("SHOW COLUMNS FROM projects LIKE 'description'")
            result = cursor.fetchone()
            if not result:
                print("[INFO] Adding description column to projects table...")
                cursor.execute("ALTER TABLE projects ADD COLUMN description TEXT")
                conn.commit()
                print("[OK] Description column added successfully")
        except Exception as e:
            print(f"[WARN] Description column check failed: {e}")
            # Column might already exist, continue anyway
            pass
        
        query = """
            UPDATE projects
            SET name = %s, description = %s, group_type = %s, course_code = %s, 
                instructor_code = %s, mentor_code = %s,
                member1_name = %s, member1_phone = %s, member1_code = %s,
                member2_name = %s, member2_phone = %s, member2_code = %s,
                member3_name = %s, member3_phone = %s, member3_code = %s,
                member4_name = %s, member4_phone = %s, member4_code = %s,
                member5_name = %s, member5_phone = %s, member5_code = %s,
                member6_name = %s, member6_phone = %s, member6_code = %s,
                account1_name = %s, account1_id = %s, account1_pw = %s,
                account2_name = %s, account2_id = %s, account2_pw = %s,
                account3_name = %s, account3_id = %s, account3_pw = %s,
                account4_name = %s, account4_id = %s, account4_pw = %s,
                account5_name = %s, account5_id = %s, account5_pw = %s,
                photo_urls = %s
            WHERE code = %s
        """
        cursor.execute(query, (
            data['name'], data.get('description'), data.get('group_type'), data.get('course_code'),
            data.get('instructor_code'), data.get('mentor_code'),
            data.get('member1_name'), data.get('member1_phone'), data.get('member1_code'),
            data.get('member2_name'), data.get('member2_phone'), data.get('member2_code'),
            data.get('member3_name'), data.get('member3_phone'), data.get('member3_code'),
            data.get('member4_name'), data.get('member4_phone'), data.get('member4_code'),
            data.get('member5_name'), data.get('member5_phone'), data.get('member5_code'),
            data.get('member6_name'), data.get('member6_phone'), data.get('member6_code'),
            data.get('account1_name'), data.get('account1_id'), data.get('account1_pw'),
            data.get('account2_name'), data.get('account2_id'), data.get('account2_pw'),
            data.get('account3_name'), data.get('account3_id'), data.get('account3_pw'),
            data.get('account4_name'), data.get('account4_id'), data.get('account4_pw'),
            data.get('account5_name'), data.get('account5_id'), data.get('account5_pw'),
            data.get('photo_urls', '[]'),
            code
        ))
        conn.commit()
        return {"code": code}
    finally:
        conn.close()

@app.delete("/api/projects/{code}")
async def delete_project(code: str):
    """팀 삭제"""
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM projects WHERE code = %s", (code,))
        if cursor.rowcount == 0:
            raise HTTPException(status_code=404, detail="팀을 찾을 수 없습니다")
        conn.commit()
        return {"message": "팀이 삭제되었습니다"}
    finally:
        conn.close()

# ==================== 수업관리(시간표) API ====================

@app.get("/api/timetables")
async def get_timetables(
    course_code: Optional[str] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None
):
    """시간표 목록 조회 (과정/기간별 필터)"""
    conn = get_db_connection()
    try:
        cursor = conn.cursor(pymysql.cursors.DictCursor)
        
        query = """
            SELECT t.*, 
                   c.name as course_name, c.start_date as course_start_date,
                   s.name as subject_name,
                   i.name as instructor_name,
                   tl.id as training_log_id,
                   tl.content as training_content,
                   tl.photo_urls as training_log_photo_urls
            FROM timetables t
            LEFT JOIN courses c ON t.course_code = c.code
            LEFT JOIN subjects s ON t.subject_code = s.code
            LEFT JOIN instructors i ON t.instructor_code = i.code
            LEFT JOIN training_logs tl ON t.id = tl.timetable_id
            WHERE 1=1
        """
        params = []
        
        if course_code:
            query += " AND t.course_code = %s"
            params.append(course_code)
        
        if start_date:
            query += " AND t.class_date >= %s"
            params.append(start_date)
        
        if end_date:
            query += " AND t.class_date <= %s"
            params.append(end_date)
        
        query += " ORDER BY t.class_date, t.start_time"
        
        cursor.execute(query, params)
        timetables = cursor.fetchall()
        
        # 주차/일차 계산
        for tt in timetables:
            if tt.get('course_start_date') and tt.get('class_date'):
                delta = (tt['class_date'] - tt['course_start_date']).days
                tt['week_number'] = (delta // 7) + 1
                tt['day_number'] = delta + 1
            else:
                tt['week_number'] = None
                tt['day_number'] = None
        return [convert_datetime(tt) for tt in timetables]
    finally:
        conn.close()

@app.get("/api/timetables/{timetable_id}")
async def get_timetable(timetable_id: int):
    """특정 시간표 조회"""
    conn = get_db_connection()
    try:
        cursor = conn.cursor(pymysql.cursors.DictCursor)
        cursor.execute("""
            SELECT t.*,
                   c.name as course_name,
                   s.name as subject_name,
                   i.name as instructor_name
            FROM timetables t
            LEFT JOIN courses c ON t.course_code = c.code
            LEFT JOIN subjects s ON t.subject_code = s.code
            LEFT JOIN instructors i ON t.instructor_code = i.code
            WHERE t.id = %s
        """, (timetable_id,))
        timetable = cursor.fetchone()
        if not timetable:
            raise HTTPException(status_code=404, detail="시간표를 찾을 수 없습니다")
        return convert_datetime(timetable)
    finally:
        conn.close()

@app.post("/api/timetables")
async def create_timetable(data: dict):
    """시간표 생성"""
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        query = """
            INSERT INTO timetables (course_code, subject_code, class_date, start_time,
                                   end_time, instructor_code, type, notes)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        """
        cursor.execute(query, (
            data['course_code'], data.get('subject_code'), data['class_date'],
            data['start_time'], data['end_time'], data.get('instructor_code'),
            data['type'], data.get('notes')
        ))
        conn.commit()
        return {"id": cursor.lastrowid}
    finally:
        conn.close()

@app.put("/api/timetables/{timetable_id}")
async def update_timetable(timetable_id: int, data: dict):
    """시간표 수정"""
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        query = """
            UPDATE timetables
            SET course_code = %s, subject_code = %s, class_date = %s,
                start_time = %s, end_time = %s, instructor_code = %s,
                type = %s, notes = %s
            WHERE id = %s
        """
        cursor.execute(query, (
            data['course_code'], data.get('subject_code'), data['class_date'],
            data['start_time'], data['end_time'], data.get('instructor_code'),
            data['type'], data.get('notes'), timetable_id
        ))
        conn.commit()
        return {"id": timetable_id}
    except Exception as e:
        conn.rollback()
        print(f"시간표 수정 에러: {str(e)}")
        print(f"데이터: {data}")
        raise HTTPException(status_code=500, detail=f"시간표 수정 실패: {str(e)}")
    finally:
        conn.close()

@app.delete("/api/timetables/{timetable_id}")
async def delete_timetable(timetable_id: int):
    """시간표 삭제"""
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM timetables WHERE id = %s", (timetable_id,))
        conn.commit()
        return {"message": "시간표가 삭제되었습니다"}
    finally:
        conn.close()

# ==================== 상담 관리 API ====================

@app.get("/api/counselings")
async def get_counselings(
    student_id: Optional[int] = None,
    month: Optional[str] = None,
    course_code: Optional[str] = None
):
    """상담 목록 조회 (학생별/월별/학급별 필터)"""
    conn = get_db_connection()
    try:
        cursor = conn.cursor(pymysql.cursors.DictCursor)
        
        # photo_urls, career_decision 컬럼 확인 및 추가
        ensure_photo_urls_column(cursor, 'consultations')
        ensure_career_decision_column(cursor)
        
        query = """
            SELECT c.*, s.name as student_name, s.code as student_code, s.course_code,
                   i.name as instructor_name
            FROM consultations c
            LEFT JOIN students s ON c.student_id = s.id
            LEFT JOIN instructors i ON c.instructor_code = i.code
            WHERE 1=1
        """
        params = []
        
        if student_id:
            query += " AND c.student_id = %s"
            params.append(student_id)
        
        if month:  # 형식: "2025-01"
            query += " AND DATE_FORMAT(c.consultation_date, '%%Y-%%m') = %s"
            params.append(month)
        
        if course_code:
            query += " AND s.course_code = %s"
            params.append(course_code)
        
        query += " ORDER BY c.consultation_date DESC"
        
        cursor.execute(query, params)
        counselings = cursor.fetchall()
        
        for counseling in counselings:
            for key, value in counseling.items():
                if isinstance(value, (datetime, date)):
                    counseling[key] = value.isoformat()
        
        return counselings
    finally:
        conn.close()

@app.get("/api/counselings/{counseling_id}")
async def get_counseling(counseling_id: int):
    """특정 상담 조회"""
    conn = get_db_connection()
    try:
        cursor = conn.cursor(pymysql.cursors.DictCursor)
        cursor.execute("""
            SELECT c.*, s.name as student_name, s.code as student_code,
                   i.name as instructor_name
            FROM consultations c
            LEFT JOIN students s ON c.student_id = s.id
            LEFT JOIN instructors i ON c.instructor_code = i.code
            WHERE c.id = %s
        """, (counseling_id,))
        counseling = cursor.fetchone()
        
        if not counseling:
            raise HTTPException(status_code=404, detail="상담 기록을 찾을 수 없습니다")
        
        for key, value in counseling.items():
            if isinstance(value, (datetime, date)):
                counseling[key] = value.isoformat()
        
        return counseling
    finally:
        conn.close()

@app.post("/api/counselings")
async def create_counseling(data: dict):
    """상담 생성"""
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        
        # photo_urls, career_decision 컬럼 확인 및 추가
        ensure_photo_urls_column(cursor, 'consultations')
        ensure_career_decision_column(cursor)
        
        # consultations 테이블 구조에 맞게 조정
        query = """
            INSERT INTO consultations 
            (student_id, instructor_code, consultation_date, consultation_type, main_topic, content, status, photo_urls, career_decision)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
        """
        
        # instructor_code가 빈 문자열이면 None으로 처리
        instructor_code = data.get('instructor_code')
        if instructor_code == '':
            instructor_code = None
        
        cursor.execute(query, (
            data.get('student_id'),
            instructor_code,
            data.get('consultation_date') or data.get('counseling_date'),
            data.get('consultation_type', '정기'),
            data.get('main_topic') or data.get('topic', ''),
            data.get('content'),
            data.get('status', '완료'),
            data.get('photo_urls'),
            data.get('career_decision')
        ))
        
        conn.commit()
        return {"id": cursor.lastrowid}
    except pymysql.err.OperationalError as e:
        raise HTTPException(status_code=500, detail=f"데이터베이스 오류: {str(e)}")
    except pymysql.err.IntegrityError as e:
        raise HTTPException(status_code=400, detail=f"데이터 무결성 오류: {str(e)}")
    finally:
        conn.close()

@app.put("/api/counselings/{counseling_id}")
async def update_counseling(counseling_id: int, data: dict):
    """상담 수정"""
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        
        # photo_urls, career_decision 컬럼 확인 및 추가
        ensure_photo_urls_column(cursor, 'consultations')
        ensure_career_decision_column(cursor)
        
        query = """
            UPDATE consultations 
            SET student_id = %s, instructor_code = %s, consultation_date = %s, consultation_type = %s,
                main_topic = %s, content = %s, status = %s, photo_urls = %s, career_decision = %s
            WHERE id = %s
        """
        
        # instructor_code가 빈 문자열이면 None으로 처리
        instructor_code = data.get('instructor_code')
        if instructor_code == '':
            instructor_code = None
        
        cursor.execute(query, (
            data.get('student_id'),
            instructor_code,
            data.get('consultation_date') or data.get('counseling_date'),
            data.get('consultation_type', '정기'),
            data.get('main_topic') or data.get('topic', ''),
            data.get('content'),
            data.get('status', '완료'),
            data.get('photo_urls'),
            data.get('career_decision'),
            counseling_id
        ))
        
        conn.commit()
        return {"id": counseling_id}
    finally:
        conn.close()

@app.delete("/api/counselings/{counseling_id}")
async def delete_counseling(counseling_id: int):
    """상담 삭제"""
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM consultations WHERE id = %s", (counseling_id,))
        conn.commit()
        return {"message": "상담 기록이 삭제되었습니다"}
    finally:
        conn.close()

# ==================== 훈련일지 관리 API ====================

@app.get("/api/training-logs")
async def get_training_logs(
    course_code: Optional[str] = None,
    instructor_code: Optional[str] = None,
    year: Optional[int] = None,
    month: Optional[int] = None,
    timetable_id: Optional[int] = None
):
    """훈련일지 목록 조회"""
    conn = get_db_connection()
    try:
        cursor = conn.cursor(pymysql.cursors.DictCursor)
        
        # training_logs 테이블이 없으면 생성
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS training_logs (
                id INT AUTO_INCREMENT PRIMARY KEY,
                timetable_id INT NOT NULL,
                course_code VARCHAR(50),
                instructor_code VARCHAR(50),
                class_date DATE,
                content TEXT,
                homework TEXT,
                notes TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                FOREIGN KEY (timetable_id) REFERENCES timetables(id) ON DELETE CASCADE
            )
        """)
        conn.commit()
        
        query = """
            SELECT tl.*, 
                   t.class_date, t.start_time, t.end_time, t.type,
                   s.name as subject_name,
                   i.name as instructor_name,
                   c.name as course_name
            FROM training_logs tl
            LEFT JOIN timetables t ON tl.timetable_id = t.id
            LEFT JOIN subjects s ON t.subject_code = s.code
            LEFT JOIN instructors i ON t.instructor_code = i.code
            LEFT JOIN courses c ON t.course_code = c.code
            WHERE 1=1
        """
        
        params = []
        
        if timetable_id:
            query += " AND tl.timetable_id = %s"
            params.append(timetable_id)
        
        if course_code:
            query += " AND t.course_code = %s"
            params.append(course_code)
        
        if instructor_code:
            query += " AND t.instructor_code = %s"
            params.append(instructor_code)
        
        if year and month:
            query += " AND YEAR(t.class_date) = %s AND MONTH(t.class_date) = %s"
            params.extend([year, month])
        elif year:
            query += " AND YEAR(t.class_date) = %s"
            params.append(year)
        
        query += " ORDER BY t.class_date, t.start_time"
        
        cursor.execute(query, params)
        logs = cursor.fetchall()
        
        for log in logs:
            for key, value in log.items():
                if isinstance(value, (datetime, date)):
                    log[key] = value.isoformat()
        
        return logs
    finally:
        conn.close()

@app.get("/api/training-logs/{log_id}")
async def get_training_log(log_id: int):
    """특정 훈련일지 조회"""
    conn = get_db_connection()
    try:
        cursor = conn.cursor(pymysql.cursors.DictCursor)
        cursor.execute("""
            SELECT tl.*, 
                   t.class_date, t.start_time, t.end_time, t.type,
                   s.name as subject_name,
                   i.name as instructor_name,
                   c.name as course_name
            FROM training_logs tl
            LEFT JOIN timetables t ON tl.timetable_id = t.id
            LEFT JOIN subjects s ON t.subject_code = s.code
            LEFT JOIN instructors i ON t.instructor_code = i.code
            LEFT JOIN courses c ON t.course_code = c.code
            WHERE tl.id = %s
        """, (log_id,))
        log = cursor.fetchone()
        
        if not log:
            raise HTTPException(status_code=404, detail="훈련일지를 찾을 수 없습니다")
        
        for key, value in log.items():
            if isinstance(value, (datetime, date)):
                log[key] = value.isoformat()
        
        return log
    finally:
        conn.close()

@app.post("/api/training-logs")
async def create_training_log(data: dict):
    """훈련일지 생성"""
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        
        # photo_urls 컬럼이 없으면 자동 생성
        ensure_photo_urls_column(cursor, 'training_logs')
        
        query = """
            INSERT INTO training_logs 
            (timetable_id, course_code, instructor_code, class_date, content, homework, notes, photo_urls)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        """
        
        cursor.execute(query, (
            data.get('timetable_id'),
            data.get('course_code'),
            data.get('instructor_code'),
            data.get('class_date'),
            data.get('content', ''),
            data.get('homework', ''),
            data.get('notes', ''),
            data.get('photo_urls')
        ))
        
        conn.commit()
        return {"id": cursor.lastrowid}
    except pymysql.err.OperationalError as e:
        raise HTTPException(status_code=500, detail=f"데이터베이스 오류: {str(e)}")
    finally:
        conn.close()

@app.put("/api/training-logs/{log_id}")
async def update_training_log(log_id: int, data: dict):
    """훈련일지 수정"""
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        
        # photo_urls 컬럼이 없으면 자동 생성
        ensure_photo_urls_column(cursor, 'training_logs')
        
        query = """
            UPDATE training_logs 
            SET content = %s, homework = %s, notes = %s, photo_urls = %s
            WHERE id = %s
        """
        
        cursor.execute(query, (
            data.get('content', ''),
            data.get('homework', ''),
            data.get('notes', ''),
            data.get('photo_urls'),
            log_id
        ))
        
        conn.commit()
        return {"id": log_id}
    finally:
        conn.close()

@app.delete("/api/training-logs/{log_id}")
async def delete_training_log(log_id: int):
    """훈련일지 삭제"""
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM training_logs WHERE id = %s", (log_id,))
        conn.commit()
        return {"message": "훈련일지가 삭제되었습니다"}
    finally:
        conn.close()

@app.post("/api/training-logs/generate-content")
async def generate_training_content(data: dict):
    """AI를 이용한 훈련일지 수업 내용 자동 생성 (사용자 입력 기반 확장)"""
    subject_name = data.get('subject_name', '')
    sub_subjects = data.get('sub_subjects', [])  # 세부 교과목 리스트
    class_date = data.get('class_date', '')
    instructor_name = data.get('instructor_name', '')
    user_input = data.get('user_input', '').strip()  # 사용자가 입력한 내용
    detail_level = data.get('detail_level', 'normal')  # 'summary', 'normal', 'detailed'
    timetable_type = data.get('timetable_type', 'lecture')  # 'lecture', 'project', 'practice'
    
    if not user_input:
        raise HTTPException(status_code=400, detail="수업 내용을 먼저 입력해주세요 (최소 몇 단어라도)")
    
    # Groq API 키 확인
    groq_api_key = os.getenv('GROQ_API_KEY', '')
    
    # 세부 교과목 텍스트 포맷팅
    sub_subjects_text = ""
    if sub_subjects:
        for sub in sub_subjects:
            sub_subjects_text += f"- {sub.get('name', '')} ({sub.get('hours', 0)}시간)\n"
    
    # 상세도에 따른 지시사항
    detail_instructions = {
        'summary': '간결하고 핵심적인 내용으로 200-300자 정도로 작성해주세요.',
        'normal': '적절한 상세도로 400-600자 정도로 작성해주세요.',
        'detailed': '매우 상세하고 구체적으로 800-1200자 정도로 작성해주세요. 예제, 실습 내용, 학생 반응 등을 포함하세요.'
    }
    
    # 타입별 시스템 프롬프트
    if timetable_type == 'project':
        system_prompt = """당신은 IT 프로젝트 과정의 전문 지도 강사입니다.
강사가 입력한 간단한 메모나 키워드를 바탕으로, 실제 프로젝트 진행 내용을 전문적인 훈련일지 형식으로 확장하여 작성해주세요.

**중요 규칙**:
1. 강사가 입력한 원본 내용은 반드시 그대로 포함
2. 원본 텍스트를 절대 삭제하거나 변경하지 말 것
3. **개조식(bullet point) 형식으로 작성** - 완전한 문장이 아닌 간결한 구문 사용
4. "~했습니다", "~입니다" 등의 서술형 대신 "~함", "~진행", "~학습" 등의 체언 종결 사용
5. 프로젝트 진행 상황, 문제 해결, 팀 협업에 초점"""

        user_prompt_template = """
다음은 강사가 입력한 오늘 프로젝트 활동 메모입니다:

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
【강사가 입력한 원본 내용】
{user_input}
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

【프로젝트 정보】
- 날짜: {class_date}
- 활동: 프로젝트
- 지도강사: {instructor_name}

위의 원본 내용을 **반드시 그대로 유지하면서** 프로젝트 훈련일지 형식으로 확장해주세요:

[OK] 필수 요구사항:
1. 강사가 입력한 원본 내용("{user_input}")을 반드시 포함
2. 원본 내용을 중심으로 프로젝트 목표, 진행 상황, 팀 활동 추가
3. 원본 키워드나 문장을 삭제하거나 변경 금지
4. **개조식(bullet point) 형식으로 작성**

📝 작성 형식 (개조식):
- 프로젝트 주제: [원본 내용 포함]
- 금일 목표:
  • 목표1
  • 목표2
- 주요 진행 내용:
  • 내용1 (원본 키워드 활용)
  • 내용2
  • 내용3
- 팀별 활동:
  • 활동1
  • 활동2
- 문제 해결 및 개선사항:
  • 이슈1 및 해결방법
  • 이슈2 및 해결방법
- 진행률 및 성과:
  • 달성사항1
  • 달성사항2

{detail_instructions}

**다시 한번 강조**: 
1. "{user_input}" 이 내용은 반드시 결과물에 포함
2. 개조식으로 작성 (서술형 금지)
"""
    
    elif timetable_type == 'practice':
        system_prompt = """당신은 IT 현장실습 과정의 전문 지도 강사입니다.
강사가 입력한 간단한 메모나 키워드를 바탕으로, 실제 현장실습 진행 내용을 전문적인 훈련일지 형식으로 확장하여 작성해주세요.

**중요 규칙**:
1. 강사가 입력한 원본 내용은 반드시 그대로 포함
2. 원본 텍스트를 절대 삭제하거나 변경하지 말 것
3. **개조식(bullet point) 형식으로 작성** - 완전한 문장이 아닌 간결한 구문 사용
4. "~했습니다", "~입니다" 등의 서술형 대신 "~함", "~진행", "~학습" 등의 체언 종결 사용
5. 현장 업무, 실무 경험, 기업 멘토링에 초점"""

        user_prompt_template = """
다음은 강사가 입력한 오늘 현장실습 활동 메모입니다:

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
【강사가 입력한 원본 내용】
{user_input}
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

【현장실습 정보】
- 날짜: {class_date}
- 활동: 현장실습
- 지도강사: {instructor_name}

위의 원본 내용을 **반드시 그대로 유지하면서** 현장실습 훈련일지 형식으로 확장해주세요:

[OK] 필수 요구사항:
1. 강사가 입력한 원본 내용("{user_input}")을 반드시 포함
2. 원본 내용을 중심으로 실습 목표, 현장 업무, 멘토링 내용 추가
3. 원본 키워드나 문장을 삭제하거나 변경 금지
4. **개조식(bullet point) 형식으로 작성**

📝 작성 형식 (개조식):
- 실습 업무: [원본 내용 포함]
- 금일 목표:
  • 목표1
  • 목표2
- 주요 실습 내용:
  • 내용1 (원본 키워드 활용)
  • 내용2
  • 내용3
- 현장 업무 수행:
  • 업무1
  • 업무2
- 멘토링 및 피드백:
  • 피드백1
  • 피드백2
- 학습 성과 및 역량:
  • 성과1
  • 성과2

{detail_instructions}

**다시 한번 강조**: 
1. "{user_input}" 이 내용은 반드시 결과물에 포함
2. 개조식으로 작성 (서술형 금지)
"""
    
    else:  # lecture (기존 교과목)
        system_prompt = """당신은 IT 훈련 과정의 전문 강사입니다.
강사가 입력한 간단한 메모나 키워드를 바탕으로, 실제 수업에서 진행한 내용을 전문적인 훈련일지 형식으로 확장하여 작성해주세요.

**중요 규칙**:
1. 강사가 입력한 원본 내용은 반드시 그대로 포함
2. 원본 텍스트를 절대 삭제하거나 변경하지 말 것
3. **개조식(bullet point) 형식으로 작성** - 완전한 문장이 아닌 간결한 구문 사용
4. "~했습니다", "~입니다" 등의 서술형 대신 "~함", "~진행", "~학습" 등의 체언 종결 사용"""

        user_prompt_template = """
다음은 강사가 입력한 오늘 수업의 메모입니다:

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
【강사가 입력한 원본 내용】
{user_input}
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

【수업 정보】
- 날짜: {class_date}
- 과목: {subject_name}
- 강사: {instructor_name}
- 세부 교과목: 
{sub_subjects_text}

위의 원본 내용을 **반드시 그대로 유지하면서** 훈련일지 형식으로 확장해주세요:

[OK] 필수 요구사항:
1. 강사가 입력한 원본 내용("{user_input}")을 반드시 포함
2. 원본 내용을 중심으로 학습 목표, 진행 내용, 실습 활동 추가
3. 원본 키워드나 문장을 삭제하거나 변경 금지
4. **개조식(bullet point) 형식으로 작성** - 서술형 문장 대신 간결한 구문 사용

📝 작성 형식 (개조식):
- 수업 주제: [원본 내용 포함]
- 학습 목표:
  • 목표1
  • 목표2
- 주요 학습 내용:
  • 내용1 (원본 키워드 활용)
  • 내용2
  • 내용3
- 실습/프로젝트:
  • 실습1
  • 실습2
- 학습 성과:
  • 성과1
  • 성과2

📏 작성 스타일:
- [ERROR] 나쁜 예: "오늘 수업에서는 HTML을 학습했습니다." (서술형)
- [OK] 좋은 예: "HTML 기본 문법 학습 및 실습 진행" (개조식)
- [ERROR] 나쁜 예: "학생들은 CSS를 이해하고 활용할 수 있게 되었습니다."
- [OK] 좋은 예: "CSS 선택자, 속성 이해 및 레이아웃 실습 완료"

{detail_instructions}

**다시 한번 강조**: 
1. "{user_input}" 이 내용은 반드시 결과물에 포함
2. 개조식으로 작성 (서술형 금지)
"""
    
    # 프롬프트 변수 대입
    user_prompt = user_prompt_template.format(
        user_input=user_input,
        class_date=class_date,
        subject_name=subject_name,
        instructor_name=instructor_name,
        sub_subjects_text=sub_subjects_text if sub_subjects_text else '세부 교과목 정보 없음',
        detail_instructions=detail_instructions.get(detail_level, detail_instructions['normal'])
    )
    
    try:
        if groq_api_key:
            headers = {
                "Authorization": f"Bearer {groq_api_key}",
                "Content-Type": "application/json"
            }
            
            payload = {
                "model": "llama-3.3-70b-versatile",  # 업데이트된 모델로 변경
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                "temperature": 0.7,
                "max_tokens": 1000
            }
            
            response = requests.post(
                "https://api.groq.com/openai/v1/chat/completions",
                headers=headers,
                json=payload,
                timeout=30
            )
            
            if response.status_code != 200:
                raise Exception(f"Groq API 오류: {response.text}")
            
            content = response.json()['choices'][0]['message']['content']
        else:
            # API 키가 없으면 템플릿 기반 생성 (타입별 템플릿)
            if timetable_type == 'project':
                # 프로젝트 템플릿
                detail_templates = {
                    'summary': f"""• 프로젝트 주제: {user_input}
• 금일 핵심 진행사항 및 완료된 작업
• 팀 협업 및 문제 해결 진행""",
                    
                    'normal': f"""【프로젝트 주제】
• {user_input}

【금일 목표】
• {user_input} 관련 주요 기능 구현
• 팀원 간 역할 분담 및 협업 진행
• 프로젝트 일정 대비 진행 상황 점검

【주요 진행 내용】
• {user_input} 핵심 기능 개발
• 데이터 구조 설계 및 구현
• UI/UX 개선 작업
• 코드 리뷰 및 품질 개선

【팀별 활동】
• 역할별 작업 진행 상황 공유
• 통합 작업 및 충돌 해결
• 상호 코드 리뷰 및 피드백

【문제 해결 및 개선사항】
• 발생한 기술적 이슈 해결
• 일정 지연 요인 파악 및 대응
• 효율적 개발 방법론 적용

【프로젝트 목표 달성도】
• 계획 대비 진행률: 약 65% (중반 단계)
• 주요 기능 구현 완료율: 70%
• 팀 협업 효율성: 우수""",
                    
                    'detailed': f"""【프로젝트 개요】
• 프로젝트 주제: {user_input}
• 진행 방식: 애자일 방법론, 스프린트 단위 개발
• 금일 목표: 핵심 기능 구현 및 통합 테스트

【금일 목표】
1. {user_input} 관련 주요 모듈 완성
2. 팀원 간 작업 통합 및 충돌 해결
3. 프로젝트 중간 점검 및 일정 조정
4. 품질 개선 및 리팩토링 진행

【주요 진행 내용】
• 개발 작업
  - {user_input} 핵심 로직 구현
  - 데이터베이스 스키마 설계 및 적용
  - API 엔드포인트 개발
  - 프론트엔드 컴포넌트 제작

• 통합 작업
  - Git 브랜치 병합 및 충돌 해결
  - 통합 테스트 수행
  - 버그 수정 및 코드 최적화
  - 문서화 작업 진행

【팀별 활동 상세】
• 프론트엔드 팀
  - UI 컴포넌트 구현 완료
  - 반응형 디자인 적용
  - 사용자 경험 개선

• 백엔드 팀
  - API 서버 기능 구현
  - 데이터베이스 연동 완료
  - 보안 및 인증 처리

• 기획/디자인 팀
  - 와이어프레임 최종 확정
  - 디자인 가이드 작성
  - 사용자 시나리오 테스트

【문제 해결 및 개선사항】
• 기술적 이슈
  - {user_input} 관련 버그 3건 해결
  - 성능 최적화 2건 적용
  - 보안 취약점 1건 수정

• 협업 개선
  - 코드 리뷰 프로세스 개선
  - 커뮤니케이션 도구 활용 강화
  - 일정 관리 방법 최적화

【프로젝트 목표 달성도】
• 전체 진행률: 약 65% (전체 기간 대비 중반 단계)
• 금일 목표 달성률: 85%
• 핵심 기능 완성도: 70%
• 팀 협업 효율: 매우 우수
• 일정 준수율: 양호

【향후 계획】
• 다음 스프린트: {user_input} 고도화 및 테스트
• 남은 기간: 프로젝트 완성 및 발표 준비
• 최종 배포 및 유지보수 계획 수립"""
                }
            
            elif timetable_type == 'practice':
                # 현장실습 템플릿
                detail_templates = {
                    'summary': f"""• 실습 업무: {user_input}
• 현장 실무 경험 및 멘토링 수행
• 실무 역량 강화 및 피드백 적용""",
                    
                    'normal': f"""【실습 업무】
• {user_input}

【금일 목표】
• {user_input} 관련 실무 업무 수행
• 기업 멘토 지도 하에 현장 실습 진행
• 실무 프로세스 이해 및 적용

【주요 실습 내용】
• {user_input} 현장 업무 직접 수행
• 실무 도구 및 시스템 활용 학습
• 업무 프로세스 및 워크플로우 습득
• 팀 협업 및 커뮤니케이션 실습

【현장 업무 수행】
• 실제 프로젝트 참여 및 기여
• 업무 요구사항 분석 및 구현
• 품질 관리 및 테스트 수행
• 문서 작성 및 보고서 제출

【멘토링 및 피드백】
• 기업 멘토의 실무 지도 및 조언
• 작업 결과물에 대한 구체적 피드백
• 개선 방향 및 학습 가이드 제공
• 진로 상담 및 커리어 조언

【학습 성과 및 역량】
• {user_input}에 대한 실무 경험 축적
• 현장 업무 수행 능력 향상
• 협업 및 문제 해결 역량 강화
• 직무 역량 및 전문성 성장""",
                    
                    'detailed': f"""【실습 개요】
• 실습 업무: {user_input}
• 실습 기업: 현장 파트너 기업
• 실습 방식: 멘토 1:1 지도 + 팀 협업
• 금일 목표: 실무 프로젝트 참여 및 핵심 업무 수행

【금일 목표】
1. {user_input} 관련 실무 작업 완수
2. 기업 멘토 피드백 반영 및 개선
3. 현장 프로세스 및 도구 활용 숙달
4. 팀 협업 및 커뮤니케이션 강화

【주요 실습 내용】
• 실무 작업
  - {user_input} 관련 과제 수행
  - 실제 비즈니스 요구사항 분석
  - 현장 도구 및 시스템 활용
  - 품질 기준에 맞는 결과물 산출

• 프로세스 학습
  - 업무 워크플로우 이해 및 적용
  - 협업 도구 활용 (Jira, Slack 등)
  - 코드 리뷰 및 배포 프로세스 경험
  - 애자일/스크럼 방법론 실습

【현장 업무 수행 상세】
• 개발 작업
  - {user_input} 기능 개발 및 테스트
  - 레거시 코드 유지보수
  - 버그 수정 및 성능 개선
  - 기술 문서 작성

• 협업 활동
  - 팀 미팅 참석 및 의견 제시
  - 타 부서와의 커뮤니케이션
  - 일정 관리 및 진행 상황 보고
  - 동료 실습생과의 지식 공유

【멘토링 및 피드백】
• 멘토 지도 내용
  - {user_input} 실무 노하우 전수
  - 코드 리뷰 및 개선 방향 제시
  - 산업 트렌드 및 기술 동향 안내
  - 커리어 발전 방향 상담

• 받은 피드백
  - 작업 속도 및 품질: 우수
  - 기술 이해도: 빠른 학습 능력
  - 협업 태도: 적극적 참여
  - 개선 필요사항: 시간 관리 기술

【학습 성과 및 역량】
• 기술 역량
  - {user_input} 실무 활용 능력 향상
  - 현장 도구 숙련도 증가
  - 문제 해결 능력 강화
  - 코드 품질 의식 함양

• 소프트 스킬
  - 팀 협업 및 커뮤니케이션 능력
  - 업무 책임감 및 자기 관리
  - 비즈니스 이해도 향상
  - 전문가 마인드셋 형성

【진로 및 취업 준비】
• 현장 경험을 통한 직무 적합성 확인
• 포트폴리오 강화 소재 확보
• 기업 인사 담당자와의 네트워킹
• 취업 역량 및 경쟁력 제고"""
                }
            
            else:  # lecture
                # 교과목 템플릿 (기존 유지)
                detail_templates = {
                    'summary': f"""• 수업 주제: {user_input}
• 핵심 개념 학습 및 기본 실습 완료
• 주요 기술 이해도 향상""",
                    
                    'normal': f"""【수업 주제】
• {user_input}

【학습 목표】
• {user_input}의 핵심 개념 이해
• 실무 활용 방법 습득
• 관련 기술 실습 능력 향상

【주요 학습 내용】
• {user_input} 이론 강의 진행
• 기본 원리 및 핵심 개념 설명
• 실제 활용 사례 분석
• 단계별 실습 프로젝트 수행

【실습 활동】
• {user_input} 기반 프로젝트 실습
• 개별/팀별 과제 수행
• 문제 해결 및 피드백

【학습 성과】
• {user_input}에 대한 이해도 향상
• 실무 적용 능력 강화
• 과제 완료율 우수""",
                    
                    'detailed': f"""【수업 개요】
• 수업 주제: {user_input}
• 진행 방식: 이론 강의 + 실습 병행
• 학습 목표: 핵심 개념 이해 및 실무 활용 능력 배양

【학습 목표】
1. {user_input}의 기본 개념 및 원리 완전 이해
2. 실무 환경에서의 효과적 활용 방법 습득
3. 관련 도구 및 기술 숙련도 향상
4. 문제 해결 및 응용 능력 강화

【주요 학습 내용】
• 이론 학습
  - {user_input}의 배경 및 필요성
  - 핵심 개념 및 용어 정리
  - 기본 원리 및 작동 방식 설명
  - 실제 산업 현장 활용 사례 분석

• 실습 진행
  - 기초 실습: {user_input} 기본 활용법
  - 중급 실습: 실무 시나리오 적용
  - 고급 실습: 복합 프로젝트 구현
  - 오류 디버깅 및 최적화 기법

【실습 활동 상세】
• 개별 실습
  - {user_input} 기본 기능 구현
  - 단계별 과제 수행 및 검토
  - 개인별 맞춤 피드백 제공

• 팀 프로젝트
  - 협업 도구 활용한 팀 작업
  - 역할 분담 및 일정 관리
  - 최종 결과물 발표 및 상호 평가

【학습 성과 및 피드백】
• 성취 수준
  - {user_input} 개념 이해도: 상
  - 실습 과제 완료율: 90% 이상
  - 팀 프로젝트 수행 능력: 우수

• 학생 반응
  - 적극적 수업 참여도
  - 질의응답 활발히 진행
  - 추가 학습 자료 요청 다수

【향후 학습 계획】
• 다음 차시: {user_input} 심화 과정
• 고급 기능 및 응용 기술 학습 예정
• 실무 프로젝트 완성도 향상 중점"""
                }
            
            content = detail_templates.get(detail_level, detail_templates['normal'])
        
        return {
            "content": content.strip(),
            "subject_name": subject_name,
            "class_date": class_date
        }
    except Exception as e:
        print(f"[ERROR] AI 생성 실패 상세: {type(e).__name__}: {str(e)}")
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"AI 생성 실패: {str(e)}")

# ==================== AI 생기부 작성 API ====================

def generate_report_template(student, counselings, counseling_text, style='formal'):
    """스타일별 생기부 템플릿 생성"""
    name = student['name']
    code = student.get('code', '')
    birth = student.get('birth_date', '')
    interests = student.get('interests', '정보 없음')
    education = student.get('education', '')
    count = len(counselings)
    
    if style == 'formal':
        # 공식적 스타일
        report = f"""━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
【 학생 생활기록부 】
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

1. 기본 정보
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
• 성명: {name} ({code})
• 생년월일: {birth}
• 학력: {education}
• 관심분야: {interests}
• 상담 이력: 총 {count}회

2. 학생 특성 종합 분석
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
본 학생은 {count}회에 걸친 지속적인 상담을 통해 다음과 같은 특성을 보였습니다.

【 학업 태도 및 역량 】
자기주도적 학습 태도를 갖추고 있으며, {interests} 분야에 대한 높은 관심과 열정을 보이고 있습니다.
학습 과정에서 어려움에 직면했을 때에도 포기하지 않고 해결 방안을 모색하는 모습을 보였습니다.

【 성장 과정 및 발전 사항 】
상담 기간 동안 학생은 꾸준한 성장을 보여주었습니다. 초기에 비해 자기 인식 능력이 향상되었으며,
구체적인 목표 설정과 실행 계획 수립 능력이 발전하였습니다.

【 대인관계 및 의사소통 】
상담자와의 소통 과정에서 자신의 생각을 논리적으로 표현하는 능력이 우수하였으며,
타인의 조언을 경청하고 수용하는 긍정적인 태도를 보였습니다.

3. 상담 내역 및 주요 논의 사항
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
{counseling_text}

4. 종합 의견 및 향후 지도 방향
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
【 강점 및 잠재력 】
• 자기주도적 학습 능력 보유
• {interests} 분야에 대한 높은 관심과 동기
• 목표 지향적 사고방식
• 긍정적이고 적극적인 태도

【 개선 및 발전 방향 】
• 체계적인 학습 계획 수립 및 실행
• 시간 관리 능력 강화
• 자신감 향상을 위한 성공 경험 축적
• 지속적인 자기 성찰 및 피드백 수용

【 향후 지도 계획 】
1단계 (1-2개월): 기초 역량 강화 및 학습 습관 확립
2단계 (3-4개월): 심화 학습 및 실전 경험 축적
3단계 (5-6개월): 자기주도 학습 완성 및 목표 달성

5. 교사 종합 소견
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
{name} 학생은 충분한 잠재력과 강한 학습 의지를 갖춘 우수한 학생입니다.
상담 과정에서 보여준 진지한 태도와 자기 개선 노력은 매우 인상적이었습니다.
체계적인 지원과 지속적인 격려를 통해 {interests} 분야에서 탁월한 성과를 달성할 수 있을 것으로 
기대되며, 앞으로의 성장과 발전이 매우 기대됩니다.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
작성일: {datetime.now().strftime('%Y년 %m월 %d일')}
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""
    
    elif style == 'friendly':
        # 친근한 스타일
        report = f"""💙 {name} 학생 생활기록부 💙

안녕하세요! {name} 학생의 한 학기 동안의 성장 이야기를 정리해봤어요.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
✨ 학생 소개
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
• 이름: {name} ({code})
• 생년월일: {birth}
• 학력: {education}
• 좋아하는 것: {interests}
• 함께한 상담: {count}회

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
🌟 {name} 학생은 어떤 학생일까요?
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
{name} 학생은 {interests}에 대한 열정이 가득한 학생이에요!
{count}번의 상담을 통해 정말 많이 성장하는 모습을 볼 수 있었답니다.

【 멋진 점들 】
✓ 자기주도적으로 학습하는 습관이 있어요
✓ {interests} 분야에 대한 관심이 정말 높아요
✓ 어려운 일이 있어도 포기하지 않고 도전해요
✓ 선생님의 조언을 잘 듣고 실천하려고 노력해요

【 성장하는 모습 】
처음 만났을 때보다 자신감이 많이 생겼어요! 
자신에 대해 더 잘 이해하게 되었고, 구체적인 목표를 세우는 법도 배웠답니다.
무엇보다 꾸준히 노력하는 모습이 정말 멋있었어요. 👍

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
[DOC] 함께 나눈 이야기들
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
{counseling_text}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
🎯 앞으로의 계획
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
【 계속 키워나갈 점 】
• 자신감을 더 키워봐요!
• {interests} 실력을 꾸준히 향상시켜요
• 시간 관리를 잘해서 효율적으로 공부해요
• 작은 목표들을 하나씩 달성해나가요

【 함께 노력할 방법 】
1. 우선 기초를 탄탄히 다져요 (1-2개월)
2. 실력을 쌓으면서 자신감을 키워요 (3-4개월)
3. 스스로 잘할 수 있게 되도록 도와드릴게요 (5-6개월)

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
💝 선생님의 한마디
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
{name} 학생, 정말 열심히 노력하는 모습이 멋있어요!
{interests}에 대한 열정과 배우고자 하는 의지가 느껴져서 선생님도 기쁩니다.
앞으로도 지금처럼 꾸준히 노력하다 보면 분명 원하는 목표를 이룰 수 있을 거예요.
언제든지 도움이 필요하면 찾아오세요. 항상 응원하고 있어요! 화이팅! 💪✨

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
작성일: {datetime.now().strftime('%Y년 %m월 %d일')}
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""
    
    else:  # detailed
        # 상세 분석 스타일
        report = f"""╔════════════════════════════════════════════════════╗
║          학생 생활기록부 (상세 분석)              ║
╚════════════════════════════════════════════════════╝

1. 기본 정보 및 배경
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
【 학생 프로필 】
• 성명: {name}
• 학번: {code}
• 생년월일: {birth}
• 최종학력: {education}
• 관심분야: {interests}
• 상담 횟수: {count}회
• 기록 기간: {counselings[0]['consultation_date'] if counselings else '정보없음'} ~ {counselings[-1]['consultation_date'] if counselings else '정보없음'}

2. 학생 특성 심층 분석
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
【 인지적 특성 】
▪ 자기 인식 수준: 우수
  - 자신의 강점과 약점을 정확하게 파악하고 있음
  - 현실적인 목표 설정 능력 보유
  - 자기 성찰 능력이 발달되어 있음

▪ 학습 접근 방식: 자기주도적
  - 능동적인 학습 태도
  - 문제 해결을 위한 적극적 탐색
  - {interests} 분야에 대한 깊이 있는 관심

▪ 사고 패턴: 논리적이고 체계적
  - 상황을 분석하고 판단하는 능력 우수
  - 구조화된 사고방식
  - 단계적 접근 능력

【 정서적 특성 】
▪ 정서 안정성: 양호
  - 전반적으로 안정적인 정서 상태
  - 스트레스 상황에 대한 적응력 보유
  - 긍정적 마인드셋 유지

▪ 동기 수준: 높음
  - {interests}에 대한 내적 동기 강함
  - 성취 지향적 태도
  - 지속적인 자기 개발 의지

▪ 자신감: 발전 중
  - 기초적 자신감은 보유
  - 성공 경험 축적을 통한 향상 필요
  - 긍정적 자기 이미지 형성 과정

【 사회적 특성 】
▪ 의사소통 능력: 우수
  - 자신의 생각을 명확히 표현
  - 타인의 의견을 경청하는 태도
  - 건설적인 대화 참여

▪ 협력 태도: 긍정적
  - 상담자의 조언을 개방적으로 수용
  - 피드백에 대한 긍정적 반응
  - 지도에 협조적인 자세

3. 상담 내역 상세 분석
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
【 전체 상담 현황 】
{counseling_text}

【 상담 효과 분석 】
▪ 자기 인식 향상
  - 상담 초기 대비 자기 이해도 증가
  - 강점과 개선점에 대한 명확한 인식

▪ 목표 설정 능력 발전
  - 구체적이고 현실적인 목표 수립
  - 단계별 실행 계획 능력 향상

▪ 문제 해결 능력 개선
  - 어려움에 대한 적극적 대처
  - 다양한 해결 방안 모색 능력

4. 역량 평가 (5단계 척도)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
【 학업 관련 역량 】
• 자기주도 학습: ★★★★☆ (4/5)
• 문제 해결 능력: ★★★★☆ (4/5)
• 창의적 사고: ★★★☆☆ (3/5)
• 분석적 사고: ★★★★☆ (4/5)

【 개인 역량 】
• 자기 관리: ★★★☆☆ (3/5)
• 시간 관리: ★★★☆☆ (3/5)
• 목표 지향성: ★★★★☆ (4/5)
• 회복탄력성: ★★★★☆ (4/5)

【 사회적 역량 】
• 의사소통: ★★★★★ (5/5)
• 협업 능력: ★★★★☆ (4/5)
• 리더십: ★★★☆☆ (3/5)
• 공감 능력: ★★★★☆ (4/5)

5. SWOT 분석
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
【 Strengths (강점) 】
✓ 자기주도적 학습 태도
✓ {interests}에 대한 깊은 관심과 열정
✓ 논리적이고 체계적인 사고방식
✓ 우수한 의사소통 능력
✓ 긍정적이고 적극적인 자세

【 Weaknesses (약점) 】
△ 시간 관리 능력 개선 필요
△ 자신감 향상 필요
△ 체계적 학습 전략 수립 필요
△ 실행력 강화 필요

【 Opportunities (기회) 】
◆ {interests} 분야의 성장 가능성
◆ 체계적 지원 시스템 활용
◆ 멘토링 및 코칭 기회
◆ 프로젝트 참여를 통한 실전 경험

【 Threats (위협) 】
⚠ 과도한 목표로 인한 스트레스
⚠ 초기 어려움으로 인한 동기 저하 가능성
⚠ 시간 관리 실패 시 학습 효율 저하

6. 단계별 발전 계획 (상세)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
【 Phase 1: 기초 확립 단계 (1-2개월) 】
▸ 목표
  - {interests} 기본 개념 및 원리 완전 이해
  - 체계적 학습 습관 형성
  - 기초 실력 다지기

▸ 실행 방법
  - 주간 학습 계획표 작성 및 실행
  - 매일 30분 이상 집중 학습
  - 주 1회 진도 점검 및 피드백
  - 기초 개념 테스트 및 보완

▸ 평가 지표
  - 학습 계획 실행률 80% 이상
  - 기초 개념 이해도 테스트 80점 이상
  - 주간 학습 시간 15시간 이상

【 Phase 2: 실력 향상 단계 (3-4개월) 】
▸ 목표
  - 실전 적용 능력 배양
  - 문제 해결 능력 향상
  - 프로젝트 수행 경험 축적

▸ 실행 방법
  - 미니 프로젝트 수행 (주 1회)
  - 실전 문제 풀이 및 분석
  - 멘토링 세션 참여 (월 2회)
  - 학습 그룹 활동 참여

▸ 평가 지표
  - 프로젝트 완성도 평가
  - 문제 해결 속도 및 정확도
  - 자신감 수준 자체 평가

【 Phase 3: 전문성 심화 단계 (5-6개월) 】
▸ 목표
  - 독립적 학습 능력 완성
  - 심화 지식 및 기술 습득
  - 장기 목표 달성 준비

▸ 실행 방법
  - 자기주도 프로젝트 수행
  - 심화 학습 자료 탐구
  - 포트폴리오 구축
  - 분야별 전문가 네트워킹

▸ 평가 지표
  - 프로젝트 포트폴리오 3개 이상
  - 자기주도 학습률 90% 이상
  - 종합 평가 90점 이상

7. 지원 체계 및 모니터링
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
【 정기 지원 프로그램 】
▸ 주간 체크인 (매주)
  - 학습 진행 상황 확인
  - 어려움 및 질문 해결
  - 다음 주 계획 수립

▸ 월간 면담 (매월)
  - 월간 성과 리뷰
  - 심층 상담 및 코칭
  - 차월 목표 설정

▸ 분기 평가 (3개월마다)
  - 종합 성과 평가
  - SWOT 재분석
  - 장기 계획 조정

【 맞춤형 지원 서비스 】
▸ 학습 자료 제공
  - 수준별 학습 자료
  - 추천 도서 및 온라인 강의
  - 실습 프로젝트 자료

▸ 멘토링 연결
  - 분야별 전문가 멘토
  - 선배 학습자와의 교류
  - 스터디 그룹 운영

▸ 심리·정서 지원
  - 필요시 심리 상담
  - 동기 부여 세션
  - 스트레스 관리 지도

8. 종합 평가 및 권장사항
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
【 종합 평가 】
{name} 학생은 {interests} 분야에서 탁월한 잠재력을 보유하고 있습니다.
{count}회의 상담을 통해 확인된 학생의 자기주도적 학습 태도, 논리적 사고력, 
우수한 의사소통 능력은 향후 발전의 강력한 기반이 될 것입니다.

현재 시간 관리와 체계적 학습 전략 수립에서 개선이 필요하나, 
이는 체계적인 지도와 꾸준한 연습을 통해 충분히 향상될 수 있는 영역입니다.

학생이 보여준 높은 학습 동기와 개선 의지를 고려할 때, 
적절한 지원과 체계적인 지도가 제공된다면 목표한 성과를 달성할 수 있을 것으로 
확신합니다.

【 권장사항 】
1. 단계별 목표 달성에 집중
   - 한 번에 모든 것을 이루려 하지 말고 단계별 접근
   - 작은 성공 경험을 축적하여 자신감 향상

2. 체계적인 시간 관리
   - 학습 계획표 작성 및 준수
   - 우선순위에 따른 시간 배분
   - 규칙적인 생활 패턴 유지

3. 지속적인 자기 성찰
   - 일일 학습 일지 작성
   - 주간 회고 및 개선점 도출
   - 정기적인 자기 평가

4. 적극적인 도움 요청
   - 어려움 발생 시 즉시 상담
   - 멘토 및 동료와의 활발한 교류
   - 학습 커뮤니티 적극 활용

5. 균형 잡힌 생활
   - 학습과 휴식의 균형
   - 취미 및 여가 활동 병행
   - 신체적·정신적 건강 관리

【 기대 효과 】
위 계획대로 6개월간 체계적인 학습과 지도가 이루어진다면:
• {interests} 분야 기본 역량 완전 확립
• 자기주도적 학습 능력 완성
• 실전 프로젝트 수행 경험 축적
• 자신감 및 자기효능감 대폭 향상
• 장기적 성장을 위한 탄탄한 기반 마련

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
【 교사 최종 의견 】
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
{name} 학생과의 {count}회 상담을 통해 학생의 우수한 잠재력과 
강한 성장 의지를 확인할 수 있었습니다.

학생이 보여준 진지한 태도, 자기 성찰 능력, 그리고 지속적인 개선 노력은
교사로서 매우 인상 깊었으며, 앞으로의 발전이 매우 기대됩니다.

{interests} 분야에서의 깊은 관심과 열정을 바탕으로,
체계적인 학습과 꾸준한 노력을 통해 반드시 목표를 달성할 수 있을 것으로
확신합니다.

학생의 성공적인 성장을 위해 지속적으로 지원하고 격려하겠습니다.
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

작성일: {datetime.now().strftime('%Y년 %m월 %d일 %H:%M')}
작성자: 담당 교사
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""
    
    return report

@app.post("/api/ai/generate-report")
async def generate_ai_report(data: dict):
    """AI를 이용한 생기부 작성"""
    student_id = data.get('student_id')
    style = data.get('style', 'formal')  # formal, friendly, detailed
    custom_instructions = data.get('custom_instructions', '')
    
    if not student_id:
        raise HTTPException(status_code=400, detail="학생 ID가 필요합니다")
    
    # Groq API 키 확인 (없으면 무료 API 사용)
    groq_api_key = os.getenv('GROQ_API_KEY', '')
    
    conn = get_db_connection()
    try:
        cursor = conn.cursor(pymysql.cursors.DictCursor)
        
        # 학생 정보 조회
        cursor.execute("SELECT * FROM students WHERE id = %s", (student_id,))
        student = cursor.fetchone()
        
        if not student:
            raise HTTPException(status_code=404, detail="학생을 찾을 수 없습니다")
        
        # 상담 내역 조회
        cursor.execute("""
            SELECT consultation_date, consultation_type, main_topic, content
            FROM consultations
            WHERE student_id = %s
            ORDER BY consultation_date
        """, (student_id,))
        counselings = cursor.fetchall()
        
        if not counselings:
            raise HTTPException(status_code=400, detail="상담 기록이 없습니다")
        
        # 상담 내용 포맷팅
        counseling_text = ""
        for c in counselings:
            counseling_text += f"\n[{c['consultation_date']}] {c['consultation_type']} - {c['main_topic']}\n"
            counseling_text += f"내용: {c['content']}\n"
        
        system_prompt = """당신은 학생 생활기록부를 작성하는 전문 교사입니다.
학생의 상담 기록을 바탕으로 학생의 성장과 발달, 특성을 잘 드러내는 생활기록부를 작성해주세요.
생활기록부는 교육적이고 긍정적인 표현을 사용하며, 학생의 강점과 발전 가능성을 강조해야 합니다."""

        user_prompt = f"""
학생 정보:
- 이름: {student['name']}
- 생년월일: {student['birth_date']}
- 관심분야: {student['interests']}
- 학력: {student['education']}

상담 기록:
{counseling_text}

맞춤형 지시사항:
{custom_instructions if custom_instructions else '표준 생활기록부 형식으로 작성'}

위 정보를 바탕으로 학생의 생활기록부를 작성해주세요.
1. 학생의 전반적인 특성과 성장 과정을 요약해주세요 (200-300자)
2. 각 상담 내용을 통합하여 학생의 학업, 생활, 진로 측면의 발달사항을 기술해주세요 (500-800자)
"""
        
        # Groq API 사용 (무료, 빠른 추론)
        if groq_api_key:
            headers = {
                "Authorization": f"Bearer {groq_api_key}",
                "Content-Type": "application/json"
            }
            
            payload = {
                "model": "llama-3.1-70b-versatile",
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                "temperature": 0.7,
                "max_tokens": 2000
            }
            
            response = requests.post(
                "https://api.groq.com/openai/v1/chat/completions",
                headers=headers,
                json=payload,
                timeout=30
            )
            
            if response.status_code != 200:
                raise Exception(f"Groq API 오류: {response.text}")
            
            ai_report = response.json()['choices'][0]['message']['content']
        else:
            # API 키가 없으면 스타일별 생기부 템플릿 생성
            ai_report = generate_report_template(student, counselings, counseling_text, style)
        
        ai_report = ai_report
        
        return {
            "student_id": student_id,
            "student_name": student['name'],
            "report": ai_report,
            "counseling_count": len(counselings),
            "generated_at": datetime.now().isoformat()
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"AI 보고서 생성 실패: {str(e)}")
    finally:
        conn.close()

# ==================== 헬스 체크 ====================

@app.get("/api/status")
async def api_status():
    """API 상태 확인"""
    return {
        "message": "학급 관리 시스템 API",
        "version": "2.0",
        "status": "running"
    }

def generate_calculation_pdf(calculation_result: dict, course_code: str):
    """과정 계산 결과 PDF 생성"""
    try:
        # 한글 폰트 등록
        font_path = os.path.join(os.path.dirname(__file__), 'fonts', 'NanumGothic.ttf')
        if os.path.exists(font_path):
            pdfmetrics.registerFont(TTFont('NanumGothic', font_path))
            font_name = 'NanumGothic'
        else:
            font_name = 'Helvetica'
        
        # PDF 파일 경로 (크로스 플랫폼 지원)
        import tempfile
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        filename = f"course_calculation_{course_code}_{timestamp}.pdf"
        temp_dir = tempfile.gettempdir()
        pdf_path = os.path.join(temp_dir, filename)
        
        # PDF 문서 생성
        doc = SimpleDocTemplate(pdf_path, pagesize=A4)
        story = []
        
        # 스타일 정의
        styles = getSampleStyleSheet()
        title_style = ParagraphStyle(
            'CustomTitle',
            parent=styles['Heading1'],
            fontName=font_name,
            fontSize=18,
            alignment=TA_CENTER,
            spaceAfter=30
        )
        heading_style = ParagraphStyle(
            'CustomHeading',
            parent=styles['Heading2'],
            fontName=font_name,
            fontSize=14,
            spaceAfter=12
        )
        normal_style = ParagraphStyle(
            'CustomNormal',
            parent=styles['Normal'],
            fontName=font_name,
            fontSize=10,
            leading=16
        )
        
        # 제목
        story.append(Paragraph(f'과정 자동 계산 보고서', title_style))
        story.append(Paragraph(f'과정 코드: {course_code}', normal_style))
        story.append(Spacer(1, 20))
        
        # 1. 기본 정보
        story.append(Paragraph('1. 과정 기본 정보', heading_style))
        basic_data = [
            ['항목', '내용'],
            ['과정 시작일', calculation_result['start_date']],
            ['과정 종료일', calculation_result['final_end_date']],
            ['총 교육시간', f"{calculation_result['total_hours']}시간"],
            ['일일 수업시간', f"{calculation_result['daily_hours']}시간 (오전 {calculation_result['morning_hours']}h + 오후 {calculation_result['afternoon_hours']}h)"],
            ['주간 수업시간', f"{calculation_result['daily_hours'] * 5}시간 (월~금)"]
        ]
        basic_table = Table(basic_data, colWidths=[100, 300])
        basic_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.grey),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
            ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
            ('FONTNAME', (0, 0), (-1, -1), font_name),
            ('FONTSIZE', (0, 0), (-1, -1), 9),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 8),
            ('GRID', (0, 0), (-1, -1), 1, colors.black)
        ]))
        story.append(basic_table)
        story.append(Spacer(1, 20))
        
        # 2. 단계별 상세
        story.append(Paragraph('2. 교육 단계별 상세', heading_style))
        phase_data = [
            ['단계', '시간', '일수', '시작일', '종료일'],
            ['이론', f"{calculation_result['lecture_hours']}h", f"{calculation_result['lecture_days']}일", 
             calculation_result['start_date'], calculation_result['lecture_end_date']],
            ['프로젝트', f"{calculation_result['project_hours']}h", f"{calculation_result['project_days']}일",
             calculation_result['lecture_end_date'], calculation_result['project_end_date']],
            ['현장실습', f"{calculation_result['workship_hours']}h", f"{calculation_result['workship_days']}일",
             calculation_result['project_end_date'], calculation_result['workship_end_date']]
        ]
        phase_table = Table(phase_data, colWidths=[80, 70, 70, 90, 90])
        phase_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.grey),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
            ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
            ('FONTNAME', (0, 0), (-1, -1), font_name),
            ('FONTSIZE', (0, 0), (-1, -1), 9),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 8),
            ('GRID', (0, 0), (-1, -1), 1, colors.black)
        ]))
        story.append(phase_table)
        story.append(Spacer(1, 20))
        
        # 3. 일수 계산
        story.append(Paragraph('3. 교육일수 분석', heading_style))
        days_data = [
            ['구분', '일수'],
            ['총 기간', f"{calculation_result['total_days']}일"],
            ['근무일', f"{calculation_result['work_days']}일"],
            ['주말', f"{calculation_result['weekend_days']}일"],
            ['공휴일', f"{calculation_result['holiday_count']}일"],
            ['제외일 합계', f"{calculation_result['excluded_days']}일"]
        ]
        days_table = Table(days_data, colWidths=[200, 200])
        days_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.grey),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
            ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
            ('FONTNAME', (0, 0), (-1, -1), font_name),
            ('FONTSIZE', (0, 0), (-1, -1), 9),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 8),
            ('GRID', (0, 0), (-1, -1), 1, colors.black)
        ]))
        story.append(days_table)
        story.append(Spacer(1, 20))
        
        # 4. 공휴일 목록
        story.append(Paragraph('4. 과정 기간 내 공휴일', heading_style))
        story.append(Paragraph(f"공휴일: {calculation_result['holidays_formatted']}", normal_style))
        story.append(Spacer(1, 20))
        
        # 5. 계산 공식
        story.append(Paragraph('5. 계산 방식', heading_style))
        story.append(Paragraph('• 근무일 계산: 주말(토,일) 및 공휴일 제외', normal_style))
        story.append(Paragraph(f"• 일일 수업: {calculation_result['morning_hours']}시간(오전) + {calculation_result['afternoon_hours']}시간(오후) = {calculation_result['daily_hours']}시간", normal_style))
        story.append(Paragraph(f"• 필요 근무일 = 총 교육시간({calculation_result['total_hours']}h) ÷ 일일시간({calculation_result['daily_hours']}h) = {calculation_result['work_days']}일", normal_style))
        story.append(Spacer(1, 20))
        
        # 생성 정보
        story.append(Spacer(1, 30))
        story.append(Paragraph(f"생성일시: {datetime.now().strftime('%Y년 %m월 %d일 %H:%M:%S')}", normal_style))
        story.append(Paragraph("시스템: 바이오헬스교육관리시스템", normal_style))
        
        # PDF 빌드
        doc.build(story)
        
        # FTP 업로드
        try:
            upload_to_ftp(pdf_path, f"course_reports/{filename}")
            print(f"[OK] PDF FTP 업로드 완료: {filename}")
        except Exception as e:
            print(f"[WARN] PDF FTP 업로드 실패: {str(e)}")
        
        return pdf_path
        
    except Exception as e:
        import traceback
        print(f"PDF 생성 오류: {str(e)}")
        print(traceback.format_exc())
        raise

def generate_detailed_calculation(start_date, lecture_hours, project_hours, workship_hours,
                                  morning_hours, afternoon_hours, holidays_detail,
                                  lecture_end_date, project_end_date, workship_end_date,
                                  lecture_days, project_days, intern_days,
                                  weekend_days, holiday_count,
                                  lecture_weekdays=None):
    """상세 계산 과정 생성 - 오전/오후 분할 고려"""
    from datetime import timedelta
    from collections import defaultdict
    
    # 날짜 형식 헬퍼
    def format_date(d):
        weekdays = ['월', '화', '수', '목', '금', '토', '일']
        return f"{d.year}-{d.month:02d}-{d.day:02d} ({weekdays[d.weekday()]})"
    
    # 공휴일 set 생성
    holidays_set = set([h['date'] for h in holidays_detail]) if holidays_detail else set()
    
    def is_workday(date):
        return date.weekday() < 5 and date not in holidays_set
    
    # 상세 계산 로직 (오전/오후 분할 정확 처리, 날짜별 상세 표시)
    # allowed_weekdays: 수업 가능한 요일 목록 (1=월~5=금), None이면 모든 평일
    def calculate_stage_detail(stage_name, start, hours, morning_h, afternoon_h, start_at_afternoon=False, allowed_weekdays=None):
        current = start
        remaining = hours
        monthly_hours = defaultdict(lambda: {'days': 0, 'hours': 0, 'detail': []})
        all_dates = []  # 모든 날짜 기록

        # 첫날 오후부터 시작하는 경우
        first_day = True

        # 오전/오후 둘 다 0이면 빈 결과 즉시 반환
        if morning_h <= 0 and afternoon_h <= 0:
            return start, start, {}, []

        while remaining > 0:
            if not is_workday(current):
                current += timedelta(days=1)
                continue

            # 요일 제한이 있으면 해당 요일만 수업 배치
            if allowed_weekdays is not None:
                today_weekday = current.weekday() + 1  # 0(월)~4(금) → 1(월)~5(금)
                if today_weekday not in allowed_weekdays:
                    current += timedelta(days=1)
                    continue

            month_key = f"{current.year}년 {current.month}월"
            day_hours = 0
            time_str = ""

            # 첫날이고 오후부터 시작하는 경우
            if first_day and start_at_afternoon:
                # 오후만
                if remaining >= afternoon_h:
                    day_hours = afternoon_h
                    remaining -= afternoon_h
                    time_str = f"오후 {afternoon_h}시간"
                else:
                    day_hours = remaining
                    remaining = 0
                    time_str = f"오후 {day_hours}시간"
                first_day = False
            else:
                # 일반적인 경우: 오전 + 오후
                morning_done = 0
                afternoon_done = 0
                
                # 오전
                if remaining >= morning_h:
                    morning_done = morning_h
                    remaining -= morning_h
                elif remaining > 0:
                    morning_done = remaining
                    remaining = 0
                
                # 오후
                if remaining >= afternoon_h:
                    afternoon_done = afternoon_h
                    remaining -= afternoon_h
                elif remaining > 0:
                    afternoon_done = remaining
                    remaining = 0
                
                day_hours = morning_done + afternoon_done
                
                if morning_done > 0 and afternoon_done > 0:
                    time_str = f"오전 {morning_done}시간 + 오후 {afternoon_done}시간"
                elif morning_done > 0:
                    time_str = f"오전 {morning_done}시간"
                elif afternoon_done > 0:
                    time_str = f"오후 {afternoon_done}시간"
                
                first_day = False
            
            if day_hours > 0:
                monthly_hours[month_key]['hours'] += day_hours
                monthly_hours[month_key]['days'] += 1
                all_dates.append(f"    {format_date(current)}: {time_str} (누적: {hours - remaining}시간)")
            
            current += timedelta(days=1)
        
        # 종료일 찾기
        end_date = current - timedelta(days=1)
        while not is_workday(end_date):
            end_date -= timedelta(days=1)
        
        # 종료 시간 판단
        # 오후부터 시작한 경우: (hours - afternoon_h) % 8을 기준으로 계산
        # 그 외: hours % 8을 기준으로 계산
        if start_at_afternoon:
            # 첫날 오후(4시간) + N일 + 마지막날
            # 예: 220 = 4(첫날) + 208(26일) + 8(마지막날)
            remaining_after_first = hours - afternoon_h
            total_h = morning_h + afternoon_h
            last_day_hours = (remaining_after_first % total_h) if total_h > 0 else 0
        else:
            total_h = morning_h + afternoon_h
            last_day_hours = (hours % total_h) if total_h > 0 else 0
        
        if last_day_hours == 0:
            end_time = "18:00"
        elif last_day_hours <= morning_h:
            end_time = "13:00"
        else:
            end_time = "18:00"
        
        # 월별 요약 생성 (날짜별 상세 포함)
        summary = f"\n【{stage_name}: {hours}시간】\n"
        summary += f"  • 시작: {format_date(start)} {'14:00' if start_at_afternoon else '09:00'}\n"
        summary += f"  • 종료: {format_date(end_date)} {end_time}\n\n"
        
        summary += "  📅 일자별 상세:\n"
        for date_line in all_dates:
            summary += date_line + "\n"
        
        summary += "\n  [STAT] 월별 집계:\n"
        for month, data in sorted(monthly_hours.items()):
            summary += f"    {month}: 근무일 {data['days']}일, 수업시간 {data['hours']}시간\n"
        
        summary += f"\n  [OK] 총: {hours}시간 완료\n"
        
        # 다음 단계가 오후부터 시작하는지 판단
        # last_day_hours == 0이면 오전+오후 모두 사용 → 다음은 다음날 오전부터
        # last_day_hours <= morning_h이면 오전만 사용 → 다음은 같은 날 오후부터
        # last_day_hours > morning_h이면 오전+오후 모두 사용 → 다음은 다음날 오전부터
        ends_with_afternoon = (last_day_hours == 0 or last_day_hours > morning_h)
        
        return summary, end_date, ends_with_afternoon
    
    # 공휴일 정보 포맷팅
    holidays_str = ""
    if holidays_detail:
        for h in holidays_detail:
            holidays_str += f"\n  - {h['date'].year}-{h['date'].month:02d}-{h['date'].day:02d} ({h['weekday']}): {h['name']}"
    else:
        holidays_str += "\n  없음"
    
    # 각 단계별 상세 계산 (이론은 교과목 요일 배정 적용)
    lecture_detail, lecture_actual_end, lecture_ends_afternoon = calculate_stage_detail(
        "1단계: 이론", start_date, lecture_hours, morning_hours, afternoon_hours, False, allowed_weekdays=lecture_weekdays
    )
    
    # 프로젝트 시작일 결정
    if lecture_ends_afternoon:
        # 이론이 하루 전체를 사용했다면 다음날부터
        project_start = lecture_actual_end + timedelta(days=1)
        while not is_workday(project_start):
            project_start += timedelta(days=1)
        project_starts_afternoon = False
    else:
        # 이론이 오전만 사용했다면 같은 날 오후부터
        project_start = lecture_actual_end
        project_starts_afternoon = True
    
    project_detail, project_actual_end, project_ends_afternoon = calculate_stage_detail(
        "2단계: 프로젝트", project_start, project_hours, morning_hours, afternoon_hours, project_starts_afternoon
    )
    
    # 현장실습 시작일 결정
    if project_ends_afternoon:
        intern_start = project_actual_end + timedelta(days=1)
        while not is_workday(intern_start):
            intern_start += timedelta(days=1)
        intern_starts_afternoon = False
    else:
        intern_start = project_actual_end
        intern_starts_afternoon = True
    
    intern_detail, intern_actual_end, _ = calculate_stage_detail(
        "3단계: 현장실습", intern_start, workship_hours, morning_hours, afternoon_hours, intern_starts_afternoon
    )
    
    details = f"""
[STAT] 과정 자동 계산 상세 내역

📋 기본 정보
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
• 시작일: {format_date(start_date)}
• 일일 수업: 오전 {morning_hours}시간 + 오후 {afternoon_hours}시간 = {morning_hours + afternoon_hours}시간
• 주간 수업: {(morning_hours + afternoon_hours) * 5}시간 (월~금)

🎯 교육 단계별 시간
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
• 이론: {lecture_hours}시간
• 프로젝트: {project_hours}시간
• 현장실습: {workship_hours}시간
• 총: {lecture_hours + project_hours + workship_hours}시간

📅 공휴일 (과정 기간 내)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━{holidays_str}
• 총 공휴일: {holiday_count}일

🧮 단계별 계산 과정
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
{lecture_detail}
{project_detail}
{intern_detail}

[STAT] 최종 요약
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
• 교육 기간: {format_date(start_date)} ~ {format_date(intern_actual_end)}
• 총 교육시간: {lecture_hours + project_hours + workship_hours}시간
• 총 근무일: {lecture_days + project_days + intern_days}일
• 주말 제외: {weekend_days}일
• 공휴일 제외: {holiday_count}일
• 실제 경과일: {(intern_actual_end - start_date).days + 1}일
"""
    
    # 정확한 종료일 반환
    actual_dates = {
        'lecture_end': lecture_actual_end,
        'project_end': project_actual_end,
        'workship_end': intern_actual_end
    }
    
    return details, actual_dates
    return details

@app.post("/api/courses/calculate-dates")
async def calculate_course_dates(data: dict):
    """
    과정 날짜 자동 계산 (공휴일 제외)
    - start_date: 시작일
    - lecture_hours: 강의시간
    - project_hours: 프로젝트시간
    - workship_hours: 현장실습시간
    """
    from datetime import timedelta
    
    try:
        start_date_str = data.get('start_date')
        lecture_hours = int(data.get('lecture_hours', 0))
        project_hours = int(data.get('project_hours', 0))
        workship_hours = int(data.get('workship_hours', 0))
        daily_hours = int(data.get('daily_hours', 8))  # 일일 수업시간 (기본값 8시간)
        morning_hours = int(data.get('morning_hours', 4))
        afternoon_hours = int(data.get('afternoon_hours', 4))
        course_code = data.get('course_code')

        if not start_date_str:
            raise HTTPException(status_code=400, detail="시작일은 필수입니다.")

        if daily_hours <= 0:
            raise HTTPException(status_code=400, detail="일일 수업시간(오전+오후)은 0보다 커야 합니다.")

        start_date = datetime.strptime(start_date_str, '%Y-%m-%d').date()

        # 교과목 요일 배정 조회 (이론 단계에서 사용)
        lecture_weekdays = None  # None이면 모든 평일
        if course_code:
            conn_subj = get_db_connection()
            cursor_subj = conn_subj.cursor(pymysql.cursors.DictCursor)
            cursor_subj.execute("""
                SELECT DISTINCT s.day_of_week
                FROM course_subjects cs
                JOIN subjects s ON cs.subject_code = s.code
                WHERE cs.course_code = %s AND s.day_of_week IS NOT NULL AND s.day_of_week BETWEEN 1 AND 5
            """, (course_code,))
            weekday_rows = cursor_subj.fetchall()
            cursor_subj.close()
            conn_subj.close()
            if weekday_rows:
                lecture_weekdays = set(row['day_of_week'] for row in weekday_rows)

        # 시간을 일수로 변환 (입력된 일일 시간 기준)
        lecture_days = (lecture_hours + daily_hours - 1) // daily_hours  # 올림 처리
        project_days = (project_hours + daily_hours - 1) // daily_hours
        intern_days = (workship_hours + daily_hours - 1) // daily_hours

        # 공휴일 가져오기
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # 시작일로부터 1년간의 공휴일 조회
        end_year = start_date.year + 1
        cursor.execute("""
            SELECT holiday_date 
            FROM holidays 
            WHERE holiday_date >= %s 
            AND YEAR(holiday_date) BETWEEN %s AND %s
        """, (start_date_str, start_date.year, end_year))
        
        holidays_result = cursor.fetchall()
        holidays = set(row[0] for row in holidays_result)
        
        cursor.close()
        conn.close()
        
        # 근무일 계산 함수 (주말 및 공휴일 제외)
        # allowed_weekdays: 수업 가능한 요일 (1=월~5=금), None이면 모든 평일
        def add_business_days(start, days_to_add, allowed_weekdays=None):
            current = start
            added_days = 0

            while added_days < days_to_add:
                current += timedelta(days=1)
                if current.weekday() < 5 and current not in holidays:
                    if allowed_weekdays is None or (current.weekday() + 1) in allowed_weekdays:
                        added_days += 1

            return current

        # 각 단계별 종료일 계산 (이론은 요일 제한 적용)
        lecture_end_date = add_business_days(start_date, lecture_days, allowed_weekdays=lecture_weekdays)
        project_end_date = add_business_days(lecture_end_date, project_days)
        workship_end_date = add_business_days(project_end_date, intern_days)
        
        # 총 일수 계산 (실제 캘린더 일수)
        total_days = (workship_end_date - start_date).days
        
        # 과정 기간 내 공휴일 목록 생성 (상세)
        holidays_in_period = []
        holidays_detail = []  # 상세 정보 저장
        current = start_date
        
        # 공휴일 이름 조회를 위한 DB 연결
        conn_holiday = get_db_connection()
        cursor_holiday = conn_holiday.cursor(pymysql.cursors.DictCursor)
        
        while current <= workship_end_date:
            if current in holidays:
                # 공휴일 이름 조회
                cursor_holiday.execute(
                    "SELECT name FROM holidays WHERE holiday_date = %s",
                    (current,)
                )
                holiday_info = cursor_holiday.fetchone()
                holiday_name = holiday_info['name'] if holiday_info else '공휴일'
                
                holidays_in_period.append(current)
                holidays_detail.append({
                    'date': current,
                    'name': holiday_name,
                    'weekday': ['월', '화', '수', '목', '금', '토', '일'][current.weekday()]
                })
            current += timedelta(days=1)
        
        cursor_holiday.close()
        conn_holiday.close()
        
        # 공휴일을 그룹화 (연속된 날짜는 범위로 표시)
        holiday_strings = []
        if holidays_in_period:
            holidays_in_period.sort()
            i = 0
            while i < len(holidays_in_period):
                start_holiday = holidays_in_period[i]
                end_holiday = start_holiday
                
                # 연속된 날짜 찾기
                j = i + 1
                while j < len(holidays_in_period) and (holidays_in_period[j] - holidays_in_period[j-1]).days == 1:
                    end_holiday = holidays_in_period[j]
                    j += 1
                
                # 포맷팅 (연속이면 범위로, 아니면 단일 날짜로)
                if start_holiday == end_holiday:
                    holiday_strings.append(start_holiday.strftime('%-m/%-d'))
                else:
                    holiday_strings.append(f"{start_holiday.strftime('%-m/%-d')}~{end_holiday.strftime('%-m/%-d')}")
                
                i = j
        
        # 주말 일수 계산
        weekend_days = 0
        current = start_date
        while current <= workship_end_date:
            if current.weekday() >= 5:  # 토요일(5), 일요일(6)
                weekend_days += 1
            current += timedelta(days=1)
        
        # 제외 일수 (주말 + 공휴일)
        excluded_days = weekend_days + len(holidays_in_period)
        
        # 상세 계산 과정 생성 (정확한 종료일 포함)
        calculation_details, actual_dates = generate_detailed_calculation(
            start_date, lecture_hours, project_hours, workship_hours,
            morning_hours, afternoon_hours, holidays_detail,
            lecture_end_date, project_end_date, workship_end_date,
            lecture_days, project_days, intern_days,
            weekend_days, len(holidays_in_period),
            lecture_weekdays=lecture_weekdays
        )
        
        # 정확한 종료일 사용
        lecture_end_date = actual_dates['lecture_end']
        project_end_date = actual_dates['project_end']
        workship_end_date = actual_dates['workship_end']
        
        result = {
            "start_date": start_date_str,
            "lecture_end_date": lecture_end_date.strftime('%Y-%m-%d'),
            "project_end_date": project_end_date.strftime('%Y-%m-%d'),
            "workship_end_date": workship_end_date.strftime('%Y-%m-%d'),
            "final_end_date": workship_end_date.strftime('%Y-%m-%d'),
            "total_days": (workship_end_date - start_date).days,
            "lecture_days": lecture_days,
            "project_days": project_days,
            "workship_days": intern_days,
            "work_days": lecture_days + project_days + intern_days,
            "weekend_days": weekend_days,
            "holiday_count": len(holidays_in_period),
            "excluded_days": excluded_days,
            "holidays_formatted": ", ".join(holiday_strings) if holiday_strings else "없음",
            "holidays_detail": holidays_detail,
            "lecture_hours": lecture_hours,
            "project_hours": project_hours,
            "workship_hours": workship_hours,
            "total_hours": lecture_hours + project_hours + workship_hours,
            "morning_hours": morning_hours,
            "afternoon_hours": afternoon_hours,
            "daily_hours": daily_hours,
            "course_code": data.get('course_code', ''),
            "calculation_details": calculation_details
        }
        
        # course_code가 있으면 비고란에 상세 계산 과정 저장
        course_code = data.get('course_code')
        if course_code:
            try:
                import re
                conn_update = get_db_connection()
                cursor_update = conn_update.cursor()
                
                # 이모지 및 4바이트 UTF-8 문자 제거 (utf8mb4 미지원 DB 컬럼 대응)
                def remove_emoji(text):
                    # 4바이트 UTF-8 문자 모두 제거 (이모지 포함)
                    # UTF-8에서 4바이트는 \xF0-\xF7로 시작
                    try:
                        # 각 문자를 검사하여 4바이트 문자 제거
                        return ''.join(c for c in text if len(c.encode('utf-8')) < 4)
                    except:
                        return text
                
                notes_text = remove_emoji(calculation_details)
                
                # 과정의 비고란(notes)에 상세 계산 과정 저장
                cursor_update.execute("""
                    UPDATE courses 
                    SET notes = %s
                    WHERE code = %s
                """, (notes_text, course_code))
                conn_update.commit()
                cursor_update.close()
                conn_update.close()
                
                result['notes_updated'] = True
            except Exception as e:
                print(f"비고란 업데이트 실패: {str(e)}")
                import traceback
                print(traceback.format_exc())
                result['notes_updated'] = False
                result['notes_error'] = str(e)
        
        # 자동 저장 옵션이 있으면 시간표도 생성
        if data.get('auto_save_timetable', False):
            if course_code:
                # 시간표 자동 생성 호출
                try:
                    # 과정에 배정된 교과목 자동 조회
                    conn_temp = get_db_connection()
                    cursor_temp = conn_temp.cursor(pymysql.cursors.DictCursor)
                    cursor_temp.execute("""
                        SELECT subject_code FROM course_subjects 
                        WHERE course_code = %s
                    """, (course_code,))
                    subject_codes = [row['subject_code'] for row in cursor_temp.fetchall()]
                    conn_temp.close()
                    
                    timetable_data = {
                        'course_code': course_code,
                        'start_date': start_date_str,
                        'lecture_hours': lecture_hours,
                        'project_hours': project_hours,
                        'workship_hours': workship_hours,
                        'morning_hours': morning_hours,
                        'afternoon_hours': afternoon_hours,
                        'subject_codes': subject_codes
                    }
                    # 시간표 생성 로직 호출 (동일 함수 재사용)
                    from fastapi.responses import Response
                    timetable_result = await auto_generate_timetables(timetable_data)
                    result['timetable_generated'] = True
                    result['timetable_count'] = timetable_result.get('generated_count', 0)
                except Exception as e:
                    print(f"시간표 자동 생성 실패: {str(e)}")
                    result['timetable_generated'] = False
                    result['timetable_error'] = str(e)
        
        # PDF 생성 옵션이 있으면 PDF도 생성
        if data.get('generate_pdf', False):
            try:
                pdf_path = generate_calculation_pdf(result, data.get('course_code', 'COURSE'))
                result['pdf_generated'] = True
                result['pdf_path'] = pdf_path
            except Exception as e:
                print(f"PDF 생성 실패: {str(e)}")
                result['pdf_generated'] = False
                result['pdf_error'] = str(e)
        
        return result
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"날짜 계산 실패: {str(e)}")

@app.post("/api/ai/generate-training-logs")
async def generate_ai_training_logs(data: dict):
    """AI 훈련일지 자동 생성"""
    timetable_ids = data.get('timetable_ids', [])
    prompt_guide = data.get('prompt', '')
    delete_before_create = data.get('delete_before_create', False)
    
    if not timetable_ids:
        raise HTTPException(status_code=400, detail="시간표 ID가 필요합니다")
    
    conn = get_db_connection()
    try:
        cursor = conn.cursor(pymysql.cursors.DictCursor)
        success_count = 0
        failed_count = 0
        
        for timetable_id in timetable_ids:
            try:
                # 시간표 정보 가져오기
                cursor.execute("""
                    SELECT t.*, 
                           c.name as course_name,
                           s.name as subject_name,
                           i.name as instructor_name
                    FROM timetables t
                    LEFT JOIN courses c ON t.course_code = c.code
                    LEFT JOIN subjects s ON t.subject_code = s.code
                    LEFT JOIN instructors i ON t.instructor_code = i.code
                    WHERE t.id = %s
                """, (timetable_id,))
                
                timetable = cursor.fetchone()
                if not timetable:
                    failed_count += 1
                    continue
                
                # 삭제 후 작성 옵션이 활성화된 경우, 기존 훈련일지 삭제
                if delete_before_create:
                    cursor.execute("""
                        DELETE FROM training_logs WHERE timetable_id = %s
                    """, (timetable_id,))
                
                # AI로 훈련일지 내용 생성 - 타입별 템플릿
                timetable_type = timetable.get('type', 'lecture')
                
                if timetable_type == 'project':
                    # 프로젝트 타입 템플릿
                    content = f"""[{timetable['class_date']}] 프로젝트 활동

▶ 프로젝트 정보
- 활동: 프로젝트
- 지도강사: {timetable['instructor_name'] or timetable['instructor_code']}
- 날짜: {timetable['class_date']}

▶ 금일 목표
• 프로젝트 핵심 기능 구현 및 개발 진행
• 팀원 간 역할 분담 및 협업 강화
• 프로젝트 일정 대비 진행 상황 점검

▶ 주요 진행 내용
• 프로젝트 핵심 기능 개발 및 구현
• 데이터 구조 설계 및 적용
• UI/UX 개선 작업 진행
• 코드 리뷰 및 품질 개선

▶ 팀별 활동
• 역할별 작업 진행 상황 공유
• 통합 작업 및 충돌 해결
• 상호 코드 리뷰 및 피드백

▶ 문제 해결 및 개선사항
• 발생한 기술적 이슈 해결
• 일정 지연 요인 파악 및 대응
• 효율적 개발 방법론 적용

▶ 프로젝트 목표 달성도
• 계획 대비 진행률: 약 65% (중반 단계)
• 주요 기능 구현 완료율: 70%
• 팀 협업 효율성: 우수

▶ 특이사항
{prompt_guide if prompt_guide else '특별한 사항 없음'}

▶ 향후 계획
• 다음 단계: 프로젝트 고도화 및 테스트
• 남은 기간: 프로젝트 완성 및 발표 준비
"""
                
                elif timetable_type == 'practice':
                    # 현장실습 타입 템플릿
                    content = f"""[{timetable['class_date']}] 현장실습 활동

▶ 실습 정보
- 활동: 현장실습
- 지도강사: {timetable['instructor_name'] or timetable['instructor_code']}
- 날짜: {timetable['class_date']}

▶ 금일 목표
• 현장 실무 업무 수행 및 학습
• 기업 멘토 지도 하에 실습 진행
• 실무 프로세스 이해 및 적용

▶ 주요 실습 내용
• 현장 업무 직접 수행 및 경험
• 실무 도구 및 시스템 활용 학습
• 업무 프로세스 및 워크플로우 습득
• 팀 협업 및 커뮤니케이션 실습

▶ 현장 업무 수행
• 실제 프로젝트 참여 및 기여
• 업무 요구사항 분석 및 구현
• 품질 관리 및 테스트 수행
• 문서 작성 및 보고서 제출

▶ 멘토링 및 피드백
• 기업 멘토의 실무 지도 및 조언
• 작업 결과물에 대한 구체적 피드백
• 개선 방향 및 학습 가이드 제공
• 진로 상담 및 커리어 조언

▶ 학습 성과 및 역량
• 실무 경험 축적 및 역량 강화
• 현장 업무 수행 능력 향상
• 협업 및 문제 해결 역량 강화
• 직무 역량 및 전문성 성장

▶ 특이사항
{prompt_guide if prompt_guide else '특별한 사항 없음'}

▶ 향후 계획
• 현장 실습 지속 및 심화
• 실무 프로젝트 완성도 제고
"""
                
                else:  # lecture (교과목)
                    # 교과목 타입 템플릿 (기존 유지)
                    content = f"""[{timetable['class_date']}] {timetable['subject_name'] or '과목'} 수업

▶ 교육 내용
- 과목: {timetable['subject_name'] or timetable['subject_code']}
- 강사: {timetable['instructor_name'] or timetable['instructor_code']}
- 수업 유형: 교과

▶ 학습 목표
• {timetable['subject_name'] or '과목'}의 핵심 개념 이해
• 실무 활용 방법 습득
• 관련 기술 실습 능력 향상

▶ 주요 학습 내용
• {timetable['subject_name'] or '과목'} 이론 강의 진행
• 기본 원리 및 핵심 개념 설명
• 실제 활용 사례 분석
• 단계별 실습 프로젝트 수행

▶ 실습 활동
• {timetable['subject_name'] or '과목'} 기반 프로젝트 실습
• 개별/팀별 과제 수행
• 문제 해결 및 피드백

▶ 학습 성과
• {timetable['subject_name'] or '과목'}에 대한 이해도 향상
• 실무 적용 능력 강화
• 과제 완료율 우수

▶ 특이사항
{prompt_guide if prompt_guide else '특별한 사항 없음'}

▶ 다음 시간 계획
• {timetable['subject_name'] or '과목'} 심화 학습 진행 예정
"""
                
                # 훈련일지 생성
                cursor.execute("""
                    INSERT INTO training_logs (timetable_id, content, created_at)
                    VALUES (%s, %s, NOW())
                """, (timetable_id, content))
                
                success_count += 1
                
            except Exception as e:
                print(f"훈련일지 생성 실패 (timetable_id: {timetable_id}): {str(e)}")
                failed_count += 1
                continue
        
        conn.commit()
        
        return {
            "success_count": success_count,
            "failed_count": failed_count,
            "total_count": len(timetable_ids)
        }
        
    except Exception as e:
        conn.rollback()
        raise HTTPException(status_code=500, detail=f"AI 훈련일지 생성 실패: {str(e)}")
    finally:
        conn.close()

@app.post("/api/counselings/ai-generate")
async def generate_ai_counseling(data: dict):
    """AI 상담일지 자동 생성"""
    student_code = data.get('student_code')
    course_code = data.get('course_code')
    custom_prompt = data.get('custom_prompt', '')
    
    if not student_code:
        raise HTTPException(status_code=400, detail="학생 코드가 필요합니다")
    
    conn = get_db_connection()
    try:
        cursor = conn.cursor(pymysql.cursors.DictCursor)
        
        # 학생 정보 가져오기 (student_id 필요)
        cursor.execute("""
            SELECT s.*, c.name as course_name
            FROM students s
            LEFT JOIN courses c ON s.course_code = c.code
            WHERE s.code = %s
        """, (student_code,))
        
        student = cursor.fetchone()
        if not student:
            raise HTTPException(status_code=404, detail="학생을 찾을 수 없습니다")
        
        student_id = student['id']
        
        # 기존 상담 횟수 확인 (consultations 테이블 사용)
        cursor.execute("""
            SELECT COUNT(*) as count
            FROM consultations
            WHERE student_id = %s
        """, (student_id,))
        
        result = cursor.fetchone()
        counseling_count = result['count'] if result else 0
        
        # AI로 상담일지 내용 생성
        content = f"""[상담 {counseling_count + 1}회차] {student['name']} 학생 상담

▶ 학생 정보
- 이름: {student['name']}
- 학생 코드: {student['code']}
- 과정: {student.get('course_name', '')}
- 연락처: {student.get('phone', '')}

▶ 상담 내용
{student['name']} 학생과 학업 진행 상황 및 향후 계획에 대해 상담을 진행하였습니다.

▶ 학습 태도 및 참여도
학생의 수업 참여도와 학습 태도가 양호한 편이며, 과제 수행 능력도 우수합니다.

▶ 진로 및 목표
현재 진행 중인 과정에 대한 이해도가 높으며, 명확한 진로 목표를 가지고 있습니다.

▶ 특이사항 및 요청사항
{custom_prompt if custom_prompt else '특별한 사항 없음'}

▶ 향후 지도 방향
- 현재의 학습 태도를 유지하도록 격려
- 추가적인 학습 자료 제공 및 심화 학습 기회 제공
- 정기적인 진도 체크 및 피드백 제공

▶ 다음 상담 계획
약 2-3주 후 학습 진도를 확인하고 추가 상담을 진행할 예정입니다.
"""
        
        # 상담일지 생성 (consultations 테이블에 student_id 사용)
        cursor.execute("""
            INSERT INTO consultations 
            (student_id, consultation_date, consultation_type, main_topic, content, status, created_at)
            VALUES (%s, CURDATE(), '정기', 'AI 자동 생성', %s, '완료', NOW())
        """, (student_id, content))
        
        conn.commit()
        
        return {
            "message": "상담일지가 생성되었습니다",
            "student_code": student_code,
            "student_name": student['name']
        }
        
    except Exception as e:
        conn.rollback()
        raise HTTPException(status_code=500, detail=f"AI 상담일지 생성 실패: {str(e)}")
    finally:
        conn.close()

@app.post("/api/ai/replace-timetable")
async def replace_timetable(data: dict):
    """AI 시간표 대체: 시간표 날짜 변경 및 원래 날짜를 공휴일로 등록"""
    course_code = data.get('course_code')
    original_date = data.get('original_date')
    replacement_date = data.get('replacement_date')
    
    if not course_code or not original_date or not replacement_date:
        raise HTTPException(status_code=400, detail="모든 필드가 필요합니다")
    
    if original_date == replacement_date:
        raise HTTPException(status_code=400, detail="원래 날짜와 대체 날짜가 같습니다")
    
    conn = get_db_connection()
    try:
        cursor = conn.cursor(pymysql.cursors.DictCursor)
        
        # 1. 해당 날짜의 시간표 개수 확인
        cursor.execute("""
            SELECT COUNT(*) as count
            FROM timetables
            WHERE course_code = %s AND class_date = %s
        """, (course_code, original_date))
        count_result = cursor.fetchone()
        timetables_count = count_result['count']
        
        if timetables_count == 0:
            raise HTTPException(status_code=404, detail="해당 날짜에 시간표가 없습니다")
        
        # 2. 시간표 날짜 업데이트
        cursor.execute("""
            UPDATE timetables
            SET class_date = %s
            WHERE course_code = %s AND class_date = %s
        """, (replacement_date, course_code, original_date))
        
        updated_count = cursor.rowcount
        
        # 3. 원래 날짜를 공휴일로 등록
        # 공휴일명: "공강/대체(대체날짜)"
        holiday_name = f"공강/대체({replacement_date})"
        
        # 기존 공휴일이 있는지 확인
        cursor.execute("""
            SELECT id FROM holidays
            WHERE holiday_date = %s
        """, (original_date,))
        existing_holiday = cursor.fetchone()
        
        if existing_holiday:
            # 기존 공휴일 업데이트
            cursor.execute("""
                UPDATE holidays
                SET name = %s
                WHERE holiday_date = %s
            """, (holiday_name, original_date))
        else:
            # 새 공휴일 등록
            cursor.execute("""
                INSERT INTO holidays (holiday_date, name, is_legal)
                VALUES (%s, %s, 0)
            """, (original_date, holiday_name))
        
        conn.commit()
        
        return {
            "success": True,
            "timetables_updated": updated_count,
            "original_date": original_date,
            "replacement_date": replacement_date,
            "holiday_created": {
                "date": original_date,
                "name": holiday_name,
                "category": "일반"
            }
        }
        
    except HTTPException as he:
        conn.rollback()
        raise he
    except Exception as e:
        conn.rollback()
        import traceback
        error_detail = f"{type(e).__name__}: {str(e)}"
        print(f"[ERROR] 시간표 대체 실패: {error_detail}")
        print(traceback.format_exc())
        raise HTTPException(status_code=500, detail=f"시간표 대체 실패: {error_detail}")
    finally:
        if conn:
            conn.close()

@app.post("/api/upload-image")
async def upload_image(
    file: UploadFile = File(...),
    category: str = Query(..., description="guidance, train, student, teacher, team")
):
    """
    이미지 파일을 FTP 서버에 업로드
    
    Args:
        file: 업로드할 이미지 파일
        category: 저장 카테고리 (guidance=상담일지, train=훈련일지, student=학생, teacher=강사, team=팀)
    
    Returns:
        업로드된 파일의 URL
    """
    try:
        # 파일 확장자 검증 (이미지 + PDF)
        allowed_extensions = [
            '.jpg', '.jpeg', '.png', '.gif', '.bmp', '.webp',  # 이미지
            '.pdf',  # PDF
            '.ppt', '.pptx',  # PowerPoint
            '.xls', '.xlsx',  # Excel
            '.doc', '.docx',  # Word
            '.txt',  # 텍스트
            '.hwp'  # 한글
        ]
        file_ext = os.path.splitext(file.filename)[1].lower()
        
        if file_ext not in allowed_extensions:
            raise HTTPException(
                status_code=400,
                detail=f"허용되지 않는 파일 형식입니다. 허용 형식: {', '.join(allowed_extensions)}"
            )
        
        # 파일 크기 체크 (100MB 제한)
        contents = await file.read()
        file_size = len(contents)
        await file.seek(0)  # 파일 처음으로 되돌림
        
        if file_size > 100 * 1024 * 1024:
            raise HTTPException(status_code=413, detail=f"파일 크기는 100MB를 초과할 수 없습니다 (현재: {file_size / 1024 / 1024:.2f}MB)")
        
        # 원본 파일명 보존 (타임스탬프 접두어로 중복 방지)
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        unique_id = str(uuid.uuid4())[:8]
        
        # 원본 파일명에서 확장자 제거
        original_name = os.path.splitext(file.filename)[0]
        
        # 안전한 파일명으로 변환 (ASCII 문자만 허용)
        # 한글/특수문자는 언더스코어로, 영문/숫자/-/_/.만 유지
        safe_name = ""
        for c in original_name:
            if c.isascii() and (c.isalnum() or c in ('-', '_', '.')):
                safe_name += c
            else:
                safe_name += '_'
        
        # 연속된 언더스코어 제거
        import re
        safe_name = re.sub(r'_+', '_', safe_name)
        safe_name = safe_name.strip('_')
        
        # 너무 긴 파일명은 자르기
        if len(safe_name) > 50:
            safe_name = safe_name[:50]
        
        # 파일명이 비어있으면 file로 대체
        if not safe_name:
            safe_name = "file"
        
        new_filename = f"{timestamp}_{unique_id}_{safe_name}{file_ext}"
        
        # 스트리밍 FTP 업로드 (메모리 절약)
        file_url = await upload_stream_to_ftp(file, new_filename, category)
        
        return {
            "success": True,
            "url": file_url,
            "filename": new_filename,
            "original_filename": file.filename,  # 원본 파일명 추가
            "size": file_size
        }
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"이미지 업로드 실패: {str(e)}")

@app.post("/api/upload-image-base64")
async def upload_image_base64(data: dict):
    """
    Base64 인코딩된 이미지를 FTP 서버에 업로드 (모바일 카메라 촬영용)
    
    Args:
        data: {
            "image": "data:image/jpeg;base64,...",
            "category": "guidance|train|student|teacher"
        }
    
    Returns:
        업로드된 파일의 URL
    """
    try:
        image_data = data.get('image')
        category = data.get('category')
        
        if not image_data or not category:
            raise HTTPException(status_code=400, detail="image와 category는 필수입니다")
        
        # Base64 데이터 파싱
        if ',' in image_data:
            header, base64_data = image_data.split(',', 1)
            # 이미지 타입 추출 (data:image/jpeg;base64 -> jpeg)
            if 'image/' in header:
                image_type = header.split('image/')[1].split(';')[0]
                file_ext = f'.{image_type}'
            else:
                file_ext = '.jpg'
        else:
            base64_data = image_data
            file_ext = '.jpg'
        
        # Base64 디코딩
        file_data = base64.b64decode(base64_data)
        
        # 파일 크기 체크 (100MB 제한 - 413 에러 방지)
        if len(file_data) > 100 * 1024 * 1024:
            raise HTTPException(status_code=413, detail=f"파일 크기는 100MB를 초과할 수 없습니다 (현재: {len(file_data) / 1024 / 1024:.2f}MB)")
        
        # 고유한 파일명 생성
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        unique_id = str(uuid.uuid4())[:8]
        new_filename = f"{timestamp}_{unique_id}{file_ext}"
        
        # FTP 업로드
        file_url = upload_to_ftp(file_data, new_filename, category)
        
        return {
            "success": True,
            "url": file_url,
            "filename": new_filename,
            "size": len(file_data)
        }
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"이미지 업로드 실패: {str(e)}")

@app.get("/api/download-image")
async def download_image(url: str = Query(..., description="FTP URL to download")):
    """
    FTP 서버의 이미지를 다운로드하는 프록시 API
    
    Args:
        url: FTP URL (예: ftp://bitnmeta2.synology.me:2121/homes/ha/camFTP/BH2025/guidance/file.jpg)
    
    Returns:
        이미지 파일
    """
    try:
        # FTP URL 파싱
        if not url.startswith('ftp://'):
            raise HTTPException(status_code=400, detail="FTP URL이 아닙니다")
        
        # URL에서 정보 추출
        # ftp://bitnmeta2.synology.me:2121/homes/ha/camFTP/BH2025/guidance/file.jpg
        url_parts = url.replace('ftp://', '').split('/', 1)
        host_port = url_parts[0]
        file_path = url_parts[1] if len(url_parts) > 1 else ''
        
        # 호스트와 포트 분리
        if ':' in host_port:
            host, port = host_port.split(':')
            port = int(port)
        else:
            host = host_port
            port = 21
        
        # 파일명 추출
        filename = file_path.split('/')[-1]
        
        # FTP 연결 및 다운로드
        ftp = FTP()
        ftp.encoding = 'utf-8'  # 한글 파일명 지원
        ftp.connect(FTP_CONFIG['host'], FTP_CONFIG['port'])
        ftp.login(FTP_CONFIG['user'], FTP_CONFIG['passwd'])
        
        # 파일 다운로드
        file_data = io.BytesIO()
        ftp.retrbinary(f'RETR /{file_path}', file_data.write)
        ftp.quit()
        
        # 파일 데이터 가져오기
        file_data.seek(0)
        file_bytes = file_data.read()
        
        # 임시 파일로 저장 (크로스 플랫폼 지원)
        import tempfile
        temp_dir = tempfile.gettempdir()
        temp_filename = os.path.join(temp_dir, filename)
        with open(temp_filename, 'wb') as f:
            f.write(file_bytes)
        
        # 파일 확장자로 MIME 타입 결정
        ext = os.path.splitext(filename)[1].lower()
        media_type_map = {
            '.jpg': 'image/jpeg',
            '.jpeg': 'image/jpeg',
            '.png': 'image/png',
            '.gif': 'image/gif',
            '.bmp': 'image/bmp',
            '.webp': 'image/webp',
            '.pdf': 'application/pdf',
            '.ppt': 'application/vnd.ms-powerpoint',
            '.pptx': 'application/vnd.openxmlformats-officedocument.presentationml.presentation',
            '.xls': 'application/vnd.ms-excel',
            '.xlsx': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
            '.doc': 'application/msword',
            '.docx': 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
            '.txt': 'text/plain',
            '.hwp': 'application/x-hwp'
        }
        media_type = media_type_map.get(ext, 'application/octet-stream')
        
        # PDF와 이미지는 inline으로 보여주고, 나머지는 다운로드
        inline_types = ['.pdf', '.jpg', '.jpeg', '.png', '.gif', '.bmp', '.webp', '.txt']
        disposition_type = 'inline' if ext in inline_types else 'attachment'
        
        return FileResponse(
            temp_filename,
            media_type=media_type,
            filename=filename,
            headers={
                'Content-Disposition': f'{disposition_type}; filename="{filename}"'
            }
        )
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"이미지 다운로드 실패: {str(e)}")

@app.get("/api/thumbnail")
@app.head("/api/thumbnail")
async def get_thumbnail(url: str = Query(..., description="FTP URL")):
    """
    이미지 썸네일 제공 API
    
    Args:
        url: FTP URL
    
    Returns:
        썸네일 이미지 (있으면 제공, 없으면 FTP에서 다운로드하여 생성)
    """
    try:
        # URL에서 파일명 추출
        filename = url.split('/')[-1]
        thumb_filename = f"thumb_{filename}"
        # 크로스 플랫폼 지원 경로
        backend_dir = os.path.dirname(os.path.abspath(__file__))
        thumbnails_dir = os.path.join(backend_dir, 'thumbnails')
        thumb_path = os.path.join(thumbnails_dir, thumb_filename)
        
        # 썸네일 디렉토리 생성 (없으면)
        os.makedirs(thumbnails_dir, exist_ok=True)
        
        # 썸네일이 있으면 반환
        if os.path.exists(thumb_path):
            return FileResponse(
                thumb_path,
                media_type='image/jpeg',
                headers={
                    'Cache-Control': 'public, max-age=86400'  # 1일 캐싱
                }
            )
        
        # 썸네일이 없으면 FTP에서 원본 다운로드하여 생성
        try:
            # FTP URL 파싱
            url_parts = url.replace('ftp://', '').split('/', 1)
            file_path = url_parts[1] if len(url_parts) > 1 else ''
            
            # FTP 연결 및 다운로드
            ftp = FTP()
            ftp.encoding = 'utf-8'  # 한글 파일명 지원
            ftp.connect(FTP_CONFIG['host'], FTP_CONFIG['port'])
            ftp.login(FTP_CONFIG['user'], FTP_CONFIG['passwd'])
            
            # 파일 다운로드
            file_data = io.BytesIO()
            ftp.retrbinary(f'RETR /{file_path}', file_data.write)
            ftp.quit()
            
            # 파일 데이터 가져오기
            file_data.seek(0)
            file_bytes = file_data.read()
            
            # 썸네일 생성
            thumb_result = create_thumbnail(file_bytes, filename)
            
            if thumb_result and os.path.exists(thumb_path):
                return FileResponse(
                    thumb_path,
                    media_type='image/jpeg',
                    headers={
                        'Cache-Control': 'public, max-age=86400'
                    }
                )
            else:
                # 썸네일 생성 실패
                raise HTTPException(status_code=404, detail="썸네일 생성 실패")
                
        except Exception as e:
            print(f"FTP 다운로드 및 썸네일 생성 실패: {str(e)}")
            raise HTTPException(status_code=404, detail="썸네일을 생성할 수 없습니다")
            
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"썸네일 조회 실패: {str(e)}")

@app.get("/health")
async def health_check():
    """헬스 체크"""
    try:
        conn = get_db_connection()
        conn.close()
        return {"status": "healthy", "database": "connected"}
    except Exception as e:
        return {"status": "unhealthy", "error": str(e)}

# ==================== 인증 API ====================

@app.post("/api/auth/login")
async def login(credentials: dict):
    """
    통합 로그인 API
    - 이름으로 강사 또는 학생 자동 구분 로그인
    - 기본 비밀번호: kdt2025
    - 관리자 계정: .env 파일의 ROOT_USER/ROOT_PASSWORD 사용
    """
    user_name = credentials.get('name')
    password = credentials.get('password')
    
    if not user_name or not password:
        raise HTTPException(status_code=400, detail="이름과 비밀번호를 입력하세요")
    
    # 🔐 관리자 계정 (환경변수에서 로드, 기본값 포함)
    root_user = os.getenv('ROOT_USER', 'root')
    root_password = os.getenv('ROOT_PASSWORD', 'xhRl1004!@#')
    if user_name.strip() == root_user and password == root_password:
        # 모든 메뉴에 대한 권한 부여
        all_permissions = {
            "dashboard": True,
            "instructor-codes": True,
            "instructors": True,
            "system-settings": True,
            "subjects": True,
            "holidays": True,
            "courses": True,
            "students": True,
            "counselings": True,
            "timetables": True,
            "training-logs": True,
            "ai-report": True,
            "ai-training-log": True,
            "ai-counseling": True,
            "projects": True,
            "team-activity-logs": True
        }
        return {
            "success": True,
            "message": "관리자님, 환영합니다!",
            "instructor": {
                "code": "ROOT",
                "name": root_user,
                "phone": None,
                "major": "시스템 관리자",
                "instructor_type": "0",
                "email": "root@system.com",
                "photo_urls": None,
                "password": root_password,
                "instructor_type_name": "관리자",
                "instructor_type_type": "0",
                "permissions": all_permissions,
                "default_screen": "dashboard"
            }
        }
    
    conn = get_db_connection()
    try:
        cursor = conn.cursor(pymysql.cursors.DictCursor)
        
        # 1️⃣ 먼저 강사 테이블에서 검색
        cursor.execute("SHOW COLUMNS FROM instructors LIKE 'password'")
        has_instructor_password = cursor.fetchone() is not None
        
        ensure_profile_photo_columns(cursor, 'instructors')
        
        if has_instructor_password:
            cursor.execute("""
                SELECT i.code, TRIM(i.name) as name, i.phone, i.major, i.instructor_type, 
                       i.email, i.created_at, i.updated_at, i.profile_photo, i.attachments, i.password,
                       ic.name as instructor_type_name, ic.type as instructor_type_type, 
                       ic.permissions, ic.default_screen
                FROM instructors i
                LEFT JOIN instructor_codes ic ON i.instructor_type = ic.code
                WHERE TRIM(i.name) = %s
            """, (user_name.strip(),))
        else:
            cursor.execute("""
                SELECT i.code, TRIM(i.name) as name, i.phone, i.major, i.instructor_type, 
                       i.email, i.created_at, i.updated_at, i.profile_photo, i.attachments,
                       ic.name as instructor_type_name, ic.type as instructor_type_type, 
                       ic.permissions, ic.default_screen
                FROM instructors i
                LEFT JOIN instructor_codes ic ON i.instructor_type = ic.code
                WHERE TRIM(i.name) = %s
            """, (user_name.strip(),))
        
        instructor = cursor.fetchone()
        
        # 2️⃣ 강사로 검색되면 강사 로그인 처리
        if instructor:
        
            # 비밀번호 확인 (기본값: kdt2025)
            default_password = "kdt2025"
            stored_password = instructor.get('password', default_password)
            
            if stored_password is None:
                stored_password = default_password
            
            if password != stored_password:
                raise HTTPException(status_code=401, detail="비밀번호가 일치하지 않습니다")
            
            # datetime 변환
            for key, value in instructor.items():
                if isinstance(value, (datetime, date)):
                    instructor[key] = value.isoformat()
                elif isinstance(value, bytes):
                    instructor[key] = None
            
            # permissions 처리 (JSON 또는 menu_permissions 배열)
            import json
            permissions_dict = {}
            
            # 1. permissions 컬럼 확인 (JSON 문자열)
            if instructor.get('permissions'):
                try:
                    permissions_dict = json.loads(instructor['permissions'])
                except:
                    pass
            
            # 2. menu_permissions 배열 확인
            if not permissions_dict:
                cursor.execute("""
                    SELECT menu_permissions FROM instructor_codes WHERE code = %s
                """, (instructor.get('instructor_type'),))
                result = cursor.fetchone()
                if result and result.get('menu_permissions'):
                    try:
                        menu_list = json.loads(result['menu_permissions'])
                        permissions_dict = {menu: True for menu in menu_list}
                    except:
                        pass
            
            # 3. 권한이 없으면 빈 객체
            if not permissions_dict:
                permissions_dict = {}
            
            # aesong-3d-chat 권한 자동 추가 (모든 강사에게)
            permissions_dict['aesong-3d-chat'] = True
            
            instructor['permissions'] = permissions_dict

            return {
                "success": True,
                "message": f"{instructor['name']}님, 환영합니다!",
                "user_type": "instructor",
                "instructor": instructor
            }
        
        # 3️⃣ 강사가 아니면 학생 테이블에서 검색
        ensure_profile_photo_columns(cursor, 'students')
        
        cursor.execute("SHOW COLUMNS FROM students LIKE 'password'")
        if not cursor.fetchone():
            cursor.execute("ALTER TABLE students ADD COLUMN password VARCHAR(100) DEFAULT 'kdt2025'")
            conn.commit()
        
        cursor.execute("""
            SELECT s.*, 
                   c.name as course_name,
                   c.start_date,
                   c.final_end_date as end_date
            FROM students s
            LEFT JOIN courses c ON s.course_code = c.code
            WHERE s.name = %s
            LIMIT 1
        """, (user_name.strip(),))
        
        student = cursor.fetchone()

        if not student:
            # 4️⃣ 학생도 아니면 신규가입 신청자 테이블에서 검색
            ensure_student_registrations_table(cursor)
            conn.commit()

            cursor.execute("""
                SELECT * FROM student_registrations
                WHERE name = %s
                ORDER BY created_at DESC
                LIMIT 1
            """, (user_name.strip(),))

            registration = cursor.fetchone()

            if registration:
                # 생년월일로 비밀번호 확인
                birth_date = registration.get('birth_date', '')
                if password != birth_date:
                    raise HTTPException(status_code=401, detail="비밀번호가 일치하지 않습니다 (생년월일 6자리)")

                status = registration.get('status', 'pending')

                if status == 'pending':
                    raise HTTPException(status_code=403, detail="⏳ 처리중입니다. 승인 후 이용 가능합니다.")
                elif status == 'rejected':
                    raise HTTPException(status_code=403, detail="❌ 신청이 거부되었습니다. 관리자에게 문의하세요.")
                elif status == 'approved':
                    # 승인되었으면 학생 테이블에서 다시 검색해야 함
                    cursor.execute("""
                        SELECT s.*,
                               c.name as course_name,
                               c.start_date,
                               c.final_end_date as end_date
                        FROM students s
                        LEFT JOIN courses c ON s.course_code = c.code
                        WHERE s.name = %s
                        LIMIT 1
                    """, (user_name.strip(),))
                    student = cursor.fetchone()

                    if student:
                        # 학생 비밀번호 확인 (생년월일)
                        stored_password = student.get('password', 'kdt2025')
                        if stored_password is None:
                            stored_password = 'kdt2025'
                        if password != stored_password:
                            raise HTTPException(status_code=401, detail="비밀번호가 일치하지 않습니다")
                    else:
                        raise HTTPException(status_code=401, detail="✅ 승인되었습니다. 잠시 후 다시 시도해주세요.")
            else:
                raise HTTPException(status_code=401, detail="등록되지 않은 사용자입니다")

        if student:
            # 비밀번호 확인
            default_password = "kdt2025"
            stored_password = student.get('password', default_password)

            if stored_password is None:
                stored_password = default_password

            if password != stored_password:
                raise HTTPException(status_code=401, detail="비밀번호가 일치하지 않습니다")

            # datetime 변환
            for key, value in student.items():
                if isinstance(value, (datetime, date)):
                    student[key] = value.isoformat()
                elif isinstance(value, bytes):
                    student[key] = None

            return {
                "success": True,
                "message": f"{student['name']}님, 환영합니다!",
                "user_type": "student",
                "student": student
            }

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"로그인 실패: {str(e)}")
    finally:
        conn.close()

@app.post("/api/auth/student-login")
async def student_login(credentials: dict):
    """
    학생 로그인 API
    - 학생 이름과 비밀번호로 로그인
    - 기본 비밀번호: kdt2025
    """
    student_name = credentials.get('name')
    password = credentials.get('password')
    
    if not student_name:
        raise HTTPException(status_code=400, detail="이름을 입력하세요")
    
    if not password:
        raise HTTPException(status_code=400, detail="비밀번호를 입력하세요")
    
    conn = get_db_connection()
    try:
        cursor = conn.cursor(pymysql.cursors.DictCursor)
        
        # profile_photo와 attachments 컬럼이 없으면 자동 생성
        ensure_profile_photo_columns(cursor, 'students')
        
        # password 컬럼이 없으면 추가
        cursor.execute("SHOW COLUMNS FROM students LIKE 'password'")
        if not cursor.fetchone():
            cursor.execute("ALTER TABLE students ADD COLUMN password VARCHAR(100) DEFAULT 'kdt2025'")
            conn.commit()
        
        # 학생 조회 (이름으로)
        cursor.execute("""
            SELECT s.*, 
                   c.name as course_name,
                   c.start_date,
                   c.final_end_date as end_date
            FROM students s
            LEFT JOIN courses c ON s.course_code = c.code
            WHERE s.name = %s
            LIMIT 1
        """, (student_name.strip(),))
        
        student = cursor.fetchone()

        if not student:
            raise HTTPException(status_code=401, detail="등록되지 않은 학생입니다")
        
        # 비밀번호 확인 (기본값: kdt2025)
        default_password = "kdt2025"
        stored_password = student.get('password', default_password)
        
        if stored_password is None:
            stored_password = default_password
        
        if password != stored_password:
            raise HTTPException(status_code=401, detail="비밀번호가 일치하지 않습니다")
        
        # datetime 변환
        for key, value in student.items():
            if isinstance(value, (datetime, date)):
                student[key] = value.isoformat()
            elif isinstance(value, bytes):
                student[key] = None
        
        return {
            "success": True,
            "message": f"{student['name']}님, 환영합니다!",
            "student": student
        }
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"로그인 실패: {str(e)}")
    finally:
        conn.close()

@app.post("/api/auth/change-password")
async def change_password(data: dict):
    """
    비밀번호 변경 API
    - old_password가 있으면: 본인이 비밀번호 변경 (기존 비밀번호 확인 필요)
    - old_password가 없으면: 주강사가 다른 강사 비밀번호 관리 (기존 비밀번호 확인 불필요)
    """
    instructor_code = data.get('instructor_code')
    old_password = data.get('old_password')  # 선택적 파라미터
    new_password = data.get('new_password')
    
    if not instructor_code or not new_password:
        raise HTTPException(status_code=400, detail="강사코드와 새 비밀번호를 입력하세요")
    
    conn = get_db_connection()
    try:
        cursor = conn.cursor(pymysql.cursors.DictCursor)
        
        # password 컬럼이 없으면 추가
        cursor.execute("SHOW COLUMNS FROM instructors LIKE 'password'")
        if not cursor.fetchone():
            cursor.execute("ALTER TABLE instructors ADD COLUMN password VARCHAR(100) DEFAULT 'kdt2025'")
            conn.commit()
        
        # 기존 비밀번호 확인 (old_password가 제공된 경우에만)
        if old_password:
            cursor.execute("SELECT password FROM instructors WHERE code = %s", (instructor_code,))
            result = cursor.fetchone()
            
            if not result:
                raise HTTPException(status_code=404, detail="강사를 찾을 수 없습니다")
            
            stored_password = result.get('password', 'kdt2025')
            if stored_password is None:
                stored_password = 'kdt2025'
            
            if old_password != stored_password:
                raise HTTPException(status_code=401, detail="현재 비밀번호가 일치하지 않습니다")
        else:
            # old_password가 없으면 주강사 권한으로 직접 변경
            cursor.execute("SELECT code FROM instructors WHERE code = %s", (instructor_code,))
            if not cursor.fetchone():
                raise HTTPException(status_code=404, detail="강사를 찾을 수 없습니다")
        
        # 비밀번호 업데이트
        cursor.execute("""
            UPDATE instructors 
            SET password = %s 
            WHERE code = %s
        """, (new_password, instructor_code))
        
        conn.commit()
        
        return {
            "success": True,
            "message": "비밀번호가 변경되었습니다"
        }
        
    except HTTPException:
        raise
    except Exception as e:
        conn.rollback()
        raise HTTPException(status_code=500, detail=f"비밀번호 변경 실패: {str(e)}")
    finally:
        conn.close()

@app.get("/", response_class=HTMLResponse)
async def serve_index():
    """랜딩 페이지로 리다이렉트"""
    return RedirectResponse(url="/kwv-landing.html", status_code=302)

# ==================== 팀 활동일지 API ====================

@app.get("/api/team-activity-logs")
async def get_team_activity_logs(project_id: Optional[int] = None):
    """팀 활동일지 조회"""
    conn = get_db_connection()
    try:
        cursor = conn.cursor(pymysql.cursors.DictCursor)
        
        if project_id:
            cursor.execute("""
                SELECT * FROM team_activity_logs
                WHERE project_id = %s
                ORDER BY activity_date DESC, created_at DESC
            """, (project_id,))
        else:
            cursor.execute("""
                SELECT * FROM team_activity_logs
                ORDER BY activity_date DESC, created_at DESC
            """)
        
        logs = cursor.fetchall()
        return logs
    except pymysql.err.ProgrammingError as e:
        # 테이블이 없는 경우 빈 배열 반환
        if "doesn't exist" in str(e):
            return []
        raise
    finally:
        conn.close()

@app.post("/api/team-activity-logs")
async def create_team_activity_log(log: dict):
    """팀 활동일지 생성"""
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        
        cursor.execute("""
            INSERT INTO team_activity_logs 
            (project_id, instructor_code, activity_date, activity_type, content, achievements, next_plan, notes, photo_urls)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
        """, (
            log.get('project_id'),
            log.get('instructor_code'),
            log.get('activity_date'),
            log.get('activity_type', '팀 활동'),
            log.get('content'),
            log.get('achievements'),
            log.get('next_plan'),
            log.get('notes'),
            log.get('photo_urls', '[]')
        ))
        
        conn.commit()
        log_id = cursor.lastrowid
        
        return {"success": True, "id": log_id, "message": "팀 활동일지가 생성되었습니다"}
    except Exception as e:
        conn.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        conn.close()

@app.put("/api/team-activity-logs/{log_id}")
async def update_team_activity_log(log_id: int, log: dict):
    """팀 활동일지 수정"""
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        
        cursor.execute("""
            UPDATE team_activity_logs
            SET instructor_code = %s, activity_date = %s, activity_type = %s, content = %s,
                achievements = %s, next_plan = %s, notes = %s, photo_urls = %s
            WHERE id = %s
        """, (
            log.get('instructor_code'),
            log.get('activity_date'),
            log.get('activity_type'),
            log.get('content'),
            log.get('achievements'),
            log.get('next_plan'),
            log.get('notes'),
            log.get('photo_urls', '[]'),
            log_id
        ))
        
        conn.commit()
        
        if cursor.rowcount == 0:
            raise HTTPException(status_code=404, detail="팀 활동일지를 찾을 수 없습니다")
        
        return {"success": True, "message": "팀 활동일지가 수정되었습니다"}
    except HTTPException:
        raise
    except Exception as e:
        conn.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        conn.close()

@app.delete("/api/team-activity-logs/{log_id}")
async def delete_team_activity_log(log_id: int):
    """팀 활동일지 삭제"""
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        
        cursor.execute("DELETE FROM team_activity_logs WHERE id = %s", (log_id,))
        conn.commit()
        
        if cursor.rowcount == 0:
            raise HTTPException(status_code=404, detail="팀 활동일지를 찾을 수 없습니다")
        
        return {"success": True, "message": "팀 활동일지가 삭제되었습니다"}
    except HTTPException:
        raise
    except Exception as e:
        conn.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        conn.close()

@app.get("/login", response_class=HTMLResponse)
async def serve_login():
    """로그인 페이지 서빙"""
    try:
        login_path = os.path.join(frontend_dir, "login.html")
        with open(login_path, "r", encoding="utf-8") as f:
            return HTMLResponse(content=f.read())
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Login page not found")

@app.get("/manifest.json")
async def serve_manifest():
    """manifest.json 서빙"""
    from fastapi.responses import FileResponse
    manifest_path = os.path.join(frontend_dir, "manifest.json")
    if os.path.exists(manifest_path):
        return FileResponse(manifest_path, media_type="application/json")
    raise HTTPException(status_code=404, detail="manifest.json not found")

@app.get("/{subdir}/{filename}.html", response_class=HTMLResponse)
async def serve_subdir_html(subdir: str, filename: str):
    """프론트엔드 서브디렉토리 HTML 파일 서빙"""
    allowed_subdirs = ['admin', 'applicant', 'mobile']
    if subdir not in allowed_subdirs:
        raise HTTPException(status_code=404, detail=f"{subdir}/{filename}.html not found")
    try:
        html_path = os.path.join(frontend_dir, subdir, f"{filename}.html")
        if not os.path.exists(html_path):
            raise HTTPException(status_code=404, detail=f"{subdir}/{filename}.html not found")
        with open(html_path, "r", encoding="utf-8") as f:
            return HTMLResponse(content=f.read())
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"{subdir}/{filename}.html not found")

@app.get("/{filename}.html", response_class=HTMLResponse)
async def serve_html(filename: str):
    """프론트엔드 HTML 파일 서빙"""
    try:
        html_path = os.path.join(frontend_dir, f"{filename}.html")
        if not os.path.exists(html_path):
            raise HTTPException(status_code=404, detail=f"{filename}.html not found")
        with open(html_path, "r", encoding="utf-8") as f:
            return HTMLResponse(content=f.read())
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"{filename}.html not found")

@app.get("/{filename:path}.js")
async def serve_js(filename: str):
    """프론트엔드 JS 파일 서빙"""
    from fastapi.responses import FileResponse
    js_path = os.path.join(frontend_dir, f"{filename}.js")
    if os.path.exists(js_path):
        return FileResponse(js_path, media_type="application/javascript")
    raise HTTPException(status_code=404, detail=f"{filename}.js not found")

@app.get("/{filename:path}.css")
async def serve_css(filename: str):
    """프론트엔드 CSS 파일 서빙"""
    from fastapi.responses import FileResponse
    css_path = os.path.join(frontend_dir, f"{filename}.css")
    if os.path.exists(css_path):
        return FileResponse(css_path, media_type="text/css")
    raise HTTPException(status_code=404, detail=f"{filename}.css not found")

@app.get("/favicon.ico")
async def serve_favicon():
    """favicon.ico 서빙"""
    from fastapi.responses import FileResponse
    favicon_path = os.path.join(frontend_dir, "favicon.ico")
    if os.path.exists(favicon_path):
        return FileResponse(favicon_path, media_type="image/x-icon")
    raise HTTPException(status_code=404, detail="favicon.ico not found")

@app.get("/{filename}.png")
async def serve_png(filename: str):
    """PNG 이미지 파일 서빙"""
    from fastapi.responses import FileResponse
    png_path = os.path.join(frontend_dir, f"{filename}.png")
    if os.path.exists(png_path):
        return FileResponse(png_path, media_type="image/png")
    raise HTTPException(status_code=404, detail=f"{filename}.png not found")

# ==================== FTP 이미지 프록시 ====================
from fastapi.responses import StreamingResponse
from urllib.parse import urlparse, unquote

@app.get("/api/proxy-image")
async def proxy_ftp_image(url: str):
    """FTP 이미지를 HTTP로 프록시"""
    try:
        # URL 파싱
        parsed = urlparse(url)
        
        if parsed.scheme != 'ftp':
            raise HTTPException(status_code=400, detail="FTP URL만 지원됩니다")
        
        # FTP 연결
        ftp = FTP()
        ftp.encoding = 'utf-8'  # 한글 파일명 지원
        ftp.connect(parsed.hostname or FTP_CONFIG['host'], parsed.port or FTP_CONFIG['port'])
        ftp.login(FTP_CONFIG['user'], FTP_CONFIG['passwd'])
        
        # 파일 경로 추출 (URL 디코딩)
        file_path = unquote(parsed.path)
        
        # 파일을 메모리로 읽기
        file_data = io.BytesIO()
        ftp.retrbinary(f'RETR {file_path}', file_data.write)
        ftp.quit()
        
        # 파일 포인터를 처음으로 이동
        file_data.seek(0)
        
        # 파일 확장자로 MIME 타입 결정
        ext = file_path.lower().split('.')[-1]
        mime_types = {
            'jpg': 'image/jpeg',
            'jpeg': 'image/jpeg',
            'png': 'image/png',
            'gif': 'image/gif',
            'webp': 'image/webp',
            'bmp': 'image/bmp'
        }
        media_type = mime_types.get(ext, 'image/jpeg')
        
        return StreamingResponse(file_data, media_type=media_type)
        
    except Exception as e:
        print(f"FTP 이미지 프록시 에러: {e}")
        raise HTTPException(status_code=500, detail=f"이미지를 불러올 수 없습니다: {str(e)}")

# ==================== 시스템 설정 API ====================

def ensure_system_settings_table(cursor):
    """system_settings 테이블이 없으면 생성"""
    try:
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS system_settings (
                id INT AUTO_INCREMENT PRIMARY KEY,
                setting_key VARCHAR(50) UNIQUE NOT NULL,
                setting_value TEXT,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
            )
        """)
    except Exception as e:
        pass

@app.get("/api/og-logo")
async def get_og_logo():
    """Open Graph용 로고 이미지 - 시스템 설정의 로고로 리다이렉트"""
    conn = get_db_connection()
    cursor = conn.cursor(pymysql.cursors.DictCursor)

    try:
        cursor.execute("SELECT setting_value FROM system_settings WHERE setting_key = 'logo_url'")
        result = cursor.fetchone()

        if result and result['setting_value']:
            logo_url = result['setting_value']
            # FTP URL인 경우 download-image API로 변환
            if logo_url.startswith('ftp://'):
                return RedirectResponse(url=f"/api/download-image?url={logo_url}")
            return RedirectResponse(url=logo_url)
        else:
            # 기본 로고로 리다이렉트
            return RedirectResponse(url="/woosong-logo.png")
    finally:
        cursor.close()
        conn.close()

@app.get("/api/system-settings")
async def get_system_settings():
    """시스템 설정 조회"""
    conn = get_db_connection()
    cursor = conn.cursor(pymysql.cursors.DictCursor)
    
    try:
        ensure_system_settings_table(cursor)
        conn.commit()
        
        cursor.execute("SELECT * FROM system_settings")
        settings = cursor.fetchall()
        
        # 설정을 키-값 형태로 변환
        settings_dict = {}
        for setting in settings:
            settings_dict[setting['setting_key']] = setting['setting_value']
        
        # 기본값 설정
        if 'system_title' not in settings_dict:
            settings_dict['system_title'] = 'KDT교육관리시스템 v3.2'
        if 'system_subtitle1' not in settings_dict:
            settings_dict['system_subtitle1'] = '보건복지부(한국보건산업진흥원), KDT, 우송대학교산학협력단'
        if 'system_subtitle2' not in settings_dict:
            settings_dict['system_subtitle2'] = '바이오헬스아카데미 올인원테크 이노베이터'
        if 'logo_url' not in settings_dict:
            settings_dict['logo_url'] = '/woosong-logo.png'
        
        return settings_dict
    except Exception as e:
        conn.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        cursor.close()
        conn.close()

@app.post("/api/system-settings")
async def update_system_settings(
    system_title: Optional[str] = Form(None),
    system_subtitle1: Optional[str] = Form(None),
    system_subtitle2: Optional[str] = Form(None),
    logo_url: Optional[str] = Form(None),
    favicon_url: Optional[str] = Form(None),
    youtube_api_key: Optional[str] = Form(None),
    groq_api_key: Optional[str] = Form(None),
    gemini_api_key: Optional[str] = Form(None),
    bgm_genre: Optional[str] = Form(None),
    bgm_volume: Optional[str] = Form(None),
    dashboard_refresh_interval: Optional[str] = Form(None),
    open_courses: Optional[str] = Form(None),
    interest_keywords: Optional[str] = Form(None),
    login_show_register: Optional[str] = Form(None),
    login_show_course_intro: Optional[str] = Form(None),
    login_show_education_support: Optional[str] = Form(None),
    login_show_facebook: Optional[str] = Form(None),
    login_show_instagram: Optional[str] = Form(None)
):
    """시스템 설정 업데이트"""
    conn = get_db_connection()
    cursor = conn.cursor()

    try:
        ensure_system_settings_table(cursor)
        conn.commit()

        updates = {
            'system_title': system_title,
            'system_subtitle1': system_subtitle1,
            'system_subtitle2': system_subtitle2,
            'logo_url': logo_url,
            'favicon_url': favicon_url,
            'youtube_api_key': youtube_api_key,
            'groq_api_key': groq_api_key,
            'gemini_api_key': gemini_api_key,
            'bgm_genre': bgm_genre,
            'bgm_volume': bgm_volume,
            'dashboard_refresh_interval': dashboard_refresh_interval,
            'open_courses': open_courses,
            'interest_keywords': interest_keywords,
            'login_show_register': login_show_register,
            'login_show_course_intro': login_show_course_intro,
            'login_show_education_support': login_show_education_support,
            'login_show_facebook': login_show_facebook,
            'login_show_instagram': login_show_instagram
        }
        
        update_count = 0
        for key, value in updates.items():
            if value is not None:
                cursor.execute("""
                    INSERT INTO system_settings (setting_key, setting_value)
                    VALUES (%s, %s)
                    ON DUPLICATE KEY UPDATE setting_value = %s
                """, (key, value, value))
                update_count += 1

        conn.commit()

        # 로고가 변경되면 OG 이미지로 복사
        if logo_url:
            try:
                og_image_path = os.path.join(os.path.dirname(__file__), '..', 'frontend', 'og-image.png')

                if logo_url.startswith('ftp://'):
                    # FTP URL인 경우 직접 FTP에서 다운로드
                    url_parts = logo_url.replace('ftp://', '').split('/', 1)
                    file_path = url_parts[1] if len(url_parts) > 1 else ''

                    ftp = FTP()
                    ftp.encoding = 'utf-8'
                    ftp.connect(FTP_CONFIG['host'], FTP_CONFIG['port'])
                    ftp.login(FTP_CONFIG['user'], FTP_CONFIG['passwd'])

                    file_data = io.BytesIO()
                    ftp.retrbinary(f'RETR /{file_path}', file_data.write)
                    ftp.quit()

                    with open(og_image_path, 'wb') as f:
                        f.write(file_data.getvalue())
                else:
                    # 일반 URL인 경우 직접 다운로드
                    import requests
                    response = requests.get(logo_url, timeout=10)
                    if response.status_code == 200:
                        with open(og_image_path, 'wb') as f:
                            f.write(response.content)
            except Exception as og_err:
                pass  # OG 이미지 복사 실패는 무시

        return {"message": "시스템 설정이 업데이트되었습니다", "updated_count": update_count}
    except Exception as e:
        conn.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        cursor.close()
        conn.close()

# ==================== 신규가입 (학생 등록 신청) API ====================

def ensure_student_registrations_table(cursor):
    """student_registrations 테이블이 없으면 생성"""
    try:
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS student_registrations (
                id INT AUTO_INCREMENT PRIMARY KEY,
                name VARCHAR(100) NOT NULL,
                birth_date VARCHAR(20),
                gender VARCHAR(10),
                phone VARCHAR(50),
                email VARCHAR(100),
                address TEXT,
                interests TEXT,
                education TEXT,
                introduction TEXT,
                course_code VARCHAR(50),
                profile_photo TEXT,
                status ENUM('pending', 'approved', 'rejected') DEFAULT 'pending',
                processed_at DATETIME,
                processed_by VARCHAR(50),
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                INDEX idx_status (status),
                INDEX idx_created_at (created_at)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
        """)
    except Exception as e:
        pass

@app.get("/api/student-registrations")
async def get_student_registrations(status: Optional[str] = None):
    """신규가입 신청 목록 조회"""
    conn = get_db_connection()
    cursor = conn.cursor(pymysql.cursors.DictCursor)

    try:
        ensure_student_registrations_table(cursor)
        conn.commit()

        query = "SELECT * FROM student_registrations WHERE 1=1"
        params = []

        if status:
            query += " AND status = %s"
            params.append(status)

        query += " ORDER BY created_at DESC"

        cursor.execute(query, params)
        registrations = cursor.fetchall()

        # datetime 변환
        for reg in registrations:
            for key, value in reg.items():
                if isinstance(value, (datetime, date)):
                    reg[key] = value.isoformat()

        return registrations
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        cursor.close()
        conn.close()

@app.post("/api/student-registrations")
async def create_student_registration(data: dict):
    """신규가입 신청 등록"""
    conn = get_db_connection()
    cursor = conn.cursor()

    try:
        ensure_student_registrations_table(cursor)

        name = data.get('name')
        if not name:
            raise HTTPException(status_code=400, detail="이름은 필수입니다")

        # profile_photo가 Base64 데이터이면 FTP에 업로드하고 URL만 저장
        profile_photo = data.get('profile_photo', '')
        if profile_photo and profile_photo.startswith('data:image'):
            try:
                if ',' in profile_photo:
                    header, base64_data = profile_photo.split(',', 1)
                    if 'image/' in header:
                        image_type = header.split('image/')[1].split(';')[0]
                        file_ext = f'.{image_type}'
                    else:
                        file_ext = '.jpg'
                else:
                    base64_data = profile_photo
                    file_ext = '.jpg'

                file_data = base64.b64decode(base64_data)
                timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
                unique_id = str(uuid.uuid4())[:8]
                new_filename = f"{timestamp}_{unique_id}{file_ext}"
                profile_photo = upload_to_ftp(file_data, new_filename, "student")
            except Exception as e:
                print(f"[WARN] 신규가입 프로필 사진 FTP 업로드 실패: {e}")
                profile_photo = ''

        cursor.execute("""
            INSERT INTO student_registrations
            (name, birth_date, gender, phone, email, address, interests, education, introduction, course_code, profile_photo)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """, (
            name,
            data.get('birth_date'),
            data.get('gender'),
            data.get('phone', ''),
            data.get('email', ''),
            data.get('address', ''),
            data.get('interests', ''),
            data.get('education', ''),
            data.get('introduction', ''),
            data.get('course_code', ''),
            profile_photo
        ))

        conn.commit()
        registration_id = cursor.lastrowid

        print(f"[OK] 신규가입 신청 등록 완료: ID={registration_id}, 이름={name}")

        return {"message": "신규가입 신청이 완료되었습니다", "id": registration_id}
    except Exception as e:
        conn.rollback()
        print(f"[ERROR] 신규가입 신청 실패: {e}")
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        cursor.close()
        conn.close()

@app.put("/api/student-registrations/{registration_id}/approve")
async def approve_student_registration(registration_id: int, data: dict):
    """신규가입 승인 - 학생 DB로 이동"""
    conn = get_db_connection()
    cursor = conn.cursor(pymysql.cursors.DictCursor)

    try:
        ensure_student_registrations_table(cursor)

        # 신청 정보 조회
        cursor.execute("SELECT * FROM student_registrations WHERE id = %s", (registration_id,))
        registration = cursor.fetchone()

        if not registration:
            raise HTTPException(status_code=404, detail="신청 정보를 찾을 수 없습니다")

        if registration['status'] != 'pending':
            raise HTTPException(status_code=400, detail="이미 처리된 신청입니다")

        # 학생 코드 생성
        cursor.execute("SELECT MAX(CAST(SUBSTRING(code, 2) AS UNSIGNED)) as max_code FROM students WHERE code LIKE 'S%'")
        result = cursor.fetchone()
        next_num = (result['max_code'] or 0) + 1
        student_code = f"S{next_num:03d}"

        # 학생 테이블에 추가 (비밀번호는 생년월일 6자리)
        birth_date = registration['birth_date'] or ''
        # 숫자만 추출하여 6자리로
        password = ''.join(filter(str.isdigit, birth_date))[:6] if birth_date else 'kdt2025'

        cursor.execute("""
            INSERT INTO students
            (code, name, birth_date, gender, phone, email, address, interests, education, introduction, course_code, profile_photo, password)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """, (
            student_code,
            registration['name'],
            registration['birth_date'],
            registration['gender'],
            registration['phone'],
            registration['email'],
            registration['address'],
            registration['interests'],
            registration['education'],
            registration['introduction'],
            registration['course_code'],
            registration['profile_photo'],
            password
        ))

        student_id = cursor.lastrowid

        # 신청 상태 업데이트
        processed_by = data.get('processed_by', '')
        cursor.execute("""
            UPDATE student_registrations
            SET status = 'approved', processed_at = NOW(), processed_by = %s
            WHERE id = %s
        """, (processed_by, registration_id))

        conn.commit()

        print(f"[OK] 신규가입 승인 완료: 신청ID={registration_id}, 학생ID={student_id}, 학생코드={student_code}")

        return {
            "message": "학생으로 등록되었습니다",
            "student_id": student_id,
            "student_code": student_code
        }
    except HTTPException:
        raise
    except Exception as e:
        conn.rollback()
        print(f"[ERROR] 신규가입 승인 실패: {e}")
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        cursor.close()
        conn.close()

@app.put("/api/student-registrations/{registration_id}/reject")
async def reject_student_registration(registration_id: int, data: dict):
    """신규가입 거절"""
    conn = get_db_connection()
    cursor = conn.cursor()

    try:
        ensure_student_registrations_table(cursor)

        # 신청 상태 확인
        cursor.execute("SELECT status FROM student_registrations WHERE id = %s", (registration_id,))
        result = cursor.fetchone()

        if not result:
            raise HTTPException(status_code=404, detail="신청 정보를 찾을 수 없습니다")

        if result[0] != 'pending':
            raise HTTPException(status_code=400, detail="이미 처리된 신청입니다")

        processed_by = data.get('processed_by', '')
        cursor.execute("""
            UPDATE student_registrations
            SET status = 'rejected', processed_at = NOW(), processed_by = %s
            WHERE id = %s
        """, (processed_by, registration_id))

        conn.commit()

        print(f"[OK] 신규가입 거절 완료: 신청ID={registration_id}")

        return {"message": "신청이 거절되었습니다"}
    except HTTPException:
        raise
    except Exception as e:
        conn.rollback()
        print(f"[ERROR] 신규가입 거절 실패: {e}")
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        cursor.close()
        conn.close()

@app.delete("/api/student-registrations/{registration_id}")
async def delete_student_registration(registration_id: int):
    """신규가입 신청 삭제"""
    conn = get_db_connection()
    cursor = conn.cursor()

    try:
        cursor.execute("DELETE FROM student_registrations WHERE id = %s", (registration_id,))
        conn.commit()
        return {"message": "신청이 삭제되었습니다"}
    except Exception as e:
        conn.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        cursor.close()
        conn.close()

# ==================== 학생 수업일지 API ====================

def ensure_class_notes_table(cursor):
    """class_notes 테이블이 없으면 생성하고 필요한 컬럼 추가"""
    try:
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS class_notes (
                id INT AUTO_INCREMENT PRIMARY KEY,
                student_id INT,
                instructor_code VARCHAR(50),
                note_date DATE NOT NULL,
                content TEXT,
                photo_urls TEXT,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                INDEX idx_student_date (student_id, note_date),
                INDEX idx_instructor_code (instructor_code, note_date)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
        """)
        
        # 기존 테이블에 instructor_code 컬럼이 없으면 추가
        try:
            cursor.execute("""
                ALTER TABLE class_notes
                ADD COLUMN instructor_code VARCHAR(50) AFTER student_id
            """)
        except Exception:
            pass  # 이미 존재하면 무시

        # 기존 테이블에 photo_urls 컬럼이 없으면 추가
        try:
            cursor.execute("""
                ALTER TABLE class_notes
                ADD COLUMN photo_urls TEXT AFTER content
            """)
        except Exception:
            pass  # 이미 존재하면 무시

        # student_id를 NULL 허용으로 변경
        try:
            cursor.execute("""
                ALTER TABLE class_notes
                MODIFY COLUMN student_id INT NULL
            """)
        except Exception:
            pass

        # note_date를 DATE에서 DATETIME으로 변경 (시간 정보 저장)
        try:
            cursor.execute("""
                ALTER TABLE class_notes
                MODIFY COLUMN note_date DATETIME NOT NULL
            """)
        except Exception as e:
            pass
    except Exception as e:
        pass

@app.get("/api/class-notes")
async def get_all_class_notes(student_id: Optional[int] = None, instructor_code: Optional[str] = None):
    """모든 수업일지 조회 (필터링 옵션)"""
    conn = get_db_connection()
    try:
        cursor = conn.cursor(pymysql.cursors.DictCursor)
        ensure_class_notes_table(cursor)
        conn.commit()
        
        query = "SELECT * FROM class_notes WHERE 1=1"
        params = []
        
        if student_id is not None:
            # 학생 메모만 조회 (student_id가 일치하고 NULL이 아닌 것)
            query += " AND student_id = %s AND student_id IS NOT NULL"
            params.append(student_id)
        
        if instructor_code is not None:
            # 강사 메모만 조회 (instructor_code가 일치하고 student_id가 NULL인 것)
            query += " AND instructor_code = %s AND student_id IS NULL"
            params.append(instructor_code)
        
        query += " ORDER BY note_date DESC"
        
        cursor.execute(query, params)
        notes = cursor.fetchall()
        
        # datetime 변환
        for note in notes:
            for key, value in note.items():
                if isinstance(value, (datetime, date)):
                    note[key] = value.isoformat()
        
        return notes
    finally:
        conn.close()

@app.get("/api/class-notes/{note_id}")
async def get_class_note_by_id(note_id: int):
    """ID로 특정 수업일지 조회"""
    conn = get_db_connection()
    try:
        cursor = conn.cursor(pymysql.cursors.DictCursor)
        ensure_class_notes_table(cursor)
        conn.commit()
        
        cursor.execute("SELECT * FROM class_notes WHERE id = %s", (note_id,))
        note = cursor.fetchone()
        
        if not note:
            raise HTTPException(status_code=404, detail="수업일지를 찾을 수 없습니다")
        
        # datetime 변환
        for key, value in note.items():
            if isinstance(value, (datetime, date)):
                note[key] = value.isoformat()
        
        return note
    finally:
        conn.close()

@app.post("/api/class-notes")
async def create_class_note(data: dict):
    """수업일지 생성 또는 수정"""
    conn = get_db_connection()
    try:
        cursor = conn.cursor(pymysql.cursors.DictCursor)
        ensure_class_notes_table(cursor)
        
        note_id = data.get('id')  # ID가 있으면 수정
        student_id = data.get('student_id')
        instructor_code = data.get('instructor_code')
        note_date = data.get('note_date')
        content = data.get('content', '')
        photo_urls = data.get('photo_urls', '[]')

        if not note_date:
            raise HTTPException(status_code=400, detail="note_date는 필수입니다")
        
        # student_id와 instructor_code 중 하나는 반드시 있어야 함
        if not student_id and not instructor_code:
            raise HTTPException(status_code=400, detail="student_id 또는 instructor_code가 필요합니다")
        
        # ID가 있으면 UPDATE, 없으면 INSERT
        if note_id:
            cursor.execute(
                """UPDATE class_notes 
                   SET student_id = %s, instructor_code = %s, note_date = %s, content = %s, photo_urls = %s
                   WHERE id = %s""",
                (student_id, instructor_code, note_date, content, photo_urls, note_id)
            )
            if cursor.rowcount == 0:
                raise HTTPException(status_code=404, detail="수업일지를 찾을 수 없습니다")
        else:
            # INSERT 쿼리
            cursor.execute(
                """INSERT INTO class_notes (student_id, instructor_code, note_date, content, photo_urls) 
                   VALUES (%s, %s, %s, %s, %s)""",
                (student_id, instructor_code, note_date, content, photo_urls)
            )
            note_id = cursor.lastrowid
        
        conn.commit()
        
        # 저장된 일지 반환
        cursor.execute("SELECT * FROM class_notes WHERE id = %s", (note_id,))
        note = cursor.fetchone()
        
        # datetime 변환
        for key, value in note.items():
            if isinstance(value, (datetime, date)):
                note[key] = value.isoformat()
        
        return {"success": True, "message": "수업일지가 저장되었습니다", "note": note, "id": note_id}
    except Exception as e:
        conn.rollback()
        print(f"[ERROR] class-notes 저장 에러: {str(e)}")
        print(f"   데이터: id={note_id}, student_id={student_id}, note_date={note_date}")
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        conn.close()

@app.put("/api/class-notes/{note_id}")
async def update_class_note(note_id: int, data: dict):
    """수업일지 수정"""
    conn = get_db_connection()
    try:
        cursor = conn.cursor(pymysql.cursors.DictCursor)
        ensure_class_notes_table(cursor)
        
        note_date = data.get('note_date')
        content = data.get('content', '')
        photo_urls = data.get('photo_urls', '[]')
        
        if not note_date:
            raise HTTPException(status_code=400, detail="note_date는 필수입니다")
        
        # UPDATE 쿼리
        cursor.execute(
            """UPDATE class_notes 
               SET note_date = %s, content = %s, photo_urls = %s 
               WHERE id = %s""",
            (note_date, content, photo_urls, note_id)
        )
        
        if cursor.rowcount == 0:
            raise HTTPException(status_code=404, detail="수업일지를 찾을 수 없습니다")
        
        conn.commit()
        
        # 수정된 일지 반환
        cursor.execute("SELECT * FROM class_notes WHERE id = %s", (note_id,))
        note = cursor.fetchone()
        
        # datetime 변환
        for key, value in note.items():
            if isinstance(value, (datetime, date)):
                note[key] = value.isoformat()
        
        return {"success": True, "message": "수업일지가 수정되었습니다", "note": note}
    except Exception as e:
        conn.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        conn.close()

@app.delete("/api/class-notes/{note_id}")
async def delete_class_note(note_id: int):
    """수업일지 삭제"""
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM class_notes WHERE id = %s", (note_id,))
        conn.commit()
        
        if cursor.rowcount == 0:
            raise HTTPException(status_code=404, detail="수업일지를 찾을 수 없습니다")
        
        return {"success": True, "message": "수업일지가 삭제되었습니다"}
    finally:
        conn.close()

@app.post("/api/upload-note-file")
async def upload_note_file(
    file: UploadFile = File(...),
    note_id: int = Form(...)
):
    """
    수업메모 파일 업로드 (사진, 문서 등)
    
    Args:
        file: 업로드할 파일
        note_id: 수업메모 ID
    
    Returns:
        업로드된 파일 정보
    """
    conn = get_db_connection()
    try:
        # 파일 업로드 (기존 upload-image 로직 재사용)
        allowed_extensions = [
            '.jpg', '.jpeg', '.png', '.gif', '.bmp', '.webp',  # 이미지
            '.pdf',  # PDF
            '.doc', '.docx',  # Word
            '.xls', '.xlsx'  # Excel
        ]
        file_ext = os.path.splitext(file.filename)[1].lower()
        
        if file_ext not in allowed_extensions:
            raise HTTPException(
                status_code=400,
                detail=f"허용되지 않는 파일 형식입니다. 허용: {', '.join(allowed_extensions)}"
            )
        
        # 파일 크기 체크 (100MB)
        # UploadFile은 seek()가 동기 함수입니다
        file.file.seek(0, 2)
        file_size = file.file.tell()
        file.file.seek(0)
        
        if file_size > 100 * 1024 * 1024:
            raise HTTPException(
                status_code=413,
                detail=f"파일 크기는 100MB 이하여야 합니다 (현재: {file_size / 1024 / 1024:.2f}MB)"
            )
        
        # 파일명 생성
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        unique_id = str(uuid.uuid4())[:8]
        original_name = os.path.splitext(file.filename)[0]
        
        # 안전한 파일명
        safe_name = ""
        for c in original_name:
            if c.isascii() and (c.isalnum() or c in ('-', '_', '.')):
                safe_name += c
            else:
                safe_name += '_'
        
        import re
        safe_name = re.sub(r'_+', '_', safe_name).strip('_')[:50]
        if not safe_name:
            safe_name = "file"
        
        new_filename = f"{timestamp}_{unique_id}_{safe_name}{file_ext}"
        
        # FTP 업로드 (student 카테고리)
        file_url = await upload_stream_to_ftp(file, new_filename, "student")
        
        # DB에 파일 URL 추가
        cursor = conn.cursor()
        cursor.execute("SELECT photo_urls FROM class_notes WHERE id = %s", (note_id,))
        result = cursor.fetchone()
        
        if not result:
            raise HTTPException(status_code=404, detail="메모를 찾을 수 없습니다")
        
        existing_urls = result[0] if result[0] else ""
        
        # URL 목록 업데이트 (콤마로 구분)
        if existing_urls:
            new_urls = f"{existing_urls},{file_url}"
        else:
            new_urls = file_url
        
        cursor.execute(
            "UPDATE class_notes SET photo_urls = %s WHERE id = %s",
            (new_urls, note_id)
        )
        conn.commit()
        
        print(f"[OK] upload-note-file 성공: note_id={note_id}, url={file_url}")
        
        return {
            "success": True,
            "url": file_url,
            "filename": new_filename,
            "note_id": note_id
        }
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"[ERROR] upload-note-file 에러: {str(e)}")
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"파일 업로드 실패: {str(e)}")
    finally:
        conn.close()

# ==================== 강사 SSIRN 메모 관리 ====================
def ensure_instructor_notes_table(cursor):
    """instructor_notes 테이블이 없으면 생성"""
    try:
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS instructor_notes (
                id INT AUTO_INCREMENT PRIMARY KEY,
                instructor_id INT NOT NULL,
                note_date DATE NOT NULL,
                content TEXT,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                FOREIGN KEY (instructor_id) REFERENCES instructors(id) ON DELETE CASCADE,
                INDEX idx_instructor_date (instructor_id, note_date)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
        """)
    except Exception as e:
        pass

@app.get("/api/instructors/{instructor_id}/notes")
async def get_instructor_notes(instructor_id: int, note_date: Optional[str] = None):
    """강사의 SSIRN 메모 조회"""
    conn = get_db_connection()
    try:
        cursor = conn.cursor(pymysql.cursors.DictCursor)
        ensure_instructor_notes_table(cursor)
        conn.commit()
        
        if note_date:
            # 특정 날짜의 메모 조회
            cursor.execute(
                "SELECT * FROM instructor_notes WHERE instructor_id = %s AND note_date = %s",
                (instructor_id, note_date)
            )
            notes = cursor.fetchall()
            
            # datetime 변환
            for note in notes:
                for key, value in note.items():
                    if isinstance(value, (datetime, date)):
                        note[key] = value.isoformat()
            
            return notes
        else:
            # 모든 메모 조회 (최근 순)
            cursor.execute(
                "SELECT * FROM instructor_notes WHERE instructor_id = %s ORDER BY note_date DESC, created_at DESC",
                (instructor_id,)
            )
            notes = cursor.fetchall()
            
            # datetime 변환
            for note in notes:
                for key, value in note.items():
                    if isinstance(value, (datetime, date)):
                        note[key] = value.isoformat()
            
            return notes
    finally:
        conn.close()

@app.post("/api/instructors/{instructor_id}/notes")
async def create_or_update_instructor_note(instructor_id: int, data: dict):
    """강사 SSIRN 메모 생성 또는 업데이트"""
    conn = get_db_connection()
    try:
        cursor = conn.cursor(pymysql.cursors.DictCursor)
        ensure_instructor_notes_table(cursor)
        
        note_date = data.get('note_date')
        content = data.get('content', '')
        note_id = data.get('id')  # ID가 있으면 수정, 없으면 생성
        
        if not note_date:
            raise HTTPException(status_code=400, detail="note_date는 필수입니다")
        
        if note_id:
            # ID가 제공된 경우: 기존 메모 업데이트
            cursor.execute(
                "UPDATE instructor_notes SET content = %s, note_date = %s WHERE id = %s AND instructor_id = %s",
                (content, note_date, note_id, instructor_id)
            )
            if cursor.rowcount == 0:
                raise HTTPException(status_code=404, detail="메모를 찾을 수 없습니다")
            message = "메모가 수정되었습니다"
        else:
            # ID가 없는 경우: 항상 새로 생성 (같은 날짜에도 여러 개 가능)
            cursor.execute(
                "INSERT INTO instructor_notes (instructor_id, note_date, content) VALUES (%s, %s, %s)",
                (instructor_id, note_date, content)
            )
            note_id = cursor.lastrowid
            message = "메모가 저장되었습니다"
        
        conn.commit()
        
        # 저장된 메모 반환
        cursor.execute("SELECT * FROM instructor_notes WHERE id = %s", (note_id,))
        note = cursor.fetchone()
        
        # datetime 변환
        for key, value in note.items():
            if isinstance(value, (datetime, date)):
                note[key] = value.isoformat()
        
        return {"success": True, "message": message, "note": note}
    except Exception as e:
        conn.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        conn.close()

@app.delete("/api/instructors/{instructor_id}/notes/{note_id}")
async def delete_instructor_note(instructor_id: int, note_id: int):
    """강사 SSIRN 메모 삭제"""
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM instructor_notes WHERE id = %s AND instructor_id = %s", (note_id, instructor_id))
        conn.commit()
        
        if cursor.rowcount == 0:
            raise HTTPException(status_code=404, detail="메모를 찾을 수 없습니다")
        
        return {"success": True, "message": "메모가 삭제되었습니다"}
    finally:
        conn.close()

# ==================== 공지사항 관리 ====================
def ensure_notices_table(cursor):
    """notices 테이블이 없으면 생성"""
    try:
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS notices (
                id INT AUTO_INCREMENT PRIMARY KEY,
                title VARCHAR(500) NOT NULL,
                content TEXT NOT NULL,
                start_date DATE NOT NULL,
                end_date DATE NOT NULL,
                created_by VARCHAR(50),
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                INDEX idx_dates (start_date, end_date)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
        """)
    except Exception as e:
        pass

@app.get("/api/notices")
async def get_notices(
    active_only: bool = False,
    notice_type: Optional[str] = None,
    target_code: Optional[str] = None
):
    """공지사항 목록 조회 (강사용)"""
    conn = get_db_connection()
    try:
        cursor = conn.cursor(pymysql.cursors.DictCursor)
        ensure_notices_table(cursor)
        conn.commit()

        query = """
            SELECT n.*,
                   CASE
                       WHEN n.notice_type = 'course' THEN c.name
                       WHEN n.notice_type = 'subject' THEN s.name
                       ELSE NULL
                   END as target_name
            FROM notices n
            LEFT JOIN courses c ON n.notice_type = 'course' AND n.target_code = c.code
            LEFT JOIN subjects s ON n.notice_type = 'subject' AND n.target_code = s.code
            WHERE 1=1
        """
        params = []

        if active_only:
            query += " AND CURDATE() BETWEEN n.start_date AND n.end_date"

        if notice_type:
            query += " AND n.notice_type = %s"
            params.append(notice_type)

        if target_code:
            query += " AND n.target_code = %s"
            params.append(target_code)

        query += " ORDER BY n.created_at DESC"

        cursor.execute(query, params)
        notices = cursor.fetchall()

        # datetime 변환
        for notice in notices:
            for key, value in notice.items():
                if isinstance(value, (datetime, date)):
                    notice[key] = value.isoformat()

        return notices
    finally:
        conn.close()


@app.get("/api/notices/student/{student_id}")
async def get_student_notices(student_id: int, active_only: bool = True):
    """학생용 공지사항 조회 (전체 + 해당 과정 + 수강 중인 교과목)"""
    conn = get_db_connection()
    try:
        cursor = conn.cursor(pymysql.cursors.DictCursor)

        # 학생 정보 조회
        cursor.execute("SELECT course_code FROM students WHERE id = %s", (student_id,))
        student = cursor.fetchone()
        if not student:
            raise HTTPException(status_code=404, detail="학생을 찾을 수 없습니다")

        course_code = student['course_code']

        # 해당 과정의 교과목 코드 조회
        cursor.execute("""
            SELECT subject_code FROM course_subjects WHERE course_code = %s
        """, (course_code,))
        subject_codes = [row['subject_code'] for row in cursor.fetchall()]

        # 공지 조회: 전체 + 해당 과정 + 수강 중인 교과목
        query = """
            SELECT n.*,
                   CASE
                       WHEN n.notice_type = 'course' THEN c.name
                       WHEN n.notice_type = 'subject' THEN s.name
                       ELSE NULL
                   END as target_name
            FROM notices n
            LEFT JOIN courses c ON n.notice_type = 'course' AND n.target_code = c.code
            LEFT JOIN subjects s ON n.notice_type = 'subject' AND n.target_code = s.code
            WHERE (
                n.notice_type = 'all'
                OR (n.notice_type = 'course' AND n.target_code = %s)
        """
        params = [course_code]

        if subject_codes:
            placeholders = ','.join(['%s'] * len(subject_codes))
            query += f" OR (n.notice_type = 'subject' AND n.target_code IN ({placeholders}))"
            params.extend(subject_codes)

        query += ")"

        if active_only:
            query += " AND CURDATE() BETWEEN n.start_date AND n.end_date"

        query += " ORDER BY n.created_at DESC"

        cursor.execute(query, params)
        notices = cursor.fetchall()

        # datetime 변환
        for notice in notices:
            for key, value in notice.items():
                if isinstance(value, (datetime, date)):
                    notice[key] = value.isoformat()

        return notices
    finally:
        conn.close()

@app.get("/api/notices/{notice_id}")
async def get_notice(notice_id: int):
    """특정 공지사항 조회"""
    conn = get_db_connection()
    try:
        cursor = conn.cursor(pymysql.cursors.DictCursor)
        cursor.execute("SELECT * FROM notices WHERE id = %s", (notice_id,))
        notice = cursor.fetchone()
        
        if not notice:
            raise HTTPException(status_code=404, detail="공지사항을 찾을 수 없습니다")
        
        # datetime 변환
        for key, value in notice.items():
            if isinstance(value, (datetime, date)):
                notice[key] = value.isoformat()
        
        return notice
    finally:
        conn.close()

@app.post("/api/notices")
async def create_notice(data: dict):
    """공지사항 생성"""
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        ensure_notices_table(cursor)
        conn.commit()

        query = """
            INSERT INTO notices (notice_type, target_code, title, content, start_date, end_date, created_by)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
        """
        cursor.execute(query, (
            data.get('notice_type', 'all'),
            data.get('target_code') if data.get('notice_type') != 'all' else None,
            data['title'],
            data['content'],
            data['start_date'],
            data['end_date'],
            data.get('created_by')
        ))
        conn.commit()

        return {"id": cursor.lastrowid, "success": True, "message": "공지사항이 등록되었습니다"}
    finally:
        conn.close()

@app.put("/api/notices/{notice_id}")
async def update_notice(notice_id: int, data: dict):
    """공지사항 수정"""
    conn = get_db_connection()
    try:
        cursor = conn.cursor()

        query = """
            UPDATE notices
            SET notice_type = %s, target_code = %s, title = %s, content = %s, start_date = %s, end_date = %s
            WHERE id = %s
        """
        cursor.execute(query, (
            data.get('notice_type', 'all'),
            data.get('target_code') if data.get('notice_type') != 'all' else None,
            data['title'],
            data['content'],
            data['start_date'],
            data['end_date'],
            notice_id
        ))
        conn.commit()

        if cursor.rowcount == 0:
            raise HTTPException(status_code=404, detail="공지사항을 찾을 수 없습니다")

        return {"success": True, "message": "공지사항이 수정되었습니다"}
    finally:
        conn.close()

@app.delete("/api/notices/{notice_id}")
async def delete_notice(notice_id: int):
    """공지사항 삭제"""
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM notices WHERE id = %s", (notice_id,))
        conn.commit()
        
        if cursor.rowcount == 0:
            raise HTTPException(status_code=404, detail="공지사항을 찾을 수 없습니다")
        
        return {"success": True, "message": "공지사항이 삭제되었습니다"}
    finally:
        conn.close()

# ==================== 예진이 챗봇 API ====================
@app.post("/api/aesong-chat")
async def aesong_chat(data: dict, request: Request):
    """예진이 AI 챗봇 - GROQ, Gemini, 또는 Gemma 모델 사용"""
    message = data.get('message', '')
    character = data.get('character', '예진이')  # 캐릭터 이름 받기
    model = data.get('model', 'groq')  # 사용할 모델 (groq, gemini, gemma)
    
    # 헤더에서 API 키 가져오기 (프론트엔드에서 전달)
    groq_api_key_header = request.headers.get('X-GROQ-API-Key', '')
    gemini_api_key_header = request.headers.get('X-Gemini-API-Key', '')
    
    # DB에서 API 키 가져오기 (헤더가 없을 경우)
    conn = get_db_connection()
    cursor = conn.cursor(pymysql.cursors.DictCursor)
    
    try:
        cursor.execute("SELECT setting_key, setting_value FROM system_settings WHERE setting_key IN ('groq_api_key', 'gemini_api_key')")
        db_settings = {row['setting_key']: row['setting_value'] for row in cursor.fetchall()}
    except:
        db_settings = {}
    finally:
        cursor.close()
        conn.close()
    
    # API 키 우선순위: 헤더 > DB > 환경변수
    groq_api_key = groq_api_key_header or db_settings.get('groq_api_key', '') or os.getenv('GROQ_API_KEY', '')
    gemini_api_key = gemini_api_key_header or db_settings.get('gemini_api_key', '') or os.getenv('GOOGLE_CLOUD_TTS_API_KEY', '')
    
    if not message:
        raise HTTPException(status_code=400, detail="메시지가 필요합니다")
    
    try:
        # 캐릭터별 페르소나 설정
        if character == '데이빗':
            system_prompt = """당신은 '데이빗'입니다. 우송대학교 바이오헬스 교육과정의 생산직 프로그램 전문가입니다.

특징:
- AI 기반 바이오헬스 디지털 케어 프로그램 개발 전문가입니다
- 학생들이 AI를 활용한 헬스케어 솔루션을 개발할 수 있도록 쉽게 실습 중심으로 설명합니다
- 친절하고 열정적인 톤으로 대화합니다
- 쉽고 이해하기 편한 말투를 사용합니다 (예: ~하면 돼요, ~해보세요)
- 이모티콘을 사용하지 마세요 (절대 금지)
- 복잡한 AI와 헬스케어 개념도 실습 예제로 쉽게 설명해줍니다
- 실무 경험을 바탕으로 실용적인 조언을 제공합니다
- 짧고 명확하면서도 친절하게 답변합니다 (2-3문장)

중요: 당신의 이름은 '데이빗'입니다. 절대 다른 이름을 사용하지 마세요.

역할:
- 우송대학교 바이오헬스 교육 관리 시스템의 생산직 프로그램 전문가
- AI 기반 바이오헬스 디지털 케어 프로그램 개발 교육
- 헬스케어 데이터 분석, AI 모델 구축, 디지털 헬스 앱 개발 등 실습 중심 교육
- 학생들에게 실무에서 바로 활용 가능한 AI 헬스케어 기술 전수
- 매우 친절하고 열정적인 강사"""
        elif character == 'PM' or character == '아솔님':
            system_prompt = """당신은 'PM'입니다. 우송대학교 바이오헬스 교육과정의 프로젝트 매니저입니다.

특징:
- 프로젝트 관리 전문가로서 실무적이고 체계적인 조언을 제공합니다
- 중후하고 신뢰감 있는 톤으로 대화합니다
- 존댓말을 사용하며 프로페셔널한 말투를 사용합니다 (예: ~하시면 됩니다, ~권장드립니다)
- 이모티콘을 사용하지 마세요 (절대 금지)
- 프로젝트 진행, 팀워크, 일정 관리 등 실무적인 조언을 제공합니다
- 짧고 명확하면서도 실용적으로 답변합니다 (2-3문장)

중요: 당신의 이름은 'PM'입니다. 절대 다른 이름을 사용하지 마세요.

역할:
- 우송대학교 바이오헬스 교육 관리 시스템의 프로젝트 매니저
- 학생들의 프로젝트 진행 및 팀 협업 지원
- 실무 중심의 조언자"""
        else:
            system_prompt = """당신은 '예진이'라는 이름의 친근하고 귀여운 AI 비서입니다.
우송대학교의 마스코트로, 학생들을 돕는 역할을 합니다.

특징:
- 항상 밝고 긍정적인 톤으로 대화합니다
- 친근하고 귀여운 말투를 사용합니다 (예: ~해요, ~이에요)
- 이모티콘을 사용하지 마세요 (절대 금지)
- 학생들의 고민과 질문에 공감하며 답변합니다
- 짧고 명확하게 답변합니다 (2-3문장)

중요: 당신의 이름은 '예진이'입니다. 절대 다른 이름을 사용하지 마세요.

역할:
- 우송대학교 바이오헬스 교육 관리 시스템의 도우미
- 학생 관리, 상담, 훈련일지 등에 대해 안내
- 친근한 대화 상대"""

        # Gemini 모델 사용
        if model == 'gemini':
            if not gemini_api_key:
                raise Exception("Gemini API 키가 설정되지 않았습니다. 시스템 등록에서 API 키를 입력해주세요.")
            
            # Gemini API 호출
            gemini_url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash-exp:generateContent?key={gemini_api_key}"
            
            payload = {
                "contents": [{
                    "parts": [
                        {"text": f"{system_prompt}\n\n사용자: {message}\n\n당신:"}
                    ]
                }],
                "generationConfig": {
                    "temperature": 0.8,
                    "maxOutputTokens": 200,
                    "topP": 0.9
                }
            }
            
            response = requests.post(gemini_url, json=payload, timeout=15)
            
            if response.status_code != 200:
                raise Exception(f"Gemini API 오류: {response.text}")
            
            result = response.json()
            ai_response = result['candidates'][0]['content']['parts'][0]['text']
            
            return {
                "response": ai_response,
                "model": "gemini-2.0-flash-exp"
            }
        
        # Gemma-3-4B 모델 사용 (GROQ 무료 모델)
        elif model == 'gemma':
            if not groq_api_key:
                raise Exception("GROQ API 키가 설정되지 않았습니다. 시스템 등록에서 API 키를 입력해주세요.")
            
            headers = {
                "Authorization": f"Bearer {groq_api_key}",
                "Content-Type": "application/json"
            }
            
            payload = {
                "model": "gemma2-9b-it",  # GROQ의 Gemma 2 9B 모델 (무료)
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": message}
                ],
                "temperature": 0.8,
                "max_tokens": 200,
                "top_p": 0.9
            }
            
            response = requests.post(
                "https://api.groq.com/openai/v1/chat/completions",
                headers=headers,
                json=payload,
                timeout=15
            )
            
            if response.status_code != 200:
                raise Exception(f"GROQ API 오류: {response.text}")
            
            ai_response = response.json()['choices'][0]['message']['content']
            
            return {
                "response": ai_response,
                "model": "gemma2-9b-it"
            }
        
        # GROQ 모델 사용 (기본값 - Llama 3.3 70B)
        else:
            if not groq_api_key:
                # API 키가 없으면 안내 메시지
                raise Exception("GROQ API 키가 설정되지 않았습니다. 시스템 등록에서 API 키를 입력해주세요.")
            
            headers = {
                "Authorization": f"Bearer {groq_api_key}",
                "Content-Type": "application/json"
            }
            
            payload = {
                "model": "llama-3.3-70b-versatile",
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": message}
                ],
                "temperature": 0.8,
                "max_tokens": 200,
                "top_p": 0.9
            }
            
            response = requests.post(
                "https://api.groq.com/openai/v1/chat/completions",
                headers=headers,
                json=payload,
                timeout=15
            )
            
            if response.status_code != 200:
                raise Exception(f"GROQ API 오류: {response.text}")
            
            ai_response = response.json()['choices'][0]['message']['content']
            
            return {
                "response": ai_response,
                "model": "llama-3.3-70b-versatile"
            }
        
    except Exception as e:
        print(f"예진이 챗봇 오류: {str(e)}")
        # 오류 시 기본 응답
        return {
            "response": "죄송합니다. 지금은 답변하기 어려워요. 잠시 후 다시 말씀해주세요.",
            "model": "error",
            "error": str(e)
        }

# ==================== Google Cloud TTS API ====================
@app.post("/api/tts")
async def text_to_speech(data: dict, request: Request):
    """Google Cloud TTS - 텍스트를 음성으로 변환 (개선된 파라미터)"""
    text = data.get('text', '')
    character = data.get('character', '예진이')
    
    if not text:
        raise HTTPException(status_code=400, detail="텍스트가 필요합니다")
    
    # Google Cloud TTS API 키 확인
    # 1. 헤더에서 가져오기
    api_key_header = request.headers.get('X-Gemini-API-Key', '')
    
    # 2. DB에서 가져오기 (헤더가 없을 경우)
    api_key_db = ''
    if not api_key_header:
        conn = get_db_connection()
        cursor = conn.cursor(pymysql.cursors.DictCursor)
        try:
            cursor.execute("SELECT setting_value FROM system_settings WHERE setting_key = 'gemini_api_key'")
            result = cursor.fetchone()
            if result:
                api_key_db = result['setting_value']
        except:
            pass
        finally:
            cursor.close()
            conn.close()
    
    # 3. 환경변수에서 가져오기 (최후 수단)
    api_key = api_key_header or api_key_db or os.getenv('GOOGLE_CLOUD_TTS_API_KEY', '')
    
    if not api_key:
        raise HTTPException(status_code=500, detail="Google Cloud TTS API 키가 설정되지 않았습니다. 시스템 등록에서 Gemini API 키를 입력해주세요.")
    
    try:
        # 캐릭터별 음성 설정 (자연스러운 파라미터로 개선)
        if character == '데이빗':
            voice_name = "ko-KR-Neural2-C"  # Neural2 남성 음성 (더 자연스러움)
            pitch = -3.0  # 적당히 낮은 톤
            speaking_rate = 0.95  # 조금 느린 속도
        elif character == 'PM' or character == '아솔님':
            voice_name = "ko-KR-Neural2-C"  # Neural2 남성 음성 (PM 중후한 목소리)
            pitch = -5.0  # 매우 낮은 톤 (중후함)
            speaking_rate = 0.85  # 느린 속도 (안정감)
        else:
            voice_name = "ko-KR-Neural2-A"  # Neural2 여성 음성 (더 자연스러움)
            pitch = 2.0  # 적당히 높은 톤
            speaking_rate = 1.0  # 보통 속도
        
        # Google Cloud TTS API 요청
        url = f"https://texttospeech.googleapis.com/v1/text:synthesize?key={api_key}"
        
        payload = {
            "input": {
                "text": text
            },
            "voice": {
                "languageCode": "ko-KR",
                "name": voice_name
            },
            "audioConfig": {
                "audioEncoding": "MP3",
                "pitch": pitch,
                "speakingRate": speaking_rate,
                "volumeGainDb": 0.0,
                "effectsProfileId": ["headphone-class-device"]  # 헤드폰 최적화
            }
        }
        
        response = requests.post(url, json=payload, timeout=10)
        
        if response.status_code != 200:
            raise Exception(f"Google TTS API 오류: {response.text}")
        
        # Base64 인코딩된 오디오 데이터 반환
        audio_content = response.json().get('audioContent', '')
        
        return {
            "audioContent": audio_content,
            "character": character,
            "voice": voice_name
        }
        
    except Exception as e:
        import traceback
        error_trace = traceback.format_exc()
        print(f"TTS 오류 상세: {str(e)}")
        print(f"TTS 오류 스택: {error_trace}")
        raise HTTPException(status_code=500, detail=f"TTS 생성 실패: {str(e)}")

@app.post("/api/timetables/auto-generate")
async def auto_generate_timetables(data: dict):
    """스마트 시간표 자동 생성 (과정별 요일 배정 기반)
    
    Args:
        course_code: 과정 코드
        start_date: 시작일
        lecture_hours: 이론 시간
        project_hours: 프로젝트 시간
        workship_hours: 현장실습 시간
        morning_hours: 오전 시간 (기본 4)
        afternoon_hours: 오후 시간 (기본 4)
    
    Note:
        - course_subjects 테이블의 day_of_week, week_type을 기반으로 시간표 생성
        - 예: 월요일=G-002, 금요일(홀수주)=G-001, 금요일(짝수주)=G-003
    """
    conn = get_db_connection()
    try:
        course_code = data['course_code']
        start_date = datetime.strptime(data['start_date'], '%Y-%m-%d').date()
        lecture_hours = data['lecture_hours']
        project_hours = data['project_hours']
        workship_hours = data['workship_hours']
        morning_hours = data.get('morning_hours', 4)
        afternoon_hours = data.get('afternoon_hours', 4)

        if morning_hours + afternoon_hours <= 0:
            return JSONResponse(status_code=400, content={"detail": "오전/오후 수업시간 합계가 0보다 커야 합니다."})

        cursor = conn.cursor(pymysql.cursors.DictCursor)
        
        # 기존 시간표 삭제
        cursor.execute("DELETE FROM timetables WHERE course_code = %s", (course_code,))
        
        # 공휴일 목록 가져오기
        cursor.execute("SELECT holiday_date FROM holidays ORDER BY holiday_date")
        holidays = [row['holiday_date'] for row in cursor.fetchall()]
        
        # 과정별 요일 배정 정보 가져오기 (subjects 테이블의 day_of_week 사용)
        cursor.execute("""
            SELECT cs.subject_code, s.day_of_week, s.is_biweekly, s.week_offset,
                   s.name, s.hours, s.main_instructor
            FROM course_subjects cs
            JOIN subjects s ON cs.subject_code = s.code
            WHERE cs.course_code = %s
            ORDER BY s.day_of_week, s.week_offset
        """, (course_code,))
        course_subject_assignments = cursor.fetchall()
        
        # 요일별 교과목 매핑 생성 (day_of_week -> [(subject_code, week_type), ...])
        day_subject_map = {}
        for assignment in course_subject_assignments:
            day = assignment['day_of_week']
            if day is None:
                continue
            
            if day not in day_subject_map:
                day_subject_map[day] = []
            
            day_subject_map[day].append({
                'subject_code': assignment['subject_code'],
                'is_biweekly': assignment['is_biweekly'],
                'week_offset': assignment['week_offset'],
                'name': assignment['name'],
                'hours': assignment['hours'],
                'instructor': assignment['main_instructor']
            })
        
        # 주강사 추출
        course_instructors = []
        seen_instructors = set()
        for assignment in course_subject_assignments:
            instructor = assignment['main_instructor']
            if instructor and instructor not in seen_instructors:
                course_instructors.append(instructor)
                seen_instructors.add(instructor)
        
        if not course_instructors:
            cursor.execute("""
                SELECT code FROM instructors 
                WHERE instructor_type = '주강사' 
                ORDER BY code 
                LIMIT 3
            """)
            course_instructors = [row['code'] for row in cursor.fetchall()]
        
        print(f"📋 과정 {course_code}의 요일별 배정:")
        for day, subjects in sorted(day_subject_map.items()):
            # day_of_week는 1(월) ~ 5(금)이므로 -1 해야 함
            day_name = ['월', '화', '수', '목', '금'][day - 1] if 1 <= day <= 5 else f"[{day}]"
            for subj in subjects:
                week_info = f" ({'짝수' if subj['week_offset'] == 0 else '홀수'}주)" if subj['is_biweekly'] else ""
                print(f"  {day_name}{week_info}: {subj['subject_code']} - {subj['name']}")
        
        # 헬퍼 함수
        def is_weekend(date_obj):
            return date_obj.weekday() >= 5
        
        def is_holiday(date_obj):
            return date_obj in holidays
        
        def get_week_number(date_obj, start_date):
            """과정 시작일로부터 몇 주차인지 계산 (0부터 시작)"""
            days_diff = (date_obj - start_date).days
            return days_diff // 7
        
        timetables = []
        current_date = start_date
        
        # 각 교과목별 남은 시간 추적
        subject_remaining = {}
        for assignment in course_subject_assignments:
            subject_remaining[assignment['subject_code']] = assignment['hours']
        
        # 1단계: 이론 (lecture) - 과정별 요일 배정 기반
        total_remaining = lecture_hours
        MAX_ITERATIONS = 500
        iteration_count = 0
        afternoon_slot_available = False  # 오후 슬롯 사용 가능 여부
        
        while total_remaining > 0 and iteration_count < MAX_ITERATIONS:
            iteration_count += 1
            
            if is_weekend(current_date) or is_holiday(current_date):
                current_date += timedelta(days=1)
                afternoon_slot_available = False
                continue
            
            # 오늘 요일에 배정된 교과목 찾기
            # subjects 테이블의 day_of_week는 1(월)~7(일)이므로 weekday()+1로 변환
            today_weekday = current_date.weekday() + 1  # 0(월)~6(일) → 1(월)~7(일)
            if today_weekday not in day_subject_map:
                current_date += timedelta(days=1)
                afternoon_slot_available = False
                continue
            
            week_number = get_week_number(current_date, start_date)
            
            # 오늘 수업 가능한 교과목 필터링
            available_subjects = []
            for subj in day_subject_map[today_weekday]:
                # 격주 체크 (is_biweekly=1이면 격주, week_offset으로 짝수주/홀수주 구분)
                if subj['is_biweekly']:
                    if (week_number % 2) != subj['week_offset']:
                        continue
                # ★★★ 핵심: 남은 시간이 0보다 큰 교과목만 선택 ★★★
                if subject_remaining.get(subj['subject_code'], 0) > 0:
                    available_subjects.append(subj)
            
            # 해당 요일 배정 과목이 모두 소진되면 빈 요일로 건너뛰기
            if not available_subjects:
                # 모든 교과목이 소진되었는지 확인
                all_subjects_exhausted = all(hours <= 0 for hours in subject_remaining.values())
                if all_subjects_exhausted or total_remaining <= 0:
                    # 이론 완전 종료
                    break

                # 해당 요일 과목은 소진 → 빈 요일로 넘김
                current_date += timedelta(days=1)
                afternoon_slot_available = False
                continue
            
            # 남은 시수가 많은 순으로 정렬
            available_subjects.sort(key=lambda s: subject_remaining.get(s['subject_code'], 0), reverse=True)
            
            # 오전 슬롯
            if total_remaining > 0 and available_subjects and morning_hours > 0:
                subj = available_subjects[0]  # 남은 시수가 가장 많은 교과목
                hours_to_use = min(morning_hours, subject_remaining[subj['subject_code']], total_remaining)

                timetables.append({
                    'course_code': course_code,
                    'subject_code': subj['subject_code'],
                    'class_date': current_date,
                    'start_time': '09:00:00',
                    'end_time': f'{9 + int(hours_to_use):02d}:00:00',
                    'instructor_code': subj['instructor'],
                    'type': 'lecture'
                })

                subject_remaining[subj['subject_code']] -= hours_to_use
                total_remaining -= hours_to_use

                # ★★★ 핵심: 이론이 오전에 완전히 끝났는지 체크 ★★★
                if total_remaining <= 0:
                    # 이론이 오전에 끝남 → 오후부터 프로젝트 시작
                    afternoon_slot_available = True
                    break
            
            # 오후 슬롯 - 이론이 아직 남아있는 경우에만
            if total_remaining > 0:
                # ★★★ 1일 1과목 원칙: 오전 과목이 남아있으면 계속, 소진되었으면 다른 과목 ★★★
                afternoon_subject = None
                
                # 1. 오전에 사용한 과목이 아직 남아있는지 확인
                morning_subject_code = subj['subject_code'] if 'subj' in locals() else None
                if morning_subject_code and subject_remaining.get(morning_subject_code, 0) > 0:
                    # 오전 과목이 남아있으면 계속 사용
                    afternoon_subject = subj
                else:
                    # 2. 오전 과목이 소진되었으면 같은 요일 배정 과목 중에서만 선택
                    for s in available_subjects:
                        if subject_remaining.get(s['subject_code'], 0) > 0:
                            afternoon_subject = s
                            break
                
                # 오후 슬롯 생성
                if afternoon_subject and afternoon_hours > 0:
                    hours_to_use = min(afternoon_hours, subject_remaining[afternoon_subject['subject_code']], total_remaining)
                    
                    timetables.append({
                        'course_code': course_code,
                        'subject_code': afternoon_subject['subject_code'],
                        'class_date': current_date,
                        'start_time': '14:00:00',
                        'end_time': f'{14 + int(hours_to_use):02d}:00:00',
                        'instructor_code': afternoon_subject['instructor'],
                        'type': 'lecture'
                    })
                    
                    subject_remaining[afternoon_subject['subject_code']] -= hours_to_use
                    total_remaining -= hours_to_use
            
            # 다음날로 이동
            current_date += timedelta(days=1)
            afternoon_slot_available = False
        
        # 프로젝트/현장실습에서는 course_instructors를 그대로 사용
        instructor_idx = 0
        
        # 2단계: 프로젝트 (project)
        if project_hours > 0:
            remaining_hours = project_hours
            
            # 이론이 오전에 끝나고 오후가 비어있으면 같은 날 오후부터 시작
            if afternoon_slot_available and remaining_hours > 0 and afternoon_hours > 0:
                daily_instructor = course_instructors[instructor_idx % len(course_instructors)]
                hours_to_use = min(afternoon_hours, remaining_hours)
                timetables.append({
                    'course_code': course_code,
                    'subject_code': None,
                    'class_date': current_date,
                    'start_time': '14:00:00',
                    'end_time': f'{14 + int(hours_to_use):02d}:00:00',
                    'instructor_code': daily_instructor,
                    'type': 'project'
                })
                remaining_hours -= hours_to_use
                instructor_idx += 1
                current_date += timedelta(days=1)
                afternoon_slot_available = False

            while remaining_hours > 0:
                if is_weekend(current_date) or is_holiday(current_date):
                    current_date += timedelta(days=1)
                    continue

                daily_instructor = course_instructors[instructor_idx % len(course_instructors)]

                # 오전
                if remaining_hours > 0 and morning_hours > 0:
                    hours_to_use = min(morning_hours, remaining_hours)
                    timetables.append({
                        'course_code': course_code,
                        'subject_code': None,
                        'class_date': current_date,
                        'start_time': '09:00:00',
                        'end_time': f'{9 + int(hours_to_use):02d}:00:00',
                        'instructor_code': daily_instructor,
                        'type': 'project'
                    })
                    remaining_hours -= hours_to_use

                    # ★★★ 핵심: 프로젝트가 오전에 완전히 끝났는지 체크 ★★★
                    if remaining_hours <= 0:
                        # 프로젝트가 오전에 끝남 → 오후부터 현장실습 시작
                        afternoon_slot_available = True
                        break

                # 오후 - 프로젝트가 아직 남아있는 경우에만
                if remaining_hours > 0 and afternoon_hours > 0:
                    hours_to_use = min(afternoon_hours, remaining_hours)
                    timetables.append({
                        'course_code': course_code,
                        'subject_code': None,
                        'class_date': current_date,
                        'start_time': '14:00:00',
                        'end_time': f'{14 + int(hours_to_use):02d}:00:00',
                        'instructor_code': daily_instructor,
                        'type': 'project'
                    })
                    remaining_hours -= hours_to_use

                instructor_idx += 1
                current_date += timedelta(days=1)
                afternoon_slot_available = False
        
        # 3단계: 현장실습 (workship)
        if workship_hours > 0:
            remaining_hours = workship_hours
            
            # 프로젝트가 오전에 끝나고 오후가 비어있으면 같은 날 오후부터 시작
            if afternoon_slot_available and remaining_hours > 0 and afternoon_hours > 0:
                daily_instructor = course_instructors[instructor_idx % len(course_instructors)]
                hours_to_use = min(afternoon_hours, remaining_hours)
                timetables.append({
                    'course_code': course_code,
                    'subject_code': None,
                    'class_date': current_date,
                    'start_time': '14:00:00',
                    'end_time': f'{14 + int(hours_to_use):02d}:00:00',
                    'instructor_code': daily_instructor,
                    'type': 'workship'
                })
                remaining_hours -= hours_to_use
                instructor_idx += 1
                current_date += timedelta(days=1)

            while remaining_hours > 0:
                if is_weekend(current_date) or is_holiday(current_date):
                    current_date += timedelta(days=1)
                    continue

                daily_instructor = course_instructors[instructor_idx % len(course_instructors)]

                # 오전
                if remaining_hours > 0 and morning_hours > 0:
                    hours_to_use = min(morning_hours, remaining_hours)
                    timetables.append({
                        'course_code': course_code,
                        'subject_code': None,
                        'class_date': current_date,
                        'start_time': '09:00:00',
                        'end_time': f'{9 + int(hours_to_use):02d}:00:00',
                        'instructor_code': daily_instructor,
                        'type': 'workship'
                    })
                    remaining_hours -= hours_to_use

                # 오후
                if remaining_hours > 0 and afternoon_hours > 0:
                    hours_to_use = min(afternoon_hours, remaining_hours)
                    timetables.append({
                        'course_code': course_code,
                        'subject_code': None,
                        'class_date': current_date,
                        'start_time': '14:00:00',
                        'end_time': f'{14 + int(hours_to_use):02d}:00:00',
                        'instructor_code': daily_instructor,
                        'type': 'workship'
                    })
                    remaining_hours -= hours_to_use
                
                instructor_idx += 1
                current_date += timedelta(days=1)
        
        # DB에 삽입
        insert_query = """
            INSERT INTO timetables 
            (course_code, subject_code, class_date, start_time, end_time, 
             instructor_code, type)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
        """
        
        for tt in timetables:
            cursor.execute(insert_query, (
                tt['course_code'],
                tt['subject_code'],
                tt['class_date'],
                tt['start_time'],
                tt['end_time'],
                tt['instructor_code'],
                tt['type']
            ))
        
        conn.commit()
        
        return {
            "success": True,
            "generated_count": len(timetables),
            "message": f"{len(timetables)}개의 시간표가 생성되었습니다."
        }
        
    except Exception as e:
        conn.rollback()
        import traceback
        print(f"시간표 자동 생성 오류: {str(e)}")
        print(traceback.format_exc())
        raise HTTPException(status_code=500, detail=f"시간표 자동 생성 실패: {str(e)}")
    finally:
        conn.close()


# ==================== DB 백업 API ====================

@app.post("/api/backup/create")
async def create_backup():
    """수동 DB 백업 생성"""
    import json
    from datetime import datetime, date, timedelta
    
    def convert_to_json_serializable(obj):
        """모든 객체를 JSON 직렬화 가능하게 변환"""
        if isinstance(obj, (datetime, date)):
            return obj.isoformat()
        elif isinstance(obj, timedelta):
            return str(obj)
        elif obj is None:
            return None
        return obj
    
    conn = get_db_connection()
    try:
        cursor = conn.cursor(pymysql.cursors.DictCursor)
        
        backup_data = {}
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        
        # 백업할 테이블 목록
        tables = [
            'timetables', 'training_logs', 'courses', 'subjects', 
            'instructors', 'students', 'course_subjects', 'holidays',
            'projects', 'class_notes', 'consultations', 'notices',
            'system_settings', 'team_activity_logs'
        ]
        
        total_records = 0
        for table in tables:
            try:
                cursor.execute(f"SELECT * FROM {table}")
                rows = cursor.fetchall()
                
                serializable_rows = []
                for row in rows:
                    serializable_row = {k: convert_to_json_serializable(v) for k, v in row.items()}
                    serializable_rows.append(serializable_row)
                
                backup_data[table] = serializable_rows
                total_records += len(rows)
            except Exception as e:
                print(f"[WARN] {table} 백업 실패: {e}")
                backup_data[table] = []
        
        # 백업 디렉토리 생성
        backup_dir = '/home/user/webapp/backend/backups'
        os.makedirs(backup_dir, exist_ok=True)
        
        # JSON 파일로 저장
        backup_file = f'{backup_dir}/db_backup_{timestamp}.json'
        with open(backup_file, 'w', encoding='utf-8') as f:
            json.dump(backup_data, f, ensure_ascii=False, indent=2)
        
        # 파일 크기 확인
        file_size = os.path.getsize(backup_file)
        
        return {
            "success": True,
            "backup_file": backup_file,
            "total_records": total_records,
            "file_size": file_size,
            "timestamp": timestamp,
            "tables": {table: len(backup_data[table]) for table in tables}
        }
        
    except Exception as e:
        import traceback
        print(f"[ERROR] 백업 생성 실패: {e}")
        print(traceback.format_exc())
        raise HTTPException(status_code=500, detail=f"백업 생성 실패: {str(e)}")
    finally:
        conn.close()


@app.get("/api/backup/list")
async def list_backups():
    """백업 파일 목록 조회"""
    import os
    import json
    
    backup_dir = '/home/user/webapp/backend/backups'
    
    try:
        if not os.path.exists(backup_dir):
            return {"backups": []}
        
        backups = []
        for filename in sorted(os.listdir(backup_dir), reverse=True):
            if filename.startswith('db_backup_') and filename.endswith('.json'):
                filepath = os.path.join(backup_dir, filename)
                file_stat = os.stat(filepath)
                
                backups.append({
                    "filename": filename,
                    "filepath": filepath,
                    "size": file_stat.st_size,
                    "created_at": datetime.fromtimestamp(file_stat.st_mtime).isoformat()
                })
        
        return {"backups": backups}
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"백업 목록 조회 실패: {str(e)}")


@app.delete("/api/backup/delete/{filename}")
async def delete_backup(filename: str):
    """백업 파일 삭제"""
    import os
    
    backup_dir = '/home/user/webapp/backend/backups'
    filepath = os.path.join(backup_dir, filename)
    
    try:
        # 보안 체크
        if not filename.startswith('db_backup_') or not filename.endswith('.json'):
            raise HTTPException(status_code=400, detail="잘못된 백업 파일명")
        
        if not os.path.exists(filepath):
            raise HTTPException(status_code=404, detail="백업 파일이 없습니다")
        
        os.remove(filepath)
        return {"success": True, "message": f"{filename} 삭제 완료"}
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"백업 삭제 실패: {str(e)}")


@app.post("/api/backup/auto-cleanup")
async def auto_cleanup_backups(keep_days: int = 7):
    """오래된 백업 자동 삭제 (keep_days일 이전 백업)"""
    import os
    from datetime import datetime, timedelta

    backup_dir = '/home/user/webapp/backend/backups'

    try:
        if not os.path.exists(backup_dir):
            return {"deleted_count": 0, "message": "백업 디렉토리 없음"}

        cutoff_time = datetime.now() - timedelta(days=keep_days)
        deleted_count = 0

        for filename in os.listdir(backup_dir):
            if filename.startswith('db_backup_') and filename.endswith('.json'):
                filepath = os.path.join(backup_dir, filename)
                file_time = datetime.fromtimestamp(os.path.getmtime(filepath))

                if file_time < cutoff_time:
                    os.remove(filepath)
                    deleted_count += 1
                    print(f"🗑️ 삭제: {filename}")

        return {
            "success": True,
            "deleted_count": deleted_count,
            "keep_days": keep_days,
            "message": f"{keep_days}일 이전 백업 {deleted_count}개 삭제 완료"
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"자동 정리 실패: {str(e)}")


# ==================== DB 관리 로그 API ====================

def ensure_db_management_logs_table():
    """DB 관리 로그 테이블 생성 (없으면)"""
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS db_management_logs (
                id INT AUTO_INCREMENT PRIMARY KEY,
                action_type VARCHAR(50) NOT NULL COMMENT '작업 유형 (backup/reset)',
                operator_name VARCHAR(100) NOT NULL COMMENT '작업자 이름',
                action_result VARCHAR(20) NOT NULL COMMENT '결과 (success/fail)',
                backup_file VARCHAR(255) COMMENT '백업 파일명',
                details TEXT COMMENT '상세 내용',
                ip_address VARCHAR(45) COMMENT 'IP 주소',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP COMMENT '작업 시간'
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='DB 관리 로그'
        """)
        conn.commit()
    finally:
        conn.close()

# 서버 시작 시 테이블 확인
ensure_db_management_logs_table()


@app.post("/api/db-management/verify")
async def verify_db_management_credentials(request: Request, data: dict):
    """DB 관리 접속 검증 (강사 이름과 비밀번호 확인)"""
    instructor_name = data.get('instructor_name', '').strip()
    password = data.get('password', '').strip()

    if not instructor_name or not password:
        return {"success": False, "message": "강사 이름과 비밀번호를 입력해주세요."}

    conn = get_db_connection()
    try:
        cursor = conn.cursor(pymysql.cursors.DictCursor)

        # 강사 이름과 비밀번호 확인
        cursor.execute("""
            SELECT code, name, password FROM instructors WHERE name = %s
        """, (instructor_name,))
        instructor = cursor.fetchone()

        if not instructor:
            return {"success": False, "message": "존재하지 않는 강사 이름입니다."}

        if instructor['password'] != password:
            return {"success": False, "message": "비밀번호가 올바르지 않습니다."}

        return {
            "success": True,
            "message": "인증 성공",
            "instructor_name": instructor['name'],
            "instructor_code": instructor['code']
        }
    finally:
        conn.close()


@app.post("/api/db-management/backup-with-log")
async def create_backup_with_log(request: Request, data: dict):
    """백업 생성 및 로그 기록"""
    import json
    from datetime import datetime, date, timedelta

    operator_name = data.get('operator_name', '')
    instructor_code = data.get('instructor_code', '')

    if not operator_name:
        raise HTTPException(status_code=400, detail="작업자 정보가 필요합니다")

    # 클라이언트 IP 가져오기
    client_ip = request.client.host if request.client else 'unknown'

    def convert_to_json_serializable(obj):
        if isinstance(obj, (datetime, date)):
            return obj.isoformat()
        elif isinstance(obj, timedelta):
            return str(obj)
        elif obj is None:
            return None
        return obj

    conn = get_db_connection()
    try:
        cursor = conn.cursor(pymysql.cursors.DictCursor)

        backup_data = {}
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')

        tables = [
            'timetables', 'training_logs', 'courses', 'subjects',
            'instructors', 'students', 'course_subjects', 'holidays',
            'projects', 'class_notes', 'consultations', 'notices',
            'system_settings', 'team_activity_logs', 'db_management_logs'
        ]

        total_records = 0
        for table in tables:
            try:
                cursor.execute(f"SELECT * FROM {table}")
                rows = cursor.fetchall()

                serializable_rows = []
                for row in rows:
                    serializable_row = {k: convert_to_json_serializable(v) for k, v in row.items()}
                    serializable_rows.append(serializable_row)

                backup_data[table] = serializable_rows
                total_records += len(rows)
            except Exception as e:
                print(f"[WARN] {table} 백업 실패: {e}")
                backup_data[table] = []

        backup_dir = '/home/user/webapp/backend/backups'
        os.makedirs(backup_dir, exist_ok=True)

        backup_file = f'db_backup_{timestamp}.json'
        backup_path = f'{backup_dir}/{backup_file}'
        with open(backup_path, 'w', encoding='utf-8') as f:
            json.dump(backup_data, f, ensure_ascii=False, indent=2)

        file_size = os.path.getsize(backup_path)

        # 로그 기록
        cursor.execute("""
            INSERT INTO db_management_logs
            (action_type, operator_name, action_result, backup_file, details, ip_address)
            VALUES (%s, %s, %s, %s, %s, %s)
        """, (
            'backup',
            f"{operator_name} ({instructor_code})",
            'success',
            backup_file,
            f"총 {total_records}개 레코드, {file_size / 1024 / 1024:.2f}MB",
            client_ip
        ))
        conn.commit()

        return {
            "success": True,
            "backup_file": backup_file,
            "total_records": total_records,
            "file_size": file_size,
            "timestamp": timestamp,
            "tables": {table: len(backup_data[table]) for table in tables}
        }

    except Exception as e:
        # 실패 로그 기록
        try:
            cursor.execute("""
                INSERT INTO db_management_logs
                (action_type, operator_name, action_result, details, ip_address)
                VALUES (%s, %s, %s, %s, %s)
            """, ('backup', f"{operator_name} ({instructor_code})", 'fail', str(e), client_ip))
            conn.commit()
        except:
            pass
        raise HTTPException(status_code=500, detail=f"백업 생성 실패: {str(e)}")
    finally:
        conn.close()


@app.post("/api/db-management/reset")
async def reset_database(request: Request, data: dict):
    """DB 초기화 (테이블 선택 가능, 백업 후 진행)"""
    import json
    from datetime import datetime, date, timedelta

    operator_name = data.get('operator_name', '')
    instructor_code = data.get('instructor_code', '')
    selected_tables = data.get('tables', [])  # 빈 리스트면 기본 테이블 삭제

    if not operator_name:
        raise HTTPException(status_code=400, detail="작업자 정보가 필요합니다")

    client_ip = request.client.host if request.client else 'unknown'

    # 먼저 백업 생성
    backup_result = await create_backup_with_log(request, data)

    if not backup_result.get('success'):
        raise HTTPException(status_code=500, detail="백업 생성 실패로 초기화를 중단합니다")

    backup_file = backup_result.get('backup_file', '')

    conn = get_db_connection()
    try:
        cursor = conn.cursor()

        # 삭제 가능한 테이블 목록 (외래키 순서 고려)
        all_clearable_tables = [
            'team_activity_logs', 'consultations', 'class_notes', 'training_logs',
            'timetables', 'notices', 'projects', 'course_subjects', 'students',
            'instructors', 'subjects', 'courses', 'holidays', 'system_settings'
        ]

        # 기본 초기화 대상 (시스템 설정, 강사 정보, 과목 등은 유지)
        default_tables = [
            'team_activity_logs', 'consultations', 'class_notes', 'training_logs',
            'timetables', 'notices', 'projects', 'course_subjects', 'students'
        ]

        # 선택된 테이블만 삭제 (빈 리스트면 기본 테이블)
        tables_to_clear = selected_tables if selected_tables else default_tables
        # 외래키 순서 유지
        tables_to_clear = [t for t in all_clearable_tables if t in tables_to_clear]

        is_partial = len(selected_tables) > 0
        action_desc = f"선택 삭제: {', '.join(tables_to_clear)}" if is_partial else "기본 초기화"

        deleted_counts = {}
        for table in tables_to_clear:
            try:
                cursor.execute(f"SELECT COUNT(*) as cnt FROM {table}")
                count = cursor.fetchone()[0]
                cursor.execute(f"DELETE FROM {table}")
                deleted_counts[table] = count
            except Exception as e:
                print(f"[WARN] {table} 초기화 실패: {e}")
                deleted_counts[table] = 0

        conn.commit()

        total_deleted = sum(deleted_counts.values())

        # 로그 기록
        cursor.execute("""
            INSERT INTO db_management_logs
            (action_type, operator_name, action_result, backup_file, details, ip_address)
            VALUES (%s, %s, %s, %s, %s, %s)
        """, (
            'reset' if not is_partial else 'partial_reset',
            f"{operator_name} ({instructor_code})",
            'success',
            backup_file,
            f"{action_desc}. 총 {total_deleted}개 레코드 삭제.",
            client_ip
        ))
        conn.commit()

        return {
            "success": True,
            "message": "선택 테이블 초기화 완료" if is_partial else "DB 초기화 완료",
            "backup_file": backup_file,
            "deleted_counts": deleted_counts,
            "deleted_tables": tables_to_clear,
            "total_deleted": total_deleted,
            "is_partial": is_partial
        }

    except Exception as e:
        conn.rollback()
        # 실패 로그 기록
        try:
            cursor.execute("""
                INSERT INTO db_management_logs
                (action_type, operator_name, action_result, backup_file, details, ip_address)
                VALUES (%s, %s, %s, %s, %s, %s)
            """, ('reset', f"{operator_name} ({instructor_code})", 'fail', backup_file, str(e), client_ip))
            conn.commit()
        except:
            pass
        raise HTTPException(status_code=500, detail=f"DB 초기화 실패: {str(e)}")
    finally:
        conn.close()


@app.post("/api/db-management/restore")
async def restore_database(request: Request, data: dict):
    """백업 파일에서 DB 복구 (테이블 선택 가능)"""
    import json
    from datetime import datetime

    operator_name = data.get('operator_name', '')
    instructor_code = data.get('instructor_code', '')
    backup_file = data.get('backup_file', '')
    selected_tables = data.get('tables', [])  # 빈 리스트면 전체 복구

    if not operator_name:
        raise HTTPException(status_code=400, detail="작업자 정보가 필요합니다")
    if not backup_file:
        raise HTTPException(status_code=400, detail="복구할 백업 파일을 선택해주세요")

    client_ip = request.client.host if request.client else 'unknown'
    backup_dir = '/home/user/webapp/backend/backups'
    backup_path = f'{backup_dir}/{backup_file}'

    # 백업 파일 존재 확인
    if not os.path.exists(backup_path):
        raise HTTPException(status_code=404, detail="백업 파일을 찾을 수 없습니다")

    # 복구 전 현재 상태 백업
    pre_restore_backup = await create_backup_with_log(request, {
        'operator_name': f"{operator_name} (복구 전 자동백업)",
        'instructor_code': instructor_code
    })

    conn = get_db_connection()
    try:
        cursor = conn.cursor()

        # 백업 파일 읽기
        with open(backup_path, 'r', encoding='utf-8') as f:
            backup_data = json.load(f)

        restored_counts = {}
        errors = []

        # 복구 순서 (외래키 제약조건 고려)
        all_tables = [
            'system_settings', 'holidays', 'courses', 'subjects', 'instructors',
            'students', 'course_subjects', 'projects', 'timetables',
            'training_logs', 'class_notes', 'consultations', 'notices',
            'team_activity_logs'
        ]

        # 선택된 테이블만 복구 (빈 리스트면 전체)
        restore_order = selected_tables if selected_tables else all_tables
        # 전체 테이블 순서 기준으로 정렬 (외래키 순서 유지)
        restore_order = [t for t in all_tables if t in restore_order]

        is_partial = len(selected_tables) > 0
        action_desc = f"선택 복구: {', '.join(restore_order)}" if is_partial else "전체 복구"

        # 기존 데이터 삭제 (역순으로)
        for table in reversed(restore_order):
            if table in backup_data and table != 'db_management_logs':
                try:
                    cursor.execute(f"DELETE FROM {table}")
                except Exception as e:
                    print(f"[WARN] {table} 삭제 실패: {e}")

        conn.commit()

        # 데이터 복구
        for table in restore_order:
            if table not in backup_data or table == 'db_management_logs':
                continue

            rows = backup_data[table]
            if not rows:
                restored_counts[table] = 0
                continue

            try:
                # 첫 번째 행에서 컬럼 이름 가져오기
                columns = list(rows[0].keys())
                placeholders = ', '.join(['%s'] * len(columns))
                columns_str = ', '.join([f'`{col}`' for col in columns])

                insert_sql = f"INSERT INTO `{table}` ({columns_str}) VALUES ({placeholders})"

                success_count = 0
                for row in rows:
                    try:
                        values = [row.get(col) for col in columns]
                        cursor.execute(insert_sql, values)
                        success_count += 1
                    except Exception as row_error:
                        # 개별 행 오류는 건너뛰고 계속 진행
                        pass

                restored_counts[table] = success_count
            except Exception as e:
                errors.append(f"{table}: {str(e)}")
                restored_counts[table] = 0

        conn.commit()

        total_restored = sum(restored_counts.values())

        # 로그 기록
        log_details = f"{action_desc}. 총 {total_restored}개 레코드 복구. 복구 전 백업: {pre_restore_backup.get('backup_file', 'N/A')}"
        cursor.execute("""
            INSERT INTO db_management_logs
            (action_type, operator_name, action_result, backup_file, details, ip_address)
            VALUES (%s, %s, %s, %s, %s, %s)
        """, (
            'restore' if not is_partial else 'partial_restore',
            f"{operator_name} ({instructor_code})",
            'success',
            backup_file,
            log_details,
            client_ip
        ))
        conn.commit()

        return {
            "success": True,
            "message": "선택 테이블 복구 완료" if is_partial else "DB 복구 완료",
            "backup_file": backup_file,
            "pre_restore_backup": pre_restore_backup.get('backup_file', ''),
            "restored_counts": restored_counts,
            "restored_tables": restore_order,
            "total_restored": total_restored,
            "is_partial": is_partial,
            "errors": errors if errors else None
        }

    except Exception as e:
        conn.rollback()
        # 실패 로그 기록
        try:
            cursor.execute("""
                INSERT INTO db_management_logs
                (action_type, operator_name, action_result, backup_file, details, ip_address)
                VALUES (%s, %s, %s, %s, %s, %s)
            """, ('restore', f"{operator_name} ({instructor_code})", 'fail', backup_file, str(e), client_ip))
            conn.commit()
        except:
            pass
        raise HTTPException(status_code=500, detail=f"DB 복구 실패: {str(e)}")
    finally:
        conn.close()


@app.get("/api/db-management/backup-info/{filename}")
async def get_backup_info(filename: str):
    """백업 파일의 테이블 정보 조회"""
    import json

    backup_dir = '/home/user/webapp/backend/backups'
    backup_path = f'{backup_dir}/{filename}'

    if not os.path.exists(backup_path):
        raise HTTPException(status_code=404, detail="백업 파일을 찾을 수 없습니다")

    try:
        with open(backup_path, 'r', encoding='utf-8') as f:
            backup_data = json.load(f)

        # 테이블별 정보 (한글 이름 매핑)
        table_names_kr = {
            'system_settings': '시스템 설정',
            'holidays': '공휴일',
            'courses': '과정',
            'subjects': '과목',
            'instructors': '강사',
            'students': '학생',
            'course_subjects': '과정-과목 연결',
            'projects': '프로젝트',
            'timetables': '시간표',
            'training_logs': '훈련일지',
            'class_notes': '수업일지',
            'consultations': '상담',
            'notices': '공지사항',
            'team_activity_logs': '팀활동 로그'
        }

        tables_info = []
        for table, rows in backup_data.items():
            if table == 'db_management_logs':
                continue
            if isinstance(rows, list):
                tables_info.append({
                    'table': table,
                    'name_kr': table_names_kr.get(table, table),
                    'count': len(rows)
                })

        # 순서 정렬 (외래키 고려)
        order = ['system_settings', 'holidays', 'courses', 'subjects', 'instructors',
                 'students', 'course_subjects', 'projects', 'timetables',
                 'training_logs', 'class_notes', 'consultations', 'notices', 'team_activity_logs']
        tables_info.sort(key=lambda x: order.index(x['table']) if x['table'] in order else 999)

        return {
            "filename": filename,
            "tables": tables_info,
            "total_records": sum(t['count'] for t in tables_info)
        }
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="백업 파일 형식이 올바르지 않습니다")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"파일 읽기 실패: {str(e)}")


@app.get("/api/db-management/current-tables")
async def get_current_tables():
    """현재 DB의 테이블별 레코드 수 조회"""
    conn = get_db_connection()
    try:
        cursor = conn.cursor()

        table_names_kr = {
            'system_settings': '시스템 설정',
            'holidays': '공휴일',
            'courses': '과정',
            'subjects': '과목',
            'instructors': '강사',
            'students': '학생',
            'course_subjects': '과정-과목 연결',
            'projects': '프로젝트',
            'timetables': '시간표',
            'training_logs': '훈련일지',
            'class_notes': '수업일지',
            'consultations': '상담',
            'notices': '공지사항',
            'team_activity_logs': '팀활동 로그'
        }

        tables = ['system_settings', 'holidays', 'courses', 'subjects', 'instructors',
                  'students', 'course_subjects', 'projects', 'timetables',
                  'training_logs', 'class_notes', 'consultations', 'notices', 'team_activity_logs']

        tables_info = []
        for table in tables:
            try:
                cursor.execute(f"SELECT COUNT(*) FROM {table}")
                count = cursor.fetchone()[0]
                tables_info.append({
                    'table': table,
                    'name_kr': table_names_kr.get(table, table),
                    'count': count
                })
            except:
                pass

        return {
            "tables": tables_info,
            "total_records": sum(t['count'] for t in tables_info)
        }
    finally:
        conn.close()


@app.get("/api/db-management/logs")
async def get_db_management_logs(limit: int = 50):
    """DB 관리 로그 조회"""
    conn = get_db_connection()
    try:
        cursor = conn.cursor(pymysql.cursors.DictCursor)
        cursor.execute("""
            SELECT * FROM db_management_logs
            ORDER BY created_at DESC
            LIMIT %s
        """, (limit,))
        logs = cursor.fetchall()
        return {"logs": logs}
    finally:
        conn.close()

if __name__ == "__main__":
    import uvicorn
    # 파일 업로드 크기 제한 100MB로 증가
    uvicorn.run(
        app, 
        host="0.0.0.0", 
        port=8000,
        limit_max_requests=10000,
        timeout_keep_alive=300
    )


# ============================================
# RAG (Retrieval-Augmented Generation) API
# ============================================

from rag.document_loader import DocumentLoader
from rag.vector_store import VectorStoreManager
from rag.rag_chain import RAGChain
import shutil
from typing import Optional

# RAG 전역 인스턴스 (앱 시작 시 초기화)
vector_store_manager = None
document_loader = None

# RAG 백그라운드 태스크 상태 관리
rag_task_status = {}  # {task_id: {status, filename, progress, chunks, error, ...}}

def _process_rag_upload(task_id, file_path, metadata, original_filename):
    """백그라운드 스레드에서 RAG 문서 업로드 처리 (파싱→임베딩→저장)"""
    global vector_store_manager, document_loader
    try:
        rag_task_status[task_id]['status'] = 'parsing'
        print(f"[RAG Task {task_id}] 문서 파싱 중: {original_filename}")
        documents = document_loader.load_document(str(file_path), metadata)

        if not documents:
            rag_task_status[task_id]['status'] = 'failed'
            rag_task_status[task_id]['error'] = '문서에서 텍스트를 추출할 수 없습니다'
            return

        rag_task_status[task_id]['chunks'] = len(documents)
        rag_task_status[task_id]['status'] = 'embedding'
        print(f"[RAG Task {task_id}] 임베딩 중: {len(documents)}개 청크")

        texts = [doc.page_content for doc in documents]
        metadatas = [doc.metadata for doc in documents]
        doc_ids = vector_store_manager.add_documents(texts, metadatas)

        rag_task_status[task_id]['status'] = 'completed'
        rag_task_status[task_id]['document_ids'] = doc_ids
        rag_task_status[task_id]['vector_count'] = len(doc_ids)
        print(f"[RAG Task {task_id}] 완료: {len(doc_ids)}개 벡터 저장")

    except Exception as e:
        print(f"[RAG Task {task_id}] 실패: {e}")
        rag_task_status[task_id]['status'] = 'failed'
        rag_task_status[task_id]['error'] = str(e)


def _process_rag_index(task_id, file_path, metadata, filename):
    """백그라운드 스레드에서 RAG 문서 인덱싱 처리"""
    global vector_store_manager, document_loader
    try:
        rag_task_status[task_id]['status'] = 'parsing'
        print(f"[RAG Task {task_id}] 문서 파싱 중: {filename}")
        documents = document_loader.load_document(str(file_path), metadata)

        if not documents:
            rag_task_status[task_id]['status'] = 'failed'
            rag_task_status[task_id]['error'] = '문서에서 텍스트를 추출할 수 없습니다'
            return

        rag_task_status[task_id]['chunks'] = len(documents)
        rag_task_status[task_id]['status'] = 'embedding'
        print(f"[RAG Task {task_id}] 임베딩 중: {len(documents)}개 청크")

        texts = [doc.page_content for doc in documents]
        metadatas = [doc.metadata for doc in documents]
        doc_ids = vector_store_manager.add_documents(texts, metadatas)

        rag_task_status[task_id]['status'] = 'completed'
        rag_task_status[task_id]['chunks'] = len(documents)
        rag_task_status[task_id]['vector_count'] = len(doc_ids)
        print(f"[RAG Task {task_id}] 인덱싱 완료: {len(doc_ids)}개 벡터 저장")

    except Exception as e:
        print(f"[RAG Task {task_id}] 인덱싱 실패: {e}")
        import traceback
        traceback.print_exc()
        rag_task_status[task_id]['status'] = 'failed'
        rag_task_status[task_id]['error'] = str(e)

def init_rag():
    """RAG 시스템 초기화"""
    global vector_store_manager, document_loader
    
    print("[INFO] RAG 시스템 초기화 중...")
    
    try:
        # 문서 로더 초기화
        document_loader = DocumentLoader(chunk_size=1000, chunk_overlap=200)
        
        # 벡터 DB 경로 (절대 경로로 통일)
        from pathlib import Path
        project_root = Path(__file__).parent.parent  # /home/user/webapp
        vector_db_path = project_root / "backend" / "vector_db"
        vector_db_path.mkdir(exist_ok=True, parents=True)
        
        # 벡터 스토어 초기화
        vector_store_manager = VectorStoreManager(
            persist_directory=str(vector_db_path),
            collection_name="biohealth_docs"
        )
        
        # RAG 시스템 초기화 완료
        pass
    except Exception as e:
        # RAG 기능 사용을 위해 pip install -r requirements_rag.txt 필요
        pass


def load_default_documents():
    """documents 폴더의 기본 문서들을 RAG에 자동 로드 (중복 체크)"""
    global vector_store_manager, document_loader
    
    if not vector_store_manager or not document_loader:
        print("[WARN] RAG 시스템이 초기화되지 않아 기본 문서를 로드할 수 없습니다")
        return
    
    # 이미 문서가 있으면 건너뛰기
    current_doc_count = vector_store_manager.count_documents()
    if current_doc_count > 0:
        print(f"[INFO] 이미 {current_doc_count}개 문서가 저장되어 있습니다. 자동 로드 건너뜀")
        return
    
    documents_dir = Path("./documents")
    
    # documents 폴더가 없으면 생성
    if not documents_dir.exists():
        documents_dir.mkdir(parents=True)
        print("[INFO] documents 폴더가 생성되었습니다")
        return
    
    # 지원하는 파일 형식
    supported_extensions = ['.pdf', '.docx', '.doc', '.txt']
    
    # documents 폴더의 모든 파일 검색
    doc_files = []
    for ext in supported_extensions:
        doc_files.extend(documents_dir.glob(f'*{ext}'))
    
    if not doc_files:
        print("[INFO] documents 폴더에 문서가 없습니다")
        print("[TIP] 교재 및 교육자료를 documents 폴더에 넣어주세요")
        return
    
    print(f"\n[DOC] 기본 문서 자동 로드 시작 ({len(doc_files)}개 파일)")
    print("=" * 60)
    
    loaded_count = 0
    skipped_count = 0
    
    for doc_path in doc_files:
        try:
            # 파일명에서 메타데이터 추출
            filename = doc_path.stem
            parts = filename.split('_')
            
            metadata = {
                'original_filename': doc_path.name,
                'upload_date': datetime.now().strftime('%Y-%m-%d'),
                'file_size': doc_path.stat().st_size,
                'auto_loaded': True
            }
            
            # 파일명에서 과목, 강사명 등 추출 시도
            if len(parts) >= 2:
                metadata['subject'] = parts[1] if len(parts) > 1 else ''
                metadata['instructor'] = parts[2] if len(parts) > 2 else ''
            
            # 문서 로드
            documents = document_loader.load_document(str(doc_path), metadata)
            
            if not documents:
                print(f"[WARN] {doc_path.name}: 텍스트를 추출할 수 없습니다")
                skipped_count += 1
                continue
            
            # 텍스트와 메타데이터 분리
            texts = [doc.page_content for doc in documents]
            metadatas = [doc.metadata for doc in documents]
            
            # 벡터 스토어에 추가
            doc_ids = vector_store_manager.add_documents(texts, metadatas)
            
            print(f"[OK] {doc_path.name}: {len(documents)}개 청크 로드 완료")
            loaded_count += 1
            
        except Exception as e:
            print(f"[ERROR] {doc_path.name}: 로드 실패 - {str(e)}")
            skipped_count += 1
    
    print("=" * 60)
    print(f"[STAT] 기본 문서 로드 완료: {loaded_count}개 성공, {skipped_count}개 실패")
    print(f"[DOC] 현재 총 문서 수: {vector_store_manager.count_documents()}")
    print()


# 앱 시작 시 RAG 초기화
try:
    init_rag()
except:
    print("[WARN] RAG 초기화 실패 - RAG 기능 비활성화됨")


# ==================== Startup 이벤트 ====================
def auto_migrate_tables():
    """서버 시작 시 필수 테이블 자동 생성/마이그레이션"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        # exam_bank 테이블
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS exam_bank (
                exam_id INT AUTO_INCREMENT PRIMARY KEY,
                exam_name VARCHAR(200) NOT NULL,
                subject VARCHAR(100),
                exam_date DATE,
                exam_time TIME,
                total_questions INT DEFAULT 0,
                question_type VARCHAR(50) DEFAULT 'multiple_choice',
                difficulty VARCHAR(20) DEFAULT 'medium',
                instructor_code VARCHAR(50),
                description TEXT,
                questions_text LONGTEXT,
                sources TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # exam_bank_questions 테이블
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS exam_bank_questions (
                id INT AUTO_INCREMENT PRIMARY KEY,
                exam_id INT NOT NULL,
                question_number INT,
                question_text TEXT,
                question_type VARCHAR(50) DEFAULT 'multiple_choice',
                options TEXT,
                correct_answer VARCHAR(500),
                explanation TEXT,
                source_reference VARCHAR(500),
                points INT DEFAULT 10,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (exam_id) REFERENCES exam_bank(exam_id) ON DELETE CASCADE
            )
        """)

        # online_exams 테이블
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS online_exams (
                id INT AUTO_INCREMENT PRIMARY KEY,
                title VARCHAR(200) NOT NULL,
                exam_type ENUM('exam', 'quiz', 'assignment') DEFAULT 'exam',
                exam_bank_id INT,
                course_code VARCHAR(50),
                instructor_code VARCHAR(50),
                duration INT DEFAULT 60,
                scheduled_at DATETIME,
                started_at DATETIME,
                ended_at DATETIME,
                deadline DATETIME,
                description TEXT,
                pass_score INT DEFAULT 60,
                shuffle_questions TINYINT DEFAULT 0,
                shuffle_options TINYINT DEFAULT 0,
                show_result TINYINT DEFAULT 1,
                status ENUM('scheduled', 'waiting', 'ongoing', 'ended', 'graded') DEFAULT 'scheduled',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (exam_bank_id) REFERENCES exam_bank(exam_id) ON DELETE SET NULL
            )
        """)

        # online_exam_participants 테이블
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS online_exam_participants (
                id INT AUTO_INCREMENT PRIMARY KEY,
                online_exam_id INT NOT NULL,
                student_id INT NOT NULL,
                status ENUM('waiting', 'taking', 'submitted', 'graded') DEFAULT 'waiting',
                entered_at DATETIME,
                started_at DATETIME,
                submitted_at DATETIME,
                answers JSON,
                file_path VARCHAR(500),
                file_name VARCHAR(255),
                score INT,
                feedback TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (online_exam_id) REFERENCES online_exams(id) ON DELETE CASCADE
            )
        """)

        # notices 테이블 컬럼 추가
        try:
            cursor.execute("ALTER TABLE notices ADD COLUMN notice_type ENUM('all', 'course', 'subject') DEFAULT 'all'")
        except:
            pass
        try:
            cursor.execute("ALTER TABLE notices ADD COLUMN target_code VARCHAR(50) DEFAULT NULL")
        except:
            pass

        conn.commit()
        conn.close()
        return True
    except Exception as e:
        return False


@app.on_event("startup")
async def startup_event():
    """서버 시작 시 실행"""
    auto_migrate_tables()
    print("[OK] Server started: http://localhost:8000")


@app.post("/api/rag/upload")
async def upload_rag_document(
    file: UploadFile = File(...),
    subject: Optional[str] = Form(None),
    instructor: Optional[str] = Form(None),
    date: Optional[str] = Form(None),
    description: Optional[str] = Form(None)
):
    """
    RAG 문서 업로드
    
    - PDF, DOCX, TXT 파일 지원
    - 자동으로 벡터 DB에 저장
    """
    if not vector_store_manager or not document_loader:
        raise HTTPException(status_code=503, detail="RAG 시스템이 초기화되지 않았습니다")
    
    # 파일 확장자 확인
    file_ext = Path(file.filename).suffix.lower()
    if file_ext not in ['.pdf', '.docx', '.doc', '.txt']:
        raise HTTPException(
            status_code=400, 
            detail="지원하지 않는 파일 형식입니다. PDF, DOCX, TXT 파일만 업로드 가능합니다."
        )
    
    # 파일 크기 확인 (50MB 제한)
    file_size = 0
    content = await file.read()
    file_size = len(content)
    
    if file_size > 50 * 1024 * 1024:  # 50MB
        raise HTTPException(status_code=400, detail="파일 크기는 50MB 이하여야 합니다")
    
    try:
        # 파일 저장
        upload_dir = Path("./backend/uploads")
        upload_dir.mkdir(exist_ok=True)
        
        # 고유 파일명 생성
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        safe_filename = f"{timestamp}_{file.filename}"
        file_path = upload_dir / safe_filename
        
        with open(file_path, "wb") as f:
            f.write(content)
        
        print(f"[OK] File saved: {file_path}")
        
        # 메타데이터 구성
        metadata = {
            "original_filename": file.filename,
            "upload_date": datetime.now().isoformat(),
            "file_size": file_size,
            "subject": subject or "미지정",
            "instructor": instructor or "미지정",
            "date": date or datetime.now().strftime("%Y-%m-%d"),
            "description": description or ""
        }

        # 백그라운드 태스크로 파싱/임베딩 처리
        task_id = str(uuid.uuid4())
        rag_task_status[task_id] = {
            "status": "pending",
            "filename": file.filename,
            "file_path": str(file_path),
            "progress": 0,
            "chunks": 0,
            "error": None,
            "metadata": metadata
        }

        thread = threading.Thread(
            target=_process_rag_upload,
            args=(task_id, file_path, metadata, file.filename),
            daemon=True
        )
        thread.start()

        return {
            "success": True,
            "task_id": task_id,
            "status": "processing",
            "message": "문서 업로드 완료. 백그라운드에서 인덱싱 처리 중입니다.",
            "filename": file.filename,
            "file_path": str(file_path)
        }

    except Exception as e:
        print(f"[ERROR] 문서 업로드 실패: {e}")
        raise HTTPException(status_code=500, detail=f"문서 업로드 실패: {str(e)}")


@app.get("/api/rag/documents")
async def list_rag_documents(limit: int = 100):
    """RAG 문서 목록 조회"""
    if not vector_store_manager:
        raise HTTPException(status_code=503, detail="RAG 시스템이 초기화되지 않았습니다")
    
    try:
        documents = vector_store_manager.get_all_documents()
        count = vector_store_manager.count_documents()
        
        # 중복 제거 (원본 파일명 기준)
        unique_docs = {}
        for doc in documents:
            metadata = doc.get('metadata', {})
            filename = metadata.get('filename', metadata.get('source', '알 수 없음'))
            if filename not in unique_docs:
                unique_docs[filename] = {
                    'filename': filename,
                    'document_id': metadata.get('document_id', ''),
                    'uploaded_at': metadata.get('uploaded_at', ''),
                    'chunks_count': 1
                }
            else:
                unique_docs[filename]['chunks_count'] += 1
        
        return {
            "success": True,
            "total_chunks": count,
            "unique_documents": len(unique_docs),
            "documents": list(unique_docs.values())
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"문서 목록 조회 실패: {str(e)}")


@app.post("/api/rag/chat")
async def rag_chat(request: Request):
    """
    RAG 기반 채팅 (개선된 버전)
    
    Body:
        - message: 사용자 질문
        - k: 검색할 문서 수 (기본 5)
        - model: AI 모델 (groq, gemini, gemma)
        - document_context: 특정 문서로 제한 (선택, 파일명)
    
    특수 기능:
        - 통계/숫자 질문 감지 시 DB 직접 조회
        - 유사도 임계값 체크
        - 문서 특정 컨텍스트 지원
    """
    if not vector_store_manager:
        raise HTTPException(status_code=503, detail="RAG 시스템이 초기화되지 않았습니다")
    
    try:
        data = await request.json()
        message = data.get('message', '').strip()
        k = data.get('k', 5)  # 기본값 3에서 5로 증가
        model = data.get('model', 'groq').lower()
        document_context = data.get('document_context', None)  # 특정 문서로 제한 (문자열 또는 배열)
        
        if not message:
            raise HTTPException(status_code=400, detail="메시지를 입력해주세요")
        
        # 문서 컨텍스트 정규화 (문자열 -> 배열)
        if document_context:
            if isinstance(document_context, str):
                document_context = [document_context]
            elif not isinstance(document_context, list):
                document_context = None
        
        # 문서 컨텍스트가 지정된 경우 메시지에 추가
        if document_context and len(document_context) > 0:
            doc_names = ', '.join(document_context)
            print(f"[DOC] Document context ({len(document_context)}): {doc_names}")
            message_with_context = f"[문서: {doc_names}에 대한 질문] {message}"
        else:
            message_with_context = message
            document_context = None
        
        # ==================== 통계/숫자 질문 감지 ====================
        message_lower = message.lower()
        
        # 강사 수 질문 감지
        if any(keyword in message_lower for keyword in ['강사', '강사수', '강사 수', '강사는', '강사 수는', '몇 명', '몇명', '인원']):
            if any(keyword in message_lower for keyword in ['수', '명', '얼마', '몇', '많', '인원']):
                try:
                    conn = get_db_connection()
                    cursor = conn.cursor(pymysql.cursors.DictCursor)
                    
                    # 강사 수 조회
                    cursor.execute("SELECT COUNT(*) as count FROM instructors")
                    result = cursor.fetchone()
                    instructor_count = result['count'] if result else 0
                    
                    # 강사 이름 목록 (상위 10명)
                    cursor.execute("""
                        SELECT name, email 
                        FROM instructors 
                        ORDER BY id 
                        LIMIT 10
                    """)
                    instructor_list = cursor.fetchall()
                    
                    conn.close()
                    
                    # 답변 생성
                    answer = f"현재 시스템에 등록된 강사 수는 **총 {instructor_count}명**입니다.\n\n"
                    
                    if instructor_list and len(instructor_list) > 0:
                        answer += "📋 **등록된 강사 (상위 10명):**\n"
                        for idx, instructor in enumerate(instructor_list, 1):
                            name = instructor.get('name', '이름없음')
                            email = instructor.get('email', '')
                            if email:
                                answer += f"{idx}. {name} ({email})\n"
                            else:
                                answer += f"{idx}. {name}\n"
                    
                    answer += "\n💡 *이 정보는 데이터베이스에서 실시간으로 조회되었습니다.*"
                    
                    return {
                        "success": True,
                        "model": "database",
                        "answer": answer,
                        "sources": [{
                            'source': 'instructors 테이블 (DB 직접 조회)',
                            'similarity': 1.0,
                            'content': f"총 강사 수: {instructor_count}명"
                        }],
                        "message": message,
                        "query_type": "statistics"
                    }
                except Exception as e:
                    print(f"[ERROR] 강사 수 조회 실패: {e}")
                    # 실패 시 RAG로 폴백
        
        # 학생 수 질문 감지
        if any(keyword in message_lower for keyword in ['학생', '학생수', '학생 수', '수강생', '훈련생']):
            if any(keyword in message_lower for keyword in ['수', '명', '얼마', '몇', '많', '인원']):
                try:
                    conn = get_db_connection()
                    cursor = conn.cursor(pymysql.cursors.DictCursor)
                    
                    cursor.execute("SELECT COUNT(*) as count FROM students")
                    result = cursor.fetchone()
                    student_count = result['count'] if result else 0
                    
                    # 과정별 통계
                    cursor.execute("""
                        SELECT course_code, COUNT(*) as count 
                        FROM students 
                        GROUP BY course_code 
                        ORDER BY count DESC 
                        LIMIT 5
                    """)
                    course_stats = cursor.fetchall()
                    
                    conn.close()
                    
                    answer = f"현재 시스템에 등록된 학생 수는 **총 {student_count}명**입니다.\n\n"
                    
                    if course_stats:
                        answer += "📊 **과정별 학생 수 (상위 5개):**\n"
                        for stat in course_stats:
                            answer += f"- {stat['course_code']}: {stat['count']}명\n"
                    
                    answer += "\n💡 *이 정보는 데이터베이스에서 실시간으로 조회되었습니다.*"
                    
                    return {
                        "success": True,
                        "model": "database",
                        "answer": answer,
                        "sources": [{
                            'source': 'students 테이블 (DB 직접 조회)',
                            'similarity': 1.0,
                            'content': f"총 학생 수: {student_count}명"
                        }],
                        "message": message,
                        "query_type": "statistics"
                    }
                except Exception as e:
                    print(f"[ERROR] 학생 수 조회 실패: {e}")
        
        # ==================== RAG 처리 ====================
        # API 키 가져오기 (DB → 헤더 → 환경변수 순서)
        conn = get_db_connection()
        cursor = conn.cursor(pymysql.cursors.DictCursor)
        cursor.execute("SELECT setting_key, setting_value FROM system_settings WHERE setting_key IN ('groq_api_key', 'gemini_api_key')")
        db_settings_list = cursor.fetchall()
        conn.close()
        
        db_settings = {item['setting_key']: item['setting_value'] for item in db_settings_list}
        
        groq_api_key = request.headers.get('X-GROQ-API-Key') or db_settings.get('groq_api_key', '') or os.getenv('GROQ_API_KEY', '')
        gemini_api_key = request.headers.get('X-Gemini-API-Key') or db_settings.get('gemini_api_key', '') or os.getenv('GOOGLE_CLOUD_TTS_API_KEY', '')
        
        # 모델에 따라 API 키 선택
        if model in ['groq', 'gemma']:
            api_key = groq_api_key
            api_type = 'groq'
        elif model == 'gemini':
            api_key = gemini_api_key
            api_type = 'gemini'
        else:
            raise HTTPException(status_code=400, detail="지원하지 않는 모델입니다")
        
        if not api_key:
            error_msg = f"{api_type.upper()} API 키가 설정되지 않았습니다. 시스템 설정에서 API 키를 입력해주세요."
            print(f"[ERROR] {error_msg}")
            raise HTTPException(
                status_code=400, 
                detail=error_msg
            )
        
        # RAG 체인 생성
        rag_chain = RAGChain(vector_store_manager, api_key, api_type)
        
        # RAG 질문 처리 (유사도 임계값 0.008 = 0.8%)
        print(f"💬 RAG 질문: {message_with_context if document_context else message}")
        result = await rag_chain.query(message_with_context if document_context else message, k=k, min_similarity=0.008)
        
        # 문서 컨텍스트가 지정된 경우 결과 필터링 (복수 문서 지원)
        if document_context and len(document_context) > 0:
            filtered_sources = []
            for source in result.get('sources', []):
                metadata = source.get('metadata', {})
                source_filename = metadata.get('filename', '') or metadata.get('original_filename', '')
                
                # 지정된 문서 목록에 포함되는 경우만 포함
                for doc_name in document_context:
                    if doc_name in source_filename or source_filename in doc_name:
                        filtered_sources.append(source)
                        break
            
            # 필터링된 소스가 있으면 사용, 없으면 모든 소스 사용
            if filtered_sources:
                result['sources'] = filtered_sources
                doc_names = ', '.join(document_context)
                print(f"[DOC] Document filter ({len(document_context)}): {len(filtered_sources)}/{len(result.get('sources', []))} sources")
            else:
                doc_names = ', '.join(document_context)
                print(f"⚠️ 문서 '{doc_names}'에서 관련 내용을 찾을 수 없어 전체 검색 결과를 사용합니다")
        
        return {
            "success": True,
            "model": model,
            "answer": result['answer'],
            "sources": result['sources'],
            "message": message,
            "document_context": document_context,
            "query_type": "rag"
        }
        
    except HTTPException as he:
        print(f"[ERROR] RAG 채팅 요청 실패: {he.detail}")
        raise he
    except Exception as e:
        print(f"[ERROR] RAG 채팅 실패: {e}")
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"RAG 채팅 실패: {str(e)}")


@app.post("/api/rag/search")
async def rag_search(
    query: str = Form(...),
    k: int = Form(5),
    subject: Optional[str] = Form(None)
):
    """
    RAG 문서 검색
    
    - 질문과 유사한 문서 검색
    - 메타데이터 필터링 지원
    """
    if not vector_store_manager:
        raise HTTPException(status_code=503, detail="RAG 시스템이 초기화되지 않았습니다")
    
    try:
        # 검색 (필터 없이)
        results = vector_store_manager.search_with_score(query, k=k)
        
        # 결과 포맷팅
        search_results = []
        for result in results:
            search_results.append({
                'content': result.get('content', ''),
                'similarity': float(result.get('score', 0)),
                'metadata': result.get('metadata', {})
            })
        
        return {
            "success": True,
            "query": query,
            "results_count": len(search_results),
            "results": search_results
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"문서 검색 실패: {str(e)}")


@app.delete("/api/rag/clear")
async def clear_rag_database():
    """RAG 데이터베이스 초기화 (모든 문서 삭제)"""
    if not vector_store_manager:
        raise HTTPException(status_code=503, detail="RAG 시스템이 초기화되지 않았습니다")
    
    try:
        old_count = vector_store_manager.count_documents()
        vector_store_manager.delete_collection()
        
        return {
            "success": True,
            "message": "RAG 데이터베이스가 초기화되었습니다",
            "deleted_chunks": old_count
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"데이터베이스 초기화 실패: {str(e)}")


@app.get("/api/rag/status")
async def rag_status():
    """RAG 시스템 상태 확인"""
    if not vector_store_manager:
        return {
            "initialized": False,
            "message": "RAG 시스템이 초기화되지 않았습니다"
        }
    
    try:
        count = vector_store_manager.count_documents()
        
        return {
            "initialized": True,
            "document_count": count,
            "embedding_model": vector_store_manager.embedding_model,
            "collection_name": vector_store_manager.collection_name,
            "vector_db": "FAISS",
            "status": "정상"
        }
        
    except Exception as e:
        return {
            "initialized": False,
            "error": str(e)
        }


# ====================문제은행 API====================

@app.post("/api/exam-bank/generate")
async def generate_exam_questions(request: Request):
    """RAG 기반 문제 생성"""
    try:
        data = await request.json()
        exam_name = data.get('exam_name')
        subject = data.get('subject')
        exam_date = data.get('exam_date')
        num_questions = int(data.get('num_questions', 10))
        question_type = data.get('question_type', 'multiple_choice')
        difficulty = data.get('difficulty', 'medium')
        instructor_code = data.get('instructor_code', '')
        description = data.get('description', '')
        rag_documents = data.get('rag_documents', [])  # 선택된 RAG 문서 목록

        # RAG 시스템 확인 (vector_store_manager만 체크)
        if not vector_store_manager:
            raise HTTPException(status_code=503, detail="RAG 시스템이 초기화되지 않았습니다")
        
        # GROQ API 키 가져오기
        conn = get_db_connection()
        cursor = conn.cursor(pymysql.cursors.DictCursor)
        cursor.execute("SELECT setting_value FROM system_settings WHERE setting_key = 'groq_api_key'")
        result = cursor.fetchone()
        groq_api_key = result['setting_value'] if result else os.getenv('GROQ_API_KEY', '')
        conn.close()
        
        if not groq_api_key:
            raise HTTPException(status_code=400, detail="GROQ API 키가 설정되지 않았습니다")
        
        # 난이도에 따른 프롬프트 조정
        difficulty_prompts = {
            'easy': '기본적이고 쉬운 수준의',
            'medium': '중간 수준의',
            'hard': '심화되고 어려운 수준의'
        }
        difficulty_text = difficulty_prompts.get(difficulty, '중간 수준의')
        
        # 문제 유형에 따른 프롬프트
        type_prompts = {
            'multiple_choice': f'''
{num_questions}개의 {difficulty_text} 객관식 문제를 생성해주세요.

【중요 규칙】
1. 선택지는 반드시 4개, 번호(A,B,C,D) 없이 텍스트만 작성
2. 정답은 반드시 숫자(1, 2, 3, 4)로 표기
3. 각 문제에 반드시 "참고:" 필드에 출처 문서명 기재
4. 아래 형식을 정확히 따를 것

【문제 형식】
문제 1:
[문제 내용을 여기에 작성]

1) [선택지 1 텍스트만]
2) [선택지 2 텍스트만]
3) [선택지 3 텍스트만]
4) [선택지 4 텍스트만]

정답: [1 또는 2 또는 3 또는 4 중 하나]
해설: [왜 이것이 정답인지 설명]
참고: [출처 문서명, p.페이지번호] (예: 기본간호학.pdf, p.15)

---

(위 형식으로 {num_questions}개 문제 작성)
''',
            'short_answer': f'''
{num_questions}개의 {difficulty_text} 단답형 문제를 생성해주세요.

【문제 형식】
문제 1:
[문제 내용]

정답: [답]
해설: [설명]
참고: [출처 문서명, p.페이지번호]

---
''',
            'essay': f'''
{num_questions}개의 {difficulty_text} 서술형 문제를 생성해주세요.

【문제 형식】
문제 1:
[문제 내용]

모범답안: [상세 답안]
채점기준: [평가 기준]
참고: [출처 문서명, p.페이지번호]

---
''',
            'assignment': f'''
{num_questions}개의 {difficulty_text} 과제형 문제를 생성해주세요.
과제형은 학생들이 파일이나 보고서를 제출하는 형태입니다.

【문제 형식】
문제 1:
[과제 주제 및 요구사항을 상세히 작성]

제출형식: [보고서/파일/프로젝트 등]
평가기준: [평가 항목 및 배점]
참고자료: [참고할 수 있는 문서명]

---
'''
        }

        prompt = f"""
교과목: {subject if subject else '(미지정)'}
시험명: {exam_name}

{type_prompts.get(question_type, type_prompts['multiple_choice'])}

【필수 사항】
- 문제는 제공된 문서 내용을 기반으로 출제
- 각 문제의 "참고:" 필드에 출처 문서명과 페이지 번호를 반드시 명시 (예: 기본간호학.pdf, p.15)
- 객관식의 경우 선택지는 1) 2) 3) 4) 4개 고정, 정답은 숫자로 표기
"""

        # 선택된 문서가 있으면 프롬프트에 추가
        if rag_documents and len(rag_documents) > 0:
            doc_names = ', '.join(rag_documents)
            prompt = f"[참고 문서: {doc_names}]\n\n" + prompt
            print(f"[RAG] 선택된 문서 ({len(rag_documents)}개): {doc_names}")

        # RAGChain 인스턴스 생성
        rag_chain = RAGChain(vector_store_manager, groq_api_key, "groq")

        # RAG를 사용하여 문제 생성 (문제 생성은 유사도 임계값을 낮춤)
        result = await rag_chain.query(
            prompt,
            k=min(10, len(rag_documents) * 3) if rag_documents else 8,
            groq_api_key=groq_api_key,
            document_context=rag_documents if rag_documents else None,
            min_similarity=0.005  # 문제 생성 시에는 임계값을 매우 낮게 설정
        )
        
        return {
            "success": True,
            "questions_text": result['answer'],
            "sources": result.get('sources', []),
            "exam_info": {
                "exam_name": exam_name,
                "subject": subject,
                "exam_date": exam_date,
                "num_questions": num_questions,
                "question_type": question_type,
                "difficulty": difficulty
            }
        }
        
    except Exception as e:
        print(f"[ERROR] 문제 생성 실패: {str(e)}")
        raise HTTPException(status_code=500, detail=f"문제 생성 실패: {str(e)}")


@app.post("/api/exam-bank/save")
async def save_exam(request: Request):
    """생성된 문제를 데이터베이스에 저장"""
    try:
        data = await request.json()
        exam_name = data.get('exam_name')
        subject = data.get('subject')
        exam_date = data.get('exam_date')
        question_type = data.get('question_type', 'multiple_choice')
        difficulty = data.get('difficulty', 'medium')
        instructor_code = data.get('instructor_code', '')
        description = data.get('description', '')
        questions = data.get('questions', [])
        
        conn = get_db_connection()
        cursor = conn.cursor(pymysql.cursors.DictCursor)
        
        # 시험 정보 저장
        cursor.execute("""
            INSERT INTO exam_bank (exam_name, subject, exam_date, total_questions, 
                                   question_type, difficulty, instructor_code, description)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        """, (exam_name, subject, exam_date, len(questions), question_type, 
              difficulty, instructor_code, description))
        
        exam_id = cursor.lastrowid
        
        # 문제 저장
        for idx, question in enumerate(questions, 1):
            # options를 JSON 문자열로 변환
            import json
            options_json = json.dumps(question.get('options', []), ensure_ascii=False) if question.get('options') else None
            
            cursor.execute("""
                INSERT INTO exam_questions (exam_id, question_number, question_text, 
                                           question_type, options, correct_answer, 
                                           explanation, reference_page, reference_document, 
                                           difficulty, points)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """, (exam_id, idx, question.get('question_text', ''),
                  question_type, options_json, question.get('correct_answer', ''),
                  question.get('explanation', ''), question.get('reference_page', ''),
                  question.get('reference_document', ''), difficulty, 
                  question.get('points', 1)))
        
        conn.commit()
        conn.close()
        
        return {
            "success": True,
            "exam_id": exam_id,
            "message": f"시험 '{exam_name}'이(가) 저장되었습니다"
        }
        
    except Exception as e:
        print(f"[ERROR] 시험 저장 실패: {str(e)}")
        raise HTTPException(status_code=500, detail=f"시험 저장 실패: {str(e)}")


@app.get("/api/exam-bank/list")
async def get_exam_list():
    """저장된 시험 목록 조회"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor(pymysql.cursors.DictCursor)
        
        cursor.execute("""
            SELECT exam_id, exam_name, subject, exam_date, total_questions,
                   question_type, difficulty, instructor_code, description,
                   created_at
            FROM exam_bank
            ORDER BY exam_date DESC, created_at DESC
        """)
        
        exams = cursor.fetchall()
        conn.close()
        
        return {
            "success": True,
            "exams": exams
        }
        
    except Exception as e:
        print(f"[ERROR] 시험 목록 조회 실패: {str(e)}")
        raise HTTPException(status_code=500, detail=f"시험 목록 조회 실패: {str(e)}")


@app.get("/api/exam-bank/{exam_id}")
async def get_exam_detail(exam_id: int):
    """시험 상세 정보 및 문제 조회"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor(pymysql.cursors.DictCursor)
        
        # 시험 정보 조회
        cursor.execute("""
            SELECT exam_id, exam_name, subject, exam_date, total_questions,
                   question_type, difficulty, instructor_code, description,
                   created_at
            FROM exam_bank
            WHERE exam_id = %s
        """, (exam_id,))
        
        exam = cursor.fetchone()
        
        if not exam:
            raise HTTPException(status_code=404, detail="시험을 찾을 수 없습니다")
        
        # 문제 조회
        cursor.execute("""
            SELECT question_id, question_number, question_text, question_type,
                   options, correct_answer, explanation, reference_page,
                   reference_document, difficulty, points
            FROM exam_questions
            WHERE exam_id = %s
            ORDER BY question_number
        """, (exam_id,))
        
        questions = cursor.fetchall()
        
        # options JSON 파싱
        import json
        for q in questions:
            if q['options']:
                try:
                    q['options'] = json.loads(q['options'])
                except:
                    q['options'] = []
        
        conn.close()
        
        exam['questions'] = questions
        
        return {
            "success": True,
            "exam": exam
        }
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"[ERROR] 시험 상세 조회 실패: {str(e)}")
        raise HTTPException(status_code=500, detail=f"시험 상세 조회 실패: {str(e)}")


@app.delete("/api/exam-bank/{exam_id}")
async def delete_exam(exam_id: int):
    """시험 삭제"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor(pymysql.cursors.DictCursor)
        
        # 시험 존재 확인
        cursor.execute("SELECT exam_name FROM exam_bank WHERE exam_id = %s", (exam_id,))
        exam = cursor.fetchone()
        
        if not exam:
            raise HTTPException(status_code=404, detail="시험을 찾을 수 없습니다")
        
        # 시험 삭제 (CASCADE로 문제도 자동 삭제)
        cursor.execute("DELETE FROM exam_bank WHERE exam_id = %s", (exam_id,))
        conn.commit()
        conn.close()
        
        return {
            "success": True,
            "message": f"시험 '{exam['exam_name']}'이(가) 삭제되었습니다"
        }
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"[ERROR] 시험 삭제 실패: {str(e)}")
        raise HTTPException(status_code=500, detail=f"시험 삭제 실패: {str(e)}")


@app.put("/api/exam-bank/{exam_id}")
async def update_exam(exam_id: int, request: Request):
    """시험 정보 수정"""
    try:
        data = await request.json()
        
        conn = get_db_connection()
        cursor = conn.cursor(pymysql.cursors.DictCursor)
        
        # 시험 존재 확인
        cursor.execute("SELECT exam_id FROM exam_bank WHERE exam_id = %s", (exam_id,))
        if not cursor.fetchone():
            raise HTTPException(status_code=404, detail="시험을 찾을 수 없습니다")
        
        # 업데이트할 필드 구성
        update_fields = []
        params = []
        
        if 'exam_name' in data:
            update_fields.append("exam_name = %s")
            params.append(data['exam_name'])
        if 'subject' in data:
            update_fields.append("subject = %s")
            params.append(data['subject'])
        if 'exam_date' in data:
            update_fields.append("exam_date = %s")
            params.append(data['exam_date'])
        if 'difficulty' in data:
            update_fields.append("difficulty = %s")
            params.append(data['difficulty'])
        if 'description' in data:
            update_fields.append("description = %s")
            params.append(data['description'])
        
        if update_fields:
            params.append(exam_id)
            query = f"UPDATE exam_bank SET {', '.join(update_fields)} WHERE exam_id = %s"
            cursor.execute(query, params)
            conn.commit()
        
        conn.close()
        
        return {
            "success": True,
            "message": "시험 정보가 수정되었습니다"
        }
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"[ERROR] 시험 수정 실패: {str(e)}")
        raise HTTPException(status_code=500, detail=f"시험 수정 실패: {str(e)}")


# ==================== 개별 문제 CRUD API ====================

@app.post("/api/exam-bank/{exam_id}/questions")
async def add_question(exam_id: int, request: Request):
    """시험에 새 문제 추가"""
    try:
        data = await request.json()

        conn = get_db_connection()
        cursor = conn.cursor(pymysql.cursors.DictCursor)

        # 시험 존재 확인
        cursor.execute("SELECT exam_id, total_questions FROM exam_bank WHERE exam_id = %s", (exam_id,))
        exam = cursor.fetchone()
        if not exam:
            raise HTTPException(status_code=404, detail="시험을 찾을 수 없습니다")

        # 다음 문제 번호 계산
        cursor.execute("SELECT MAX(question_number) as max_num FROM exam_questions WHERE exam_id = %s", (exam_id,))
        result = cursor.fetchone()
        next_number = (result['max_num'] or 0) + 1

        # options를 JSON 문자열로 변환
        import json
        options_json = json.dumps(data.get('options', []), ensure_ascii=False) if data.get('options') else None

        # 문제 추가
        cursor.execute("""
            INSERT INTO exam_questions (exam_id, question_number, question_text,
                                        question_type, options, correct_answer,
                                        explanation, reference_page, reference_document,
                                        difficulty, points)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """, (exam_id, next_number, data.get('question_text', ''),
              data.get('question_type', 'multiple_choice'), options_json,
              data.get('correct_answer', ''), data.get('explanation', ''),
              data.get('reference_page', ''), data.get('reference_document', ''),
              data.get('difficulty', 'medium'), data.get('points', 1)))

        question_id = cursor.lastrowid

        # 시험의 total_questions 업데이트
        cursor.execute("UPDATE exam_bank SET total_questions = total_questions + 1 WHERE exam_id = %s", (exam_id,))

        conn.commit()
        conn.close()

        return {
            "success": True,
            "message": "문제가 추가되었습니다",
            "question_id": question_id,
            "question_number": next_number
        }

    except HTTPException:
        raise
    except Exception as e:
        print(f"[ERROR] 문제 추가 실패: {str(e)}")
        raise HTTPException(status_code=500, detail=f"문제 추가 실패: {str(e)}")


@app.put("/api/exam-bank/questions/{question_id}")
async def update_question(question_id: int, request: Request):
    """개별 문제 수정"""
    try:
        data = await request.json()

        conn = get_db_connection()
        cursor = conn.cursor(pymysql.cursors.DictCursor)

        # 문제 존재 확인
        cursor.execute("SELECT question_id FROM exam_questions WHERE question_id = %s", (question_id,))
        if not cursor.fetchone():
            raise HTTPException(status_code=404, detail="문제를 찾을 수 없습니다")

        # 업데이트할 필드 구성
        update_fields = []
        params = []

        if 'question_text' in data:
            update_fields.append("question_text = %s")
            params.append(data['question_text'])
        if 'question_type' in data:
            update_fields.append("question_type = %s")
            params.append(data['question_type'])
        if 'options' in data:
            import json
            update_fields.append("options = %s")
            params.append(json.dumps(data['options'], ensure_ascii=False) if data['options'] else None)
        if 'correct_answer' in data:
            update_fields.append("correct_answer = %s")
            params.append(data['correct_answer'])
        if 'explanation' in data:
            update_fields.append("explanation = %s")
            params.append(data['explanation'])
        if 'reference_page' in data:
            update_fields.append("reference_page = %s")
            params.append(data['reference_page'])
        if 'reference_document' in data:
            update_fields.append("reference_document = %s")
            params.append(data['reference_document'])
        if 'difficulty' in data:
            update_fields.append("difficulty = %s")
            params.append(data['difficulty'])
        if 'points' in data:
            update_fields.append("points = %s")
            params.append(data['points'])

        if update_fields:
            params.append(question_id)
            query = f"UPDATE exam_questions SET {', '.join(update_fields)} WHERE question_id = %s"
            cursor.execute(query, params)
            conn.commit()

        conn.close()

        return {
            "success": True,
            "message": "문제가 수정되었습니다"
        }

    except HTTPException:
        raise
    except Exception as e:
        print(f"[ERROR] 문제 수정 실패: {str(e)}")
        raise HTTPException(status_code=500, detail=f"문제 수정 실패: {str(e)}")


@app.delete("/api/exam-bank/questions/{question_id}")
async def delete_question(question_id: int):
    """개별 문제 삭제"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor(pymysql.cursors.DictCursor)

        # 문제 정보 조회 (exam_id 확인용)
        cursor.execute("SELECT exam_id, question_number FROM exam_questions WHERE question_id = %s", (question_id,))
        question = cursor.fetchone()

        if not question:
            raise HTTPException(status_code=404, detail="문제를 찾을 수 없습니다")

        exam_id = question['exam_id']
        deleted_number = question['question_number']

        # 문제 삭제
        cursor.execute("DELETE FROM exam_questions WHERE question_id = %s", (question_id,))

        # 뒤 문제들의 번호 재정렬
        cursor.execute("""
            UPDATE exam_questions
            SET question_number = question_number - 1
            WHERE exam_id = %s AND question_number > %s
        """, (exam_id, deleted_number))

        # 시험의 total_questions 업데이트
        cursor.execute("UPDATE exam_bank SET total_questions = total_questions - 1 WHERE exam_id = %s", (exam_id,))

        conn.commit()
        conn.close()

        return {
            "success": True,
            "message": "문제가 삭제되었습니다"
        }

    except HTTPException:
        raise
    except Exception as e:
        print(f"[ERROR] 문제 삭제 실패: {str(e)}")
        raise HTTPException(status_code=500, detail=f"문제 삭제 실패: {str(e)}")


# ==================== 온라인 시험 API ====================

@app.get("/api/online-exams")
async def get_online_exams(
    course_code: Optional[str] = None,
    status: Optional[str] = None,
    instructor_code: Optional[str] = None
):
    """온라인 시험 목록 조회"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor(pymysql.cursors.DictCursor)

        query = """
            SELECT oe.*, eb.exam_name as exam_bank_name, eb.total_questions,
                   c.name as course_name,
                   (SELECT COUNT(*) FROM online_exam_participants WHERE online_exam_id = oe.id) as participant_count,
                   (SELECT COUNT(*) FROM online_exam_participants WHERE online_exam_id = oe.id AND status != 'waiting') as started_count
            FROM online_exams oe
            LEFT JOIN exam_bank eb ON oe.exam_bank_id = eb.exam_id
            LEFT JOIN courses c ON oe.course_code = c.code
            WHERE 1=1
        """
        params = []

        if course_code:
            query += " AND oe.course_code = %s"
            params.append(course_code)
        if status:
            query += " AND oe.status = %s"
            params.append(status)
        if instructor_code:
            query += " AND oe.instructor_code = %s"
            params.append(instructor_code)

        query += " ORDER BY oe.created_at DESC"

        cursor.execute(query, params)
        exams = cursor.fetchall()
        conn.close()

        return {"success": True, "exams": exams}
    except Exception as e:
        print(f"[ERROR] 온라인 시험 목록 조회 실패: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/online-exams")
async def create_online_exam(request: Request):
    """온라인 시험/과제 등록"""
    try:
        data = await request.json()

        conn = get_db_connection()
        cursor = conn.cursor(pymysql.cursors.DictCursor)

        # 문제은행 시험 확인
        cursor.execute("SELECT exam_id, exam_name, total_questions FROM exam_bank WHERE exam_id = %s",
                      (data.get('exam_bank_id'),))
        exam_bank = cursor.fetchone()
        if not exam_bank:
            raise HTTPException(status_code=404, detail="문제은행 시험을 찾을 수 없습니다")

        exam_type = data.get('exam_type', 'exam')
        # 과제형은 바로 ongoing 상태로 시작 (deadline까지 제출 가능)
        initial_status = 'ongoing' if exam_type == 'assignment' else 'scheduled'

        cursor.execute("""
            INSERT INTO online_exams (title, exam_type, exam_bank_id, course_code, instructor_code,
                                     duration, scheduled_at, deadline, description, pass_score,
                                     shuffle_questions, shuffle_options, show_result, status)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """, (
            data.get('title', exam_bank['exam_name']),
            exam_type,  # exam, quiz, assignment
            data.get('exam_bank_id'),
            data.get('course_code'),
            data.get('instructor_code'),
            data.get('duration', 60),
            data.get('scheduled_at'),
            data.get('deadline'),  # 과제 마감일
            data.get('description', ''),
            data.get('pass_score', 60),
            data.get('shuffle_questions', 0),
            data.get('shuffle_options', 0),
            data.get('show_result', 1),
            initial_status
        ))

        exam_id = cursor.lastrowid
        conn.commit()
        conn.close()

        type_text = {'exam': '시험', 'quiz': '퀴즈', 'assignment': '과제'}
        return {
            "success": True,
            "message": f"온라인 {type_text.get(exam_type, '시험')}이(가) 등록되었습니다",
            "exam_id": exam_id
        }
    except HTTPException:
        raise
    except Exception as e:
        print(f"[ERROR] 온라인 시험 등록 실패: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/online-exams/{exam_id}")
async def get_online_exam(exam_id: int):
    """온라인 시험 상세 조회"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor(pymysql.cursors.DictCursor)

        cursor.execute("""
            SELECT oe.*, eb.exam_name as exam_bank_name, eb.total_questions, eb.subject,
                   c.name as course_name
            FROM online_exams oe
            LEFT JOIN exam_bank eb ON oe.exam_bank_id = eb.exam_id
            LEFT JOIN courses c ON oe.course_code = c.code
            WHERE oe.id = %s
        """, (exam_id,))
        exam = cursor.fetchone()

        if not exam:
            raise HTTPException(status_code=404, detail="시험을 찾을 수 없습니다")

        conn.close()
        return {"success": True, "exam": exam}
    except HTTPException:
        raise
    except Exception as e:
        print(f"[ERROR] 온라인 시험 조회 실패: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/online-exams/{exam_id}/open-waiting")
async def open_waiting_room(exam_id: int, request: Request):
    """대기실 오픈 (강사)"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor(pymysql.cursors.DictCursor)

        cursor.execute("SELECT * FROM online_exams WHERE id = %s", (exam_id,))
        exam = cursor.fetchone()
        if not exam:
            raise HTTPException(status_code=404, detail="시험을 찾을 수 없습니다")

        if exam['status'] not in ['scheduled', 'waiting']:
            raise HTTPException(status_code=400, detail="이미 시작되었거나 종료된 시험입니다")

        cursor.execute("""
            UPDATE online_exams SET status = 'waiting' WHERE id = %s
        """, (exam_id,))

        conn.commit()
        conn.close()

        return {"success": True, "message": "대기실이 오픈되었습니다"}
    except HTTPException:
        raise
    except Exception as e:
        print(f"[ERROR] 대기실 오픈 실패: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/online-exams/{exam_id}/start")
async def start_online_exam(exam_id: int, request: Request):
    """시험 시작 (강사)"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor(pymysql.cursors.DictCursor)

        cursor.execute("SELECT * FROM online_exams WHERE id = %s", (exam_id,))
        exam = cursor.fetchone()
        if not exam:
            raise HTTPException(status_code=404, detail="시험을 찾을 수 없습니다")

        if exam['status'] == 'ongoing':
            raise HTTPException(status_code=400, detail="이미 진행 중인 시험입니다")
        if exam['status'] == 'ended':
            raise HTTPException(status_code=400, detail="이미 종료된 시험입니다")

        now = datetime.now()
        end_time = now + timedelta(minutes=exam['duration'])

        cursor.execute("""
            UPDATE online_exams
            SET status = 'ongoing', started_at = %s, ended_at = %s
            WHERE id = %s
        """, (now, end_time, exam_id))

        # 대기 중인 모든 응시자 상태 변경
        cursor.execute("""
            UPDATE online_exam_participants
            SET status = 'taking', started_at = %s
            WHERE online_exam_id = %s AND status = 'waiting'
        """, (now, exam_id))

        conn.commit()
        conn.close()

        return {
            "success": True,
            "message": "시험이 시작되었습니다",
            "started_at": now.isoformat(),
            "ended_at": end_time.isoformat()
        }
    except HTTPException:
        raise
    except Exception as e:
        print(f"[ERROR] 시험 시작 실패: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/online-exams/{exam_id}/end")
async def end_online_exam(exam_id: int, request: Request):
    """시험 종료 (강사) - 강제 종료"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor(pymysql.cursors.DictCursor)

        cursor.execute("SELECT * FROM online_exams WHERE id = %s", (exam_id,))
        exam = cursor.fetchone()
        if not exam:
            raise HTTPException(status_code=404, detail="시험을 찾을 수 없습니다")

        now = datetime.now()

        cursor.execute("""
            UPDATE online_exams SET status = 'ended', ended_at = %s WHERE id = %s
        """, (now, exam_id))

        # 미제출 응시자 자동 제출 처리
        cursor.execute("""
            UPDATE online_exam_participants
            SET status = 'submitted', submitted_at = %s
            WHERE online_exam_id = %s AND status IN ('waiting', 'taking')
        """, (now, exam_id))

        conn.commit()
        conn.close()

        return {"success": True, "message": "시험이 종료되었습니다"}
    except HTTPException:
        raise
    except Exception as e:
        print(f"[ERROR] 시험 종료 실패: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/online-exams/{exam_id}/enter")
async def enter_exam_waiting_room(exam_id: int, request: Request):
    """대기실 입장 (학생)"""
    try:
        data = await request.json()
        student_id = data.get('student_id')

        if not student_id:
            raise HTTPException(status_code=400, detail="학생 ID가 필요합니다")

        conn = get_db_connection()
        cursor = conn.cursor(pymysql.cursors.DictCursor)

        # 시험 확인
        cursor.execute("SELECT * FROM online_exams WHERE id = %s", (exam_id,))
        exam = cursor.fetchone()
        if not exam:
            raise HTTPException(status_code=404, detail="시험을 찾을 수 없습니다")

        if exam['status'] == 'scheduled':
            raise HTTPException(status_code=400, detail="아직 대기실이 열리지 않았습니다")
        if exam['status'] == 'ended':
            raise HTTPException(status_code=400, detail="이미 종료된 시험입니다")

        # 학생 정보 확인
        cursor.execute("SELECT id, name, course_code FROM students WHERE id = %s", (student_id,))
        student = cursor.fetchone()
        if not student:
            raise HTTPException(status_code=404, detail="학생 정보를 찾을 수 없습니다")

        # 해당 과정 학생인지 확인
        if student['course_code'] != exam['course_code']:
            raise HTTPException(status_code=403, detail="해당 과정의 학생만 응시할 수 있습니다")

        now = datetime.now()

        # 이미 입장했는지 확인
        cursor.execute("""
            SELECT * FROM online_exam_participants
            WHERE online_exam_id = %s AND student_id = %s
        """, (exam_id, student_id))
        existing = cursor.fetchone()

        if existing:
            # 이미 입장한 경우
            if exam['status'] == 'ongoing':
                # 시험 진행 중이면 재입장 허용 (submitted 상태도 포함)
                if existing['status'] in ['waiting', 'taking', 'submitted']:
                    # submitted 상태면 taking으로 변경하여 재응시 허용
                    if existing['status'] == 'submitted':
                        cursor.execute("""
                            UPDATE online_exam_participants
                            SET status = 'taking'
                            WHERE id = %s
                        """, (existing['id'],))
                        conn.commit()
                        existing['status'] = 'taking'

                    # 기존 답안도 함께 반환
                    import json
                    previous_answers = {}
                    if existing['answers']:
                        try:
                            previous_answers = json.loads(existing['answers'])
                        except:
                            pass

                    conn.close()
                    return {
                        "success": True,
                        "message": "시험에 재입장하였습니다" if previous_answers else "시험이 진행 중입니다",
                        "participant_id": existing['id'],
                        "exam_status": exam['status'],
                        "participant_status": existing['status'],
                        "started_at": exam['started_at'].isoformat() if exam['started_at'] else None,
                        "ended_at": exam['ended_at'].isoformat() if exam['ended_at'] else None,
                        "previous_answers": previous_answers
                    }

            conn.close()
            return {
                "success": True,
                "message": "이미 입장하셨습니다",
                "participant_id": existing['id'],
                "exam_status": exam['status'],
                "participant_status": existing['status']
            }

        # 새로 입장
        initial_status = 'taking' if exam['status'] == 'ongoing' else 'waiting'
        started_at = now if exam['status'] == 'ongoing' else None

        cursor.execute("""
            INSERT INTO online_exam_participants (online_exam_id, student_id, status, entered_at, started_at)
            VALUES (%s, %s, %s, %s, %s)
        """, (exam_id, student_id, initial_status, now, started_at))

        participant_id = cursor.lastrowid
        conn.commit()
        conn.close()

        return {
            "success": True,
            "message": "대기실에 입장하였습니다" if initial_status == 'waiting' else "시험에 입장하였습니다",
            "participant_id": participant_id,
            "exam_status": exam['status'],
            "participant_status": initial_status,
            "started_at": exam['started_at'].isoformat() if exam['started_at'] else None,
            "ended_at": exam['ended_at'].isoformat() if exam['ended_at'] else None
        }
    except HTTPException:
        raise
    except Exception as e:
        print(f"[ERROR] 대기실 입장 실패: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/online-exams/{exam_id}/questions")
async def get_exam_questions(exam_id: int, student_id: Optional[int] = None):
    """시험 문제 조회 (시험 시작 후에만)"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor(pymysql.cursors.DictCursor)

        # 시험 정보 조회
        cursor.execute("""
            SELECT oe.*, eb.total_questions
            FROM online_exams oe
            LEFT JOIN exam_bank eb ON oe.exam_bank_id = eb.exam_id
            WHERE oe.id = %s
        """, (exam_id,))
        exam = cursor.fetchone()

        if not exam:
            raise HTTPException(status_code=404, detail="시험을 찾을 수 없습니다")

        if exam['status'] != 'ongoing':
            raise HTTPException(status_code=400, detail="시험이 진행 중이 아닙니다")

        # 응시자 확인 (학생인 경우) - submitted 상태도 재응시 허용
        if student_id:
            cursor.execute("""
                SELECT * FROM online_exam_participants
                WHERE online_exam_id = %s AND student_id = %s AND status IN ('waiting', 'taking', 'submitted')
            """, (exam_id, student_id))
            participant = cursor.fetchone()
            if not participant:
                raise HTTPException(status_code=403, detail="응시 권한이 없습니다")

        # 문제 조회 (정답 제외)
        cursor.execute("""
            SELECT question_id, question_number, question_text, question_type,
                   options, difficulty, points, reference_page, reference_document
            FROM exam_questions
            WHERE exam_id = %s
            ORDER BY question_number
        """, (exam['exam_bank_id'],))
        questions = cursor.fetchall()

        # options JSON 파싱
        import json
        for q in questions:
            if q['options']:
                try:
                    q['options'] = json.loads(q['options'])
                except:
                    q['options'] = []

        conn.close()

        return {
            "success": True,
            "exam": {
                "id": exam['id'],
                "title": exam['title'],
                "duration": exam['duration'],
                "started_at": exam['started_at'].isoformat() if exam['started_at'] else None,
                "ended_at": exam['ended_at'].isoformat() if exam['ended_at'] else None,
                "total_questions": exam['total_questions']
            },
            "questions": questions
        }
    except HTTPException:
        raise
    except Exception as e:
        print(f"[ERROR] 시험 문제 조회 실패: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/online-exams/{exam_id}/submit")
async def submit_exam_answers(exam_id: int, request: Request):
    """답안 제출 (학생)"""
    try:
        data = await request.json()
        student_id = data.get('student_id')
        answers = data.get('answers', {})  # {"question_id": "answer", ...}

        if not student_id:
            raise HTTPException(status_code=400, detail="학생 ID가 필요합니다")

        conn = get_db_connection()
        cursor = conn.cursor(pymysql.cursors.DictCursor)

        # 시험 확인
        cursor.execute("SELECT * FROM online_exams WHERE id = %s", (exam_id,))
        exam = cursor.fetchone()
        if not exam:
            raise HTTPException(status_code=404, detail="시험을 찾을 수 없습니다")

        # 응시자 확인
        cursor.execute("""
            SELECT * FROM online_exam_participants
            WHERE online_exam_id = %s AND student_id = %s
        """, (exam_id, student_id))
        participant = cursor.fetchone()

        if not participant:
            raise HTTPException(status_code=404, detail="응시 정보를 찾을 수 없습니다")

        # 시험이 진행 중일 때만 제출/재제출 가능
        if exam['status'] != 'ongoing':
            raise HTTPException(status_code=400, detail="시험이 종료되어 제출할 수 없습니다")

        now = datetime.now()
        import json

        is_resubmit = participant['status'] == 'submitted'

        cursor.execute("""
            UPDATE online_exam_participants
            SET status = 'submitted', submitted_at = %s, answers = %s
            WHERE id = %s
        """, (now, json.dumps(answers, ensure_ascii=False), participant['id']))

        conn.commit()
        conn.close()

        return {
            "success": True,
            "message": "답안이 재제출되었습니다" if is_resubmit else "답안이 제출되었습니다",
            "submitted_at": now.isoformat(),
            "is_resubmit": is_resubmit
        }
    except HTTPException:
        raise
    except Exception as e:
        print(f"[ERROR] 답안 제출 실패: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/online-exams/{exam_id}/monitor")
async def monitor_exam(exam_id: int):
    """시험 모니터링 (강사)"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor(pymysql.cursors.DictCursor)

        # 시험 정보
        cursor.execute("""
            SELECT oe.*, eb.exam_name as exam_bank_name, eb.total_questions
            FROM online_exams oe
            LEFT JOIN exam_bank eb ON oe.exam_bank_id = eb.exam_id
            WHERE oe.id = %s
        """, (exam_id,))
        exam = cursor.fetchone()

        if not exam:
            raise HTTPException(status_code=404, detail="시험을 찾을 수 없습니다")

        # 응시자 목록
        cursor.execute("""
            SELECT oep.*, s.name as student_name, s.code as student_code
            FROM online_exam_participants oep
            LEFT JOIN students s ON oep.student_id = s.id
            WHERE oep.online_exam_id = %s
            ORDER BY oep.entered_at
        """, (exam_id,))
        participants = cursor.fetchall()

        # 해당 과정 전체 학생 수
        cursor.execute("""
            SELECT COUNT(*) as total FROM students WHERE course_code = %s
        """, (exam['course_code'],))
        total_students = cursor.fetchone()['total']

        # 통계
        stats = {
            "total_students": total_students,
            "entered_count": len(participants),
            "waiting_count": sum(1 for p in participants if p['status'] == 'waiting'),
            "taking_count": sum(1 for p in participants if p['status'] == 'taking'),
            "submitted_count": sum(1 for p in participants if p['status'] == 'submitted'),
            "graded_count": sum(1 for p in participants if p['status'] == 'graded')
        }

        conn.close()

        # 남은 시간 계산
        remaining_seconds = None
        if exam['status'] == 'ongoing' and exam['ended_at']:
            remaining = exam['ended_at'] - datetime.now()
            remaining_seconds = max(0, int(remaining.total_seconds()))

        return {
            "success": True,
            "exam": exam,
            "participants": participants,
            "stats": stats,
            "remaining_seconds": remaining_seconds
        }
    except HTTPException:
        raise
    except Exception as e:
        print(f"[ERROR] 시험 모니터링 실패: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/online-exams/{exam_id}/status")
async def get_exam_status(exam_id: int, student_id: Optional[int] = None):
    """시험 상태 조회 (폴링용)"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor(pymysql.cursors.DictCursor)

        cursor.execute("""
            SELECT id, status, started_at, ended_at, duration
            FROM online_exams WHERE id = %s
        """, (exam_id,))
        exam = cursor.fetchone()

        if not exam:
            raise HTTPException(status_code=404, detail="시험을 찾을 수 없습니다")

        # 남은 시간 계산
        remaining_seconds = None
        if exam['status'] == 'ongoing' and exam['ended_at']:
            remaining = exam['ended_at'] - datetime.now()
            remaining_seconds = max(0, int(remaining.total_seconds()))

            # 시간 초과시 자동 종료
            if remaining_seconds <= 0:
                cursor.execute("""
                    UPDATE online_exams SET status = 'ended' WHERE id = %s AND status = 'ongoing'
                """, (exam_id,))
                cursor.execute("""
                    UPDATE online_exam_participants
                    SET status = 'submitted', submitted_at = NOW()
                    WHERE online_exam_id = %s AND status IN ('waiting', 'taking')
                """, (exam_id,))
                conn.commit()
                exam['status'] = 'ended'

        result = {
            "success": True,
            "exam_status": exam['status'],
            "started_at": exam['started_at'].isoformat() if exam['started_at'] else None,
            "ended_at": exam['ended_at'].isoformat() if exam['ended_at'] else None,
            "remaining_seconds": remaining_seconds
        }

        # 학생인 경우 본인 상태도 반환
        if student_id:
            cursor.execute("""
                SELECT status, submitted_at FROM online_exam_participants
                WHERE online_exam_id = %s AND student_id = %s
            """, (exam_id, student_id))
            participant = cursor.fetchone()
            if participant:
                result['participant_status'] = participant['status']
                result['submitted_at'] = participant['submitted_at'].isoformat() if participant['submitted_at'] else None

        conn.close()
        return result
    except HTTPException:
        raise
    except Exception as e:
        print(f"[ERROR] 시험 상태 조회 실패: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/online-exams/{exam_id}/grade")
async def grade_exam(exam_id: int, request: Request):
    """자동 채점 (강사)"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor(pymysql.cursors.DictCursor)

        # 시험 정보
        cursor.execute("""
            SELECT oe.*, eb.total_questions
            FROM online_exams oe
            LEFT JOIN exam_bank eb ON oe.exam_bank_id = eb.exam_id
            WHERE oe.id = %s
        """, (exam_id,))
        exam = cursor.fetchone()

        if not exam:
            raise HTTPException(status_code=404, detail="시험을 찾을 수 없습니다")

        # 정답 목록 조회
        cursor.execute("""
            SELECT question_id, correct_answer, points
            FROM exam_questions WHERE exam_id = %s
        """, (exam['exam_bank_id'],))
        questions = cursor.fetchall()

        answer_key = {str(q['question_id']): q for q in questions}
        total_points = sum(q['points'] for q in questions)

        # 제출된 응시자 목록
        cursor.execute("""
            SELECT * FROM online_exam_participants
            WHERE online_exam_id = %s AND status = 'submitted'
        """, (exam_id,))
        participants = cursor.fetchall()

        import json
        graded_count = 0

        # 알파벳 <-> 숫자 변환 맵
        alpha_to_num = {'A': '1', 'B': '2', 'C': '3', 'D': '4', 'E': '5'}
        num_to_alpha = {'1': 'A', '2': 'B', '3': 'C', '4': 'D', '5': 'E'}

        for p in participants:
            answers = json.loads(p['answers']) if p['answers'] else {}
            score = 0
            correct_count = 0

            for qid, q_info in answer_key.items():
                student_answer = str(answers.get(qid, '')).strip()
                correct_answer = str(q_info['correct_answer']).strip()

                # 학생 답안을 숫자로 정규화 (1, 2, 3, 4)
                student_num = student_answer
                if student_answer.upper() in alpha_to_num:
                    student_num = alpha_to_num[student_answer.upper()]

                # 정답을 숫자로 정규화
                # 케이스1: "3" (새로운 형식)
                # 케이스2: "C) 데이터의 윤리적 사용" (기존 형식)
                # 케이스3: "C" (알파벳만)
                correct_num = ''
                if correct_answer and correct_answer[0].isdigit():
                    correct_num = correct_answer[0]
                elif correct_answer and correct_answer[0].upper() in alpha_to_num:
                    correct_num = alpha_to_num[correct_answer[0].upper()]

                if student_num == correct_num:
                    score += q_info['points']
                    correct_count += 1

            # 100점 만점으로 환산
            final_score = round((score / total_points) * 100) if total_points > 0 else 0
            is_passed = 1 if final_score >= exam['pass_score'] else 0

            cursor.execute("""
                UPDATE online_exam_participants
                SET status = 'graded', score = %s, correct_count = %s,
                    total_questions = %s, is_passed = %s, graded_at = NOW()
                WHERE id = %s
            """, (final_score, correct_count, len(questions), is_passed, p['id']))
            graded_count += 1

        # 시험 상태 업데이트
        cursor.execute("UPDATE online_exams SET status = 'graded' WHERE id = %s", (exam_id,))

        conn.commit()
        conn.close()

        return {
            "success": True,
            "message": f"{graded_count}명의 답안이 채점되었습니다",
            "graded_count": graded_count
        }
    except HTTPException:
        raise
    except Exception as e:
        print(f"[ERROR] 채점 실패: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/online-exams/{exam_id}/results")
async def get_exam_results(exam_id: int):
    """시험 결과 조회 (강사)"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor(pymysql.cursors.DictCursor)

        # 시험 정보
        cursor.execute("""
            SELECT oe.*, eb.exam_name as exam_bank_name, eb.total_questions
            FROM online_exams oe
            LEFT JOIN exam_bank eb ON oe.exam_bank_id = eb.exam_id
            WHERE oe.id = %s
        """, (exam_id,))
        exam = cursor.fetchone()

        if not exam:
            raise HTTPException(status_code=404, detail="시험을 찾을 수 없습니다")

        # 채점된 응시자 목록 (제출시간 순으로 정렬하여 순위 부여)
        cursor.execute("""
            SELECT oep.*, s.name as student_name, s.code as student_code
            FROM online_exam_participants oep
            LEFT JOIN students s ON oep.student_id = s.id
            WHERE oep.online_exam_id = %s AND oep.status = 'graded'
            ORDER BY oep.submitted_at ASC
        """, (exam_id,))
        results = cursor.fetchall()

        # 퀴즈인 경우 제출 순서 순위 및 전부 정답 여부 추가
        if exam.get('exam_type') == 'quiz':
            rank = 1
            for r in results:
                # 전부 정답인지 확인
                r['is_all_correct'] = (r['correct_count'] == r['total_questions']) if r['total_questions'] else False
                if r['is_all_correct']:
                    r['rank'] = rank
                    rank += 1
                else:
                    r['rank'] = None  # 오답자는 순위 없음

        # 통계
        if results:
            scores = [r['score'] for r in results]
            stats = {
                "total_count": len(results),
                "average_score": round(sum(scores) / len(scores), 1),
                "max_score": max(scores),
                "min_score": min(scores),
                "pass_count": sum(1 for r in results if r['is_passed']),
                "fail_count": sum(1 for r in results if not r['is_passed'])
            }
        else:
            stats = {
                "total_count": 0, "average_score": 0, "max_score": 0,
                "min_score": 0, "pass_count": 0, "fail_count": 0
            }

        conn.close()

        return {
            "success": True,
            "exam": exam,
            "results": results,
            "stats": stats
        }
    except HTTPException:
        raise
    except Exception as e:
        print(f"[ERROR] 시험 결과 조회 실패: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@app.delete("/api/online-exams/{exam_id}")
async def delete_online_exam(exam_id: int):
    """온라인 시험 삭제"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor(pymysql.cursors.DictCursor)

        cursor.execute("SELECT * FROM online_exams WHERE id = %s", (exam_id,))
        exam = cursor.fetchone()
        if not exam:
            raise HTTPException(status_code=404, detail="시험을 찾을 수 없습니다")

        if exam['status'] == 'ongoing':
            raise HTTPException(status_code=400, detail="진행 중인 시험은 삭제할 수 없습니다")

        cursor.execute("DELETE FROM online_exams WHERE id = %s", (exam_id,))
        conn.commit()
        conn.close()

        return {"success": True, "message": "시험이 삭제되었습니다"}
    except HTTPException:
        raise
    except Exception as e:
        print(f"[ERROR] 시험 삭제 실패: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/online-exams/{exam_id}/submit-assignment")
async def submit_assignment(exam_id: int, student_id: int = Form(...), file: UploadFile = File(None), answer_text: str = Form(None)):
    """과제 제출 (파일 첨부 또는 텍스트)"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor(pymysql.cursors.DictCursor)

        # 시험(과제) 확인
        cursor.execute("SELECT * FROM online_exams WHERE id = %s", (exam_id,))
        exam = cursor.fetchone()
        if not exam:
            raise HTTPException(status_code=404, detail="과제를 찾을 수 없습니다")

        if exam['exam_type'] != 'assignment':
            raise HTTPException(status_code=400, detail="과제형이 아닙니다")

        # 마감일 확인
        now = datetime.now()
        if exam['deadline'] and now > exam['deadline']:
            raise HTTPException(status_code=400, detail="제출 기한이 지났습니다")

        # 응시자 정보 확인/생성
        cursor.execute("""
            SELECT * FROM online_exam_participants
            WHERE online_exam_id = %s AND student_id = %s
        """, (exam_id, student_id))
        participant = cursor.fetchone()

        file_path = None
        file_name = None

        # 파일 업로드 처리
        if file and file.filename:
            import os
            upload_dir = "/usr/miniLMS/uploads/assignments"
            os.makedirs(upload_dir, exist_ok=True)

            # 파일명 생성 (exam_id_student_id_timestamp_원본파일명)
            timestamp = now.strftime("%Y%m%d_%H%M%S")
            safe_filename = file.filename.replace(" ", "_")
            file_name = f"{exam_id}_{student_id}_{timestamp}_{safe_filename}"
            file_path = os.path.join(upload_dir, file_name)

            # 파일 저장
            content = await file.read()
            with open(file_path, "wb") as f:
                f.write(content)

        # 답안 데이터 (텍스트 또는 파일 정보)
        import json
        answers = {}
        if answer_text:
            answers = {"text": answer_text}

        if participant:
            # 기존 제출 수정
            cursor.execute("""
                UPDATE online_exam_participants
                SET status = 'submitted', submitted_at = %s, answers = %s,
                    file_path = COALESCE(%s, file_path), file_name = COALESCE(%s, file_name)
                WHERE id = %s
            """, (now, json.dumps(answers, ensure_ascii=False) if answers else None,
                  file_path, file_name, participant['id']))
            is_resubmit = True
        else:
            # 새로 제출
            cursor.execute("""
                INSERT INTO online_exam_participants
                (online_exam_id, student_id, status, entered_at, submitted_at, answers, file_path, file_name)
                VALUES (%s, %s, 'submitted', %s, %s, %s, %s, %s)
            """, (exam_id, student_id, now, now,
                  json.dumps(answers, ensure_ascii=False) if answers else None,
                  file_path, file_name))
            is_resubmit = False

        conn.commit()
        conn.close()

        return {
            "success": True,
            "message": "과제가 재제출되었습니다" if is_resubmit else "과제가 제출되었습니다",
            "submitted_at": now.isoformat(),
            "file_name": file_name,
            "is_resubmit": is_resubmit
        }
    except HTTPException:
        raise
    except Exception as e:
        print(f"[ERROR] 과제 제출 실패: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/online-exams/{exam_id}/assignment-status")
async def get_assignment_status(exam_id: int, student_id: int):
    """과제 제출 상태 조회"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor(pymysql.cursors.DictCursor)

        # 과제 정보
        cursor.execute("""
            SELECT oe.*, eb.exam_name as exam_bank_name
            FROM online_exams oe
            LEFT JOIN exam_bank eb ON oe.exam_bank_id = eb.exam_id
            WHERE oe.id = %s
        """, (exam_id,))
        exam = cursor.fetchone()

        if not exam:
            raise HTTPException(status_code=404, detail="과제를 찾을 수 없습니다")

        # 학생 제출 정보
        cursor.execute("""
            SELECT * FROM online_exam_participants
            WHERE online_exam_id = %s AND student_id = %s
        """, (exam_id, student_id))
        submission = cursor.fetchone()

        conn.close()

        # 남은 시간 계산
        remaining_seconds = None
        if exam['deadline']:
            remaining = exam['deadline'] - datetime.now()
            remaining_seconds = max(0, int(remaining.total_seconds()))

        return {
            "success": True,
            "exam": {
                "id": exam['id'],
                "title": exam['title'],
                "deadline": exam['deadline'].isoformat() if exam['deadline'] else None,
                "description": exam['description']
            },
            "submission": {
                "submitted": submission is not None,
                "submitted_at": submission['submitted_at'].isoformat() if submission and submission['submitted_at'] else None,
                "file_name": submission['file_name'] if submission else None,
                "answers": submission['answers'] if submission else None
            } if submission else None,
            "remaining_seconds": remaining_seconds,
            "is_expired": remaining_seconds == 0 if remaining_seconds is not None else False
        }
    except HTTPException:
        raise
    except Exception as e:
        print(f"[ERROR] 과제 상태 조회 실패: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/assignments/download/{filename}")
async def download_assignment(filename: str):
    """과제 파일 다운로드"""
    from fastapi.responses import FileResponse
    import os

    file_path = os.path.join("/usr/miniLMS/uploads/assignments", filename)

    if not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail="파일을 찾을 수 없습니다")

    # 원본 파일명 추출 (exam_id_student_id_timestamp_원본파일명)
    parts = filename.split("_", 3)
    original_name = parts[3] if len(parts) > 3 else filename

    return FileResponse(
        file_path,
        filename=original_name,
        media_type="application/octet-stream"
    )


@app.post("/api/online-exams/{exam_id}/grade-assignment")
async def grade_assignment(exam_id: int, request: Request):
    """과제 수동 채점 (강사)"""
    try:
        data = await request.json()
        participant_id = data.get('participant_id')
        score = data.get('score')
        feedback = data.get('feedback', '')

        if participant_id is None or score is None:
            raise HTTPException(status_code=400, detail="participant_id와 score가 필요합니다")

        conn = get_db_connection()
        cursor = conn.cursor(pymysql.cursors.DictCursor)

        # 과제 확인
        cursor.execute("""
            SELECT exam_type FROM online_exams WHERE id = %s
        """, (exam_id,))
        exam = cursor.fetchone()
        if not exam:
            raise HTTPException(status_code=404, detail="과제를 찾을 수 없습니다")

        # 점수 업데이트
        cursor.execute("""
            UPDATE online_exam_participants
            SET score = %s, status = 'graded', feedback = %s
            WHERE id = %s AND online_exam_id = %s
        """, (score, feedback, participant_id, exam_id))

        conn.commit()
        conn.close()

        return {
            "success": True,
            "message": "점수가 저장되었습니다"
        }
    except HTTPException:
        raise
    except Exception as e:
        print(f"[ERROR] 과제 채점 실패: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/online-exams/{exam_id}/grade-all-assignments")
async def grade_all_assignments(exam_id: int, request: Request):
    """모든 과제 일괄 채점 (강사)"""
    try:
        data = await request.json()
        grades = data.get('grades', [])  # [{participant_id, score, feedback}, ...]

        if not grades:
            raise HTTPException(status_code=400, detail="채점 데이터가 필요합니다")

        conn = get_db_connection()
        cursor = conn.cursor(pymysql.cursors.DictCursor)

        graded_count = 0
        for grade in grades:
            cursor.execute("""
                UPDATE online_exam_participants
                SET score = %s, status = 'graded', feedback = %s
                WHERE id = %s AND online_exam_id = %s
            """, (grade.get('score', 0), grade.get('feedback', ''), grade['participant_id'], exam_id))
            graded_count += cursor.rowcount

        # 모든 과제가 채점되었는지 확인하고 상태 업데이트
        cursor.execute("""
            SELECT COUNT(*) as total, SUM(CASE WHEN status = 'graded' THEN 1 ELSE 0 END) as graded
            FROM online_exam_participants WHERE online_exam_id = %s
        """, (exam_id,))
        result = cursor.fetchone()

        if result['total'] > 0 and result['total'] == result['graded']:
            cursor.execute("UPDATE online_exams SET status = 'graded' WHERE id = %s", (exam_id,))

        conn.commit()
        conn.close()

        return {
            "success": True,
            "message": f"{graded_count}명의 과제가 채점되었습니다",
            "graded_count": graded_count
        }
    except HTTPException:
        raise
    except Exception as e:
        print(f"[ERROR] 일괄 채점 실패: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


# ====================문서 관리 API====================

@app.post("/api/documents/upload")
async def upload_document(
    file: UploadFile = File(...),
    category: Optional[str] = Form("general")
):
    """
    문서 업로드 (documents 폴더에 저장)
    - PDF, DOCX, DOC, TXT, PPTX, XLSX 파일 지원
    """
    try:
        # 파일 확장자 확인
        file_ext = Path(file.filename).suffix.lower()
        allowed_extensions = ['.pdf', '.docx', '.doc', '.txt', '.pptx', '.ppt', '.xlsx', '.xls']
        
        if file_ext not in allowed_extensions:
            raise HTTPException(
                status_code=400,
                detail="지원하지 않는 파일 형식입니다. PDF, DOCX, DOC, TXT, PPTX, XLSX 파일만 업로드 가능합니다."
            )
        
        # 파일 읽기
        content = await file.read()
        file_size = len(content)
        
        # 파일 크기 확인 (100MB 제한)
        if file_size > 100 * 1024 * 1024:
            raise HTTPException(status_code=400, detail="파일 크기는 100MB 이하여야 합니다")
        
        # 카테고리에 따라 저장 폴더 결정
        if category == "rag-indexed" or category == "rag":
            # RAG 문서는 rag_documents 폴더에 저장
            documents_dir = Path("./rag_documents")
        else:
            # 일반 문서는 documents 폴더에 저장
            documents_dir = Path("./documents")
        
        documents_dir.mkdir(exist_ok=True)
        
        # 고유 파일명 생성 (타임스탬프 + 원본 파일명)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        safe_filename = f"{timestamp}_{file.filename}"
        file_path = documents_dir / safe_filename
        
        # 파일 저장
        with open(file_path, "wb") as f:
            f.write(content)
        
        print(f"[OK] 문서 저장 완료: {file_path}")
        
        return {
            "success": True,
            "message": "문서가 성공적으로 업로드되었습니다",
            "filename": safe_filename,
            "original_filename": file.filename,
            "file_size": file_size,
            "file_path": str(file_path),
            "category": category,
            "upload_date": datetime.now().isoformat()
        }
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"[ERROR] 문서 업로드 실패: {str(e)}")
        raise HTTPException(status_code=500, detail=f"문서 업로드 실패: {str(e)}")


@app.get("/api/documents/list")
async def list_documents():
    """documents 및 rag_documents 폴더의 파일 목록 조회"""
    try:
        documents = []
        
        # documents 폴더와 rag_documents 폴더 모두에서 파일 조회
        for folder_name in ["documents", "rag_documents"]:
            folder_path = Path(f"./{folder_name}")
            
            if folder_path.exists():
                for file_path in folder_path.iterdir():
                    if file_path.is_file() and not file_path.name.startswith('.'):
                        stat = file_path.stat()
                        documents.append({
                            "filename": file_path.name,
                            "file_size": stat.st_size,
                            "file_size_mb": round(stat.st_size / (1024 * 1024), 2),
                            "modified_at": datetime.fromtimestamp(stat.st_mtime).isoformat(),
                            "extension": file_path.suffix.lower(),
                            "folder": folder_name  # 어느 폴더에서 온 파일인지 표시
                        })
        
        # 수정일시 기준 내림차순 정렬
        documents.sort(key=lambda x: x['modified_at'], reverse=True)
        
        return {
            "success": True,
            "documents": documents,
            "count": len(documents)
        }
        
    except Exception as e:
        print(f"[ERROR] 문서 목록 조회 실패: {str(e)}")
        raise HTTPException(status_code=500, detail=f"문서 목록 조회 실패: {str(e)}")


@app.delete("/api/documents/{filename}")
async def delete_document(filename: str):
    """문서 삭제 (documents 및 rag_documents 폴더에서 검색)"""
    try:
        # 파일명 검증 (경로 탐색 공격 방지)
        if '..' in filename or '/' in filename or '\\' in filename:
            raise HTTPException(status_code=400, detail="잘못된 파일명입니다")
        
        # documents와 rag_documents 폴더 모두에서 파일 찾기
        file_path = None
        for folder in ["documents", "rag_documents"]:
            test_path = Path(f"./{folder}") / filename
            if test_path.exists():
                file_path = test_path
                break
        
        if not file_path:
            raise HTTPException(status_code=404, detail="파일을 찾을 수 없습니다")
        
        if not file_path.is_file():
            raise HTTPException(status_code=400, detail="파일이 아닙니다")
        
        # 파일 삭제
        file_path.unlink()
        
        print(f"[OK] 문서 삭제 완료: {filename}")
        
        return {
            "success": True,
            "message": f"문서 '{filename}'이(가) 삭제되었습니다"
        }
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"[ERROR] 문서 삭제 실패: {str(e)}")
        raise HTTPException(status_code=500, detail=f"문서 삭제 실패: {str(e)}")


@app.get("/api/documents/download/{filename}")
async def download_document(filename: str):
    """문서 다운로드 (documents 및 rag_documents 폴더에서 검색)"""
    try:
        # 파일명 검증
        if '..' in filename or '/' in filename or '\\' in filename:
            raise HTTPException(status_code=400, detail="잘못된 파일명입니다")
        
        # documents와 rag_documents 폴더 모두에서 파일 찾기
        file_path = None
        for folder in ["documents", "rag_documents"]:
            test_path = Path(f"./{folder}") / filename
            if test_path.exists():
                file_path = test_path
                break
        
        if not file_path:
            raise HTTPException(status_code=404, detail="파일을 찾을 수 없습니다")
        
        from fastapi.responses import FileResponse
        
        return FileResponse(
            path=str(file_path),
            filename=filename,
            media_type='application/octet-stream'
        )
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"[ERROR] 문서 다운로드 실패: {str(e)}")
        raise HTTPException(status_code=500, detail=f"문서 다운로드 실패: {str(e)}")


@app.post("/api/rag/index-document")
async def index_document_to_rag(request: Request):
    """
    문서를 RAG 시스템에 인덱싱
    - filename: rag_documents 또는 documents 폴더에 있는 파일명
    - original_filename: 원본 파일명 (선택)
    """
    if not vector_store_manager or not document_loader:
        raise HTTPException(status_code=503, detail="RAG 시스템이 초기화되지 않았습니다")
    
    try:
        body = await request.json()
        filename = body.get('filename')
        original_filename = body.get('original_filename', filename)
        
        if not filename:
            raise HTTPException(status_code=400, detail="filename이 필요합니다")
        
        # rag_documents 폴더와 documents 폴더에서 파일 찾기
        file_path = None
        for folder in ["rag_documents", "documents"]:
            test_path = Path(f"./{folder}") / filename
            if test_path.exists():
                file_path = test_path
                break
        
        if not file_path:
            raise HTTPException(status_code=404, detail=f"파일을 찾을 수 없습니다: {filename}")
        
        # 파일 확장자 확인
        file_ext = file_path.suffix.lower()
        if file_ext not in ['.pdf', '.docx', '.doc', '.txt']:
            raise HTTPException(
                status_code=400, 
                detail="RAG 인덱싱은 PDF, DOCX, TXT 파일만 지원합니다"
            )
        
        print(f"📚 RAG 인덱싱 시작: {filename}")

        # 메타데이터 구성
        metadata = {
            "filename": filename,
            "original_filename": original_filename,
            "indexed_at": datetime.now().isoformat(),
            "file_size": file_path.stat().st_size,
            "source": "documents_folder"
        }

        # 백그라운드 태스크로 파싱/임베딩 처리
        task_id = str(uuid.uuid4())
        rag_task_status[task_id] = {
            "status": "pending",
            "filename": filename,
            "original_filename": original_filename,
            "progress": 0,
            "chunks": 0,
            "error": None,
            "metadata": metadata
        }

        thread = threading.Thread(
            target=_process_rag_index,
            args=(task_id, file_path, metadata, filename),
            daemon=True
        )
        thread.start()

        return {
            "success": True,
            "task_id": task_id,
            "status": "processing",
            "message": "인덱싱 요청 완료. 백그라운드에서 처리 중입니다.",
            "filename": filename
        }

    except HTTPException:
        raise
    except Exception as e:
        print(f"[ERROR] RAG 인덱싱 실패: {str(e)}")
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"RAG 인덱싱 실패: {str(e)}")


@app.get("/api/rag/task-status/{task_id}")
async def get_rag_task_status(task_id: str):
    """RAG 백그라운드 태스크 상태 조회"""
    task = rag_task_status.get(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="태스크를 찾을 수 없습니다")
    return task


@app.get("/api/rag/document-status/{filename}")
async def get_document_rag_status(filename: str):
    """
    문서의 RAG 인덱싱 상태 확인
    """
    if not vector_store_manager:
        raise HTTPException(status_code=503, detail="RAG 시스템이 초기화되지 않았습니다")
    
    try:
        # 파일명으로 벡터 DB 검색
        documents = vector_store_manager.get_all_documents()
        
        # 해당 파일명을 가진 문서가 있는지 확인
        indexed_docs = [
            doc for doc in documents 
            if doc.get('metadata', {}).get('filename') == filename or
               doc.get('metadata', {}).get('original_filename') == filename
        ]
        
        is_indexed = len(indexed_docs) > 0
        
        return {
            "success": True,
            "filename": filename,
            "indexed": is_indexed,
            "chunk_count": len(indexed_docs),
            "total_docs_in_rag": len(documents)
        }
        
    except Exception as e:
        print(f"[ERROR] RAG 상태 조회 실패: {str(e)}")
        raise HTTPException(status_code=500, detail=f"RAG 상태 조회 실패: {str(e)}")


# ==================== 시스템 연결 테스트 API ====================

@app.get("/api/test/database")
async def test_database_connection():
    """데이터베이스 연결 테스트"""
    import time
    start_time = time.time()

    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        # 간단한 쿼리 실행
        cursor.execute("SELECT 1 as test")
        result = cursor.fetchone()

        cursor.close()
        conn.close()

        response_time = int((time.time() - start_time) * 1000)

        return {
            "success": True,
            "message": "데이터베이스 연결 정상",
            "host": DB_CONFIG['host'],
            "database": DB_CONFIG['db'],
            "response_time": response_time
        }
    except Exception as e:
        response_time = int((time.time() - start_time) * 1000)
        raise HTTPException(
            status_code=503,
            detail=f"데이터베이스 연결 실패: {str(e)}"
        )

@app.get("/api/test/ftp")
async def test_ftp_connection():
    """FTP 서버 연결 테스트"""
    import time
    from ftplib import FTP

    start_time = time.time()

    try:
        ftp = FTP()
        ftp.encoding = 'utf-8'

        # FTP 연결
        ftp.connect(FTP_CONFIG['host'], FTP_CONFIG['port'])
        ftp.login(FTP_CONFIG['user'], FTP_CONFIG['passwd'])

        # 현재 디렉토리 확인
        current_dir = ftp.pwd()

        ftp.quit()

        response_time = int((time.time() - start_time) * 1000)

        return {
            "success": True,
            "message": "FTP 서버 연결 정상",
            "host": FTP_CONFIG['host'],
            "port": FTP_CONFIG['port'],
            "user": FTP_CONFIG['user'],
            "current_dir": current_dir,
            "response_time": response_time
        }
    except Exception as e:
        response_time = int((time.time() - start_time) * 1000)
        raise HTTPException(
            status_code=503,
            detail=f"FTP 서버 연결 실패: {str(e)}"
        )


# ==================== 서버 시작 ====================
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)

# ================================================
# KoreaWorkingVisa API 추가
# ================================================

# 비자 종류
VISA_TYPES = {
    "E8": {"name": "계절근로비자", "name_en": "Seasonal Worker", "duration": "4-8개월", "type": "단수", "industries": ["농업", "어업"]},
    "D2": {"name": "유학비자", "name_en": "Student Visa", "duration": "2년+", "type": "연장가능", "industries": ["교육"]},
    "D4": {"name": "어학연수비자", "name_en": "Language Training", "duration": "최대2년", "type": "연장가능", "industries": ["교육"]},
    "D10": {"name": "구직비자", "name_en": "Job Seeker", "duration": "6개월-2년", "type": "연장가능", "industries": ["전체"]},
    "F4": {"name": "재외동포비자", "name_en": "Overseas Korean", "duration": "3년+", "type": "복수", "industries": ["전체"]},
}

# 한국 지자체
KR_REGIONS = [
    {"id": 1, "name": "서천군", "province": "충남", "population": 50000, "climate": "온난", "main_industry": "농업", "needed_workers": 100},
    {"id": 2, "name": "해남군", "province": "전남", "population": 68000, "climate": "온난", "main_industry": "농업", "needed_workers": 150},
    {"id": 3, "name": "영덕군", "province": "경북", "population": 35000, "climate": "해양성", "main_industry": "어업", "needed_workers": 80},
    {"id": 4, "name": "고성군", "province": "강원", "population": 27000, "climate": "냉대", "main_industry": "농업", "needed_workers": 60},
]

# 해외 지자체
FOREIGN_REGIONS = [
    {"id": 1, "name": "하노이", "country": "베트남", "country_code": "VN"},
    {"id": 2, "name": "호치민", "country": "베트남", "country_code": "VN"},
    {"id": 3, "name": "방콕", "country": "태국", "country_code": "TH"},
    {"id": 4, "name": "마닐라", "country": "필리핀", "country_code": "PH"},
    {"id": 5, "name": "세부", "country": "필리핀", "country_code": "PH"},
]

# 구인 정보
JOB_LISTINGS = [
    {"id": 1, "region_id": 1, "region": "서천군", "visa_type": "E8", "title": "딸기 농장 근로자", "positions": 50, "salary": "월 220만원", "period": "2026.03 - 2026.10", "benefits": ["숙소제공", "식사제공"]},
    {"id": 2, "region_id": 2, "region": "해남군", "visa_type": "E8", "title": "배추 농장 근로자", "positions": 80, "salary": "월 200만원", "period": "2026.04 - 2026.11", "benefits": ["숙소제공"]},
    {"id": 3, "region_id": 3, "region": "영덕군", "visa_type": "E8", "title": "수산물 가공 근로자", "positions": 40, "salary": "월 230만원", "period": "2026.05 - 2026.12", "benefits": ["숙소제공", "식사제공", "귀국항공료"]},
]

# ========== KoreaWorkingVisa API ==========

@app.get("/api/kwv/visa")
async def get_visa_types():
    """비자 종류 조회"""
    return {"success": True, "data": VISA_TYPES}

@app.get("/api/kwv/visa/{visa_type}")
async def get_visa_detail(visa_type: str):
    """비자 상세 정보"""
    if visa_type.upper() in VISA_TYPES:
        return {"success": True, "data": VISA_TYPES[visa_type.upper()]}
    return {"success": False, "message": "비자 타입을 찾을 수 없습니다"}

@app.get("/api/kwv/regions/kr")
async def get_kr_regions():
    """한국 지자체 목록"""
    return {"success": True, "data": KR_REGIONS}

@app.get("/api/kwv/regions/foreign")
async def get_foreign_regions():
    """해외 지자체 목록"""
    return {"success": True, "data": FOREIGN_REGIONS}

@app.get("/api/kwv/jobs")
async def get_jobs(visa_type: str = None, region_id: int = None):
    """구인 목록 조회"""
    jobs = JOB_LISTINGS
    if visa_type:
        jobs = [j for j in jobs if j["visa_type"] == visa_type.upper()]
    if region_id:
        jobs = [j for j in jobs if j["region_id"] == region_id]
    return {"success": True, "data": jobs, "total": len(jobs)}

@app.get("/api/kwv/jobs/{job_id}")
async def get_job_detail(job_id: int):
    """구인 상세 정보"""
    for job in JOB_LISTINGS:
        if job["id"] == job_id:
            return {"success": True, "data": job}
    return {"success": False, "message": "구인 정보를 찾을 수 없습니다"}

@app.post("/api/kwv/applications")
async def create_application(data: dict):
    """지원서 제출"""
    return {
        "success": True, 
        "message": "지원이 완료되었습니다",
        "application_id": 12345
    }

@app.get("/api/kwv/dashboard/stats")
async def get_dashboard_stats():
    """대시보드 통계"""
    return {
        "success": True,
        "data": {
            "total_jobs": len(JOB_LISTINGS),
            "total_positions": sum(j["positions"] for j in JOB_LISTINGS),
            "kr_regions": len(KR_REGIONS),
            "foreign_regions": len(FOREIGN_REGIONS),
            "visa_types": len(VISA_TYPES)
        }
    }

print("✅ KoreaWorkingVisa API 로드 완료")

# ================================================
# 비자 상세 정보 API
# ================================================

VISA_DETAILS = {
    "E8": {
        "name": "계절근로비자",
        "name_en": "Seasonal Worker Visa",
        "duration": "4-8개월",
        "type": "단수",
        "industries": ["농업", "어업"],
        "description": "농번기 인력 부족을 해소하기 위한 단기 계절근로 비자입니다.",
        "requirements": [
            "만 18세 이상 40세 이하",
            "범죄경력 없음",
            "건강 상태 양호",
            "해당 국가 지자체 추천"
        ],
        "documents": [
            "여권 (유효기간 1년 이상)",
            "비자발급신청서",
            "증명사진 (3.5x4.5cm) 2매",
            "건강진단서",
            "범죄경력증명서",
            "지자체 추천서",
            "고용계약서"
        ],
        "process": [
            {"step": 1, "title": "지자체 신청", "desc": "해외 파트너 지자체에 근로 신청"},
            {"step": 2, "title": "서류 심사", "desc": "한국 지자체에서 서류 검토"},
            {"step": 3, "title": "고용허가", "desc": "고용노동부 고용허가 발급"},
            {"step": 4, "title": "비자 신청", "desc": "대한민국 대사관에서 비자 신청"},
            {"step": 5, "title": "입국", "desc": "한국 입국 및 근무 시작"}
        ],
        "cost": "약 50~100만원 (국가별 상이)",
        "faq": [
            {"q": "계절근로 후 재입국이 가능한가요?", "a": "네, 성실 근로자는 다음 해 우선 선발됩니다."},
            {"q": "가족 동반이 가능한가요?", "a": "아니요, 단독 입국만 가능합니다."},
            {"q": "근무지 변경이 가능한가요?", "a": "원칙적으로 불가하나, 사업장 폐업 등 특별한 경우 가능합니다."}
        ]
    },
    "D2": {
        "name": "유학비자",
        "name_en": "Student Visa",
        "duration": "2년+",
        "type": "연장가능",
        "industries": ["교육"],
        "description": "한국의 대학(원)에서 정규 학위과정을 이수하기 위한 비자입니다.",
        "requirements": [
            "고등학교 졸업 이상",
            "한국어능력시험(TOPIK) 3급 이상 또는 영어능력 증빙",
            "학비 및 생활비 지불 능력",
            "입학허가서 보유"
        ],
        "documents": [
            "여권",
            "비자발급신청서",
            "증명사진 2매",
            "입학허가서",
            "최종학력 증명서",
            "재정능력 증빙 (은행잔고증명 등)",
            "한국어/영어 능력 증명서"
        ],
        "process": [
            {"step": 1, "title": "학교 선택", "desc": "한국 대학 검색 및 선택"},
            {"step": 2, "title": "입학 지원", "desc": "온라인 또는 오프라인 입학 신청"},
            {"step": 3, "title": "입학허가", "desc": "대학으로부터 입학허가서 수령"},
            {"step": 4, "title": "비자 신청", "desc": "대사관에서 D-2 비자 신청"},
            {"step": 5, "title": "입국 및 등록", "desc": "한국 입국 후 외국인등록"}
        ],
        "cost": "비자 수수료 약 6~8만원",
        "faq": [
            {"q": "아르바이트가 가능한가요?", "a": "네, 출입국관리사무소 허가 후 주 20시간 가능합니다."},
            {"q": "D-2에서 취업비자로 변경 가능한가요?", "a": "네, 졸업 후 D-10 또는 E-7 등으로 변경 가능합니다."},
            {"q": "휴학 중에도 체류 가능한가요?", "a": "휴학 시 D-2 자격 유지가 어려울 수 있으니 출입국사무소 상담이 필요합니다."}
        ]
    },
    "D4": {
        "name": "어학연수비자",
        "name_en": "Language Training Visa",
        "duration": "최대 2년",
        "type": "연장가능",
        "industries": ["교육"],
        "description": "한국어 연수기관에서 한국어를 배우기 위한 비자입니다.",
        "requirements": [
            "고등학교 졸업 이상",
            "등록금 납부 능력",
            "정부 인가 어학원 등록"
        ],
        "documents": [
            "여권",
            "비자발급신청서",
            "증명사진 2매",
            "어학원 입학허가서",
            "최종학력 증명서",
            "재정능력 증빙"
        ],
        "process": [
            {"step": 1, "title": "어학원 선택", "desc": "정부 인가 어학원 검색"},
            {"step": 2, "title": "등록 신청", "desc": "어학원에 등록 및 등록금 납부"},
            {"step": 3, "title": "입학허가", "desc": "어학원 입학허가서 수령"},
            {"step": 4, "title": "비자 신청", "desc": "대사관에서 D-4 비자 신청"},
            {"step": 5, "title": "입국", "desc": "한국 입국 후 연수 시작"}
        ],
        "cost": "비자 수수료 약 6~8만원",
        "faq": [
            {"q": "D-4에서 D-2로 변경 가능한가요?", "a": "네, 대학 입학 시 D-2로 자격 변경 가능합니다."},
            {"q": "아르바이트가 가능한가요?", "a": "6개월 이상 체류 후 허가받아 가능합니다."},
            {"q": "연장은 어떻게 하나요?", "a": "출석률 70% 이상 유지 시 연장 가능합니다."}
        ]
    },
    "D10": {
        "name": "구직비자",
        "name_en": "Job Seeker Visa",
        "duration": "6개월-2년",
        "type": "연장가능",
        "industries": ["전체"],
        "description": "한국에서 취업 활동을 하기 위한 구직 비자입니다.",
        "requirements": [
            "학사 학위 이상 (한국 또는 해외)",
            "또는 전문학사 + 경력",
            "범죄경력 없음"
        ],
        "documents": [
            "여권",
            "비자발급신청서",
            "증명사진 2매",
            "학위증명서",
            "성적증명서",
            "경력증명서 (해당자)",
            "구직활동계획서"
        ],
        "process": [
            {"step": 1, "title": "자격 확인", "desc": "D-10 신청 자격 요건 확인"},
            {"step": 2, "title": "서류 준비", "desc": "필요 서류 준비 및 번역/공증"},
            {"step": 3, "title": "비자 신청", "desc": "출입국사무소 또는 대사관 신청"},
            {"step": 4, "title": "구직 활동", "desc": "한국에서 적극적인 구직 활동"},
            {"step": 5, "title": "취업비자 변경", "desc": "취업 시 해당 비자로 변경"}
        ],
        "cost": "비자 수수료 약 13만원",
        "faq": [
            {"q": "D-10 기간 중 아르바이트 가능한가요?", "a": "허가받아 제한적으로 가능합니다."},
            {"q": "연장은 몇 번까지 가능한가요?", "a": "최대 2년까지 연장 가능합니다."},
            {"q": "취업하면 어떤 비자로 변경하나요?", "a": "E-7(특정활동), H-1(워킹홀리데이) 등으로 변경합니다."}
        ]
    },
    "F4": {
        "name": "재외동포비자",
        "name_en": "Overseas Korean Visa",
        "duration": "3년+",
        "type": "복수",
        "industries": ["전체"],
        "description": "재외동포의 한국 내 자유로운 경제활동을 위한 비자입니다.",
        "requirements": [
            "대한민국 국적 보유 후 외국 국적 취득자",
            "또는 부모/조부모가 대한민국 국적 보유자",
            "범죄경력 없음"
        ],
        "documents": [
            "여권",
            "비자발급신청서",
            "증명사진 2매",
            "가족관계 증빙서류",
            "국적 상실/이탈 증빙",
            "범죄경력증명서"
        ],
        "process": [
            {"step": 1, "title": "자격 확인", "desc": "재외동포 자격 요건 확인"},
            {"step": 2, "title": "서류 준비", "desc": "가족관계 증빙 등 서류 준비"},
            {"step": 3, "title": "비자 신청", "desc": "대사관 또는 영사관에서 신청"},
            {"step": 4, "title": "비자 발급", "desc": "심사 후 F-4 비자 발급"},
            {"step": 5, "title": "입국 및 등록", "desc": "입국 후 외국인등록"}
        ],
        "cost": "비자 수수료 약 6~8만원",
        "faq": [
            {"q": "F-4로 어떤 일을 할 수 있나요?", "a": "단순노무직을 제외한 대부분의 직종에서 근무 가능합니다."},
            {"q": "체류 기간은 얼마나 되나요?", "a": "최대 3년이며, 계속 연장 가능합니다."},
            {"q": "가족 초청이 가능한가요?", "a": "배우자와 미성년 자녀 초청이 가능합니다."}
        ]
    }
}

@app.get("/api/kwv/visa/{visa_type}/detail")
async def get_visa_full_detail(visa_type: str):
    """비자 상세 정보 전체"""
    vtype = visa_type.upper()
    if vtype in VISA_DETAILS:
        return {"success": True, "data": VISA_DETAILS[vtype]}
    return {"success": False, "message": "비자 정보를 찾을 수 없습니다"}

print("✅ 비자 상세 API 로드 완료")
