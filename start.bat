@echo off
chcp 65001 >nul
setlocal enabledelayedexpansion
REM ============================================================================
REM  VOC Radar 评论雷达 —— Windows 一键启动脚本
REM
REM  用法：
REM      双击本文件即可，或命令行执行：  start.bat
REM      不自动打开浏览器：              start.bat --no-browser
REM
REM  重要（架构说明）：
REM      后端 FastAPI 只有一个端口，就同时提供两种服务——
REM          /            → 前端页面（backend/app/main.py 用 StaticFiles 挂载）
REM          /api/v1/...  → 后端 API（frontend/js/api.js 用相对路径调用）
REM      所以【不需要】再单独启动前端静态服务器。
REM      旧文档中"后端 8080 + 前端 python -m http.server 8080"的写法是错误的，
REM      两个进程抢同一个端口会冲突，且与本项目实际架构不符。
REM
REM  改端口：修改下面 PORT 变量即可（同时改这一处就够了）。
REM ============================================================================

REM ---------- 可配置区 ----------
set "PORT=8000"
set "HOST=127.0.0.1"
set "APP_MODULE=app.main:app"

REM ---------- 路径推导（%~dp0 为本脚本所在目录，末尾带反斜杠） ----------
set "ROOT=%~dp0"
set "VENV_PY=%ROOT%.venv\Scripts\python.exe"
set "BACKEND_DIR=%ROOT%backend"
set "FRONTEND_DIR=%ROOT%frontend"
set "ENV_FILE=%BACKEND_DIR%\.env"
set "REQ_FILE=%BACKEND_DIR%\requirements.txt"

REM ---------- 浏览器开关 ----------
set "OPEN_BROWSER=1"
if /i "%~1"=="--no-browser" set "OPEN_BROWSER=0"

echo.
echo ============================================================================
echo   VOC Radar 评论雷达 —— 一键启动
echo ============================================================================
echo.

REM ============================================================================
REM  第一步：环境自检
REM ============================================================================
echo [1/4] 环境自检 ...

REM --- 1.1 虚拟环境 ---
if not exist "%VENV_PY%" (
    echo        [失败] 找不到虚拟环境：%VENV_PY%
    echo.
    echo        请先创建虚拟环境并安装依赖（在项目根目录执行）：
    echo            python -m venv .venv
    echo            .venv\Scripts\python.exe -m pip install -r backend\requirements.txt
    echo.
    goto :fail
)
echo        [通过] 虚拟环境：%VENV_PY%

REM --- 1.2 backend 目录 ---
if not exist "%BACKEND_DIR%" (
    echo        [失败] 找不到 backend 目录：%BACKEND_DIR%
    goto :fail
)
echo        [通过] 后端目录：%BACKEND_DIR%

REM --- 1.3 frontend 目录（缺失则只能以纯 API 模式运行） ---
if not exist "%FRONTEND_DIR%" (
    echo        [警告] 找不到 frontend 目录：%FRONTEND_DIR%
    echo               将以纯 API 模式启动，浏览器看不到界面。
) else (
    echo        [通过] 前端目录：%FRONTEND_DIR%
)

REM --- 1.4 .env 文件与 API Key（缺失时降级为「无 Key 演示模式」，不阻断启动） ---
REM     浏览已有分析结果与内置 Demo 不需要 Key；只有触发新的 Pipeline 分析才需要。
set "KEYLESS=1"
if not exist "%ENV_FILE%" (
    echo        [警告] 找不到配置文件：%ENV_FILE%
    echo               将以「无 Key 演示模式」启动：可浏览已有分析结果，无法触发新分析。
    echo               如需完整功能，请先执行：
    echo                   copy backend\.env.example backend\.env   并填入 API Key
    echo.
    goto :env_key_done
)
echo        [通过] 配置文件：%ENV_FILE%

set "API_KEY_VALUE="
for /f "usebackq tokens=1,* delims==" %%A in (`findstr /b /c:"MODEL_ROUTER_API_KEY=" "%ENV_FILE%"`) do (
    set "API_KEY_VALUE=%%B"
)
REM 去掉可能存在的行尾空格
if defined API_KEY_VALUE (
    for /f "tokens=* delims= " %%Z in ("!API_KEY_VALUE!") do set "API_KEY_VALUE=%%Z"
)

