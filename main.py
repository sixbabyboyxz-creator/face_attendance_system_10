# -*- coding: utf-8 -*-
"""
main.py
แอปพลิเคชันหลัก - ระบบเช็คชื่อเข้าร่วมกิจกรรมด้วยใบหน้า (Face Attendance System)
รันด้วยคำสั่ง: python main.py

โครงสร้างหน้าจอ (Tab):
  1. จัดการนักเรียน   - เพิ่ม/ลบนักเรียน + ลงทะเบียนใบหน้า (ถ่ายภาพจากกล้อง)
  2. จัดการกิจกรรม    - สร้าง/ลบกิจกรรม
  3. เช็คชื่อ         - เปิดกล้อง สแกนใบหน้าแบบเรียลไทม์ บันทึกลงฐานข้อมูล
  4. รายงาน          - ดูรายชื่อเข้าร่วม/ขาด และส่งออก Excel
"""

import os
import time
import threading
import shutil
import datetime
import tkinter as tk
from tkinter import ttk, messagebox, simpledialog, filedialog

import cv2
import numpy as np
from PIL import Image, ImageTk

import config
import database
import face_engine
import camera_utils
import export_utils
import detector_worker
import import_utils


# ============================================================================
# หน้าต่างโหลดโมเดล (โมเดล InsightFace โหลดช้าตอนแรก ~5-15 วินาที)
# ============================================================================

class ModelLoader:
    """โหลด FaceEngine ใน background thread พร้อม callback เมื่อเสร็จ"""

    def __init__(self, on_done, on_error):
        self.on_done = on_done
        self.on_error = on_error
        self.engine = None

    def start(self):
        threading.Thread(target=self._load, daemon=True).start()

    def _load(self):
        try:
            self.engine = face_engine.FaceEngine()
            self.on_done(self.engine)
        except Exception as e:
            self.on_error(e)


# ============================================================================
# Tab 1: จัดการนักเรียน + ลงทะเบียนใบหน้า
# ============================================================================

