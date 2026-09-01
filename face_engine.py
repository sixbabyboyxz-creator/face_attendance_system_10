# -*- coding: utf-8 -*-
"""
face_engine.py
เอนจินตรวจจับใบหน้า + สร้างเวกเตอร์ใบหน้า (embedding) ด้วย InsightFace
และตัวจับคู่ใบหน้า (matcher) แบบ cosine similarity บน numpy

เลือกใช้ InsightFace เพราะ:
  - ติดตั้งบน Windows ง่ายกว่า dlib/face_recognition มาก (ไม่ต้องคอมไพล์)
  - ความแม่นยำสูง เหมาะกับฐานข้อมูลระดับ ~2000 คน
"""

import os
import numpy as np
import cv2
from PIL import Image, ImageDraw, ImageFont

import config

# ฟอนต์ที่รองรับภาษาไทยสำหรับวาดชื่อบนเฟรมกล้อง (OpenCV วาดข้อความไทยไม่ได้โดยตรง)
_THAI_FONT_CANDIDATES = [
    r"C:\Windows\Fonts\tahoma.ttf",
    r"C:\Windows\Fonts\leelawad.ttf",
    r"C:\Windows\Fonts\angsana.ttc",
    "/usr/share/fonts/truetype/thai/Garuda.ttf",  # เผื่อรันบน Linux ตอนทดสอบ
]


def _load_thai_font(size=20):
    for path in _THAI_FONT_CANDIDATES:
        if os.path.exists(path):
            try:
                return ImageFont.truetype(path, size)
            except Exception:
                continue
    return ImageFont.load_default()


_THAI_FONT = _load_thai_font(20)


class FaceEngine:
    def __init__(self):
        # import ในนี้เพื่อให้ error message ชัดเจนถ้ายังไม่ได้ติดตั้ง insightface/onnxruntime
        from insightface.app import FaceAnalysis
        import onnxruntime as ort

        # ตั้งค่า onnxruntime ให้จำกัดจำนวน thread และปิด spin-wait
        # (ค่าเริ่มต้นของ onnxruntime จะใช้ทุก physical core และ "หมุนวนรอ" ตลอดเวลา
        #  ทำให้ CPU ขึ้น 90-100% แม้เรียกตรวจจับไม่บ่อยก็ตาม)
        sess_options = ort.SessionOptions()
        sess_options.intra_op_num_threads = config.ONNX_INTRA_OP_THREADS
        sess_options.inter_op_num_threads = config.ONNX_INTER_OP_THREADS
        sess_options.execution_mode = ort.ExecutionMode.ORT_SEQUENTIAL
        if config.ONNX_DISABLE_SPINNING:
            sess_options.add_session_config_entry("session.intra_op.allow_spinning", "0")
            sess_options.add_session_config_entry("session.inter_op.allow_spinning", "0")

        providers = ["CPUExecutionProvider"] if config.CTX_ID < 0 else [
            "CUDAExecutionProvider", "CPUExecutionProvider"
        ]

        self.app = FaceAnalysis(
            name=config.FACE_MODEL_NAME,
            # จำกัดให้โหลดแค่โมเดลที่ใช้จริง: detection (หาตำแหน่งหน้า) + recognition (สร้าง embedding)
            # ตัด landmark_3d_68 / landmark_2d_106 / genderage ออก เพราะไม่ได้ใช้ในระบบเช็คชื่อนี้
            # แต่ค่าเริ่มต้นจะรันทั้ง 5 โมเดลทุกครั้ง ทำให้เปลืองการประมวลผล/CPU โดยไม่จำเป็น
            allowed_modules=["detection", "recognition"],
            providers=providers,
            sess_options=sess_options,
        )
        self.app.prepare(ctx_id=config.CTX_ID, det_size=config.DET_SIZE)

    def detect_faces(self, frame_bgr):
        """
        ตรวจจับใบหน้าทั้งหมดในเฟรม (numpy array, BGR - จาก OpenCV)
        คืนค่า list ของ face object (มี .bbox, .embedding, .det_score)
        """
        faces = self.app.get(frame_bgr)
        # กรองใบหน้าที่ความมั่นใจต่ำเกินไปออก
        faces = [f for f in faces if f.det_score >= config.MIN_DET_SCORE]
        return faces

    @staticmethod
    def normalize(vec: np.ndarray) -> np.ndarray:
        norm = np.linalg.norm(vec)
        if norm < 1e-8:
            return vec
        return vec / norm


