# -*- coding: utf-8 -*-
"""
config.py
การตั้งค่าหลักของระบบเช็คชื่อด้วยใบหน้า (Face Attendance System)
แก้ไขค่าต่างๆ ในไฟล์นี้เพื่อปรับพฤติกรรมของระบบ
"""

import os

# ----- Path หลัก -----
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
DB_PATH = os.path.join(DATA_DIR, "attendance.db")
STUDENT_PHOTOS_DIR = os.path.join(DATA_DIR, "student_photos")
EXPORT_DIR = os.path.join(DATA_DIR, "exports")

# ----- ตั้งค่าโมเดล Face Recognition (InsightFace) -----
# buffalo_l = แม่นยำสูง (ใช้ GPU จะเร็วมาก, CPU ก็ใช้ได้กับ 2000 คน)
# buffalo_s = เบากว่า เหมาะกับเครื่องที่ไม่มี GPU / ต้องการความเร็วสูงสุด
FACE_MODEL_NAME = "buffalo_l"
DET_SIZE = (640, 640)          # ขนาดภาพที่ใช้ตรวจจับใบหน้า (ยิ่งใหญ่ยิ่งแม่น แต่ช้าลง)
CTX_ID = -1                    # -1 = CPU, 0 = GPU ตัวแรก (ถ้ามี CUDA/onnxruntime-gpu)

# ----- จำกัดการใช้ CPU ของ onnxruntime -----
# ค่าเริ่มต้นของ onnxruntime จะสร้าง thread เท่าจำนวน physical core ทั้งหมด และให้ทุก thread
# "spin-wait" (หมุนวนรอคำสั่งตลอดเวลา) เพื่อตอบสนองเร็วสุด ผลคือ CPU ขึ้น 90-100% แม้เรียกตรวจจับ
# ไม่บ่อยก็ตาม ตั้งค่านี้ให้จำกัดจำนวน thread และปิด spin-wait ช่วยลด CPU ได้มาก
# (แลกกับความเร็วต่อครั้งที่ช้าลงเล็กน้อย ซึ่งไม่กระทบงานเช็คชื่อที่ไม่ต้องเรียลไทม์จัด)
ONNX_INTRA_OP_THREADS = 2      # จำนวน thread ประมวลผลภายในโมเดล (ลองปรับ 2-4 ตามสเปกเครื่อง)
ONNX_INTER_OP_THREADS = 1
ONNX_DISABLE_SPINNING = True   # True = ปิด spin-wait (แนะนำสำหรับงานที่ไม่ต้องเรียลไทม์สุดๆ)

# ----- เกณฑ์การจดจำใบหน้า -----
# ค่า cosine similarity ที่ถือว่า "ใช่คนเดียวกัน" ยิ่งสูงยิ่งเข้มงวด (0.0 - 1.0)
RECOGNITION_THRESHOLD = 0.45
# จำนวนภาพที่แนะนำให้ถ่ายตอนลงทะเบียนต่อคน (มุมต่างกัน)
ENROLL_SHOTS_PER_STUDENT = 4

# ----- กล้อง -----
CAMERA_INDEX = 0                # เปลี่ยนเป็น 1,2 ถ้ามีหลายกล้อง
CAMERA_WIDTH = 640               # ลดจาก 960 -> 640 เพื่อลดภาระประมวลผลต่อเฟรม (ปรับขึ้นได้ถ้า CPU ไหว)
CAMERA_HEIGHT = 480

# ----- ความถี่การตรวจจับใบหน้า -----
# ตรวจจับใบหน้าถี่แค่ไหนต่อวินาที (วินาทีต่อครั้ง) ไม่จำเป็นต้องตรวจทุกเฟรม
# เพราะคนเดินผ่านกล้องใช้เวลาเป็นวินาทีอยู่แล้ว ค่านี้ช่วยลดการใช้ CPU ลงมาก
# 0.3 = ตรวจจับประมาณ 3 ครั้ง/วินาที (แนะนำ) / ปรับเป็น 0.15-0.2 ถ้าอยากตอบสนองไวขึ้นและ CPU ยังไหว
DETECTION_INTERVAL_SEC = 0.3
# วินาทีที่ต้องรอ ก่อนจะให้เช็คชื่อคนเดิมซ้ำในกิจกรรมเดียวกัน (กันบันทึกซ้ำรัวๆ)
DUPLICATE_CHECKIN_COOLDOWN_SEC = 5

# สร้างโฟลเดอร์ที่จำเป็นถ้ายังไม่มี
for _d in (DATA_DIR, STUDENT_PHOTOS_DIR, EXPORT_DIR):
    os.makedirs(_d, exist_ok=True)
