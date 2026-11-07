@echo off
rem Self respawn through a fresh cmd process AFTER switching the console to
rem UTF-8, so the whole file below (which contains CJK text) is always parsed
rem with code page 65001. A batch file is decoded with the console code page
rem captured when its cmd process starts; parsing UTF-8 bytes as GBK (936)
rem corrupts CJK lines into bogus commands. This ASCII-only stub is immune to
rem that and guarantees clean parsing on any system default code page.
if /i "%~1"=="u8" goto :u8ready
chcp 65001 >nul
cmd /d /c "%~f0" u8 %*
exit /b %errorlevel%
:u8ready
shift /1
setlocal enabledelayedexpansion
chcp 65001 >nul
title TRAWL - Close

rem ============================================================
rem  trawl-close.bat
rem  一键关闭 start-trawl.bat 启动的全部进程：
rem    1) TRAWL API      - bun.exe 运行 apps\api\src\index.ts (端口 8191，MITM 8192)
rem    2) Camoufox 浏览器 - .cache\camoufox\camoufox.exe 及其子进程
rem                        (plugin-container.exe / private_browsing.exe / nmhproxy.exe)
rem    3) 内置 Redis      - redis\redis-server.exe (端口 6380)
rem  需要管理员权限：若当前不是管理员，会自动请求提权后重新运行自己。
rem  由 trawl-close.vbs 以隐藏窗口 + 提权方式调用时，请带 hidden 参数
rem  （跳过末尾 pause，避免隐藏窗口卡住不退出）。
rem ============================================================

rem ---------- 管理员权限自检，未提权则 relaunch ----------
net session >nul 2>&1
if %errorlevel% neq 0 (
    echo [INFO] 需要管理员权限，正在请求提权...
    if "%~1"=="" (
        powershell -NoProfile -ExecutionPolicy Bypass -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
    ) else (
        powershell -NoProfile -ExecutionPolicy Bypass -Command "Start-Process -FilePath '%~f0' -ArgumentList '%*' -Verb RunAs"
    )
    if errorlevel 1 (
        echo [WARN] 提权失败或 UAC 已取消。请右键本脚本选择“以管理员身份运行”。
        if /i not "%~1"=="hidden" pause
    )
    exit /b
)

cd /d "%~dp0"

echo ========================================
echo   TRAWL - 一键关闭
echo ========================================
echo.

rem ---------- 1/5 关闭 TRAWL API (bun，只杀命令行含 trawl/index.ts 的进程，避免误杀) ----------
echo [1/5] 正在关闭 TRAWL API (bun, 端口 8191/8192)...
powershell -NoProfile -ExecutionPolicy Bypass -Command "Get-CimInstance Win32_Process -Filter 'Name = ''bun.exe''' | Where-Object { $_.CommandLine -like '*index.ts*' -or $_.CommandLine -like '*trawl*' -or $_.CommandLine -like '*apps\api*' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }"
echo        完成。

rem ---------- 2/5 关闭 Camoufox 浏览器进程族 (命令行含 camoufox 才杀，避免误杀用户自己的 Firefox) ----------
echo [2/5] 正在关闭 Camoufox 浏览器进程...
powershell -NoProfile -ExecutionPolicy Bypass -Command "$names = @('camoufox.exe','plugin-container.exe','private_browsing.exe','nmhproxy.exe','firefox.exe'); Get-CimInstance Win32_Process | Where-Object { $names -contains $_.Name -and $_.CommandLine -like '*camoufox*' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }"
rem 兜底：按镜像名直接结束 camoufox 主进程（该名字只属于 Camoufox，不会误伤 Firefox）
taskkill /F /IM camoufox.exe >nul 2>&1
echo        完成。

