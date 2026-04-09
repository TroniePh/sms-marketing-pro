@echo off
chcp 65001 >nul
title SMS Marketing Pro — Cài đặt tự động
color 0A
echo.
echo  ╔══════════════════════════════════════════════╗
echo  ║   SMS MARKETING PRO — CÀI ĐẶT TỰ ĐỘNG     ║
echo  ║   Phát triển bởi: Phạm Duy                  ║
echo  ╚══════════════════════════════════════════════╝
echo.

cd /d "%~dp0"

REM ── Bước 1: Kiểm tra Python ──────────────────────
echo [1/4] Kiểm tra Python...
python --version >nul 2>&1
if errorlevel 1 (
    py --version >nul 2>&1
    if errorlevel 1 (
        echo.
        echo  [LOI] Khong tim thay Python tren may tinh nay!
        echo  Vui long cai dat Python 3.10+ tu: https://www.python.org/downloads/
        echo  QUAN TRONG: Tick chon "Add Python to PATH" khi cai dat.
        echo.
        start https://www.python.org/downloads/
        pause
        exit /b 1
    ) else (
        set PYTHON_CMD=py
    )
) else (
    set PYTHON_CMD=python
)

echo     Python OK: 
%PYTHON_CMD% --version
echo.

REM ── Bước 2: Tạo môi trường ảo ────────────────────
echo [2/4] Tạo môi trường ảo (venv)...
if not exist "venv" (
    %PYTHON_CMD% -m venv venv
    if errorlevel 1 (
        echo  [LOI] Khong the tao moi truong ao. Kiem tra Python.
        pause
        exit /b 1
    )
    echo     Đã tạo venv mới.
) else (
    echo     venv đã tồn tại, bỏ qua.
)
echo.

REM ── Bước 3: Cài đặt thư viện ─────────────────────
echo [3/4] Cài đặt thư viện (pip install)...
call venv\Scripts\activate.bat

pip install --upgrade pip >nul 2>&1

if exist requirements.txt (
    pip install -r requirements.txt
) else (
    echo  [!] Khong tim thay requirements.txt, cai thu cong...
    pip install streamlit pandas openpyxl requests
)

if errorlevel 1 (
    echo.
    echo  [LOI] Cài đặt thư viện thất bại. Kiểm tra kết nối mạng.
    pause
    exit /b 1
)
echo.
echo     Cài đặt thư viện thành công!
echo.

REM ── Bước 4: Khởi động ứng dụng ───────────────────
echo [4/4] Khởi động SMS Marketing Pro...
echo.
echo  ╔══════════════════════════════════════════════╗
echo  ║  Ứng dụng sẽ mở trên trình duyệt tại:      ║
echo  ║  http://localhost:8501                       ║
echo  ║                                              ║
echo  ║  Nhấn Ctrl+C tại cửa sổ này để tắt.         ║
echo  ╚══════════════════════════════════════════════╝
echo.

start http://localhost:8501
streamlit run app.py --server.port=8501 --browser.gatherUsageStats=false

call venv\Scripts\deactivate.bat
pause
