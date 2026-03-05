"""
교육관리시스템 확장 API
- 강사코드관리
- 강사관리  
- 교과목관리
- 공휴일관리
- 과정(학급)관리
- 프로젝트관리
- 수업관리(시간표)
"""

from fastapi import HTTPException
from typing import Optional, List
import pymysql
from datetime import datetime, date

DB_CONFIG = {
    'host': 'bitnmeta2.synology.me',
    'user': 'iyrc',
    'passwd': 'Dodan1004!',
    'db': 'bh2025',
    'charset': 'utf8',
    'port': 3307
}

def get_db_connection():
    return pymysql.connect(**DB_CONFIG)

def convert_datetime(obj):
    """datetime 객체를 문자열로 변환"""
    for key, value in obj.items():
        if isinstance(value, (datetime, date)):
            obj[key] = value.isoformat()
        elif isinstance(value, bytes):
            obj[key] = None
    return obj

# ==================== 강사코드관리 API ====================

async def get_instructor_codes():
    """강사코드 목록 조회"""
    conn = get_db_connection()
    try:
        cursor = conn.cursor(pymysql.cursors.DictCursor)
        cursor.execute("SELECT * FROM instructor_codes ORDER BY code")
        codes = cursor.fetchall()
        return [convert_datetime(code) for code in codes]
    finally:
        conn.close()

async def create_instructor_code(data: dict):
    """강사코드 생성"""
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        query = """
            INSERT INTO instructor_codes (code, name, type)
            VALUES (%s, %s, %s)
        """
        cursor.execute(query, (data['code'], data['name'], data['type']))
        conn.commit()
        return {"code": data['code']}
    finally:
        conn.close()

async def update_instructor_code(code: str, data: dict):
    """강사코드 수정"""
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        query = """
            UPDATE instructor_codes
            SET name = %s, type = %s
            WHERE code = %s
        """
        cursor.execute(query, (data['name'], data['type'], code))
        conn.commit()
        return {"code": code}
    finally:
        conn.close()

async def delete_instructor_code(code: str):
    """강사코드 삭제"""
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM instructor_codes WHERE code = %s", (code,))
        conn.commit()
        return {"message": "강사코드가 삭제되었습니다"}
    finally:
        conn.close()

# ==================== 강사관리 API ====================

async def get_instructors(search: Optional[str] = None):
    """강사 목록 조회"""
    conn = get_db_connection()
    try:
        cursor = conn.cursor(pymysql.cursors.DictCursor)
        
        query = """
            SELECT i.*, ic.name as type_name
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

async def create_instructor(data: dict):
    """강사 생성"""
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        query = """
            INSERT INTO instructors (code, name, phone, major, instructor_type, email)
            VALUES (%s, %s, %s, %s, %s, %s)
        """
        cursor.execute(query, (
            data['code'], data['name'], data.get('phone'),
            data.get('major'), data.get('instructor_type'), data.get('email')
        ))
        conn.commit()
        return {"code": data['code']}
    finally:
        conn.close()

async def update_instructor(code: str, data: dict):
    """강사 수정"""
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        query = """
            UPDATE instructors
            SET name = %s, phone = %s, major = %s, instructor_type = %s, email = %s
            WHERE code = %s
        """
        cursor.execute(query, (
            data['name'], data.get('phone'), data.get('major'),
            data.get('instructor_type'), data.get('email'), code
        ))
        conn.commit()
        return {"code": code}
    finally:
        conn.close()

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

# ==================== 공휴일관리 API ====================

async def get_holidays(year: Optional[int] = None):
    """공휴일 목록 조회"""
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

async def create_holiday(data: dict):
    """공휴일 생성"""
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        query = """
            INSERT INTO holidays (holiday_date, name, is_legal)
            VALUES (%s, %s, %s)
        """
        cursor.execute(query, (data['holiday_date'], data['name'], data.get('is_legal', 0)))
        conn.commit()
        return {"id": cursor.lastrowid}
    finally:
        conn.close()

async def update_holiday(id: int, data: dict):
    """공휴일 수정"""
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        query = """
            UPDATE holidays
            SET holiday_date = %s, name = %s, is_legal = %s
            WHERE id = %s
        """
        cursor.execute(query, (data['holiday_date'], data['name'], data.get('is_legal', 0), id))
        conn.commit()
        return {"id": id}
    finally:
        conn.close()

async def delete_holiday(id: int):
    """공휴일 삭제"""
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM holidays WHERE id = %s", (id,))
        conn.commit()
        return {"message": "공휴일이 삭제되었습니다"}
    finally:
        conn.close()

# ==================== 과정(학급)관리 API ====================

async def get_courses():
    """과정 목록 조회"""
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
        return [convert_datetime(course) for course in courses]
    finally:
        conn.close()

async def get_course(code: str):
    """특정 과정 조회"""
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
        return convert_datetime(course)
    finally:
        conn.close()

async def create_course(data: dict):
    """과정 생성"""
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        query = """
            INSERT INTO courses (code, name, lecture_hours, project_hours, internship_hours,
                                capacity, location, notes, start_date, lecture_end_date,
                                project_end_date, internship_end_date, final_end_date, total_days)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """
        cursor.execute(query, (
            data['code'], data['name'], data['lecture_hours'], data['project_hours'],
            data['internship_hours'], data['capacity'], data.get('location'),
            data.get('notes'), data.get('start_date'), data.get('lecture_end_date'),
            data.get('project_end_date'), data.get('internship_end_date'),
            data.get('final_end_date'), data.get('total_days')
        ))
        conn.commit()
        return {"code": data['code']}
    finally:
        conn.close()

async def update_course(code: str, data: dict):
    """과정 수정"""
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        query = """
            UPDATE courses
            SET name = %s, lecture_hours = %s, project_hours = %s, internship_hours = %s,
                capacity = %s, location = %s, notes = %s, start_date = %s,
                lecture_end_date = %s, project_end_date = %s, internship_end_date = %s,
                final_end_date = %s, total_days = %s
            WHERE code = %s
        """
        cursor.execute(query, (
            data['name'], data['lecture_hours'], data['project_hours'],
            data['internship_hours'], data['capacity'], data.get('location'),
            data.get('notes'), data.get('start_date'), data.get('lecture_end_date'),
            data.get('project_end_date'), data.get('internship_end_date'),
            data.get('final_end_date'), data.get('total_days'), code
        ))
        conn.commit()
        return {"code": code}
    finally:
        conn.close()

async def delete_course(code: str):
    """과정 삭제"""
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM courses WHERE code = %s", (code,))
        conn.commit()
        return {"message": "과정이 삭제되었습니다"}
    finally:
        conn.close()

# ==================== 프로젝트관리 API ====================

async def get_projects(course_code: Optional[str] = None):
    """프로젝트 목록 조회"""
    conn = get_db_connection()
    try:
        cursor = conn.cursor(pymysql.cursors.DictCursor)
        
        query = """
            SELECT p.*, c.name as course_name
            FROM projects p
            LEFT JOIN courses c ON p.course_code = c.code
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