rem ---------- 3/5 关闭内置 Redis（只认 --port 6380，避免误杀用户自建的 Redis） ----------
echo [3/5] 正在关闭 Redis (端口 6380)...
powershell -NoProfile -ExecutionPolicy Bypass -Command "Get-CimInstance Win32_Process -Filter 'Name = ''redis-server.exe''' | Where-Object { $_.CommandLine -like '*6380*' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }"
rem 故意不用 taskkill /IM blanket 结束：用户自建的 Redis（如默认 6379）不应被波及。
rem 若 PowerShell 不可用，后续步骤 4 会按端口 6380 兜底（带进程名白名单）。
echo        完成。

rem ---------- 4/5 按端口兜底：占用 8191 / 8192 / 6380 的残留进程（仅白名单内进程名才结束） ----------
echo [4/5] 正在清理残留端口占用 (8191 / 8192 / 6380)...
call :KillPort 8191
call :KillPort 8192
call :KillPort 6380
echo        完成。

rem ---------- 5/5 按窗口标题兜底（可见窗口启动的 TRAWL-Redis / TRAWL 控制台） ----------
echo [5/5] 正在关闭残留控制台窗口...
rem 必须精确匹配：TRAWL* 通配会误杀本脚本自己的窗口（标题为 TRAWL - Close）
taskkill /F /FI "WINDOWTITLE eq TRAWL-Redis" >nul 2>&1
taskkill /F /FI "WINDOWTITLE eq TRAWL - Cloudflare Bypass" >nul 2>&1
echo        完成。

echo.
echo ---------- 检查结果 ----------
call :CheckPort 8191 "API"
call :CheckPort 8192 "MITM"
call :CheckPort 6380 "Redis"
echo.
echo [DONE] 关闭流程执行完毕。如端口仍被占用，请用 netstat -ano ^| findstr :端口 查看 PID 后手动处理。
if /i "%~1"=="hidden" (
    endlocal
    exit /b 0
)
pause
endlocal
exit /b 0

rem ---------- 子程序：结束监听指定端口的进程 ----------
:KillPort
set "KPORT=%~1"
for /f "tokens=5" %%P in ('netstat -ano ^| findstr /R /C:":%KPORT% .*LISTENING"') do (
    if not "%%P"=="0" (
        if not "%%P"=="4" (
            call :KillPid %%P
        )
    )
)
exit /b 0

rem ---------- 子程序：按 PID 结束进程（带进程名白名单，防止误杀占用同端口的其它软件） ----------
:KillPid
set "KPid=%~1"
set "KName=?"
for /f "tokens=1 delims=," %%N in ('tasklist /FI "PID eq %KPid%" /NH /FO CSV 2^>nul') do set "KName=%%~N"
if /i "%KName%"=="bun.exe" goto :DoKillPid
if /i "%KName%"=="node.exe" goto :DoKillPid
if /i "%KName%"=="python.exe" goto :DoKillPid
if /i "%KName%"=="pythonw.exe" goto :DoKillPid
if /i "%KName%"=="redis-server.exe" goto :DoKillPid
if /i "%KName%"=="camoufox.exe" goto :DoKillPid
if /i "%KName%"=="firefox.exe" goto :DoKillPid
if /i "%KName%"=="plugin-container.exe" goto :DoKillPid
if /i "%KName%"=="private_browsing.exe" goto :DoKillPid
if /i "%KName%"=="nmhproxy.exe" goto :DoKillPid
echo [INFO] 跳过非 TRAWL 进程：[%KName%] PID %KPid%
exit /b 0
:DoKillPid
taskkill /F /PID %KPid% >nul 2>&1
exit /b 0

rem ---------- 子程序：检查端口是否已释放 ----------
:CheckPort
set "CPORT=%~1"
set "CNAME=%~2"
netstat -ano | findstr /R /C:":%CPORT% .*LISTENING" >nul 2>&1
if %errorlevel%==0 (
    echo [WARN] 端口 %CPORT% / %CNAME% 仍被占用。
) else (
    echo [OK]   端口 %CPORT% / %CNAME% 已释放。
)
exit /b 0
