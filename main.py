# -*- coding: utf-8 -*-
"""
main.py
แอปพลิเคชันหลัก - ระบบเช็คชื่อเข้าร่วมกิจกรรมด้วยใบหน้า (Face Attendance System)
Enterprise Edition — CustomTkinter Modern UI

รันด้วยคำสั่ง: python main.py

โครงสร้างหน้าจอ (Sidebar Navigation):
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
from tkinter import ttk, messagebox, filedialog

import customtkinter as ctk
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
# ค่าคงที่ UI
# ============================================================================
SIDEBAR_WIDTH = 220
PRIMARY_COLOR = "#2E5395"
PRIMARY_DARK = "#1F3A6E"
SUCCESS_COLOR = "#2E7D32"
DANGER_COLOR = "#C62828"
WARNING_COLOR = "#B36B00"
MUTED_COLOR = "#888888"
CARD_BG_LIGHT = "#F4F6FA"
CARD_BG_DARK = "#2B2B2B"

FONT_FAMILY = "Tahoma"
FONT_BASE = (FONT_FAMILY, 12)
FONT_BOLD = (FONT_FAMILY, 12, "bold")
FONT_HEADER = (FONT_FAMILY, 16, "bold")
FONT_BIG_NUM = (FONT_FAMILY, 28, "bold")
FONT_SMALL = (FONT_FAMILY, 10)

APP_VERSION = "2.0 Enterprise"

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
# Toast Notification System
# ============================================================================

class ToastManager:
    """ระบบแจ้งเตือนแบบ Toast — แสดงข้อความชั่วคราวแล้วหายไป"""

    def __init__(self, parent):
        self.parent = parent
        self.toasts = []

    def show(self, message, toast_type="info", duration=3000):
        """แสดง toast notification
        toast_type: 'success', 'warning', 'error', 'info'
        """
        colors = {
            "success": ("#2E7D32", "#E8F5E9"),
            "warning": ("#E65100", "#FFF3E0"),
            "error": ("#C62828", "#FFEBEE"),
            "info": ("#1565C0", "#E3F2FD"),
        }
        fg_color, bg_color = colors.get(toast_type, colors["info"])

        icons = {"success": "✓", "warning": "⚠", "error": "✗", "info": "ℹ"}
        icon = icons.get(toast_type, "ℹ")

        toast = ctk.CTkFrame(self.parent, fg_color=bg_color, corner_radius=8, height=42)
        toast.place(relx=1.0, y=10 + len(self.toasts) * 50, anchor="ne", x=-10)

        label = ctk.CTkLabel(
            toast, text=f"  {icon}  {message}  ",
            text_color=fg_color,
            font=FONT_BOLD,
        )
        label.pack(padx=12, pady=8)

        self.toasts.append(toast)

        def remove():
            if toast in self.toasts:
                self.toasts.remove(toast)
                toast.destroy()

        self.parent.after(duration, remove)


# ============================================================================
# Sidebar Navigation
# ============================================================================

class Sidebar(ctk.CTkFrame):
    """แถบนำทางด้านซ้าย — เลือกหน้าที่ต้องการใช้งาน"""

    def __init__(self, parent, app):
        super().__init__(parent, width=SIDEBAR_WIDTH, corner_radius=0, fg_color=PRIMARY_DARK)
        self.app = app
        self.buttons = []
        self.active_index = 0

        # โลโก้/ชื่อระบบ
        header = ctk.CTkFrame(self, fg_color="transparent")
        header.pack(fill="x", padx=15, pady=(20, 5))
        ctk.CTkLabel(header, text="📷", font=(FONT_FAMILY, 32)).pack()
        ctk.CTkLabel(
            header, text="ระบบเช็คชื่อ\nด้วยใบหน้า",
            font=(FONT_FAMILY, 13, "bold"), text_color="white", justify="center",
        ).pack(pady=(4, 0))

        ctk.CTkFrame(self, height=1, fg_color="#3A5384").pack(fill="x", padx=20, pady=12)

        # Navigation buttons
        nav_items = [
            ("🧑‍🎓", "จัดการนักเรียน"),
            ("📅", "จัดการกิจกรรม"),
            ("📷", "เช็คชื่อ"),
            ("📊", "รายงาน"),
        ]
        for i, (icon, label) in enumerate(nav_items):
            btn = ctk.CTkButton(
                self, text=f"  {icon}  {label}",
                font=(FONT_FAMILY, 13, "bold"),
                fg_color="transparent", text_color="white",
                hover_color="#27467D",
                anchor="w", height=44, corner_radius=8,
                command=lambda idx=i: self._select(idx),
            )
            btn.pack(fill="x", padx=10, pady=2)
            self.buttons.append(btn)

        self._highlight(0)

        # Badge counts
        self.badge_labels = {}

        # Spacer
        ctk.CTkFrame(self, fg_color="transparent").pack(fill="both", expand=True)

        # Bottom section — sound toggle + dark mode + version
        bottom = ctk.CTkFrame(self, fg_color="transparent")
        bottom.pack(fill="x", padx=15, pady=(0, 15))

        # Sound toggle
        sound_row = ctk.CTkFrame(bottom, fg_color="transparent")
        sound_row.pack(fill="x", pady=(0, 6))
        ctk.CTkLabel(sound_row, text="🔊 เสียง", text_color="white", font=FONT_SMALL).pack(side="left")
        self.sound_switch = ctk.CTkSwitch(
            sound_row, text="", width=40, height=20,
            command=self._toggle_sound,
        )
        self.sound_switch.pack(side="right")
        try:
            from sound_manager import sound
            if sound.is_enabled():
                self.sound_switch.select()
        except Exception:
            self.sound_switch.select()

        # Dark mode toggle
        mode_row = ctk.CTkFrame(bottom, fg_color="transparent")
        mode_row.pack(fill="x", pady=(0, 6))
        ctk.CTkLabel(mode_row, text="🌙 โหมดมืด", text_color="white", font=FONT_SMALL).pack(side="left")
        self.mode_switch = ctk.CTkSwitch(
            mode_row, text="", width=40, height=20,
            command=self._toggle_mode,
        )
        self.mode_switch.pack(side="right")

        ctk.CTkFrame(self, height=1, fg_color="#3A5384").pack(fill="x", padx=20, pady=(0, 8))
        ctk.CTkLabel(
            self, text=f"v{APP_VERSION}", text_color="#8EA0C0", font=(FONT_FAMILY, 9),
        ).pack(pady=(0, 8))

    def _select(self, index):
        self.active_index = index
        self._highlight(index)
        self.app.show_page(index)

    def _highlight(self, index):
        for i, btn in enumerate(self.buttons):
            if i == index:
                btn.configure(fg_color=PRIMARY_COLOR)
            else:
                btn.configure(fg_color="transparent")

    def _toggle_sound(self):
        try:
            from sound_manager import sound
            enabled = bool(self.sound_switch.get())
            sound.set_enabled(enabled)
            # Sync with AttendanceTab switch if exists
            if hasattr(self.app, 'attendance_tab') and hasattr(self.app.attendance_tab, 'sound_switch'):
                if enabled:
                    self.app.attendance_tab.sound_switch.select()
                else:
                    self.app.attendance_tab.sound_switch.deselect()
        except Exception:
            pass

    def _toggle_mode(self):
        if self.mode_switch.get():
            ctk.set_appearance_mode("dark")
        else:
            ctk.set_appearance_mode("light")


# ============================================================================
# Tab 1: จัดการนักเรียน + ลงทะเบียนใบหน้า
# ============================================================================

class StudentTab(ctk.CTkFrame):
    def __init__(self, parent, app):
        super().__init__(parent, fg_color="transparent")
        self.app = app
        self.camera = None
        self.preview_job = None
        self.captured_count = 0
        self.pending_embeddings = []

        self._build_ui()
        self._refresh_student_list()

    def _build_ui(self):
        # --- ซ้าย: ฟอร์ม + กล้อง ---
        left = ctk.CTkFrame(self, fg_color="transparent", width=420)
        left.pack(side="left", fill="y", padx=(15, 5), pady=15)
        left.pack_propagate(False)

        # ฟอร์มข้อมูลนักเรียน
        form = ctk.CTkFrame(left, corner_radius=12)
        form.pack(fill="x", pady=(0, 10))

        ctk.CTkLabel(form, text="ข้อมูลนักเรียน", font=FONT_HEADER, anchor="w").pack(
            fill="x", padx=15, pady=(12, 6)
        )

        fields_frame = ctk.CTkFrame(form, fg_color="transparent")
        fields_frame.pack(fill="x", padx=15, pady=(0, 10))

        ctk.CTkLabel(fields_frame, text="รหัสนักเรียน", font=FONT_BOLD, anchor="w").pack(fill="x")
        self.entry_code = ctk.CTkEntry(fields_frame, placeholder_text="เช่น 6530101001", height=35)
        self.entry_code.pack(fill="x", pady=(2, 8))

        ctk.CTkLabel(fields_frame, text="ชื่อ-สกุล", font=FONT_BOLD, anchor="w").pack(fill="x")
        self.entry_name = ctk.CTkEntry(fields_frame, placeholder_text="เช่น นายสมชาย ใจดี", height=35)
        self.entry_name.pack(fill="x", pady=(2, 8))

        ctk.CTkLabel(fields_frame, text="ห้อง/ระดับชั้น", font=FONT_BOLD, anchor="w").pack(fill="x")
        self.entry_class = ctk.CTkEntry(fields_frame, placeholder_text="เช่น ปวช.1/1", height=35)
        self.entry_class.pack(fill="x", pady=(2, 8))

        ctk.CTkLabel(fields_frame, text="สาขา", font=FONT_BOLD, anchor="w").pack(fill="x")
        self.entry_department = ctk.CTkEntry(fields_frame, placeholder_text="เช่น คอมพิวเตอร์ธุรกิจ", height=35)
        self.entry_department.pack(fill="x", pady=(2, 8))

        ctk.CTkButton(
            form, text="1) บันทึกข้อมูลนักเรียน",
            font=FONT_BOLD, fg_color=PRIMARY_COLOR, hover_color=PRIMARY_DARK,
            height=40, command=self._save_student,
        ).pack(fill="x", padx=15, pady=(0, 12))

        # กล้องลงทะเบียนใบหน้า
        cam_frame = ctk.CTkFrame(left, corner_radius=12)
        cam_frame.pack(fill="x")

        ctk.CTkLabel(cam_frame, text="2) ลงทะเบียนใบหน้า", font=FONT_HEADER, anchor="w").pack(
            fill="x", padx=15, pady=(12, 6)
        )

        cam_controls = ctk.CTkFrame(cam_frame, fg_color="transparent")
        cam_controls.pack(fill="x", padx=15, pady=(0, 6))

        ctk.CTkLabel(cam_controls, text="กล้อง:", font=FONT_BASE).pack(side="left")
        self.camera_combo = ctk.CTkComboBox(cam_controls, state="readonly", width=100, values=["กล้อง 0"])
        self.camera_combo.pack(side="left", padx=5)
        ctk.CTkButton(cam_controls, text="รีเฟรช", width=70, height=28,
                       fg_color="transparent", border_width=1, text_color=PRIMARY_COLOR,
                       command=self._refresh_camera_list).pack(side="left", padx=(0, 8))
        self._refresh_camera_list()

        btn_row = ctk.CTkFrame(cam_frame, fg_color="transparent")
        btn_row.pack(fill="x", padx=15, pady=(0, 6))
        self.btn_start_cam = ctk.CTkButton(
            btn_row, text="เปิดกล้อง", width=100, height=32,
            fg_color="transparent", border_width=1, text_color=PRIMARY_COLOR,
            command=self._toggle_camera,
        )
        self.btn_start_cam.pack(side="left", padx=(0, 6))
        self.btn_capture = ctk.CTkButton(
            btn_row, text="📸 ถ่ายภาพ + เก็บใบหน้า",
            fg_color=PRIMARY_COLOR, hover_color=PRIMARY_DARK,
            height=32, command=self._capture_face, state="disabled",
        )
        self.btn_capture.pack(side="left", fill="x", expand=True)

        self.video_label = ctk.CTkLabel(cam_frame, text="กล้องยังไม่เปิด", height=280,
                                          fg_color=("gray90", "gray20"), corner_radius=8)
        self.video_label.pack(fill="x", padx=15, pady=(0, 6))

        self.lbl_capture_status = ctk.CTkLabel(
            cam_frame,
            text=f"ถ่ายแล้ว 0 / {config.ENROLL_SHOTS_PER_STUDENT} ภาพ (แนะนำหันหน้าหลายมุม)",
            font=FONT_SMALL, text_color=MUTED_COLOR,
        )
        self.lbl_capture_status.pack(padx=15, pady=(0, 10))

        # --- ขวา: รายชื่อนักเรียน ---
        right = ctk.CTkFrame(self, fg_color="transparent")
        right.pack(side="left", fill="both", expand=True, padx=(5, 15), pady=15)

        # แถวนำเข้า
        import_row = ctk.CTkFrame(right, fg_color="transparent")
        import_row.pack(fill="x", pady=(0, 8))
        ctk.CTkButton(
            import_row, text="📥 นำเข้ารายชื่อจากไฟล์ (Excel/CSV)",
            fg_color=PRIMARY_COLOR, hover_color=PRIMARY_DARK,
            height=34, command=self._import_from_file,
        ).pack(side="left")
        ctk.CTkButton(
            import_row, text="📋 ดาวน์โหลดเทมเพลต",
            fg_color="transparent", border_width=1, text_color=PRIMARY_COLOR,
            height=34, command=self._download_template,
        ).pack(side="left", padx=6)

        # แถวกรอง
        filter_frame = ctk.CTkFrame(right, corner_radius=8)
        filter_frame.pack(fill="x", pady=(0, 8))
        filter_inner = ctk.CTkFrame(filter_frame, fg_color="transparent")
        filter_inner.pack(fill="x", padx=10, pady=8)

        ctk.CTkLabel(filter_inner, text="ห้อง:", font=FONT_SMALL).pack(side="left")
        self.room_filter_combo = ctk.CTkComboBox(filter_inner, state="readonly", width=120,
                                                  values=["ทั้งหมด"], command=lambda v: self._refresh_student_list())
        self.room_filter_combo.pack(side="left", padx=(4, 10))
        self.room_filter_combo.set("ทั้งหมด")

        ctk.CTkLabel(filter_inner, text="สาขา:", font=FONT_SMALL).pack(side="left")
        self.department_filter_combo = ctk.CTkComboBox(filter_inner, state="readonly", width=140,
                                                        values=["ทั้งหมด"], command=lambda v: self._refresh_student_list())
        self.department_filter_combo.pack(side="left", padx=(4, 10))
        self.department_filter_combo.set("ทั้งหมด")

        ctk.CTkLabel(filter_inner, text="🔍", font=FONT_SMALL).pack(side="left")
        self.entry_search = ctk.CTkEntry(filter_inner, placeholder_text="ค้นหาชื่อ/รหัส...", height=30)
        self.entry_search.pack(side="left", fill="x", expand=True, padx=(4, 0))
        self.entry_search.bind("<KeyRelease>", lambda e: self._refresh_student_list())

        # ข้อมูลกลุ่มเรียน
        self.lbl_group_info = ctk.CTkLabel(right, text="", text_color=PRIMARY_COLOR, font=FONT_SMALL, anchor="w")
        self.lbl_group_info.pack(fill="x", pady=(0, 2))

        ctk.CTkLabel(
            right, text="ดับเบิลคลิกที่แถวเพื่อเลือกนักเรียนสำหรับถ่ายภาพลงทะเบียนใบหน้า",
            text_color=MUTED_COLOR, font=FONT_SMALL, anchor="w",
        ).pack(fill="x", pady=(0, 4))

        # ตาราง Treeview (ยังใช้ ttk Treeview เพราะ CTk ไม่มี Treeview)
        tree_frame = ctk.CTkFrame(right, corner_radius=8)
        tree_frame.pack(fill="both", expand=True)

        style = ttk.Style()
        style.configure("Enterprise.Treeview", rowheight=28, font=FONT_BASE)
        style.configure("Enterprise.Treeview.Heading", font=FONT_BOLD)

        columns = ("code", "name", "class", "department", "type", "status", "faces")
        self.tree = ttk.Treeview(tree_frame, columns=columns, show="headings",
                                  style="Enterprise.Treeview")
        for col, text, w in [
            ("code", "รหัส", 95), ("name", "ชื่อ-สกุล", 180), ("class", "ห้อง", 80),
            ("department", "สาขา", 130), ("type", "ประเภท", 80),
            ("status", "สถานะ", 80), ("faces", "ภาพใบหน้า", 80),
        ]:
            self.tree.heading(col, text=text)
            self.tree.column(col, width=w)

        scrollbar = ttk.Scrollbar(tree_frame, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=scrollbar.set)
        self.tree.pack(side="left", fill="both", expand=True, padx=(8, 0), pady=8)
        scrollbar.pack(side="right", fill="y", pady=8, padx=(0, 4))
        self.tree.bind("<Double-1>", self._select_student_for_enrollment)

        # แถวล่าง
        bottom_row = ctk.CTkFrame(right, fg_color="transparent")
        bottom_row.pack(fill="x", pady=(6, 0))
        self.lbl_student_count = ctk.CTkLabel(bottom_row, text="", font=FONT_SMALL, text_color=MUTED_COLOR)
        self.lbl_student_count.pack(side="left")
        ctk.CTkButton(
            bottom_row, text="🗑  ลบนักเรียนที่เลือก",
            fg_color=DANGER_COLOR, hover_color="#8B0000",
            height=32, width=180, command=self._delete_selected,
        ).pack(side="right")

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
        self.lbl_capture_status.configure(
            text=f"ถ่ายแล้ว 0 / {config.ENROLL_SHOTS_PER_STUDENT} ภาพ (แนะนำหันหน้าหลายมุม)"
        )
        self._refresh_room_filter()
        self._refresh_department_filter()
        self.app.toast.show(f"บันทึกข้อมูล {name} สำเร็จ", "success")
        messagebox.showinfo(
            "สำเร็จ", "บันทึกข้อมูลนักเรียนแล้ว\nขั้นต่อไป: เปิดกล้องแล้วกด 'ถ่ายภาพ + เก็บใบหน้า'"
        )

    def _refresh_student_list(self, *_args):
        for row in self.tree.get_children():
            self.tree.delete(row)

        selected_room = self.room_filter_combo.get() if hasattr(self, "room_filter_combo") else None
        selected_dept = self.department_filter_combo.get() if hasattr(self, "department_filter_combo") else None
        students = database.list_students(
            self.entry_search.get().strip(), class_room=selected_room, department=selected_dept
        )

        enrolled_count = 0
        for s in students:
            n_faces = database.count_embeddings_for_student(s["id"])
            if n_faces > 0:
                enrolled_count += 1
            self.tree.insert(
                "", "end", iid=str(s["id"]),
                values=(
                    s["student_code"], s["full_name"], s["class_room"], s.get("department", ""),
                    s.get("student_type", ""), s.get("status", ""), n_faces,
                ),
            )

        total = len(students)
        self.lbl_student_count.configure(
            text=f"แสดง {total} คน  |  ลงทะเบียนใบหน้าแล้ว {enrolled_count} คน"
        )
        self._update_group_info_panel(selected_room)

    def _refresh_room_filter(self):
        current = self.room_filter_combo.get()
        rooms = database.list_class_rooms()
        values = ["ทั้งหมด"] + rooms
        self.room_filter_combo.configure(values=values)
        if current in values:
            self.room_filter_combo.set(current)
        else:
            self.room_filter_combo.set("ทั้งหมด")
        self._refresh_student_list()

    def _refresh_department_filter(self):
        current = self.department_filter_combo.get()
        depts = database.list_departments()
        values = ["ทั้งหมด"] + depts
        self.department_filter_combo.configure(values=values)
        if current in values:
            self.department_filter_combo.set(current)
        else:
            self.department_filter_combo.set("ทั้งหมด")
        self._refresh_student_list()

    def _update_group_info_panel(self, selected_room):
        if not selected_room or selected_room == "ทั้งหมด":
            self.lbl_group_info.configure(text="")
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
            self.lbl_group_info.configure(text="  |  ".join(parts) if parts else "ไม่มีข้อมูลกลุ่มเรียนเพิ่มเติม")
        else:
            self.lbl_group_info.configure(text="ไม่มีข้อมูลกลุ่มเรียน (นักเรียนกลุ่มนี้ถูกเพิ่มด้วยมือ/เทมเพลตทั่วไป)")

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
            self.app.toast.show(f"ลบนักเรียน {len(sel)} คนสำเร็จ", "success")

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
        self.app.toast.show(f"นำเข้า {result['success']} คนสำเร็จ", "success")

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

        self.lbl_capture_status.configure(
            text=f"เลือก: {student['full_name']} — ถ่ายแล้ว {self.captured_count} / "
            f"{config.ENROLL_SHOTS_PER_STUDENT} ภาพ"
        )

    # -------------------------------------------------------------- กล้อง
    def _refresh_camera_list(self):
        cams = camera_utils.list_available_cameras()
        if not cams:
            cams = [config.CAMERA_INDEX]
        values = [f"กล้อง {i}" for i in cams]
        self.camera_combo.configure(values=values)

        saved = database.get_setting("camera_index", str(config.CAMERA_INDEX))
        try:
            saved_idx = int(saved)
        except (TypeError, ValueError):
            saved_idx = config.CAMERA_INDEX
        default_label = f"กล้อง {saved_idx}" if saved_idx in cams else values[0]
        self.camera_combo.set(default_label)

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
            self.btn_start_cam.configure(text="ปิดกล้อง", fg_color=DANGER_COLOR, hover_color="#8B0000",
                                          text_color="white")
            self.btn_capture.configure(state="normal")
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
        self.btn_start_cam.configure(text="เปิดกล้อง", fg_color="transparent",
                                      text_color=PRIMARY_COLOR)
        self.btn_capture.configure(state="disabled")
        self.video_label.configure(image=None, text="กล้องยังไม่เปิด")

    def _update_preview(self):
        if self.camera is None:
            return
        frame = self.camera.read()
        if frame is not None:
            img = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            img = cv2.resize(img, (400, 300))
            imgtk = ImageTk.PhotoImage(image=Image.fromarray(img))
            self.video_label.imgtk = imgtk
            self.video_label.configure(image=imgtk, text="")
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

        # Face Quality Check
        face = faces[0]
        quality = face_engine.assess_face_quality(frame, face.bbox)
        if not quality["pass"]:
            reasons = "\n".join(f"• {r}" for r in quality["reasons"])
            messagebox.showwarning("คุณภาพภาพไม่ผ่าน", f"กรุณาปรับปรุง:\n{reasons}")
            return

        database.add_embedding(self.current_student_id, face.embedding)
        self.captured_count += 1
        self.lbl_capture_status.configure(
            text=f"ถ่ายแล้ว {self.captured_count} / {config.ENROLL_SHOTS_PER_STUDENT} ภาพ (แนะนำหันหน้าหลายมุม)"
        )
        self._refresh_student_list()
        self.app.refresh_matcher()
        self.app.toast.show(f"ถ่ายภาพที่ {self.captured_count} สำเร็จ ✓", "success")

        # เล่นเสียง
        try:
            from sound_manager import sound
            sound.play_capture()
        except Exception:
            pass

        if self.captured_count >= config.ENROLL_SHOTS_PER_STUDENT:
            messagebox.showinfo("ครบแล้ว", "ลงทะเบียนใบหน้าครบตามจำนวนที่แนะนำแล้ว\nสามารถถ่ายเพิ่มได้ถ้าต้องการความแม่นยำสูงขึ้น")


# ============================================================================
# Tab 2: จัดการกิจกรรม
# ============================================================================

class EventTab(ctk.CTkFrame):
    def __init__(self, parent, app):
        super().__init__(parent, fg_color="transparent")
        self.app = app
        self._build_ui()
        self._refresh()

    def _build_ui(self):
        # ฟอร์มสร้างกิจกรรม
        form = ctk.CTkFrame(self, corner_radius=12)
        form.pack(fill="x", padx=15, pady=15)

        ctk.CTkLabel(form, text="สร้างกิจกรรมใหม่", font=FONT_HEADER, anchor="w").pack(
            fill="x", padx=15, pady=(12, 8)
        )

        fields = ctk.CTkFrame(form, fg_color="transparent")
        fields.pack(fill="x", padx=15, pady=(0, 10))

        # Row 1: ชื่อกิจกรรม
        ctk.CTkLabel(fields, text="ชื่อกิจกรรม", font=FONT_BOLD, anchor="w").grid(
            row=0, column=0, sticky="w", padx=(0, 10), pady=4
        )
        self.entry_name = ctk.CTkEntry(fields, placeholder_text="เช่น อบรมความปลอดภัย ครั้งที่ 1", height=35, width=350)
        self.entry_name.grid(row=0, column=1, sticky="ew", pady=4)

        # Row 2: วันที่
        ctk.CTkLabel(fields, text="วันที่", font=FONT_BOLD, anchor="w").grid(
            row=1, column=0, sticky="w", padx=(0, 10), pady=4
        )
        date_frame = ctk.CTkFrame(fields, fg_color="transparent")
        date_frame.grid(row=1, column=1, sticky="ew", pady=4)
        self.entry_date = ctk.CTkEntry(date_frame, placeholder_text="YYYY-MM-DD", height=35, width=200)
        self.entry_date.pack(side="left")
        ctk.CTkButton(
            date_frame, text="📅 วันนี้", width=80, height=35,
            fg_color="transparent", border_width=1, text_color=PRIMARY_COLOR,
            command=self._fill_today,
        ).pack(side="left", padx=6)

        # Row 3: สถานที่
        ctk.CTkLabel(fields, text="สถานที่", font=FONT_BOLD, anchor="w").grid(
            row=2, column=0, sticky="w", padx=(0, 10), pady=4
        )
        self.entry_location = ctk.CTkEntry(fields, placeholder_text="เช่น ห้องประชุมอาคาร 1", height=35, width=350)
        self.entry_location.grid(row=2, column=1, sticky="ew", pady=4)

        fields.columnconfigure(1, weight=1)

        ctk.CTkButton(
            form, text="+ สร้างกิจกรรม",
            font=FONT_BOLD, fg_color=PRIMARY_COLOR, hover_color=PRIMARY_DARK,
            height=42, command=self._create_event,
        ).pack(fill="x", padx=15, pady=(0, 12))

        # รายการกิจกรรม
        list_frame = ctk.CTkFrame(self, corner_radius=12)
        list_frame.pack(fill="both", expand=True, padx=15, pady=(0, 15))

        ctk.CTkLabel(list_frame, text="กิจกรรมทั้งหมด", font=FONT_HEADER, anchor="w").pack(
            fill="x", padx=15, pady=(12, 6)
        )

        tree_wrapper = ctk.CTkFrame(list_frame, fg_color="transparent")
        tree_wrapper.pack(fill="both", expand=True, padx=10, pady=(0, 8))

        columns = ("name", "date", "location")
        self.tree = ttk.Treeview(tree_wrapper, columns=columns, show="headings",
                                  style="Enterprise.Treeview", height=15)
        for col, text, w in [("name", "ชื่อกิจกรรม", 350), ("date", "วันที่", 130), ("location", "สถานที่", 250)]:
            self.tree.heading(col, text=text)
            self.tree.column(col, width=w)
        self.tree.pack(fill="both", expand=True)

        btn_row = ctk.CTkFrame(list_frame, fg_color="transparent")
        btn_row.pack(fill="x", padx=15, pady=(0, 10))
        ctk.CTkButton(
            btn_row, text="🗑  ลบกิจกรรมที่เลือก",
            fg_color=DANGER_COLOR, hover_color="#8B0000",
            height=34, width=200, command=self._delete_selected,
        ).pack(side="right")

    def _fill_today(self):
        self.entry_date.delete(0, "end")
        self.entry_date.insert(0, datetime.date.today().isoformat())

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
        self.app.toast.show(f"สร้างกิจกรรม '{name}' สำเร็จ", "success")

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
# Tab 3: เช็คชื่อด้วยกล้อง (real-time) — Enterprise Edition
# ============================================================================

class AttendanceTab(ctk.CTkFrame):
    def __init__(self, parent, app):
        super().__init__(parent, fg_color="transparent")
        self.app = app
        self.camera = None
        self.worker = None
        self.display_job = None
        self._scan_count = 0
        self._build_ui()
        self.refresh_event_list()

    def _build_ui(self):
        # --- แถวควบคุม (บนสุด) ---
        top = ctk.CTkFrame(self, corner_radius=12)
        top.pack(fill="x", padx=15, pady=(15, 8))

        controls = ctk.CTkFrame(top, fg_color="transparent")
        controls.pack(fill="x", padx=15, pady=10)

        ctk.CTkLabel(controls, text="กิจกรรม:", font=FONT_BOLD).pack(side="left")
        self.event_combo = ctk.CTkComboBox(controls, state="readonly", width=250, values=[])
        self.event_combo.pack(side="left", padx=(4, 12))

        ctk.CTkLabel(controls, text="โหมด:", font=FONT_BOLD).pack(side="left")
        self.scan_mode_combo = ctk.CTkComboBox(
            controls, state="readonly", width=120, values=["สแกนเข้า", "สแกนออก"]
        )
        self.scan_mode_combo.set("สแกนเข้า")
        self.scan_mode_combo.pack(side="left", padx=(4, 12))

        ctk.CTkLabel(controls, text="กล้อง:", font=FONT_BOLD).pack(side="left")
        self.camera_combo = ctk.CTkComboBox(controls, state="readonly", width=100, values=["กล้อง 0"])
        self.camera_combo.pack(side="left", padx=(4, 4))
        ctk.CTkButton(controls, text="🔄", width=32, height=32,
                       fg_color="transparent", border_width=1, text_color=PRIMARY_COLOR,
                       command=self._refresh_camera_list).pack(side="left", padx=(0, 12))
        self._refresh_camera_list()

        self.btn_start = ctk.CTkButton(
            controls, text="▶  เริ่มเช็คชื่อ",
            font=FONT_BOLD, fg_color=SUCCESS_COLOR, hover_color="#1B5E20",
            height=40, width=150, command=self._toggle_camera,
        )
        self.btn_start.pack(side="left", padx=(0, 15))

        # สวิตช์เปิด/ปิดเสียงตรงหน้าเช็คชื่อ
        sound_ctrl = ctk.CTkFrame(controls, fg_color="transparent")
        sound_ctrl.pack(side="left", padx=(0, 10))
        ctk.CTkLabel(sound_ctrl, text="🔊 เสียง:", font=FONT_BOLD).pack(side="left", padx=(0, 4))
        self.sound_switch = ctk.CTkSwitch(
            sound_ctrl, text="", width=40, height=20,
            command=self._toggle_sound,
        )
        self.sound_switch.pack(side="left")
        try:
            from sound_manager import sound
            if sound.is_enabled():
                self.sound_switch.select()
        except Exception:
            self.sound_switch.select()

        # สถานะ
        status_row = ctk.CTkFrame(top, fg_color="transparent")
        status_row.pack(fill="x", padx=15, pady=(0, 8))
        self.lbl_status = ctk.CTkLabel(status_row, text="", font=FONT_BOLD, text_color=SUCCESS_COLOR)
        self.lbl_status.pack(side="left")
        self.lbl_scan_count = ctk.CTkLabel(status_row, text="", font=FONT_BOLD, text_color=PRIMARY_COLOR)
        self.lbl_scan_count.pack(side="right")

        # --- เนื้อหาหลัก ---
        body = ctk.CTkFrame(self, fg_color="transparent")
        body.pack(fill="both", expand=True, padx=15, pady=(0, 15))

        # วิดีโอ (ซ้าย)
        video_container = ctk.CTkFrame(body, corner_radius=12, width=660)
        video_container.pack(side="left", fill="y", padx=(0, 8))
        video_container.pack_propagate(False)

        ctk.CTkLabel(video_container, text="📷 กล้อง", font=FONT_BOLD, anchor="w").pack(
            fill="x", padx=12, pady=(8, 4)
        )
        self.video_label = ctk.CTkLabel(video_container, text="กล้องยังไม่เปิด\n\nกรุณาเลือกกิจกรรมและกดเริ่มเช็คชื่อ",
                                          height=480, fg_color=("gray90", "gray20"), corner_radius=8)
        self.video_label.pack(fill="both", expand=True, padx=12, pady=(0, 8))

        # ข้อความสแกนล่าสุด (overlay-style)
        self.lbl_last_scan = ctk.CTkLabel(
            video_container, text="", font=(FONT_FAMILY, 14, "bold"),
            fg_color=SUCCESS_COLOR, text_color="white", corner_radius=6, height=0,
        )

        # Log (ขวา)
        log_container = ctk.CTkFrame(body, corner_radius=12)
        log_container.pack(side="left", fill="both", expand=True)

        log_header = ctk.CTkFrame(log_container, fg_color="transparent")
        log_header.pack(fill="x", padx=12, pady=(8, 4))
        ctk.CTkLabel(log_header, text="📋 รายชื่อที่สแกนล่าสุด", font=FONT_BOLD).pack(side="left")

        columns = ("time", "code", "name", "type", "score")
        self.log_tree = ttk.Treeview(log_container, columns=columns, show="headings",
                                      style="Enterprise.Treeview", height=20)
        for col, text, w in [
            ("time", "เวลา", 80), ("code", "รหัส", 90),
            ("name", "ชื่อ-สกุล", 180), ("type", "ประเภท", 65), ("score", "ความมั่นใจ", 75),
        ]:
            self.log_tree.heading(col, text=text)
            self.log_tree.column(col, width=w)
        self.log_tree.tag_configure("scan_in", foreground="#1565C0")
        self.log_tree.tag_configure("scan_out", foreground="#6A1B9A")
        self.log_tree.tag_configure("scan_success", background="#E8F5E9")
        self.log_tree.pack(fill="both", expand=True, padx=12, pady=(0, 12))

    def _toggle_sound(self):
        try:
            from sound_manager import sound
            enabled = bool(self.sound_switch.get())
            sound.set_enabled(enabled)
            # Sync with Sidebar switch
            if hasattr(self.app, 'sidebar') and hasattr(self.app.sidebar, 'sound_switch'):
                if enabled:
                    self.app.sidebar.sound_switch.select()
                else:
                    self.app.sidebar.sound_switch.deselect()
            status_text = "เปิดเสียงสแกนแล้ว" if enabled else "ปิดเสียงสแกนแล้ว (โหมดเงียบ)"
            self.app.toast.show(status_text, "info", duration=1500)
        except Exception:
            pass

    def refresh_event_list(self):
        events = database.list_events()
        self._events_by_label = {f"{e['event_name']} ({e['event_date']})": e["id"] for e in events}
        values = list(self._events_by_label.keys())
        self.event_combo.configure(values=values)
        if values:
            self.event_combo.set(values[0])

    def _refresh_camera_list(self):
        cams = camera_utils.list_available_cameras()
        if not cams:
            cams = [config.CAMERA_INDEX]
        values = [f"กล้อง {i}" for i in cams]
        self.camera_combo.configure(values=values)

        saved = database.get_setting("camera_index", str(config.CAMERA_INDEX))
        try:
            saved_idx = int(saved)
        except (TypeError, ValueError):
            saved_idx = config.CAMERA_INDEX
        default_label = f"กล้อง {saved_idx}" if saved_idx in cams else values[0]
        self.camera_combo.set(default_label)

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

            self.worker = detector_worker.AttendanceWorker(
                camera=self.camera, engine=self.app.engine,
                matcher=self.app.matcher, event_id=event_id, scan_type=scan_type,
            ).start()

            self.btn_start.configure(text="■  หยุดเช็คชื่อ", fg_color=DANGER_COLOR, hover_color="#8B0000")
            self.event_combo.configure(state="disabled")
            self.scan_mode_combo.configure(state="disabled")
            scan_label = "สแกนเข้า" if scan_type == "in" else "สแกนออก"
            self.lbl_status.configure(text=f"● กำลังทำงาน — โหมด: {scan_label}", text_color=SUCCESS_COLOR)
            self._scan_count = 0
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
        self.btn_start.configure(text="▶  เริ่มเช็คชื่อ", fg_color=SUCCESS_COLOR, hover_color="#1B5E20")
        self.event_combo.configure(state="readonly")
        self.scan_mode_combo.configure(state="readonly")
        self.video_label.configure(image=None, text="กล้องยังไม่เปิด\n\nกรุณาเลือกกิจกรรมและกดเริ่มเช็คชื่อ")
        self.lbl_status.configure(text="")
        self.lbl_last_scan.place_forget()

    def _current_event_id(self):
        label = self.event_combo.get()
        return self._events_by_label.get(label)

    def _refresh_display(self):
        """
        ลูปนี้รันบน GUI thread ทุก ~30ms
        ดึง 'ภาพกล้องสดล่าสุด' มาแสดงเสมอ (ลื่นเท่าความเร็วกล้องจริง ไม่รอ AI)
        แล้วซ้อนกรอบ/ชื่อจากผลลัพธ์ AI ล่าสุดที่ worker คำนวณไว้ทับลงไป
        """
        if self.worker is None:
            return

        frame = self.camera.read() if self.camera else None
        if frame is not None:
            for f in self.worker.get_latest_faces():
                status = f.get("scan_result", "ok")
                face_engine.draw_face_box(frame, f["bbox"], f["label"], color=f["color"], status=status)

            img = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            img = cv2.resize(img, (636, 464))
            imgtk = ImageTk.PhotoImage(image=Image.fromarray(img))
            self.video_label.imgtk = imgtk
            self.video_label.configure(image=imgtk, text="")

        # ดึงผลลัพธ์จาก worker queue
        new_names = []
        while True:
            try:
                result = self.worker.checkin_queue.get_nowait()
                # รองรับทั้ง tuple 3 และ 4 elements (backward compatibility)
                if len(result) == 4:
                    student, score, scan_type, result_type = result
                else:
                    student, score, scan_type = result
                    result_type = "success"

                # ข้าม camera error notifications
                if student is None:
                    if result_type == "camera_error":
                        self.lbl_status.configure(text="⚠ ปัญหากล้อง — กำลัง retry...", text_color=WARNING_COLOR)
                    continue

                self._add_log_row(student, score, scan_type)
                scan_label = "เข้า" if scan_type == "in" else "ออก"
                new_names.append(f"{student['full_name']} ({scan_label})")
                self._scan_count += 1
            except Exception:
                break

        if new_names:
            last_name = new_names[-1]
            self.lbl_status.configure(text=f"✓ สแกนล่าสุด: {last_name}", text_color=SUCCESS_COLOR)
            self.lbl_scan_count.configure(text=f"สแกนแล้ว {self._scan_count} คน")

            # Show overlay toast on video
            self.lbl_last_scan.configure(text=f"  ✓ {last_name}  ")
            self.lbl_last_scan.place(relx=0.5, y=50, anchor="center")
            self.after(2000, lambda: self.lbl_last_scan.place_forget())

            self.app.toast.show(f"✓ {last_name}", "success", duration=2000)

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
            tags=(tag, "scan_success"),
        )


# ============================================================================
# Tab 4: รายงาน
# ============================================================================

class ReportTab(ctk.CTkFrame):
    PCT_HIGH = 80
    PCT_MID = 50
    BAR_LEN = 16
    DEPT_ALL = "ทั้งหมด"

    def __init__(self, parent, app):
        super().__init__(parent, fg_color="transparent")
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
        # แถวเลือกกิจกรรม
        top = ctk.CTkFrame(self, corner_radius=12)
        top.pack(fill="x", padx=15, pady=(15, 8))

        controls = ctk.CTkFrame(top, fg_color="transparent")
        controls.pack(fill="x", padx=15, pady=10)

        ctk.CTkLabel(controls, text="กิจกรรม:", font=FONT_BOLD).pack(side="left")
        self.event_combo = ctk.CTkComboBox(controls, state="readonly", width=300, values=[],
                                            command=lambda v: self._load_report())
        self.event_combo.pack(side="left", padx=(4, 12))

        ctk.CTkButton(
            controls, text="🔄 โหลดรายงาน",
            fg_color="transparent", border_width=1, text_color=PRIMARY_COLOR,
            height=34, command=self._load_report,
        ).pack(side="left", padx=4)
        ctk.CTkButton(
            controls, text="⬇ ส่งออก Excel (พร้อมกราฟ)",
            font=FONT_BOLD, fg_color=PRIMARY_COLOR, hover_color=PRIMARY_DARK,
            height=34, command=self._export,
        ).pack(side="left", padx=4)

        # Stat Cards
        cards_row = ctk.CTkFrame(self, fg_color="transparent")
        cards_row.pack(fill="x", padx=15, pady=(0, 4))
        self.card_total = self._make_stat_card(cards_row, "นักเรียนทั้งหมด", "👥", PRIMARY_COLOR)
        self.card_attended = self._make_stat_card(cards_row, "เข้าร่วมกิจกรรม", "✅", SUCCESS_COLOR)
        self.card_not_attended = self._make_stat_card(cards_row, "ไม่เข้าร่วมกิจกรรม", "❌", DANGER_COLOR)

        self.lbl_summary_note = ctk.CTkLabel(
            self,
            text='เงื่อนไข: นับเป็น "เข้าร่วมกิจกรรม" เฉพาะผู้ที่มีทั้งสแกนเข้าและสแกนออกเท่านั้น',
            font=FONT_SMALL, text_color=MUTED_COLOR,
        )
        self.lbl_summary_note.pack(anchor="w", padx=20, pady=(4, 0))

        # แถบกรองสาขา
        filter_row = ctk.CTkFrame(self, fg_color="transparent")
        filter_row.pack(fill="x", padx=15, pady=(6, 0))
        ctk.CTkLabel(filter_row, text="กรองตามสาขา:", font=FONT_BOLD).pack(side="left")
        self.dept_filter_combo = ctk.CTkComboBox(filter_row, state="readonly", width=220, values=["ทั้งหมด"],
                                                   command=lambda v: self._apply_department_filter())
        self.dept_filter_combo.pack(side="left", padx=(4, 8))
        self.dept_filter_combo.set("ทั้งหมด")
        ctk.CTkButton(
            filter_row, text="✕ ล้างตัวกรอง", width=100, height=28,
            fg_color="transparent", border_width=1, text_color=MUTED_COLOR,
            command=self._clear_department_filter,
        ).pack(side="left")
        self.lbl_filter_status = ctk.CTkLabel(filter_row, text="", font=FONT_SMALL, text_color=MUTED_COLOR)
        self.lbl_filter_status.pack(side="left", padx=10)

        # Notebook sub-tabs
        self.notebook = ttk.Notebook(self)
        self.notebook.pack(fill="both", expand=True, padx=15, pady=(6, 15))

        # Tab: กราฟ
        self.chart_frame = ctk.CTkFrame(self.notebook, fg_color="transparent")
        self.notebook.add(self.chart_frame, text="  📊  สรุปภาพรวม  ")

        # Tab: แยกตามสาขา
        self._build_department_tab(self.notebook)

        # Tab: เข้าร่วม
        present_frame = ctk.CTkFrame(self.notebook, fg_color="transparent")
        self.notebook.add(present_frame, text="  ✅  เข้าร่วมกิจกรรม  ")
        self._present_tab_index = self.notebook.index("end") - 1
        columns = ("time_in", "time_out", "code", "name", "class", "dept", "score")
        self.present_tree = ttk.Treeview(present_frame, columns=columns, show="headings",
                                          style="Enterprise.Treeview", height=16)
        for col, text, w in [
            ("time_in", "เวลาสแกนเข้า", 120), ("time_out", "เวลาสแกนออก", 120), ("code", "รหัส", 90),
            ("name", "ชื่อ-สกุล", 200), ("class", "ห้อง", 90), ("dept", "สาขา", 140), ("score", "ความมั่นใจ", 80),
        ]:
            self.present_tree.heading(col, text=text)
            self.present_tree.column(col, width=w)
        self.present_tree.tag_configure("attended", foreground="#2E7D32")
        self.present_tree.pack(fill="both", expand=True, padx=5, pady=5)

        # Tab: ไม่เข้าร่วม
        absent_frame = ctk.CTkFrame(self.notebook, fg_color="transparent")
        self.notebook.add(absent_frame, text="  ❌  ไม่เข้าร่วมกิจกรรม  ")
        columns2 = ("code", "name", "class", "dept", "note")
        self.absent_tree = ttk.Treeview(absent_frame, columns=columns2, show="headings",
                                         style="Enterprise.Treeview", height=16)
        for col, text, w in [
            ("code", "รหัส", 90), ("name", "ชื่อ-สกุล", 200),
            ("class", "ห้อง", 90), ("dept", "สาขา", 140), ("note", "หมายเหตุ", 180),
        ]:
            self.absent_tree.heading(col, text=text)
            self.absent_tree.column(col, width=w)
        self.absent_tree.tag_configure("not_attended", foreground="#C62828")
        self.absent_tree.pack(fill="both", expand=True, padx=5, pady=5)

    def _make_stat_card(self, parent, title, icon, color):
        """การ์ดตัวเลขสรุปแบบ Modern"""
        card = ctk.CTkFrame(parent, corner_radius=12)
        card.pack(side="left", padx=(0, 10), fill="both", expand=True, pady=4)

        inner = ctk.CTkFrame(card, fg_color="transparent")
        inner.pack(fill="both", expand=True, padx=16, pady=12)

        header_row = ctk.CTkFrame(inner, fg_color="transparent")
        header_row.pack(fill="x")
        ctk.CTkLabel(header_row, text=icon, font=(FONT_FAMILY, 20)).pack(side="left")
        ctk.CTkLabel(header_row, text=title, font=FONT_SMALL, text_color=MUTED_COLOR).pack(side="left", padx=(6, 0))

        lbl_value = ctk.CTkLabel(inner, text="0", font=FONT_BIG_NUM, text_color=color, anchor="w")
        lbl_value.pack(fill="x", pady=(4, 0))
        lbl_pct = ctk.CTkLabel(inner, text="", font=FONT_BOLD, text_color=color, anchor="w")
        lbl_pct.pack(fill="x")

        return {"value": lbl_value, "pct": lbl_pct}

    def _build_department_tab(self, notebook):
        dept_frame = ctk.CTkFrame(notebook, fg_color="transparent")
        notebook.add(dept_frame, text="  🏫  แยกตามสาขา (%)  ")
        self._dept_tab_index = notebook.index("end") - 1

        ctk.CTkLabel(
            dept_frame,
            text="คลิกหัวคอลัมน์เพื่อจัดเรียง • ดับเบิลคลิกแถวเพื่อกรองรายชื่อเฉพาะสาขานั้น",
            font=FONT_SMALL, text_color=MUTED_COLOR,
        ).pack(anchor="w", padx=8, pady=(8, 4))

        columns = ("dept", "attended", "not_attended", "total", "pct_bar")
        self.dept_tree = ttk.Treeview(dept_frame, columns=columns, show="headings",
                                       style="Enterprise.Treeview", height=16)
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
        values = list(self._events_by_label.keys())
        self.event_combo.configure(values=values)
        if values:
            self.event_combo.set(values[0])
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

        self.card_total["value"].configure(text=str(total))
        self.card_total["pct"].configure(text="คน")

        self.card_attended["value"].configure(text=str(summary["attended"]))
        self.card_attended["pct"].configure(text=f"{pct_attended:.1f}%")

        self.card_not_attended["value"].configure(text=str(summary["not_attended"]))
        self.card_not_attended["pct"].configure(text=f"{pct_not_attended:.1f}%")

    # ------------------------------------------------------- แท็บแยกตามสาขา

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
            self._dept_sort_reverse = True
        self._render_department_tree_sorted()

    def _on_department_row_double_click(self, event):
        item = self.dept_tree.identify_row(event.y)
        if not item:
            return
        values = list(self.dept_filter_combo.cget("values") if hasattr(self.dept_filter_combo, 'cget') else [])
        if not values:
            try:
                values = self.dept_filter_combo._values
            except Exception:
                values = []
        if item in values:
            self.dept_filter_combo.set(item)
            self._apply_department_filter()
            self.notebook.select(self._present_tab_index)

    def _refresh_department_filter_options(self, by_department):
        values = [self.DEPT_ALL] + sorted(by_department.keys())
        current = self.dept_filter_combo.get()
        self.dept_filter_combo.configure(values=values)
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
            self.lbl_filter_status.configure(text="")
        else:
            self.lbl_filter_status.configure(
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
            ctk.CTkLabel(
                self.chart_frame, text=f"ไม่สามารถแสดงกราฟได้: {e}",
                text_color=MUTED_COLOR,
            ).pack(padx=20, pady=20)

    def _export(self):
        event_id, label = self._current_event()
        if event_id is None:
            messagebox.showwarning("ยังไม่ได้เลือกกิจกรรม", "กรุณาเลือกกิจกรรมก่อน")
            return
        event_name = label.split(" (")[0]
        path = export_utils.export_attendance_report(event_id, event_name)
        messagebox.showinfo("ส่งออกสำเร็จ", f"บันทึกไฟล์แล้วที่:\n{path}")
        self.app.toast.show("ส่งออก Excel สำเร็จ ✓", "success")


# ============================================================================
# Main Application — Enterprise Edition
# ============================================================================

class App(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("ระบบเช็คชื่อเข้าร่วมกิจกรรมด้วยใบหน้า — วิทยาลัยการอาชีพจอมทอง")
        self.geometry("1360x850")
        self.minsize(1200, 720)

        # ตั้งค่า CustomTkinter
        ctk.set_appearance_mode("light")
        ctk.set_default_color_theme("blue")

        database.init_db()

        self.engine = None
        self.matcher = None

        # Setup Treeview styles (ttk ยังใช้อยู่สำหรับ Treeview)
        self._setup_treeview_style()

        # Layout: Sidebar (ซ้าย) + Content (ขวา)
        self.sidebar = Sidebar(self, self)
        self.sidebar.pack(side="left", fill="y")

        # Content area
        self.content_area = ctk.CTkFrame(self, fg_color="transparent", corner_radius=0)
        self.content_area.pack(side="left", fill="both", expand=True)

        # Toast notification manager
        self.toast = ToastManager(self.content_area)

        # สร้าง pages (frames)
        self.student_tab = StudentTab(self.content_area, self)
        self.event_tab = EventTab(self.content_area, self)
        self.attendance_tab = AttendanceTab(self.content_area, self)
        self.report_tab = ReportTab(self.content_area, self)

        self.pages = [self.student_tab, self.event_tab, self.attendance_tab, self.report_tab]
        self.show_page(0)

        # Status bar
        self.status_bar = ctk.CTkFrame(self.content_area, height=32, corner_radius=0, fg_color=("gray92", "gray18"))
        self.status_bar.pack(side="bottom", fill="x")
        self.status_bar.pack_propagate(False)

        self.lbl_model_status = ctk.CTkLabel(
            self.status_bar, text="  ⏳ กำลังโหลดโมเดลจดจำใบหน้า กรุณารอสักครู่...",
            font=FONT_SMALL, text_color=WARNING_COLOR,
        )
        self.lbl_model_status.pack(side="left", padx=8)

        self.lbl_clock = ctk.CTkLabel(self.status_bar, text="", font=FONT_SMALL, text_color=MUTED_COLOR)
        self.lbl_clock.pack(side="right", padx=8)
        self._update_clock()

        # Menu bar
        self._build_menu()

        # Keyboard shortcuts
        self.bind("<F5>", lambda e: self._refresh_current())
        self.bind("<Control-b>", lambda e: self._backup_database())
        self.bind("<Control-e>", lambda e: self.report_tab._export())

        self.protocol("WM_DELETE_WINDOW", self._on_close)

        # โหลดโมเดลใน background
        ModelLoader(self._on_model_ready, self._on_model_error).start()

    def _setup_treeview_style(self):
        style = ttk.Style()
        try:
            style.theme_use("vista")
        except tk.TclError:
            try:
                style.theme_use("clam")
            except tk.TclError:
                pass

        base_font = (FONT_FAMILY, 10)
        style.configure("Enterprise.Treeview", rowheight=28, font=base_font)
        style.configure("Enterprise.Treeview.Heading", font=(FONT_FAMILY, 10, "bold"))

    def show_page(self, index):
        for page in self.pages:
            page.pack_forget()
        self.pages[index].pack(fill="both", expand=True)

    def _build_menu(self):
        menubar = tk.Menu(self)
        file_menu = tk.Menu(menubar, tearoff=0)
        file_menu.add_command(label="สำรองข้อมูล (Backup)...  Ctrl+B", command=self._backup_database)
        file_menu.add_command(label="กู้คืนข้อมูลจากไฟล์สำรอง (Restore)...", command=self._restore_database)
        file_menu.add_separator()
        file_menu.add_command(label="ออกจากโปรแกรม", command=self._on_close)
        menubar.add_cascade(label="ไฟล์", menu=file_menu)

        help_menu = tk.Menu(menubar, tearoff=0)
        help_menu.add_command(label=f"เกี่ยวกับ (v{APP_VERSION})", command=self._show_about)
        menubar.add_cascade(label="ช่วยเหลือ", menu=help_menu)

        self.config(menu=menubar)

    def _show_about(self):
        messagebox.showinfo(
            "เกี่ยวกับระบบ",
            f"ระบบเช็คชื่อเข้าร่วมกิจกรรมด้วยใบหน้า\n"
            f"Enterprise Edition v{APP_VERSION}\n\n"
            f"เทคโนโลยี: InsightFace + ONNX Runtime\n"
            f"UI Framework: CustomTkinter\n\n"
            f"วิทยาลัยการอาชีพจอมทอง"
        )

    def _update_clock(self):
        now = datetime.datetime.now().strftime("%d/%m/%Y  %H:%M:%S")
        self.lbl_clock.configure(text=now)
        self.after(1000, self._update_clock)

    def _refresh_current(self):
        """F5 — รีเฟรชหน้าปัจจุบัน"""
        idx = self.sidebar.active_index
        if idx == 0:
            self.student_tab._refresh_student_list()
        elif idx == 1:
            self.event_tab._refresh()
        elif idx == 3:
            self.report_tab._load_report()
        self.toast.show("รีเฟรชข้อมูลแล้ว", "info", duration=1500)

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
        self.toast.show("สำรองข้อมูลสำเร็จ ✓", "success")

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
        self.toast.show("กู้คืนข้อมูลสำเร็จ ✓", "success")

    def _on_model_ready(self, engine):
        self.engine = engine
        self.refresh_matcher()
        self.lbl_model_status.configure(
            text="  ✓ โมเดลพร้อมใช้งาน", text_color=SUCCESS_COLOR
        )
        self.toast.show("โหลดโมเดล AI สำเร็จ — พร้อมสแกนใบหน้า", "success", duration=4000)

    def _on_model_error(self, err):
        self.lbl_model_status.configure(
            text=f"  ✗ โหลดโมเดลล้มเหลว: {err}", text_color=DANGER_COLOR
        )
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