class StudentTab(ttk.Frame):
    def __init__(self, parent, app):
        super().__init__(parent)
        self.app = app
        self.camera = None
        self.preview_job = None
        self.captured_count = 0
        self.pending_embeddings = []

        self._build_ui()
        self._refresh_student_list()

    def _build_ui(self):
        # --- ซ้าย: ฟอร์ม + กล้อง ---
        left = ttk.Frame(self)
        left.pack(side="left", fill="y", padx=10, pady=10)

        form = ttk.LabelFrame(left, text=" ข้อมูลนักเรียน ", padding=10)
        form.pack(fill="x", pady=(0, 10))

        ttk.Label(form, text="รหัสนักเรียน:", style="FieldLabel.TLabel").grid(row=0, column=0, sticky="w", padx=5, pady=4)
        self.entry_code = ttk.Entry(form, width=25)
        self.entry_code.grid(row=0, column=1, padx=5, pady=4)

        ttk.Label(form, text="ชื่อ-สกุล:", style="FieldLabel.TLabel").grid(row=1, column=0, sticky="w", padx=5, pady=4)
        self.entry_name = ttk.Entry(form, width=25)
        self.entry_name.grid(row=1, column=1, padx=5, pady=4)

        ttk.Label(form, text="ห้อง/ระดับชั้น:", style="FieldLabel.TLabel").grid(row=2, column=0, sticky="w", padx=5, pady=4)
        self.entry_class = ttk.Entry(form, width=25)
        self.entry_class.grid(row=2, column=1, padx=5, pady=4)

        ttk.Label(form, text="สาขา:", style="FieldLabel.TLabel").grid(row=3, column=0, sticky="w", padx=5, pady=4)
        self.entry_department = ttk.Entry(form, width=25)
        self.entry_department.grid(row=3, column=1, padx=5, pady=4)

        ttk.Button(
            form, text="1) บันทึกข้อมูลนักเรียน", style="Accent.TButton", command=self._save_student
        ).grid(row=4, column=0, columnspan=2, sticky="ew", padx=5, pady=(8, 4))

        cam_frame = ttk.LabelFrame(left, text=" 2) ลงทะเบียนใบหน้า (เปิดกล้อง) ", padding=10)
        cam_frame.pack(fill="x")

        # แถวควบคุมกล้องทั้งหมดไว้ด้านบนสุด (เหนือภาพพรีวิว) กันไม่ให้ปุ่มโดนภาพกล้องบดบัง
        # เมื่อเปิดกล้องแล้วภาพพรีวิวขยายใหญ่ขึ้น
        cam_select_row = ttk.Frame(cam_frame)
        cam_select_row.pack(fill="x", padx=5, pady=(5, 0))
        ttk.Label(cam_select_row, text="กล้อง:", style="FieldLabel.TLabel").pack(side="left")
        self.camera_combo = ttk.Combobox(cam_select_row, state="readonly", width=10)
        self.camera_combo.pack(side="left", padx=5)
        ttk.Button(cam_select_row, text="รีเฟรช", command=self._refresh_camera_list).pack(side="left", padx=(0, 15))
        self._refresh_camera_list()

        self.btn_start_cam = ttk.Button(cam_select_row, text="เปิดกล้อง", command=self._toggle_camera)
        self.btn_start_cam.pack(side="left", padx=(0, 5))
        self.btn_capture = ttk.Button(
            cam_select_row, text="ถ่ายภาพ + เก็บใบหน้า", style="Accent.TButton",
            command=self._capture_face, state="disabled"
        )
        self.btn_capture.pack(side="left")

        self.video_label = ttk.Label(cam_frame, text="กล้องยังไม่เปิด", anchor="center")
        self.video_label.pack(padx=5, pady=(10, 5))

        self.lbl_capture_status = ttk.Label(
            cam_frame,
            text=f"ถ่ายแล้ว 0 / {config.ENROLL_SHOTS_PER_STUDENT} ภาพ (แนะนำหันหน้าหลายมุม)",
        )
        self.lbl_capture_status.pack(pady=(0, 5))

        # --- ขวา: รายชื่อนักเรียน ---
        right = ttk.Frame(self)
        right.pack(side="left", fill="both", expand=True, padx=10, pady=10)

        import_row = ttk.Frame(right)
        import_row.pack(fill="x", pady=(0, 6))
        ttk.Button(import_row, text="นำเข้ารายชื่อจากไฟล์ (Excel/CSV)", command=self._import_from_file).pack(
            side="left"
        )
        ttk.Button(import_row, text="ดาวน์โหลดเทมเพลต", command=self._download_template).pack(
            side="left", padx=6
        )

        filter_row = ttk.Frame(right)
        filter_row.pack(fill="x", pady=(0, 4))
        ttk.Label(filter_row, text="กลุ่มเรียน/ห้อง:").pack(side="left")
        self.room_filter_combo = ttk.Combobox(filter_row, state="readonly", width=16)
        self.room_filter_combo.pack(side="left", padx=5)
        self.room_filter_combo.bind("<<ComboboxSelected>>", lambda e: self._refresh_student_list())

        ttk.Label(filter_row, text="สาขา:").pack(side="left", padx=(10, 0))
        self.department_filter_combo = ttk.Combobox(filter_row, state="readonly", width=18)
        self.department_filter_combo.pack(side="left", padx=5)
        self.department_filter_combo.bind("<<ComboboxSelected>>", lambda e: self._refresh_student_list())

        ttk.Label(filter_row, text="ค้นหา:").pack(side="left", padx=(10, 0))
        self.entry_search = ttk.Entry(filter_row)
        self.entry_search.pack(side="left", fill="x", expand=True, padx=5)
        self.entry_search.bind("<KeyRelease>", lambda e: self._refresh_student_list())

        # แผงแสดงข้อมูลกลุ่มเรียน (รหัสกลุ่มเรียน/ชื่อกลุ่มเรียน/ครูที่ปรึกษา) ของห้องที่เลือกกรองอยู่
        self.lbl_group_info = ttk.Label(right, text="", foreground="#2E5395")
        self.lbl_group_info.pack(anchor="w", pady=(0, 4))

        ttk.Label(
            right, text="ดับเบิลคลิกที่แถวเพื่อเลือกนักเรียนคนนั้นสำหรับถ่ายภาพลงทะเบียนใบหน้า",
            foreground="#555555",
        ).pack(anchor="w", pady=(0, 4))

        columns = ("code", "name", "class", "department", "type", "status", "faces")
        self.tree = ttk.Treeview(right, columns=columns, show="headings", height=18)
        for col, text, w in [
            ("code", "รหัส", 95),
            ("name", "ชื่อ-สกุล", 190),
            ("class", "ห้อง", 80),
            ("department", "สาขา", 130),
            ("type", "ประเภทผู้เรียน", 90),
            ("status", "สถานะ", 90),
            ("faces", "จำนวนภาพใบหน้า", 110),
        ]:
            self.tree.heading(col, text=text)
            self.tree.column(col, width=w)
        self.tree.pack(fill="both", expand=True, pady=5)
        self.tree.bind("<Double-1>", self._select_student_for_enrollment)

        ttk.Button(right, text="🗑  ลบนักเรียนที่เลือก", style="Danger.TButton", command=self._delete_selected).pack(
            anchor="e", pady=4
        )

        self._refresh_room_filter()
        self._refresh_department_filter()

    # -------------------------------------------------------------- ข้อมูล
    def _save_student(self):
        code = self.entry_code.get().strip()
        name = self.entry_name.get().strip()
        klass = self.entry_class.get().strip()
        dept = self.entry_department.get().strip()
        if not code or not name:
            messagebox.showwarning("ข้อมูลไม่ครบ", "กรุณากรอกรหัสนักเรียนและชื่อ-สกุล")
            return
        if database.get_student_by_code(code):
            messagebox.showwarning(
                "ซ้ำ",
                f"มีรหัสนักเรียน {code} อยู่แล้วในระบบ\n"
                "ถ้าต้องการถ่ายภาพลงทะเบียนใบหน้าให้คนนี้ ให้ดับเบิลคลิกที่แถวของเขาในตารางด้านขวาแทน",
            )
            return
        self.current_student_id = database.add_student(code, name, klass, department=dept)
        self.captured_count = 0
        self.pending_embeddings = []
        self.lbl_capture_status.config(
            text=f"ถ่ายแล้ว 0 / {config.ENROLL_SHOTS_PER_STUDENT} ภาพ (แนะนำหันหน้าหลายมุม)"
        )
        self._refresh_room_filter()
        self._refresh_department_filter()
        messagebox.showinfo(
            "สำเร็จ", "บันทึกข้อมูลนักเรียนแล้ว\nขั้นต่อไป: เปิดกล้องแล้วกด 'ถ่ายภาพ + เก็บใบหน้า'"
        )

    def _refresh_student_list(self):
        for row in self.tree.get_children():
            self.tree.delete(row)

        selected_room = self.room_filter_combo.get() if hasattr(self, "room_filter_combo") else None
        selected_dept = self.department_filter_combo.get() if hasattr(self, "department_filter_combo") else None
        students = database.list_students(
            self.entry_search.get().strip(), class_room=selected_room, department=selected_dept
        )

        for s in students:
            n_faces = database.count_embeddings_for_student(s["id"])
            self.tree.insert(
                "", "end", iid=str(s["id"]),
                values=(
                    s["student_code"], s["full_name"], s["class_room"], s.get("department", ""),
                    s.get("student_type", ""), s.get("status", ""), n_faces,
                ),
            )

        self._update_group_info_panel(selected_room)

    def _refresh_room_filter(self):
        current = self.room_filter_combo.get()
        rooms = database.list_class_rooms()
        values = ["ทั้งหมด"] + rooms
        self.room_filter_combo["values"] = values
        if current in values:
            self.room_filter_combo.set(current)
        else:
            self.room_filter_combo.current(0)
        self._refresh_student_list()

    def _refresh_department_filter(self):
        current = self.department_filter_combo.get()
        depts = database.list_departments()
        values = ["ทั้งหมด"] + depts
        self.department_filter_combo["values"] = values
        if current in values:
            self.department_filter_combo.set(current)
        else:
            self.department_filter_combo.current(0)
        self._refresh_student_list()

    def _update_group_info_panel(self, selected_room):
        if not selected_room or selected_room == "ทั้งหมด":
            self.lbl_group_info.config(text="")
            return
        group = database.get_class_group_by_level(selected_room)
        if group:
            parts = []
            if group.get("group_code"):
                parts.append(f"รหัสกลุ่มเรียน: {group['group_code']}")
            if group.get("group_name"):
                parts.append(f"ชื่อกลุ่มเรียน: {group['group_name']}")
            if group.get("advisor_teacher"):
                parts.append(f"ครูที่ปรึกษา: {group['advisor_teacher']}")
            self.lbl_group_info.config(text="  |  ".join(parts) if parts else "ไม่มีข้อมูลกลุ่มเรียนเพิ่มเติม")
        else:
            self.lbl_group_info.config(text="ไม่มีข้อมูลกลุ่มเรียน (นักเรียนกลุ่มนี้ถูกเพิ่มด้วยมือ/เทมเพลตทั่วไป)")

    def _delete_selected(self):
        sel = self.tree.selection()
        if not sel:
            return
        if messagebox.askyesno("ยืนยัน", "ลบนักเรียนที่เลือก (รวมข้อมูลใบหน้า) ใช่หรือไม่?"):
            for iid in sel:
                database.delete_student(int(iid))
            self._refresh_room_filter()
            self._refresh_department_filter()
            self.app.refresh_matcher()

    # -------------------------------------------------------------- นำเข้าไฟล์
    def _import_from_file(self):
        path = filedialog.askopenfilename(
            title="เลือกไฟล์รายชื่อนักเรียน (Excel หรือ CSV)",
            filetypes=[("Excel/CSV files", "*.xlsx *.xlsm *.csv"), ("All files", "*.*")],
        )
        if not path:
            return
        try:
            result = import_utils.import_students_from_file(path)
        except Exception as e:
            messagebox.showerror("นำเข้าล้มเหลว", str(e))
            return

        self._refresh_room_filter()
        self._refresh_department_filter()

        msg = f"นำเข้าสำเร็จ {result['success']} คน"
        if result["skipped"]:
            msg += f"\nข้ามไป {len(result['skipped'])} คน (มีรหัสนี้อยู่ในระบบแล้ว)"
        if result.get("skipped_inactive"):
            msg += f"\nข้ามไป {len(result['skipped_inactive'])} คน (สถานะพ้นสภาพ/ลาออก/ไม่ได้เรียนแล้ว)"
        if result["errors"]:
            shown = "\n".join(result["errors"][:10])
            more = "" if len(result["errors"]) <= 10 else f"\n...และอีก {len(result['errors']) - 10} รายการ"
            msg += f"\n\nพบข้อผิดพลาด {len(result['errors'])} รายการ:\n{shown}{more}"
        messagebox.showinfo("ผลการนำเข้า", msg)

    def _download_template(self):
        path = filedialog.asksaveasfilename(
            title="บันทึกไฟล์เทมเพลตนำเข้ารายชื่อ",
            defaultextension=".xlsx",
            filetypes=[("Excel files", "*.xlsx")],
            initialfile="เทมเพลตนำเข้ารายชื่อนักเรียน.xlsx",
        )
        if not path:
            return
        try:
            import_utils.create_template(path)
        except Exception as e:
            messagebox.showerror("สร้างเทมเพลตล้มเหลว", str(e))
            return
        messagebox.showinfo(
            "สำเร็จ",
            f"บันทึกเทมเพลตแล้วที่:\n{path}\n\n"
            "กรอกรหัสนักเรียน/ชื่อ-สกุล/ห้อง ในไฟล์นี้ แล้วนำเข้ากลับผ่านปุ่ม "
            "'นำเข้ารายชื่อจากไฟล์' ได้เลย",
        )

    # -------------------------------------------------------------- เลือกเพื่อลงทะเบียนใบหน้า
    def _select_student_for_enrollment(self, event):
        sel = self.tree.selection()
        if not sel:
            return
        student_id = int(sel[0])
        student = database.get_student_by_id(student_id)
        if not student:
            return

        self.current_student_id = student_id
        self.captured_count = database.count_embeddings_for_student(student_id)

        self.entry_code.delete(0, "end")
        self.entry_code.insert(0, student["student_code"])
        self.entry_name.delete(0, "end")
        self.entry_name.insert(0, student["full_name"])
        self.entry_class.delete(0, "end")
        self.entry_class.insert(0, student["class_room"] or "")
        self.entry_department.delete(0, "end")
        self.entry_department.insert(0, student.get("department") or "")

        self.lbl_capture_status.config(
            text=f"เลือก: {student['full_name']} — ถ่ายแล้ว {self.captured_count} / "
            f"{config.ENROLL_SHOTS_PER_STUDENT} ภาพ"
        )

    # -------------------------------------------------------------- กล้อง
    def _refresh_camera_list(self):
        cams = camera_utils.list_available_cameras()
        if not cams:
            cams = [config.CAMERA_INDEX]  # เผื่อตรวจไม่เจอเลย ยังให้เลือก index เริ่มต้นได้
        self.camera_combo["values"] = [f"กล้อง {i}" for i in cams]

        saved = database.get_setting("camera_index", str(config.CAMERA_INDEX))
        try:
            saved_idx = int(saved)
        except (TypeError, ValueError):
            saved_idx = config.CAMERA_INDEX
        default_pos = cams.index(saved_idx) if saved_idx in cams else 0
        self.camera_combo.current(default_pos)

    def _selected_camera_index(self):
        label = self.camera_combo.get()
        try:
            idx = int(label.replace("กล้อง", "").strip())
        except ValueError:
            idx = config.CAMERA_INDEX
        database.set_setting("camera_index", idx)
        return idx

    def _toggle_camera(self):
        if self.camera is None:
            try:
                self.camera = camera_utils.CameraStream(camera_index=self._selected_camera_index()).start()
            except Exception as e:
                messagebox.showerror("เปิดกล้องไม่สำเร็จ", str(e))
                self.camera = None
                return
            self.btn_start_cam.config(text="ปิดกล้อง")
            self.btn_capture.config(state="normal")
            self._update_preview()
        else:
            self._stop_camera()

    def _stop_camera(self):
        if self.preview_job:
            self.after_cancel(self.preview_job)
            self.preview_job = None
        if self.camera:
            self.camera.stop()
            self.camera = None
        self.btn_start_cam.config(text="เปิดกล้อง")
        self.btn_capture.config(state="disabled")
        self.video_label.config(image="", text="กล้องยังไม่เปิด")

    def _update_preview(self):
        if self.camera is None:
            return
        frame = self.camera.read()
        if frame is not None:
            img = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            img = cv2.resize(img, (480, 360))
            imgtk = ImageTk.PhotoImage(image=Image.fromarray(img))
            self.video_label.imgtk = imgtk
            self.video_label.config(image=imgtk, text="")
        self.preview_job = self.after(30, self._update_preview)

    def _capture_face(self):
        if not hasattr(self, "current_student_id"):
            messagebox.showwarning("ยังไม่ได้บันทึกนักเรียน", "กรุณาบันทึกข้อมูลนักเรียนก่อน (ขั้นตอนที่ 1)")
            return
        if self.app.engine is None:
            messagebox.showwarning("โมเดลยังไม่พร้อม", "ระบบกำลังโหลดโมเดลจดจำใบหน้า กรุณารอสักครู่")
            return
        frame = self.camera.read()
        if frame is None:
            messagebox.showwarning("ไม่มีภาพ", "ยังไม่ได้รับภาพจากกล้อง")
            return

        faces = self.app.engine.detect_faces(frame)
        if len(faces) == 0:
            messagebox.showwarning("ไม่พบใบหน้า", "ไม่พบใบหน้าในเฟรม กรุณาหันหน้าเข้ากล้องให้ชัดเจน")
            return
        if len(faces) > 1:
            messagebox.showwarning("พบหลายใบหน้า", "กรุณาให้มีใบหน้าเดียวในเฟรมตอนลงทะเบียน")
            return

        face = faces[0]
        database.add_embedding(self.current_student_id, face.embedding)
        self.captured_count += 1
        self.lbl_capture_status.config(
            text=f"ถ่ายแล้ว {self.captured_count} / {config.ENROLL_SHOTS_PER_STUDENT} ภาพ (แนะนำหันหน้าหลายมุม)"
        )
        self._refresh_student_list()
        self.app.refresh_matcher()

        if self.captured_count >= config.ENROLL_SHOTS_PER_STUDENT:
            messagebox.showinfo("ครบแล้ว", "ลงทะเบียนใบหน้าครบตามจำนวนที่แนะนำแล้ว\nสามารถถ่ายเพิ่มได้ถ้าต้องการความแม่นยำสูงขึ้น")


