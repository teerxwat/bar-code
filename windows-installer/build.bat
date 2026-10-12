@echo off
rem Build the Windows installer. Run this on a Windows PC that has Python 3 and
rem Inno Setup 6 (https://jrsoftware.org/isdl.php) installed.
cd /d "%~dp0"
python -m pip install -r requirements.txt || goto :fail
python build_windows.py || goto :fail
echo.
pause
exit /b 0
:fail
echo.
echo *** BUILD FAILED ***
pause
exit /b 1
