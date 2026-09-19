@echo off
REM ============================================================
REM  local-ops 一体化启动脚本 (Windows)
REM ------------------------------------------------------------
REM  架构说明（重要）：
REM    后端 FastAPI (backend\run.py) 会"同源托管" frontend/ 目录，
REM    即一个进程同时提供 API (/api/*) 与前端页面 (/)。前端 api.js
REM    采用同源调用 (API_BASE="")，后端刻意禁用 CORS，因此：
REM      - 启动后端 = 前后端同时启动且可真实通信（唯一正确形态）
REM      - 单独再起一个 8080 前端会退化成"演示模式"，无法与后端通信
REM    所以本脚本默认只启动后端；如需独立 UI 预览，加 --preview。
REM
REM  用法：
REM    start.bat                        启动后端(同源托管前端)并自动打开浏览器
REM    start.bat --no-browser           不自动打开浏览器
REM    start.bat --preferred-port 9731  指定首选端口(被占用则自动回退空闲端口)
REM    start.bat --data-dir D:/x        指定数据目录
REM    start.bat --preview              额外启动独立前端预览(8080, 演示模式/不与后端通信)
REM ============================================================
setlocal EnableDelayedExpansion
cd /d "%~dp0"

REM --- 选定 Python 解释器（优先项目虚拟环境）---
set "USE_VENV=0"
if exist "backend\venv\Scripts\activate.bat" (
    set "USE_VENV=1"
    echo [local-ops] 检测到 backend\venv，将激活虚拟环境
) else (
    echo [local-ops] 未检测到 backend\venv，回退到系统 PATH 中的 python
)

REM --- 解析可选 --preview 开关（独立前端预览，演示模式）---
set "PREVIEW=0"
set "ARGS="
:parse_args
if "%~1"=="" goto :done_args
if /i "%~1"=="--preview" (
    set "PREVIEW=1"
) else (
    set "ARGS=!ARGS! %~1"
)
shift
goto :parse_args
:done_args

REM --- 可选：独立前端预览（8080，仅本地 UI 预览，演示模式，不与后端通信）---
if "%PREVIEW%"=="1" (
    echo [local-ops] 启动独立前端预览 (8080, 演示模式)...
    pushd "%~dp0frontend"
    start "local-ops 前端预览(8080)" cmd /k "python serve.py 8080"
    popd
)

REM --- 启动后端（同源托管前端，作为协同主实例）---
echo [local-ops] 启动后端 (FastAPI, 同源托管 frontend/)...
cd /d "%~dp0backend"
if "%USE_VENV%"=="1" call "venv\Scripts\activate.bat"
python run.py %ARGS%

endlocal
