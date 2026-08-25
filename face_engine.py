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


def draw_face_box(frame, bbox, label, color=(0, 200, 0)):
    """
    วาดกรอบสี่เหลี่ยม + ป้ายชื่อ (รองรับภาษาไทย) บนเฟรม
    frame: numpy array BGR (จาก OpenCV) - แก้ไข in-place และคืนค่ากลับด้วย
    """
    x1, y1, x2, y2 = [int(v) for v in bbox]
    cv2.rectangle(frame, (x1, y1), (x2, y2), color, 2)

    # วาดข้อความไทยด้วย PIL แล้ว paste กลับเป็น numpy/BGR
    pil_img = Image.fromarray(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
    draw = ImageDraw.Draw(pil_img)

    try:
        text_bbox = draw.textbbox((0, 0), label, font=_THAI_FONT)
        text_w = text_bbox[2] - text_bbox[0]
        text_h = text_bbox[3] - text_bbox[1]
    except Exception:
        text_w, text_h = len(label) * 10, 20

    label_y1 = max(0, y2 - text_h - 8)
    draw.rectangle([x1, label_y1, x1 + text_w + 8, y2], fill=(color[2], color[1], color[0]))
    draw.text((x1 + 4, label_y1 + 2), label, font=_THAI_FONT, fill=(255, 255, 255))

    result = cv2.cvtColor(np.array(pil_img), cv2.COLOR_RGB2BGR)
    frame[:, :, :] = result
    return frame
