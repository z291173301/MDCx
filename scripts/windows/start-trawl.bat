@echo off
setlocal enabledelayedexpansion
chcp 65001 >nul
title TRAWL - Cloudflare Bypass

echo ========================================
echo   TRAWL - Cloudflare Bypass Service
echo   Windows Portable Edition
echo ========================================
echo.

cd /d "%~dp0"

rem locate bun: support both bun\bun.exe and bun\bun-windows-x64\bun.exe layouts
set "BUN_EXE="
if exist "bun\bun.exe" (
    set "BUN_EXE=bun\bun.exe"
) else (
    for /d %%D in ("bun\bun-windows-*") do (
        if exist "%%D\bun.exe" set "BUN_EXE=%%D\bun.exe"
    )
)
if not defined BUN_EXE (
    echo [ERROR] 未找到 Bun，请先运行 download-bun.bat
    pause
    exit /b 1
)
echo [INFO] Bun: %BUN_EXE%

rem pick source: prefer bundled source at package root (patched at pack time, deps ready, fully offline);
rem src clone is only a fallback when root has no source (bare-script deploy), avoids first-run network hard dependency + version drift
set "SRC_DIR="
if exist "apps\api\src\index.ts" (
    set "SRC_DIR=."
    echo [INFO] 使用便携包自带源码
) else if exist "src\apps\api\src\index.ts" (
    set "SRC_DIR=src"
    echo [INFO] 使用 src\ 目录源码
) else (
    echo [INFO] 未发现源码，正在克隆上游仓库到 src\ ...
    git clone --depth 1 https://github.com/germondai/trawl.git src
    if errorlevel 1 (
        echo [ERROR] 克隆失败，请检查网络连接
        pause
        exit /b 1
    )
    set "SRC_DIR=src"
)

rem apply MDCx compat patch only for the src clone copy (raises Tier3/4 page-load timeout for challenge stability)
rem bundled root source was patched at pack time, skip
if "%SRC_DIR%"=="src" if exist "trawl-goto-timeout.patch" (
    cd /d "%~dp0src"
    git apply --check ..\trawl-goto-timeout.patch >nul 2>&1
    if not errorlevel 1 (
        echo [INFO] 应用 TRAWL goto 超时补丁...
        git apply ..\trawl-goto-timeout.patch
        if errorlevel 1 echo [WARN] 补丁应用失败，继续以原版运行
    ) else (
        echo [INFO] 补丁已应用或无法应用，跳过
    )
    cd /d "%~dp0"
)

rem verify/install deps inside the chosen source dir; bun installs per cwd package.json/bun.lock
rem wrong dir = not installed. Skip when node_modules already present (zip ships complete deps).
if exist "%SRC_DIR%\node_modules" (
    echo [INFO] 依赖已就绪，跳过安装
) else (
    echo [INFO] 正在安装依赖，请稍候（首次较慢）...
    pushd "%~dp0%SRC_DIR%"
    "%BUN_EXE%" install --frozen-lockfile --linker hoisted
    if errorlevel 1 (
        echo [WARN] frozen lockfile 安装失败，尝试普通安装...
        "%BUN_EXE%" install --linker hoisted
    )
    set "INSTALL_ERR=%errorlevel%"
    popd
    if not "%INSTALL_ERR%"=="0" (
        echo [ERROR] 依赖安装失败，请检查网络后重试
        pause
        exit /b 1
    )
)

rem env vars
set MITM_PROXY_ENABLED=false
set PORT=8191
rem browser pool default 2 (stability/memory tradeoff; override via BROWSER_POOL_SIZE in .env)
set BROWSER_POOL_SIZE=2
rem point camoufox-js at the bundled Camoufox to avoid online download
set CAMOUFOX_INSTALL_DIR=%~dp0.cache\camoufox

rem bundled Redis: auto-start for TRAWL session cache (Tier 2 fast-path)
rem locate redis-server.exe: support both redis\redis-server.exe and redis\Redis-*\redis-server.exe layouts
set "REDIS_EXE="
set REDIS_URL=
if exist "redis\redis-server.exe" (
    set "REDIS_EXE=redis\redis-server.exe"
) else (
    for /d %%D in ("redis\Redis-*") do (
        if exist "%%D\redis-server.exe" set "REDIS_EXE=%%D\redis-server.exe"
    )
)
if defined REDIS_EXE (
    echo [INFO] 检测到内置 Redis: %REDIS_EXE%，正在启动...
    start "TRAWL-Redis" /min "%~dp0%REDIS_EXE%" --port 6380 --save "" --appendonly no
    if not errorlevel 1 (
        set REDIS_URL=redis://127.0.0.1:6380
        echo [INFO] Redis 已启动，TRAWL 会话缓存已启用
    )
) else (
    echo [INFO] 未发现内置 Redis，TRAWL 将以无缓存模式运行
)
if defined REDIS_URL set REDIS_URL=redis://127.0.0.1:6380

echo.
echo [INFO] 服务启动中...
echo [INFO] API 地址: http://localhost:%PORT%
echo [INFO] 健康检查: http://localhost:%PORT%/health
echo.
echo [提示] 按 Ctrl+C 停止服务
echo.

rem start service (cwd stays at package root so bun reads root .env)
"%BUN_EXE%" run "%SRC_DIR%\apps\api\src\index.ts"

if errorlevel 1 (
    echo.
    echo [ERROR] 服务启动失败
    pause
)
