@echo off
chcp 65001 >nul
title Build SMS Marketing Pro — PyInstaller (onedir)
echo ============================================
echo   Dang build SMS Marketing Pro (onedir)
echo ============================================
echo.

REM Don dep moi truong cu (Clean Build)
echo [0/3] Don dep thu muc build cu...
if exist "build" rmdir /s /q "build"
if exist "dist\SMS_Marketing_Pro" rmdir /s /q "dist\SMS_Marketing_Pro"
echo     Da don dep xong.
echo.

REM Kiem tra PyInstaller
pip show pyinstaller >nul 2>&1
if errorlevel 1 (
    echo [!] Chua cai PyInstaller. Dang cai dat...
    pip install pyinstaller
)

echo.
echo [1/3] Tim duong dan streamlit/static...
echo.

REM Lay duong dan site-packages tu Python
for /f "delims=" %%i in ('python -c "import streamlit, os; print(os.path.dirname(streamlit.__file__))"') do set STREAMLIT_PATH=%%i

if "%STREAMLIT_PATH%"=="" (
    echo [LOI] Khong tim thay thu vien Streamlit. Hay chay: pip install streamlit
    pause
    exit /b 1
)

echo     Streamlit path: %STREAMLIT_PATH%
echo.

echo [2/3] Dang chay PyInstaller...
echo.

pyinstaller --noconfirm --onedir --console ^
    --name "SMS_Marketing_Pro" ^
    --add-data "app.py;." ^
    --add-data "database.py;." ^
    --add-data "gateway.py;." ^
    --add-data "utils.py;." ^
    --add-data "update_manager.py;." ^
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
    --hidden-import importlib_metadata ^
    --collect-all streamlit ^
    --copy-metadata streamlit ^
    --copy-metadata importlib_metadata ^
    run_app.py

echo.
echo [3/3] Kiem tra ket qua...
echo.

if exist "dist\SMS_Marketing_Pro\SMS_Marketing_Pro.exe" (
    REM Copy file requirements.txt va database neu co
    copy /Y requirements.txt "dist\SMS_Marketing_Pro\" >nul 2>nul
    if exist app_data.db copy /Y app_data.db "dist\SMS_Marketing_Pro\" >nul

    echo.
    echo ============================================
    echo   BUILD THANH CONG!
    echo.
    echo   Thu muc: dist\SMS_Marketing_Pro\
    echo   File:    dist\SMS_Marketing_Pro\SMS_Marketing_Pro.exe
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
