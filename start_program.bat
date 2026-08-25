@echo off
REM ===============================================================
REM  เปิดระบบเช็คชื่อเข้าร่วมกิจกรรมด้วยใบหน้า
REM  ดับเบิลคลิกไฟล์นี้ (หรือ shortcut ที่ชี้มาที่ไฟล์นี้) เพื่อเปิดโปรแกรม
REM ===============================================================

REM เข้าไปที่โฟลเดอร์ที่ไฟล์ .bat นี้อยู่จริง (กันปัญหา path ผิดถ้าเรียกจาก shortcut)
cd /d "%~dp0"

if not exist "venv\Scripts\activate.bat" (
    echo [ผิดพลาด] ไม่พบ venv กรุณาติดตั้งตามขั้นตอนใน README.md ก่อน
    echo ^(รันคำสั่ง: python -m venv venv  แล้ว  pip install -r requirements.txt^)
    pause
    exit /b 1
)

call venv\Scripts\activate.bat
python main.py

REM ถ้าโปรแกรมปิดตัวเพราะ error (ไม่ใช่ปิดหน้าต่างปกติ) ให้ค้างหน้าต่างไว้ให้อ่าน error ได้
if errorlevel 1 (
    echo.
    echo เกิดข้อผิดพลาด กรุณาอ่านข้อความด้านบน หรือส่งภาพหน้าจอนี้ไปสอบถามเพิ่มเติม
    pause
)