if not defined API_KEY_VALUE (
    echo        [警告] .env 里没有配置 MODEL_ROUTER_API_KEY。
    echo               将以「无 Key 演示模式」启动：可浏览已有分析结果，无法触发新分析。
    echo.
    goto :env_key_done
)
echo "!API_KEY_VALUE!" | findstr /i /c:"your-personal" /c:"your-key" /c:"changeme" >nul
if not errorlevel 1 (
    echo        [警告] .env 里的 MODEL_ROUTER_API_KEY 仍是模板占位值。
    echo               将以「无 Key 演示模式」启动；请替换为真实 Key 以启用完整分析。
    echo.
    goto :env_key_done
)
set "KEYLESS=0"
echo        [通过] API Key 已配置（Key 内容不在此打印）

:env_key_done

REM --- 1.5 uvicorn 是否已安装 ---
"%VENV_PY%" -c "import uvicorn" >nul 2>&1
if errorlevel 1 (
    echo        [失败] 虚拟环境里缺少 uvicorn。
    echo               请执行：.venv\Scripts\python.exe -m pip install -r backend\requirements.txt
    goto :fail
)
echo        [通过] 依赖检查：uvicorn 可用

REM --- 1.6 端口占用提示（仅警告，不阻断） ---
netstat -ano | findstr /c:":%PORT% " | findstr /i /c:"LISTENING" >nul
if not errorlevel 1 (
    echo        [警告] 端口 %PORT% 已被其他程序占用，启动可能失败。
    echo               如需换端口，请用记事本打开 start.bat 修改 set "PORT=8000" 这一行。
)

echo        [完成] 环境自检全部通过
echo.

REM ============================================================================
REM  第二步：打印访问说明
REM ============================================================================
echo [2/4] 启动参数
echo        监听地址：http://%HOST%:%PORT%
echo        应用模块：%APP_MODULE%
echo        工作目录：%BACKEND_DIR%
echo.
echo        单端口说明：该端口同时提供 API（/api/v1）与前端页面（/），
echo                    无需另起前端服务，也请不要再用 python -m http.server。
if "%KEYLESS%"=="1" (
    echo        运行模式：无 Key 演示 —— 可浏览已有分析结果与内置 Demo；
    echo                   触发新的 Pipeline 分析需要配置 API Key（见上方提示）。
)
echo.

REM ============================================================================
REM  第三步：延迟打开浏览器（等 uvicorn 起来后再打开，避免"无法访问"）
REM ============================================================================
if "%OPEN_BROWSER%"=="1" (
    echo [3/4] 将在服务启动约 5 秒后自动打开浏览器 ...
    start "VOC-Radar-Browser" /min "%VENV_PY%" -c "import time, webbrowser; time.sleep(5); webbrowser.open('http://%HOST%:%PORT%/')"
) else (
    echo [3/4] 已跳过自动打开浏览器（--no-browser）
)
echo.

REM ============================================================================
REM  第四步：启动服务（前台运行，Ctrl+C 或关闭窗口即停止）
REM ============================================================================
echo [4/4] 启动 VOC Radar 服务（关闭本窗口或按 Ctrl+C 即停止）
echo ----------------------------------------------------------------------------
echo.

cd /d "%BACKEND_DIR%"
"%VENV_PY%" -m uvicorn %APP_MODULE% --host %HOST% --port %PORT%

set "EXIT_CODE=%ERRORLEVEL%"

echo.
echo ----------------------------------------------------------------------------
if not "%EXIT_CODE%"=="0" (
    echo   服务已退出，退出码：%EXIT_CODE%
    echo.
    echo   常见原因与处理：
    echo     1. 端口 %PORT% 被占用 —— 修改 start.bat 里的 PORT 变量后重试；
    echo     2. 依赖缺失          —— 运行 .venv\Scripts\python.exe -m pip install -r backend\requirements.txt
    echo     3. .env 配置错误     —— 运行 .venv\Scripts\python.exe backend\check_models.py 检查模型与 Key；
    echo     4. 需要在 backend 目录下手动跑，请看上方 Python 报错堆栈定位。
    echo.
    goto :fail
)
echo   服务已正常停止。
echo.
pause
exit /b 0

:fail
echo ----------------------------------------------------------------------------
echo   启动失败，请按上方提示处理后重新运行本脚本。
echo ----------------------------------------------------------------------------
echo.
pause
exit /b 1
