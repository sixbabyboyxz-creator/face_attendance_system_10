# -*- coding: utf-8 -*-
"""
camera_utils.py
เปิดกล้องด้วย OpenCV บน thread แยก เพื่อไม่ให้ GUI ค้าง
"""

import threading
import time
import cv2

import config


def list_available_cameras(max_index=5):
    """
    ตรวจหากล้องที่เปิดใช้งานได้จริงในเครื่อง (ลอง index 0 ถึง max_index)
    คืนค่า list ของ index ที่เปิดได้ เช่น [0, 1]
    หมายเหตุ: OpenCV ไม่มีวิธีดึง "ชื่อกล้อง" ได้ตรงๆ บนทุกระบบ จึงแสดงผลเป็นเลข index
    """
    available = []
    for i in range(max_index + 1):
        cap = cv2.VideoCapture(i, cv2.CAP_DSHOW)
        if not cap.isOpened():
            cap = cv2.VideoCapture(i)
        if cap.isOpened():
            ok, _ = cap.read()
            if ok:
                available.append(i)
        cap.release()
    return available


class CameraStream:
    def __init__(self, camera_index=None, width=None, height=None):
        self.camera_index = camera_index if camera_index is not None else config.CAMERA_INDEX
        self.width = width or config.CAMERA_WIDTH
        self.height = height or config.CAMERA_HEIGHT

        self.cap = None
        self.frame = None
        self.running = False
        self.lock = threading.Lock()
        self.thread = None

    def start(self):
        # CAP_DSHOW ช่วยให้เปิดกล้องบน Windows เร็วขึ้นและเสถียรกว่า
        self.cap = cv2.VideoCapture(self.camera_index, cv2.CAP_DSHOW)
        if not self.cap.isOpened():
            self.cap = cv2.VideoCapture(self.camera_index)
        self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, self.width)
        self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self.height)

        if not self.cap.isOpened():
            raise RuntimeError(
                f"เปิดกล้องไม่สำเร็จ (index={self.camera_index}) "
                "ตรวจสอบว่ากล้องเสียบอยู่และไม่ถูกโปรแกรมอื่นใช้งาน"
            )

        self.running = True
        self.thread = threading.Thread(target=self._update_loop, daemon=True)
        self.thread.start()
        return self

    def _update_loop(self):
        while self.running:
            ok, frame = self.cap.read()
            if ok:
                with self.lock:
                    self.frame = frame
                # หน่วงเล็กน้อยกันบางไดรเวอร์กล้อง/OpenCV คืนเฟรมเร็วเกินจำเป็นจนวิ่งเต็ม CPU core
                time.sleep(0.005)
            else:
                time.sleep(0.05)

    def read(self):
        with self.lock:
            return None if self.frame is None else self.frame.copy()

    def stop(self):
        self.running = False
        if self.thread is not None:
            self.thread.join(timeout=1.0)
        if self.cap is not None:
            self.cap.release()
