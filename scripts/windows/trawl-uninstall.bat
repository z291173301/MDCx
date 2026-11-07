@echo off
rem Self respawn through a fresh cmd process AFTER switching the console to
rem UTF-8, so the whole file below (which contains CJK text) is always parsed
rem with code page 65001. A batch file is decoded with the console code page
rem captured when its cmd process starts; parsing UTF-8 bytes as GBK (936)
rem corrupts CJK lines into bogus commands. This ASCII-only stub is immune to
rem that and guarantees clean parsing on any system default code page.
rem (This stub only EVER runs before anything is deleted: the destructive work
rem happens detached in a TEMP copy, minutes later. Exit-code fidelity here is
rem not critical; the worker reports its own result in the same window.)
if /i "%~1"=="u8" goto :u8ready
chcp 65001 >nul
cmd /d /c "%~f0" u8 %*
exit /b %errorlevel%
:u8ready
shift /1
setlocal enabledelayedexpansion
chcp 65001 >nul

rem ============================================================
rem  trawl-uninstall.bat —— TRAWL 便携包一键彻底删除
rem  解开即用，用完即删。用法：双击本文件。
rem
rem  设计说明（Windows 批处理的坑，勿“优化”掉）：
rem  cmd 是一行一行读脚本文件的。本脚本最终要删掉自己所在的整个目录，
rem  此后任何再读本文件的动作都会报“找不到指定路径”并把退出码搞成 1。
rem  因此：本文件只做“复制自身到 TEMP + 脱离启动 worker + 立刻退出”，
rem  所有耗时/删除动作都在 TEMP 副本里做（TEMP 副本删的是目标目录，
rem  不是自己，全程可读）。本文件的每一行都在删除发生前执行完毕。
rem
rem  覆盖的删不掉场景：
rem    1) 相关进程还活着（API bun / Camoufox / Redis :6380）占着文件句柄；
rem    2) 解压出来的只读/隐藏/系统属性导致“拒绝访问”；
rem    3) node_modules 这类超 260 字符的长路径（资源管理器删不动，
rem       还会显示“文件已删光但目录删不掉”）——用 robocopy 空目录镜像压平；
rem    4) 外部程序把该目录当工作目录（开着的终端/资源管理器窗口、杀毒扫描）
rem       ——3 次重试后注册系统重启删除，重启后自动消失。
rem  停止逻辑不依赖包内其它文件，即使 trawl-close.bat 已被手动删掉照样能停干净。
rem ============================================================

if /i "%~1"=="worker" goto :worker

set "TARGET=%~dp0"
rem 去掉末尾反斜杠，但别把盘符根目录（如 D:\）截成 D:
if "%TARGET:~-1%"=="\" set "TARGET=%TARGET:~0,-1%"
if "%TARGET:~-1%"==":" set "TARGET=%TARGET%\"

if not exist "%TARGET%" (
    echo [INFO] 目录已不存在，无需删除：%TARGET%
    pause
    exit /b 0
)

rem 正常路径：复制自身到 TEMP，脱离启动 worker，本进程立刻退出。
rem worker 是 start 出去的（不等它），6 秒左右后才真正动手删除；
rem 本进程毫秒级退出，绝不会读到被删掉的文件。
set "SELFCP=%TEMP%\trawl-uninstall-%RANDOM%%RANDOM%.bat"
copy /y "%~f0" "%SELFCP%" >nul 2>&1
if errorlevel 1 (
    echo [ERROR] 无法复制自身到 TEMP，退出。
    pause
    exit /b 1
)
rem 必须先切走当前目录：若本进程正站在目标目录里，cwd 句柄会锁住它。
cd /d "%TEMP%"
echo [INFO] 正在新窗口中启动清理（停止相关进程并删除目录），请在新窗口查看进度...
echo [INFO] 本窗口马上关闭，不影响清理继续执行。
rem 新开独立窗口跑 worker（不用 /b 同窗口）：本进程立刻退出，worker 全程读写
rem TEMP 副本；目标目录是 worker 在数秒后才删，此时本进程早已不在读原文件。
rem （实测结论：子进程结束后父进程再读原文件必报“找不到指定路径”，
rem  所以这里绝不等 worker，自己先退。）
start "" cmd /d /s /c ""%SELFCP%" u8 worker "%TARGET%""
exit /b 0

:worker
rem ============================================================
rem  worker：运行在 TEMP 副本里（%~f0 是 TEMP 路径），删的是 TARGET。
rem  全程只读 TEMP 文件；TEMP 文件到最后才由自己收尾，不影响任何读取。
rem ============================================================
set "TARGET=%~2"
if not defined TARGET (
    echo [ERROR] 缺少目标目录参数。
    pause
    exit /b 1
)
if not exist "%TARGET%" (
    echo [INFO] 目录已不存在，无需删除：%TARGET%
    call :SelfDel
    pause
    exit /b 0
)
title TRAWL - Uninstall

echo ========================================
echo   TRAWL - 一键彻底删除
echo   目标: %TARGET%
echo ========================================
echo.
echo [提示] 请先关闭指向该目录的资源管理器窗口和终端，
echo [提示] 否则最后一步可能需要重启电脑才完成。
echo.

