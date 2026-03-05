#!/usr/bin/env python3
"""projects 테이블에 id 컬럼 추가"""

import pymysql
import os
from dotenv import load_dotenv

load_dotenv()

def add_id_to_projects():
    """projects 테이블에 id AUTO_INCREMENT 컬럼 추가"""
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
        
        # id 컬럼이 이미 있는지 확인
        cursor.execute("SHOW COLUMNS FROM projects LIKE 'id'")
        if cursor.fetchone():
            print("⚠️  id 컬럼이 이미 존재합니다")
            return
        
        # 기존 PRIMARY KEY 제거
        print("기존 PRIMARY KEY (code) 제거 중...")
        cursor.execute("ALTER TABLE projects DROP PRIMARY KEY")
        conn.commit()
        print("✅ PRIMARY KEY 제거 완료")
        
        # code를 UNIQUE로 변경
        print("code를 UNIQUE INDEX로 설정 중...")
        cursor.execute("ALTER TABLE projects ADD UNIQUE KEY unique_code (code)")
        conn.commit()
        print("✅ code UNIQUE INDEX 설정 완료")
        
        # id 컬럼 추가 (첫 번째 컬럼으로)
        print("id AUTO_INCREMENT 컬럼 추가 중...")
        cursor.execute("""
            ALTER TABLE projects 
            ADD COLUMN id INT AUTO_INCREMENT PRIMARY KEY FIRST
        """)
        conn.commit()
        print("✅ id 컬럼 추가 완료")
        
        # 결과 확인
        cursor.execute("SELECT id, code, name FROM projects LIMIT 5")
        rows = cursor.fetchall()
        print("\n✅ 완료! 샘플 데이터:")
        for row in rows:
            print(f"  ID: {row[0]}, Code: {row[1]}, Name: {row[2]}")
            
    except Exception as e:
        print(f"❌ 오류: {e}")
        conn.rollback()
    finally:
        conn.close()

if __name__ == '__main__':
    print("🔧 projects 테이블에 id 컬럼 추가 중...")
    add_id_to_projects()
