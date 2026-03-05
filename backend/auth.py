# -*- coding: utf-8 -*-
"""
Korea Working Visa - Authentication Module
이메일 기반 회원가입/로그인 API
"""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, validator
import re
from typing import Optional
import pymysql
import hashlib
import secrets
from datetime import datetime
import logging

logger = logging.getLogger("kwv-auth")

router = APIRouter(prefix="/api/kwv", tags=["KWV Authentication"])

# ==================== Pydantic Models ====================

def validate_email(email: str) -> bool:
    """이메일 형식 검증"""
    pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
    return bool(re.match(pattern, email))

class RegisterRequest(BaseModel):
    email: str
    password: str
    firstName: str
    lastName: str
    koreanName: Optional[str] = None
    birthDate: str
    nationality: str
    phone: str
    agreeMarketing: bool = False

class LoginRequest(BaseModel):
    email: str
    password: str
    rememberMe: bool = False

class EmailCheckRequest(BaseModel):
    email: str

# ==================== Helper Functions ====================

def hash_password(password: str, salt: str = None) -> tuple:
    """비밀번호 해싱 (SHA-256 + salt)"""
    if salt is None:
        salt = secrets.token_hex(16)
    hashed = hashlib.sha256((password + salt).encode()).hexdigest()
    return hashed, salt

def verify_password(password: str, hashed: str, salt: str) -> bool:
    """비밀번호 검증"""
    check_hash, _ = hash_password(password, salt)
    return check_hash == hashed

def ensure_kwv_users_table(cursor):
    """kwv_users 테이블이 없으면 생성"""
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS kwv_users (
            id INT AUTO_INCREMENT PRIMARY KEY,
            email VARCHAR(255) NOT NULL UNIQUE,
            password_hash VARCHAR(255) NOT NULL,
            password_salt VARCHAR(64) NOT NULL,
            first_name VARCHAR(100) NOT NULL,
            last_name VARCHAR(100) NOT NULL,
            korean_name VARCHAR(100) DEFAULT NULL,
            birth_date DATE NOT NULL,
            nationality VARCHAR(10) NOT NULL,
            phone VARCHAR(30) NOT NULL,
            agree_marketing TINYINT(1) DEFAULT 0,
            status ENUM('active', 'inactive', 'suspended') DEFAULT 'active',
            email_verified TINYINT(1) DEFAULT 0,
            last_login DATETIME DEFAULT NULL,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
            INDEX idx_email (email),
            INDEX idx_status (status)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """)

# ==================== API Endpoints ====================

@router.post("/register")
async def register(request: RegisterRequest):
    """회원가입 API"""
    from main import get_db_connection

    # 이메일 유효성 검사
    if not validate_email(request.email):
        raise HTTPException(status_code=400, detail="올바른 이메일 형식이 아닙니다.")

    # 비밀번호 유효성 검사
    if len(request.password) < 8:
        raise HTTPException(status_code=400, detail="비밀번호는 8자 이상이어야 합니다.")

    conn = get_db_connection()
    try:
        cursor = conn.cursor(pymysql.cursors.DictCursor)

        # 테이블 확인/생성
        ensure_kwv_users_table(cursor)
        conn.commit()

        # 이메일 중복 확인
        cursor.execute("SELECT id FROM kwv_users WHERE email = %s", (request.email,))
        if cursor.fetchone():
            raise HTTPException(status_code=400, detail="이미 사용 중인 이메일입니다.")

        # 비밀번호 해싱
        password_hash, password_salt = hash_password(request.password)

        # 사용자 등록
        cursor.execute("""
            INSERT INTO kwv_users (
                email, password_hash, password_salt, first_name, last_name,
                korean_name, birth_date, nationality, phone, agree_marketing
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """, (
            request.email,
            password_hash,
            password_salt,
            request.firstName,
            request.lastName,
            request.koreanName,
            request.birthDate,
            request.nationality,
            request.phone,
            1 if request.agreeMarketing else 0
        ))
        conn.commit()

        user_id = cursor.lastrowid
        logger.info(f"New user registered: {request.email} (ID: {user_id})")

        return {
            "success": True,
            "message": "회원가입이 완료되었습니다.",
            "userId": user_id
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Registration error: {str(e)}")
        raise HTTPException(status_code=500, detail="회원가입 처리 중 오류가 발생했습니다.")
    finally:
        conn.close()

@router.post("/login")
async def login(request: LoginRequest):
    """로그인 API"""
    from main import get_db_connection

    conn = get_db_connection()
    try:
        cursor = conn.cursor(pymysql.cursors.DictCursor)

        # 테이블 확인/생성
        ensure_kwv_users_table(cursor)

        # 사용자 조회
        cursor.execute("""
            SELECT id, email, password_hash, password_salt, first_name, last_name,
                   korean_name, nationality, status, last_login
            FROM kwv_users WHERE email = %s
        """, (request.email,))

        user = cursor.fetchone()

        if not user:
            raise HTTPException(status_code=401, detail="이메일 또는 비밀번호가 올바르지 않습니다.")

        # 비밀번호 검증
        if not verify_password(request.password, user['password_hash'], user['password_salt']):
            raise HTTPException(status_code=401, detail="이메일 또는 비밀번호가 올바르지 않습니다.")

        # 계정 상태 확인
        if user['status'] != 'active':
            raise HTTPException(status_code=403, detail="비활성화된 계정입니다. 관리자에게 문의하세요.")

        # 마지막 로그인 시간 업데이트
        cursor.execute("UPDATE kwv_users SET last_login = NOW() WHERE id = %s", (user['id'],))
        conn.commit()

        logger.info(f"User logged in: {request.email}")

        # 응답 데이터 (비밀번호 제외)
        return {
            "success": True,
            "message": "로그인 성공",
            "user": {
                "id": user['id'],
                "email": user['email'],
                "firstName": user['first_name'],
                "lastName": user['last_name'],
                "koreanName": user['korean_name'],
                "nationality": user['nationality']
            },
            "redirect": "kwv-dashboard.html"
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Login error: {str(e)}")
        raise HTTPException(status_code=500, detail="로그인 처리 중 오류가 발생했습니다.")
    finally:
        conn.close()

@router.post("/check-email")
async def check_email(request: EmailCheckRequest):
    """이메일 중복 확인 API"""
    from main import get_db_connection

    conn = get_db_connection()
    try:
        cursor = conn.cursor(pymysql.cursors.DictCursor)

        # 테이블 확인/생성
        ensure_kwv_users_table(cursor)

        cursor.execute("SELECT id FROM kwv_users WHERE email = %s", (request.email,))
        exists = cursor.fetchone() is not None

        return {
            "success": True,
            "available": not exists,
            "message": "이미 사용 중인 이메일입니다." if exists else "사용 가능한 이메일입니다."
        }

    except Exception as e:
        logger.error(f"Email check error: {str(e)}")
        raise HTTPException(status_code=500, detail="확인 중 오류가 발생했습니다.")
    finally:
        conn.close()

@router.post("/logout")
async def logout():
    """로그아웃 API"""
    return {
        "success": True,
        "message": "로그아웃 되었습니다.",
        "redirect": "kwv-login.html"
    }
