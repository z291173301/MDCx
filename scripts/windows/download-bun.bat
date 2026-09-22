@echo off
chcp 65001 >nul
title TRAWL - 下载 Bun

echo ========================================
echo   TRAWL - 下载 Bun 运行时
echo ========================================
echo.

cd /d "%~dp0"

:: 创建 bun 目录
if not exist "bun" mkdir bun
cd bun

:: 检测系统架构
set ARCH=x64
if "%PROCESSOR_ARCHITECTURE%"=="ARM64" set ARCH=arm64

echo [INFO] 检测到架构: %ARCH%
echo [INFO] 正在下载 Bun...
echo.

:: 下载 Bun (尝试多个源)
:: 注意：此处为手动兜底脚本的固定版本，与 package-trawl.yml 动态取的 bun 版本可能不同步；如需一致请手动对齐
set BUN_VERSION=1.3.9
set URL=https://github.com/oven-sh/bun/releases/download/bun-v%BUN_VERSION%/bun-windows-%ARCH%.zip

echo [1/3] 下载 Bun %BUN_VERSION%...
powershell -Command "Invoke-WebRequest -Uri '%URL%' -OutFile 'bun.zip' -UseBasicParsing"
if errorlevel 1 (
    echo [WARN] 主源下载失败，尝试备用源...
    set URL=https://github.com/nicolo-ribaudo/bun/releases/download/bun-v%BUN_VERSION%/bun-windows-%ARCH%.zip
    powershell -Command "Invoke-WebRequest -Uri '%URL%' -OutFile 'bun.zip' -UseBasicParsing"
)

if not exist "bun.zip" (
    echo [ERROR] 下载失败
    pause
    exit /b 1
)

echo [2/3] 解压...
powershell -Command "Expand-Archive -Path 'bun.zip' -DestinationPath '.' -Force"
del bun.zip

:: 扁平化：bun-windows-x64.zip 解压后是 bun-windows-x64\bun.exe，
:: 提到 bun/ 根目录，与 start-trawl.bat 的 bun\bun.exe 检测路径一致
if not exist "bun.exe" (
    for /d %%D in ("bun-windows-*") do (
        if exist "%%D\bun.exe" move "%%D\bun.exe" "." >nul 2>&1
    )
)

echo [3/3] 验证...
if exist "bun.exe" (
    echo.
    echo [SUCCESS] Bun 安装完成!
    bun.exe --version
) else (
    echo [ERROR] 验证失败，未找到 bun.exe
)

echo.
echo 现在可以运行 start-trawl.bat 启动服务
pause
