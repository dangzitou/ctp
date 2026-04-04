@echo off
chcp 65001 >nul
title CTP 全量行情客户端
echo ==========================================
echo   CTP 全量期货行情 (279合约)
echo ==========================================
echo.

REM ====== 1. 检查 Java ======
where java >nul 2>&1
if %errorlevel% neq 0 (
    echo [错误] 未找到 Java，请先安装 JDK 17+
    echo 下载: https://adoptium.net/
    pause
    exit /b 1
)
java -version 2>nul | findstr "version" >nul
echo [OK] Java:& java -version 2>nul | findstr /i "version"

REM ====== 2. 启动 md_server ======
echo.
echo [1] 启动行情服务(后台)...
echo    SimNow: tcp://182.254.243.31:40011
echo    订阅: 279合约 (SHFE/DCE/CZCE/CFFEX/INE)
echo.

REM 找到 python
where py >nul 2>&1 && set PY=py || set PY=python

REM 启动 md_server (它会自动登录并订阅所有合约)
start "md_server" cmd /c "cd /d E:\Develop\projects\ctp\runtime\md_simnow && %PY% -u md_server.py 19842"

echo     等待md_server启动 (5秒)...
timeout /t 5 /nobreak >nul

REM 检查端口
netstat -an | findstr ":19842.*ESTABLISHED" >nul
if %errorlevel%==0 (
    echo [OK] md_server 已连接，已订阅279合约
) else (
    echo [警告] 无法确认md_server状态，继续...
)

REM ====== 3. 启动 Java 客户端 ======
echo.
echo [2] 启动Java客户端(全量279合约行情)...
echo ----------------------------------------
echo   Ctrl+C 退出
echo ----------------------------------------
echo.
java -jar "E:\Develop\projects\ctp\java_ctp_md\MdServerClient.jar"

pause
