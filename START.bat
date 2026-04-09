@echo off
title He Thong Gui SMS Tu Dong
echo ==========================================
echo DANG KHOI DONG PHAN MEM SMS MARKETING...
echo Vui long doi trong giay lat!
echo ==========================================

:: Kich hoat moi truong ao cho CMD (Dung .bat thay vi .ps1)
call .venv\Scripts\activate.bat

:: Chay ung dung
streamlit run app.py --browser.gatherUsageStats=false

pause