# ============================================================================
# Tab 2: จัดการกิจกรรม
# ============================================================================

class EventTab(ttk.Frame):
    def __init__(self, parent, app):
        super().__init__(parent)
        self.app = app
        self._build_ui()
        self._refresh()

    def _build_ui(self):
        form = ttk.LabelFrame(self, text=" สร้างกิจกรรมใหม่ ", padding=10)
        form.pack(fill="x", padx=10, pady=10)

        ttk.Label(form, text="ชื่อกิจกรรม:", style="FieldLabel.TLabel").grid(row=0, column=0, padx=5, pady=5, sticky="w")
        self.entry_name = ttk.Entry(form, width=40)
        self.entry_name.grid(row=0, column=1, padx=5, pady=5)

        ttk.Label(form, text="วันที่ (YYYY-MM-DD):", style="FieldLabel.TLabel").grid(row=1, column=0, padx=5, pady=5, sticky="w")
        self.entry_date = ttk.Entry(form, width=40)
        self.entry_date.grid(row=1, column=1, padx=5, pady=5)

        ttk.Label(form, text="สถานที่:", style="FieldLabel.TLabel").grid(row=2, column=0, padx=5, pady=5, sticky="w")
        self.entry_location = ttk.Entry(form, width=40)
        self.entry_location.grid(row=2, column=1, padx=5, pady=5)

        ttk.Button(form, text="+ สร้างกิจกรรม", style="Accent.TButton", command=self._create_event).grid(
            row=3, column=0, columnspan=2, pady=8, sticky="ew"
        )

        list_frame = ttk.LabelFrame(self, text=" กิจกรรมทั้งหมด ", padding=10)
        list_frame.pack(fill="both", expand=True, padx=10, pady=(0, 10))

        columns = ("name", "date", "location")
        self.tree = ttk.Treeview(list_frame, columns=columns, show="headings", height=15)
        for col, text, w in [("name", "ชื่อกิจกรรม", 300), ("date", "วันที่", 120), ("location", "สถานที่", 200)]:
            self.tree.heading(col, text=text)
            self.tree.column(col, width=w)
        self.tree.pack(fill="both", expand=True, padx=5, pady=5)

        ttk.Button(list_frame, text="🗑  ลบกิจกรรมที่เลือก", style="Danger.TButton", command=self._delete_selected).pack(
            anchor="e", padx=5, pady=4
        )

    def _create_event(self):
        name = self.entry_name.get().strip()
        date = self.entry_date.get().strip() or None
        location = self.entry_location.get().strip()
        if not name:
            messagebox.showwarning("ข้อมูลไม่ครบ", "กรุณากรอกชื่อกิจกรรม")
            return
        database.add_event(name, date, location)
        self.entry_name.delete(0, "end")
        self.entry_date.delete(0, "end")
        self.entry_location.delete(0, "end")
        self._refresh()
        self.app.attendance_tab.refresh_event_list()
        self.app.report_tab.refresh_event_list()

    def _refresh(self):
        for row in self.tree.get_children():
            self.tree.delete(row)
        for e in database.list_events():
            self.tree.insert(
                "", "end", iid=str(e["id"]),
                values=(e["event_name"], e["event_date"], e["location"]),
            )

    def _delete_selected(self):
        sel = self.tree.selection()
        if not sel:
            return
        if messagebox.askyesno("ยืนยัน", "ลบกิจกรรมที่เลือก (รวมประวัติเช็คชื่อ) ใช่หรือไม่?"):
            for iid in sel:
                database.delete_event(int(iid))
            self._refresh()
            self.app.attendance_tab.refresh_event_list()
            self.app.report_tab.refresh_event_list()


