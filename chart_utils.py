# -*- coding: utf-8 -*-
"""
chart_utils.py
สร้างกราฟสรุปผลการเข้าร่วมกิจกรรม (matplotlib) สำหรับฝังในแท็บรายงาน
"""

import matplotlib
matplotlib.use("TkAgg")
import matplotlib.pyplot as plt

# ใช้ Tahoma เพราะรองรับภาษาไทยและมีอยู่ในทุกเครื่อง Windows โดยไม่ต้องติดตั้งฟอนต์เพิ่ม
matplotlib.rcParams["font.family"] = ["Tahoma", "Leelawadee UI", "TH Sarabun New", "sans-serif"]
matplotlib.rcParams["axes.unicode_minus"] = False

COLOR_ATTENDED = "#2E7D32"     # เขียว
COLOR_NOT_ATTENDED = "#C62828"  # แดง
COLOR_BG = "#FFFFFF"


def _draw_breakdown_bar(ax, breakdown: dict, title: str, empty_text: str):
    """วาดกราฟแท่งแนวนอนสรุปเข้าร่วม/ไม่เข้าร่วม แยกตาม key ของ breakdown (ใช้ซ้ำได้ทั้งแยกตามห้อง/สาขา)"""
    if not breakdown:
        ax.text(0.5, 0.5, empty_text, ha="center", va="center", fontsize=11)
        ax.axis("off")
        return

    keys = list(breakdown.keys())
    attended_counts = [breakdown[k]["attended"] for k in keys]
    not_attended_counts = [breakdown[k]["not_attended"] for k in keys]

    y_pos = range(len(keys))
    ax.barh(y_pos, attended_counts, color=COLOR_ATTENDED, label="เข้าร่วมกิจกรรม")
    ax.barh(y_pos, not_attended_counts, left=attended_counts, color=COLOR_NOT_ATTENDED, label="ไม่เข้าร่วมกิจกรรม")
    ax.set_yticks(list(y_pos))
    ax.set_yticklabels(keys, fontsize=9)
    ax.invert_yaxis()
    ax.set_xlabel("จำนวนคน", fontsize=9)
    ax.set_title(title, fontsize=12, pad=14)
    ax.legend(loc="lower right", fontsize=7, framealpha=0.9)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)


def build_summary_figure(summary, event_name=""):
    """
    สร้าง matplotlib Figure สรุปผลการเข้าร่วมกิจกรรม 3 ส่วน:
      1) กราฟวงกลมโดนัท เข้าร่วม / ไม่เข้าร่วม
      2) กราฟแท่งแนวนอน จำนวนแยกตามห้อง/กลุ่มเรียน
      3) กราฟแท่งแนวนอน จำนวนแยกตามสาขา
    summary มาจาก database.get_attendance_summary(event_id)
    """
    fig = plt.Figure(figsize=(13, 4.8), dpi=100, facecolor=COLOR_BG)

    # --- 1) กราฟวงกลมโดนัท ---
    ax1 = fig.add_subplot(1, 3, 1)
    attended = summary["attended"]
    not_attended = summary["not_attended"]
    total = summary["total"]

    if total == 0:
        ax1.text(0.5, 0.5, "ยังไม่มีข้อมูลนักเรียน", ha="center", va="center", fontsize=12)
        ax1.axis("off")
    else:
        values = [attended, not_attended]
        labels = [f"เข้าร่วมกิจกรรม\n{attended} คน", f"ไม่เข้าร่วมกิจกรรม\n{not_attended} คน"]
        colors = [COLOR_ATTENDED, COLOR_NOT_ATTENDED]
        # ซ่อน label ของค่าที่เป็น 0 กันข้อความทับกัน
        display_labels = [lab if val > 0 else "" for lab, val in zip(labels, values)]

        wedges, _texts, autotexts = ax1.pie(
            values,
            labels=display_labels,
            colors=colors,
            autopct=lambda pct: f"{pct:.0f}%" if pct > 0 else "",
            startangle=90,
            pctdistance=0.78,
            wedgeprops=dict(width=0.42, edgecolor="white", linewidth=2),
            textprops=dict(fontsize=9),
        )
        for t in autotexts:
            t.set_color("white")
            t.set_fontweight("bold")
        ax1.text(0, 0, f"{total}\nคนทั้งหมด", ha="center", va="center", fontsize=11, fontweight="bold")
        ax1.set_title(f"สรุปภาพรวม{(' — ' + event_name) if event_name else ''}", fontsize=11, pad=14)

    # --- 2) กราฟแท่งแนวนอนแยกตามห้อง ---
    ax2 = fig.add_subplot(1, 3, 2)
    _draw_breakdown_bar(ax2, summary.get("by_room", {}), "แยกตามห้อง/กลุ่มเรียน", "ไม่มีข้อมูลห้อง")

    # --- 3) กราฟแท่งแนวนอนแยกตามสาขา ---
    ax3 = fig.add_subplot(1, 3, 3)
    _draw_breakdown_bar(ax3, summary.get("by_department", {}), "แยกตามสาขา", "ไม่มีข้อมูลสาขา")

    fig.tight_layout()
    return fig
