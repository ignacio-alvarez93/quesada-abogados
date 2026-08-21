@echo off
setlocal

cd /d "%~dp0\..\.."

set "PYTHONPATH=%CD%"
set "PYTHONIOENCODING=utf-8"
set "PYTHONUTF8=1"

echo ======================================================
echo  ICP PLUS SCHEDULER WORKER
echo ======================================================

python scripts\icpplus_scheduler_worker.py

endlocal
