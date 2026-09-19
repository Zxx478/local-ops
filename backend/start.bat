@echo off
REM local-ops 后端启动脚本（Windows）
cd /d "%~dp0"
python run.py %*
