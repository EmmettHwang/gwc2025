#!/usr/bin/env python3
"""
instructor_codes 테이블에 permissions와 default_screen 컬럼 추가
"""
import pymysql
import os
import json

DB_CONFIG = {
    'host': os.getenv('DB_HOST', 'bitnmeta2.synology.me'),
    'user': os.getenv('DB_USER', 'iyrc'),
    'passwd': os.getenv('DB_PASSWORD', 'Dodan1004!'),
    'db': os.getenv('DB_NAME', 'bh2025'),
    'charset': 'utf8',
    'port': int(os.getenv('DB_PORT', '3307'))
}

def main():
    conn = pymysql.connect(**DB_CONFIG)
    cursor = conn.cursor()
    
    try:
        print("=== instructor_codes 테이블 업데이트 시작 ===\n")
        
        # Check if permissions column exists
        cursor.execute("SHOW COLUMNS FROM instructor_codes LIKE 'permissions'")
        if not cursor.fetchone():
            print("➕ permissions 컬럼 추가 중...")
            cursor.execute("""
                ALTER TABLE instructor_codes 
                ADD COLUMN permissions JSON DEFAULT NULL
            """)
            conn.commit()
            print("✅ permissions 컬럼 추가 완료\n")
        else:
            print("✓ permissions 컬럼 이미 존재\n")
        
        # Check if default_screen column exists
        cursor.execute("SHOW COLUMNS FROM instructor_codes LIKE 'default_screen'")
        if not cursor.fetchone():
            print("➕ default_screen 컬럼 추가 중...")
            cursor.execute("""
                ALTER TABLE instructor_codes 
                ADD COLUMN default_screen VARCHAR(50) DEFAULT 'dashboard'
            """)
            conn.commit()
            print("✅ default_screen 컬럼 추가 완료\n")
        else:
            print("✓ default_screen 컬럼 이미 존재\n")
        
        # Set default permissions for all instructor codes
        default_permissions = {
            "dashboard": True,
            "courses": True,
            "students": True,
            "counselings": True,
            "timetables": True,
            "training-logs": True,
            "projects": True,
            "team-activity-logs": True
        }
        
        cursor.execute("SELECT code, name FROM instructor_codes")
        codes = cursor.fetchall()
        
        print(f"📝 {len(codes)}개 강사 코드 권한 설정 중...")
        for code, name in codes:
            cursor.execute("""
                UPDATE instructor_codes 
                SET permissions = %s, default_screen = 'dashboard'
                WHERE code = %s AND (permissions IS NULL OR permissions = '')
            """, (json.dumps(default_permissions), code))
            print(f"  ✓ {code} ({name})")
        
        conn.commit()
        print(f"\n✅ 모든 작업 완료!")
        
    except Exception as e:
        print(f"\n❌ 에러 발생: {e}")
        conn.rollback()
        raise
    finally:
        conn.close()

if __name__ == "__main__":
    main()
