@echo off
title MaeWang SmartPay - Setup
chcp 65001 >nul
cd /d "%~dp0"
echo ============================================
echo    ติดตั้ง library ที่ print server ต้องใช้
echo ============================================
echo.

set "PYEXE="
for %%P in (py python python3) do (
  if not defined PYEXE (
    where %%P >nul 2>nul && set "PYEXE=%%P"
  )
)

if not defined PYEXE (
  echo [ERROR] ไม่พบ Python — ติดตั้งก่อนที่:
  echo   https://www.python.org/downloads/windows/
  echo   ^(ตอนติดตั้ง ให้ติ๊ก "Add Python to PATH"^)
  echo.
  pause
  exit /b 1
)

echo ใช้ Python: %PYEXE%
echo.
%PYEXE% -m pip install --upgrade pip
%PYEXE% -m pip install pyusb pillow libusb-package
echo.
echo ============================================
echo  เสร็จแล้ว!
echo  ขั้นต่อไป: ลงไดรเวอร์ USB ของเครื่องปริ้นด้วย Zadig
echo  (อ่าน README-Windows.txt ข้อ 3)
echo ============================================
pause
