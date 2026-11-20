@echo off
REM Pharmacy Enterprise v6.6 — launcher for Windows
REM Verified launcher on this PC is `py` (Python 3.11.2 via the py launcher).
REM `python` is NOT on PATH here, so there is no fallback to it:
REM falling through to `python` only showed the confusing
REM "Python was not found / Microsoft Store" message.
REM Stdlib only — no venv, no pip install needed.
cd /d "%~dp0"
py main.py
if errorlevel 1 (
  echo.
  echo حدث خطأ اثناء التشغيل. راجع ملف error.log
  pause
)