class FaceMatcher:
    """
    เก็บเวกเตอร์ใบหน้าของนักเรียนทั้งหมดในหน่วยความจำ (โหลดจาก DB)
    ใช้ cosine similarity แบบ brute-force ซึ่งเร็วพอสำหรับ ~2000 คน x หลายภาพ/คน
    """

    def __init__(self, student_ids, matrix: np.ndarray):
        self.student_ids = student_ids
        if matrix.shape[0] > 0:
            norms = np.linalg.norm(matrix, axis=1, keepdims=True)
            norms[norms < 1e-8] = 1e-8
            self.matrix_norm = matrix / norms
        else:
            self.matrix_norm = matrix

    @classmethod
    def load_from_db(cls):
        import database

        student_ids, matrix = database.get_all_embeddings()
        return cls(student_ids, matrix)

    def is_empty(self):
        return self.matrix_norm.shape[0] == 0

    def match(self, query_embedding: np.ndarray):
        """
        เทียบเวกเตอร์ใบหน้า 1 ใบหน้า กับฐานข้อมูลทั้งหมด
        คืนค่า (student_id, similarity) ของคนที่คล้ายที่สุด
        ถ้าไม่มีใครในฐานข้อมูลผ่านเกณฑ์ RECOGNITION_THRESHOLD คืนค่า (None, best_score)
        """
        if self.is_empty():
            return None, 0.0

        q = query_embedding / (np.linalg.norm(query_embedding) + 1e-8)
        sims = self.matrix_norm @ q  # cosine similarity กับทุกแถว
        best_idx = int(np.argmax(sims))
        best_score = float(sims[best_idx])

        if best_score >= config.RECOGNITION_THRESHOLD:
            return self.student_ids[best_idx], best_score
        return None, best_score


def assess_face_quality(frame_bgr, bbox):
    """
    ประเมินคุณภาพใบหน้าจากภาพและตำแหน่ง
    คืนค่า dict: {"pass": bool, "reasons": list[str], "blur_score": float, "brightness": float, "face_size": int}
    """
    x1, y1, x2, y2 = [int(v) for v in bbox]
    h, w = y2 - y1, x2 - x1
    face_size = max(w, h)
    
    reasons = []
    
    if face_size < config.MIN_FACE_SIZE:
        reasons.append("ใบหน้าเล็กเกินไป")
        
    # Crop face region
    x1_c, y1_c = max(0, x1), max(0, y1)
    face_img = frame_bgr[y1_c:y2, x1_c:x2]
    
    blur_score = 0.0
    brightness = 0.0
    
    if face_img.size > 0:
        gray = cv2.cvtColor(face_img, cv2.COLOR_BGR2GRAY)
        blur_score = cv2.Laplacian(gray, cv2.CV_64F).var()
        brightness = np.mean(gray)
        
        if blur_score < config.MIN_BLUR_THRESHOLD:
            reasons.append("ภาพเบลอ")
            
        if brightness < config.MIN_BRIGHTNESS:
            reasons.append("มืดเกินไป")
        elif brightness > config.MAX_BRIGHTNESS:
            reasons.append("สว่างเกินไป")
            
    is_pass = len(reasons) == 0
    return {
        "pass": is_pass,
        "reasons": reasons,
        "blur_score": blur_score,
        "brightness": brightness,
        "face_size": face_size
    }


