@echo off
title MaeWang SmartPay - Print Server
chcp 65001 >nul
cd /d "%~dp0"
echo ============================================
echo    MaeWang SmartPay  -  Print Server
echo    ปิดหน้าต่างนี้เพื่อหยุด server
echo ============================================
echo.

set "PYEXE="
for %%P in (py python python3) do (
  if not defined PYEXE (
    where %%P >nul 2>nul && set "PYEXE=%%P"
  )
)

if not defined PYEXE (
  echo [ERROR] ไม่พบ Python บนเครื่องนี้
  echo   1^) ติดตั้ง Python 3: https://www.python.org/downloads/windows/
  echo      ^(ตอนติดตั้ง ให้ติ๊ก "Add Python to PATH"^)
  echo   2^) ดับเบิลคลิก setup.bat หนึ่งครั้งเพื่อลง library
  echo.
  pause
  exit /b 1
)

echo ใช้ Python: %PYEXE%
echo.
%PYEXE% tsc_te310_print_server.py

echo.
echo === print server หยุดทำงานแล้ว ===
pause