# ============================================================================
# Tab 3: เช็คชื่อด้วยกล้อง (real-time)
# ============================================================================

class AttendanceTab(ttk.Frame):
    def __init__(self, parent, app):
        super().__init__(parent)
        self.app = app
        self.camera = None
        self.worker = None
        self.display_job = None
        self._build_ui()
        self.refresh_event_list()

    def _build_ui(self):
        top = ttk.Frame(self, style="Card.TFrame", padding=10)
        top.pack(fill="x", padx=10, pady=10)

        ttk.Label(top, text="กิจกรรม:", style="FieldLabel.TLabel").grid(row=0, column=0, sticky="w", padx=(0, 4))
        self.event_combo = ttk.Combobox(top, state="readonly", width=32)
        self.event_combo.grid(row=0, column=1, padx=(0, 15))

        ttk.Label(top, text="โหมดสแกน:", style="FieldLabel.TLabel").grid(row=0, column=2, sticky="w", padx=(0, 4))
        self.scan_mode_combo = ttk.Combobox(
            top, state="readonly", width=14, values=["สแกนเข้า", "สแกนออก"]
        )
        self.scan_mode_combo.current(0)
        self.scan_mode_combo.grid(row=0, column=3, padx=(0, 15))

        ttk.Label(top, text="กล้อง:", style="FieldLabel.TLabel").grid(row=0, column=4, sticky="w", padx=(0, 4))
        self.camera_combo = ttk.Combobox(top, state="readonly", width=10)
        self.camera_combo.grid(row=0, column=5, padx=(0, 5))
        ttk.Button(top, text="รีเฟรช", command=self._refresh_camera_list).grid(row=0, column=6, padx=(0, 15))
        self._refresh_camera_list()

        self.btn_start = ttk.Button(
            top, text="▶  เริ่มเช็คชื่อ", style="Accent.TButton", command=self._toggle_camera
        )
        self.btn_start.grid(row=0, column=7, padx=(0, 15))

        self.lbl_status = ttk.Label(top, text="", style="StatusOk.TLabel")
        self.lbl_status.grid(row=1, column=0, columnspan=8, sticky="w", pady=(8, 0))

        body = ttk.Frame(self)
        body.pack(fill="both", expand=True, padx=10, pady=(0, 10))

        video_frame = ttk.LabelFrame(body, text=" กล้อง ", padding=8)
        video_frame.pack(side="left", padx=(0, 10))
        self.video_label = ttk.Label(video_frame, text="กล้องยังไม่เปิด", anchor="center")
        self.video_label.pack()

        log_frame = ttk.LabelFrame(body, text=" รายชื่อที่สแกนล่าสุด ", padding=8)
        log_frame.pack(side="left", fill="both", expand=True)
        columns = ("time", "code", "name", "type", "score")
        self.log_tree = ttk.Treeview(log_frame, columns=columns, show="headings", height=20)
        for col, text, w in [
            ("time", "เวลา", 85), ("code", "รหัส", 90),
            ("name", "ชื่อ-สกุล", 200), ("type", "ประเภท", 70), ("score", "ความมั่นใจ", 80),
        ]:
            self.log_tree.heading(col, text=text)
            self.log_tree.column(col, width=w)
        self.log_tree.tag_configure("scan_in", foreground="#1565C0")
        self.log_tree.tag_configure("scan_out", foreground="#6A1B9A")
        self.log_tree.pack(fill="both", expand=True)

    def refresh_event_list(self):
        events = database.list_events()
        self._events_by_label = {f"{e['event_name']} ({e['event_date']})": e["id"] for e in events}
        self.event_combo["values"] = list(self._events_by_label.keys())
        if self._events_by_label:
            self.event_combo.current(0)

    def _refresh_camera_list(self):
        cams = camera_utils.list_available_cameras()
        if not cams:
            cams = [config.CAMERA_INDEX]
        self.camera_combo["values"] = [f"กล้อง {i}" for i in cams]

        saved = database.get_setting("camera_index", str(config.CAMERA_INDEX))
        try:
            saved_idx = int(saved)
        except (TypeError, ValueError):
            saved_idx = config.CAMERA_INDEX
        default_pos = cams.index(saved_idx) if saved_idx in cams else 0
        self.camera_combo.current(default_pos)

    def _selected_camera_index(self):
        label = self.camera_combo.get()
        try:
            idx = int(label.replace("กล้อง", "").strip())
        except ValueError:
            idx = config.CAMERA_INDEX
        database.set_setting("camera_index", idx)
        return idx

    def _selected_scan_type(self):
        return "in" if self.scan_mode_combo.get() == "สแกนเข้า" else "out"

    def _toggle_camera(self):
        if self.camera is None:
            if not self.event_combo.get():
                messagebox.showwarning("ยังไม่ได้เลือกกิจกรรม", "กรุณาเลือกกิจกรรมก่อนเริ่มเช็คชื่อ")
                return
            if self.app.engine is None:
                messagebox.showwarning("โมเดลยังไม่พร้อม", "ระบบกำลังโหลดโมเดลจดจำใบหน้า กรุณารอสักครู่")
                return
            if self.app.matcher is None or self.app.matcher.is_empty():
                messagebox.showwarning("ไม่มีข้อมูลใบหน้า", "ยังไม่มีนักเรียนที่ลงทะเบียนใบหน้าในระบบ")
                return

            event_id = self._current_event_id()
            scan_type = self._selected_scan_type()
            try:
                self.camera = camera_utils.CameraStream(camera_index=self._selected_camera_index()).start()
            except Exception as e:
                messagebox.showerror("เปิดกล้องไม่สำเร็จ", str(e))
                self.camera = None
                return

            # แยกงานตรวจจับใบหน้า+เช็คชื่อไปรันบน thread ของตัวเอง
            # เพื่อให้ภาพกล้องที่แสดงผลลื่น ไม่กระตุกตามความเร็วของ AI
            self.worker = detector_worker.AttendanceWorker(
                camera=self.camera, engine=self.app.engine,
                matcher=self.app.matcher, event_id=event_id, scan_type=scan_type,
            ).start()

            self.btn_start.config(text="■  หยุดเช็คชื่อ")
            self.event_combo.config(state="disabled")
            self.scan_mode_combo.config(state="disabled")
            scan_label = "สแกนเข้า" if scan_type == "in" else "สแกนออก"
            self.lbl_status.config(text=f"กำลังทำงานในโหมด: {scan_label}", style="StatusOk.TLabel")
            for row in self.log_tree.get_children():
                self.log_tree.delete(row)
            self._refresh_display()
        else:
            self._stop_camera()

    def _stop_camera(self):
        if self.display_job:
            self.after_cancel(self.display_job)
            self.display_job = None
        if self.worker:
            self.worker.stop()
            self.worker = None
        if self.camera:
            self.camera.stop()
            self.camera = None
        self.btn_start.config(text="▶  เริ่มเช็คชื่อ")
        self.event_combo.config(state="readonly")
        self.scan_mode_combo.config(state="readonly")
        self.video_label.config(image="", text="กล้องยังไม่เปิด")
        self.lbl_status.config(text="")

    def _current_event_id(self):
        label = self.event_combo.get()
        return self._events_by_label.get(label)

    def _refresh_display(self):
        """
        ลูปนี้รันบน GUI thread ทุก ~30ms
        ดึง 'ภาพกล้องสดล่าสุด' มาแสดงเสมอ (ลื่นเท่าความเร็วกล้องจริง ไม่รอ AI)
        แล้วซ้อนกรอบ/ชื่อจากผลลัพธ์ AI ล่าสุดที่ worker คำนวณไว้ทับลงไป
        ถ้า AI ช้ากว่ากล้อง กรอบจะขยับตามหลังเล็กน้อย แต่ภาพวิดีโอจะไม่กระตุก
        """
        if self.worker is None:
            return

        frame = self.camera.read() if self.camera else None
        if frame is not None:
            for f in self.worker.get_latest_faces():
                face_engine.draw_face_box(frame, f["bbox"], f["label"], color=f["color"])

            img = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            img = cv2.resize(img, (600, 450))
            imgtk = ImageTk.PhotoImage(image=Image.fromarray(img))
            self.video_label.imgtk = imgtk
            self.video_label.config(image=imgtk, text="")

        new_names = []
        while True:
            try:
                student, score, scan_type = self.worker.checkin_queue.get_nowait()
            except Exception:
                break
            self._add_log_row(student, score, scan_type)
            scan_label = "เข้า" if scan_type == "in" else "ออก"
            new_names.append(f"{student['full_name']} ({scan_label})")

        if new_names:
            self.lbl_status.config(text="สแกนล่าสุด: " + ", ".join(new_names), style="StatusOk.TLabel")

        self.display_job = self.after(30, self._refresh_display)

    def _add_log_row(self, student, score, scan_type):
        tag = "scan_in" if scan_type == "in" else "scan_out"
        scan_label = "เข้า" if scan_type == "in" else "ออก"
        self.log_tree.insert(
            "", 0,
            values=(
                time.strftime("%H:%M:%S"),
                student["student_code"],
                student["full_name"],
                scan_label,
                f"{score*100:.0f}%",
            ),
            tags=(tag,),
        )

