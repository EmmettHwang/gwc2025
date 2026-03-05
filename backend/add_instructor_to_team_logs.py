#!/usr/bin/env python3
"""team_activity_logs 테이블에 instructor_code 컬럼 추가"""

import pymysql
import os
import sys

# .env 파일에서 직접 읽기
env_path = '/home/user/webapp/backend/.env'
env_vars = {}
with open(env_path, 'r') as f:
    for line in f:
        line = line.strip()
        if line and not line.startswith('#') and '=' in line:
            key, value = line.split('=', 1)
            env_vars[key] = value.strip()

def add_instructor_code():
    """team_activity_logs 테이블에 instructor_code 컬럼 추가"""
    conn = pymysql.connect(
        host=env_vars.get('DB_HOST'),
        port=int(env_vars.get('DB_PORT', 3306)),
        user=env_vars.get('DB_USER'),
        password=env_vars.get('DB_PASSWORD'),
        database=env_vars.get('DB_NAME'),
        charset='utf8mb4'
    )
    
    try:
        cursor = conn.cursor()
        
        # instructor_code 컬럼이 이미 있는지 확인
        cursor.execute("SHOW COLUMNS FROM team_activity_logs LIKE 'instructor_code'")
        if cursor.fetchone():
            print("⚠️  instructor_code 컬럼이 이미 존재합니다")
            return
        
        # instructor_code 컬럼 추가
        print("instructor_code 컬럼 추가 중...")
        cursor.execute("""
            ALTER TABLE team_activity_logs
            ADD COLUMN instructor_code VARCHAR(20) AFTER project_id,
            ADD INDEX idx_instructor_code (instructor_code)
        """)
        conn.commit()
        print("✅ instructor_code 컬럼이 추가되었습니다")
        
        # 컬럼 확인
        cursor.execute("SHOW COLUMNS FROM team_activity_logs")
        columns = cursor.fetchall()
        print("\n✅ 현재 team_activity_logs 테이블 구조:")
        for col in columns:
            print(f"  - {col[0]} ({col[1]})")
            
    except Exception as e:
        print(f"❌ 오류: {e}")
        conn.rollback()
        sys.exit(1)
    finally:
        conn.close()

if __name__ == "__main__":
    add_instructor_code()