def draw_face_box(frame, bbox, label, color=(0, 200, 0), status="ok"):
    """
    วาดกรอบใบหน้าแบบ Modern (มุมโค้ง) + ป้ายชื่อภาษาไทย บนเฟรม
    status: 'ok' = สำเร็จ, 'duplicate' = สแกนแล้ว, 'unknown' = ไม่รู้จัก, 'low_quality' = คุณภาพต่ำ
    """
    x1, y1, x2, y2 = [int(v) for v in bbox]
    h_frame, w_frame = frame.shape[:2]
    
    # --- กรอบมุมโค้ง (Corner brackets) ---
    corner_len = max(15, min(30, (x2 - x1) // 5))
    thickness = 3
    
    # มุมบนซ้าย
    cv2.line(frame, (x1, y1), (x1 + corner_len, y1), color, thickness)
    cv2.line(frame, (x1, y1), (x1, y1 + corner_len), color, thickness)
    # มุมบนขวา
    cv2.line(frame, (x2, y1), (x2 - corner_len, y1), color, thickness)
    cv2.line(frame, (x2, y1), (x2, y1 + corner_len), color, thickness)
    # มุมล่างซ้าย
    cv2.line(frame, (x1, y2), (x1 + corner_len, y2), color, thickness)
    cv2.line(frame, (x1, y2), (x1, y2 - corner_len), color, thickness)
    # มุมล่างขวา
    cv2.line(frame, (x2, y2), (x2 - corner_len, y2), color, thickness)
    cv2.line(frame, (x2, y2), (x2, y2 - corner_len), color, thickness)
    
    # --- Status icon ---
    icon = {"ok": "✓", "duplicate": "↻", "unknown": "?", "low_quality": "⚠"}.get(status, "")
    display_label = f"{icon} {label}" if icon else label
    
    # --- ป้ายชื่อภาษาไทย (แปลงเฉพาะ region ไม่ใช่ทั้งเฟรม) ---
    try:
        text_bbox_result = _get_text_size(display_label)
        text_w, text_h = text_bbox_result
    except Exception:
        text_w, text_h = len(display_label) * 12, 24
    
    padding = 6
    label_h = text_h + padding * 2
    label_w = text_w + padding * 2
    label_y1 = max(0, y1 - label_h - 4)
    label_x1 = max(0, x1)
    label_x2 = min(w_frame, label_x1 + label_w)
    label_y2 = label_y1 + label_h
    
    # สร้าง overlay เฉพาะ region ป้ายชื่อ
    overlay = frame.copy()
    cv2.rectangle(overlay, (label_x1, label_y1), (label_x2, label_y2), color, -1)
    cv2.addWeighted(overlay[label_y1:label_y2, label_x1:label_x2], 0.85,
                    frame[label_y1:label_y2, label_x1:label_x2], 0.15, 0,
                    frame[label_y1:label_y2, label_x1:label_x2])
    
    # วาดข้อความไทยด้วย PIL เฉพาะ region
    region = frame[label_y1:label_y2, label_x1:label_x2]
    if region.size > 0:
        pil_region = Image.fromarray(cv2.cvtColor(region, cv2.COLOR_BGR2RGB))
        draw = ImageDraw.Draw(pil_region)
        draw.text((padding, padding - 2), display_label, font=_THAI_FONT, fill=(255, 255, 255))
        frame[label_y1:label_y2, label_x1:label_x2] = cv2.cvtColor(np.array(pil_region), cv2.COLOR_RGB2BGR)
    
    return frame


def _get_text_size(text):
    """คำนวณขนาดข้อความโดยไม่ต้องสร้างภาพเต็ม"""
    dummy = Image.new('RGB', (1, 1))
    draw = ImageDraw.Draw(dummy)
    text_bbox = draw.textbbox((0, 0), text, font=_THAI_FONT)
    return text_bbox[2] - text_bbox[0], text_bbox[3] - text_bbox[1]