class ReportTab(ttk.Frame):
    PCT_HIGH = 80
    PCT_MID = 50
    BAR_LEN = 16
    DEPT_ALL = "ทั้งหมด"

    def __init__(self, parent, app):
        super().__init__(parent)
        self.app = app
        self.chart_canvas_widget = None
        self._dept_sort_col = "pct"
        self._dept_sort_reverse = True
        self._dept_rows = {}          
        self._current_report = []    
        self._current_absent = []    
        self._build_ui()
        self.refresh_event_list()


    def _build_ui(self):
        top = ttk.Frame(self, style="Card.TFrame", padding=10)
        top.pack(fill="x", padx=10, pady=10)

        ttk.Label(top, text="กิจกรรม:", style="FieldLabel.TLabel").pack(side="left")
        self.event_combo = ttk.Combobox(top, state="readonly", width=38)
        self.event_combo.pack(side="left", padx=(4, 15))
        self.event_combo.bind("<<ComboboxSelected>>", lambda e: self._load_report())

        ttk.Button(top, text="🔄  โหลดรายงาน", command=self._load_report).pack(side="left", padx=4)
        ttk.Button(top, text="⬇  ส่งออก Excel (พร้อมกราฟ)", style="Accent.TButton", command=self._export).pack(
            side="left", padx=4
        )

        cards_row = ttk.Frame(self, padding=(10, 0))
        cards_row.pack(fill="x")
        self.card_total = self._make_stat_card(cards_row, "นักเรียนทั้งหมด", "#1F3A6E")
        self.card_attended = self._make_stat_card(cards_row, "เข้าร่วมกิจกรรม", "#2E7D32")
        self.card_not_attended = self._make_stat_card(cards_row, "ไม่เข้าร่วมกิจกรรม", "#C62828")

        self.lbl_summary_note = ttk.Label(
            self,
            text='เงื่อนไข: นับเป็น "เข้าร่วมกิจกรรม" เฉพาะผู้ที่มีทั้งสแกนเข้าและสแกนออกเท่านั้น',
            style="Muted.TLabel",
            padding=(10, 6, 10, 0),
        )
        self.lbl_summary_note.pack(anchor="w")

        # --- แถบกรองตามสาขา ใช้ร่วมกันกับแท็บ "เข้าร่วม" / "ไม่เข้าร่วม" ---
        filter_row = ttk.Frame(self, padding=(10, 8, 10, 0))
        filter_row.pack(fill="x")
        ttk.Label(filter_row, text="กรองรายชื่อตามสาขา:", style="FieldLabel.TLabel").pack(side="left")
        self.dept_filter_combo = ttk.Combobox(filter_row, state="readonly", width=28)
        self.dept_filter_combo.pack(side="left", padx=(4, 4))
        self.dept_filter_combo.bind("<<ComboboxSelected>>", lambda e: self._apply_department_filter())
        ttk.Button(filter_row, text="✕ ล้างตัวกรอง", command=self._clear_department_filter).pack(
            side="left", padx=4
        )
        self.lbl_filter_status = ttk.Label(filter_row, text="", style="Muted.TLabel")
        self.lbl_filter_status.pack(side="left", padx=10)

        notebook = ttk.Notebook(self)
        notebook.pack(fill="both", expand=True, padx=10, pady=10)
        self.notebook = notebook

        self.chart_frame = ttk.Frame(notebook)
        notebook.add(self.chart_frame, text="  📊  สรุปภาพรวม  ")

        self._build_department_tab(notebook)

        present_frame = ttk.Frame(notebook)
        notebook.add(present_frame, text="  ✅  เข้าร่วมกิจกรรม  ")
        self._present_tab_index = notebook.index("end") - 1
        columns = ("time_in", "time_out", "code", "name", "class", "dept", "score")
        self.present_tree = ttk.Treeview(present_frame, columns=columns, show="headings", height=16)
        for col, text, w in [
            ("time_in", "เวลาสแกนเข้า", 120), ("time_out", "เวลาสแกนออก", 120), ("code", "รหัส", 90),
            ("name", "ชื่อ-สกุล", 200), ("class", "ห้อง", 90), ("dept", "สาขา", 140), ("score", "ความมั่นใจ", 80),
        ]:
            self.present_tree.heading(col, text=text)
            self.present_tree.column(col, width=w)
        self.present_tree.tag_configure("attended", foreground="#2E7D32")
        self.present_tree.pack(fill="both", expand=True, padx=5, pady=5)

        # --- แท็บไม่เข้าร่วมกิจกรรม (สแกนไม่ครบ + ไม่สแกนเลย) ---
        absent_frame = ttk.Frame(notebook)
        notebook.add(absent_frame, text="  ❌  ไม่เข้าร่วมกิจกรรม  ")
        columns2 = ("code", "name", "class", "dept", "note")
        self.absent_tree = ttk.Treeview(absent_frame, columns=columns2, show="headings", height=16)
        for col, text, w in [
            ("code", "รหัส", 90), ("name", "ชื่อ-สกุล", 200),
            ("class", "ห้อง", 90), ("dept", "สาขา", 140), ("note", "หมายเหตุ", 180),
        ]:
            self.absent_tree.heading(col, text=text)
            self.absent_tree.column(col, width=w)
        self.absent_tree.tag_configure("not_attended", foreground="#C62828")
        self.absent_tree.pack(fill="both", expand=True, padx=5, pady=5)

    def _make_stat_card(self, parent, title, color):
        """การ์ดตัวเลขสรุปแบบย่อ (ใช้ 3 ใบ: ทั้งหมด / เข้าร่วม / ไม่เข้าร่วม)"""
        card = ttk.Frame(parent, style="Card.TFrame", padding=14)
        card.pack(side="left", padx=(0, 10), fill="both", expand=True)
        lbl_value = tk.Label(card, text="0", font=("Tahoma", 22, "bold"), fg=color, bg="#F4F6FA")
        lbl_value.pack(anchor="w")
        tk.Label(card, text=title, font=("Tahoma", 10), fg="#666666", bg="#F4F6FA").pack(anchor="w")
        lbl_pct = tk.Label(card, text="", font=("Tahoma", 10, "bold"), fg=color, bg="#F4F6FA")
        lbl_pct.pack(anchor="w")
        return {"value": lbl_value, "pct": lbl_pct}

    def _build_department_tab(self, notebook):
        """แท็บใหม่: ตารางสรุป % เข้าร่วมแยกตามสาขา เรียงลำดับได้ + คลิกเพื่อกรองรายชื่อ"""
        dept_frame = ttk.Frame(notebook)
        notebook.add(dept_frame, text="  🏫  แยกตามสาขา (%)  ")
        self._dept_tab_index = notebook.index("end") - 1

        ttk.Label(
            dept_frame,
            text="คลิกหัวคอลัมน์เพื่อจัดเรียง • ดับเบิลคลิกแถวเพื่อกรองรายชื่อเฉพาะสาขานั้น",
            style="Muted.TLabel",
        ).pack(anchor="w", padx=8, pady=(8, 4))

        columns = ("dept", "attended", "not_attended", "total", "pct_bar")
        self.dept_tree = ttk.Treeview(dept_frame, columns=columns, show="headings", height=16)
        headers = [
            ("dept", "สาขา", 200, "w"),
            ("attended", "เข้าร่วม", 90, "center"),
            ("not_attended", "ไม่เข้าร่วม", 100, "center"),
            ("total", "รวม", 70, "center"),
            ("pct_bar", "% เข้าร่วม", 280, "w"),
        ]
        for col, text, w, anchor in headers:
            self.dept_tree.heading(col, text=text, command=lambda c=col: self._sort_department_tree(c))
            self.dept_tree.column(col, width=w, anchor=anchor)
        self.dept_tree.tag_configure("high", foreground="#2E7D32")
        self.dept_tree.tag_configure("mid", foreground="#B36B00")
        self.dept_tree.tag_configure("low", foreground="#C62828")
        self.dept_tree.pack(fill="both", expand=True, padx=8, pady=(0, 8))
        self.dept_tree.bind("<Double-1>", self._on_department_row_double_click)


    def refresh_event_list(self):
        events = database.list_events()
        self._events_by_label = {f"{e['event_name']} ({e['event_date']})": e["id"] for e in events}
        self.event_combo["values"] = list(self._events_by_label.keys())
        if self._events_by_label:
            self.event_combo.current(0)
            self._load_report()

    def _current_event(self):
        label = self.event_combo.get()
        event_id = self._events_by_label.get(label)
        return event_id, label

    def _load_report(self):
        event_id, label = self._current_event()
        if event_id is None:
            return
        event_name = label.split(" (")[0]

        self._current_report = database.get_attendance_report(event_id)
        self._current_absent = database.get_absent_report(event_id)
        summary = database.get_attendance_summary(event_id)

        self._update_stat_cards(summary)
        self._populate_department_tree(summary.get("by_department", {}))
        self._refresh_department_filter_options(summary.get("by_department", {}))
        self._apply_department_filter()
        self._render_chart(summary, event_name)

    def _update_stat_cards(self, summary):
        total = summary["total"]
        pct_attended = (summary["attended"] / total * 100) if total else 0
        pct_not_attended = 100 - pct_attended if total else 0

        self.card_total["value"].config(text=str(total))
        self.card_total["pct"].config(text="คน")

        self.card_attended["value"].config(text=str(summary["attended"]))
        self.card_attended["pct"].config(text=f"{pct_attended:.1f}%")

        self.card_not_attended["value"].config(text=str(summary["not_attended"]))
        self.card_not_attended["pct"].config(text=f"{pct_not_attended:.1f}%")

    # ------------------------------------------------------- แท็บแยกตามสาขา (%) ---

    def _bar_text(self, pct):
        filled = round(pct / 100 * self.BAR_LEN)
        filled = max(0, min(self.BAR_LEN, filled))
        return f"{'█' * filled}{'░' * (self.BAR_LEN - filled)}  {pct:.1f}%"

    def _pct_tag(self, pct):
        if pct >= self.PCT_HIGH:
            return "high"
        if pct >= self.PCT_MID:
            return "mid"
        return "low"

    def _populate_department_tree(self, by_department):
        self.dept_tree.delete(*self.dept_tree.get_children())
        self._dept_rows = {}

        for dept, counts in by_department.items():
            attended = counts["attended"]
            not_attended = counts["not_attended"]
            total = attended + not_attended
            pct = (attended / total * 100) if total else 0
            self._dept_rows[dept] = {
                "attended": attended, "not_attended": not_attended, "total": total, "pct": pct,
            }

        self._render_department_tree_sorted()

    def _render_department_tree_sorted(self):
        """เรียงและวาดตารางสาขาใหม่ตาม self._dept_sort_col / self._dept_sort_reverse"""
        self.dept_tree.delete(*self.dept_tree.get_children())
        col = self._dept_sort_col
        if col == "dept":
            items = sorted(self._dept_rows.items(), key=lambda kv: kv[0], reverse=self._dept_sort_reverse)
        else:
            key_map = {"attended": "attended", "not_attended": "not_attended", "total": "total", "pct_bar": "pct"}
            key = key_map.get(col, "pct")
            items = sorted(self._dept_rows.items(), key=lambda kv: kv[1][key], reverse=self._dept_sort_reverse)

        for dept, data in items:
            self.dept_tree.insert(
                "", "end", iid=dept,
                values=(dept, data["attended"], data["not_attended"], data["total"], self._bar_text(data["pct"])),
                tags=(self._pct_tag(data["pct"]),),
            )

    def _sort_department_tree(self, col):
        if self._dept_sort_col == col:
            self._dept_sort_reverse = not self._dept_sort_reverse
        else:
            self._dept_sort_col = col
            self._dept_sort_reverse = True  # ค่าเริ่มต้น: มาก -> น้อย
        self._render_department_tree_sorted()

    def _on_department_row_double_click(self, event):
        item = self.dept_tree.identify_row(event.y)
        if not item:
            return
        if item in self.dept_filter_combo["values"]:
            self.dept_filter_combo.set(item)
            self._apply_department_filter()
            self.notebook.select(self._present_tab_index)


    def _refresh_department_filter_options(self, by_department):
        values = [self.DEPT_ALL] + sorted(by_department.keys())
        current = self.dept_filter_combo.get()
        self.dept_filter_combo["values"] = values
        self.dept_filter_combo.set(current if current in values else self.DEPT_ALL)

    def _clear_department_filter(self):
        self.dept_filter_combo.set(self.DEPT_ALL)
        self._apply_department_filter()

    def _selected_department(self):
        dept = self.dept_filter_combo.get() or self.DEPT_ALL
        return None if dept == self.DEPT_ALL else dept

    def _apply_department_filter(self):
        dept = self._selected_department()

        def match(row):
            return dept is None or (row.get("department") or "ไม่ระบุสาขา") == dept

        report = [r for r in self._current_report if match(r)]
        absent = [r for r in self._current_absent if match(r)]
        attended = [r for r in report if r["attended"]]
        not_attended_partial = [r for r in report if not r["attended"]]

        self.present_tree.delete(*self.present_tree.get_children())
        self.absent_tree.delete(*self.absent_tree.get_children())

        for r in attended:
            self.present_tree.insert(
                "", "end",
                values=(
                    r["checkin_time"], r["check_out_time"], r["student_code"], r["full_name"], r["class_room"],
                    r.get("department", "") or "-", f"{(r['confidence'] or 0)*100:.0f}%",
                ),
                tags=("attended",),
            )
        for r in not_attended_partial:
            note = r["status_text"].replace("ไม่เข้าร่วมกิจกรรม ", "").strip("()") or "สแกนไม่ครบ"
            self.absent_tree.insert(
                "", "end",
                values=(r["student_code"], r["full_name"], r["class_room"], r.get("department", "") or "-", note),
                tags=("not_attended",),
            )
        for r in absent:
            self.absent_tree.insert(
                "", "end",
                values=(
                    r["student_code"], r["full_name"], r["class_room"], r.get("department", "") or "-",
                    "ไม่ได้สแกนเลย",
                ),
                tags=("not_attended",),
            )

        if dept is None:
            self.lbl_filter_status.config(text="")
        else:
            self.lbl_filter_status.config(
                text=f"กำลังแสดงเฉพาะสาขา \"{dept}\"   —   เข้าร่วม {len(attended)} / "
                f"{len(attended) + len(not_attended_partial) + len(absent)} คน"
            )


    def _render_chart(self, summary, event_name):
        if self.chart_canvas_widget is not None:
            self.chart_canvas_widget.destroy()
            self.chart_canvas_widget = None

        try:
            from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
            import chart_utils
            fig = chart_utils.build_summary_figure(summary, event_name)
            canvas = FigureCanvasTkAgg(fig, master=self.chart_frame)
            canvas.draw()
            self.chart_canvas_widget = canvas.get_tk_widget()
            self.chart_canvas_widget.pack(fill="both", expand=True, padx=10, pady=10)
        except Exception as e:
            ttk.Label(
                self.chart_frame, text=f"ไม่สามารถแสดงกราฟได้: {e}", style="Muted.TLabel"
            ).pack(padx=20, pady=20)

    def _export(self):
        event_id, label = self._current_event()
        if event_id is None:
            messagebox.showwarning("ยังไม่ได้เลือกกิจกรรม", "กรุณาเลือกกิจกรรมก่อน")
            return
        event_name = label.split(" (")[0]
        path = export_utils.export_attendance_report(event_id, event_name)
        messagebox.showinfo("ส่งออกสำเร็จ", f"บันทึกไฟล์แล้วที่:\n{path}")


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("ระบบเช็คชื่อเข้าร่วมกิจกรรมด้วยใบหน้า - วิทยาลัยการอาชีพจอมทอง")
        self.geometry("1280x800")
        self.minsize(1100, 680)

        database.init_db()

        self.engine = None
        self.matcher = None

        self._setup_style()
        self._build_menu()

        self.status_bar = ttk.Label(
            self, text="  กำลังโหลดโมเดลจดจำใบหน้า กรุณารอสักครู่...",
            style="StatusWarn.TLabel", padding=(4, 4),
        )
        self.status_bar.pack(side="bottom", fill="x")

        notebook = ttk.Notebook(self)
        notebook.pack(fill="both", expand=True, padx=8, pady=8)

        self.student_tab = StudentTab(notebook, self)
        self.event_tab = EventTab(notebook, self)
        self.attendance_tab = AttendanceTab(notebook, self)
        self.report_tab = ReportTab(notebook, self)

        notebook.add(self.student_tab, text="  🧑‍🎓  1. จัดการนักเรียน  ")
        notebook.add(self.event_tab, text="  📅  2. จัดการกิจกรรม  ")
        notebook.add(self.attendance_tab, text="  📷  3. เช็คชื่อ  ")
        notebook.add(self.report_tab, text="  📊  4. รายงาน  ")

        self.protocol("WM_DELETE_WINDOW", self._on_close)

        ModelLoader(self._on_model_ready, self._on_model_error).start()

    def _setup_style(self):
        """ตั้งค่าธีม/สไตล์ ttk ทั้งระบบไว้ที่เดียว ให้หน้าตาสม่ำเสมอและอ่านง่ายทุกแท็บ"""
        style = ttk.Style(self)
        try:
            style.theme_use("vista") 
        except tk.TclError:
            pass

        base_font = ("Tahoma", 10)
        header_font = ("Tahoma", 12, "bold")
        self.option_add("*Font", base_font)

        style.configure(".", font=base_font)
        style.configure("TNotebook.Tab", font=("Tahoma", 10, "bold"), padding=(10, 8))
        style.configure("TLabelframe.Label", font=("Tahoma", 10, "bold"), foreground="#2E5395")
        style.configure("TButton", padding=(10, 6))
        style.configure("Treeview", rowheight=26, font=base_font)
        style.configure("Treeview.Heading", font=("Tahoma", 10, "bold"))

        style.configure("Accent.TButton", font=("Tahoma", 10, "bold"), foreground="#000000")
        style.map(
            "Accent.TButton",
            background=[("disabled", "#B7C2D6"), ("!disabled", "#2E5395"), ("active", "#1F3A6E")],
            foreground=[("disabled", "#333333"), ("!disabled", "#000000"), ("active", "#000000")],
        )

        style.configure("Danger.TButton", font=("Tahoma", 10, "bold"))
        style.map("Danger.TButton", foreground=[("disabled", "#B0B0B0"), ("!disabled", "#C62828")])

        style.configure("Header.TLabel", font=header_font, foreground="#1F3A6E")
        style.configure("FieldLabel.TLabel", font=("Tahoma", 10, "bold"))
        style.configure("Muted.TLabel", foreground="#666666")
        style.configure("Card.TFrame", background="#F4F6FA", relief="flat")

        style.configure("StatusOk.TLabel", foreground="#2E7D32", font=("Tahoma", 10, "bold"))
        style.configure("StatusBad.TLabel", foreground="#C62828", font=("Tahoma", 10, "bold"))
        style.configure("StatusWarn.TLabel", foreground="#B36B00", font=("Tahoma", 10, "bold"))

    def _build_menu(self):
        menubar = tk.Menu(self)
        file_menu = tk.Menu(menubar, tearoff=0)
        file_menu.add_command(label="สำรองข้อมูล (Backup)...", command=self._backup_database)
        file_menu.add_command(label="กู้คืนข้อมูลจากไฟล์สำรอง (Restore)...", command=self._restore_database)
        file_menu.add_separator()
        file_menu.add_command(label="ออกจากโปรแกรม", command=self._on_close)
        menubar.add_cascade(label="ไฟล์", menu=file_menu)
        self.config(menu=menubar)

    def _backup_database(self):
        default_name = f"attendance_backup_{datetime.date.today().isoformat()}.db"
        path = filedialog.asksaveasfilename(
            title="บันทึกไฟล์สำรองข้อมูล",
            defaultextension=".db",
            filetypes=[("Database files", "*.db"), ("All files", "*.*")],
            initialfile=default_name,
        )
        if not path:
            return
        try:
            shutil.copy2(config.DB_PATH, path)
        except Exception as e:
            messagebox.showerror("สำรองข้อมูลล้มเหลว", str(e))
            return
        messagebox.showinfo(
            "สำรองข้อมูลสำเร็จ",
            f"บันทึกไฟล์สำรองแล้วที่:\n{path}\n\n"
            "ไฟล์นี้มีข้อมูลนักเรียน, ใบหน้าที่ลงทะเบียน, กิจกรรม และประวัติเช็คชื่อทั้งหมด\n"
            "แนะนำให้เก็บสำเนาไว้ในที่ปลอดภัย (USB, Google Drive) แยกจากเครื่องนี้",
        )

    def _restore_database(self):
        path = filedialog.askopenfilename(
            title="เลือกไฟล์สำรองข้อมูลที่จะกู้คืน",
            filetypes=[("Database files", "*.db"), ("All files", "*.*")],
        )
        if not path:
            return

        confirm = messagebox.askyesno(
            "ยืนยันการกู้คืนข้อมูล",
            "การกู้คืนจะ 'แทนที่' ข้อมูลปัจจุบันทั้งหมดด้วยไฟล์สำรองที่เลือก\n"
            "(นักเรียน/ใบหน้า/กิจกรรม/ประวัติเช็คชื่อปัจจุบันจะหายไป ถ้ายังไม่ได้สำรองไว้ก่อน)\n\n"
            "ต้องการดำเนินการต่อหรือไม่?",
            icon="warning",
        )
        if not confirm:
            return

        for tab in (self.student_tab, self.attendance_tab):
            try:
                tab._stop_camera()
            except Exception:
                pass

        try:
            shutil.copy2(path, config.DB_PATH)
        except Exception as e:
            messagebox.showerror("กู้คืนข้อมูลล้มเหลว", str(e))
            return

        self.refresh_matcher()
        self.student_tab._refresh_room_filter()
        self.student_tab._refresh_department_filter()
        self.event_tab._refresh()
        self.attendance_tab.refresh_event_list()
        self.report_tab.refresh_event_list()

        messagebox.showinfo("กู้คืนข้อมูลสำเร็จ", "กู้คืนข้อมูลจากไฟล์สำรองเรียบร้อยแล้ว")

    def _on_model_ready(self, engine):
        self.engine = engine
        self.refresh_matcher()
        self.status_bar.config(text="  ✓ โหลดโมเดลสำเร็จ พร้อมใช้งาน", style="StatusOk.TLabel")

    def _on_model_error(self, err):
        self.status_bar.config(text=f"  ✗ โหลดโมเดลล้มเหลว: {err}", style="StatusBad.TLabel")
        messagebox.showerror(
            "โหลดโมเดลล้มเหลว",
            f"ไม่สามารถโหลดโมเดล InsightFace ได้:\n{err}\n\n"
            "ตรวจสอบว่าติดตั้ง insightface และ onnxruntime แล้ว (ดู README.md)",
        )

    def refresh_matcher(self):
        self.matcher = face_engine.FaceMatcher.load_from_db()

    def _on_close(self):
        for tab in (self.student_tab, self.attendance_tab):
            try:
                tab._stop_camera()
            except Exception:
                pass
        self.destroy()


if __name__ == "__main__":
    app = App()
    app.mainloop()