rem 让启动器进程先退干净（毫秒级的事，这里等 3 秒，留足余量）。
ping -n 4 127.0.0.1 >nul

rem ---------- 1/4 停进程（本进程 cwd 在 TEMP，不会锁住目标目录） ----------
echo [1/4] 正在停止 TRAWL 相关进程...
rem API：只杀命令行含 trawl/index.ts 的 bun，避免误杀用户自己的 bun
powershell -NoProfile -ExecutionPolicy Bypass -Command "Get-CimInstance Win32_Process -Filter 'Name = ''bun.exe''' | Where-Object { $_.CommandLine -like '*index.ts*' -or $_.CommandLine -like '*trawl*' -or $_.CommandLine -like '*apps\api*' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }" >nul 2>&1
rem Camoufox 浏览器进程族（camoufox.exe / private_browsing.exe / nmhproxy.exe
rem 只属于 Camoufox；plugin-container.exe 与 Firefox 重名，必须按命令行过滤，
rem 不可 blanket 结束，否则会误杀用户自己的 Firefox）
taskkill /F /IM camoufox.exe >nul 2>&1
taskkill /F /IM private_browsing.exe >nul 2>&1
taskkill /F /IM nmhproxy.exe >nul 2>&1
powershell -NoProfile -ExecutionPolicy Bypass -Command "$names = @('plugin-container.exe','firefox.exe'); Get-CimInstance Win32_Process | Where-Object { $names -contains $_.Name -and $_.CommandLine -like '*camoufox*' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }" >nul 2>&1
rem 内置 Redis：只认 --port 6380，避免误杀用户自建的 Redis
powershell -NoProfile -ExecutionPolicy Bypass -Command "Get-CimInstance Win32_Process -Filter 'Name = ''redis-server.exe''' | Where-Object { $_.CommandLine -like '*6380*' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }" >nul 2>&1
rem 按端口兜底（仅白名单进程名才结束）
call :KillPort 8191
call :KillPort 8192
call :KillPort 6380
echo        进程已停，等待残留句柄释放...
ping -n 3 127.0.0.1 >nul
echo        完成。

rem ---------- 2/4 去属性（只读文件直接删会“拒绝访问”） ----------
echo [2/4] 正在清除只读/隐藏/系统属性...
attrib -R -H -S "%TARGET%\*.*" /S /D >nul 2>&1
echo        完成。

rem ---------- 3/4 删除（robocopy 空镜像对付超长路径，重试 3 次） ----------
echo [3/4] 正在删除目录...
set "EMPTYDIR=%TEMP%\trawl-empty-%RANDOM%%RANDOM%"
mkdir "%EMPTYDIR%" >nul 2>&1
set "DEL_OK=0"
for /L %%I in (1,1,3) do (
    if exist "%TARGET%" (
        rem 先用空目录镜像把长路径压平（rmdir/del 对超 260 字符路径无能为力），再删顶层
        robocopy "%EMPTYDIR%" "%TARGET%" /MIR /NFL /NDL /NJH /NJS >nul 2>&1
        rmdir /S /Q "%TARGET%" >nul 2>&1
        if not exist "%TARGET%" set "DEL_OK=1"
        if exist "%TARGET%" ping -n 3 127.0.0.1 >nul
    ) else (
        set "DEL_OK=1"
    )
)
rmdir /S /Q "%EMPTYDIR%" >nul 2>&1
if "%DEL_OK%"=="1" (
    echo.
    echo [DONE] 已彻底删除：%TARGET%
    call :SelfDel
    pause
    exit /b 0
)

rem ---------- 4/4 删不动：注册重启删除 ----------
echo.
echo [4/4] 目录仍被占用（通常是有终端/资源管理器窗口正停在该目录里，
echo        或杀毒软件正在扫描）。现注册系统重启时删除：
powershell -NoProfile -ExecutionPolicy Bypass -Command "Add-Type -Namespace Win32 -Name Mv -MemberDefinition '[System.Runtime.InteropServices.DllImport(\"kernel32.dll\", CharSet=CharSet.Unicode, SetLastError=true)] public static extern bool MoveFileEx(string a, string b, int f);'; if (-not [Win32.Mv]::MoveFileEx('%TARGET%', $null, 4)) { exit 1 }" >nul 2>&1
if errorlevel 1 (
    echo [ERROR] 注册重启删除失败（需要管理员权限）。
    echo [ERROR] 请关闭所有指向该目录的窗口后，右键本脚本“以管理员身份运行”再试一次。
    call :SelfDel
    pause
    exit /b 1
)
echo [DONE] 已注册重启删除：请重启电脑，重启后该目录会自动消失。
call :SelfDel
pause
exit /b 0

rem ---------- 子程序：收尾 TEMP 副本（脱离再删自己，本文件读完才执行，无影响） ----------
:SelfDel
start "" /b powershell -NoProfile -WindowStyle Hidden -Command "Start-Sleep 2; Remove-Item -LiteralPath '%~f0' -Force -ErrorAction SilentlyContinue" >nul 2>&1
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
exit /b 0
:DoKillPid
taskkill /F /PID %KPid% >nul 2>&1
exit /b 0
