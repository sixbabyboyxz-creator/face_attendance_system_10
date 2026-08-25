# -*- coding: utf-8 -*-
"""
database.py
เลเยอร์จัดการฐานข้อมูล SQLite สำหรับระบบเช็คชื่อด้วยใบหน้า

ตารางหลัก:
  - students          : ข้อมูลนักเรียน
  - face_embeddings   : เวกเตอร์ใบหน้าของนักเรียนแต่ละคน (อาจมีหลายภาพต่อคน)
  - events            : กิจกรรมที่เปิดให้เช็คชื่อ
  - attendance        : บันทึกการเช็คชื่อ (student x event)
"""

import sqlite3
import numpy as np
import datetime
from contextlib import contextmanager

import config


def _connect():
    conn = sqlite3.connect(config.DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON")
    conn.row_factory = sqlite3.Row
    return conn


@contextmanager
def get_conn():
    conn = _connect()
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db():
    """สร้างตารางทั้งหมดถ้ายังไม่มี เรียกครั้งเดียวตอนเริ่มโปรแกรม"""
    with get_conn() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS students (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                student_code  TEXT UNIQUE NOT NULL,
                full_name     TEXT NOT NULL,
                class_room    TEXT,
                photo_path    TEXT,
                created_at    TEXT DEFAULT (datetime('now', 'localtime'))
            );

            CREATE TABLE IF NOT EXISTS face_embeddings (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                student_id    INTEGER NOT NULL REFERENCES students(id) ON DELETE CASCADE,
                embedding     BLOB NOT NULL,
                dim           INTEGER NOT NULL,
                created_at    TEXT DEFAULT (datetime('now', 'localtime'))
            );

            CREATE TABLE IF NOT EXISTS events (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                event_name    TEXT NOT NULL,
                event_date    TEXT,
                location      TEXT,
                created_at    TEXT DEFAULT (datetime('now', 'localtime'))
            );

            CREATE TABLE IF NOT EXISTS attendance (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                event_id      INTEGER NOT NULL REFERENCES events(id) ON DELETE CASCADE,
                student_id    INTEGER NOT NULL REFERENCES students(id) ON DELETE CASCADE,
                checkin_time  TEXT DEFAULT (datetime('now', 'localtime')),
                confidence    REAL,
                UNIQUE(event_id, student_id)
            );

            CREATE TABLE IF NOT EXISTS settings (
                key           TEXT PRIMARY KEY,
                value         TEXT
            );

            -- ข้อมูลระดับ "กลุ่มเรียน" (เช่น จากรายงาน สอศ.) แยกจากข้อมูลรายบุคคล
            -- เพราะรหัสกลุ่มเรียน/ชื่อกลุ่มเรียน/ครูที่ปรึกษา เป็นข้อมูลของทั้งห้อง ไม่ใช่ของนักเรียนคนเดียว
            CREATE TABLE IF NOT EXISTS class_groups (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                group_code      TEXT,
                group_name      TEXT,
                level           TEXT,
                advisor_teacher TEXT,
                created_at      TEXT DEFAULT (datetime('now', 'localtime'))
            );

            CREATE INDEX IF NOT EXISTS idx_embeddings_student ON face_embeddings(student_id);
            CREATE INDEX IF NOT EXISTS idx_attendance_event ON attendance(event_id);
            """
        )

        # Migration: เพิ่มคอลัมน์ใหม่ให้ตาราง students ที่อาจสร้างไว้ก่อนฟีเจอร์นี้จะมีอยู่
        # (ต้องดัก error เผื่อคอลัมน์มีอยู่แล้ว เพราะ SQLite ไม่มี "ADD COLUMN IF NOT EXISTS")
        existing_cols = {row["name"] for row in conn.execute("PRAGMA table_info(students)")}
        for col_def in (
            ("student_type", "TEXT DEFAULT ''"),
            ("status", "TEXT DEFAULT ''"),
            ("department", "TEXT DEFAULT ''"),
        ):
            col_name, col_type = col_def
            if col_name not in existing_cols:
                conn.execute(f"ALTER TABLE students ADD COLUMN {col_name} {col_type}")

        # Migration: เพิ่มคอลัมน์ "สแกนออก" ให้ตาราง attendance (เดิมมีแค่ checkin_time/confidence
        # ซึ่งถือเป็น "สแกนเข้า" อยู่แล้ว ไม่ต้องแก้ชื่อคอลัมน์เดิม กันกระทบข้อมูลเก่า)
        existing_att_cols = {row["name"] for row in conn.execute("PRAGMA table_info(attendance)")}
        for col_def in (
            ("check_out_time", "TEXT"),
            ("confidence_out", "REAL"),
        ):
            col_name, col_type = col_def
            if col_name not in existing_att_cols:
                conn.execute(f"ALTER TABLE attendance ADD COLUMN {col_name} {col_type}")


# ---------------------------------------------------------------------------
# Settings (เก็บค่าที่ผู้ใช้ตั้งไว้ เช่น กล้องที่เลือกใช้ล่าสุด)
# ---------------------------------------------------------------------------

def get_setting(key, default=None):
    with get_conn() as conn:
        row = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
        return row["value"] if row else default


def set_setting(key, value):
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO settings (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, str(value)),
        )


# ---------------------------------------------------------------------------
# Students
# ---------------------------------------------------------------------------

def add_student(
    student_code, full_name, class_room="", photo_path=None,
    student_type="", status="", department="",
):
    with get_conn() as conn:
        cur = conn.execute(
            "INSERT INTO students (student_code, full_name, class_room, photo_path, "
            "student_type, status, department) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (student_code, full_name, class_room, photo_path, student_type, status, department),
        )
        return cur.lastrowid


def get_student_by_code(student_code):
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM students WHERE student_code = ?", (student_code,)
        ).fetchone()
        return dict(row) if row else None


def get_student_by_id(student_id):
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM students WHERE id = ?", (student_id,)
        ).fetchone()
        return dict(row) if row else None


def list_students(search_text="", class_room=None, department=None):
    """
    ดึงรายชื่อนักเรียน กรองด้วยคำค้นหา (รหัส/ชื่อ), ห้อง/กลุ่มเรียน, และ/หรือสาขา (ตรงเป๊ะ) ได้
    class_room/department = None หรือ "" หรือ "ทั้งหมด" = ไม่กรองส่วนนั้น
    """
    query = "SELECT * FROM students WHERE 1=1"
    params = []

    if search_text:
        query += " AND (student_code LIKE ? OR full_name LIKE ?)"
        like = f"%{search_text}%"
        params += [like, like]

    if class_room and class_room != "ทั้งหมด":
        query += " AND class_room = ?"
        params.append(class_room)

    if department and department != "ทั้งหมด":
        query += " AND department = ?"
        params.append(department)

    query += " ORDER BY department, class_room, full_name"

    with get_conn() as conn:
        rows = conn.execute(query, params).fetchall()
        return [dict(r) for r in rows]


def list_departments():
    """รายชื่อสาขาทั้งหมดที่มีนักเรียนอยู่ (ไม่ซ้ำ) ใช้ทำ dropdown กรอง"""
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT DISTINCT department FROM students "
            "WHERE department IS NOT NULL AND department != '' "
            "ORDER BY department"
        ).fetchall()
        return [r["department"] for r in rows]


def list_class_rooms():
    """รายชื่อห้อง/ระดับชั้นทั้งหมดที่มีนักเรียนอยู่ (ไม่ซ้ำ) ใช้ทำ dropdown กรอง"""
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT DISTINCT class_room FROM students "
            "WHERE class_room IS NOT NULL AND class_room != '' "
            "ORDER BY class_room"
        ).fetchall()
        return [r["class_room"] for r in rows]


def delete_student(student_id):
    with get_conn() as conn:
        conn.execute("DELETE FROM students WHERE id = ?", (student_id,))


# ---------------------------------------------------------------------------
# Class groups (ข้อมูลระดับกลุ่มเรียน: รหัสกลุ่มเรียน/ชื่อกลุ่มเรียน/ชั้นปี/ครูที่ปรึกษา)
# ---------------------------------------------------------------------------

def get_or_create_class_group(group_code="", group_name="", level="", advisor_teacher=""):
    """
    หากลุ่มเรียนที่ตรงกับ group_code (ถ้ามี) หรือ level ถ้าไม่มี group_code
    ถ้าเจอและบางฟิลด์ว่างอยู่ ให้อัปเดตด้วยข้อมูลใหม่ที่ไม่ว่าง / ถ้าไม่เจอให้สร้างใหม่
    คืนค่า id ของ class_groups (หรือ None ถ้าไม่มีข้อมูลระบุกลุ่มเรียนเลย)
    """
    if not group_code and not level:
        return None

    with get_conn() as conn:
        row = None
        if group_code:
            row = conn.execute(
                "SELECT * FROM class_groups WHERE group_code = ?", (group_code,)
            ).fetchone()
        if row is None and level:
            row = conn.execute(
                "SELECT * FROM class_groups WHERE level = ? AND (group_code IS NULL OR group_code = '')",
                (level,),
            ).fetchone()

        if row is not None:
            updates = {}
            if group_name and not row["group_name"]:
                updates["group_name"] = group_name
            if level and not row["level"]:
                updates["level"] = level
            if advisor_teacher and not row["advisor_teacher"]:
                updates["advisor_teacher"] = advisor_teacher
            if updates:
                set_clause = ", ".join(f"{k} = ?" for k in updates)
                conn.execute(
                    f"UPDATE class_groups SET {set_clause} WHERE id = ?",
                    (*updates.values(), row["id"]),
                )
            return row["id"]

        cur = conn.execute(
            "INSERT INTO class_groups (group_code, group_name, level, advisor_teacher) "
            "VALUES (?, ?, ?, ?)",
            (group_code, group_name, level, advisor_teacher),
        )
        return cur.lastrowid


def get_class_group_by_level(level):
    """หาข้อมูลกลุ่มเรียนจากค่าห้อง/ชั้นปี (level) เอาแค่รายการแรกที่พบ"""
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM class_groups WHERE level = ? ORDER BY id LIMIT 1", (level,)
        ).fetchone()
        return dict(row) if row else None


def list_class_groups():
    with get_conn() as conn:
        rows = conn.execute("SELECT * FROM class_groups ORDER BY level").fetchall()
        return [dict(r) for r in rows]


# ---------------------------------------------------------------------------
# Face embeddings
# ---------------------------------------------------------------------------

def add_embedding(student_id, embedding: np.ndarray):
    """เก็บเวกเตอร์ใบหน้า (float32) เป็น BLOB"""
    vec = np.asarray(embedding, dtype=np.float32)
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO face_embeddings (student_id, embedding, dim) VALUES (?, ?, ?)",
            (student_id, vec.tobytes(), vec.shape[0]),
        )


def get_all_embeddings():
    """
    ดึงเวกเตอร์ทั้งหมดในฐานข้อมูล คืนค่าเป็น:
      student_ids: list[int]  (คู่ขนานกับ matrix แต่ละแถว)
      matrix:      np.ndarray shape (N, dim)
    ใช้โหลดเข้าหน่วยความจำครั้งเดียวตอนเริ่มระบบ/รีเฟรช เพื่อจับคู่ใบหน้าแบบเร็ว
    """
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT student_id, embedding, dim FROM face_embeddings"
        ).fetchall()

    if not rows:
        return [], np.zeros((0, 512), dtype=np.float32)

    student_ids = []
    vectors = []
    for r in rows:
        vec = np.frombuffer(r["embedding"], dtype=np.float32)
        student_ids.append(r["student_id"])
        vectors.append(vec)
    matrix = np.vstack(vectors)
    return student_ids, matrix


def count_embeddings_for_student(student_id):
    with get_conn() as conn:
        row = conn.execute(
            "SELECT COUNT(*) as c FROM face_embeddings WHERE student_id = ?",
            (student_id,),
        ).fetchone()
        return row["c"]


# ---------------------------------------------------------------------------
# Events
# ---------------------------------------------------------------------------

def add_event(event_name, event_date=None, location=""):
    if event_date is None:
        event_date = datetime.date.today().isoformat()
    with get_conn() as conn:
        cur = conn.execute(
            "INSERT INTO events (event_name, event_date, location) VALUES (?, ?, ?)",
            (event_name, event_date, location),
        )
        return cur.lastrowid


def list_events():
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM events ORDER BY event_date DESC, id DESC"
        ).fetchall()
        return [dict(r) for r in rows]


def delete_event(event_id):
    with get_conn() as conn:
        conn.execute("DELETE FROM events WHERE id = ?", (event_id,))


# ---------------------------------------------------------------------------
# Attendance (รองรับสแกนเข้า + สแกนออก แยกกัน)
# ---------------------------------------------------------------------------

def mark_attendance(event_id, student_id, confidence, scan_type="in"):
    """
    บันทึกการสแกน (เข้า หรือ ออก) ของนักเรียนในกิจกรรมหนึ่งๆ
    scan_type: "in" = สแกนเข้า (checkin_time/confidence), "out" = สแกนออก (check_out_time/confidence_out)
    ถ้าสแกนประเภทนั้นถูกบันทึกไปแล้ว จะไม่บันทึกซ้ำ (กันสแกนซ้ำทับเวลาเดิม)
    คืนค่า True ถ้าบันทึกใหม่สำเร็จ, False ถ้าเคยสแกนประเภทนี้ไปแล้ว
    """
    time_col = "checkin_time" if scan_type == "in" else "check_out_time"
    conf_col = "confidence" if scan_type == "in" else "confidence_out"

    with get_conn() as conn:
        existing = conn.execute(
            "SELECT * FROM attendance WHERE event_id = ? AND student_id = ?",
            (event_id, student_id),
        ).fetchone()

        if existing is None:
            conn.execute(
                f"INSERT INTO attendance (event_id, student_id, {time_col}, {conf_col}) "
                f"VALUES (?, ?, datetime('now', 'localtime'), ?)",
                (event_id, student_id, confidence),
            )
            return True

        if existing[time_col]:
            return False  # สแกนประเภทนี้มาแล้ว ไม่บันทึกซ้ำ

        conn.execute(
            f"UPDATE attendance SET {time_col} = datetime('now', 'localtime'), {conf_col} = ? WHERE id = ?",
            (confidence, existing["id"]),
        )
        return True


def already_checked_in(event_id, student_id, scan_type="in"):
    time_col = "checkin_time" if scan_type == "in" else "check_out_time"
    with get_conn() as conn:
        row = conn.execute(
            f"SELECT {time_col} FROM attendance WHERE event_id = ? AND student_id = ?",
            (event_id, student_id),
        ).fetchone()
        return row is not None and row[time_col] is not None


def _attendance_status_text(checkin_time, check_out_time):
    if checkin_time and check_out_time:
        return "เข้าร่วมกิจกรรม"
    if checkin_time and not check_out_time:
        return "ไม่เข้าร่วมกิจกรรม (สแกนเข้าอย่างเดียว)"
    if check_out_time and not checkin_time:
        return "ไม่เข้าร่วมกิจกรรม (สแกนออกอย่างเดียว)"
    return "ไม่เข้าร่วมกิจกรรม"


def get_attendance_report(event_id):
    """
    คืนรายชื่อทุกคนที่มีการสแกนอย่างน้อย 1 ครั้ง (เข้าหรือออก) ในกิจกรรม พร้อมเวลาทั้งสองฝั่ง
    และสถานะสรุป — 'เข้าร่วมกิจกรรม' เฉพาะกรณีมีทั้งสแกนเข้าและสแกนออกเท่านั้น ตามเงื่อนไขที่กำหนด
    """
    with get_conn() as conn:
        rows = conn.execute(
            """
            SELECT a.checkin_time, a.confidence, a.check_out_time, a.confidence_out,
                   s.student_code, s.full_name, s.class_room, s.department
            FROM attendance a
            JOIN students s ON s.id = a.student_id
            WHERE a.event_id = ?
            ORDER BY COALESCE(a.checkin_time, a.check_out_time) ASC
            """,
            (event_id,),
        ).fetchall()
        result = []
        for r in rows:
            d = dict(r)
            d["attended"] = bool(d["checkin_time"] and d["check_out_time"])
            d["status_text"] = _attendance_status_text(d["checkin_time"], d["check_out_time"])
            result.append(d)
        return result


def get_absent_report(event_id):
    """รายชื่อนักเรียนทั้งหมดที่ 'ไม่มีการสแกนเลย' ทั้งเข้าและออก ในกิจกรรมนี้"""
    with get_conn() as conn:
        rows = conn.execute(
            """
            SELECT s.student_code, s.full_name, s.class_room, s.department
            FROM students s
            WHERE s.id NOT IN (
                SELECT student_id FROM attendance WHERE event_id = ?
            )
            ORDER BY s.class_room, s.full_name
            """,
            (event_id,),
        ).fetchall()
        return [dict(r) for r in rows]


def get_attendance_summary(event_id):
    """
    สรุปจำนวนตามสถานะสำหรับกิจกรรมหนึ่งๆ ใช้ทำกราฟและสรุปตัวเลข คืนค่า dict:
      total, attended (ครบเข้า-ออก), partial (สแกนอย่างเดียว), absent (ไม่สแกนเลย)
      by_room: {ห้อง: {"attended": n, "not_attended": n}}
      by_department: {สาขา: {"attended": n, "not_attended": n}}
    """
    total_students = list_students()
    report = get_attendance_report(event_id)
    report_by_code = {r["student_code"]: r for r in report}

    attended = sum(1 for r in report if r["attended"])
    partial = sum(1 for r in report if not r["attended"])
    absent = len(total_students) - len(report)

    by_room = {}
    by_department = {}
    for s in total_students:
        room = s["class_room"] or "ไม่ระบุห้อง"
        dept = s.get("department") or "ไม่ระบุสาขา"
        by_room.setdefault(room, {"attended": 0, "not_attended": 0})
        by_department.setdefault(dept, {"attended": 0, "not_attended": 0})

        r = report_by_code.get(s["student_code"])
        is_attended = bool(r and r["attended"])
        key = "attended" if is_attended else "not_attended"
        by_room[room][key] += 1
        by_department[dept][key] += 1

    return {
        "total": len(total_students),
        "attended": attended,
        "partial": partial,
        "absent": absent,
        "not_attended": partial + absent,
        "by_room": by_room,
        "by_department": by_department,
    }
