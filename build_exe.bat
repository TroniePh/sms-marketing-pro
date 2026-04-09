@echo off
chcp 65001 >nul
title Build SMS Marketing Pro — PyArmor + PyInstaller
echo ============================================
echo   SMS Marketing Pro — Build Pipeline
echo   PyArmor (ma hoa) + PyInstaller (dong goi)
echo ============================================
echo.

REM ── Kich hoat moi truong ao (neu co) ────────────
if exist ".venv\Scripts\activate.bat" (
    echo     Kich hoat .venv...
    call .venv\Scripts\activate.bat
) else if exist "venv\Scripts\activate.bat" (
    echo     Kich hoat venv...
    call venv\Scripts\activate.bat
)

REM ── Tim Python ──────────────────────────────────
set PYTHON_CMD=
where python >nul 2>&1 && set PYTHON_CMD=python
if "%PYTHON_CMD%"=="" (where py >nul 2>&1 && set PYTHON_CMD=py)
if "%PYTHON_CMD%"=="" (
    echo [LOI] Khong tim thay Python. Hay cai dat Python va them vao PATH.
    pause
    exit /b 1
)
echo     Python: %PYTHON_CMD%
%PYTHON_CMD% --version
echo.

REM ── Buoc 0: Don dep moi truong cu ──────────────
echo [0/4] Don dep thu muc build cu...
if exist "build" rmdir /s /q "build"
if exist "dist\SMS_Marketing_Pro" rmdir /s /q "dist\SMS_Marketing_Pro"
if exist "obfuscated" rmdir /s /q "obfuscated"
echo     Da don dep xong.
echo.

REM ── Kiem tra PyArmor va PyInstaller ─────────────
pyarmor --version >nul 2>&1
if errorlevel 1 (
    echo [!] Chua cai PyArmor. Dang cai dat...
    %PYTHON_CMD% -m pip install pyarmor
)

%PYTHON_CMD% -m PyInstaller --version >nul 2>&1
if errorlevel 1 (
    echo [!] Chua cai PyInstaller. Dang cai dat...
    %PYTHON_CMD% -m pip install pyinstaller
)
echo.

REM ── Buoc 1: Ma hoa source code bang PyArmor ────
echo [1/4] Ma hoa source code bang PyArmor...
echo.

pyarmor gen -O obfuscated app.py database.py gateway.py utils.py update_manager.py

if not exist "obfuscated\app.py" (
    echo [LOI] PyArmor ma hoa that bai. Kiem tra log phia tren.
    pause
    exit /b 1
)

echo.
echo     Ma hoa thanh cong! Thu muc: obfuscated\
echo.

REM ── Buoc 2: Tim duong dan streamlit/static ─────
echo [2/4] Tim duong dan streamlit/static...
echo.

for /f "tokens=*" %%i in ('%PYTHON_CMD% -c "import streamlit; print(streamlit.__path__[0])"') do set STREAMLIT_PATH=%%i

if "%STREAMLIT_PATH%"=="" (
    echo [LOI] Khong tim thay thu vien Streamlit. Hay chay: %PYTHON_CMD% -m pip install streamlit
    pause
    exit /b 1
)
echo     Streamlit path: %STREAMLIT_PATH%
echo.

REM ── Tim thu muc pyarmor_runtime sinh ra ─────────
set PYARMOR_RUNTIME=
set PYARMOR_RUNTIME_NAME=
for /d %%d in (obfuscated\pyarmor_runtime_*) do (
    set PYARMOR_RUNTIME=%%d
    set PYARMOR_RUNTIME_NAME=%%~nxd
)

if "%PYARMOR_RUNTIME%"=="" (
    echo [CANH BAO] Khong tim thay pyarmor_runtime trong obfuscated\.
) else (
    echo     PyArmor runtime dir:  %PYARMOR_RUNTIME%
    echo     PyArmor runtime name: %PYARMOR_RUNTIME_NAME%
)
echo.

REM ── Buoc 3: Dong goi bang PyInstaller ───────────
echo [3/4] Dang chay PyInstaller (dung file da ma hoa)...
echo.

pyinstaller --noconfirm --onedir --console ^
    --name "SMS_Marketing_Pro" ^
    --add-data "obfuscated\app.py;." ^
    --add-data "obfuscated\database.py;." ^
    --add-data "obfuscated\gateway.py;." ^
    --add-data "obfuscated\utils.py;." ^
    --add-data "obfuscated\update_manager.py;." ^
    --add-data "%PYARMOR_RUNTIME%\*;%PYARMOR_RUNTIME_NAME%" ^
    --add-data "%STREAMLIT_PATH%\static;streamlit/static" ^
    --hidden-import streamlit ^
    --hidden-import streamlit.web.cli ^
    --hidden-import streamlit.runtime.scriptrunner ^
    --hidden-import streamlit.runtime.scriptrunner.magic_funcs ^
    --hidden-import pandas ^
    --hidden-import openpyxl ^
    --hidden-import sqlite3 ^
    --hidden-import requests ^
    --hidden-import PIL ^
    --hidden-import altair ^
    --hidden-import jinja2 ^
    --hidden-import markupsafe ^
    --hidden-import toml ^
    --hidden-import pyarrow ^
    --hidden-import packaging ^
    --collect-all streamlit ^
    --copy-metadata streamlit ^
    run_app.py

echo.
echo [4/4] Kiem tra ket qua...
echo.

if exist "dist\SMS_Marketing_Pro\SMS_Marketing_Pro.exe" (
    copy /Y requirements.txt "dist\SMS_Marketing_Pro\" >nul 2>nul

    echo.
    echo ============================================
    echo   BUILD THANH CONG! (Source da ma hoa)
    echo.
    echo   Thu muc: dist\SMS_Marketing_Pro\
    echo   File:    dist\SMS_Marketing_Pro\SMS_Marketing_Pro.exe
    echo.
    echo   Cac file .py trong ban build da duoc
    echo   ma hoa boi PyArmor, khong the doc duoc.
    echo.
    echo   Hay copy CA THU MUC dist\SMS_Marketing_Pro\
    echo   de chia se cho nguoi dung khac.
    echo ============================================
) else (
    echo.
    echo [LOI] Build that bai. Kiem tra log phia tren.
)

echo.
pause