async def get_project(code: str):
    """특정 프로젝트 조회"""
    conn = get_db_connection()
    try:
        cursor = conn.cursor(pymysql.cursors.DictCursor)
        cursor.execute("""
            SELECT p.*, c.name as course_name
            FROM projects p
            LEFT JOIN courses c ON p.course_code = c.code
            WHERE p.code = %s
        """, (code,))
        project = cursor.fetchone()
        if not project:
            raise HTTPException(status_code=404, detail="프로젝트를 찾을 수 없습니다")
        return convert_datetime(project)
    finally:
        conn.close()

async def create_project(data: dict):
    """프로젝트 생성"""
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        query = """
            INSERT INTO projects (code, name, course_code,
                                 member1_name, member1_phone,
                                 member2_name, member2_phone,
                                 member3_name, member3_phone,
                                 member4_name, member4_phone,
                                 member5_name, member5_phone)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """
        cursor.execute(query, (
            data['code'], data['name'], data.get('course_code'),
            data.get('member1_name'), data.get('member1_phone'),
            data.get('member2_name'), data.get('member2_phone'),
            data.get('member3_name'), data.get('member3_phone'),
            data.get('member4_name'), data.get('member4_phone'),
            data.get('member5_name'), data.get('member5_phone')
        ))
        conn.commit()
        return {"code": data['code']}
    finally:
        conn.close()

async def update_project(code: str, data: dict):
    """프로젝트 수정"""
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        query = """
            UPDATE projects
            SET name = %s, course_code = %s,
                member1_name = %s, member1_phone = %s,
                member2_name = %s, member2_phone = %s,
                member3_name = %s, member3_phone = %s,
                member4_name = %s, member4_phone = %s,
                member5_name = %s, member5_phone = %s
            WHERE code = %s
        """
        cursor.execute(query, (
            data['name'], data.get('course_code'),
            data.get('member1_name'), data.get('member1_phone'),
            data.get('member2_name'), data.get('member2_phone'),
            data.get('member3_name'), data.get('member3_phone'),
            data.get('member4_name'), data.get('member4_phone'),
            data.get('member5_name'), data.get('member5_phone'),
            code
        ))
        conn.commit()
        return {"code": code}
    finally:
        conn.close()

async def delete_project(code: str):
    """프로젝트 삭제"""
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM projects WHERE code = %s", (code,))
        conn.commit()
        return {"message": "프로젝트가 삭제되었습니다"}
    finally:
        conn.close()

# ==================== 수업관리(시간표) API ====================

async def get_timetables(course_code: Optional[str] = None, start_date: Optional[str] = None, end_date: Optional[str] = None):
    """시간표 목록 조회"""
    conn = get_db_connection()
    try:
        cursor = conn.cursor(pymysql.cursors.DictCursor)
        
        query = """
            SELECT t.*, 
                   c.name as course_name,
                   s.name as subject_name,
                   i.name as instructor_name
            FROM timetables t
            LEFT JOIN courses c ON t.course_code = c.code
            LEFT JOIN subjects s ON t.subject_code = s.code
            LEFT JOIN instructors i ON t.instructor_code = i.code
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
        return [convert_datetime(tt) for tt in timetables]
    finally:
        conn.close()

async def get_timetable(id: int):
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
        """, (id,))
        timetable = cursor.fetchone()
        if not timetable:
            raise HTTPException(status_code=404, detail="시간표를 찾을 수 없습니다")
        return convert_datetime(timetable)
    finally:
        conn.close()

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

async def update_timetable(id: int, data: dict):
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
            data['type'], data.get('notes'), id
        ))
        conn.commit()
        return {"id": id}
    finally:
        conn.close()

async def delete_timetable(id: int):
    """시간표 삭제"""
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM timetables WHERE id = %s", (id,))
        conn.commit()
        return {"message": "시간표가 삭제되었습니다"}
    finally:
        conn.close()
