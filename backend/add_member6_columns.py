#!/usr/bin/env python3
"""projects 테이블에 member6 컬럼 추가"""

import pymysql
import os
from dotenv import load_dotenv

# 환경변수 로드
load_dotenv()

def add_member6_columns():
    """projects 테이블에 member6 관련 컬럼 추가"""
    conn = pymysql.connect(
        host=os.getenv('DB_HOST'),
        port=int(os.getenv('DB_PORT', 3306)),
        user=os.getenv('DB_USER'),
        password=os.getenv('DB_PASSWORD'),
        database=os.getenv('DB_NAME'),
        charset='utf8mb4'
    )
    
    try:
        cursor = conn.cursor()
        
        # member6 관련 컬럼 추가
        alter_queries = [
            "ALTER TABLE projects ADD COLUMN IF NOT EXISTS member6_name VARCHAR(100)",
            "ALTER TABLE projects ADD COLUMN IF NOT EXISTS member6_phone VARCHAR(20)",
            "ALTER TABLE projects ADD COLUMN IF NOT EXISTS member6_code VARCHAR(20)"
        ]
        
        for query in alter_queries:
            try:
                print(f"실행 중: {query}")
                cursor.execute(query)
                conn.commit()
                print("✅ 성공")
            except pymysql.err.OperationalError as e:
                if "Duplicate column name" in str(e):
                    print(f"⚠️  컬럼이 이미 존재합니다: {e}")
                else:
                    print(f"❌ 오류: {e}")
                    raise
        
        # 결과 확인
        cursor.execute("DESCRIBE projects")
        columns = cursor.fetchall()
        
        member6_cols = [col for col in columns if 'member6' in col[0]]
        if member6_cols:
            print("\n✅ member6 컬럼이 성공적으로 추가되었습니다:")
            for col in member6_cols:
                print(f"  - {col[0]}: {col[1]}")
        else:
            print("\n❌ member6 컬럼 추가 실패")
            
    finally:
        conn.close()

if __name__ == '__main__':
    print("🔧 projects 테이블에 member6 컬럼 추가 중...")
    add_member6_columns()
    print("\n✅ 완료!")
