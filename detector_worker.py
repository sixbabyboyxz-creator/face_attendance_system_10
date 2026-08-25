# -*- coding: utf-8 -*-
"""
detector_worker.py
รัน face detection + matching + บันทึกเช็คชื่อ บน thread แยกต่างหาก

เหตุผล: การตรวจจับใบหน้าด้วย AI (InsightFace) ใช้เวลาต่อเฟรมนานกว่าการแค่แสดงภาพกล้องมาก
ถ้ารันตรวจจับในลูปเดียวกับที่วาดภาพขึ้นจอ (Tkinter main thread) ภาพจะกระตุกตามความเร็วของ AI
จึงแยกออกมาเป็น thread ของตัวเอง:
  - thread นี้: อ่านเฟรมล่าสุด -> ตรวจจับ (จำกัดความถี่ด้วย DETECTION_INTERVAL_SEC เพื่อลด CPU)
    -> จับคู่ -> บันทึกเช็คชื่อ -> เก็บ "ตำแหน่งกรอบ/ชื่อ" ล่าสุดไว้ (ไม่เก็บภาพทั้งเฟรม)
  - GUI thread (main.py): ดึงภาพกล้องสดมาแสดงทุกครั้ง แล้ววาดกรอบจากผลลัพธ์ล่าสุดของ thread นี้ทับ
    ทำให้วิดีโอลื่นเท่าความเร็วกล้องจริง ไม่ขึ้นกับความเร็ว AI
"""

import threading
import time
import queue

import database
import face_engine
import config


class AttendanceWorker:
    def __init__(self, camera, engine, matcher, event_id, scan_type="in", cooldown_sec=None):
        self.camera = camera
        self.engine = engine
        self.matcher = matcher
        self.event_id = event_id
        self.scan_type = scan_type  # "in" = สแกนเข้า, "out" = สแกนออก
        self.cooldown_sec = cooldown_sec or config.DUPLICATE_CHECKIN_COOLDOWN_SEC

        self.running = False
        self.thread = None

        self.result_lock = threading.Lock()
        # ผลลัพธ์ล่าสุดจาก AI: list ของ dict {bbox, label, color}
        # เก็บแค่ "ตำแหน่ง/ป้ายชื่อ" ไม่เก็บภาพทั้งเฟรม เพื่อให้ GUI thread นำไปวาดซ้อนบน
        # ภาพกล้องสดล่าสุดได้เองทุกครั้งที่รีเฟรชจอ (ภาพจะลื่นเท่าความเร็วกล้อง ไม่ใช่ความเร็ว AI)
        self.latest_faces = []

        # เหตุการณ์เช็คชื่อใหม่ๆ ส่งผ่าน queue ไปให้ GUI thread อัปเดตตาราง/สถานะ
        self.checkin_queue = queue.Queue()
        self.recent_checkins = {}

    def start(self):
        self.running = True
        self.thread = threading.Thread(target=self._loop, daemon=True)
        self.thread.start()
        return self

    def stop(self):
        self.running = False
        if self.thread is not None:
            self.thread.join(timeout=1.5)

    def get_latest_faces(self):
        with self.result_lock:
            return list(self.latest_faces)

    def _loop(self):
        last_detect_time = 0.0
        scan_label = "เข้า" if self.scan_type == "in" else "ออก"
        while self.running:
            now = time.time()
            # จำกัดความถี่การตรวจจับ (ไม่ต้องตรวจทุกเฟรม) เพื่อลดการใช้ CPU
            # เช็คก่อนดึงเฟรม เพื่อไม่ต้องเสียเวลาก๊อปปี้ภาพทิ้งเปล่าๆ ระหว่างที่ยังไม่ครบรอบ
            if now - last_detect_time < config.DETECTION_INTERVAL_SEC:
                time.sleep(0.02)
                continue
            last_detect_time = now

            frame = self.camera.read()
            if frame is None:
                continue

            try:
                faces = self.engine.detect_faces(frame)
            except Exception:
                faces = []

            now = time.time()
            results = []
            for face in faces:
                student_id, score = self.matcher.match(face.embedding)

                if student_id is None:
                    results.append({"bbox": face.bbox, "label": "ไม่รู้จัก", "color": (0, 0, 220)})
                    continue

                student = database.get_student_by_id(student_id)

                last_time = self.recent_checkins.get(student_id, 0)
                if now - last_time > self.cooldown_sec:
                    self.recent_checkins[student_id] = now
                    is_new = database.mark_attendance(self.event_id, student_id, score, scan_type=self.scan_type)
                    if is_new:
                        self.checkin_queue.put((student, score, self.scan_type))
                        label = f"{student['full_name']} ({scan_label} {score * 100:.0f}%)"
                        results.append({"bbox": face.bbox, "label": label, "color": (0, 200, 0)})
                        continue

                # สแกนซ้ำ (คูลดาวน์ยังไม่ครบ หรือสแกนประเภทนี้ไปแล้ว) แสดงกรอบสีเหลืองแทน
                label = f"{student['full_name']} (สแกนแล้ว)"
                results.append({"bbox": face.bbox, "label": label, "color": (0, 165, 255)})

            with self.result_lock:
                self.latest_faces = results

            # หน่วงเล็กน้อย กันไม่ให้ thread นี้ใช้ CPU เต็ม 100% ตลอดเวลาบนเครื่องที่เร็วมาก
            time.sleep(0.01)
